#!/usr/bin/env python3
"""Songs from another USB into this Mac's library: a friend's stick, or songs on your own USB that The Crate didn't
put there. You pick playlists (the other USB's rekordbox library) or folders on the Library Manager page; each song
is copied into the music folder on the Mac, where it is one of your songs like any other: safety-checked, listened
to (tempo and key), given genres, written into every deck library and copied to your own USB, once, by usb.sh.
What a rekordbox USB knows about a song comes along: the playlists it is in, and its analysis files (beat grid,
waveform, and the hot cues and memory cues kept in them), which rekordbox_usb.py puts on your USB's rekordbox
library.

The other USB is only ever read: its library is read from a copy made on the Mac.

  friend.py list DIR             what can be copied, as JSON (the page asks this)
  friend.py copy DIR SRC USB     copy the lists named on stdin (JSON: ["rb:3", "dir:Music/House"]), then the safety
                                 check and the decks' libraries
  friend.py dump FILE            (the private Python) a rekordbox USB library as plain data

Also kept here: the songs you asked a better copy of (better.tsv; soulseek.py looks for them with the rest).
Standard library only; reading a rekordbox library needs the private Python (dj-setup.sh). Without it, folders can
still be copied."""
import fcntl, json, os, re, shutil, subprocess, sys, tempfile, time, unicodedata, zlib

import place

TAKEN = (".flac", ".wav", ".aiff", ".aif", ".mp3", ".m4a")  # what both the safety check and the decks' libraries take
AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus", ".alac", ".aac")  # any song, for doubles
PY = next((p for p in map(os.path.expanduser, ("~/.local/share/crate-dj/python/bin/python3",
                                               "~/.local/share/crate-dj/venv/bin/python")) if os.path.exists(p)),
          os.path.expanduser("~/.local/share/crate-dj/python/bin/python3"))
RECORD = "dj-friends.json"     # what came from another USB: {"lists": {name: {"from", "rels"}}, "songs": {rel: {...}}}
CARRIED = "friend-anlz"        # the analysis files that came along, one folder a song
PROGRESS = ".friend-copy.json"  # the copy running now: the page shows how far it is
CACHE = ".friend-library.json"  # the other USB's rekordbox library as last read
BETTER = "better.tsv"          # songs you asked a better copy of: name, link, "", seconds, artist, title, the file now
THROWN = "usb-thrown.tsv"      # as soulseek.py names it: files you threw away (never copied in again)
FOLDER = "The Crate"  # its folder in the decks' libraries (its own folder on a USB: place.py)
SKIP = {"pioneer", "engine library", "_serato_", "_serato_backup", "system volume information", "$recycle.bin",
        "thrown back by the crate", "quarantine"}
KINDS = {1: ".mp3", 3: ".mp4", 4: ".m4a", 5: ".flac", 11: ".wav", 12: ".aiff"}  # rekordbox's own codes
SPARE = 2 * 1024 ** 3  # the Mac's disk is never filled to the brim


def root():
    return os.environ.get("VOLUMES") or "/Volumes"  # overridable for tests, as usb.sh and dj.py


def low(ext, kbps):
    """Below gig quality: an MP3 under 320 kbps or an AAC under 256. Lossless files never are. (Files that say 320
    often measure a hair under, so the line sits just below.)"""
    ext = ext.lower()
    return bool(kbps) and ((ext == ".mp3" and kbps < 318) or (ext in (".m4a", ".aac", ".mp4") and kbps < 250))


def one(name):
    """Two files are the same song when their names match once capitals, accents and punctuation are set aside."""
    s = unicodedata.normalize("NFKD", os.path.splitext(name)[0]).lower()
    return re.sub(r"[^a-z0-9]+", "", s) or unicodedata.normalize("NFC", s)


def load(dir):
    try:
        with open(os.path.join(dir, RECORD)) as f:
            got = json.load(f)
        return {"lists": dict(got.get("lists") or {}), "songs": dict(got.get("songs") or {})}
    except (OSError, ValueError, AttributeError):
        return {"lists": {}, "songs": {}}


def save(dir, rec):
    tmp = os.path.join(dir, RECORD + ".tmp")
    with open(tmp, "w") as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(dir, RECORD))


def rows(dir, name, least=2):
    try:
        with open(os.path.join(dir, name), errors="replace") as f:
            return [p for p in (l.rstrip("\n").split("\t") for l in f) if len(p) >= least and p[0]]
    except OSError:
        return []


def wanted(dir):
    """The songs a better copy is being looked for: [[name, link, "", seconds, artist, title, the file now, again]].
    again ("1"): the better copy that came in was thrown back itself, so the file named is gone and the search goes
    on; without it, a file that is gone means you threw the song away, and the search stops."""
    return [(r + [""] * 8)[:8] for r in rows(dir, BETTER)]


def save_wanted(dir, lines):
    tmp = os.path.join(dir, BETTER + ".tmp")
    with open(tmp, "w") as f:
        f.writelines("\t".join(re.sub(r"[\t\r\n]+", " ", str(x)) for x in r) + "\n" for r in lines)
    os.replace(tmp, os.path.join(dir, BETTER))


def moved(dir, old, new):
    """A song's file was swapped for another (a better copy): its playlists from the other USB follow. Its analysis
    files don't: they were made from the old file."""
    rec = load(dir)
    for l in rec["lists"].values():
        l["rels"] = list(dict.fromkeys(new if r == old else r for r in l.get("rels", [])))
    was = rec["songs"].pop(old, None)
    if was:
        shutil.rmtree(os.path.dirname(was.get("anlz") or "") or os.path.join(dir, CARRIED, "-"), ignore_errors=True)
    save(dir, rec)


def prune(dir, src):
    """Songs that left the music folder (thrown away) leave the record, with the analysis files kept for them."""
    rec = load(dir)
    if not rec["songs"] and not rec["lists"] or not os.path.isdir(src):
        return
    gone = [r for r in rec["songs"] if not os.path.isfile(os.path.join(src, r))]
    waiting = {w[6] for w in wanted(dir) if w[7]}  # a better copy is still on its way: its place in the lists is kept
    there = lambda r: r in waiting or os.path.isfile(os.path.join(src, r))
    lists = {n: {**l, "rels": [r for r in l.get("rels", []) if there(r)]} for n, l in rec["lists"].items()}
    lists = {n: l for n, l in lists.items() if l["rels"]}
    if not gone and lists == rec["lists"]:
        return
    for r in gone:
        a = rec["songs"].pop(r).get("anlz") or ""
        if a.startswith(os.path.join(dir, CARRIED) + os.sep):
            shutil.rmtree(os.path.dirname(a), ignore_errors=True)
    rec["lists"] = lists
    save(dir, rec)


def within(base, path):
    """The file a USB's library names, only when it really is on that USB (a library is someone else's data)."""
    full = os.path.realpath(os.path.join(base, path.lstrip("/")))
    return full if full.startswith(os.path.realpath(base) + os.sep) else ""


def dump(db_file):
    """(the private Python) A rekordbox USB library as plain data."""
    import logging
    logging.disable(logging.WARNING)
    from pyrekordbox.onelibrary import OneLibrary
    from sqlalchemy import text
    lib = OneLibrary(db_file)
    run = lambda sql: lib.session.execute(text(sql))
    try:
        tracks = {}
        for i, path, size, kind, kbps, length, bpm, key, anlz, title, artist in run(
                "SELECT c.content_id, c.path, c.fileSize, c.fileType, c.bitrate, c.length, c.bpmx100, k.name, "
                "c.analysisDataFilePath, c.title, a.name FROM content c LEFT JOIN key k ON k.key_id = c.key_id "
                "LEFT JOIN artist a ON a.artist_id = c.artist_id_artist"):
            tracks[str(i)] = {"path": path or "", "size": size or 0, "kind": kind or 0, "kbps": kbps or 0,
                              "length": length or 0, "bpm": bpm or 0, "key": key or "", "anlz": anlz or "",
                              "title": title or "", "artist": artist or ""}
        lists = [list(r) for r in run("SELECT playlist_id, name, attribute, playlist_id_parent FROM playlist "
                                      "ORDER BY playlist_id_parent, sequenceNo")]
        members = {}
        for p, c in run("SELECT playlist_id, content_id FROM playlist_content ORDER BY playlist_id, sequenceNo"):
            members.setdefault(str(p), []).append(str(c))
        cols = [r[1] for r in run("PRAGMA table_info(cue)")]
        cues = {}
        for r in run("SELECT * FROM cue ORDER BY content_id, cue_id") if cols else []:
            row = dict(zip(cols, r))
            cues.setdefault(str(row["content_id"]), []).append(
                {k: v for k, v in row.items() if k not in ("cue_id", "content_id") and not isinstance(v, bytes)})
        name = run("SELECT deviceName FROM property").scalar() or ""
    finally:
        lib.close()
    return {"name": name, "tracks": tracks, "lists": lists, "members": members, "cues": cues}


def library_of(dir, vol):
    """The rekordbox library on a USB as plain data (dump), read from a copy made on the Mac, and kept until the
    USB's library changes. None when it has none, or this Mac can't read one (no private Python)."""
    db = os.path.join(root(), vol, "PIONEER", "rekordbox", "exportLibrary.db")
    if not os.path.isfile(db) or not os.path.exists(PY):
        return None
    try:
        stamp = [vol] + [[os.path.getsize(db + x), int(os.path.getmtime(db + x))] if os.path.isfile(db + x) else 0
                         for x in ("", "-wal")]
    except OSError:
        return None
    try:
        with open(os.path.join(dir, CACHE)) as f:
            got = json.load(f)
        if got["stamp"] == stamp:
            return got["lib"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    tmp = tempfile.mkdtemp(prefix="crate-friend-")
    try:
        for x in ("", "-wal", "-shm"):
            if os.path.isfile(db + x):
                shutil.copy2(db + x, os.path.join(tmp, "exportLibrary.db" + x))
        r = subprocess.run([PY, os.path.abspath(__file__), "dump", os.path.join(tmp, "exportLibrary.db")],
                           capture_output=True, text=True, timeout=180)
        lib = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        lib = None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if lib:
        try:
            with open(os.path.join(dir, CACHE + ".tmp"), "w") as f:
                json.dump({"stamp": stamp, "lib": lib}, f)
            os.replace(os.path.join(dir, CACHE + ".tmp"), os.path.join(dir, CACHE))
        except OSError:
            pass
    return lib


def folders(base, own, contents):
    """The folders on a USB that hold songs themselves: [(the folder inside the USB, [its songs])]. The decks' own
    folders are passed over, and on your own USB The Crate's folder too (those songs are yours already)."""
    out, mine = [], place.on(base)

    def walk(rel, depth):
        try:
            names = sorted(os.listdir(os.path.join(base, rel)), key=str.lower)
        except OSError:
            return
        songs = [n for n in names if not n.startswith(".") and n.lower().endswith(TAKEN)]
        if songs:
            out.append((rel, songs))
        if depth >= 4:
            return
        for n in names:
            if n.startswith(".") or n.lower() in SKIP or len(out) >= 300:
                continue
            if own and os.path.join(rel, n) == mine or not rel and not contents and n == "Contents":
                continue
            if os.path.isdir(os.path.join(base, rel, n)):
                walk(os.path.join(rel, n), depth + 1)
    walk("", 0)
    return out


def tree(base, rel):
    """Every song under a folder, however deep (what rekordbox's own export leaves under "Contents")."""
    out = []
    for at, dirs, files in os.walk(os.path.join(base, rel)):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        out += [os.path.join(os.path.relpath(at, base), f) for f in sorted(files)
                if not f.startswith(".") and f.lower().endswith(TAKEN)]
    return out


def kbps_of(t):
    """A track's bitrate as the USB's library gives it; worked out from its size and length where it doesn't."""
    ext = os.path.splitext(t["path"])[1].lower()
    if ext in (".flac", ".wav", ".aiff", ".aif"):
        return 0
    return t["kbps"] or (round(t["size"] * 8 / t["length"] / 1000) if t["length"] and t["size"] else 0)


def named(lib):
    """Each playlist of a USB's library with its folders' names in front: {id: "Folder / Playlist"}; and the ids
    inside The Crate's own folder."""
    by = {str(i): (n or "", a, str(p)) for i, n, a, p in lib["lists"]}
    crate = {i for i, (n, a, p) in by.items() if a == 1 and p == "0" and n == FOLDER}
    out, ours = {}, set()
    for i, (n, a, p) in by.items():
        parts, up, mine = [n], p, i in crate
        while up in by and len(parts) < 8:
            parts.insert(0, by[up][0])
            mine = mine or up in crate
            up = by[up][2]
        if mine:
            ours.add(i)
        if a != 1:
            out[i] = " / ".join(parts)
    return out, ours


def pick(dir, vol, ids=None):
    """What a USB offers, or with ids only those: [(id, name, [track], kind)], each track {"path" (inside the USB),
    "size", and for a rekordbox library its "anlz", "bpm", "key", "cues", "kbps"}. And the USB's own name."""
    base = os.path.join(root(), vol)
    own = vol == (rows(dir, "usb.txt", 1) or [[""]])[0][0].strip()
    lib = library_of(dir, vol)
    out = []
    if lib:
        ok = {}
        for i, t in lib["tracks"].items():
            p = t["path"]
            if p.lower().endswith(TAKEN) and not (own and p.startswith("/" + place.web(base) + "/")):
                ok[i] = {**t, "kbps": kbps_of(t), "cues": lib["cues"].get(i, [])}
        names, ours = named(lib)
        if ok:
            out.append(("rb:all", "Everything in its rekordbox library", list(ok.values()), "all"))
        for i, name in names.items():
            got = [ok[c] for c in lib["members"].get(i, []) if c in ok]
            if got and not (own and i in ours):
                out.append(("rb:" + i, name, got, "playlist"))
    elif os.path.isdir(os.path.join(base, "Contents")) and (not ids or "tree:Contents" in ids):
        songs = tree(base, "Contents")
        if songs:
            out.append(("tree:Contents", "Everything rekordbox put on it", [{"path": "/" + s} for s in songs], "all"))
    if not ids or any(i.startswith("dir:") for i in ids):
        for rel, songs in folders(base, own, not lib and not os.path.isdir(os.path.join(base, "Contents"))):
            out.append(("dir:" + rel, rel or "Loose songs on it",
                        [{"path": "/" + os.path.join(rel, s)} for s in songs], "folder"))
    if ids:
        out = [o for o in out if o[0] in ids]
    return out, (lib or {}).get("name") or vol, own


def volumes(dir=""):
    try:
        return sorted(v for v in os.listdir(root()) if v not in ("Macintosh HD", "Recovery") and not v.startswith(".")
                      and os.path.isdir(os.path.join(root(), v)))
    except OSError:
        return []


def scan(dir, src):
    """For the page: every plugged-in USB with songs that can be copied, and what each offers."""
    usbs = []
    for vol in volumes():
        lists, name, own = pick(dir, vol)
        base = os.path.join(root(), vol)
        shown = []
        for i, title, tracks, kind in lists:
            size = 0
            for t in tracks:
                if "size" not in t:
                    try:
                        t["size"] = os.path.getsize(base + t["path"])
                    except OSError:
                        t["size"] = 0
                size += t["size"]
            shown.append({"id": i, "name": title, "kind": kind, "count": len(tracks), "mb": round(size / 1e6),
                          "low": sum(low(os.path.splitext(t["path"])[1], t.get("kbps", 0)) for t in tracks)})
        if shown:
            older = not any(s["id"].startswith("rb:") for s in shown) and \
                os.path.isfile(os.path.join(base, "PIONEER", "rekordbox", "export.pdb"))
            usbs.append({"usb": vol, "name": name, "own": own, "lists": shown, "older": older,
                         "rekordbox": any(s["id"].startswith("rb:") for s in shown)})
    try:
        free = shutil.disk_usage(src if os.path.isdir(src) else os.path.dirname(src)).free
    except OSError:
        free = 0
    return {"usbs": usbs, "freeMb": round(max(0, free - SPARE) / 1e6), "reader": os.path.exists(PY)}


def progress(dir):
    """The copy running now ({"usb", "done", "total"}), or None."""
    try:
        with open(os.path.join(dir, PROGRESS)) as f:
            p = json.load(f)
        os.kill(int(p["pid"]), 0)
        return {"usb": p["usb"], "done": p["done"], "total": p["total"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def carry(dir, base, who, t):
    """What the other USB's rekordbox library knows about a track, kept beside the app: its analysis files (beat
    grid, waveform, cues), its tempo and key, and its cue rows."""
    out = {k: t[k] for k in ("bpm", "key", "cues") if t.get(k)}
    dat = within(base, t.get("anlz") or "") if (t.get("anlz") or "").upper().endswith(".DAT") else ""
    if dat and os.path.isfile(dat):
        to = os.path.join(dir, CARRIED, f"{zlib.crc32((who + t['path']).encode()):08x}")
        try:
            os.makedirs(to, exist_ok=True)
            for part in ("DAT", "EXT", "2EX"):
                if os.path.isfile(dat[:-3] + part):
                    shutil.copyfile(dat[:-3] + part, os.path.join(to, "ANLZ0000." + part))
            out["anlz"] = os.path.join(to, "ANLZ0000.DAT")
        except OSError:
            pass
    return out


def copy(dir, src, vol, ids):
    """Copies the picked lists' songs into the music folder. Returns what happened as counts, or a sentence when it
    couldn't start. A song the library already has (the same name, any kind of file) isn't copied again, it only
    joins the playlist; one you threw away before stays away."""
    base = os.path.join(root(), vol)
    if vol not in volumes():
        return "That USB isn't plugged in any more."
    lock = open(os.path.join(dir, ".friend.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return "A copy from another USB is already running."
    picked, who, _ = pick(dir, vol, set(ids))
    todo = list({t["path"]: t for _, _, tracks, _ in picked for t in tracks}.values())
    if not todo:
        return "Nothing to copy there."
    os.makedirs(src, exist_ok=True)
    rec = load(dir)
    have = {}
    for f in sorted(os.listdir(src)):
        if not f.startswith(".") and f.lower().endswith(AUDIO) and os.path.isfile(os.path.join(src, f)):
            have.setdefault(one(f), f)
    thrown = {(r[0], r[1]) for r in rows(dir, THROWN)}
    origin = {(v.get("from"), v.get("path"), v.get("size")): r for r, v in rec["songs"].items()}
    n = dict(copied=0, had=0, thrown=0, gone=0, full=0, failed=0)
    placed = {}

    def tell(done):
        with open(os.path.join(dir, PROGRESS + ".tmp"), "w") as f:
            json.dump({"pid": os.getpid(), "usb": vol, "done": done, "total": len(todo)}, f)
        os.replace(os.path.join(dir, PROGRESS + ".tmp"), os.path.join(dir, PROGRESS))
    try:
        for done, t in enumerate(todo):
            tell(done)
            file, name = within(base, t["path"]), os.path.basename(t["path"])
            try:
                size = os.path.getsize(file) if file and os.path.isfile(file) else -1
            except OSError:
                size = -1
            if size <= 0 or not name.lower().endswith(TAKEN) or name.startswith("."):
                n["gone"] += 1
                continue
            rel = origin.get((who, t["path"], size))
            if rel and os.path.isfile(os.path.join(src, rel)):  # copied in before
                placed[t["path"]] = rel
                n["had"] += 1
                continue
            dest = os.path.join(src, name)
            if (dest, str(size)) in thrown:
                n["thrown"] += 1
                continue
            if one(name) in have:
                placed[t["path"]] = have[one(name)]
                n["had"] += 1
                continue
            if shutil.disk_usage(src).free < size + SPARE:
                n["full"] = len(todo) - done
                break
            try:
                shutil.copyfile(file, dest + ".part")
                if os.path.getsize(dest + ".part") != size:
                    raise OSError("cut short")
                os.replace(dest + ".part", dest)
            except OSError:
                try:
                    os.remove(dest + ".part")
                except OSError:
                    pass
                n["failed"] += 1
                continue
            have[one(name)] = placed[t["path"]] = name
            n["copied"] += 1
            rec["songs"][name] = {"from": who, "path": t["path"], "size": size, **carry(dir, base, who, t)}
            if n["copied"] % 25 == 0:
                save(dir, rec)
        for _, title, tracks, kind in picked:
            rels = [placed[t["path"]] for t in tracks if placed.get(t["path"])]
            if rels and kind != "all":  # ("everything" is no playlist of its own)
                title = f"{os.path.basename(title) if kind == 'folder' else title} ({who})"
                l = rec["lists"].setdefault(title, {"from": who, "rels": []})
                l["rels"] = list(dict.fromkeys(l.get("rels", []) + rels))
        save(dir, rec)
    finally:
        try:
            os.remove(os.path.join(dir, PROGRESS))
        except OSError:
            pass
    return n


def say(who, n):
    s = lambda k: "" if n[k] == 1 else "s"
    parts = [f"{n['copied']} song{s('copied')} copied into your library"] + \
            ([f"{n['had']} you already had (not copied again)"] if n["had"] else []) + \
            ([f"{n['thrown']} left out: you threw {'it' if n['thrown'] == 1 else 'them'} away before"] if n["thrown"] else []) + \
            ([f"{n['gone']} not on it any more or not a kind of file the decks take"] if n["gone"] else []) + \
            ([f"PROBLEM: {n['failed']} couldn't be copied"] if n["failed"] else []) + \
            ([f"PROBLEM: this Mac's disk is nearly full, so {n['full']} song{s('full')} stayed behind"] if n["full"] else [])
    return f'from "{who}": ' + "; ".join(parts)


def log(dir, text):
    with open(os.path.join(dir, "dj.log"), "a") as f:
        f.write(time.strftime("%F %R") + "  " + text + "\n")


if __name__ == "__main__":
    a = sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    if len(a) == 2 and a[0] == "dump":
        print(json.dumps(dump(a[1]), default=str))
    elif len(a) == 2 and a[0] == "list":
        print(json.dumps(scan(a[1], os.environ.get("SRC") or os.path.expanduser("~/Music/SoundCloud Sync"))))
    elif len(a) == 4 and a[0] == "copy":
        dir, src, vol = a[1:]
        who = vol
        try:
            got = copy(dir, src, vol, json.load(sys.stdin))
            who = (library_of(dir, vol) or {}).get("name") or vol
        except Exception as e:  # never silent: the page shows the last lines of dj.log
            got = f"{e!r}"[:300]
        log(dir, f'COPY PROBLEM from "{vol}": {got}' if isinstance(got, str) else "USB copy " + say(who, got))
        if not isinstance(got, str) and got["copied"] + got["had"]:
            # Each new file is checked like any download before it counts, then the decks' libraries (and your own
            # USB, when it's in) follow: usb.sh copies and runs dj.py; with no USB of yours in, dj.py alone.
            with open(os.path.join(dir, "safety.log"), "a") as err:
                subprocess.run([sys.executable, os.path.join(here, "safety.py"), "check", dir, src], stderr=err)
            mine = (rows(dir, "usb.txt", 1) or [[""]])[0][0].strip()
            env = {**os.environ, "SRC": src}
            if mine and os.path.isdir(os.path.join(root(), mine)):
                subprocess.run([os.path.join(here, "usb.sh")], env=env, stdin=subprocess.DEVNULL)
            else:
                with open(os.path.join(dir, "dj.log"), "a") as err:
                    subprocess.run([sys.executable, os.path.join(here, "dj.py"), dir, src, "--wait"], env=env, stderr=err)
        try:  # the page's progress line ends here, whatever happened
            os.remove(os.path.join(dir, PROGRESS))
        except OSError:
            pass
    else:
        sys.exit(__doc__)
