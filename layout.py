#!/usr/bin/env python3
"""The folders inside The Crate's own folder on a USB.

    python3 layout.py missing USB_FOLDER <list     # the "./song" lines of the list that aren't on the USB yet

Three ways to lay the songs out, picked on the Library Manager page (usb-layout.json):

    flat    every song in the one folder (how it always was; the choice unless you pick another)
    group   EDM / Other / No genre yet
    genre   EDM/<genre> / Other/<genre> / No genre yet      (a song sits in its first genre's folder; one with
            any EDM genre is EDM, under its first EDM genre, so the folders match the "EDM (all)" playlist)

With group or genre, "All songs" can be ticked too: an "All songs" folder beside them holds a copy of every song,
so a phone app or a deck that browses folders finds everything in one place as well (all_songs(); it needs room on
the USB for a second copy, and is left out, and said, when there isn't). The decks' libraries list each song once,
from its own folder.

Only the USB is laid out: the music folder on the Mac stays as it is. Only songs from this library are ever moved,
and only inside The Crate's own folder; nothing is copied twice and nothing is deleted. The USB itself is the
record of where each song sits, so there is no list to fall out of step: where() looks. Picking "flat" again puts
every song back in the one folder. Standard library only."""
import json, os, shutil, sys, unicodedata

import genres, usb_tidy

FILE = "usb-layout.json"
EDM, REST = "EDM", "Other"
OTHER = ["Hip Hop", "R&B", "Pop", "Rock"]  # the genres that aren't EDM, unless you say otherwise
MODES = ("flat", "group", "genre")
ALL = "All songs"  # the folder of copies, when "All songs" is ticked
ROOM = 5 << 30  # what the USB keeps free when it makes those copies (the decks need room for their own files too)
LEFT = (".DS_Store", "._.DS_Store")  # what macOS leaves in a folder: it doesn't make the folder "not empty"


def cf(name):
    """A file's or genre's name, however the drive spells its letters (accents, capitals, ":" or "：")."""
    return unicodedata.normalize("NFC", name).casefold().translate(usb_tidy.LOOK)


def load(dir):
    try:
        with open(os.path.join(dir, FILE)) as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = {}
    got = got if isinstance(got, dict) else {}
    other = got.get("other") if isinstance(got.get("other"), list) else OTHER
    return {"mode": got.get("mode") if got.get("mode") in MODES else "flat",
            "other": [x for x in other if isinstance(x, str) and x.strip()],
            "all": got.get("all") is True}


def save(dir, mode=None, other=None, all=None):
    cfg = load(dir)
    if mode in MODES:
        cfg["mode"] = mode
    if isinstance(all, bool):
        cfg["all"] = all
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


def copies(cfg):
    """Whether the USB gets the "All songs" folder of copies."""
    return cfg.get("all") is True and cfg["mode"] != "flat"


def unchanged(p, q, head=512 << 10, tail=128 << 10):
    """The copy still matches the song: its start and end, where a song's tags and cover sit, are the same. (A tag
    edit can keep the size and land within the 2 seconds a USB's clock tells apart, so the time can't say.)"""
    try:
        with open(p, "rb") as a, open(q, "rb") as b:
            if a.read(head) != b.read(head):
                return False
            for f in (a, b):
                f.seek(max(0, os.fstat(f.fileno()).st_size - tail))
            return a.read() == b.read()
    except OSError:
        return False


def all_songs(dest, at, cfg, dry=False):
    """Keeps the "All songs" folder in step: a copy of each song from where it sits (at: {song: where, inside The
    Crate's folder}), made again when the song's file changed, and taken off when the song left the USB or the
    folder isn't wanted. A copy is only ever taken off while the song's own file is still on the USB (else it goes
    to the USB's Trash, like a song you threw back). Returns (copies made, taken off, said: a line for the log)."""
    home = os.path.join(dest, ALL)
    if any(cf(w.replace("\\", "/").split("/")[0]) == cf(ALL) for w in at.values()):
        # songs of their own already sit in a folder of that name (one you picked for your Liked Songs, say): it isn't
        # The Crate's to fill or clear, so the copies are left off
        return 0, 0, (f'"{ALL}" is the name of a folder your own songs sit in, so the copies are left off: pick another '
                      "name for that folder to have them") if copies(cfg) else ""
    want = {}
    if copies(cfg):
        for rel, where in at.items():
            p = os.path.join(dest, where)
            if usb_tidy.size(p) >= 0:
                want.setdefault(cf(os.path.basename(rel)), p)  # (two songs of one name: the first)
    try:
        there = {cf(f): f for f in os.listdir(home) if not f.startswith(".") and f.lower().endswith(usb_tidy.AUDIO)}
    except OSError:
        there = {}
    made = off = 0
    for f in os.listdir(home) if not dry and os.path.isdir(home) else ():  # a copy that was cut short
        if f.startswith(".crate-"):
            try:
                os.remove(os.path.join(home, f))
            except OSError:
                pass
    for k, f in there.items():  # no longer wanted here
        if k in want:
            continue
        p = os.path.join(home, f)
        if dry:
            off += 1
            continue
        kept = [q for q in at.values() if cf(os.path.basename(q)) == k and usb_tidy.size(os.path.join(dest, q)) >= 0
                and not os.path.samefile(os.path.join(dest, q), p)]
        try:
            if kept:
                os.remove(p)
                if usb_tidy.size(usb_tidy.shadow(p)) >= 0:
                    os.remove(usb_tidy.shadow(p))
            elif not usb_tidy.trash(dest, p):
                continue
            off += 1
        except OSError:
            pass
    todo = []
    for k, p in want.items():
        q = os.path.join(home, there.get(k, os.path.basename(p)))
        try:
            if os.stat(p).st_size == os.stat(q).st_size and unchanged(p, q):
                continue
        except OSError:
            pass
        todo.append((p, q))
    said = ""
    need = sum(usb_tidy.size(p) for p, _ in todo)
    try:
        free = shutil.disk_usage(dest).free
    except OSError:
        free = 0
    if todo and free - need < ROOM:
        said = (f'PROBLEM: no room for the "{ALL}" copies ({-(-need >> 20)} MB more needed, and the USB keeps '
                f"{ROOM >> 30} GB free). Free some space, or untick All songs on the page")
        todo = []
    for p, q in todo:
        if dry:
            made += 1
            continue
        tmp = os.path.join(home, ".crate-" + os.path.basename(q))
        try:
            os.makedirs(home, exist_ok=True)
            shutil.copy2(p, tmp)
            os.replace(tmp, q)
            made += 1
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            said = f'PROBLEM: a copy in "{ALL}" couldn\'t be made ({e.strerror})'
            break
    if not dry and not copies(cfg) and empty(home):
        gone(home)
    if not said and (made or off):
        s = lambda n: "" if n == 1 else "s"
        said = "; ".join(([f'{made} song{s(made)} copied into "{ALL}"'] if made else []) +
                         ([f'{off} taken off "{ALL}"'] if off else []))
    return made, off, said


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
    out = {"mode": cfg["mode"], "all": copies(cfg), "songs": len(songs),
           "folders": [{"name": f.replace(os.sep, "/"), "songs": n} for f, n in sorted(folders.items(), key=lambda x: order(x[0])) if f]}
    if copies(cfg):
        out["folders"].insert(0, {"name": ALL, "songs": len(songs), "copies": True})
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
