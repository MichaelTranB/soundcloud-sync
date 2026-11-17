"""Keeps cue points in step across the places a Crate song lives: Engine DJ on the USB (the Prime 4), rekordbox on
this Mac, and the USB's own rekordbox library (its cue table and its analysis files, where club and friends' CDJs
save the cues you set on them). Hot cues A-H, memory cues and saved loops.

How it decides, per song and per cue slot (hot cue A..H, or a memory cue/loop at a given time):
  - what each place held after the last run is kept in DIR/cues-state.json; a place that now holds something else
    was edited there;
  - one edit: it wins. Edits in several places: the newest wins (the places' own edit times where they keep them);
  - a cue missing in a place is never taken as "deleted": it is simply sent there. Nothing is ever deleted;
  - every value that gets replaced is kept in DIR/cues-history.json, and undo() puts the last run's back.
What can't be carried is listed in plain words: memory cues (not loops) have no place in Engine; Engine has 8 loops;
MP3 and M4A cues are kept between rekordbox and the USB only, never sent to or from Engine, because Engine and
rekordbox start MP3/AAC time at different points (an offset of 0-52 ms that depends on the file's encoder, with no
published rule); beat grids are not carried (each app keeps its own).

Only Crate songs (in the USB's "SoundCloud Sync" folder, matched by their place inside it) are read or touched;
every other row and file stays exactly as it is. A place that isn't there (no USB, no Engine library, no rekordbox)
is skipped and catches up next run. rekordbox's files (the Mac's library and the USB's) are written only while
rekordbox is closed; while it is open they are read, and written next run. Before each write the file is copied to
dj-backups/ (the last 20 kept). Engine cues are written only to songs the deck has analysed (it needs the song's
sample rate and would redo cues on an unanalysed song); the rest wait for the Prime 4.

Runs on the private Python (pyrekordbox, for rekordbox's locked libraries). From dj.py: a JSON job on stdin
({"dir", "src", "usb", "rels"?, "undo"?}), one line out."""
import calendar, json, os, shutil, sqlite3, struct, sys, time, unicodedata, uuid, zlib

MUSIC = "SoundCloud Sync"
LETTERS = "ABCDEFGH"
NOT_ENGINE = (".mp3", ".m4a", ".mp4", ".aac")  # their time starts differently in Engine and rekordbox
KIND = {0: 1, 1: 2, 2: 3, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9}  # rekordbox's Kind for hot cue A..H (4 is an active loop)
SLOT = {k: i for i, k in KIND.items()}
# Engine's own pad colours when none was picked (slots 1-2 as seen on a Prime 4, the rest libdjinterop's standard).
ENGINE_DEFAULT = ["#ff2a3e", "#07c5ff", "#b855bf", "#ba2a41", "#86c64b", "#20c67c", "#00a8b1", "#158ee2"]
# rekordbox's hot cue colours by code (Deep Symmetry / beat-link), and the 16 its colour menu offers.
HOT = {1: "305aff", 2: "5073ff", 3: "508cff", 4: "50a0ff", 5: "50b4ff", 6: "50b0f2", 7: "50aee8", 8: "45acdb",
       9: "00e0ff", 10: "19daf0", 11: "32d2e6", 12: "21b4b9", 13: "20aaa0", 14: "1fa392", 15: "19a08c", 16: "14a584",
       17: "14aa7d", 18: "10b176", 19: "30d26e", 20: "37de5a", 21: "3ceb50", 22: "28e214", 23: "7dc13d",
       24: "8cc832", 25: "9bd723", 26: "a5e116", 27: "a5dc0a", 28: "aad208", 29: "b4c805", 30: "b4be04",
       31: "bab404", 32: "c3af04", 33: "e1aa00", 34: "ffa000", 35: "ff9600", 36: "ff8c00", 37: "ff7500",
       38: "e0641b", 39: "e0461e", 40: "e0301e", 41: "e02823", 42: "e62828", 43: "ff376f", 44: "ff2d6f",
       45: "ff127b", 46: "f51e8c", 47: "eb2da0", 48: "e637b4", 49: "de44cf", 50: "de448d", 51: "e630b4",
       52: "e619dc", 53: "e600ff", 54: "dc00ff", 55: "cc00ff", 56: "b432ff", 57: "b93cff", 58: "c542ff",
       59: "aa5aff", 60: "aa72ff", 61: "8272ff", 62: "6473ff"}
HOT = {k: "#" + v for k, v in HOT.items()}
MENU = (49, 56, 60, 62, 1, 5, 9, 14, 18, 22, 26, 30, 32, 38, 42, 45)
# Memory cue colours: rekordbox's Color 0-7 (the analysis files' color_id 1-8).
MEMORY = ["#ffafaf", "#ff0000", "#ffc800", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#800080"]
PLACES = {"mac": "rekordbox", "engine": "the Prime 4", "usbdb": "the USB", "usbanlz": "the USB"}
RANK = {"usbdb": 0, "mac": 1, "engine": 2, "usbanlz": 3}  # who wins a tie in time (a deck's edit is the latest)


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def letter(key):
    return LETTERS.index(key[4:]) if key.startswith("hot:") else -1


def clean(v):
    """A cue in its one shared form: {"ms", "end"?, "name"?, "color"?} with empty parts left out."""
    if not v:
        return None
    out = {"ms": int(v["ms"])}
    if v.get("end") is not None and int(v["end"]) > out["ms"]:
        out["end"] = int(v["end"])
    if v.get("name"):
        out["name"] = str(v["name"])
    if v.get("color"):
        out["color"] = str(v["color"]).lower()
    return out


def rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def nearest(color, choices):
    """The choice (a {key: "#rrggbb"}) closest to a colour."""
    r, g, b = rgb(color)
    return min(choices, key=lambda k: sum((x - y) ** 2 for x, y in zip((r, g, b), rgb(choices[k]))))


def code(v):
    """rekordbox's colour code for a hot cue's colour (None for none)."""
    return nearest(v["color"], {k: HOT[k] for k in MENU}) if v.get("color") else None


def when(ms):
    return f"{ms // 60000}:{ms % 60000 / 1000:04.1f}"


# ---- what each place can hold --------------------------------------------------------------------------------

def project(place, key, v, rel):
    """The cue as this place would hold it, or None when it can't hold it at all."""
    v = clean(v)
    if v is None:
        return None
    hot = key.startswith("hot:")
    if place == "engine":
        if os.path.splitext(rel)[1].lower() in NOT_ENGINE:
            return None
        if hot:
            v.pop("end", None)
            i = letter(key)
            if v.get("name") == f"Cue {i + 1}":
                v.pop("name")
            if v.get("color") == ENGINE_DEFAULT[i]:
                v.pop("color")
        elif "end" not in v:
            return None
        return v
    if v.get("color"):
        if hot and place != "usbanlz":  # the analysis files keep the exact colour beside the code
            v["color"] = HOT[nearest(v["color"], {k: HOT[k] for k in MENU})]
        elif not hot and place in ("mac", "usbanlz"):
            v["color"] = MEMORY[nearest(v["color"], dict(enumerate(MEMORY)))]
        elif not hot:
            v.pop("color")
    return v


def why_not(place, key, v, rel):
    """Plain words for a cue a place can't hold."""
    if place == "engine" and os.path.splitext(rel)[1].lower() in NOT_ENGINE:
        return ""  # said once per song, not per cue
    return f"{rel}: the memory cue at {when(v['ms'])} has no place on the Prime 4 (Engine keeps hot cues and loops)"


# ---- Engine (the Prime 4's library on the USB) -----------------------------------------------------------------

def unz(blob):
    return zlib.decompress(blob[4:])


def z(data):
    return struct.pack(">I", len(data)) + zlib.compress(data)


def quick_parse(blob):
    """Engine's hot cues blob: [[label, samples, argb bytes], ...] and the main-cue bytes after them."""
    d = unz(blob)
    n, i, out = struct.unpack(">q", d[:8])[0], 8, []
    for _ in range(n):
        size = d[i]
        label = d[i + 1:i + 1 + size].decode("utf-8", "replace")
        i += 1 + size
        out.append([label, struct.unpack(">d", d[i:i + 8])[0], d[i + 8:i + 12]])
        i += 12
    return out, d[i:]


def quick_build(cues, tail):
    d = struct.pack(">q", len(cues))
    for label, pos, color in cues:
        b = label.encode()
        d += bytes([len(b)]) + b + struct.pack(">d", pos) + color
    return z(d + tail)


EMPTY_TAIL = struct.pack(">dBd", -1.0, 0, -1.0)


def loops_parse(blob):
    """Engine's loops blob (not compressed, little-endian): [[label, start, end, start set, end set, argb], ...]."""
    n, i, out = struct.unpack("<q", blob[:8])[0], 8, []
    for _ in range(n):
        size = blob[i]
        label = blob[i + 1:i + 1 + size].decode("utf-8", "replace")
        i += 1 + size
        s, e = struct.unpack("<dd", blob[i:i + 16])
        out.append([label, s, e, blob[i + 16], blob[i + 17], blob[i + 18:i + 22]])
        i += 22
    return out


def loops_build(loops):
    d = struct.pack("<q", len(loops))
    for label, s, e, ss, es, color in loops:
        b = label.encode()
        d += bytes([len(b)]) + b + struct.pack("<ddBB", s, e, ss, es) + color
    return d


def engine_cues(qc, lp, rate):
    """One Engine track's cues in the shared form."""
    out = {}
    if qc:
        for i, (label, pos, color) in enumerate(quick_parse(qc)[0][:8]):
            if pos == -1.0 and color == bytes(4):
                continue
            c = "#" + color[1:].hex() if color[0] else None
            out[f"hot:{LETTERS[i]}"] = clean({"ms": round(pos * 1000 / rate), "name": label, "color": c})
            out[f"hot:{LETTERS[i]}"] = project("engine", f"hot:{LETTERS[i]}", out[f"hot:{LETTERS[i]}"], "")
    if lp:
        for label, s, e, ss, es, color in loops_parse(lp):
            if not (ss and es) or e <= s:
                continue
            ms = round(s * 1000 / rate)
            c = "#" + color[1:].hex() if color[0] else None
            out[f"mem:{ms}"] = clean({"ms": ms, "end": round(e * 1000 / rate), "name": label, "color": c})
    return out


def engine_apply(qc, lp, rate, want):
    """The blobs with the given cues ({key: cue}) put in; the rest byte for byte as it was. Also the keys that had
    no free place (Engine has 8 loops)."""
    cues, tail = quick_parse(qc) if qc else ([["", -1.0, bytes(4)] for _ in range(8)], EMPTY_TAIL)
    loops = loops_parse(lp) if lp else [["", -1.0, -1.0, 0, 0, bytes(4)] for _ in range(8)]
    full = []
    for key, v in sorted(want.items()):
        if key.startswith("hot:"):
            i = letter(key)
            color = v.get("color") or ENGINE_DEFAULT[i]
            cues[i] = [v.get("name") or f"Cue {i + 1}", v["ms"] * rate / 1000, b"\xff" + bytes(rgb(color))]
            continue
        at = [j for j, l in enumerate(loops) if l[3] and l[4] and round(l[1] * 1000 / rate) == v["ms"]]
        at = at or [j for j, l in enumerate(loops) if not (l[3] and l[4])]
        if not at:
            full.append(key)
            continue
        color = b"\xff" + bytes(rgb(v["color"])) if v.get("color") else bytes(4)
        loops[at[0]] = [v.get("name") or "", v["ms"] * rate / 1000, v["end"] * rate / 1000, 1, 1, color]
    new_qc = quick_build(cues, tail) if any(k.startswith("hot:") for k in want) else qc
    new_lp = loops_build(loops) if any(k.startswith("mem:") for k in want) else lp
    return new_qc, new_lp, full


def engine_db(usb):
    return os.path.join(usb, "Engine Library", "Database2", "m.db")


def engine_read(usb, rels):
    """{rel: {"id", "rate", "cues", "time"}} for the Crate songs Engine knows; "waiting" ones aren't analysed yet."""
    con = sqlite3.connect(f"file:{engine_db(usb)}?mode=ro", uri=True, timeout=20)
    try:
        info = con.execute("SELECT schemaVersionMajor FROM Information").fetchone()
        if not info or info[0] != 3:
            raise RuntimeError(f"Engine library version {info[0] if info else '?'}; this knows version 3")
        want = {nfc(f"../{MUSIC}/{r}"): r for r in rels}
        out, waiting = {}, []
        for tid, path, done, edited, td, qc, lp in con.execute(
                "SELECT t.id, t.path, t.isAnalyzed, t.lastEditTime, p.trackData, p.quickCues, p.loops FROM Track t "
                "LEFT JOIN PerformanceData p ON p.trackId = t.id WHERE t.path LIKE ?", (f"../{MUSIC}/%",)):
            rel = want.get(nfc(path))
            if rel is None or os.path.splitext(rel)[1].lower() in NOT_ENGINE:
                continue
            if not (done and td):
                waiting.append(rel)
                continue
            rate = struct.unpack(">d", unz(td)[:8])[0]
            if not rate:
                waiting.append(rel)
                continue
            out[rel] = {"id": tid, "rate": rate, "qc": qc, "lp": lp, "time": float(edited or 0),
                        "cues": engine_cues(qc, lp, rate)}
        return out, waiting
    finally:
        con.close()


def engine_write(usb, have, writes, backups):
    """Puts the cues in ({rel: {key: cue}}); returns the keys that had no free place, as (rel, key)."""
    import engine
    db = engine_db(usb)
    saved = engine.backup(db, backups, os.path.basename(usb.rstrip("/")))
    con = sqlite3.connect(db, timeout=20, isolation_level=None)
    full = []
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("BEGIN IMMEDIATE")
        try:
            for rel, want in writes.items():
                h = have[rel]
                qc, lp, no_room = engine_apply(h["qc"], h["lp"], h["rate"], want)
                full += [(rel, k) for k in no_room]
                if (qc, lp) != (h["qc"], h["lp"]):
                    con.execute("UPDATE PerformanceData SET quickCues=?, loops=? WHERE trackId=?", (qc, lp, h["id"]))
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if ok != "ok":
        shutil.copy2(saved, db)
        raise RuntimeError("the Engine library didn't pass its check after the change; put back as it was")
    try:  # macOS leaves a "._m.db" note beside a file it wrote on a USB
        os.remove(os.path.join(os.path.dirname(db), "._m.db"))
    except OSError:
        pass
    return full


# ---- rekordbox on this Mac ---------------------------------------------------------------------------------------

def stamp(t=None):
    t = time.time() if t is None else t
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d} +00:00"


def seconds(s):
    try:
        return float(calendar.timegm(time.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")))
    except (ValueError, TypeError):
        return 0.0


def rb_cue(kind, ms, out, comment, color, index):
    """A rekordbox cue row in the shared form: (key, cue), key None for a kind this doesn't know."""
    if kind in SLOT:
        key, c = f"hot:{LETTERS[SLOT[kind]]}", HOT.get(index) if index else None
    elif kind in (0, 4):
        key, c = f"mem:{ms}", MEMORY[color] if color is not None and 0 <= color < 8 else None
    else:
        return None, None
    return key, clean({"ms": ms, "end": out if out and out > 0 else None, "name": comment, "color": c})


def mac_open(mac_db):
    import logging
    logging.disable(logging.WARNING)
    from pyrekordbox import MasterDatabase
    mac_db = mac_db or os.environ.get("REKORDBOX_DB")
    return MasterDatabase(path=mac_db) if mac_db else MasterDatabase()


def mac_file(db, mac_db):
    return mac_db or str(db.engine.url.database)


def mac_read(db, src, rels):
    """{rel: {"id", "uuid", "cues", "rows", "times"}} for the Crate songs rekordbox on this Mac knows."""
    from sqlalchemy import text
    q = lambda sql, **p: db.session.execute(text(sql), p).fetchall()
    want = {nfc(os.path.join(src, r)): r for r in rels}
    out = {}
    for cid, folder, cuuid in q("SELECT ID, FolderPath, UUID FROM djmdContent WHERE FolderPath LIKE :p "
                                "AND rb_local_deleted = 0", p=nfc(src).rstrip("/") + "/%"):
        rel = want.get(nfc(folder))
        if rel is not None:
            out[rel] = {"id": cid, "uuid": cuuid, "cues": {}, "rows": {}, "times": {}}
    by_id = {v["id"]: v for v in out.values()}
    for row in q("SELECT ID, ContentID, Kind, InMsec, OutMsec, Comment, Color, ColorTableIndex, updated_at "
                 "FROM djmdCue WHERE rb_local_deleted = 0 ORDER BY updated_at"):
        t = by_id.get(row[1])
        if t is None:
            continue
        key, v = rb_cue(row[2], row[3], row[4], row[5], row[6], row[7])
        if key:  # (two rows on one pad: the newer counts)
            t["cues"][key], t["rows"][key], t["times"][key] = v, row[0], seconds(row[8])
    return out


JSON_ORDER = ("ID", "ContentID", "ContentUUID", "InMsec", "InFrame", "InMpegFrame", "InMpegAbs", "OutMsec",
              "OutFrame", "OutMpegFrame", "OutMpegAbs", "Kind", "Color", "ColorTableIndex", "ActiveLoop", "Comment",
              "BeatLoopSize", "CueMicrosec", "InPointSeekInfo", "OutPointSeekInfo", "UUID", "created_at", "updated_at")
OPTIONAL = {"ColorTableIndex", "ActiveLoop", "Comment", "BeatLoopSize", "CueMicrosec", "InPointSeekInfo",
            "OutPointSeekInfo"}


def iso(s):
    """'2026-11-15 01:32:55.739 +00:00' as rekordbox writes it inside its JSON: '2026-11-15T01:32:55.739+00:00'."""
    return str(s).replace(" +", "+").replace(" ", "T", 1)


def mac_write(db, have, writes):
    """Puts the cues in ({rel: {key: cue}}): djmdCue rows, their copy in contentCue, the song's cue counter."""
    from sqlalchemy import text
    run = lambda sql, **p: db.session.execute(text(sql), p)
    usn = run("SELECT int_1 FROM agentRegistry WHERE registry_id = 'localUpdateCount'").scalar() or 0
    used = {r[0] for r in run("SELECT ID FROM djmdCue")}
    now = stamp()

    def next_usn():
        nonlocal usn
        usn += 1
        return usn
    for rel, want in writes.items():
        h = have[rel]
        for key, v in want.items():
            ms, end = v["ms"], v.get("end")
            hot = key.startswith("hot:")
            cols = {"InMsec": ms, "InFrame": ms * 150 // 1000, "OutMsec": end if end else -1,
                    "OutFrame": end * 150 // 1000 if end else 0, "Comment": v.get("name"),
                    "Color": -1 if hot or not v.get("color") else MEMORY.index(v["color"]),
                    "ColorTableIndex": code(v) if hot else None,
                    "updated_at": now, "rb_local_usn": next_usn()}
            if key in h["rows"]:
                run("UPDATE djmdCue SET " + ", ".join(f"{c} = :{c}" for c in cols) + " WHERE ID = :id",
                    id=h["rows"][key], **cols)
                continue
            new = str(int.from_bytes(os.urandom(4), "big") or 1)
            while new in used:
                new = str(int.from_bytes(os.urandom(4), "big") or 1)
            used.add(new)
            cols.update({"ID": new, "ContentID": h["id"], "InMpegFrame": 0, "InMpegAbs": 0, "OutMpegFrame": 0,
                         "OutMpegAbs": 0, "Kind": KIND[letter(key)] if hot else 0, "ContentUUID": h["uuid"],
                         "UUID": str(uuid.uuid4()), "rb_data_status": 0, "rb_local_data_status": 0,
                         "rb_local_deleted": 0, "rb_local_synced": 0, "created_at": now})
            run(f"INSERT INTO djmdCue ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})", **cols)
            h["rows"][key] = new
        # contentCue: rekordbox's own copy of the song's cues as one JSON list
        rows = run("SELECT * FROM djmdCue WHERE ContentID = :c AND rb_local_deleted = 0 ORDER BY created_at, ID",
                   c=h["id"]).mappings().all()
        items = []
        for r in rows:
            d = {}
            for k in JSON_ORDER:
                if k in OPTIONAL and r.get(k) is None:
                    continue
                d[k] = iso(r[k]) if k in ("created_at", "updated_at") else r.get(k)
            items.append(d)
        js = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        if run("SELECT 1 FROM contentCue WHERE ContentID = :c", c=h["id"]).scalar():
            run("UPDATE contentCue SET Cues = :j, rb_cue_count = :n, rb_local_usn = :u, updated_at = :t "
                "WHERE ContentID = :c", j=js, n=len(items), u=next_usn(), t=now, c=h["id"])
        else:
            run("INSERT INTO contentCue (ID, ContentID, Cues, rb_cue_count, UUID, rb_data_status, "
                "rb_local_data_status, rb_local_deleted, rb_local_synced, rb_local_usn, created_at, updated_at) "
                "VALUES (:i, :c, :j, :n, :uu, 0, 0, 0, 0, :u, :t, :t)",
                i=h["uuid"], c=h["id"], j=js, n=len(items), uu=str(uuid.uuid4()), u=next_usn(), t=now)
        run("UPDATE djmdContent SET CueUpdated = CAST(COALESCE(CAST(CueUpdated AS INTEGER), 0) + 1 AS TEXT), "
            "rb_local_usn = :u, updated_at = :t WHERE ID = :c", u=next_usn(), t=now, c=h["id"])
    run("UPDATE agentRegistry SET int_1 = :u, updated_at = :t WHERE registry_id = 'localUpdateCount'", u=usn, t=now)


# ---- the USB's rekordbox library: its cue table ------------------------------------------------------------------

def usb_db(usb):
    return os.path.join(usb, "PIONEER", "rekordbox", "exportLibrary.db")


def usbdb_read(lib, rels):
    """{rel: {"id", "anlz", "cues", "rows"}} for the Crate songs in the USB's library."""
    from sqlalchemy import text
    q = lambda sql, **p: lib.session.execute(text(sql), p).fetchall()
    want = {"/" + MUSIC + "/" + nfc(r).replace(os.sep, "/"): r for r in rels}
    out = {}
    for cid, path, anlz in q("SELECT content_id, path, analysisDataFilePath FROM content WHERE path LIKE :p",
                             p="/" + MUSIC + "/%"):
        rel = want.get(nfc(path))
        if rel is not None:
            out[rel] = {"id": cid, "anlz": anlz or "", "cues": {}, "rows": {}, "times": {}}
    by_id = {v["id"]: v for v in out.values()}
    for cue_id, cid, kind, index, comment, inu, outu in q(
            "SELECT cue_id, content_id, kind, colorTableIndex, cueComment, inUsec, outUsec FROM cue ORDER BY cue_id"):
        t = by_id.get(cid)
        if t is None or inu is None:
            continue
        ms, end = round(inu / 1000), round(outu / 1000) if outu and outu > 0 else None
        key, v = rb_cue(kind, ms, end, comment, None, index)
        if key:
            t["cues"][key], t["rows"][key] = project("usbdb", key, v, ""), cue_id
    return out


def usbdb_write(lib, have, writes):
    from sqlalchemy import text
    run = lambda sql, **p: lib.session.execute(text(sql), p)
    for rel, want in writes.items():
        h = have[rel]
        for key, v in want.items():
            hot, end = key.startswith("hot:"), v.get("end")
            cols = {"kind": KIND[letter(key)] if hot else 0, "colorTableIndex": code(v) if hot else None,
                    "cueComment": v.get("name"), "inUsec": v["ms"] * 1000, "outUsec": end * 1000 if end else -1,
                    "in150FramePerSec": v["ms"] * 150 // 1000, "out150FramePerSec": end * 150 // 1000 if end else None}
            if key in h["rows"]:
                run("UPDATE cue SET " + ", ".join(f"{c} = :{c}" for c in cols) + " WHERE cue_id = :i",
                    i=h["rows"][key], **cols)
            else:
                cols["content_id"] = h["id"]
                names = ", ".join(cols)
                h["rows"][key] = run(f"INSERT INTO cue ({names}) VALUES ({', '.join(':' + c for c in cols)})",
                                     **cols).lastrowid
        run("UPDATE content SET cueUpdateCount = COALESCE(cueUpdateCount, 0) + 1 WHERE content_id = :c", c=h["id"])


# ---- the USB's analysis files (what CDJs read, and where they save cues set on them) ---------------------------

def tags(data):
    """The analysis file's parts: [(name, start, size)]."""
    if data[:4] != b"PMAI":
        raise ValueError("not an analysis file")
    i, out = struct.unpack(">I", data[4:8])[0], []
    while i + 12 <= len(data):
        size = struct.unpack(">I", data[i + 8:i + 12])[0]
        if size < 12:
            break
        out.append((data[i:i + 4], i, size))
        i += size
    return out


def anlz_cues(data):
    """The cues in one analysis file (DAT or EXT), in the shared form. The newer PCO2 list wins over PCOB."""
    old, new = {}, {}
    for name, i, size in tags(data):
        if name == b"PCOB":
            count = struct.unpack(">H", data[i + 18:i + 20])[0]
            j = i + struct.unpack(">I", data[i + 4:i + 8])[0]
            for _ in range(count):
                e = data[j:j + struct.unpack(">I", data[j + 8:j + 12])[0]]
                hot, kind, ms, loop = struct.unpack(">I", e[12:16])[0], e[28], *struct.unpack(">II", e[32:40])
                key = f"hot:{LETTERS[hot - 1]}" if 1 <= hot <= 8 else f"mem:{ms}" if hot == 0 else None
                if key:
                    old[key] = clean({"ms": ms, "end": loop if kind == 2 and loop != 0xFFFFFFFF else None})
                j += len(e)
        elif name == b"PCO2":
            count = struct.unpack(">H", data[i + 16:i + 18])[0]
            j = i + struct.unpack(">I", data[i + 4:i + 8])[0]
            for _ in range(count):
                e = data[j:j + struct.unpack(">I", data[j + 8:j + 12])[0]]
                hot, kind = struct.unpack(">I", e[12:16])[0], e[16]
                ms, loop = struct.unpack(">II", e[20:28])
                n = struct.unpack(">I", e[40:44])[0]
                name_ = e[44:44 + n].decode("utf-16-be", "replace").rstrip("\0")
                code, r, g, b = e[44 + n:48 + n] if len(e) >= 48 + n else (0, 0, 0, 0)
                if 1 <= hot <= 8:
                    key, c = f"hot:{LETTERS[hot - 1]}", f"#{r:02x}{g:02x}{b:02x}" if code else None
                elif hot == 0:
                    key, c = f"mem:{ms}", MEMORY[e[28] - 1] if 1 <= e[28] <= 8 else None
                else:
                    continue
                new[key] = clean({"ms": ms, "end": loop if kind == 2 and loop != 0xFFFFFFFF else None,
                                  "name": name_, "color": c})
                j += len(e)
    old.update(new)
    return old


def pcob(kind, cues):
    """One PCOB part (kind 1 hot cues, 0 memory) holding the given [(key, cue)] in order."""
    body = b""
    for n, (key, v) in enumerate(cues):
        hot = letter(key) + 1 if kind else 0
        loop = v.get("end")
        body += b"PCPT" + struct.pack(">IIIIIHHBBHII", 28, 56, hot, 4, 0x10000, 0xFFFF if n == 0 else n - 1,
                                      0xFFFF if n == len(cues) - 1 else n + 1, 2 if loop else 1, 0, 1000, v["ms"],
                                      loop if loop else 0xFFFFFFFF) + bytes(16)
    return b"PCOB" + struct.pack(">IIIHHI", 24, 24 + len(body), kind, 0, len(cues), 0xFFFFFFFF) + body


def pco2(kind, cues):
    """One PCO2 part (the newer list, with names and colours), laid out as the Lexar's own files have it."""
    body = b""
    for key, v in cues:
        hot = letter(key) + 1 if kind else 0
        loop = v.get("end")
        name = (v["name"].encode("utf-16-be") + b"\0\0") if v.get("name") else b""
        if kind and v.get("color"):
            color = bytes([nearest(v["color"], HOT), *rgb(v["color"])])
        else:
            color = bytes(4)
        cid = MEMORY.index(v["color"]) + 1 if not kind and v.get("color") in MEMORY else 0
        e = struct.pack(">IBBBBIIB", hot, 2 if loop else 1, 0, 3, 0xE8, v["ms"], loop if loop else 0xFFFFFFFF, cid)
        e += b"\x01" + bytes(6) + struct.pack(">HHI", 0, 0, len(name)) + name + color
        body += b"PCP2" + struct.pack(">II", 16, 12 + len(e)) + e
    return b"PCO2" + struct.pack(">IIIHH", 20, 20 + len(body), kind, len(cues), 0) + body


def anlz_apply(data, cues, ext):
    """The analysis file with its cue lists made from cues ({key: cue}); every other part byte for byte as it was.
    Lists the file lacks are added at its end."""
    hot = sorted((k, v) for k, v in cues.items() if k.startswith("hot:"))
    mem = sorted(((k, v) for k, v in cues.items() if not k.startswith("hot:")), key=lambda kv: kv[1]["ms"])
    made = {(b"PCOB", 1): pcob(1, hot), (b"PCOB", 0): pcob(0, mem)}
    if ext:
        made.update({(b"PCO2", 1): pco2(1, hot), (b"PCO2", 0): pco2(0, mem)})
    out, last = b"", 0
    for name, i, size in tags(data):
        if name in (b"PCOB", b"PCO2"):
            kind = struct.unpack(">I", data[i + 12:i + 16])[0]
            out += data[last:i] + made.pop((name, kind), b"")
            last = i + size
    out += data[last:] + b"".join(made.values())
    return out[:8] + struct.pack(">I", len(out)) + out[12:]


def anlz_read(usb, have):
    """{rel: {"files", "cues", "time"}} from each Crate song's analysis files on the USB."""
    out = {}
    for rel, h in have.items():
        dat = usb + h["anlz"] if h["anlz"] else ""
        files = [p for p in (dat, dat[:-3] + "EXT") if dat and os.path.isfile(p)]
        if not files:
            continue
        cues = {}
        for p in files:  # the EXT file's lists, with names and colours, win over the DAT file's
            with open(p, "rb") as f:
                cues.update(anlz_cues(f.read()))
        out[rel] = {"files": files, "time": max(os.path.getmtime(p) for p in files),
                    "cues": {k: project("usbanlz", k, v, rel) for k, v in cues.items()}}
    return out


def anlz_backup(usb, files, backups):
    """The analysis files about to change, copied to dj-backups/cues-anlz-<USB>-<time>/ (the last 20 kept)."""
    label = "cues-anlz-" + "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in os.path.basename(usb))
    out = os.path.join(backups, f"{label}-{time.strftime('%Y%m%d-%H%M%S')}")
    n = 1
    while os.path.exists(out):
        n += 1
        out = os.path.join(backups, f"{label}-{time.strftime('%Y%m%d-%H%M%S')}-{n}")
    for p in files:
        to = os.path.join(out, os.path.relpath(p, usb))
        os.makedirs(os.path.dirname(to), exist_ok=True)
        shutil.copy2(p, to)
    mine = sorted(f for f in os.listdir(backups) if f.startswith(label + "-"))
    for old in mine[:-20]:
        shutil.rmtree(os.path.join(backups, old), ignore_errors=True)
    return out


def anlz_write(usb, have, full, backups):
    """Writes each song's whole cue set ({rel: {key: cue}}) into its analysis files."""
    files = [p for rel in full for p in have[rel]["files"]]
    anlz_backup(usb, files, backups)
    for rel, cues in full.items():
        for p in have[rel]["files"]:
            with open(p, "rb") as f:
                data = f.read()
            new = anlz_apply(data, cues, p.endswith(".EXT"))
            if new != data:
                tmp = p + ".crate-tmp"
                with open(tmp, "wb") as f:
                    f.write(new)
                os.replace(tmp, p)
            try:
                os.remove(os.path.join(os.path.dirname(p), "._" + os.path.basename(p)))
            except OSError:
                pass


# ---- the state, the history, and the one-line summary ------------------------------------------------------------

def load(path, empty):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return empty


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, path)


def running():
    from pyrekordbox.masterdb.database import get_rekordbox_pid
    return bool(get_rekordbox_pid())


def crate(src):
    """Every song in the Crate's folder, by its place inside it."""
    out = []
    for d, _, files in os.walk(src):
        out += [os.path.relpath(os.path.join(d, f), src) for f in files if not f.startswith(".")]
    return sorted(nfc(r) for r in out)


class Place:
    """One library: what it holds now, and how to write to it."""
    def __init__(self, name, kind, have, writable, why=""):
        self.name, self.kind, self.have, self.writable, self.why = name, kind, have, writable, why

    def cues(self, rel):
        return self.have[rel]["cues"] if rel in self.have else None

    def time(self, rel, key):
        h = self.have[rel]
        return h.get("times", {}).get(key) or h.get("time") or 0.0


def gather(src, usb, rels, mac_db, is_open, problems):
    """Reads every place that's there; returns ([Place], closers, songs waiting for the Prime 4)."""
    places, closers, waiting = [], [], []
    shut = not is_open()
    label = os.path.basename((usb or "").rstrip("/"))
    try:
        db = mac_open(mac_db)
        closers.append(db.close)
        places.append(Place("mac", "mac", mac_read(db, src, rels), shut))
        places[-1].db, places[-1].file = db, mac_file(db, mac_db)
    except Exception as e:  # no rekordbox on this Mac, or a library this can't read
        if not isinstance(e, (FileNotFoundError, ImportError)) and "not found" not in str(e).lower():
            problems.append(f"rekordbox on this Mac couldn't be read: {e}")
    if usb and os.path.isdir(usb):
        if os.path.isfile(engine_db(usb)):
            try:
                have, waiting = engine_read(usb, rels)
                places.append(Place("engine@" + label, "engine", have, True))
            except Exception as e:
                problems.append(f"Engine on the USB couldn't be read: {e}")
        if os.path.isfile(usb_db(usb)):
            try:
                import rekordbox_usb
                lib = rekordbox_usb.opened(usb_db(usb))
                closers.append(lib.close)
                have = usbdb_read(lib, rels)
                places.append(Place("usbdb@" + label, "usbdb", have, shut))
                places[-1].lib = lib
                places.append(Place("usbanlz@" + label, "usbanlz", anlz_read(usb, have), shut))
            except Exception as e:
                problems.append(f"the USB's rekordbox library couldn't be read: {e}")
    return places, closers, waiting


def merge(rel, places, truth, bases, hist, held=None):
    """One song: works out the newest value of every cue slot and what each place must get. Returns
    ({place name: {key: cue}} to write, {place name: number of slots it brought in})."""
    writes, brought = {}, {}
    there = [p for p in places if p.cues(rel) is not None]
    keys = set(truth) | {k for p in there for k in p.cues(rel)}
    for key in sorted(keys):
        now = truth.get(key)
        edits = []
        for p in there:
            v, base = p.cues(rel).get(key), bases.setdefault(p.name, {}).get(key)
            should = project(p.kind, key, now, rel) if now else None
            if v is not None and v != base and v != should:
                edits.append((p.time(rel, key), RANK[p.kind], p, v, base if base is not None else should))
        if edits:
            new = dict(now or {})
            for _, _, p, v, ref in sorted(edits, key=lambda e: e[:2]):  # oldest first, so the newest has the last say
                ref = ref or {}
                for f in set(v) | set(ref):
                    if v.get(f) != ref.get(f):
                        new[f] = v.get(f)
            new = clean(new)
            if new != now:
                truth[key] = now = new
                winner = sorted(edits, key=lambda e: e[:2])[-1][2]
                brought[winner.name] = brought.get(winner.name, 0) + 1
        for p in there:
            want = project(p.kind, key, now, rel) if now else None
            v = p.cues(rel).get(key)
            if want is None:
                continue
            if v != want and p.writable:
                writes.setdefault(p.name, {})[key] = want
                hist.append({"rel": rel, "key": key, "place": p.name, "old": v, "new": want})
            elif v != want and held is not None:  # rekordbox is open: its side gets this one next run
                held.add((rel, key))
                if v is not None:
                    bases[p.name][key] = v
            elif v is not None:
                bases[p.name][key] = v
    return writes, brought


def apply(places, usb, writes, backups, problems, is_open):
    """Writes each place's changes ({place name: {rel: {key: cue}}}); returns the names whose write went through."""
    done = set()
    for p in places:
        w = writes.get(p.name)
        if not w:
            continue
        if p.kind != "engine" and is_open():  # rekordbox opened since the start: its files wait for next run
            continue
        try:
            if p.kind == "engine":
                for rel, key in engine_write(usb, p.have, w, backups):
                    w[rel].pop(key, None)
                    problems.append(f"{rel}: no free loop on the Prime 4 for the loop at {when(int(key[4:]))}")
            elif p.kind == "mac":
                import rekordbox
                p.db.session.execute(__import__("sqlalchemy").text("PRAGMA wal_checkpoint(TRUNCATE)"))
                rekordbox.backup(p.file, backups)
                try:
                    mac_write(p.db, p.have, w)
                    p.db.session.commit()
                except Exception:
                    p.db.session.rollback()
                    raise
            elif p.kind == "usbdb":
                import rekordbox_usb
                from sqlalchemy import text
                saved = rekordbox_usb.backup(usb_db(usb), backups, os.path.basename(usb.rstrip("/")))
                try:
                    usbdb_write(p.lib, p.have, w)
                    p.lib.session.commit()
                    p.lib.session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                    if p.lib.session.execute(text("PRAGMA integrity_check")).scalar() != "ok":
                        raise RuntimeError("the USB's library didn't pass its check after the change")
                except Exception:
                    p.lib.session.rollback()
                    p.lib.close()
                    rekordbox_usb.restore(saved, usb_db(usb))
                    raise
            elif p.kind == "usbanlz":
                full = {rel: {**p.have[rel]["cues"], **w[rel]} for rel in w}
                anlz_write(usb, p.have, full, backups)
            done.add(p.name)
        except Exception as e:  # that place keeps what it had and is tried again next run
            problems.append(f"{PLACES[p.kind]} couldn't take the cues: {e}"[:300])
    return done


def sync(dir, src, usb, mac_db=None, rels=None, is_open=running, backups=None):
    """Brings cue points in step across Engine on the USB, rekordbox on this Mac and the USB's rekordbox library.
    Returns {"line": one short line ("" when nothing moved), "in": {place: n}, "out": {place: n},
    "unmapped": [plain words], "waiting": n songs not analysed on the Prime 4 yet, "problems": [...]}."""
    src = nfc(src).rstrip("/")
    usb = (usb or "").rstrip("/")
    backups = backups or os.path.join(dir, "dj-backups")
    rels = [nfc(r) for r in (rels if rels is not None else crate(src))]
    state = load(os.path.join(dir, "cues-state.json"), {"tracks": {}})
    problems = []
    places, closers, waiting = gather(src, usb, rels, mac_db, is_open, problems)
    try:
        writes, brought, hist, unmapped, saved_bases, memory, held = {}, {}, [], [], {}, [], set()
        old_truth = {}
        for rel in rels:
            t = state["tracks"].setdefault(rel, {"truth": {}})
            truth = t["truth"]
            before = json.loads(json.dumps(truth))
            bases = {p.name: dict(t.get(p.name, {})) for p in places}
            w, b = merge(rel, places, truth, bases, hist, held)
            if truth != before:
                old_truth[rel] = before
            for name, n in b.items():
                brought[name] = brought.get(name, 0) + n
            for name, keys in w.items():
                writes.setdefault(name, {})[rel] = keys
            saved_bases[rel] = bases
            for p in places:
                if p.cues(rel) is None:
                    continue
                for key, v in truth.items():
                    if project(p.kind, key, v, rel) is None and why_not(p.kind, key, v, rel):
                        memory.append(why_not(p.kind, key, v, rel))
        memory = list(dict.fromkeys(memory))
        if len(memory) > 3:  # one line, not one per cue (rekordbox sets memory cues by itself on many songs)
            memory = [f"{len(memory)} memory cues stay on rekordbox's side: the Prime 4 keeps hot cues and loops"]
        unmapped += memory
        skipped_mp3 = [r for r in rels if os.path.splitext(r)[1].lower() in NOT_ENGINE and
                       any(p.kind == "engine" for p in places) and state["tracks"][r]["truth"]]
        if skipped_mp3:
            unmapped.append(f"{len(skipped_mp3)} MP3/M4A song{'s' * (len(skipped_mp3) != 1)}: cues stay between "
                            "rekordbox and the USB, not Engine (the two start MP3 time at different points)")
        done = apply(places, usb, writes, backups, problems, is_open)
        # what each place holds now becomes its starting point for next time
        for rel in rels:
            t = state["tracks"][rel]
            for p in places:
                if p.cues(rel) is None:
                    continue
                base = saved_bases[rel][p.name]
                if p.name in done:
                    base.update(writes.get(p.name, {}).get(rel, {}))
                if base:
                    t[p.name] = base
            if not t["truth"] and len(t) == 1:
                state["tracks"].pop(rel)
        hist = [h for h in hist if h["place"] in done and h["key"] in writes[h["place"]].get(h["rel"], {})]
        sent = {}
        for h in hist:
            sent[h["place"]] = sent.get(h["place"], 0) + 1
        if hist or old_truth:
            runs = load(os.path.join(dir, "cues-history.json"), [])
            runs.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "usb": os.path.basename(usb), "changes": hist,
                         "truth": old_truth})
            save(os.path.join(dir, "cues-history.json"), runs[-50:])
        save(os.path.join(dir, "cues-state.json"), state)
        unmapped = list(dict.fromkeys(unmapped))
        with open(os.path.join(dir, "cues-unmapped.txt"), "w") as f:  # for the page: what couldn't be carried
            f.write("".join(u + "\n" for u in unmapped))
    finally:
        for close in closers:
            try:
                close()
            except Exception:
                pass
    return {"line": line(brought, sent, len(waiting), problems, len(held)), "in": brought, "out": sent,
            "unmapped": unmapped, "waiting": len(waiting), "held": len(held), "problems": problems}


def line(brought, sent, waiting, problems, held=0):
    """'12 cues brought in from the Prime 4, 3 sent to rekordbox' ("" when nothing moved)."""
    def by(counts):
        out = {}
        for name, n in counts.items():  # the USB's cue table and its analysis files are one place to you
            label = PLACES[name.split("@")[0]]
            out[label] = max(out.get(label, 0), n) if label == "the USB" else out.get(label, 0) + n
        return out
    parts = [f"{n} cue{'s' * (n != 1)} brought in from {k}" for k, n in by(brought).items() if n]
    parts += [f"{n} sent to {k}" for k, n in by(sent).items() if n]
    if waiting and parts:
        parts.append(f"{waiting} waiting for the Prime 4 to analyse them")
    if held and parts:
        parts.append(f"{held} waiting until rekordbox is closed")
    return ", ".join(parts + problems[:1])


def undo(dir, src, usb, mac_db=None, is_open=running, backups=None):
    """Puts back what the last run replaced, in each place (where nothing newer was set there since). Cues that
    were only added stay. Returns one line."""
    runs = load(os.path.join(dir, "cues-history.json"), [])
    last = next((r for r in reversed(runs) if not r.get("undone")), None)
    if not last:
        return "nothing to undo"
    src, usb = nfc(src).rstrip("/"), (usb or "").rstrip("/")
    backups = backups or os.path.join(dir, "dj-backups")
    rels = sorted({c["rel"] for c in last["changes"]} | set(last.get("truth", {})))
    problems = []
    places, closers, _ = gather(src, usb, rels, mac_db, is_open, problems)
    try:
        writes, left = {}, []
        for c in last["changes"]:
            p = next((p for p in places if p.name == c["place"]), None)
            if c["old"] is None:
                continue
            if p is None or not p.writable or p.cues(c["rel"]) is None:
                left.append(c)
                continue
            if p.cues(c["rel"]).get(c["key"]) == c["new"]:
                writes.setdefault(p.name, {}).setdefault(c["rel"], {})[c["key"]] = c["old"]
        done = apply(places, usb, writes, backups, problems, is_open)
        state = load(os.path.join(dir, "cues-state.json"), {"tracks": {}})
        for rel, truth in last.get("truth", {}).items():
            state["tracks"].setdefault(rel, {})["truth"] = truth
        for name in done:
            for rel, keys in writes[name].items():
                state["tracks"].setdefault(rel, {"truth": {}}).setdefault(name, {}).update(keys)
        save(os.path.join(dir, "cues-state.json"), state)
        if not left and len(done) == len(writes):
            last["undone"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save(os.path.join(dir, "cues-history.json"), runs)
    finally:
        for close in closers:
            try:
                close()
            except Exception:
                pass
    n = sum(len(k) for name in done for k in writes[name].values())
    out = f"{n} cue{'s' * (n != 1)} put back as they were" if n or left else "nothing was replaced (new cues stay)"
    if left:
        out += f"; {len(left)} wait until their library can be written (rekordbox closed, the USB in)"
    return ", ".join([out] + problems[:1])


if __name__ == "__main__":
    job = json.load(sys.stdin)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if job.get("undo"):
        print(undo(job["dir"], job["src"], job.get("usb") or ""))
    else:
        got = sync(job["dir"], job["src"], job.get("usb") or "", rels=job.get("rels"))
        if got["line"]:
            print(got["line"])
        for u in got["unmapped"][:20]:
            print(u, file=sys.stderr)
