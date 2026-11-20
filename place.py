#!/usr/bin/env python3
"""Where The Crate's own folder sits on a USB, and what it is called.

    python3 place.py where USB       # prints the folder on that USB (e.g. /Volumes/Lexar/SoundCloud Sync)
    python3 place.py move USB        # moves the folder to the place you chose, when it isn't there yet

Picked on the Library Manager page (Options): at the top of the USB (how it always was, the choice unless you pick
another), or inside a folder you already keep music in, so every song sits in one part of the USB. Kept in
usb-place.json, beside the app's other records.

Changing it moves only The Crate's own folder, by renaming it on the same USB: nothing is copied, nothing is
deleted, and no file or folder of yours is touched. The decks' libraries on the USB follow at the next update, each
track with its cues and analysis. Until a USB's folder has moved, everything keeps using it where it is (on()).
Standard library only."""
import json, os, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
FILE, NAME, MARK = "usb-place.json", "SoundCloud Sync", ".thecrate"
# never inside these: the decks' own folders, and a drive's own
TAKEN = ("pioneer", "engine library", "_serato_", "contents", "system volume information", "$recycle.bin",
         "lost.dir", "found.000")
LEFT = (".DS_Store", "._.DS_Store")  # what macOS leaves in a folder: it doesn't make the folder "not empty"


def cf(name):
    return unicodedata.normalize("NFC", name).casefold()


def part(name):
    """A folder's name, as you typed it, or "" when a drive can't hold it."""
    name = unicodedata.normalize("NFC", name or "").strip().strip(".").strip()
    if not name or len(name) > 60 or any(c in '\\/:*?"<>|' or ord(c) < 32 for c in name):
        return ""
    return name


def load(dir=HERE):
    """{"in": the folder it sits in ("" = the top of the USB), "name", "was": the places it had before}."""
    try:
        with open(os.path.join(dir, FILE)) as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = {}
    got = got if isinstance(got, dict) else {}
    inside = os.sep.join(p for p in (part(x) for x in str(got.get("in") or "").split("/")) if p)
    was = [w for w in got.get("was", []) if isinstance(w, str) and w] if isinstance(got.get("was"), list) else []
    return {"in": inside, "name": part(str(got.get("name") or "")) or NAME, "was": was}


def rel(cfg):
    return os.path.join(cfg["in"], cfg["name"]) if cfg["in"] else cfg["name"]


def check(inside, name):
    """Your pick, as {"in", "name"}. Raises ValueError, in plain words, for a place it can't be."""
    parts = [p for p in str(inside or "").replace("\\", "/").split("/") if p.strip()]
    if len(parts) > 3 or any(not part(p) for p in parts):
        raise ValueError("That folder's name has a sign a USB can't hold.")
    if any(cf(part(p)) in TAKEN for p in parts):
        raise ValueError("That folder belongs to the decks. Pick another one.")
    if not part(name or NAME):
        raise ValueError("That name has a sign a USB can't hold (or is empty).")
    if cf(part(name or NAME)) in TAKEN:
        raise ValueError("That name belongs to the decks. Pick another one.")
    return {"in": os.sep.join(part(p) for p in parts), "name": part(name or NAME)}


def save(dir, inside, name):
    """Your pick on the page (check() says no to a place it can't be)."""
    cfg, new = load(dir), check(inside, name)
    before = rel(cfg)
    was = [w for w in cfg["was"] + [before] if cf(w) != cf(rel(new))]
    new["was"] = list(dict.fromkeys(was))[-8:]
    tmp = os.path.join(dir, FILE + ".tmp")
    with open(tmp, "w") as f:
        json.dump({**new, "in": new["in"].replace(os.sep, "/")}, f, indent=1)
    os.replace(tmp, os.path.join(dir, FILE))
    return load(dir)


def known(dir=HERE):
    """Every place the folder has had, the chosen one first. The very first one is always among them."""
    cfg = load(dir)
    return list(dict.fromkeys([rel(cfg)] + cfg["was"][::-1] + [NAME]))


def ours(usb, r):
    """A folder at this place on the USB that is The Crate's: it carries The Crate's note (usb_ask.py leaves it in
    the folder on every USB it may change), or it is the first place of all, which was never anyone else's."""
    p = os.path.join(usb, r)
    return os.path.isdir(p) and (cf(r) == cf(NAME) or os.path.isfile(os.path.join(p, MARK)))


def taken(usb, r):
    """Something of yours is at this place on the USB already: a folder with things in it (or a file) that isn't
    The Crate's. The Crate never takes it for its own."""
    p = os.path.join(usb, r)
    return os.path.lexists(p) and not ours(usb, r) and not empty(p)


def on(usb, dir=HERE):
    """The folder on this USB right now, from the USB's top: the chosen place when The Crate's folder is there,
    else a place it had before (it hasn't moved yet), else the chosen place (nothing of The Crate's is on this USB
    yet), unless something of yours has that name here: then the first place of all."""
    all = known(dir)
    return next((r for r in all if ours(usb, r)), NAME if taken(usb, all[0]) else all[0])


def clash(usb, dir=HERE):
    """The chosen place, when something of yours has it on this USB (so The Crate's folder stays where it is)."""
    want = rel(load(dir))
    return want.replace(os.sep, "/") if on(usb, dir) != want and taken(usb, want) else ""


def folder(usb, dir=HERE):
    return os.path.join(usb, on(usb, dir))


def web(usb, dir=HERE):
    """on(), as the decks' libraries spell a path."""
    return unicodedata.normalize("NFC", on(usb, dir)).replace(os.sep, "/")


def others(usb, dir=HERE):
    """The other places it has had, as the decks' libraries spell them: a track's row left at one follows to web()."""
    now = web(usb, dir)
    return [w for w in (unicodedata.normalize("NFC", r).replace(os.sep, "/") for r in known(dir)) if w != now]


def tops(usb, dir=HERE):
    """The folders at the top of this USB that The Crate's folder could sit in (yours; never the decks' own)."""
    mine = {cf(r.split(os.sep)[0]) for r in known(dir) if os.sep not in r}
    try:
        return sorted((f for f in os.listdir(usb) if not f.startswith((".", "$")) and cf(f) not in TAKEN
                       and cf(f) not in mine and os.path.isdir(os.path.join(usb, f))), key=str.lower)
    except OSError:
        return []


def empty(path):
    try:
        return all(f in LEFT for f in os.listdir(path))
    except OSError:
        return False


def todo(usb, dir=HERE):
    """(from, to) when this USB's folder isn't at the chosen place yet, else None."""
    want, now = rel(load(dir)), on(usb, dir)
    if now == want or not os.path.isdir(os.path.join(usb, now)) or taken(usb, want):
        return None
    return now, want


def move(usb, dir=HERE):
    """Moves The Crate's folder on this USB to the chosen place. Returns a line for the log ("" when it is there
    already, or isn't on this USB at all). Only that one folder is renamed; a folder it leaves empty behind (one it
    sat in, and only The Crate's own earlier pick) stays: it may be yours."""
    step = todo(usb, dir)
    if not step:
        return ""
    a, b = (os.path.join(usb, r) for r in step)
    same = os.path.exists(b) and os.path.samefile(a, b)  # only the capitals changed
    if os.path.exists(b) and not same:
        if not (os.path.isdir(b) and empty(b)):
            raise OSError(f'something called "{step[1]}" is on the USB already')
        for f in os.listdir(b):
            os.remove(os.path.join(b, f))
        os.rmdir(b)
    os.makedirs(os.path.dirname(b), exist_ok=True)
    os.rename(a, b)
    return f'The Crate\'s folder moved from "{step[0]}" to "{step[1]}"'.replace(os.sep, "/")


def status(usb="", dir=HERE):
    """For the page: the chosen place, and for a plugged-in USB the folders it could sit in, whether its folder
    still has to move, and a name of yours that is in the way."""
    cfg = load(dir)
    out = {"in": cfg["in"].replace(os.sep, "/"), "name": cfg["name"]}
    if usb and os.path.isdir(usb):
        out.update(tops=tops(usb, dir), now=web(usb, dir), move=bool(todo(usb, dir)), clash=clash(usb, dir))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("where", "move"):
        sys.exit(__doc__)
    if sys.argv[1] == "where":
        print(folder(sys.argv[2]))
    else:
        try:
            said = move(sys.argv[2])
        except OSError as e:
            sys.exit(f"USB PROBLEM: The Crate's folder couldn't be moved ({e})")
        if said:
            print(said)
