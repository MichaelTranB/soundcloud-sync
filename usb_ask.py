#!/usr/bin/env python3
"""Asks before The Crate changes a USB that already has things on it. Until you say "Go ahead" on the page, nothing
on that USB is touched: no song copied, no list written, nothing moved to its Trash.

  an empty USB needs no asking: there is nothing of anyone's on it to change;
  a USB with files, folders or a DJ library on it is asked about once. The yes is remembered for that very stick (a
    small note, .thecrate, in The Crate's own folder on it, so another stick with the same name is asked about too);
  a new kind of change (KINDS grows with the app) asks again, and "Stop" on the page takes the yes back.

  usb_ask.py check DIR USB    exit 0: go ahead; exit 3: waiting for your OK (USB: the drive, e.g. /Volumes/Lexar)

What The Crate does once allowed: songs go only into its own folder (SoundCloud Sync, or where you chose: place.py), its playlists are added
beside the ones already in the USB's rekordbox, Engine DJ and Serato lists (each list is copied to dj-backups
first), and your own files, folders and playlists are never moved, renamed or deleted. Standard library only."""
import json, os, sys, time, uuid

import place, usb_tidy

OK, MARK = "usb-ok.json", place.MARK
KINDS = ["songs", "lists", "convert"]  # what a yes covers: songs into its folder, playlists into the DJ lists, AIFF
SYSTEM = ("system volume information", "$recycle.bin", "lost.dir", "found.000")  # a drive's own, not content
LISTS = (("rekordbox", os.path.join("PIONEER", "rekordbox")), ("Engine DJ", "Engine Library"),
         ("Serato", "_Serato_"))


def load(dir):
    try:
        with open(os.path.join(dir, OK)) as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else {}
    except (OSError, ValueError):
        return {}


def save(dir, rec):
    tmp = os.path.join(dir, OK + ".tmp")
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, os.path.join(dir, OK))


def mark(usb):
    """The id The Crate left on this stick when you allowed it ("" when it never was)."""
    return place.note(usb)[0]


def paused(usb):
    """How a stick you said "Not now" to is remembered, without writing on it: its name and size."""
    try:
        s = os.statvfs(usb)
        return f"no:{os.path.basename(os.path.normpath(usb))}:{s.f_blocks * s.f_frsize}"
    except OSError:
        return "no:" + os.path.basename(os.path.normpath(usb))


def content(usb):
    """Something of someone's is on it: any file or folder beside The Crate's own, or songs in its folder that it
    has no note of putting there."""
    try:
        top = [f for f in os.listdir(usb) if not f.startswith(".") and f.lower() not in SYSTEM]
    except OSError:
        return False
    at = usb
    for p in place.on(usb).split(os.sep):  # down to The Crate's folder: anything beside the way there is someone's
        if any(place.cf(f) != place.cf(p) for f in top):
            return True
        at = os.path.join(at, p)
        try:
            top = [f for f in os.listdir(at) if not f.startswith(".")]
        except OSError:
            return False
    return bool(top)


def state(dir, usb):
    """"ok": allowed (or empty); "ask": has content, not asked yet; "no": you said Not now."""
    rec, i = load(dir), mark(usb)
    if i and rec.get(i, {}).get("yes") and set(KINDS) <= set(rec[i].get("kinds", [])):
        return "ok"
    if not content(usb):
        return "ok"
    return "no" if rec.get(paused(usb)) else "ask"


def answer(dir, usb, yes):
    """Your answer on the page. A yes leaves the stick's note in The Crate's folder on it; a no writes nothing there."""
    rec = load(dir)
    if yes:
        i = mark(usb) or uuid.uuid4().hex
        os.makedirs(place.folder(usb), exist_ok=True)
        place.noted(place.folder(usb), i, place.note(usb)[1])  # (the places the folder had on this USB stay noted)
        rec[i] = {"yes": True, "kinds": KINDS, "name": os.path.basename(os.path.normpath(usb)),
                  "day": time.strftime("%Y-%m-%d")}
        rec.pop(paused(usb), None)
    else:
        if mark(usb) in rec:
            rec[mark(usb)]["yes"] = False
        rec[paused(usb)] = {"day": time.strftime("%Y-%m-%d")}
    save(dir, rec)


def ready(dir, usb):
    """True when The Crate may change this USB now. An empty stick is noted as allowed on the way."""
    s = state(dir, usb)
    if s == "ok" and not mark(usb) and os.access(usb, os.W_OK):
        try:
            answer(dir, usb, True)
        except OSError:
            pass
    return s == "ok"


def what(dir, src, usb):
    """For the page's question: what would change on this USB, in numbers."""
    import layout
    dest, rels = place.folder(usb), usb_tidy.checked(dir, src)
    at = layout.places(dest, rels)  # (a USB laid out in folders has each song in its genre's folder)
    new = sum(1 for r in rels if usb_tidy.size(os.path.join(dest, at[r])) < 0)
    swap = sum(1 for r in rels if 0 <= usb_tidy.size(os.path.join(dest, at[r])) != usb_tidy.size(os.path.join(src, r)))
    thrown = sum(1 for p, n in usb_tidy.rows(dir, usb_tidy.THROWN)
                 if n.isdigit() and usb_tidy.inside(src, p) and usb_tidy.size(p) != int(n)
                 and usb_tidy.size(os.path.join(dest, usb_tidy.inside(src, p))) == int(n))
    return {"name": os.path.basename(os.path.normpath(usb)), "state": state(dir, usb), "songs": new,
            "trash": swap + thrown, "content": True, "lists": [n for n, p in LISTS if os.path.exists(os.path.join(usb, p))]}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "check":
        sys.exit(__doc__)
    sys.exit(0 if ready(sys.argv[2], sys.argv[3]) else 3)
