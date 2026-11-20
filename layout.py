#!/usr/bin/env python3
"""The folders inside The Crate's own folder on a USB.

    python3 layout.py missing USB_FOLDER <list     # the "./song" lines of the list that aren't on the USB yet

Three ways to lay the songs out, picked on the Library Manager page (usb-layout.json):

    flat    every song in the one folder (how it always was; the choice unless you pick another)
    group   EDM / Other / No genre yet
    genre   EDM/<genre> / Other/<genre> / No genre yet      (a song sits in its first genre's folder; one with
            any EDM genre is EDM, under its first EDM genre, so the folders match the "EDM (all)" playlist)

Only the USB is laid out: the music folder on the Mac stays as it is. Only songs from this library are ever moved,
and only inside The Crate's own folder; nothing is copied twice and nothing is deleted. The USB itself is the
record of where each song sits, so there is no list to fall out of step: where() looks. Picking "flat" again puts
every song back in the one folder. Standard library only."""
import json, os, sys, unicodedata

import genres, usb_tidy

FILE = "usb-layout.json"
EDM, REST = "EDM", "Other"
OTHER = ["Hip Hop", "R&B", "Pop", "Rock"]  # the genres that aren't EDM, unless you say otherwise
MODES = ("flat", "group", "genre")
LEFT = (".DS_Store", "._.DS_Store")  # what macOS leaves in a folder: it doesn't make the folder "not empty"


def cf(name):
    """A file's or genre's name, however the drive spells its letters (accents, capitals)."""
    return unicodedata.normalize("NFC", name).casefold()


def load(dir):
    try:
        with open(os.path.join(dir, FILE)) as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = {}
    got = got if isinstance(got, dict) else {}
    other = got.get("other") if isinstance(got.get("other"), list) else OTHER
    return {"mode": got.get("mode") if got.get("mode") in MODES else "flat",
            "other": [x for x in other if isinstance(x, str) and x.strip()]}


def save(dir, mode=None, other=None):
    cfg = load(dir)
    if mode in MODES:
        cfg["mode"] = mode
    if other is not None:
        cfg["other"] = list(dict.fromkeys(x.strip() for x in other if isinstance(x, str) and x.strip()))
    tmp = os.path.join(dir, FILE + ".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, os.path.join(dir, FILE))
    return cfg


def safe(name):
    """A genre's name as a folder's name (a drive can't hold some signs in a name)."""
    out = "".join("-" if c in '\\/:*?"<>|' or ord(c) < 32 else c for c in unicodedata.normalize("NFC", name))
    return out.strip(" .") or "Genre"


def edm(gs, cfg):
    """Any EDM genre at all: what the "EDM (all)" playlist and the EDM folder both go by."""
    other = {cf(x) for x in cfg["other"]}
    return any(cf(x) not in other for x in gs)


def group(gs, cfg):
    """EDM or Other ("" when the song has no genre yet). A song with any EDM genre is EDM, as in the playlist."""
    return "" if not gs else EDM if edm(gs, cfg) else REST


def main(gs, cfg):
    """The genre a song is filed under: its first EDM one, else its first."""
    other = {cf(x) for x in cfg["other"]}
    return next((x for x in gs if cf(x) not in other), gs[0])


def folder(gs, cfg):
    """The folder a song with these genres belongs in, inside The Crate's folder ("" = the folder itself)."""
    if cfg["mode"] == "flat":
        return ""
    if not gs:
        return safe(genres.NONE)
    return group(gs, cfg) if cfg["mode"] == "group" else os.path.join(group(gs, cfg), safe(main(gs, cfg)))


def tops():
    return {cf(EDM), cf(REST), cf(safe(genres.NONE))}


def where(dest):
    """What is on the USB right now: {file name: [(folder, the name as the USB spells it), ...]}, the one folder
    first, then the layout's own folders (EDM, Other, No genre yet and the genre folders in them). Nothing else in
    there is looked at."""
    out = {}

    def scan(at, depth):
        try:
            found = sorted(os.listdir(os.path.join(dest, at)))
        except OSError:
            return
        for f in found:
            if f.startswith("."):
                continue
            if os.path.isdir(os.path.join(dest, at, f)):
                if depth < 2 and (at or cf(f) in tops()):
                    scan(os.path.join(at, f), depth + 1)
            elif f.lower().endswith(usb_tidy.AUDIO):
                out.setdefault(cf(f), []).append((at, f))

    scan("", 0)
    for l in out.values():
        l.sort(key=lambda x: x[0] != "")
    return out


def plain(rels):
    """The songs this can file: straight in the music folder, and the only one of that name."""
    count = {}
    for r in rels:
        count[cf(r)] = count.get(cf(r), 0) + 1
    return {r for r in rels if os.sep not in r and count[cf(r)] == 1}


def spot(spots, rel):
    """Where this song's file is on the USB (as where() found it), inside The Crate's folder; rel when it isn't in
    one of the folders (or not on the USB at all)."""
    got = spots.get(cf(rel)) if os.sep not in rel else None
    return os.path.join(got[0][0], rel) if got else rel


def places(dest, rels):
    """{song: where it sits on this USB right now}."""
    spots, can = where(dest), plain(rels)
    return {r: spot(spots, r) if r in can else r for r in rels}


def missing(dest, rels):
    """The songs that aren't on the USB anywhere yet."""
    spots = where(dest)
    return [r for r in rels if usb_tidy.size(os.path.join(dest, spot(spots, r))) < 0]


def rows(paths, prefix):
    """The rows of a deck's library that sit in The Crate's folder, by file name: {name: [path, ...]}."""
    out = {}
    for p in paths:
        if p.startswith(prefix):
            out.setdefault(cf(p.rsplit("/", 1)[-1]), []).append(p)
    return out


def old(by, s, now, there):
    """A song whose file moved on the USB (into another folder, or became an AIFF): the row it had at its old
    place, so the same track follows with its cues and analysis. by: rows(); there(path): is a file still at that
    row's place? (then it is another track's row, and is left alone)."""
    for n in [s["rel"]] + ([s["was"]] if s.get("was") else []):
        for p in by.get(cf(os.path.basename(n)), []):
            if p != now and not there(p):
                return p
    return ""


def same(by, have, songs, spell, there):
    """The Crate's folder itself moved on the USB (place.py): each song's row at the same place under a root the
    folder had before, {rel: row}. Those rows leave by, so old() never hands one to another song that only shares
    its file name. spell(song): the paths that row could have."""
    out = {}
    for s in songs:
        for p in spell(s):
            if p in have and not there(p):
                out[s["rel"]] = p
                names = by.get(cf(p.rsplit("/", 1)[-1]), [])
                if p in names:
                    names.remove(p)
                break
    return out


def empty(path):
    try:
        return all(f in LEFT for f in os.listdir(path))
    except OSError:
        return False


def sweep(dest):
    """Takes away the layout's folders that hold nothing any more. Only those: EDM, Other, No genre yet and the
    genre folders inside them."""
    for top in sorted(os.listdir(dest)) if os.path.isdir(dest) else []:
        if cf(top) not in tops() or not os.path.isdir(os.path.join(dest, top)):
            continue
        t = os.path.join(dest, top)
        for sub in sorted(os.listdir(t)):
            if os.path.isdir(os.path.join(t, sub)) and empty(os.path.join(t, sub)):
                gone(os.path.join(t, sub))
        if empty(t):
            gone(t)


def gone(path):
    try:
        for f in os.listdir(path):
            os.remove(os.path.join(path, f))
        os.rmdir(path)
    except OSError:
        pass


def arrange(dest, songs, cfg, dry=False):
    """Files each library song on the USB into the folder it belongs in. Returns (songs moved, ones that couldn't
    be, doubles taken off, {song: where it sits now}). dry: nothing is touched, the numbers say what would be."""
    spots, can = where(dest), plain([s["rel"] for s in songs])
    moved = stuck = twice = 0
    at = {}
    for s in songs:
        rel = s["rel"]
        have = spots.get(cf(rel)) if rel in can else None
        if not have:  # not on the USB yet (usb.sh copies it in; the next look files it), or not one this files
            at[rel] = rel
            continue
        if s.get("apart"):  # a Liked Song you haven't given a genre yet: it stays where it is
            at[rel] = os.path.join(have[0][0], rel)
            continue
        want = folder(s.get("genres") or [], cfg)
        got = next(((f, n) for f, n in have if cf(f) == cf(want)), None)
        real = os.path.join(dest, *got) if got else ""  # the file that stays, where it is right now
        if got is None:
            f, n = have[0]
            a, b = os.path.join(dest, f, n), os.path.join(dest, want, rel)
            try:
                if dry:
                    pass
                elif os.path.exists(b):
                    raise OSError("something is there already")
                else:
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    os.rename(a, b)
                    if os.path.isfile(usb_tidy.shadow(a)):
                        os.rename(usb_tidy.shadow(a), usb_tidy.shadow(b))
                moved += 1
                got, have, real = (want, rel), have[1:], a if dry else b
            except OSError:
                stuck += 1
                got, have, real = (f, n), have[1:], a
        else:
            have = [h for h in have if h != got]
        at[rel] = os.path.join(got[0], rel)
        for f, n in have:  # the same song a second time, in another of the folders: one is enough
            p = os.path.join(dest, f, n)
            if usb_tidy.size(p) == usb_tidy.size(real) and (dry or usb_tidy.trash(dest, p)):
                twice += 1
    if not dry:
        sweep(dest)
    return moved, stuck, twice, at


def say(moved, stuck, twice, flat=False):
    s = lambda n: "" if n == 1 else "s"
    how = "put back in the one folder" if flat else f"filed into {'its' if moved == 1 else 'their'} folder{s(moved)}"
    parts = ([f"{moved} song{s(moved)} {how}"] if moved else []) + \
            ([f"{twice} double{s(twice)} taken off it (in the USB's Trash)"] if twice else []) + \
            ([f"PROBLEM: {stuck} song{s(stuck)} couldn't be moved (is the USB locked or full?)"] if stuck else [])
    return "; ".join(parts)


def plan(dest, songs, cfg):
    """For the page, before anything moves: how many songs each folder would hold, and how many would move on the
    USB that is plugged in (dest "" when none is)."""
    folders, can = {}, plain([s["rel"] for s in songs])
    for s in songs:  # a song in a folder of its own (your Liked Songs) stays in it: counted there
        f = folder(s.get("genres") or [], cfg) if s["rel"] in can and not s.get("apart") else os.path.dirname(s["rel"])
        folders[f] = folders.get(f, 0) + 1
    order = lambda f: (f.split(os.sep)[0] == safe(genres.NONE), f.split(os.sep)[0] != EDM, f.lower())
    out = {"mode": cfg["mode"], "songs": len(songs),
           "folders": [{"name": f.replace(os.sep, "/"), "songs": n} for f, n in sorted(folders.items(), key=lambda x: order(x[0])) if f]}
    if dest and os.path.isdir(dest):
        out.update(move=arrange(dest, songs, cfg, dry=True)[0],
                   on=len(songs) - len(missing(dest, [s["rel"] for s in songs])))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "missing":
        sys.exit(__doc__)
    lines = [l.rstrip("\n") for l in sys.stdin]
    rels = [l[2:] if l.startswith("./") else l for l in lines]
    out = set(missing(sys.argv[2], rels))
    sys.stdout.writelines(l + "\n" for l, r in zip(lines, rels) if r in out)
