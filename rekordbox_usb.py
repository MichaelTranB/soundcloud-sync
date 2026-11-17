#!/usr/bin/env python3
"""Writes The Crate's songs into the USB's own rekordbox library (PIONEER/rekordbox/exportLibrary.db, the list
rekordbox shows under Devices and the newest club decks read), so they show from the USB itself. The songs stay
where usb.sh put them, in the USB's "SoundCloud Sync" folder: nothing is copied or moved.

  rekordbox_usb.py < job     job, as JSON: {"usb": where the USB is mounted, "src": the music folder on the Mac,
                             "dir": the app folder, "backups": where the copy from before goes,
                             "songs": [...], "lists": [[name, [song, ...]], ...]}  (as dj.py makes them)

Run by dj.py with the private Python (pyrekordbox). It prints one line saying what it did, or nothing when the
library was already in step.

  Only The Crate's own rows are ever touched: tracks under /SoundCloud Sync/ and the "The Crate" playlist folder.
    Everything else in the library (songs and playlists rekordbox exported, anyone's) stays exactly as it is.
  A USB that has no rekordbox library at all gets a fresh one. One that only has the older kind (export.pdb, made
    by an old rekordbox) is left alone: a new library beside it would hide that export on the newest decks.
  Never while rekordbox is open (it keeps the USB's library open itself); it catches up when rekordbox closes.
  The library is copied to dj-backups before any change, and put back if it fails its check afterwards.
  Where rekordbox on this Mac has the track, its row is linked to it and rekordbox's own analysis (beat grid,
    waveform, tempo, key) and cover go onto the USB with it; a track rekordbox analyses later is filled in on a
    later run. Without rekordbox, the tempo and key The Crate worked out are used and the deck draws the rest.
  The older library on the USB (export.pdb, for the CDJ-3000, CDJ-2000NXS2 and earlier) is only written by
    rekordbox's own export; club.py says where that stands."""
import json, os, shutil, struct, subprocess, sys, tempfile, time, unicodedata, zlib

MUSIC, FOLDER, RECORD = "SoundCloud Sync", "The Crate", "dj-rekordbox-usb.json"
KINDS = {".mp3": 1, ".mp4": 3, ".m4a": 4, ".flac": 5, ".wav": 11, ".aiff": 12, ".aif": 12}  # rekordbox's own codes
PARTS = ("DAT", "EXT", "2EX")  # the files of one track's analysis
# A fresh library, as rekordbox 7 lays one out (its tables, and the lists a deck's browse menu is built from).
SCHEMA = (
    "CREATE TABLE content(content_id integer primary key, title varchar, titleForSearch varchar, subtitle "
    "varchar, bpmx100 integer, length integer, trackNo integer, discNo integer, artist_id_artist integer, "
    "artist_id_remixer integer, artist_id_originalArtist integer, artist_id_composer integer, "
    "artist_id_lyricist integer, album_id integer, genre_id integer, label_id integer, key_id integer, "
    "color_id integer, image_id integer, djComment varchar, rating integer, releaseYear integer, releaseDate "
    "varchar, dateCreated varchar, dateAdded varchar, path varchar, fileName varchar, fileSize integer, "
    "fileType integer, bitrate integer, bitDepth integer, samplingRate integer, isrc varchar, djPlayCount "
    "integer, isHotCueAutoLoadOn integer, isKuvoDeliverStatusOn integer, kuvoDeliveryComment varchar, "
    "masterDbId integer, masterContentId integer, analysisDataFilePath varchar, analysedBits integer, "
    "contentLink integer, hasModified integer, cueUpdateCount integer, analysisDataUpdateCount integer, "
    "informationUpdateCount integer)",
    "CREATE TABLE genre(genre_id integer primary key, name varchar)",
    "CREATE TABLE artist(artist_id integer primary key, name varchar, nameForSearch varchar)",
    "CREATE TABLE album(album_id integer primary key, name varchar, artist_id integer, image_id integer, "
    "isComplation integer, nameForSearch varchar)",
    "CREATE TABLE label(label_id integer primary key, name varchar)",
    "CREATE TABLE key(key_id integer primary key, name varchar)",
    "CREATE TABLE color(color_id integer primary key, name varchar)",
    "CREATE TABLE playlist(playlist_id integer primary key, sequenceNo integer, name varchar, image_id "
    "integer, attribute integer, playlist_id_parent integer)",
    "CREATE TABLE playlist_content(playlist_id integer, content_id integer, sequenceNo integer)",
    "CREATE TABLE hotCueBankList(hotCueBankList_id integer primary key, sequenceNo integer, name varchar, "
    "image_id integer, attribute integer, hotCueBankList_id_parent integer)",
    "CREATE TABLE hotCueBankList_cue(hotCueBankList_id integer, cue_id integer, sequenceNo integer)",
    "CREATE TABLE history(history_id integer primary key, sequenceNo integer, name varchar, attribute "
    "integer, history_id_parent integer)",
    "CREATE TABLE history_content(history_id integer, content_id integer, sequenceNo integer)",
    "CREATE TABLE image(image_id integer primary key, path varchar)",
    "CREATE TABLE cue(cue_id integer primary key, content_id integer, kind integer, colorTableIndex integer, "
    "cueComment varchar, isActiveLoop integer, beatLoopNumerator integer, beatLoopDenominator integer, inUsec"
    " integer, outUsec integer, in150FramePerSec integer, out150FramePerSec integer, inMpegFrameNumber "
    "integer, outMpegFrameNumber integer, inMpegAbs integer, outMpegAbs integer, inDecodingStartFramePosition"
    " integer, outDecodingStartFramePosition integer, inFileOffsetInBlock integer, OutFileOffsetInBlock "
    "integer, inNumberOfSampleInBlock integer, outNumberOfSampleInBlock integer)",
    "CREATE TABLE menuItem(menuItem_id integer primary key, kind integer, name varchar)",
    "CREATE TABLE category(category_id integer primary key, menuItem_id integer, sequenceNo integer, "
    "isVisible integer)",
    "CREATE TABLE sort(sort_id integer primary key, menuItem_id integer, sequenceNo integer, isVisible "
    "integer, isSelectedAsSubColumn integer)",
    "CREATE TABLE property(deviceName varchar, dbVersion varchar, numberOfContents integer, createdDate "
    "varchar, backGroundColorType integer, myTagMasterDBID integer)",
    "CREATE TABLE recommendedLike(content_id_1 integer, content_id_2 integer, rating integer, createdDate "
    "integer)",
    "CREATE TABLE myTag(myTag_id integer primary key, sequenceNo integer, name varchar, attribute integer, "
    "myTag_id_parent integer)",
    "CREATE TABLE myTag_content(myTag_id integer, content_id integer)",
    "CREATE INDEX index_playlist_content_playlist_id on playlist_content(playlist_id)",
    "CREATE INDEX index_myTag_content_myTag_id on myTag_content(myTag_id)",
    "CREATE INDEX index_myTag_content_content_id on myTag_content(content_id)",
    "CREATE INDEX index_hotCueBankList_cue_hotCueBankList_id on hotCueBankList_cue(hotCueBankList_id)",
)
COLORS = ["Pink", "Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple"]
MENU = [  # (id, kind, name)
    [1, 128, "GENRE"], [2, 129, "ARTIST"], [3, 130, "ALBUM"], [4, 131, "TRACK"], [5, 133, "BPM"], [6, 134,
    "RATING"], [7, 135, "YEAR"], [8, 136, "REMIXER"], [9, 137, "LABEL"], [10, 138, "ORIGINAL ARTIST"], [11,
    139, "KEY"], [12, 141, "CUE"], [13, 142, "COLOR"], [14, 146, "TIME"], [15, 147, "BITRATE"], [16, 148,
    "FILE NAME"], [17, 132, "PLAYLIST"], [18, 152, "HOT CUE BANK"], [19, 149, "HISTORY"], [20, 145,
    "SEARCH"], [21, 150, "COMMENTS"], [22, 140, "DATE ADDED"], [23, 151, "DJ PLAY COUNT"], [24, 144,
    "FOLDER"], [25, 161, "DEFAULT"], [26, 162, "ALPHABET"], [27, 170, "MATCHING"]
]
CATEGORY = [
    [1, 1, 0, 0], [2, 2, 1, 1], [3, 3, 2, 1], [4, 4, 3, 1], [5, 17, 5, 1], [6, 5, 0, 0], [7, 6, 0, 0], [8,
    7, 0, 0], [9, 8, 0, 0], [10, 9, 0, 0], [11, 10, 0, 0], [12, 11, 4, 1], [15, 13, 0, 0], [17, 24, 9, 1],
    [18, 20, 7, 1], [19, 14, 0, 0], [20, 15, 0, 0], [21, 16, 0, 0], [22, 19, 6, 1], [23, 18, 0, 0], [26, 27,
    8, 1], [27, 22, 10, 1]
]
SORT = [
    [0, 25, 1, 1, 0], [1, 26, 2, 1, 0], [2, 2, 3, 1, 0], [3, 3, 4, 1, 0], [4, 5, 5, 1, 0], [5, 6, 6, 1, 0],
    [6, 1, 0, 0, 0], [7, 21, 0, 0, 0], [8, 14, 0, 0, 0], [9, 8, 0, 0, 0], [10, 9, 0, 0, 0], [11, 10, 0, 0,
    0], [12, 11, 7, 1, 0], [13, 15, 0, 0, 0], [15, 13, 0, 0, 0], [16, 23, 0, 0, 0], [17, 22, 0, 0, 0]
]
OPEN = "rekordbox is open, so the USB's library was left alone; it catches up when you close it"
OLDER = ("this USB only has the older kind of rekordbox library, so it was left alone: export to it once from "
         "rekordbox 7, and The Crate keeps it up from then on")
COLUMNS = ("title titleForSearch subtitle bpmx100 length trackNo discNo artist_id_artist artist_id_remixer "
           "artist_id_originalArtist artist_id_composer artist_id_lyricist album_id genre_id label_id key_id color_id "
           "image_id djComment rating releaseYear releaseDate dateCreated dateAdded path fileName fileSize fileType "
           "bitrate bitDepth samplingRate isrc djPlayCount isHotCueAutoLoadOn isKuvoDeliverStatusOn "
           "kuvoDeliveryComment masterDbId masterContentId analysisDataFilePath analysedBits contentLink hasModified "
           "cueUpdateCount analysisDataUpdateCount informationUpdateCount").split()


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def device(rel):
    """A song's place as the USB's library names it."""
    return "/" + MUSIC + "/" + nfc(rel).replace(os.sep, "/")


def num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def running():
    from pyrekordbox.masterdb.database import get_rekordbox_pid
    return bool(get_rekordbox_pid())


def opened(db_file):
    import logging
    logging.disable(logging.WARNING)
    from pyrekordbox.onelibrary import OneLibrary
    return OneLibrary(db_file)


def mac(job, master=None):
    """What rekordbox on this Mac holds for each song ({song: {...}}): its ids there, its tempo and key, and where
    its analysis and cover are. {} when there's no rekordbox on this Mac. Reads only."""
    try:
        import logging
        logging.disable(logging.WARNING)
        from pyrekordbox import MasterDatabase
        db = MasterDatabase(path=master) if master else MasterDatabase()
    except Exception:  # no rekordbox here, or a library this can't read: the USB is written without it
        return {}
    try:
        file = master or str(db.engine.url.database)
        share = os.environ.get("REKORDBOX_SHARE") or os.path.join(os.path.dirname(file), "share")
        src, have, named = nfc(job["src"]).rstrip("/") + "/", {}, {}
        for c in db.get_content().all():
            if c.FolderPath:
                have[nfc(c.FolderPath)] = c
                if nfc(c.FolderPath).startswith(src):
                    named.setdefault(os.path.basename(nfc(c.FolderPath)), []).append(c)
        out = {}
        for s in job["songs"]:
            same = named.get(os.path.basename(nfc(s["rel"])), [])  # (a row still at the file's place from before)
            c = have.get(src + nfc(s["rel"])) or (have.get(src + nfc(s["was"])) if s.get("was") else None) or \
                (same[0] if len(same) == 1 else None)
            if c is None:
                continue
            anlz, img = share + (c.AnalysisDataPath or ""), share + (c.ImagePath or "")
            key = getattr(c, "Key", None)
            out[s["rel"]] = {
                "db": num(c.MasterDBID), "id": num(c.MasterSongID) or num(c.ID), "link": num(c.ContentLink),
                "bpm": num(c.BPM), "key": (key.ScaleName or "") if key is not None else "", "length": num(c.Length),
                "bitrate": num(c.BitRate), "depth": num(c.BitDepth), "rate": num(c.SampleRate),
                "anlz": anlz if c.AnalysisDataPath and os.path.isfile(anlz) else "",
                "art": img if c.ImagePath and all(os.path.isfile(img[:-4] + x) for x in ("_s.jpg", "_m.jpg")) else "",
                "created": str(c.DateCreated or "")[:10], "added": str(c.StockDate or "")[:10]}
        return out
    except Exception:
        return {}
    finally:
        db.close()


BLANK = {"db": 0, "id": 0, "link": 0, "bpm": 0, "key": "", "length": 0, "bitrate": 0, "depth": 0, "rate": 0,
         "anlz": "", "art": "", "created": "", "added": ""}  # a song rekordbox on this Mac doesn't know


def cued(dat):
    """Does this analysis hold cue points (hot cues, memory cues, loops)?"""
    from pyrekordbox.anlz import AnlzFile
    for part in ("DAT", "EXT"):
        try:
            with open(dat[:-3] + part, "rb") as f:
                a = AnlzFile.parse(f.read())
            if any(t.content.count for tag in ("PCOB", "PCO2") for t in a.getall_tags(tag)):
                return True
        except Exception:
            pass
    return False


def carried(job, known):
    """A song copied in from another USB brought that USB's analysis along (friend.py): its beat grid, waveform and
    cue points. It is used where rekordbox on this Mac has none for the song, or has one without cue points while
    the one that came along holds some. Cue points you set yourself on this Mac always win."""
    for s in job["songs"]:
        a = s.get("anlz") or ""
        if not a or not os.path.isfile(a):
            continue
        k = known.get(s["rel"])
        if k and k.get("anlz") and (cued(k["anlz"]) or not cued(a)):
            continue
        k = known.setdefault(s["rel"], dict(BLANK))
        k["anlz"] = a
        k["bpm"] = k["bpm"] or int(s.get("friend_bpm") or 0)
        k["key"] = k["key"] or s.get("friend_key") or ""
    return known


def fresh(db_file, name, master_id):
    """A new, empty library on a USB that has none, laid out as rekordbox 7 makes one."""
    from sqlalchemy import text
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
    open(db_file, "xb").close()
    try:
        lib = opened(db_file)
        try:
            run = lambda sql, rows=None: lib.session.execute(text(sql), rows or {})
            run("PRAGMA journal_mode=WAL")
            for sql in SCHEMA:
                run(sql)
            run("INSERT INTO color VALUES (:i, :n)", [{"i": i, "n": n} for i, n in enumerate(COLORS, 1)])
            run("INSERT INTO menuItem VALUES (:i, :k, :n)",
                [{"i": i, "k": k, "n": "￺" + n + "￻"} for i, k, n in MENU])
            run("INSERT INTO category VALUES (:a, :b, :c, :d)", [dict(zip("abcd", r)) for r in CATEGORY])
            run("INSERT INTO sort VALUES (:a, :b, :c, :d, :e)", [dict(zip("abcde", r)) for r in SORT])
            run("INSERT INTO property VALUES (:n, '1000', 0, :d, 0, :m)",
                {"n": name, "d": time.strftime("%Y-%m-%d"), "m": master_id})
            lib.session.commit()
        finally:
            lib.close()
    except Exception:
        for x in ("", "-wal", "-shm"):  # nothing half-made is left behind
            if os.path.isfile(db_file + x):
                os.remove(db_file + x)
        raise


def backup(db_file, folder, name):
    """The USB's library as it is now, copied to the Mac (the last 20 kept). Where the copy is."""
    os.makedirs(folder, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)
    stamp, n = time.strftime("%Y%m%d-%H%M%S"), 1
    out = os.path.join(folder, f"rekordbox-usb-{safe}-{stamp}.db")
    while os.path.exists(out):
        n += 1
        out = os.path.join(folder, f"rekordbox-usb-{safe}-{stamp}-{n}.db")
    for x in ("", "-wal", "-shm"):
        if os.path.isfile(db_file + x):
            shutil.copy2(db_file + x, out + x)
    mine = sorted((f for f in os.listdir(folder) if f.startswith("rekordbox-usb-") and f.endswith(".db")),
                  key=lambda f: os.path.getmtime(os.path.join(folder, f)))
    for old in mine[:-20]:
        for x in ("", "-wal", "-shm"):
            try:
                os.remove(os.path.join(folder, old + x))
            except OSError:
                pass
    return out


def restore(saved, db_file):
    for x in ("", "-wal", "-shm"):
        if os.path.isfile(saved + x):
            shutil.copy2(saved + x, db_file + x)
        elif os.path.isfile(db_file + x):
            os.remove(db_file + x)


def repath(data, path):
    """One analysis file's bytes with its track's place changed, and everything else byte for byte as it was: the
    beat grid, the waveforms, the cue points. (Done by hand: pyrekordbox can't write back a file that holds cue
    points.) The place sits in the file's PPTH part, as UTF-16 with a closing zero."""
    if data[:4] != b"PMAI":
        raise ValueError("not an analysis file")
    i = struct.unpack(">I", data[4:8])[0]
    while i + 12 <= len(data):
        size = struct.unpack(">I", data[i + 8:i + 12])[0]
        if size < 12:
            break
        if data[i:i + 4] == b"PPTH":
            p = path.encode("utf-16-be") + b"\0\0"
            out = data[:i] + b"PPTH" + struct.pack(">III", 16, 16 + len(p), len(p)) + p + data[i + size:]
            return out[:8] + struct.pack(">I", len(out)) + out[12:]
        i += size
    raise ValueError("an analysis file with no track in it")


def analysis(usb, dat, path):
    """rekordbox's analysis of one track (beat grid, waveform, cues), copied from the Mac onto the USB and addressed
    to the track's place there. Where its first file is, as the library names it; "" when it couldn't be made."""
    h = zlib.crc32(path.encode())
    rel = f"/PIONEER/USBANLZ/P{(h >> 20) & 0xFFF:03X}/{h & 0xFFFFF:08X}"
    while os.path.exists(usb + rel):
        h += 1
        rel = f"/PIONEER/USBANLZ/P{(h >> 20) & 0xFFF:03X}/{h & 0xFFFFF:08X}"
    try:
        os.makedirs(usb + rel)
        for part in PARTS:
            if os.path.isfile(dat[:-3] + part):
                with open(dat[:-3] + part, "rb") as f:
                    data = repath(f.read(), path)
                with open(f"{usb}{rel}/ANLZ0000.{part}", "wb") as f:
                    f.write(data)
        return rel + "/ANLZ0000.DAT"
    except Exception:  # an analysis file this can't read: the track goes on without, and the deck draws its own
        shutil.rmtree(usb + rel, ignore_errors=True)
        return ""


def readdress(usb, dat, path):
    """A track that moved on the USB: its analysis files there are told the new place."""
    for part in PARTS:
        p = usb + dat[:-3] + part
        try:
            with open(p, "rb") as f:
                data = repath(f.read(), path)
            with open(p, "wb") as f:
                f.write(data)
        except (OSError, ValueError, struct.error):
            pass


def pictures(src, s, known, tmp):
    """A track's cover in the two sizes the decks show (80 and 240 across), as (small file, medium file): the ones
    rekordbox on this Mac made, else made here from the picture the file carries. None when it has no cover."""
    a = known.get("art")
    if a:
        return a[:-4] + "_s.jpg", a[:-4] + "_m.jpg"
    from rekordbox import art
    data = art(os.path.join(src, s["rel"]))
    if not data:
        return None
    raw = os.path.join(tmp, f"in{len(os.listdir(tmp))}" + (".png" if data[:4] == b"\x89PNG" else ".jpg"))
    with open(raw, "wb") as f:
        f.write(data)
    out = raw + "_s.jpg", raw + "_m.jpg"
    for file, n in zip(out, ("80", "240")):
        r = subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-z", n, n, raw, "--out", file], capture_output=True)
        if r.returncode or not os.path.isfile(file) or not os.path.getsize(file):
            return None
    return out


def note(job, name, rels, analysed):
    """What the USB's library holds now, kept on the Mac for the club check (club.py can't open the library)."""
    file = os.path.join(job.get("dir") or "", RECORD)
    if not job.get("dir"):
        return
    now = {"usb": name, "rels": sorted(rels), "analysed": analysed}
    try:
        with open(file) as f:
            was = json.load(f)
        was.pop("at", None)
    except (OSError, ValueError, AttributeError):
        was = None
    if was != now:
        with open(file + ".tmp", "w") as f:
            json.dump({**now, "at": int(time.time())}, f)
        os.replace(file + ".tmp", file)


def write(job, master=None, is_open=running):
    from sqlalchemy import text
    usb, src = job["usb"].rstrip("/"), job["src"]
    name, folder = os.path.basename(usb), os.path.join(usb, MUSIC)
    db_file = os.path.join(usb, "PIONEER", "rekordbox", "exportLibrary.db")
    songs = [s for s in job["songs"] if os.path.splitext(s["rel"])[1].lower() in KINDS]
    skipped = len(job["songs"]) - len(songs)
    songs = [s for s in songs if os.path.isfile(os.path.join(folder, s["rel"]))]
    at = {s["rel"]: device(s["rel"]) for s in songs}
    known = None
    made = False
    if not os.path.isfile(db_file):
        if os.path.isfile(os.path.join(os.path.dirname(db_file), "export.pdb")):
            return OLDER
        if not songs:
            return ""
        if is_open():
            return OPEN
        known = carried(job, mac(job, master))
        fresh(db_file, name, max([k["db"] for k in known.values()] or [0]))
        made = True
    if known is None:
        known = carried(job, mac(job, master))
    lib = opened(db_file)
    run = lambda sql, **p: lib.session.execute(text(sql), p)

    def members(pid):
        return [r[0] for r in run("SELECT content_id FROM playlist_content WHERE playlist_id = :p ORDER BY sequenceNo", p=pid)]
    tmp = tempfile.mkdtemp(prefix="crate-covers-")
    try:
        cue_cols = [r[1] for r in run("PRAGMA table_info(cue)")]
        # Only The Crate's own rows: the tracks in the USB's "SoundCloud Sync" folder.
        own = {nfc(p): {"id": i, "genre": g or "", "anlz": a or "", "image": im or 0} for i, p, g, a, im in run(
            "SELECT c.content_id, c.path, g.name, c.analysisDataFilePath, c.image_id FROM content c "
            "LEFT JOIN genre g ON g.genre_id = c.genre_id WHERE c.path LIKE :p", p="/" + MUSIC + "/%")}
        # A file that moved inside the folder (dj.py's "was") is the same track at a new place: its row follows.
        moved = []
        for s in songs:
            old = device(s["was"]) if s.get("was") else ""
            if old in own and at[s["rel"]] not in own:
                own[at[s["rel"]]] = own.pop(old)
                moved.append((at[s["rel"]], s))
        # What needs doing, worked out before anything is touched.
        new = [s for s in songs if at[s["rel"]] not in own]
        mine = set(at.values())
        gone = [p for p in own if p not in mine and not os.path.isfile(usb + p)] if os.path.isdir(folder) else []
        regenre = [s for s in songs if at[s["rel"]] in own and s.get("genres") and own[at[s["rel"]]]["genre"] != s["genres"][0]]
        fill = [s for s in songs if at[s["rel"]] in own and not own[at[s["rel"]]]["anlz"] and known.get(s["rel"], {}).get("anlz")]
        covers = {}
        for s in songs:  # a picture that can't be read drops out here, so it never counts as something to do
            if at[s["rel"]] not in own or not own[at[s["rel"]]]["image"]:
                got = pictures(src, s, known.get(s["rel"], {}), tmp)
                if got:
                    covers[s["rel"]] = got
        wanted = [(nfc(n), [r for r in rels if r in at]) for n, rels in job["lists"]]
        wanted = [(n, r) for n, r in wanted if r]
        top = run("SELECT playlist_id FROM playlist WHERE name = :n AND attribute = 1 AND playlist_id_parent = 0",
                  n=FOLDER).scalar()
        kids = [tuple(r) for r in run("SELECT playlist_id, name FROM playlist WHERE playlist_id_parent = :t "
                                      "ORDER BY sequenceNo", t=top)] if top else []
        same_lists = [nfc(n) for _, n in kids] == [n for n, _ in wanted]
        stale = [n for (pid, _), (n, rels) in zip(kids, wanted)
                 if members(pid) != [own[at[r]]["id"] for r in rels]] if same_lists and not new else []
        old_covers = [r for r in covers if at[r] in own]
        if not (made or new or moved or gone or regenre or fill or old_covers or stale) and same_lists:
            note(job, name, [s["rel"] for s in songs], sum(bool(own[at[s["rel"]]]["anlz"]) for s in songs))
            return ""
        if is_open():
            return OPEN
        lib.close()
        saved = "" if made else backup(db_file, job["backups"], name)
        lib = opened(db_file)

        def named(table, name, **more):
            name = nfc(name)
            if not name:
                return 0
            col = table + "_id"
            got = run(f'SELECT {col} FROM "{table}" WHERE name = :n', n=name).scalar()
            if got is not None:
                return got
            cols = ["name", *more]
            return run(f'INSERT INTO "{table}" ({", ".join(cols)}) VALUES ({", ".join(":" + c for c in cols)})',
                       name=name, **more).lastrowid
        images = {"next": (run("SELECT max(image_id) FROM image").scalar() or 0) + 1}

        def image(rel):
            small, medium = covers[rel]
            n = images["next"]
            where = lambda n: f"/PIONEER/Artwork/{(n - 1) // 20 + 1:05d}/b{n}.jpg"
            while os.path.exists(usb + where(n)):
                n += 1
            images["next"] = n + 1
            os.makedirs(os.path.dirname(usb + where(n)), exist_ok=True)
            shutil.copyfile(small, usb + where(n))
            shutil.copyfile(medium, usb + where(n)[:-4] + "_m.jpg")
            run("INSERT INTO image (image_id, path) VALUES (:i, :p)", i=n, p=where(n))
            return n
        junk = []  # files of rows that go, taken off the USB once the library is safely written
        try:
            for p, s in moved:  # (or another kind of file with the same sound: a FLAC that is now an AIFF, aiff.py)
                run("UPDATE content SET path = :p, fileName = :f, fileType = :t, fileSize = :n, "
                    "bitrate = CASE WHEN :b > 0 THEN :b ELSE bitrate END WHERE content_id = :i", p=p,
                    f=os.path.basename(p), t=KINDS[os.path.splitext(p)[1].lower()], b=int(s.get("bitrate") or 0),
                    n=os.path.getsize(os.path.join(folder, s["rel"])), i=own[p]["id"])
                if own[p]["anlz"]:
                    readdress(usb, own[p]["anlz"], p)
            for s in new:
                k, p, file = known.get(s["rel"], {}), at[s["rel"]], os.path.join(folder, s["rel"])
                year = str(s.get("year") or "")
                day = time.strftime("%Y-%m-%d", time.localtime(s.get("mtime") or None))
                anlz = analysis(usb, k["anlz"], p) if k.get("anlz") else ""
                row = dict.fromkeys(COLUMNS, 0)
                row.update(
                    title=nfc(s.get("title")) or os.path.splitext(os.path.basename(p))[0], titleForSearch="",
                    subtitle="", bpmx100=k.get("bpm") or int(round(float(s.get("bpm") or 0) * 100)),
                    length=k.get("length") or int(round(s.get("length") or 0)),
                    artist_id_artist=named("artist", s.get("artist"), nameForSearch=""),
                    artist_id_remixer=named("artist", s.get("remixer"), nameForSearch=""),
                    album_id=named("album", s.get("album"), artist_id=0, image_id=0, isComplation=0, nameForSearch=""),
                    genre_id=named("genre", (s.get("genres") or [""])[0]), label_id=named("label", s.get("label")),
                    key_id=named("key", k.get("key") or s.get("musical_key")),
                    image_id=image(s["rel"]) if s["rel"] in covers else 0, djComment=nfc(s.get("comment")),
                    releaseYear=int(year) if year.isdigit() else 0, releaseDate="",
                    dateCreated=k.get("created") or day, dateAdded=k.get("added") or time.strftime("%Y-%m-%d"),
                    path=p, fileName=os.path.basename(p), fileSize=os.path.getsize(file),
                    fileType=KINDS[os.path.splitext(p)[1].lower()],
                    bitrate=k.get("bitrate") or int(s.get("bitrate") or 0), bitDepth=k.get("depth") or 16,
                    samplingRate=k.get("rate") or int(s.get("rate") or 0), isrc="", isHotCueAutoLoadOn=1,
                    kuvoDeliveryComment="", masterDbId=k.get("db", 0), masterContentId=k.get("id", 0),
                    analysisDataFilePath=anlz, analysedBits=41 if anlz else 0, contentLink=k.get("link", 0))
                i = run(f'INSERT INTO content ({", ".join(COLUMNS)}) VALUES ({", ".join(":" + c for c in COLUMNS)})',
                        **row).lastrowid
                own[p] = {"id": i, "genre": (s.get("genres") or [""])[0], "anlz": anlz, "image": row["image_id"]}
                for c in s.get("cues") or []:  # the cue rows it had on the USB it was copied from (friend.py)
                    cols = [x for x in c if x in cue_cols and x not in ("cue_id", "content_id")]
                    if cols:
                        run(f'INSERT INTO cue (content_id, {", ".join(cols)}) VALUES (:content_id, '
                            f'{", ".join(":" + x for x in cols)})', content_id=i, **{x: c[x] for x in cols})
            for s in regenre:
                run("UPDATE content SET genre_id = :g WHERE content_id = :i", g=named("genre", s["genres"][0]),
                    i=own[at[s["rel"]]]["id"])
            for s in fill:  # rekordbox on this Mac has analysed it since
                k, o = known[s["rel"]], own[at[s["rel"]]]
                o["anlz"] = analysis(usb, k["anlz"], at[s["rel"]])
                if o["anlz"]:
                    run("UPDATE content SET analysisDataFilePath = :a, analysedBits = 41, bpmx100 = :b, key_id = :k, "
                        "masterDbId = :d, masterContentId = :m, contentLink = :l WHERE content_id = :i", a=o["anlz"],
                        b=k["bpm"] or int(round(float(s.get("bpm") or 0) * 100)),
                        k=named("key", k["key"] or s.get("musical_key")), d=k["db"], m=k["id"], l=k["link"], i=o["id"])
            for rel in old_covers:
                run("UPDATE content SET image_id = :m WHERE content_id = :i", m=image(rel), i=own[at[rel]]["id"])
            for p in gone:  # its file left the USB (a song you threw back): its row goes too
                o = own.pop(p)
                for table in ("playlist_content", "myTag_content", "history_content", "cue", "content"):
                    run(f"DELETE FROM {table} WHERE content_id = :i", i=o["id"])
                run("DELETE FROM recommendedLike WHERE content_id_1 = :i OR content_id_2 = :i", i=o["id"])
                if o["anlz"].startswith("/PIONEER/USBANLZ/") and o["anlz"].count("/") == 5:
                    junk.append(os.path.dirname(usb + o["anlz"]))
                if o["image"] and not run("SELECT count(*) FROM content WHERE image_id = :m", m=o["image"]).scalar():
                    pic = run("SELECT path FROM image WHERE image_id = :m", m=o["image"]).scalar() or ""
                    run("DELETE FROM image WHERE image_id = :m", m=o["image"])
                    if pic.startswith("/PIONEER/Artwork/"):
                        junk += [usb + pic, usb + pic[:-4] + "_m.jpg"]
            if top is None and wanted:
                seq = run("SELECT coalesce(max(sequenceNo), -1) + 1 FROM playlist WHERE playlist_id_parent = 0").scalar()
                top = run("INSERT INTO playlist (sequenceNo, name, image_id, attribute, playlist_id_parent) "
                          "VALUES (:s, :n, 0, 1, 0)", s=seq, n=FOLDER).lastrowid
            if not same_lists:  # the lists or their order changed: The Crate's folder is laid out again
                for pid, _ in kids:
                    run("DELETE FROM playlist_content WHERE playlist_id = :p", p=pid)
                    run("DELETE FROM playlist WHERE playlist_id = :p", p=pid)
                kids = []
            kid = {nfc(n): pid for pid, n in kids}
            for seq, (n, rels) in enumerate(wanted):
                ids, pid = [own[at[r]]["id"] for r in rels], kid.get(n)
                if pid is not None and members(pid) == ids:
                    continue
                if pid is None:
                    pid = run("INSERT INTO playlist (sequenceNo, name, image_id, attribute, playlist_id_parent) "
                              "VALUES (:s, :n, 0, 0, :t)", s=seq, n=n, t=top).lastrowid
                else:
                    run("DELETE FROM playlist_content WHERE playlist_id = :p", p=pid)
                lib.session.execute(text("INSERT INTO playlist_content (playlist_id, content_id, sequenceNo) "
                                         "VALUES (:p, :c, :s)"), [{"p": pid, "c": c, "s": j} for j, c in enumerate(ids, 1)])
            run("UPDATE property SET numberOfContents = (SELECT count(*) FROM content)")
            lib.session.commit()
        except Exception:
            lib.session.rollback()
            raise
        run("PRAGMA wal_checkpoint(TRUNCATE)")
        if run("PRAGMA integrity_check").scalar() != "ok":
            lib.close()
            if saved:
                restore(saved, db_file)
            raise RuntimeError("the USB's rekordbox library didn't pass its check after the change, so it was put "
                               "back as it was" if saved else "the new rekordbox library on the USB didn't pass its check")
        for f in junk:
            if os.path.isdir(f):
                shutil.rmtree(f, ignore_errors=True)
            elif os.path.isfile(f):
                os.remove(f)
        there = [s["rel"] for s in songs if at[s["rel"]] in own]
        analysed = sum(bool(own[at[r]]["anlz"]) for r in there)
        note(job, name, there, analysed)
        s = lambda n: "" if n == 1 else "s"
        said = f"{len(there)} track{s(len(there))} in the USB's own library ({len(new)} new), {len(wanted)} " \
               f"playlist{s(len(wanted))} in \"{FOLDER}\""
        if analysed:
            said += f"; {analysed} carry rekordbox's beat grid and waveform"
        if moved:
            said += f"; {len(moved)} followed to where their file{'s are' if len(moved) != 1 else ' is'} now"
        if gone:
            said += f"; {len(gone)} taken out (no longer on the USB)"
        if skipped:
            said += f"; {skipped} left out (a file type rekordbox doesn't play)"
        return said
    finally:
        lib.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print(write(json.load(sys.stdin), os.environ.get("REKORDBOX_DB") or None))
