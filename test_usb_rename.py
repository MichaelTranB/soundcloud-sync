"""A song with an accent in its name moves on a FAT32 or exFAT USB (usb_tidy.rename). Run with:

    python3 -m unittest test_usb_rename"""
import os, tempfile, unicodedata, unittest
from unittest import mock

import usb_tidy

real = os.rename


def fat(a, b):  # as macOS's FAT32 driver does: a decomposed name it listed isn't found when moved
    if unicodedata.normalize("NFC", a) != a:
        raise FileNotFoundError(2, "No such file or directory", a)
    real(unicodedata.normalize("NFC", a), b)


class Rename(unittest.TestCase):
    def test_accented_name_moves(self):
        d = tempfile.mkdtemp()
        name = "INÉZ - EYES CUT DEEPER.mp3"
        open(os.path.join(d, name), "w").close()
        os.makedirs(os.path.join(d, "EDM"))
        nfd = os.path.join(d, unicodedata.normalize("NFD", name))
        with mock.patch.object(os, "rename", fat):
            usb_tidy.rename(nfd, os.path.join(d, "EDM", name))
        self.assertTrue(os.path.isfile(os.path.join(d, "EDM", name)))

    def test_missing_file_still_fails(self):
        d = tempfile.mkdtemp()
        with self.assertRaises(FileNotFoundError):
            usb_tidy.rename(os.path.join(d, "gone.mp3"), os.path.join(d, "x.mp3"))


if __name__ == "__main__":
    unittest.main()
