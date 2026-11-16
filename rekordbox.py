"""Puts The Crate's tracks into the rekordbox library on this Mac (Pioneer DDJ controllers play from it; rekordbox's
own "export to USB" makes CDJ sticks from it), so they are there by artist, tempo, key and genre, with The Crate's
playlists, without dragging anything in.

Run by dj.py with the private Python (it has pyrekordbox, which knows rekordbox 6 and 7's library file):

    rekordbox.py            reads {"src": music folder, "backups": folder, "songs": [...], "lists": [[name, [rel]]]}
                            on stdin, prints one line for the log (nothing when there was nothing to do)

What it does to the library:
  - adds every Crate track rekordbox doesn't know yet, by its place in the music folder, marked "not analysed", so
    rekordbox draws its own beat grid and waveform the first time the track is loaded;
  - keeps the genre of Crate tracks in step with the page (your pick there is the one that counts);
  - keeps one playlist folder, "The Crate", in step. Nothing outside that folder is read or changed: your own
    playlists, smart lists, cues and My Tags stay exactly as they are.
Never deletes a track. Only when rekordbox is closed (it would write over the change otherwise); when it's open the
change waits for the next run. Before any change the library file is copied to dj-backups/ (the last 20 kept)."""
import json, os, shutil, sys, time, unicodedata

FOLDER = "The Crate"
KINDS = (".mp3", ".m4a", ".mp4", ".flac", ".wav", ".aiff")  # what rekordbox plays and pyrekordbox can add


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def backup(db_file, folder):
    os.makedirs(folder, exist_ok=True)
    stamp, n = time.strftime("%Y%m%d-%H%M%S"), 1
    out = os.path.join(folder, f"rekordbox-master-{stamp}.db")
    while os.path.exists(out):
        n += 1
        out = os.path.join(folder, f"rekordbox-master-{stamp}-{n}.db")
    shutil.copy2(db_file, out)
    xml = os.path.join(os.path.dirname(db_file), "masterPlaylists6.xml")
    if os.path.exists(xml):
        shutil.copy2(xml, out[:-3] + ".playlists.xml")
    mine = sorted(f for f in os.listdir(folder) if f.startswith("rekordbox-master-") and f.endswith(".db"))
    for old in mine[:-20]:
        for f in (old, old[:-3] + ".playlists.xml"):
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass
    return out


def write(job, db_file=None):
    try:
        from pyrekordbox import MasterDatabase
        from pyrekordbox.masterdb import models
        from pyrekordbox.masterdb.database import get_rekordbox_pid
    except ImportError:
        return ""
    import logging
    logging.disable(logging.WARNING)
    try:
        db = MasterDatabase(path=db_file) if db_file else MasterDatabase()
    except FileNotFoundError:
        return ""  # no rekordbox on this Mac
    try:
        return sync(db, job, models, get_rekordbox_pid, db_file)
    finally:
        db.close()


def sync(db, job, models, running, db_file):
    src = job["src"]
    songs = [s for s in job["songs"] if s["rel"].lower().endswith(KINDS)]
    skipped = len(job["songs"]) - len(songs)
    path = {s["rel"]: os.path.join(src, s["rel"]) for s in songs}
    songs = [s for s in songs if os.path.isfile(path[s["rel"]])]
    have = {nfc(c.FolderPath): c for c in db.get_content().all() if c.FolderPath}

    def genre_of(c):
        return c.Genre.Name if c.Genre is not None else ""
    # What needs doing, worked out before anything is touched.
    new = [s for s in songs if nfc(path[s["rel"]]) not in have]
    regenre = [s for s in songs if nfc(path[s["rel"]]) in have and s.get("genres")
               and genre_of(have[nfc(path[s["rel"]])]) != s["genres"][0]]
    wanted = [(nfc(n), [r for r in rels if r in path and os.path.isfile(path[r])]) for n, rels in job["lists"]]
    wanted = [(n, r) for n, r in wanted if r]
    top = db.get_playlist(Name=FOLDER, ParentID="root", Attribute=1).first()
    kids = sorted(db.get_playlist(ParentID=top.ID).all(), key=lambda p: p.Seq) if top else []
    same_lists = [nfc(p.Name) for p in kids] == [n for n, _ in wanted]

    def members(p):
        return [sp.ContentID for sp in sorted(p.Songs, key=lambda x: x.TrackNo)]
    stale = []
    if same_lists and not new:
        for p, (n, rels) in zip(kids, wanted):
            if members(p) != [have[nfc(path[r])].ID for r in rels]:
                stale.append(n)
    if not new and not regenre and same_lists and not stale:
        return ""
    if running():
        return "rekordbox is open, so its library was left alone; it catches up on the next run after you close it"
    file = db_file or str(db.engine.url.database)
    saved = backup(file, job["backups"])

    def named(get, add, name):
        if not name:
            return None
        got = get(Name=name).first()
        return (got or add(name)).ID
    keys = {k.ScaleName: k.ID for k in db.get_key().all()}

    def key_id(name):
        if not name:
            return None
        if name not in keys:
            seq = max([k.Seq or 0 for k in db.get_key().all()] or [0]) + 1
            k = models.DjmdKey.create(ID=str(db.generate_unused_id(models.DjmdKey)), ScaleName=name, Seq=seq,
                                      UUID=str(__import__("uuid").uuid4()))
            db.add(k)
            db.flush()
            keys[name] = k.ID
        return keys[name]
    try:
        for s in new:
            year = str(s.get("year") or "")
            c = db.add_content(
                path[s["rel"]], Title=s.get("title") or "",
                ArtistID=named(db.get_artist, db.add_artist, s.get("artist")),
                AlbumID=named(db.get_album, db.add_album, s.get("album")),
                GenreID=named(db.get_genre, db.add_genre, (s.get("genres") or [""])[0]),
                KeyID=key_id(s.get("musical_key")), BPM=int(round(float(s.get("bpm") or 0) * 100)),
                Length=int(round(s.get("length") or 0)), BitRate=int(s.get("bitrate") or 0),
                SampleRate=int(s.get("rate") or 0), ReleaseYear=int(year) if year.isdigit() else 0,
                Commnt=s.get("comment") or "", Analysed=0, Rating=0, ColorID="0", DJPlayCount=0, FileNameS="",
                ModifiedByRBM="", DeliveryControl="on", TrackNo=0, DiscNo=0, OrgFolderPath="", ImagePath="",
                ServiceID=0, VideoAssociate="0", LyricStatus=0)
            have[nfc(path[s["rel"]])] = c
        for s in regenre:
            have[nfc(path[s["rel"]])].GenreID = named(db.get_genre, db.add_genre, s["genres"][0])
        if top is None:
            top = db.create_playlist_folder(FOLDER)
        if not same_lists:  # the lists or their order changed: The Crate's folder is laid out again
            for p in kids:
                db.delete_playlist(p)
            kids = []
        db.flush()
        kids = {nfc(p.Name): p for p in kids}
        for i, (n, rels) in enumerate(wanted):
            ids = [have[nfc(path[r])].ID for r in rels]
            p = kids.get(n)
            if p is not None and members(p) == ids:
                continue
            if p is not None:
                db.delete_playlist(p)
                db.flush()
            p = db.create_playlist(n, parent=top, seq=i + 1)
            for cid in ids:
                db.add_to_playlist(p, cid)
        db.commit()
    except Exception:
        db.rollback()
        raise
    ok = db.session.execute(__import__("sqlalchemy").text("PRAGMA integrity_check")).scalar()
    if ok != "ok":
        raise RuntimeError(f"the library didn't pass its check after the change; the copy from before is {saved}")
    said = f"{len(have_crate(have, path))} tracks in the library ({len(new)} new), {len(wanted)} playlists in \"{FOLDER}\""
    if skipped:
        said += f"; {skipped} left out (a file type rekordbox doesn't play)"
    return said


def have_crate(have, path):
    return [p for p in path.values() if nfc(p) in have]


if __name__ == "__main__":
    job = json.load(sys.stdin)
    print(write(job, os.environ.get("REKORDBOX_DB") or None))
