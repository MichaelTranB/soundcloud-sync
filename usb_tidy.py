#!/usr/bin/env python3
"""Keeps the USB's copy of the music folder in step with the Mac's, so it holds each song once and the very file
the decks' libraries were made from (usb.sh itself only ever adds):

  a song you threw back on the page ("Wrong or bad file": usb-thrown.tsv) leaves the USB as well. Its copy there
    (the same place, the same size) goes to the USB's own Trash, never deleted;
  Soulseek files that moved out of their old "From Soulseek" folder (soulseek-moved.tsv) move the same way on the
    USB, so they are not copied onto it a second time;
  a USB that already had songs on it (filled by another Mac's Crate, or half-filled by hand): a file there with a
    song's name but not its size is another download of it, so it is swapped for the library's file (the tempo,
    beat grid and waveform in the decks' libraries were made from that one); and the same song as another kind of
    file (name.mp3 beside name.flac) that isn't in the library is a double, and goes. Both to the USB's Trash.
    Songs on the USB that aren't in this library at all are someone's own, and are left alone.

  usb_tidy.py DIR SRC DEST    DIR: the app folder; SRC: the music folder on the Mac; DEST: its copy on the USB

Only files inside DEST are ever touched; anything else on the USB is left alone. Run by usb.sh before it copies, and
by dj.py before it writes the decks' libraries. Standard library only."""
import os, shutil, sys, time, unicodedata

OLD, MOVED, THROWN = "From Soulseek", "soulseek-moved.tsv", "usb-thrown.tsv"  # as soulseek.py names them
CHECKED = "safety-ok.tsv"  # the files that passed the safety check (safety.py): the only ones usb.sh copies
AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus", ".alac", ".aac")


def rows(d, name):
    try:
        with open(os.path.join(d, name), errors="replace") as f:
            return [p for p in (l.rstrip("\n").split("\t") for l in f) if len(p) == 2 and all(p)]
    except OSError:
        return []


def inside(folder, path):
    """path as it sits inside folder ("" when it isn't in there)."""
    rel = os.path.relpath(os.path.normpath(path), os.path.normpath(folder))
    return "" if rel == "." or rel.startswith("..") or os.path.isabs(rel) else rel


def size(p):
    try:
        return os.path.getsize(p) if os.path.isfile(p) else -1
    except OSError:
        return -1


def shadow(p):
    """The "._name" file macOS keeps beside a file on a USB that isn't Mac-formatted: it goes where its file goes."""
    return os.path.join(os.path.dirname(p), "._" + os.path.basename(p))


def trash(dest, p):
    """Into the USB's own Trash (what Finder shows as the Trash while the USB is in), or a folder of its own on the
    USB when that can't be made. Returns where it went, or "" when it couldn't be moved."""
    root = os.path.abspath(dest)
    while not os.path.ismount(root) and os.path.dirname(root) != root:
        root = os.path.dirname(root)
    if root == os.path.dirname(root):  # (not on a drive of its own: a test, or a folder picked by hand)
        root = os.path.dirname(os.path.abspath(dest))
    name, ext = os.path.splitext(os.path.basename(p))
    for folder in (os.path.join(root, ".Trashes", str(os.getuid())), os.path.join(root, "Thrown back by The Crate")):
        try:
            os.makedirs(folder, exist_ok=True)
            to = os.path.join(folder, os.path.basename(p))
            if os.path.exists(to):
                to = os.path.join(folder, f"{name} {time.strftime('%Y-%m-%d %H%M%S')}{ext}")
            shutil.move(p, to)
            if os.path.isfile(shadow(p)):
                shutil.move(shadow(p), shadow(to))
            return to
        except OSError:
            continue
    return ""


def checked(d, src):
    """The songs usb.sh copies: each file in the music folder that passed the safety check, as it sits in there."""
    try:
        with open(os.path.join(d, CHECKED), errors="replace") as f:
            rels = [l.rstrip("\n").split("\t")[0] for l in f]
    except OSError:
        return []
    return [r for r in dict.fromkeys(rels) if r and not os.path.isabs(r) and ".." not in r.split(os.sep)
            and r.lower().endswith(AUDIO) and size(os.path.join(src, r)) > 0]


def same(a, b):
    """Two names for one thing, however the drive spells its letters (accents, capitals)."""
    return unicodedata.normalize("NFC", a).lower() == unicodedata.normalize("NFC", b).lower()


def swap(dest, src_file, p):
    """The library's file in place of the one at p (which goes to the USB's Trash). Copied beside it first, so a
    copy that fails (a full USB) leaves what was there."""
    tmp = os.path.join(os.path.dirname(p), ".crate-" + os.path.basename(p))
    try:
        shutil.copy2(src_file, tmp)
        if size(tmp) != size(src_file) or not trash(dest, p):
            raise OSError("not swapped")
        os.rename(tmp, p)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def doubles(src, dest, rels):
    """rels: the library's songs (checked()). Returns (files swapped for the library's own, doubles taken off, ones
    that couldn't be)."""
    swapped = off = stuck = 0
    folders = {}  # each folder on the USB, listed once
    def listed(folder):
        if folder not in folders:
            try:
                found = os.listdir(os.path.join(dest, folder))
            except OSError:
                found = []
            for f in found:
                if f.startswith(".crate-"):  # a swap that was cut short left its half-made copy
                    try:
                        os.remove(os.path.join(dest, folder, f))
                    except OSError:
                        pass
            folders[folder] = [f for f in found if not f.startswith(".")]
        return folders[folder]
    for rel in rels:
        mine, p = os.path.join(src, rel), os.path.join(dest, rel)
        if size(p) >= 0 and size(p) != size(mine):
            if swap(dest, mine, p):
                swapped += 1
            else:
                stuck += 1
        folder, name = os.path.split(rel)
        stem = os.path.splitext(name)[0]
        for at in dict.fromkeys((folder, OLD)):
            for f in list(listed(at)):
                other, ext = os.path.splitext(f)
                if ext.lower() in AUDIO and same(other, stem) and not same(f, name) and \
                        size(os.path.join(src, at, f)) < 0 and size(os.path.join(dest, at, f)) >= 0:
                    if trash(dest, os.path.join(dest, at, f)):
                        off += 1
                    else:
                        stuck += 1
                    listed(at).remove(f)
    return swapped, off, stuck


def tidy(d, src, dest):
    """Returns (thrown-back songs taken off the USB, songs moved in with the rest, ones that couldn't be moved,
    files swapped for the library's own, doubles taken off)."""
    off = moved = stuck = 0
    if not os.path.isdir(dest):
        return 0, 0, 0, 0, 0
    for was, now in rows(d, MOVED):
        a, b = inside(src, was), inside(src, now)
        if not a or not b or size(os.path.join(dest, a)) < 0:
            continue
        pa, pb = os.path.join(dest, a), os.path.join(dest, b)
        try:
            if not os.path.exists(pb):
                os.makedirs(os.path.dirname(pb), exist_ok=True)
                os.rename(pa, pb)
                if os.path.isfile(shadow(pa)):
                    os.rename(shadow(pa), shadow(pb))
                moved += 1
            elif size(pb) == size(pa) and not trash(dest, pa):  # there twice: one is enough
                stuck += 1
        except OSError:
            stuck += 1
    for path, n in rows(d, THROWN):
        rel = inside(src, path)
        if not rel or not n.isdigit() or size(path) == int(n):  # (back on the Mac: you brought that file back)
            continue
        base = os.path.basename(rel)
        for at in dict.fromkeys((rel, base, os.path.join(OLD, base))):  # where it was, or where its folder moved to
            p = os.path.join(dest, at)
            if size(p) == int(n):
                if trash(dest, p):
                    off += 1
                else:
                    stuck += 1
    swapped, twice, more = doubles(src, dest, checked(d, src))
    old = os.path.join(dest, OLD)
    try:  # the old folder goes once nothing of anyone's is left in it
        left = os.listdir(old)
        if all(f in (".DS_Store", "._.DS_Store") for f in left):
            for f in left:
                os.remove(os.path.join(old, f))
            os.rmdir(old)
    except OSError:
        pass
    return off, moved, stuck + more, swapped, twice


def say(off, moved, stuck, swapped=0, twice=0):
    s = lambda n: "" if n == 1 else "s"
    parts = ([f"{off} song{s(off)} you threw back taken off it (in the USB's Trash)"] if off else []) + \
            ([f"{moved} Soulseek song{s(moved)} moved in with the rest"] if moved else []) + \
            ([f"{swapped} file{s(swapped)} that {'was' if swapped == 1 else 'were'} another download of a song "
              "swapped for your library's (the old one is in the USB's Trash)"] if swapped else []) + \
            ([f"{twice} double{s(twice)} taken off it (a song that was on it twice; in the USB's Trash)"]
             if twice else []) + \
            ([f"PROBLEM: {stuck} file{s(stuck)} couldn't be moved (is the USB locked or full?)"] if stuck else [])
    return "; ".join(parts)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    said = say(*tidy(*sys.argv[1:4]))
    if said:
        print(f"{time.strftime('%F %R')}  USB: {said}")
