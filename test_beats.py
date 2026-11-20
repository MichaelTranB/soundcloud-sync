"""Checks for The Crate's own analysis (beats.py, anlz.py, the grid parts of engine.py, tempo.py, rekordbox_usb.py).
Run with the private Python (it has numpy and pyrekordbox):

    ~/.local/share/crate-dj/python/bin/python3 -m unittest test_beats

A made-up song (a kick each beat at 128 BPM, louder on each bar's first beat) stands in for music: nothing of yours
is read or written."""
import os, sqlite3, struct, tempfile, unittest, wave, zlib

import numpy as np

import anlz, beats, engine, rekordbox_usb, tempo

BPM, FIRST, SECS = 128.0, 0.25, 40


def song(path):
    """A WAV: a kick (a short 60 Hz thump) and a hat on every beat from FIRST, the bar's first beat twice as loud."""
    r = beats.RATE
    y = np.zeros(int(SECS * r), np.float32)
    t = np.arange(int(0.12 * r)) / r
    kick = np.sin(2 * np.pi * 60 * t) * np.exp(-t * 30)
    hat = np.random.default_rng(1).standard_normal(int(0.02 * r)) * np.exp(-np.arange(int(0.02 * r)) / r * 200) * 0.2
    for i, at in enumerate(np.arange(FIRST, SECS - 0.2, 60 / BPM)):
        a = int(at * r)
        y[a:a + len(kick)] += kick * (1.0 if i % 4 == 0 else 0.5)
        y[a:a + len(hat)] += hat
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(r)
        w.writeframes((np.clip(y, -1, 1) * 32000).astype("<i2").tobytes())


class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.wav = os.path.join(cls.tmp.name, "beat.wav")
        song(cls.wav)
        cls.g, cls.W = beats.analyse(cls.wav, 44100)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_tempo_and_first_beat(self):
        self.assertEqual(self.g["bpm"], BPM)
        first = beats.times(self.g)[0][0]  # (on the kick, within a few ms: LATE is set by rekordbox on real music)
        self.assertLess(abs(first - FIRST), 0.02)
        self.assertEqual(self.g["lead"], 0.0)
        self.assertEqual(self.g["samples"], SECS * 44100)

    def test_beat_times(self):
        t = beats.times({"bpm": 120.0, "first": 0.7, "bar": 1, "lead": 0.0, "secs": 3.0})
        self.assertAlmostEqual(t[0][0], 0.7 + beats.LATE - 0.5)
        self.assertEqual([n for _, n in t[:5]], [3, 4, 1, 2, 3])  # the bar starts on the 2nd beat after 0.7 s
        self.assertTrue(all(b - a > 0.499 for (a, _), (b, _) in zip(t, t[1:])))
        e = beats.times({"bpm": 120.0, "first": 0.7, "bar": 0, "lead": 0.048, "secs": 3.0}, "engine")
        self.assertAlmostEqual(e[0][0], 0.2 + beats.LATE + beats.ENGINE_MP3)

    def test_rekordbox_files(self):
        dat, ext = anlz.files(self.g, self.W, "/Contents/beat.wav", self.wav)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ANLZ0000.DAT")
            for name, data in (("ANLZ0000.DAT", dat), ("ANLZ0000.EXT", ext)):
                with open(os.path.join(d, name), "wb") as f:
                    f.write(data)
            from pyrekordbox.anlz import AnlzFile
            a = AnlzFile.parse_file(p)
            self.assertEqual(str(a.get("path")), "/Contents/beat.wav")
            bpm = a.get("beat_grid")[1]
            self.assertTrue(np.allclose(bpm, BPM))
            AnlzFile.parse_file(os.path.join(d, "ANLZ0000.EXT"))
            self.assertEqual(tempo.grid(p), int(BPM * 100))
            # rekordbox's grid read back as The Crate keeps one: the same beats
            back = anlz.rekordbox_grid(p, self.g)
            self.assertEqual(back["bpm"], BPM)
            self.assertLess(abs(back["first"] - self.g["first"]) % (60 / BPM), 0.002)
            self.assertEqual(back["bar"], self.g["bar"])
            # moved to the song's place on a USB: only the place changes
            moved = rekordbox_usb.repath(dat, "/The Crate/beat.wav")
            self.assertEqual(moved[-200:], dat[-200:])

    def test_engine_rows(self):
        wave_ = anlz.engine_overview(self.W, self.g["samples"])
        self.assertEqual(len(wave_), 3099)
        cols = engine.analysed(self.g, "Am", wave_)
        rate, samples, key = struct.unpack(">dqi", zlib.decompress(cols["trackData"][4:])[:20])
        self.assertEqual((rate, samples), (44100.0, SECS * 44100))
        self.assertEqual(key, engine.KEYS["Am"])
        b = zlib.decompress(cols["beatData"][4:])
        self.assertEqual(struct.unpack(">ddB", b[:17]), (44100.0, SECS * 44100, 1))
        n = struct.unpack(">q", b[17:25])[0]
        self.assertEqual(n, 2)
        (s0, i0, u0, _), (s1, i1, u1, _) = [struct.unpack("<dqii", b[25 + 24 * k:49 + 24 * k]) for k in range(2)]
        self.assertEqual(i0, -4)
        self.assertEqual(u0, i1 + 4)
        self.assertAlmostEqual((s1 - s0) / (i1 - i0), 44100 * 60 / BPM, places=3)
        self.assertEqual(len(zlib.decompress(cols["quickCues"][4:])), 129)
        self.assertEqual(len(cols["loops"]), 192)


class Rules(unittest.TestCase):
    def test_check_tempo(self):
        self.assertFalse(tempo.check({"bpm_from": "grid", "bpm": 128.0, "own_bpm": 128.0}))
        self.assertTrue(tempo.check({"bpm_from": "grid", "bpm": 128.0, "own_bpm": 64.0}))
        self.assertTrue(tempo.check({"bpm_from": "grid", "bpm": 128.0, "own_bpm": 128.0, "bpm3": 170.0}))
        self.assertFalse(tempo.check({"bpm_from": "rekordbox", "bpm": 128.0, "own_bpm": 64.0}))

    def test_octave_by_genre_and_tap(self):
        g = {"bpm": 172.0}
        self.assertEqual(tempo.octave({"genres": ["Hip Hop"], "own_grid": g}, {}), (0.5, "genre"))
        self.assertEqual(tempo.octave({"genres": ["Drum & Bass"], "own_grid": {"bpm": 87.0}}, {}), (2, "genre"))
        self.assertEqual(tempo.octave({"genres": ["Drum & Bass"], "own_grid": g}, {}), (1, ""))
        self.assertEqual(tempo.octave({"genres": ["House"], "own_grid": g}, {}), (1, ""))
        self.assertEqual(tempo.octave({"key": "k", "genres": ["Hip Hop"], "own_grid": g}, {"k": 1}), (1, "you"))
        # the genre settled the octave: a second count at half is no reason to check, one off by a third is
        song = {"bpm_from": "grid", "bpm": 86.0, "own_bpm": 172.0, "octave": "genre"}
        self.assertFalse(tempo.check(song))
        self.assertTrue(tempo.check({**song, "own_bpm": 120.0}))
        self.assertFalse(tempo.check({**song, "own_bpm": 120.0, "octave": "you"}))
        with tempfile.TemporaryDirectory() as d:
            tempo.tap(d, "k", 2)
            self.assertEqual(tempo.taps(d), {"k": 2})
            tempo.tap(d, "k", None)
            self.assertEqual(tempo.taps(d), {})

    def test_fold_keeps_the_bars(self):
        g = {"bpm": 140.0, "first": 0.1, "bar": 3, "lead": 0.0, "secs": 30.0}
        one = lambda grid: [round(t, 3) for t, n in beats.times(grid) if n == 1]
        half, double = tempo.fold(g, 0.5), tempo.fold(g, 2)
        self.assertEqual((half["bpm"], double["bpm"]), (70.0, 280.0))
        self.assertTrue(set(one(half)) <= set(one(g)))  # every bar of the slow count starts on one of the fast's
        self.assertLessEqual(abs(len(one(half)) - len(one(g)) / 2), 1)  # (every other one)
        self.assertTrue(set(one(g)) <= {round(t, 3) for t in one(double)})  # a fast bar starts on each slow one
        self.assertIs(tempo.fold(g, 1), g)

    def test_grid_swapped_into_our_file(self):
        g = {"bpm": 87.0, "first": 0.2, "bar": 0, "lead": 0.0, "secs": 20.0, "samples": 20 * 44100, "rate": 44100}
        dat, _ = anlz.files(g, np.zeros((3000, 5), np.float32), "/Contents/a.wav")
        g2 = tempo.fold(g, 2)
        moved = rekordbox_usb.regrid(dat, g2)
        with tempfile.TemporaryDirectory() as d:
            mine, usb = os.path.join(d, "mine.DAT"), os.path.join(d, "usb")
            os.makedirs(usb + "/P")
            with open(mine, "wb") as f:
                f.write(dat)
            with open(usb + "/P/ANLZ0000.DAT", "wb") as f:
                f.write(rekordbox_usb.repath(dat, "/x/a.wav"))
            self.assertTrue(rekordbox_usb.ours(usb, "/P/ANLZ0000.DAT", mine, "/x/a.wav"))
            self.assertFalse(rekordbox_usb.ours(usb, "/P/ANLZ0000.DAT", mine, "/x/a.wav", g2))  # (so it's filled)
            with open(usb + "/P/ANLZ0000.DAT", "wb") as f:
                f.write(rekordbox_usb.regrid(rekordbox_usb.repath(dat, "/x/a.wav"), g2))
            self.assertTrue(rekordbox_usb.ours(usb, "/P/ANLZ0000.DAT", mine, "/x/a.wav"))
            self.assertTrue(rekordbox_usb.ours(usb, "/P/ANLZ0000.DAT", mine, "/x/a.wav", g2))
            self.assertEqual(tempo.grid(usb + "/P/ANLZ0000.DAT"), 17400)
        self.assertEqual(len(moved) - len(dat), 8 * (len(beats.times(g2)) - len(beats.times(g))))

    def test_crate_only_where_nothing_else(self):
        with tempfile.NamedTemporaryFile(suffix=".DAT") as f:
            songs = [{"rel": "a.wav", "grid_anlz": f.name, "own_grid": {"bpm": 140.0}, "musical_key": "Dm"},
                     {"rel": "b.wav", "grid_anlz": f.name, "own_grid": {"bpm": 140.0}}]
            known = {"b.wav": {**rekordbox_usb.BLANK, "anlz": "/elsewhere/ANLZ0000.DAT", "bpm": 13900}}
            k = rekordbox_usb.crate({"songs": songs}, known)
            self.assertEqual((k["a.wav"]["anlz"], k["a.wav"]["bpm"], k["a.wav"]["key"]), (f.name, 14000, "Dm"))
            self.assertTrue(k["a.wav"]["ours"])
            self.assertEqual(k["b.wav"]["anlz"], "/elsewhere/ANLZ0000.DAT")  # rekordbox's own stays

    def test_engine_tells_ours_from_a_decks(self):
        with tempfile.TemporaryDirectory() as d:
            usb, backups = os.path.join(d, "usb"), os.path.join(d, "app", "dj-backups")
            os.makedirs(os.path.join(usb, "Engine Library", "Database2")), os.makedirs(backups)
            con = sqlite3.connect(engine.db_path(usb))
            con.executescript("CREATE TABLE Track (id INTEGER PRIMARY KEY, path TEXT, bpmAnalyzed REAL, isAnalyzed INT);"
                              "CREATE TABLE PerformanceData (trackId INT, beatData BLOB);"
                              "INSERT INTO Track VALUES (1, '../The Crate/a.wav', 128, 1), (2, '../The Crate/b.wav', 140, 1);"
                              "INSERT INTO PerformanceData VALUES (1, x'01'), (2, x'02');")
            con.commit(), con.close()
            engine.remember(backups, {engine.print_of(b"\x01")})
            self.assertEqual(engine.theirs(usb, backups), {"../The Crate/b.wav": 140})


if __name__ == "__main__":
    unittest.main()
