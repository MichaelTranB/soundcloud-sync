#!/usr/bin/env python3
"""Keeps The Crate's songs readable on every deck, laptop and phone app that opens the USB.

    python3 usbsafe.py names DIR SRC     # a song whose name has a sign a USB can't hold gets a look-alike sign
    python3 usbsafe.py clean CRATE       # takes off the "._" files macOS leaves beside each file on the USB

Most USBs are FAT32 or exFAT, which can't hold \\ : * ? " < > | in a name. A Mac copies such a song anyway under a
hidden stand-in sign, and other devices then show a broken name or can't open it (djay on an iPhone calls the folder
"not a valid directory"). So the song is renamed on the Mac first, each of those signs swapped for its look-alike
(":" becomes "：", "?" becomes "？"), the way Windows shows them too. The rename is noted in dj-moved.tsv like any
other move, so every note about the song, its copy on the USB and its rows in the decks' libraries follow it
(dj.follow, usb_tidy) and nothing is copied or listened to twice.

macOS also writes a 4 KB "._name" file beside every file it puts on a USB that isn't Mac-formatted. Decks and phone
apps list them as broken tracks. clean() takes them off inside The Crate's own folder, and the one for that folder
itself at the top of the USB, after every copy. Only real "._" files (their first bytes say so) are taken; nothing
else is touched. Standard library only."""
import fcntl, os, sys, time

import usb_tidy

SIGNS = {"\\": "＼", ":": "：", "*": "＊", "?": "？", '"': "＂", "<": "＜", ">": "＞", "|": "｜"}
DOUBLE = b"\x00\x05\x16\x07"  # how every "._" file macOS writes begins (AppleDouble)


def safe(name):
    """The name with every sign a USB can't hold swapped for its look-alike."""
    return "".join(SIGNS.get(c, c) for c in name)


def names(dir, src):
    """Renames each song in the music folder whose file name has such a sign. Returns [(old, new), ...]."""
    done = []
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith(".") or not f.lower().endswith(usb_tidy.AUDIO) or safe(f) == f:
                continue
            a, b = os.path.join(root, f), os.path.join(root, safe(f))
            if os.path.lexists(b):  # (one of that name is there already: left as it is, and said)
                print(f'"{f}" has a sign a USB can\'t hold, and "{safe(f)}" is taken', file=sys.stderr)
                continue
            try:
                os.rename(a, b)
            except OSError as e:
                print(f'"{f}" couldn\'t be renamed ({e.strerror})', file=sys.stderr)
                continue
            done.append((os.path.relpath(a, src), os.path.relpath(b, src)))
    if not done:
        return done
    with open(os.path.join(dir, usb_tidy.MOVES), "a") as fh:
        fh.writelines(f"{a}\t{b}\n" for a, b in done)
    passed(dir, done)
    try:  # the Soulseek, friend and wanted notes follow too (aiff.follow)
        import aiff
        for a, b in done:
            aiff.follow(dir, src, a, b)
    except Exception as e:  # never silent
        print(f"the notes for a renamed song couldn't all follow it ({e})", file=sys.stderr)
    stamp = time.strftime("%F %R")
    with open(os.path.join(dir, "usb.log"), "a") as fh:
        fh.writelines(f'{stamp}  renamed "{a}" to "{b}" (a USB can\'t hold some signs in a name)\n' for a, b in done)
    return done


def passed(dir, done):
    """The safety check already passed the file under its old name: the same file keeps that (safety-ok.tsv)."""
    path = os.path.join(dir, "safety-ok.tsv")
    with open(os.path.join(dir, ".safety.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path) as fh:
                lines = fh.read().splitlines()
        except OSError:
            return
        to = dict(done)
        out = []
        for line in lines:
            p, tab, rest = line.partition("\t")
            out.append(to.get(p, p) + tab + rest)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.writelines(l + "\n" for l in out)
        os.replace(tmp, path)


def junk(p):
    """A "._" file macOS wrote (not a song someone named that way)."""
    try:
        if not os.path.isfile(p) or os.path.islink(p) or os.path.getsize(p) > 1 << 20:
            return False
        with open(p, "rb") as fh:
            return fh.read(4) == DOUBLE
    except OSError:
        return False


def clean(crate):
    """Takes off the "._" files inside The Crate's folder, and the one for the folder itself beside it. Returns how
    many."""
    crate = os.path.abspath(crate)
    found = [os.path.join(os.path.dirname(crate), "._" + os.path.basename(crate))]
    for root, dirs, files in os.walk(crate):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        found += [os.path.join(root, f) for f in files if f.startswith("._")]
    off = 0
    for p in found:
        if junk(p):
            try:
                os.remove(p)
                off += 1
            except OSError:
                pass
    return off


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "names":
        names(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] == "clean":
        clean(sys.argv[2])
    else:
        sys.exit(__doc__)
