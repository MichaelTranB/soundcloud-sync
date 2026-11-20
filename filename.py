#!/usr/bin/env python3
"""Song file names every USB and every deck can hold.

A USB for the decks is formatted FAT32 or exFAT, and neither can hold a file name with one of  \\ : * ? " < > |
in it. A Mac writes such a name there with a stand-in letter no deck, phone or PC can read: the song is on the
USB, but its name there is not the one the decks' lists were given, so it shows as missing or can't be opened.

  filename.py auto DIR SRC    DIR: the app folder; SRC: the music folder on the Mac (usb.sh runs this)

So before a copy, a song in the music folder with such a name is renamed, once, to the same name without the sign
("A : B" becomes "A - B", "OH YEAH?" becomes "OH YEAH"). Nothing else about the file changes. It is the same song
everywhere: every note kept for it follows (where it came from, tempo and key, cues, your genre pick), its copy on
the USB is renamed the same way instead of being copied a second time (dj-moved.tsv, usb_tidy.py), and the decks'
lists are pointed at the new name with cues, loops and grids kept (dj.py). Each rename is said in dj.log.
Standard library only."""
import fcntl, os, re, sys, time, unicodedata

import aiff, genres, soulseek, usb_tidy


def cf(name):
    return unicodedata.normalize("NFC", name).casefold()


def clean(name):
    """A file's name as every drive can hold it (the same name, untouched, when it already can)."""
    stem, ext = os.path.splitext(name)
    if not re.search(r'[\\:*?"<>|\x00-\x1f\x7f]', stem):
        return name
    s = "".join(c if ord(c) >= 32 and ord(c) != 127 else " " for c in stem)
    s = re.sub(r"\s+[:|]\s+|\s*[:|]\s+", " - ", s)  # "A : B", "A: B"
    s = re.sub(r"[:|\\]", "-", s)  # "3:00"; (a "/" typed in Finder is a ":" in the name on disk)
    s = re.sub(r"(?<=\w)\?(?=\w)", "_", s)  # a letter the download couldn't write: "M?STIC"
    s = s.replace("?", "").replace("*", "").replace('"', "'").replace("<", "(").replace(">", ")")
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    return (s or "song") + ext


def free(src, rel, taken):
    """The clean name for this song, inside the music folder: one no other file there has (a USB reads capitals as
    the same letter)."""
    folder, name = os.path.split(rel)
    stem, ext = os.path.splitext(clean(name))
    n, new = 1, os.path.join(folder, stem + ext)
    while os.path.lexists(os.path.join(src, new)) or cf(new) in taken:
        n += 1
        new = os.path.join(folder, f"{stem} ({n}){ext}")
    return new


def todo(dir, src):
    """The songs to rename: finished ones (they passed the safety check) whose name a USB can't hold."""
    return [r for r in usb_tidy.checked(dir, src) if clean(os.path.basename(r)) != os.path.basename(r)]


def notes(dir, src, old, new):
    """What is kept for the song under its file's name goes by the new one."""
    aiff.follow(dir, src, old, new)  # where it came from, tempo and key, another USB's cues, fixed names and details
    a, b = os.path.join(src, old), os.path.join(src, new)
    path = os.path.join(dir, "free.tsv")  # a free download's record holds the file too (the page reads it)
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    if any(l.split("\t")[2:3] == [a] for l in lines):
        with open(path + ".tmp", "w") as f:
            f.writelines("\t".join(p[:2] + [b] + p[3:] if p[2:3] == [a] else p) + "\n"
                         for p in (l.split("\t") for l in lines))
        os.replace(path + ".tmp", path)
    g = genres.load(dir)  # a song with no playlist link is known by its file's name: your genre pick stays its
    ka, kb = ("file:" + os.path.splitext(os.path.basename(x))[0] for x in (old, new))
    if ka in g["songs"] and kb not in g["songs"]:
        g["songs"][kb] = g["songs"].pop(ka)
        genres.save(dir, g)


def auto(dir, src):
    """Renames each. Returns [(old, new)], names inside the music folder; None when it has to wait (the decks' lists
    are being written, or songs are being converted: the next copy does it)."""
    rels = todo(dir, src)
    if not rels:
        return []
    done = []
    with open(os.path.join(dir, ".dj.lock"), "a") as decks, open(os.path.join(dir, ".aiff.lock"), "a") as conv:
        try:
            fcntl.flock(decks, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(conv, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        taken = set()
        with soulseek.locked(dir):
            for rel in rels:
                old = os.path.join(src, rel)
                try:
                    if time.time() - os.path.getmtime(old) < 120:  # just written: left until it has settled
                        continue
                    new = free(src, rel, taken)
                    taken.add(cf(new))
                    with open(os.path.join(dir, usb_tidy.MOVES), "a", encoding="utf-8") as f:  # noted first: the
                        f.write(f"{rel}\t{new}\n")  # USB's copy and the decks' lists follow from this line
                    os.rename(old, os.path.join(src, new))
                except OSError as e:
                    aiff.log(dir, f"NAME PROBLEM: {rel} couldn't be renamed for the USB ({e})"[:300])
                    continue
                done.append((rel, new))
                try:
                    notes(dir, src, rel, new)
                except Exception as e:  # the song itself is fine; said, never silent
                    aiff.log(dir, f"NAME PROBLEM: the notes for {new} didn't all follow ({e!r})"[:300])
        if done:
            aiff.safe(dir, src)  # the copy takes only checked files: these are listed under their new names now
    return done


def say(done):
    if not done:
        return ""
    s = "" if len(done) == 1 else "s"
    return (f"{len(done)} song{s} renamed so every USB and deck can hold the name{s} "
            f"(a sign like : or ? is gone, nothing else changed): "
            + "; ".join(f'"{os.path.basename(a)}" is now "{os.path.basename(b)}"' for a, b in done[:20])
            + (f"; and {len(done) - 20} more" if len(done) > 20 else ""))


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "auto":
        sys.exit(__doc__)
    aiff.log(sys.argv[2], say(auto(sys.argv[2], sys.argv[3]) or []))
