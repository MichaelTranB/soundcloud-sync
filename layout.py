#!/usr/bin/env python3
"""The folders inside The Crate's own folder on a USB.

    python3 layout.py missing USB_FOLDER <list     # the "./song" lines of the list that aren't on the USB yet

Three ways to lay the songs out, picked on the Library Manager page (usb-layout.json):

    flat    every song in the one folder (how it always was; the choice unless you pick another)
    group   EDM / Other / No genre yet
    genre   EDM/<genre> / Other/<genre> / No genre yet      (a song sits in its first genre's folder; one with
            any EDM genre is EDM, under its first EDM genre, so the folders match the "EDM (all)" playlist)

With group or genre, "All songs" can be ticked too. Kept as one copy ("one": true, the way it is set when ticked
from now on) it is a list, "All songs.m3u8" beside the folders, naming every song where it sits: each song is stored
once (onecopy()). As copies (how it was first made) an "All songs" folder holds a second copy of every song
(all_songs(); it needs room on the USB, and is left out, and said, when there isn't). Going from copies to one copy
takes the copies off only after your Go ahead for that stick (usb_ask "one"), and only a copy whose twin in its own
folder is the same file byte for byte. The decks' libraries list each song once, from its own folder, either way.

    python3 layout.py onecopy USB_FOLDER     # what keeping one copy would do there (only reads): kept, off, GB

Only the USB is laid out: the music folder on the Mac stays as it is. Only songs from this library are ever moved,
and only inside The Crate's own folder; nothing is copied twice and nothing is deleted. The USB itself is the
record of where each song sits, so there is no list to fall out of step: where() looks. Picking "flat" again puts
every song back in the one folder. Standard library only."""
import hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, unicodedata

import genres, usb_tidy

FILE = "usb-layout.json"
EDM, REST = "EDM", "Other"
OTHER = ["Hip Hop", "R&B", "Pop", "Rock"]  # the genres that aren't EDM, unless you say otherwise
MODES = ("flat", "group", "genre")
ALL = "All songs"  # the folder of copies, when "All songs" is ticked
LIST = ALL + ".m3u8"  # the list instead, with one copy of each song (onecopy())
OURS = "#THECRATE"  # a line in that list: The Crate wrote it (a list of that name without it is someone's: untouched)
STAMP = ".all-songs.json"  # in that folder: what each copy was made from (mark())
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
            "all": got.get("all") is True, "one": got.get("one") is True}


def save(dir, mode=None, other=None, all=None, one=None):
    cfg = load(dir)
    if mode in MODES:
        cfg["mode"] = mode
    if isinstance(all, bool):
        cfg["all"] = all
    if isinstance(one, bool):
        cfg["one"] = one
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
    return cfg.get("all") is True and cfg["mode"] != "flat" and cfg.get("one") is not True


def listed(cfg):
    """Whether "All songs" is a list (All songs.m3u8) naming each song where it is stored, once."""
    return cfg.get("all") is True and cfg["mode"] != "flat" and cfg.get("one") is True


def mark(p):
    """What says a song's file on the USB is still the very one a copy was made from: its size, its time and when
    that file was made (a file put in its place, when tags changed on the Mac, is a new file even at the same size)."""
    st = os.stat(p)
    return [st.st_size, int(st.st_mtime), round(getattr(st, "st_birthtime", 0), 2)]


def same_file(home, a, b):
    try:
        return os.path.samefile(os.path.join(home, a), os.path.join(home, b))
    except OSError:
        return False


def keep(made_from, home):
    """Writes down the copies The Crate made in "All songs" (STAMP). If that can't be written, the copies it doesn't
    name are left as they are from then on: never a song of someone else's taken off."""
    path = os.path.join(home, STAMP)
    try:
        if made_from:
            with open(path + ".tmp", "w") as f:
                json.dump(made_from, f, ensure_ascii=False)
            os.replace(path + ".tmp", path)
        elif os.path.lexists(path):
            os.remove(path)
        return True
    except OSError as e:
        print(f'what was copied into "{ALL}" couldn\'t be noted ({e.strerror})', file=sys.stderr)
        return False


def all_songs(dest, at, cfg, dry=False, ok=False, usb=""):
    """Keeps the "All songs" folder in step: a copy of each song from where it sits (at: {song: where, inside The
    Crate's folder}), made again when the song's file changed, and taken off when the song left the USB or the
    folder isn't wanted. A copy is only ever taken off while the song's own file is still on the USB (else it goes
    to the USB's Trash, like a song you threw back). Returns (copies made, taken off, said: a line for the log)."""
    home = os.path.join(dest, ALL)
    if any(cf(w.replace("\\", "/").split("/")[0]) == cf(ALL) for w in at.values()):
        # songs of their own already sit in a folder of that name (one you picked for your Liked Songs, say): it isn't
        # The Crate's to fill or clear, so the copies are left off
        return 0, 0, (f'"{ALL}" is the name of a folder your own songs sit in, so the copies are left off: pick another '
                      "name for that folder to have them") if copies(cfg) or listed(cfg) else ""
    if listed(cfg):
        return onecopy(dest, at, cfg, ok, usb, dry)
    if not dry:
        unlist(dest)
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
    try:  # the copies The Crate made, each with what it was made from (STAMP, in the folder): only those are its own
        made_from = json.load(open(os.path.join(home, STAMP)))
        made_from = made_from if isinstance(made_from, dict) else {}
    except (OSError, ValueError):
        made_from = {}
    mine = {k: f for k, f in there.items() if k in made_from}  # anything else in there was put by someone: untouched
    for k, f in list(mine.items()) if not dry else ():  # a copy spelled the way its song was before a rename (a sign
        to = os.path.basename(want.get(k, ""))  # a USB can't hold, now its look-alike) takes the song's spelling
        if to and to != f and not (os.path.lexists(os.path.join(home, to)) and not same_file(home, f, to)):
            try:
                usb_tidy.rename(os.path.join(home, f), os.path.join(home, to))  # (a "._" twin left: usbsafe.clean)
                mine[k] = there[k] = to
            except OSError:
                pass
    made = off = 0
    taken = set()
    for f in os.listdir(home) if not dry and os.path.isdir(home) else ():  # a copy that was cut short
        if f.startswith(".crate-"):
            try:
                os.remove(os.path.join(home, f))
            except OSError:
                pass
    for k, f in mine.items():  # no longer wanted here
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
            taken.add(k)
        except OSError:
            pass
    todo = []
    for k, p in want.items():
        if k in there and k not in mine:  # a song of that name someone put there: left as it is
            continue
        q = os.path.join(home, there.get(k, os.path.basename(p)))
        try:
            if made_from.get(cf(os.path.basename(q))) == mark(p) and os.stat(q).st_size == os.stat(p).st_size:
                continue
        except OSError:
            pass
        todo.append((p, q))
    said = ""
    need = grown = 0  # the most room the copies take at any point: each one is whole beside the one it replaces,
    for p, q in todo:  # which then frees its space
        size, was = usb_tidy.size(p), max(usb_tidy.size(q), 0)
        need = max(need, grown + size)
        grown += size - was
    try:
        free = shutil.disk_usage(dest).free
    except OSError:
        free = 0
    if todo and free - need < ROOM:
        said = (f'PROBLEM: no room for the "{ALL}" copies ({-(-need >> 20)} MB more needed, and the USB keeps '
                f"{ROOM >> 30} GB free). Free some space, or untick All songs on the page")
        todo = []
    if todo and not dry:  # each copy is noted as The Crate's before it is put there (with no marker yet, so a copy
        # cut short is made again next time), so a USB pulled out mid-way never leaves a copy it doesn't own
        for p, q in todo:
            made_from.setdefault(cf(os.path.basename(q)), [])
        try:
            os.makedirs(home, exist_ok=True)
        except OSError:
            pass
        if not keep(made_from, home):
            said, todo = f'PROBLEM: the copies in "{ALL}" couldn\'t be noted on the USB, so none were made', []
    for p, q in todo:
        if dry:
            made += 1
            continue
        tmp = os.path.join(home, ".crate-" + os.path.basename(q))
        try:
            os.makedirs(home, exist_ok=True)
            shutil.copy2(p, tmp)
            os.replace(tmp, q)
            made_from[cf(os.path.basename(q))] = mark(p)
            made += 1
            if made % 20 == 0:  # (noted as it goes: fewer made again after a USB is pulled out mid-way)
                keep(made_from, home)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            said = f'PROBLEM: a copy in "{ALL}" couldn\'t be made ({e.strerror})'
            break
    if not dry and os.path.isdir(home):
        keep({k: v for k, v in made_from.items() if k in want or (k in mine and k not in taken)}, home)
    if not dry and not copies(cfg) and empty(home):
        gone(home)
    if not said and (made or off):
        s = lambda n: "" if n == 1 else "s"
        said = "; ".join(([f'{made} song{s(made)} copied into "{ALL}"'] if made else []) +
                         ([f'{off} taken off "{ALL}"'] if off else []))
    return made, off, said


def digest(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def stamped(home):
    """The copies The Crate made in "All songs" (STAMP) and the ones of them still there: (made_from, {key: name})."""
    try:
        with open(os.path.join(home, STAMP)) as f:
            made_from = json.load(f)
        made_from = made_from if isinstance(made_from, dict) else {}
    except (OSError, ValueError):
        made_from = {}
    try:
        there = [f for f in os.listdir(home) if not f.startswith(".") and f.lower().endswith(usb_tidy.AUDIO)]
    except OSError:
        there = []
    return made_from, {cf(f): f for f in there if cf(f) in made_from}


def twins(dest):
    """Every song file in The Crate's folder outside "All songs" (the files the decks' libraries list): {key: [path]}."""
    out = {}
    for root, dirs, files in os.walk(dest):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (root == dest and cf(d) == cf(ALL)))
        for f in sorted(files):
            if not f.startswith(".") and f.lower().endswith(usb_tidy.AUDIO):
                out.setdefault(cf(f), []).append(os.path.join(root, f))
    return out


ANALYSER = os.environ.get("CRATE_DJ_PY") or next(
    (p for p in map(os.path.expanduser, ("~/.local/share/crate-dj/python/bin/python3",
                                         "~/.local/share/crate-dj/venv/bin/python")) if os.path.exists(p)), "")
READ_OL = ("import logging, sys\nlogging.disable(logging.CRITICAL)\nfrom pyrekordbox.onelibrary import OneLibrary\n"
           "db = OneLibrary(sys.argv[1])\n"
           "print(sum(sys.argv[2] in (c.path or '').replace('\\\\', '/') for c in db.get_content().all()))\n")


def onelibrary(lib, needle):
    """True: the USB's rekordbox library (exportLibrary.db) lists a file whose path holds needle; "unread": it
    couldn't be read (no analyser Python, or an error), which counts as a yes; False: it doesn't."""
    if not ANALYSER or not os.path.exists(ANALYSER):
        return "unread"
    tmp = tempfile.mkdtemp()
    try:
        for x in ("", "-wal", "-shm"):
            if os.path.isfile(lib + x):
                shutil.copy2(lib + x, os.path.join(tmp, "exportLibrary.db" + x))
        r = subprocess.run([ANALYSER, "-c", READ_OL, os.path.join(tmp, "exportLibrary.db"), needle],
                           capture_output=True, text=True, timeout=300)
        n = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""
        return "unread" if not n.isdigit() else int(n) > 0
    except (OSError, subprocess.SubprocessError):
        return "unread"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pointed(usb):
    """The deck libraries on the USB that list a file inside an "All songs" folder (or couldn't be read): while
    any does, no copy there is taken off, so no deck loses a track."""
    who, needle = [], "/" + ALL + "/"
    db = os.path.join(usb, "Engine Library", "Database2", "m.db")
    if os.path.isfile(db):
        tmp = tempfile.mkdtemp()
        try:  # (read from a copy on the Mac, with its journal: the USB's file is never opened for writing)
            for x in ("", "-wal"):
                if os.path.isfile(db + x):
                    shutil.copy2(db + x, os.path.join(tmp, "m.db" + x))
            c = sqlite3.connect(os.path.join(tmp, "m.db"))
            try:
                if c.execute("SELECT count(*) FROM Track WHERE replace(path, '\\', '/') LIKE ?",
                             ("%" + needle + "%",)).fetchone()[0]:
                    who.append("Engine DJ")
            finally:
                c.close()
        except (OSError, sqlite3.Error):
            who.append("Engine DJ (couldn't be read)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    lib = os.path.join(usb, "PIONEER", "rekordbox", "exportLibrary.db")
    if os.path.isfile(lib):  # (the newest decks' library is locked: read through pyrekordbox, from a copy on the Mac)
        hit = onelibrary(lib, needle)
        if hit:
            who.append("rekordbox" if hit is True else "rekordbox (couldn't be read)")
    files = [("rekordbox", os.path.join(usb, "PIONEER", "rekordbox", "export.pdb")),
             ("rekordbox", os.path.join(usb, "PIONEER", "rekordbox", "exportExt.pdb")),
             ("Serato", os.path.join(usb, "_Serato_", "database V2"))]
    crates = os.path.join(usb, "_Serato_", "Subcrates")
    files += [("Serato", os.path.join(crates, f)) for f in (sorted(os.listdir(crates)) if os.path.isdir(crates) else [])
              if f.endswith(".crate")]
    for name, f in files:  # (paths sit in these as plain text: the needle in any of the ways they spell it)
        if name in who or not os.path.isfile(f):
            continue
        try:
            with open(f, "rb") as h:
                b = h.read()
        except OSError:
            who.append(name + " (couldn't be read)")
            continue
        if any(needle.encode(e) in b for e in ("utf-8", "utf-16-le", "utf-16-be")):
            who.append(name)
    return who


def doubles(dest, dry=True):
    """The copies in "All songs" that have a twin in their own folder, the same file byte for byte (a dry look only
    weighs size, for the page: quick). Not dry: those copies are taken off. Returns (taken off, left, bytes freed)."""
    home = os.path.join(dest, ALL)
    made_from, mine = stamped(home)
    tw = twins(dest) if mine else {}
    off = left = freed = 0
    for k, f in sorted(mine.items()):
        p = os.path.join(home, f)
        s = usb_tidy.size(p)
        cands = [q for q in tw.get(k, []) if s >= 0 and usb_tidy.size(q) == s and not same_file(home, p, q)]
        try:
            sum_ = digest(p) if cands and dry != "quick" else ""
            twin = cands[0] if cands and dry == "quick" else next((q for q in cands if digest(q) == sum_), None)
        except OSError:
            twin = None
        if not twin:  # no verified twin: this copy stays, whatever happens
            left += 1
            continue
        if not dry:
            try:
                os.remove(p)
                if usb_tidy.size(usb_tidy.shadow(p)) >= 0:
                    os.remove(usb_tidy.shadow(p))
            except OSError:
                left += 1
                continue
        off += 1
        freed += s
    if not dry and os.path.isdir(home):
        for f in os.listdir(home):
            if f.startswith(".crate-"):  # a copy cut short, The Crate's own
                try:
                    os.remove(os.path.join(home, f))
                except OSError:
                    pass
        made_from, mine = stamped(home)
        keep({k: v for k, v in made_from.items() if k in mine}, home)
        if empty(home):
            gone(home)
    return off, left, freed


def mine_list(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return any(l.strip() == OURS for l in f)
    except OSError:
        return False


def write_list(dest):
    """All songs.m3u8: every song in The Crate's folder, where it is stored, as paths from the list itself."""
    path = os.path.join(dest, LIST)
    if os.path.lexists(path) and not mine_list(path):
        return f'a "{LIST}" of someone else\'s is there, so it was left as it is'
    songs = sorted((p for ps in twins(dest).values() for p in ps), key=lambda p: cf(os.path.relpath(p, dest)))
    text = "#EXTM3U\n#PLAYLIST:" + ALL + "\n" + OURS + "\n" + \
           "".join(("./" if os.path.relpath(p, dest).startswith("#") else "") +  # (a line starting # is a comment)
                   os.path.relpath(p, dest).replace(os.sep, "/") + "\n" for p in songs)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return ""
    except OSError:
        pass
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(path + ".tmp", path)
    except OSError as e:
        return f'PROBLEM: "{LIST}" couldn\'t be written ({e.strerror})'
    return ""


def unlist(dest):
    """The list goes when "All songs" isn't wanted as one (only The Crate's own)."""
    path = os.path.join(dest, LIST)
    if mine_list(path):
        try:
            os.remove(path)
        except OSError:
            pass


def gb(n):
    return f"{n / (1 << 30):.1f} GB"


def onecopy(dest, at, cfg, ok, usb, dry=False):
    """"All songs" as one copy of each song: the list, and the copies The Crate made in the "All songs" folder taken
    off, each only once its twin in its own folder is the same file byte for byte. ok: your Go ahead for this stick
    (usb_ask "one"); until then a USB that has the copies keeps them, kept in step as before."""
    home = os.path.join(dest, ALL)
    if stamped(home)[1] and not ok and not dry:
        made, off, said = all_songs(dest, at, {**cfg, "one": False})
        wait = f'"{ALL}" stays as copies until you say Go ahead on the page'
        return made, off, "; ".join(x for x in (said, wait) if x)
    said = []
    off = 0
    if stamped(home)[1]:
        who = pointed(usb) if usb else []
        if who:  # (the copies stay and are kept in step as before; no list is written)
            made, off, said = all_songs(dest, at, {**cfg, "one": False})
            stop = f'PROBLEM: {", ".join(who)} on the USB lists songs in "{ALL}", so its copies stay'
            return made, off, "; ".join(x for x in (said, stop) if x)
        off, left, freed = doubles(dest, dry=dry)
        if off:
            said.append(f'one copy of each song: {off} double{"" if off == 1 else "s"} taken off "{ALL}" ({gb(freed)} freed)')
        if left:
            said.append(f'{left} left in "{ALL}": no twin the same byte for byte in its own folder')
    if not dry:
        said.append(write_list(dest))
    return 0, off, "; ".join(x for x in said if x)


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
                    usb_tidy.rename(a, b)
                    if os.path.isfile(usb_tidy.shadow(a)):
                        usb_tidy.rename(usb_tidy.shadow(a), usb_tidy.shadow(b))
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
    out = {"mode": cfg["mode"], "all": copies(cfg) or listed(cfg), "one": listed(cfg), "songs": len(songs),
           "folders": [{"name": f.replace(os.sep, "/"), "songs": n} for f, n in sorted(folders.items(), key=lambda x: order(x[0])) if f]}
    if copies(cfg) or listed(cfg):
        out["folders"].insert(0, {"name": LIST if listed(cfg) else ALL, "songs": len(songs), "copies": copies(cfg)})
    if dest and os.path.isdir(dest):
        out.update(move=arrange(dest, songs, cfg, dry=True)[0],
                   on=len(songs) - len(missing(dest, [s["rel"] for s in songs])))
    return out


def usb_of(path):
    path = os.path.abspath(path)
    while not os.path.ismount(path) and os.path.dirname(path) != path:
        path = os.path.dirname(path)
    return path


def dry_run(dest):
    """What keeping one copy would do on this USB, read only: songs kept, doubles off, space freed."""
    home = os.path.join(dest, ALL)
    who = pointed(usb_of(dest)) if stamped(home)[1] else []
    off, left, freed = doubles(dest, dry=True)
    kept = sum(len(v) for v in twins(dest).values())
    lines = [f"songs kept (one copy each, in their own folders): {kept}",
             f'doubles taken off "{ALL}" (same byte for byte as their twin): {off}',
             f"space freed: {gb(freed)}",
             f'left in "{ALL}" (no identical twin, never taken off): {left}']
    if who:
        lines.append(f'PROBLEM: {", ".join(who)} lists songs in "{ALL}": nothing would be taken off until that changes')
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "onecopy":
        sys.exit(print(dry_run(sys.argv[2])))
    if len(sys.argv) != 3 or sys.argv[1] != "missing":
        sys.exit(__doc__)
    lines = [l.rstrip("\n") for l in sys.stdin]
    rels = [l[2:] if l.startswith("./") else l for l in lines]
    out = set(missing(sys.argv[2], rels))
    sys.stdout.writelines(l + "\n" for l, r in zip(lines, rels) if r in out)
