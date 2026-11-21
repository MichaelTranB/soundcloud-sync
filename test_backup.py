"""backup.py: a lost or broken USB comes back from what this Mac (or iCloud Drive) kept of it.
python3 -m unittest test_backup"""
import json, os, shutil, sqlite3, tempfile, unittest
from unittest import mock

import backup


class Room(unittest.TestCase):
    """Songs pass through this Mac on their way to iCloud Drive: a Mac short of RESERVE still sends them, a batch at a
    time, and FLOOR always stays free."""

    def test_rules(self):
        G = 1024 ** 3
        with mock.patch.multiple(backup, RESERVE=20 * G, FLOOR=5 * G, THROUGH=2 * G):
            self.assertTrue(backup.fits(40 * G, G, 10 * G))  # plenty of room: no batch limit
            self.assertTrue(backup.fits(15 * G, G, 0))  # short of RESERVE, nothing waiting: it goes
            self.assertTrue(backup.fits(15 * G, G, G))  # ... and fills the batch
            self.assertFalse(backup.fits(15 * G, G, 1.5 * G))  # ... but no more than THROUGH waits here
            self.assertTrue(backup.fits(15 * G, 3 * G, 0))  # a song bigger than a batch still goes, alone
            self.assertFalse(backup.fits(5.5 * G, G, 0))  # FLOOR always stays free


class Default(unittest.TestCase):
    def test_icloud_when_on_else_mac(self):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.object(backup, "CLOUD", t):
                self.assertEqual(backup.load(t)["place"], "icloud")
            with mock.patch.object(backup, "CLOUD", os.path.join(t, "none")):
                self.assertEqual(backup.load(t)["place"], "mac")
                with open(os.path.join(t, backup.SET), "w") as f:
                    json.dump({"place": "own"}, f)
                self.assertEqual(backup.load(t)["place"], "own")  # a choice made stands


class Libraries(unittest.TestCase):
    """Only songs leave this Mac once in iCloud: the decks' libraries (small, but thousands of files iCloud hands back
    slowly) stay, so a repair takes minutes."""

    def test_only_songs_are_freed(self):
        asked = []
        def look(dir, paths, free=False):
            asked.append((sorted(os.path.basename(p) for p in paths), free))
            return {p: "u" for p in paths}
        rows = {"PIONEER/rekordbox/exportLibrary.db": [10, 1, "rekordbox", "d1"], "Mix/song.mp3": [20, 1, "song", "d1"]}
        with tempfile.TemporaryDirectory() as t, mock.patch.object(backup, "look", look):
            backup._ASKED.pop("Lexar", None)
            got = backup.tally(t, "Lexar", t, [{"id": "d1"}], {"d1": rows})
        self.assertIn((["song.mp3"], True), asked)
        self.assertIn((["exportLibrary.db"], False), asked)
        self.assertEqual(got["here"], 1)  # the song still waits to leave; the library is where it belongs


class Restore(unittest.TestCase):
    """A USB with its decks' libraries and a song only it has is backed up; a blank stick, even one with another
    name, gets all of it back."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        t = self.t.name
        self.dir, self.src, vol = os.path.join(t, "app"), os.path.join(t, "music"), os.path.join(t, "Volumes")
        for d in (self.dir, self.src):
            os.makedirs(d)
        self.usb, self.new = os.path.join(vol, "Lexar"), os.path.join(vol, "NewStick")
        os.makedirs(self.new)
        self.put("Engine Library/Database2/m.db", None)
        db = sqlite3.connect(os.path.join(self.usb, "Engine Library", "Database2", "m.db"))
        db.execute("CREATE TABLE Track (id INTEGER PRIMARY KEY, path TEXT)")
        db.execute("INSERT INTO Track (path) VALUES ('../SoundCloud Sync/a.mp3')")
        db.commit()
        db.close()
        self.put("PIONEER/USBANLZ/P01/0001/ANLZ0000.DAT", b"PMAI" + b"\0" * 60)  # rekordbox cues and grid
        self.put("From a friend/only here.mp3", b"ID3" + b"x" * 5000)  # a song this Mac doesn't have
        self.put("SoundCloud Sync/a.mp3", b"ID3" + b"a" * 4000)  # one it has: it comes back with the usual copy
        with open(os.path.join(self.src, "a.mp3"), "wb") as f:
            f.write(b"ID3" + b"a" * 4000)
        # (no iCloud Drive, and this Mac counts as roomy whatever this test machine has free)
        self.cloud = mock.patch.multiple(backup, CLOUD=os.path.join(t, "no-icloud"), RESERVE=0)
        self.cloud.start()

    def tearDown(self):
        self.cloud.stop()
        self.t.cleanup()

    def put(self, rel, data):
        p = os.path.join(self.usb, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if data is not None:
            with open(p, "wb") as f:
                f.write(data)

    def read(self, root, rel):
        with open(os.path.join(root, *rel.split("/")), "rb") as f:
            return f.read()

    def test_blank_stick_gets_it_all_back(self):
        backup.save(self.dir, place="mac")
        got = backup.run(self.dir, self.usb, self.src)
        self.assertTrue(got and got.get("ok", True))
        day = got["id"]
        said = backup.restore(self.dir, self.new, self.src, "Lexar", day)
        self.assertNotIn("PROBLEM", said)
        for rel in ("Engine Library/Database2/m.db", "PIONEER/USBANLZ/P01/0001/ANLZ0000.DAT", "From a friend/only here.mp3"):
            self.assertEqual(self.read(self.new, rel), self.read(self.usb, rel), rel)
        self.assertFalse(os.path.exists(os.path.join(self.new, "SoundCloud Sync", "a.mp3")))  # (usb.sh's copy)

    def test_icloud_off_keeps_the_libraries_on_this_mac(self):
        backup.save(self.dir, place="icloud")
        with mock.patch.object(backup, "cloud", return_value=""):
            got = backup.run(self.dir, self.usb, self.src)
        self.assertIn("iCloud Drive could not be opened", got.get("skipped", ""))
        files = backup.files_of(self.dir, "Lexar", got["id"])
        self.assertIn("Engine Library/Database2/m.db", files)  # the cues and playlists are kept at once
        self.assertNotIn("From a friend/only here.mp3", files)  # the songs wait for iCloud: this Mac keeps its room


if __name__ == "__main__":
    unittest.main()
