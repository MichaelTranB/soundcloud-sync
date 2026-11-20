"""Writes The Crate's tracks into the Engine DJ library on a USB (Denon Prime 4 and the other Engine OS decks), so
they show up there by artist, tempo, key and genre, with The Crate's playlists, without opening Engine DJ.

The library is the SQLite file <USB>/Engine Library/Database2/m.db that the deck itself made. What this does to it:
  - adds a row for every Crate track on the USB that the library doesn't know yet, marked "not analysed", so the
    deck draws its own beat grid and waveform the first time the track is loaded (as it does for any new file);
  - on rows the deck has not analysed yet, keeps title, artist, tempo, key and genre up to date; on analysed rows
    only the genre (the deck's own tempo, key, grid, cues and loops are never touched);
  - keeps one playlist folder, "The Crate", in step. Nothing outside that folder is read or changed.
Never deletes a track, never touches the music files. Before any change the library file is copied to the Mac
(dj-backups/, the last 20 kept). Works only on the library version it knows (3.x); anything else is left alone
with a line in the log. Standard library only."""
import os, shutil, sqlite3, time, unicodedata

import layout, naming, place

FOLDER = "The Crate"
# Engine's numbers for the 24 keys.
KEYS = {k: i for i, k in enumerate(["C", "Am", "G", "Em", "D", "Bm", "A", "F#m", "E", "C#m", "B", "Abm", "F#", "Ebm",
                                    "C#", "Bbm", "Ab", "Fm", "Eb", "Cm", "Bb", "Gm", "F", "Dm"])}
KINDS = {".aif": "aiff", ".aiff": "aiff"}  # the rest are their own extension


def nfc(s):
    return unicodedata.normalize("NFC", s)


def db_path(usb):
    return os.path.join(usb, "Engine Library", "Database2", "m.db")


def backup(db, folder, label):
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, f"{label}-m-{time.strftime('%Y%m%d-%H%M%S')}.db")
    n = 1
    while os.path.exists(out):  # two runs in one second: never write over an earlier copy
        n += 1
        out = os.path.join(folder, f"{label}-m-{time.strftime('%Y%m%d-%H%M%S')}-{n}.db")
    shutil.copy2(db, out)
    mine = sorted(f for f in os.listdir(folder) if f.startswith(label + "-m-") and f.endswith(".db"))
    for old in mine[:-20]:
        os.remove(os.path.join(folder, old))
    return out


def row(song, usb_file, music):
    """A track's columns as Engine keeps them."""
    name = os.path.basename(song["rel"])
    ext = os.path.splitext(name)[1].lower()
    bpm = float(song.get("bpm") or 0)
    year = str(song.get("year") or "")
    return {
        "length": int(round(song.get("length") or 0)) or None,
        "bpm": int(round(bpm)) or None, "bpmAnalyzed": bpm or None,
        "year": int(year) if year.isdigit() else None,
        "path": nfc(f"../{music}/{song.get('at') or song['rel']}"), "filename": nfc(name),
        "bitrate": int(song.get("bitrate") or 0) or None,
        "fileBytes": os.path.getsize(usb_file),
        "title": song.get("title") or "", "artist": song.get("artist") or "", "album": song.get("album") or "",
        "genre": (song.get("genres") or [""])[0], "comment": song.get("comment") or "",
        "label": song.get("label") or "", "remixer": song.get("remixer") or "",
        "key": KEYS.get(song.get("musical_key") or ""),
        "fileType": KINDS.get(ext, ext[1:]),
    }


def genres_there(usb, songs):
    """The genre the USB's Engine library shows for each Crate track now: {rel: genre}. None when the USB has no
    Engine library. Reads only."""
    db = db_path(usb)
    if not os.path.isfile(db):
        return None
    con = sqlite3.connect(db, timeout=20)
    try:
        have = {nfc(p): g or "" for p, g in con.execute("SELECT path, genre FROM Track") if p}
    finally:
        con.close()
    out, roots = {}, [place.web(usb)] + place.others(usb)
    for s in songs:
        n = s.get("at") or s["rel"]  # ("at": the folder it sits in on this USB, layout.py)
        # (a row still at a place The Crate's folder had before counts: the write that follows moves it over)
        p = next((p for p in (nfc(f"../{m}/{n}") for m in roots) if p in have), "")
        if p:
            out[s["rel"]] = have[p]
    return out


FILL = ("length", "bpm", "bpmAnalyzed", "year", "bitrate", "title", "artist", "album", "comment", "label", "remixer",
        "key")  # kept up to date only until the deck has analysed the track
EMPTY = ("title", "artist", "album", "year")  # after that, only where the library holds nothing


def write(usb, songs, lists, backups):
    """Brings the USB's Engine library in step. Returns a short line for the log, or "" when nothing changed or
    the USB has no Engine library (a deck makes one the first time the USB is plugged into it)."""
    db = db_path(usb)
    if not os.path.isfile(db):
        return ""
    music = place.web(usb)  # The Crate's folder on this USB (place.py: yours to pick)
    on_usb = [(s, os.path.join(place.folder(usb), s.get("at") or s["rel"])) for s in songs]
    on_usb = [(s, p) for s, p in on_usb if os.path.isfile(p)]
    label = os.path.basename(usb.rstrip("/"))
    saved = backup(db, backups, label)
    con = sqlite3.connect(db, timeout=20, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        info = con.execute("SELECT uuid, schemaVersionMajor, schemaVersionMinor FROM Information").fetchone()
        if not info or info[1] != 3:
            raise RuntimeError(f"this Engine library is version {info[1] if info else '?'}; The Crate knows version 3 "
                               "and left it alone")
        uuid = info[0]
        con.execute("BEGIN IMMEDIATE")
        before = con.total_changes
        now = int(time.time())
        have = {nfc(p): (i, a) for i, p, a in con.execute("SELECT id, path, isAnalyzed FROM Track") if p}
        ids, added, analysed = {}, 0, 0
        # (a row left at a place the folder had before follows its file, the same way)
        by = layout.rows(have, tuple(f"../{m}/" for m in [music] + place.others(usb)))
        there = lambda p: os.path.isfile(os.path.join(usb, p[3:]))
        # (the same place under the old folder first; a match by file name alone is for a move inside the folder)
        same = layout.same(by, have, [s for s, _ in on_usb], lambda s: [
            nfc(f"../{m}/{n}") for n in (s.get("at") or s["rel"], s.get("was")) if n for m in place.others(usb)], there)
        for s, usb_file in on_usb:
            r = row(s, usb_file, music)
            old = nfc(f"../{music}/{s['was']}") if s.get("was") else ""
            if r["path"] not in have and old not in have:  # filed into another folder on the USB (layout.py)
                old = same.get(s["rel"]) or layout.old(by, s, r["path"], there)
            if old in have and r["path"] not in have:  # the file moved: the same track, cues and all, at its new place
                # (or became another kind of file with the same sound: a FLAC that is now an AIFF, aiff.py)
                con.execute("UPDATE Track SET path=?, filename=?, fileType=?, fileBytes=?, bitrate=COALESCE(?, bitrate) "
                            "WHERE id=?", (r["path"], r["filename"], r["fileType"], r["fileBytes"], r["bitrate"], have[old][0]))
                have[r["path"]] = have.pop(old)
            if r["path"] in have:
                tid, done = have[r["path"]]
                ids[s["rel"]] = tid
                analysed += 1 if done else 0
                # a song the deck has analysed keeps what the deck holds: only its genre follows, and a name, artist,
                # album or year the library had none of (filled in since: details.py), and a name fixed on the page
                # (naming.py) where the deck still shows the old one
                cols = ["genre", *EMPTY] if done else ["genre", *FILL]
                old = con.execute(f"SELECT {', '.join(cols)} FROM Track WHERE id=?", (tid,)).fetchone()
                fixed = naming.follows(s, old[cols.index("title")], old[cols.index("artist")])
                diff = {c: r[c] for c, o in zip(cols, old) if r[c] != o and not (r[c] in (None, "") and o in (None, ""))
                        and not (c != "genre" and r[c] in (None, ""))
                        and not (done and c in EMPTY and o not in (None, "", 0) and c not in fixed)}
                if diff:
                    con.execute(f"UPDATE Track SET {', '.join(c + '=?' for c in diff)} WHERE id=?", (*diff.values(), tid))
                continue
            if not added and not con.execute("SELECT 1 FROM AlbumArt WHERE id=1").fetchone():
                # a library the deck has only just made has no "no cover" row yet (the deck adds it with its first
                # track, as id 1 with nothing in it); every track without a cover points at it
                con.execute("INSERT INTO AlbumArt (id, hash, albumArt) VALUES (1, NULL, NULL)")
            r.update({"albumArtId": 1, "rating": 0, "isPlayed": 0, "isAnalyzed": 0, "isAvailable": 1,
                      "dateCreated": s.get("mtime") or now, "dateAdded": now, "isMetadataOfPackedTrackChanged": 0,
                      "isPerfomanceDataOfPackedTrackChanged": 0, "isMetadataImported": 1, "pdbImportKey": 0,
                      "isBeatGridLocked": 0, "streamingFlags": 0, "explicitLyrics": 0, "lastEditTime": now,
                      "composer": "", "albumArt": ""})
            cur = con.execute(f"INSERT INTO Track ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})", tuple(r.values()))
            ids[s["rel"]] = cur.lastrowid
            added += 1
        # The Crate's folder of playlists: made once, then each list inside it kept in step.
        top = con.execute("SELECT id FROM Playlist WHERE title=? AND parentListId=0", (FOLDER,)).fetchone()
        if top:
            top = top[0]
        else:
            top = con.execute("INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, "
                              "isExplicitlyExported) VALUES (?, 0, 1, 0, ?, 1)", (FOLDER, now)).lastrowid
        mine = {t: i for i, t in con.execute("SELECT id, title FROM Playlist WHERE parentListId=?", (top,))}
        wanted = [(nfc(n), [ids[s["rel"]] for s in items if s["rel"] in ids]) for n, items in lists]
        wanted = [(n, t) for n, t in wanted if t]
        # The order of the lists is part of what's kept: if it changed, the folder's lists are made again.
        order = []
        nxt = {i: n for i, n in con.execute("SELECT id, nextListId FROM Playlist WHERE parentListId=?", (top,))}
        first = set(nxt) - set(nxt.values())
        at = next(iter(first), 0)
        while at and at in nxt and len(order) <= len(nxt):
            order.append(at)
            at = nxt[at]
        titles = {i: t for t, i in mine.items()}
        if [titles.get(i) for i in order] != [n for n, _ in wanted]:
            for i in mine.values():
                con.execute("DELETE FROM PlaylistEntity WHERE listId=?", (i,))
                con.execute("DELETE FROM Playlist WHERE id=?", (i,))
            mine = {}
            for n, _ in wanted:
                mine[n] = con.execute("INSERT INTO Playlist (title, parentListId, isPersisted, nextListId, lastEditTime, "
                                      "isExplicitlyExported) VALUES (?, ?, 1, 0, ?, 1)", (n, top, now)).lastrowid
        for n, track_ids in wanted:
            lid = mine[n]
            rows = con.execute("SELECT id, trackId, nextEntityId FROM PlaylistEntity WHERE listId=?", (lid,)).fetchall()
            by_next = {r[0]: r for r in rows}
            start = set(by_next) - {r[2] for r in rows}
            cur_order, at = [], next(iter(start), 0)
            while at in by_next and len(cur_order) <= len(rows):
                cur_order.append(by_next[at][1])
                at = by_next[at][2]
            if cur_order == track_ids:
                continue
            con.execute("DELETE FROM PlaylistEntity WHERE listId=?", (lid,))
            new = [con.execute("INSERT INTO PlaylistEntity (listId, trackId, databaseUuid, nextEntityId, "
                               "membershipReference) VALUES (?, ?, ?, 0, 0)", (lid, t, uuid)).lastrowid for t in track_ids]
            con.executemany("UPDATE PlaylistEntity SET nextEntityId=? WHERE id=?", zip(new[1:], new[:-1]))
            con.execute("UPDATE Playlist SET lastEditTime=? WHERE id=?", (now, lid))
        changed = con.total_changes - before
        if not changed:
            con.execute("ROLLBACK")
            os.remove(saved)  # nothing changed: no need for the copy
            return ""
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            con.execute("ROLLBACK")
            raise RuntimeError(f"the change didn't add up ({len(bad)} loose links); the library was left as it was")
        con.execute("COMMIT")
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            con.close()
            shutil.copy2(saved, db)
            raise RuntimeError("the library didn't pass its check after the change; put back as it was")
        try:  # macOS leaves a "._m.db" note beside a file it wrote on a USB; the deck has no use for it
            os.remove(os.path.join(os.path.dirname(db), "._m.db"))
        except OSError:
            pass
        total = len(ids)
        return (f"{total} tracks in the library ({added} new, {analysed} already analysed by the deck), "
                f"{len(wanted)} playlists in \"{FOLDER}\"")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    import sys, dj, genres
    d, src, usb = sys.argv[1:4]
    songs = dj.library(d, src)
    print(write(usb, songs, dj.playlists(songs, genres.load(d)), os.path.join(d, "dj-backups")) or "nothing to change")
