"""backup.py: a USB renamed in Finder, or a new USB that took over from an old one, carries on the old one's backups
(nothing goes up again); The Crate follows a renamed USB (usb_ask.follow).
python3 -m unittest test_backup_names"""
import os, tempfile, unittest
from unittest import mock

import backup, place, usb_ask


class Names(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        t = self.t.name
        self.dir, self.src, self.vol = os.path.join(t, "app"), os.path.join(t, "music"), os.path.join(t, "Volumes")
        for d in (self.dir, self.src):
            os.makedirs(d)
        self.usb = os.path.join(self.vol, "Lexar")
        self.put(self.usb, "PIONEER/rekordbox/export.pdb", b"x" * 300)
        self.put(self.usb, "From a friend/only here.mp3", b"ID3" + b"x" * 5000)
        self.cloud = mock.patch.multiple(backup, CLOUD=os.path.join(t, "no-icloud"), RESERVE=0)
        self.cloud.start()
        backup.save(self.dir, place="mac")

    def tearDown(self):
        self.cloud.stop()
        self.t.cleanup()

    def put(self, usb, rel, data):
        p = os.path.join(usb, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def allow(self, usb, i):  # what a yes on the page leaves on the stick (usb_ask.answer)
        os.makedirs(place.folder(usb), exist_ok=True)
        place.noted(place.folder(usb), i, [])

    def rename(self, new):
        to = os.path.join(self.vol, new)
        os.rename(self.usb, to)
        return to

    def log(self):
        with open(os.path.join(self.dir, "dj.log")) as f:
            return f.read()

    def test_renamed_usb_carries_on(self):
        self.allow(self.usb, "a" * 32)
        first = backup.run(self.dir, self.usb, self.src)
        dj = self.rename("DJ")
        self.put(dj, "PIONEER/rekordbox/export.pdb", b"y" * 400)  # the decks saved since
        self.assertEqual(backup.named(self.dir, dj), "Lexar")
        backup.run(self.dir, dj, self.src)
        self.assertEqual(backup.snaps(self.dir, "DJ"), [])  # no fresh start under the new name
        got = backup.snaps(self.dir, "Lexar")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[1]["id"], first["id"])
        self.assertIn('"DJ" (it was "Lexar") carries on its backups', self.log())
        st = backup.status(self.dir, dj)
        self.assertEqual(st["mine"], "Lexar")
        self.assertEqual([s["now"] for s in st["sticks"]], ["DJ"])
        # unplugged, the page still finds its backups by the name it has now
        self.assertEqual(backup.status(self.dir, os.path.join(self.vol, "DJ-gone"))["mine"], "DJ-gone")
        os.rename(dj, os.path.join(self.vol, "away"))
        self.assertEqual(backup.status(self.dir, dj)["mine"], "Lexar")

    def test_renamed_before_its_backups_knew_its_id(self):
        backup.run(self.dir, self.usb, self.src)  # (an older version: no id kept with the backups)
        i = "b" * 32
        self.allow(self.usb, i)
        usb_ask.save(self.dir, {i: {"yes": True, "kinds": usb_ask.KINDS, "name": "Lexar"}})
        dj = self.rename("DJ")
        self.assertEqual(backup.named(self.dir, dj), "Lexar")
        self.assertEqual(usb_ask.follow(self.dir, "Lexar", self.vol), "DJ")  # The Crate follows it first
        self.assertEqual(backup.named(self.dir, dj), "Lexar")  # ... and its backups still carry on

    def test_another_stick_with_a_new_name_starts_its_own(self):
        backup.run(self.dir, self.usb, self.src)
        other = os.path.join(self.vol, "Kingston")
        self.put(other, "PIONEER/rekordbox/export.pdb", b"k" * 100)
        self.allow(other, "c" * 32)
        self.assertEqual(backup.named(self.dir, other), "Kingston")

    def test_new_usb_takes_over_after_a_repair(self):
        got = backup.run(self.dir, self.usb, self.src)
        new = os.path.join(self.vol, "NewStick")
        os.makedirs(new)
        said = backup.restore(self.dir, new, self.src, "Lexar", got["id"])
        self.assertIn('carries on the backups of "Lexar"', said)
        self.assertEqual(backup.named(self.dir, new), "Lexar")  # (no id on it yet: known by its name)
        backup.run(self.dir, new, self.src)  # the same files: nothing new to keep, nothing goes up again
        self.assertEqual(len(backup.snaps(self.dir, "Lexar")), 1)
        self.assertEqual(backup.snaps(self.dir, "NewStick"), [])
        self.allow(new, "d" * 32)  # once allowed, known by its id, whatever it is called
        self.put(new, "PIONEER/rekordbox/export.pdb", b"z" * 500)
        backup.run(self.dir, new, self.src)
        self.assertEqual(backup.names(self.dir)["ids"].get("d" * 32), "Lexar")
        self.assertEqual(len(backup.snaps(self.dir, "Lexar")), 2)

    def test_a_usb_with_its_own_history_does_not_take_over(self):
        got = backup.run(self.dir, self.usb, self.src)
        mine = os.path.join(self.vol, "Mine")
        for n in range(2):
            self.put(mine, "PIONEER/rekordbox/export.pdb", b"m" * (100 + n))
            backup.run(self.dir, mine, self.src)
        said = backup.restore(self.dir, mine, self.src, "Lexar", got["id"])
        self.assertNotIn("carries on", said)
        self.assertEqual(backup.named(self.dir, mine), "Mine")

    def test_a_pass_left_with_the_old_path_is_taken_over(self):
        m = os.path.join(self.dir, ".backup-songs-" + backup.safe("Lexar"))
        dj = self.rename("DJ")
        for at, held in ((self.usb, False), (dj, True), (os.path.join(self.vol, "other"), False)):
            with open(m, "w") as f:
                f.write(f"{os.getpid()}\t{at}")
            self.assertEqual(backup.held(self.dir, "Lexar", dj), held, at)
        os.makedirs(os.path.join(self.vol, "other"))  # (a path still there: that pass is still at work)
        self.assertTrue(backup.held(self.dir, "Lexar", dj))
        with open(m, "w") as f:
            f.write(str(os.getpid()))  # (an older version's marker: just the pid)
        self.assertTrue(backup.held(self.dir, "Lexar", dj))


class Follow(unittest.TestCase):
    def test_follows_the_renamed_usb_by_its_id(self):
        with tempfile.TemporaryDirectory() as t:
            dir, vol = os.path.join(t, "app"), os.path.join(t, "Volumes")
            os.makedirs(dir)
            for name, i in (("DJ", "e" * 32), ("Friend", "f" * 32)):
                os.makedirs(os.path.join(vol, name, place.NAME))
                place.noted(os.path.join(vol, name, place.NAME), i, [])
            usb_ask.save(dir, {"e" * 32: {"yes": True, "name": "Lexar"}, "f" * 32: {"yes": True, "name": "Friend"}})
            self.assertEqual(usb_ask.follow(dir, "Lexar", vol), "DJ")
            self.assertEqual(usb_ask.load(dir)["e" * 32]["name"], "DJ")  # (so a second rename is followed too)
            self.assertEqual(usb_ask.follow(dir, "Kingston", vol), "")  # a stick never seen: nothing to follow


if __name__ == "__main__":
    unittest.main()
