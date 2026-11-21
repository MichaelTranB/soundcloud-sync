"""Checks for the MP3 copies (mp3.py). Run with the private Python (it has mutagen), with ffmpeg and lame installed:

    ~/.local/share/crate-dj/python/bin/python3 -m unittest test_mp3

Made-up songs (a tone that swells and fades) stand in for music, and a temp folder for iCloud Drive: nothing of yours
is read or written."""
import os, subprocess, tempfile, unittest
from unittest import mock

CLOUD = tempfile.mkdtemp()
os.environ["CRATE_ICLOUD"] = CLOUD

import aiff, backup, mp3  # noqa: E402
backup.CLOUD = CLOUD  # (also when backup.py was imported first, by another test file: never your real iCloud Drive)

FF = mp3.tool("ffmpeg")


def song(path, rate=44100, codec="pcm_s16le", secs=6, tags=True):
    cmd = [FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=220:d={secs}:r={rate},volume='0.2+0.6*sin(t)':eval=frame",
           "-ac", "2", "-c:a", codec]
    if tags:
        cmd += ["-metadata", "title=Swell", "-metadata", "artist=Nobody", "-metadata", "genre=House"]
    if path.endswith(".aiff"):
        cmd += ["-write_id3v2", "1"]  # (as aiff.py's AIFFs carry theirs)
    subprocess.run(cmd + [path], check=True)


@unittest.skipUnless(FF and mp3.tool("lame"), "needs ffmpeg and lame")
class Mp3(unittest.TestCase):
    def setUp(self):
        self.dir, self.src = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.makedirs(os.path.join(self.src, "House"))
        song(os.path.join(self.src, "House", "a.flac"), codec="flac")
        song(os.path.join(self.src, "b.wav"), rate=96000, codec="pcm_s24le")
        song(os.path.join(self.src, "c.aiff"), codec="pcm_s16be")
        song(os.path.join(self.src, "d.mp3"), codec="libmp3lame")
        with open(os.path.join(self.dir, "usb-checked.tsv"), "w") as f:
            f.write("".join(r + "\n" for r in ("House/a.flac", "b.wav", "c.aiff", "d.mp3")))
        self.safe = mock.patch.object(aiff, "safe", lambda d, s: {"House/a.mp3", "b.mp3", "c.mp3", "House/a.flac",
                                                                  "b.wav", "c.aiff"})
        self.checked = mock.patch.object(mp3.usb_tidy, "checked", lambda d, s: [
            r for r in ("House/a.flac", "b.wav", "c.aiff", "d.mp3") if os.path.exists(os.path.join(s, r))])
        self.safe.start(), self.checked.start()
        self.addCleanup(self.safe.stop), self.addCleanup(self.checked.stop)

    def test_off_by_default(self):
        self.assertEqual(mp3.waiting(self.dir, self.src), [])

    def test_converts_keeps_and_undoes(self):
        mp3.save(self.dir, {"on": True})
        self.assertEqual(sorted(mp3.waiting(self.dir, self.src)), ["House/a.flac", "b.wav", "c.aiff"])
        self.assertEqual(aiff.waiting(self.dir, self.src), [])  # no AIFF step while MP3s are on
        done, why = mp3.run(self.dir, self.src, mp3.waiting(self.dir, self.src))
        self.assertEqual((sorted(done), why), (["House/a.mp3", "b.mp3", "c.mp3"], {}))
        kept = os.path.join(CLOUD, "The Crate", mp3.HOME)
        for old, new in (("House/a.flac", "House/a.mp3"), ("b.wav", "b.mp3"), ("c.aiff", "c.mp3")):
            self.assertFalse(os.path.exists(os.path.join(self.src, old)))
            self.assertTrue(os.path.isfile(os.path.join(kept, old)))  # in iCloud, in the same folders
            self.assertTrue(mp3.same(os.path.join(kept, old), os.path.join(self.src, new)))
        from mutagen.mp3 import MP3
        m = MP3(os.path.join(self.src, "House/a.mp3"))
        self.assertEqual((round(m.info.bitrate / 1000), m.info.sample_rate, str(m.tags["TIT2"]), str(m.tags["TCON"])),
                         (320, 44100, "Swell", "House"))
        self.assertEqual(MP3(os.path.join(self.src, "b.mp3")).info.sample_rate, 48000)  # 96 kHz: the most an MP3 holds
        self.assertEqual(str(MP3(os.path.join(self.src, "c.mp3")).tags["TPE1"]), "Nobody")  # an AIFF's own tags
        rows = {new: old for old, new, _, _ in aiff.rows(self.dir)}
        self.assertEqual(rows["House/a.mp3"], "House/a.flac")  # dj.py follows rekordbox and Engine along this row
        self.assertEqual(len(mp3.load(self.dir)["up"]), 3)  # to give their room back once iCloud has them
        self.assertEqual(aiff.undoable(self.dir), {})  # not the AIFF's undo
        self.assertEqual(mp3.waiting(self.dir, self.src), [])
        with mock.patch.object(aiff, "trash", lambda d, p, why: os.replace(p, os.path.join(self.dir, "t.mp3")) or
                               os.path.join(self.dir, "t.mp3")):
            done, why = mp3.run(self.dir, self.src, ["House/a.mp3"], back=True)
        self.assertEqual((done, why), (["House/a.flac"], {}))
        self.assertTrue(os.path.isfile(os.path.join(self.src, "House/a.flac")))
        self.assertFalse(os.path.exists(os.path.join(kept, "House/a.flac")))
        self.assertEqual(mp3.waiting(self.dir, self.src), [])  # brought back by you: it stays lossless

    def test_wrong_mp3_never_passes(self):
        a, b = os.path.join(self.src, "House/a.flac"), os.path.join(self.dir, "other.mp3")
        song(b, codec="libmp3lame", secs=5)
        self.assertFalse(mp3.same(a, b))  # a second short
        subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=6", "-ac", "2", b], check=True)
        self.assertFalse(mp3.same(a, b))  # the same length, but not the same swell

    def test_smaller_mp3_by_that_name_is_not_taken(self):
        mp3.save(self.dir, {"on": True})
        subprocess.run([FF, "-v", "error", "-y", "-i", os.path.join(self.src, "c.aiff"), "-b:a", "128k",
                        os.path.join(self.src, "c.mp3")], check=True)
        done, why = mp3.run(self.dir, self.src, ["c.aiff"])
        self.assertEqual(done, [])
        self.assertIn("already an MP3", why["c.aiff"])
        self.assertTrue(os.path.isfile(os.path.join(self.src, "c.aiff")))  # the original stays

    def test_undo_waits_for_the_safety_check(self):
        mp3.save(self.dir, {"on": True})
        mp3.run(self.dir, self.src, ["c.aiff"])
        kept = mp3.undoable(self.dir)["c.mp3"]
        with mock.patch.object(aiff, "safe", lambda d, s: {"c.mp3"}):  # the check couldn't run this time
            done, why = mp3.run(self.dir, self.src, ["c.mp3"], back=True)
        self.assertEqual(done, [])
        self.assertTrue(os.path.isfile(kept))  # still kept, and Undo still offered
        self.assertFalse(os.path.exists(os.path.join(self.src, "c.aiff")))
        self.assertEqual(mp3.undoable(self.dir), {"c.mp3": kept})

    def test_without_icloud_kept_on_this_mac(self):
        mp3.save(self.dir, {"on": True})
        with mock.patch.object(backup, "cloud", lambda wait=8: ""):
            done, why = mp3.run(self.dir, self.src, ["c.aiff"])
        self.assertEqual(done, ["c.mp3"])
        self.assertTrue(os.path.isfile(os.path.join(self.dir, mp3.HOME, "c.aiff")))
        self.assertEqual(mp3.load(self.dir)["up"], [])


if __name__ == "__main__":
    unittest.main()
