#!/usr/bin/env python3
"""Keeps the USB's copy of the music folder in step with two things done on the Mac (usb.sh itself only ever adds):

  a song you threw back on the page ("Wrong or bad file": usb-thrown.tsv) leaves the USB as well. Its copy there
    (the same place, the same size) goes to the USB's own Trash, never deleted;
  Soulseek files that moved out of their old "From Soulseek" folder (soulseek-moved.tsv) move the same way on the
    USB, so they are not copied onto it a second time.

  usb_tidy.py DIR SRC DEST    DIR: the app folder; SRC: the music folder on the Mac; DEST: its copy on the USB

Only files inside DEST are ever touched; anything else on the USB is left alone. Run by usb.sh before it copies, and
by dj.py before it writes the decks' libraries. Standard library only."""
import os, shutil, sys, time

OLD, MOVED, THROWN = "From Soulseek", "soulseek-moved.tsv", "usb-thrown.tsv"  # as soulseek.py names them


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


def tidy(d, src, dest):
    """Returns (thrown-back songs taken off the USB, songs moved in with the rest, ones that couldn't be moved)."""
    off = moved = stuck = 0
    if not os.path.isdir(dest):
        return 0, 0, 0
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
    old = os.path.join(dest, OLD)
    try:  # the old folder goes once nothing of anyone's is left in it
        left = os.listdir(old)
        if all(f in (".DS_Store", "._.DS_Store") for f in left):
            for f in left:
                os.remove(os.path.join(old, f))
            os.rmdir(old)
    except OSError:
        pass
    return off, moved, stuck


def say(off, moved, stuck):
    s = lambda n: "" if n == 1 else "s"
    parts = ([f"{off} song{s(off)} you threw back taken off it (in the USB's Trash)"] if off else []) + \
            ([f"{moved} Soulseek song{s(moved)} moved in with the rest"] if moved else []) + \
            ([f"PROBLEM: {stuck} file{s(stuck)} couldn't be moved (is the USB locked or full?)"] if stuck else [])
    return "; ".join(parts)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    said = say(*tidy(*sys.argv[1:4]))
    if said:
        print(f"{time.strftime('%F %R')}  USB: {said}")
