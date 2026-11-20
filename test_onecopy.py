"""Checks for "All songs" kept as one copy of each song (layout.onecopy, usb_ask.allow). Standard library only:

    python3 -m unittest test_onecopy

A made-up USB in a temp folder stands in: The Crate's folder with songs in their folders, an "All songs" folder of
copies, and an Engine DJ library. Nothing of yours is read or written."""
import json, os, shutil, sqlite3, tempfile, unittest

import layout, usb_ask

SONGS = {"EDM/a.mp3": b"A" * 5000, "Other/b.mp3": b"B" * 7000, "Spotify Liked Songs/c.mp3": b"C" * 3000,
         "d.mp3": b"D" * 4000}


class OneCopy(unittest.TestCase):
    def setUp(self):
        self.usb = tempfile.mkdtemp()
        self.dir = tempfile.mkdtemp()  # The Crate's own folder on the Mac (usb-ok.json, usb-layout.json)
        self.dest = os.path.join(self.usb, "SoundCloud Sync")
        for rel, data in SONGS.items():
            self.put(rel, data)
        home = os.path.join(self.dest, layout.ALL)
        for rel, data in SONGS.items():  # The Crate's copies: a, b, d the same; c the same size but other bytes
            self.put(os.path.join(layout.ALL, os.path.basename(rel)), b"X" * len(data) if "c.mp3" in rel else data)
        self.put(os.path.join(layout.ALL, "e.mp3"), b"E" * 100)  # a copy whose song left
        self.put(os.path.join(layout.ALL, "f.mp3"), b"F" * 100)  # someone else's: not in the stamp
        with open(os.path.join(home, layout.STAMP), "w") as f:
            json.dump({k: [1, 1, 1] for k in ("a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3")}, f)
        self.at = {os.path.basename(r): r for r in SONGS}
        self.engine(["../SoundCloud Sync/EDM/a.mp3", "../SoundCloud Sync/d.mp3"])
        self.cfg = {"mode": "group", "other": layout.OTHER, "all": True, "one": True}

    def tearDown(self):
        shutil.rmtree(self.usb), shutil.rmtree(self.dir)

    def put(self, rel, data):
        p = os.path.join(self.dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)

    def engine(self, paths):
        d = os.path.join(self.usb, "Engine Library", "Database2")
        os.makedirs(d, exist_ok=True)
        if os.path.exists(os.path.join(d, "m.db")):
            os.remove(os.path.join(d, "m.db"))
        c = sqlite3.connect(os.path.join(d, "m.db"))
        c.execute("CREATE TABLE Track (id INTEGER PRIMARY KEY, path TEXT)")
        c.executemany("INSERT INTO Track (path) VALUES (?)", [(p,) for p in paths])
        c.commit(), c.close()

    def all_songs(self):
        return sorted(f for f in os.listdir(os.path.join(self.dest, layout.ALL)) if not f.startswith("."))

    def originals(self):
        for rel, data in SONGS.items():
            with open(os.path.join(self.dest, rel), "rb") as f:
                self.assertEqual(f.read(), data, rel)

    def test_dry_run_counts_and_touches_nothing(self):
        before = self.all_songs()
        self.assertEqual(layout.doubles(self.dest, dry=True), (3, 2, 5000 + 7000 + 4000))
        out = layout.dry_run(self.dest)
        self.assertIn("songs kept (one copy each, in their own folders): 4", out)
        self.assertIn('doubles taken off "All songs" (same byte for byte as their twin): 3', out)
        self.assertIn("left in", out)
        self.assertEqual(self.all_songs(), before)
        self.assertFalse(os.path.exists(os.path.join(self.dest, layout.LIST)))

    def test_quick_look_weighs_size_only(self):
        self.assertEqual(layout.doubles(self.dest, dry="quick")[0], 4)  # c's copy has the size, not the bytes

    def test_without_go_ahead_copies_stay(self):
        made, off, said = layout.all_songs(self.dest, self.at, self.cfg, ok=False, usb=self.usb)
        self.assertEqual(off, 1)  # (copies mode as before: only e, whose song left, goes, to the USB's Trash)
        for f in ("a.mp3", "b.mp3", "c.mp3", "d.mp3", "f.mp3"):
            self.assertIn(f, self.all_songs())
        self.assertIn("Go ahead", said)
        self.assertFalse(os.path.exists(os.path.join(self.dest, layout.LIST)))
        self.originals()

    def test_go_ahead_keeps_one_copy(self):
        made, off, said = layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)
        self.assertEqual(off, 3)
        self.assertEqual(self.all_songs(), ["c.mp3", "e.mp3", "f.mp3"])  # not byte-identical, no twin, someone's
        stamp = json.load(open(os.path.join(self.dest, layout.ALL, layout.STAMP)))
        self.assertEqual(sorted(stamp), ["c.mp3", "e.mp3"])
        self.originals()
        with open(os.path.join(self.dest, layout.LIST), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[:3], ["#EXTM3U", "#PLAYLIST:All songs", layout.OURS])
        self.assertEqual(sorted(lines[3:]), sorted(SONGS))  # each song once, where it is stored, relative
        self.assertIn("3 doubles taken off", said)
        # run again: nothing more to take off, the list stays the same
        self.assertEqual(layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)[1], 0)

    def test_folder_goes_when_only_copies_were_there(self):
        os.remove(os.path.join(self.dest, layout.ALL, "f.mp3"))
        os.remove(os.path.join(self.dest, layout.ALL, "e.mp3"))
        self.put(os.path.join(layout.ALL, "c.mp3"), SONGS["Spotify Liked Songs/c.mp3"])
        layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)
        self.assertFalse(os.path.exists(os.path.join(self.dest, layout.ALL)))
        self.originals()

    def test_deck_pointing_into_all_songs_stops_it(self):
        self.engine(["../SoundCloud Sync/All songs/a.mp3"])
        made, off, said = layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)
        self.assertEqual(off, 1)  # (copies kept in step: only e, whose song left, goes; no double taken off)
        self.assertIn("PROBLEM", said)
        self.assertIn("a.mp3", self.all_songs())

    def test_rekordbox_file_pointing_into_all_songs_stops_it(self):
        d = os.path.join(self.usb, "PIONEER", "rekordbox")
        os.makedirs(d)
        with open(os.path.join(d, "export.pdb"), "wb") as f:
            f.write(b"\0" * 64 + "/SoundCloud Sync/All songs/b.mp3".encode("utf-16-le"))
        self.assertEqual(layout.pointed(self.usb), ["rekordbox"])
        self.assertEqual(layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)[1], 1)
        self.assertIn("b.mp3", self.all_songs())

    def test_blocked_keeps_copies_in_step_and_writes_no_list(self):
        self.engine(["../SoundCloud Sync/All songs/a.mp3"])
        os.remove(os.path.join(self.dest, layout.ALL, "b.mp3"))  # a copy gone missing is made again, as before
        made, off, said = layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)
        self.assertIn("PROBLEM", said)
        self.assertIn("b.mp3", self.all_songs())
        self.assertFalse(os.path.exists(os.path.join(self.dest, layout.LIST)))

    def test_newest_rekordbox_library_is_checked(self):
        d = os.path.join(self.usb, "PIONEER", "rekordbox")
        os.makedirs(d)
        open(os.path.join(d, "exportLibrary.db"), "wb").close()
        was = layout.ANALYSER
        try:
            layout.ANALYSER = ""  # no way to read it: counts as pointing there, nothing taken off
            self.assertEqual(layout.pointed(self.usb), ["rekordbox (couldn't be read)"])
            self.assertEqual(layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)[1], 1)
            self.assertIn("a.mp3", self.all_songs())
        finally:
            layout.ANALYSER = was

    def test_hash_names_get_dot_slash(self):
        self.put("#1 hit.mp3", b"H" * 10)
        layout.write_list(self.dest)
        with open(os.path.join(self.dest, layout.LIST), encoding="utf-8") as f:
            self.assertIn("./#1 hit.mp3", f.read().splitlines())

    def test_someone_elses_list_is_left(self):
        with open(os.path.join(self.dest, layout.LIST), "w") as f:
            f.write("#EXTM3U\nmine.mp3\n")
        said = layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)[2]
        self.assertIn("someone else", said)
        self.assertEqual(open(os.path.join(self.dest, layout.LIST)).read(), "#EXTM3U\nmine.mp3\n")
        layout.unlist(self.dest)
        self.assertTrue(os.path.exists(os.path.join(self.dest, layout.LIST)))

    def test_back_to_copies_takes_our_list_off(self):
        layout.all_songs(self.dest, self.at, self.cfg, ok=True, usb=self.usb)
        layout.all_songs(self.dest, self.at, {**self.cfg, "one": False}, usb=self.usb)
        self.assertFalse(os.path.exists(os.path.join(self.dest, layout.LIST)))
        for f in ("a.mp3", "b.mp3", "d.mp3"):  # the copies are made again
            self.assertIn(f, self.all_songs())

    def test_config(self):
        self.assertEqual(layout.load(self.dir)["one"], False)
        cfg = layout.save(self.dir, mode="group", all=True, one=True)
        self.assertTrue(layout.listed(cfg))
        self.assertFalse(layout.copies(cfg))
        self.assertTrue(layout.copies(layout.save(self.dir, one=False)))
        self.assertFalse(layout.listed(layout.save(self.dir, mode="flat", one=True)))

    def test_go_ahead_is_per_stick_and_per_change(self):
        self.assertFalse(usb_ask.allow(self.dir, self.usb, "one"))  # no yes for this stick at all yet
        usb_ask.answer(self.dir, self.usb, True)
        self.assertEqual(usb_ask.state(self.dir, self.usb), "ok")
        self.assertFalse(usb_ask.allows(self.dir, self.usb, "one"))  # the stick's yes doesn't cover this change
        self.assertTrue(usb_ask.allow(self.dir, self.usb, "one"))
        self.assertTrue(usb_ask.allows(self.dir, self.usb, "one"))
        usb_ask.answer(self.dir, self.usb, False)  # "Stop" takes it back
        self.assertFalse(usb_ask.allows(self.dir, self.usb, "one"))


if __name__ == "__main__":
    unittest.main()
