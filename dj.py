"""The DJ library: every track in the music folder with its tempo, key and genres, written into the libraries the
decks read, with no clicks.

    dj.py <app folder> <music folder>            analyse new tracks, then update every library that is there
    dj.py <app folder> <music folder> --wait     the same, and not back before it's done (usb.sh, before an eject)
    dj.py <app folder> <music folder> --list     print the library as JSON (what the page shows)

Libraries, each only when it exists on this Mac or the plugged-in USB:
  - Engine DJ on the USB (Denon Prime, SC, Mixstream...): engine.py
  - rekordbox on this Mac (Pioneer DDJ controllers, and its own USB export for CDJs): rekordbox.py
A genre you change in one of those libraries comes back as your pick on the page (adopt, below).
Standard library only. Tempo and key need the private Python dj-setup.sh sets up (dj_analyze.py); without it tracks
still reach the decks, which then analyse them on load."""
import fcntl, json, os, re, subprocess, sys, time, unicodedata

import dj_analyze, friend, genres, layout, liked, naming, recognise, tempo, usb_ask, usb_tidy
import place as fold  # (place() here marks where each song sits; fold is The Crate's folder on a USB)

AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus")
# The private Python with Essentia, Mutagen and pyrekordbox (dj-setup.sh); the second is where the first build kept it.
PY = next((p for p in map(os.path.expanduser, ("~/.local/share/crate-dj/python/bin/python3",
                                               "~/.local/share/crate-dj/venv/bin/python")) if os.path.exists(p)),
          os.path.expanduser("~/.local/share/crate-dj/python/bin/python3"))
CACHE = "dj-analysis.json"
SOUNDCLOUD = "My SoundCloud playlists"  # every SoundCloud playlist of yours in one
EDM_ALL, REST_ALL = "EDM (all)", "Other (all)"  # every EDM song in one, and every song that is none of it
WRITTEN = "dj-written.json"  # the genre each deck library showed for each track after The Crate last wrote it
OPTS = "dj-settings.json"  # the page's Options: what runs by itself here, each one yours to switch
DEFAULTS = {"cues": True,        # cue points kept in step between the decks' libraries (cues.py)
            "likedApart": True}  # Spotify Liked Songs stay out of the genre playlists until you give one a genre


def options(dir):
    try:
        got = json.load(open(os.path.join(dir, OPTS)))
    except (OSError, ValueError):
        got = {}
    got = got if isinstance(got, dict) else {}
    return {k: got[k] if isinstance(got.get(k), bool) else v for k, v in DEFAULTS.items()}


def set_options(dir, body):
    """Saves the switches the page sent. Returns an error to show, or None."""
    new = options(dir)
    for k, v in body.items():
        if k not in DEFAULTS or not isinstance(v, bool):
            return "That isn't one of the options."
        new[k] = v
    with open(os.path.join(dir, OPTS + ".tmp"), "w") as f:
        json.dump(new, f, indent=1)
    os.replace(os.path.join(dir, OPTS + ".tmp"), os.path.join(dir, OPTS))
    return None


def log(dir, text):
    """One line in dj.log (the page shows the last ones). The same line twice in a row is written once."""
    p = os.path.join(dir, "dj.log")
    last = (read(dir, "dj.log").splitlines() or [""])[-1]
    if last[18:] == text:
        return
    with open(p, "a") as f:
        f.write(time.strftime("%F %R") + "  " + text + "\n")


def read(dir, name):
    try:
        return open(os.path.join(dir, name), encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def flat(s):
    """Letters and digits only, so yt-dlp's stand-ins for : / ? in file names don't matter."""
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", str(s or "")).lower())


def tracks(dir, src):
    """The current, safety-checked tracks (safety-ok.tsv), relative to the music folder."""
    out = []
    for line in read(dir, "safety-ok.tsv").splitlines():
        rel = line.split("\t")[0]
        if rel.lower().endswith(AUDIO) and os.path.isfile(os.path.join(src, rel)):
            out.append(rel)
    return out


def moved(dir, src):
    """A song's file that moved inside the music folder (into the Liked Songs folder, or into one you made) is still
    the same song. Each move is noted once (dj-moved.tsv: where it was, where it is): a file that was listened to is
    gone, and the only file of that name now sits somewhere else in there."""
    try:
        cache = json.load(open(os.path.join(dir, CACHE)))
    except (OSError, ValueError):
        return
    gone = {}
    for k in cache if isinstance(cache, dict) else ():
        if not os.path.lexists(os.path.join(src, k)):
            gone.setdefault(layout.cf(os.path.basename(k)), []).append(k)
    if not gone:
        return
    at = {}
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if layout.cf(f) in gone:
                at.setdefault(layout.cf(f), []).append(os.path.relpath(os.path.join(root, f), src))
    rows = [(old[0], at[n][0]) for n, old in gone.items()
            if len(old) == 1 and len(at.get(n, [])) == 1 and at[n][0] not in cache]
    if rows:
        with open(os.path.join(dir, usb_tidy.MOVES), "a") as f:
            f.writelines(f"{a}\t{b}\n" for a, b in rows)


def follow(dir, src):
    """A file that moved is followed: Soulseek files once sat in a folder of their own and soulseek.py moved them in
    with the rest (soulseek-moved.tsv); a FLAC became an AIFF (dj-converted.tsv); a song moved into another folder
    in the music folder (moved(), above). The notes kept per file here go along, so no track is listened to again and
    the decks' libraries are pointed at the new place instead of getting every track twice. Returns
    {where it is: where it was}."""
    was = {}
    for line in read(dir, "soulseek-moved.tsv").splitlines():
        old, _, new = line.partition("\t")
        if old and new:
            was[os.path.relpath(new, src)] = os.path.relpath(old, src)
    moved(dir, src)
    went = {}
    for old, new in usb_tidy.rows(dir, usb_tidy.MOVES):
        if os.path.isfile(os.path.join(src, new)) and not os.path.lexists(os.path.join(src, old)):
            went[new] = old
    was.update(went)
    turned = {}  # a FLAC that is now an AIFF (aiff.py), or back again: the same song under another name
    for line in read(dir, "dj-converted.tsv").splitlines():
        old, new = (line.split("\t") + [""])[:2]
        if old and new:
            turned[new] = old
    was.update({new: old for new, old in turned.items()
                if os.path.isfile(os.path.join(src, new)) and not os.path.lexists(os.path.join(src, old))})
    if not was:
        return was
    # a song can be converted and renamed between two looks here (Song?.flac -> Song?.aiff -> Song？.aiff): followed
    # back along every step to the name its notes are kept under
    try:
        known = json.load(open(os.path.join(dir, CACHE)))
    except (OSError, ValueError):
        known = {}
    if isinstance(known, dict):
        step = dict(turned)
        step.update({b: a for a, b in usb_tidy.rows(dir, usb_tidy.MOVES)})  # {a name: the one before it}
        for new, old in was.items():
            seen, at = {new}, old
            while at not in known and at in step and step[at] not in seen and not os.path.lexists(os.path.join(src, at)):
                seen.add(at)
                at = step[at]
            if at in known:
                was[new] = at

    def rename(name, inner=False):
        try:
            got = json.load(open(os.path.join(dir, name)))
        except (OSError, ValueError):
            return
        if not isinstance(got, dict):
            return
        changed = False
        for part in ([v for v in got.values() if isinstance(v, dict)] if inner else [got]):
            for new, old in was.items():
                if old in part and new not in part:
                    part[new] = part.pop(old)
                    if isinstance(part[new], dict) and "path" in part[new]:  # (recognised.json keeps the full path too)
                        part[new]["path"] = os.path.realpath(os.path.join(src, new))
                    changed = True
        if changed:
            with open(os.path.join(dir, name + ".tmp"), "w") as f:
                json.dump(got, f, ensure_ascii=False, indent=0, sort_keys=True)
            os.replace(os.path.join(dir, name + ".tmp"), os.path.join(dir, name))
    def relist(name, keys, as_is=lambda r: r):  # the lists of songs aiff.py and details.py keep: a moved song is
        try:                                    # still one they have seen, so it isn't converted or filled in anew
            got = json.load(open(os.path.join(dir, name)))
        except (OSError, ValueError):
            return
        changed = False
        for k in keys:
            l = got.get(k) if isinstance(got, dict) else None
            for new, old in went.items() if isinstance(l, list) else ():
                if as_is(old) in l and as_is(new) not in l:
                    l[l.index(as_is(old))] = as_is(new)
                    changed = True
        if changed:
            with open(os.path.join(dir, name + ".tmp"), "w") as f:
                json.dump(got, f, ensure_ascii=False, indent=0)
            os.replace(os.path.join(dir, name + ".tmp"), os.path.join(dir, name))
    relist("aiff.json", ("before", "skip"))
    relist("details.json", ("seen",), lambda r: os.path.splitext(r)[0])
    rename(CACHE)
    rename(tempo.NOTE)
    rename(recognise.FILE)
    rename(WRITTEN, inner=True)
    # a name that was fixed stays fixed, with its undo (naming.py)
    naming.moved(dir, {new: old for new, old in was.items() if not os.path.lexists(os.path.join(src, old))})
    return was


def listing(dir):
    """What SoundCloud says about each playlist track: [{url, title, uploader, genre, tags, playlist, index}]."""
    rows = []
    for line in read(dir, ".listing").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rows.append({"url": r.get("webpage_url") or r.get("original_url") or "", "title": r.get("title") or "",
                     "uploader": r.get("uploader") or "", "genre": r.get("genre") or "", "tags": r.get("tags") or [],
                     "playlist": r.get("playlist_title") or r.get("playlist") or "",
                     "index": r.get("playlist_index") or len(rows) + 1})
    return rows


def liked_songs(dir, src):
    """The Spotify Liked Songs here (liked.py), by Soulseek's record of which link each file was got for:
    {rel: its place among your likes, the newest first}."""
    spot = {f"https://open.spotify.com/track/{i}": n for n, i in enumerate(liked.ids(dir))}
    out = {}
    for line in read(dir, "soulseek.tsv").splitlines() if spot else ():
        p = line.split("\t")
        if len(p) >= 3 and p[0] in spot:
            out[os.path.relpath(os.path.realpath(p[2]), os.path.realpath(src))] = spot[p[0]]
    return out


def pair(dir, src, rels, rows):
    """Which playlist track each file is: {rel: row}. Soulseek files by the record soulseek.sh keeps; the artist's
    own files by their name ("uploader - title"); then a title that only one file carries."""
    by_url = {r["url"]: r for r in rows}
    out = {}
    for line in read(dir, "soulseek.tsv").splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[0] in by_url:
            out[os.path.relpath(os.path.realpath(p[2]), os.path.realpath(src))] = by_url[p[0]]
    names = {}
    for r in rows:
        names.setdefault(flat(r["uploader"] + " - " + r["title"]), r)
    left = []
    for rel in rels:
        if rel in out:
            continue
        r = names.get(flat(os.path.splitext(os.path.basename(rel))[0]))
        if r:
            out[rel] = r
        else:
            left.append(rel)
    used = {r["url"] for r in out.values()}
    for r in rows:
        t = flat(r["title"])
        if r["url"] in used or len(t) < 8:
            continue
        hits = [rel for rel in left if t in flat(os.path.basename(rel))]
        if len(hits) == 1:
            out[hits[0]] = r
            left.remove(hits[0])
    return {rel: r for rel, r in out.items() if rel in set(rels)}


def split_name(name):
    """'Artist - Title' from a file name, for files with nothing written inside."""
    a, sep, t = name.partition(" - ")
    return (a.strip(), t.strip()) if sep else ("", name.strip())


def library(dir, src):
    """Every track, ready for the decks and the page."""
    rels = tracks(dir, src)
    was = follow(dir, src)
    try:
        cache = json.load(open(os.path.join(dir, CACHE)))
    except (OSError, ValueError):
        cache = {}
    rows = listing(dir)
    fav, home, apart = liked_songs(dir, src), liked.folder(dir), options(dir)["likedApart"]
    pairs = pair(dir, src, [r for r in rels if r not in fav], rows)  # (a Liked Song is no playlist's track)
    known = recognise.load(dir)  # what each track sounds like, when recognise.py has asked
    g = genres.load(dir)
    table = genres.lookup(g["list"])
    named = naming.was(dir)  # the names a song went by before its name was fixed (naming.py)
    settled = tempo.load(dir)  # the tempo each song is shown and written with (tempo.py)
    came, lists_of = friend.load(dir), {}  # what was copied in from another USB (friend.py)
    for n, l in came["lists"].items():
        for r in l.get("rels", []):
            lists_of.setdefault(r, []).append(n)
    out = []
    for rel in rels:
        a, row = cache.get(rel, {}), pairs.get(rel)
        name = os.path.splitext(os.path.basename(rel))[0]
        artist, title = split_name(name)
        song = {"rel": rel, "key": row["url"] if row else "file:" + name,
                "title": a.get("title") or (row or {}).get("title") or title or name,
                "artist": a.get("artist") or artist or (row or {}).get("uploader") or "",
                "album": a.get("album", ""), "year": a.get("year", ""), "label": a.get("label", ""),
                "remixer": a.get("remixer", ""), "comment": a.get("comment", ""),
                "length": a.get("length", 0), "bitrate": a.get("bitrate", 0), "rate": a.get("rate", 0),
                "own_bpm": a.get("bpm", 0), "bpm2": a.get("bpm2", 0), "musical_key": a.get("key", ""),
                "tag_genre": a.get("genre", ""), "sc_genre": (row or {}).get("genre", ""),
                "mb_genres": (known.get(rel) or {}).get("genres") or [],
                "sounds_like": " - ".join(x for x in ((known.get(rel) or {}).get("names") or [["", ""]])[0] if x),
                "sc_tags": (row or {}).get("tags", []), "url": (row or {}).get("url", ""),
                "playlist": (row or {}).get("playlist", ""), "index": (row or {}).get("index", 0),
                "tagged": bool(a.get("title")), "named": named.get(rel) or {},
                "was": was.get(rel, "")}  # where this file sat before it was moved: the decks' libraries follow
        f = came["songs"].get(rel) or {}  # from another USB: its name, the playlists it was in there, and what that
        song.update(friend=f.get("from", ""), lists=lists_of.get(rel, []), anlz=f.get("anlz", ""),  # USB's rekordbox
                    friend_bpm=f.get("bpm", 0), friend_key=f.get("key", ""), cues=f.get("cues") or [])  # knew of it
        try:
            st = os.stat(os.path.join(src, rel))
            song["size"], song["mtime"] = st.st_size, int(st.st_mtime)
        except OSError:
            song["size"], song["mtime"] = 0, 0
        # The Crate's own analysis (beat grid, waveforms: dj_analyze.py), which goes onto the USB with the song
        gid = a.get("grid_id", "") if isinstance(a.get("grid"), dict) and a["grid"].get("v") == dj_analyze.GRID_VERSION else ""
        song.update(own_grid=a["grid"] if gid else None, grid_dir=os.path.join(dir, dj_analyze.GRIDS, gid) if gid else "",
                    bpm3=a.get("bpm3", 0))
        dat = os.path.join(song["grid_dir"], "ANLZ0000.DAT") if gid else ""
        song["grid_anlz"] = dat if dat and os.path.isfile(dat) else ""
        # rekordbox's or a deck's analysis, else The Crate's: the beat grid tempo.py settled on
        song["bpm"], song["bpm_from"] = tempo.said(settled, song)
        song["grid"] = tempo.grid_said(settled, song) or song["own_grid"]  # (rekordbox's grid, where it's the one)
        song["check"] = tempo.check(song)
        song["genres"], song["from"] = genres.decide(song, g, table)
        song["heard"] = genres.heard(song)
        if rel in fav or (home and rel.startswith(home + os.sep)):  # one of your Spotify Liked Songs
            song["liked"] = fav.get(rel, len(fav))
            if apart and not (song["from"] == "your pick" and song["genres"]):  # not filed yet: on its own list
                song.update(apart=True, guess=song["genres"], genres=[], **{"from": ""})  # only, till you pick
        out.append(song)
    out.sort(key=lambda s: (s["artist"].lower(), s["title"].lower()))
    return out


def playlists(songs, g, came=None, other=None, liked_name=""):
    """The playlists the decks get, in order: [(name, [songs])]. All inside one "The Crate" folder there.
    came: the playlists copied in from another USB (friend.py's record): {name: {"rels": [...]}}.
    other: the genres that aren't EDM (layout.py's, unless you changed them).
    liked_name: what the list of your Spotify Liked Songs is called (their folder's name). One you haven't given a
    genre ("apart") is on that list and "All songs" only."""
    free = [s for s in songs if not s.get("apart")]
    lists = [("All songs", songs), ("Newest 50", sorted(free, key=lambda s: -s["mtime"])[:50])]
    mine = list(dict.fromkeys(s["playlist"] for s in songs if s["playlist"]))
    if len(mine) > 1:  # every SoundCloud playlist of yours in one, playlist after playlist
        spot = {n: i for i, n in enumerate(mine)}
        lists.append((SOUNDCLOUD, sorted((s for s in songs if s["playlist"]),
                                         key=lambda s: (spot[s["playlist"]], s["index"]))))
    for name in mine:
        lists.append((name, sorted((s for s in songs if s["playlist"] == name), key=lambda s: s["index"])))
    fav = sorted((s for s in songs if "liked" in s), key=lambda s: (s["liked"], -s["mtime"]))
    if fav:  # as on Spotify: the newest like first
        lists.append((liked_name or liked.DEFAULTS["folder"], fav))
    by = {s["rel"]: s for s in songs}
    for name, l in (came or {}).items():  # in the order they had on the other USB
        items = [by[r] for r in l.get("rels", []) if r in by]
        if items:
            lists.append((name, items))
    cfg = {"other": layout.OTHER if other is None else other}
    for name, items in ((EDM_ALL, [s for s in songs if layout.edm(s["genres"], cfg)]),  # then genre by genre
                        (REST_ALL, [s for s in songs if s["genres"] and not layout.edm(s["genres"], cfg)])):
        if items:
            lists.append((name, items))
    order = {n: i for i, n in enumerate(g["list"])}
    used = sorted({x for s in songs for x in s["genres"]}, key=lambda n: (order.get(n, 999), n.lower()))
    for name in used:
        lists.append((name, [s for s in songs if name in s["genres"]]))
    none = [s for s in free if not s["genres"]]
    if none:
        lists.append((genres.NONE, none))
    seen, out = set(), []
    for name, items in lists:  # two lists can't share a name on the decks
        n = name
        while n.lower() in seen:
            n += " (genre)" if name in used else " (2)"
        seen.add(n.lower())
        out.append((n, items))
    return out


def analyse(dir, src):
    """Tempo and key for tracks not listened to yet. Skipped, with one line in the log, when the private Python
    isn't there."""
    if not os.path.exists(PY):
        log(dir, "no tempo/key yet: the analyser isn't set up on this Mac (dj-setup.sh; the decks analyse on load meanwhile)")
        return
    follow(dir, src)  # a moved file keeps the tempo and key it already has
    here = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run([PY, os.path.join(here, "dj_analyze.py"), src, os.path.join(dir, CACHE)],
                       input="\n".join(tracks(dir, src)) + "\n", capture_output=True, text=True)
    done = [l for l in r.stdout.splitlines() if re.match(r"\d+/\d+ ", l)]
    if done:
        log(dir, f"listened to {len(done)} new track{'s' if len(done) != 1 else ''} (tempo and key)")
    again = [l for l in r.stdout.splitlines() if re.match(r"again \d+/\d+ ", l)]
    if again:
        log(dir, f"counted the tempo a second time on {len(again)} track{'s' if len(again) != 1 else ''}")
    grid = [l for l in r.stdout.splitlines() if re.match(r"grid \d+/\d+ ", l)]
    if grid:
        log(dir, f"drew the beat grid and waveforms of {len(grid)} track{'s' if len(grid) != 1 else ''} (ready for the USB)")
    unsure = sum(1 for l in r.stdout.splitlines() if re.match(r"(grid )?\d+/\d+  \S+  \S+  -  ", l))
    if unsure:
        log(dir, f"ANALYSER PROBLEM: no beat grid for {unsure} track{'s' if unsure != 1 else ''} (the decks analyse "
                 f"{'them' if unsure != 1 else 'it'} on load)")
    if r.returncode:
        log(dir, "ANALYSER PROBLEM: " + (r.stderr.strip().splitlines() or ["stopped"])[-1][:300])


def settle(dir, src, songs, stick):
    """Each song's tempo, from the best source there is (tempo.py, through the private Python: rekordbox's library
    needs pyrekordbox), put onto the songs here. Without the private Python nothing has counted a tempo at all."""
    if not os.path.exists(PY):
        return
    job = {"dir": dir, "src": src, "usb": stick, "songs": songs}
    try:
        r = subprocess.run([PY, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tempo.py")],
                           input=json.dumps(job), capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        log(dir, "TEMPO PROBLEM: took over 15 minutes and was stopped; the tempos are as they were")
        return
    if r.returncode:
        log(dir, "TEMPO PROBLEM: " + (r.stderr.strip().splitlines() or ["stopped"])[-1][:300])
    elif r.stdout.strip():
        log(dir, r.stdout.strip().splitlines()[-1])
    note = tempo.load(dir)
    for s in songs:
        s["bpm"], s["bpm_from"] = tempo.said(note, s)
        s["grid"] = tempo.grid_said(note, s) or s.get("own_grid")
        s["check"] = tempo.check(s)


def run(dir, src, volumes="/Volumes", wait=False):
    """One at a time. A run asked for while another is going is not lost: it leaves a note (.dj-again) and the one
    in flight goes round once more when it's done, so an edit made mid-run still reaches the decks. With wait, this
    one stays until that is done (the USB must not be ejected under a library being written)."""
    again = os.path.join(dir, ".dj-again")
    open(again, "w").close()
    lock = open(os.path.join(dir, ".dj.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if not wait and not reading(lock):
            return
        fcntl.flock(lock, fcntl.LOCK_EX)
    while os.path.exists(again):
        os.remove(again)
        once(dir, src, volumes)


def reading(lock):
    """The lock is held only by a USB backup reading the libraries (backup.py holds it shared), not by another run:
    no run is going that would pick up .dj-again, so this one waits for the backup instead of leaving."""
    try:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return False
    fcntl.flock(lock, fcntl.LOCK_UN)
    return True


def busy(dir):
    """True while a run is going (the page says so)."""
    try:
        with open(os.path.join(dir, ".dj.lock"), "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return not reading(lock)
        return False
    except OSError as e:
        return isinstance(e, BlockingIOError)


def convert(dir, src):
    """FLACs that arrived since last time become AIFFs (aiff.py): the same sound, in a file every deck plays. Not while
    a sync is still getting songs, except as that sync's own last step."""
    try:
        pid = int(read(dir, ".running").strip() or 0)
        os.kill(pid, 0) if pid else None
    except (ValueError, ProcessLookupError):
        pid = 0
    except OSError:
        pass
    if (pid and not os.environ.get("CRATE_FINAL") and os.getppid() != pid) or not os.path.exists(PY):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for job, name in (("aiff.py", "AIFF"), ("details.py", "DETAILS")):  # then their missing cover and details
        r = subprocess.run([PY, os.path.join(here, job), "auto", dir, src], capture_output=True, text=True)
        if r.returncode:
            log(dir, f"{name} PROBLEM: {(r.stderr.strip().splitlines() or ['it stopped'])[-1]}"[:300])


def place(dir, songs, stick, usb="", file=False):
    """Marks each song with where it sits on the USB ("at"), for the decks' libraries there. file: first every song
    is filed into the folder the chosen layout gives it (layout.py: one folder, or by genre), inside The Crate's own
    folder only."""
    if not stick:
        return
    dest = fold.folder(stick)
    try:
        if file:
            cfg = layout.load(dir)
            moved, stuck, twice, at = layout.arrange(dest, songs, cfg)
            said = layout.say(moved, stuck, twice, cfg["mode"] == "flat")
            if said:
                log(dir, f'USB "{usb}": {said}')
            said = layout.all_songs(dest, at, cfg)[2]  # the "All songs" folder of copies, when it's ticked
            if said:
                log(dir, f'USB "{usb}": {said}')
        else:
            at = layout.places(dest, [s["rel"] for s in songs])
    except Exception as e:  # never silent: the page shows the last lines of dj.log
        log(dir, f'USB PROBLEM on "{usb}": {e}')
        return
    for s in songs:
        s["at"] = at.get(s["rel"], s["rel"])


def once(dir, src, volumes):
    usb = read(dir, "usb.txt").strip()
    stick = os.path.join(volumes, usb) if usb and os.path.isdir(os.path.join(volumes, usb)) else ""
    if stick and not usb_ask.ready(dir, stick):  # it has things on it already: nothing there changes before your OK
        if "waiting for your OK" not in (read(dir, "dj.log").splitlines() or [""])[-1]:
            log(dir, f'USB "{usb}" already has things on it: waiting for your OK on the page')
        stick = ""
    if stick:  # The Crate's folder goes where you chose on the page (place.py); the decks' rows follow it below
        try:
            said = fold.move(stick)
            if said:
                log(dir, f'USB "{usb}": {said}')
        except OSError as e:
            log(dir, f'USB PROBLEM on "{usb}": The Crate\'s folder couldn\'t be moved ({e})')
    follow(dir, src)  # a song whose file moved on the Mac is noted first: the USB moves its copy too
    if stick:  # first, so it's right away: a song you threw back leaves the USB too (usb.sh does this as well)
        try:
            said = usb_tidy.say(*usb_tidy.tidy(dir, src, fold.folder(stick)))
            if said:
                log(dir, f'USB "{usb}": {said}')
        except Exception as e:  # never silent: the page shows the last lines of dj.log
            log(dir, f'USB PROBLEM on "{usb}": {e}')
    for step in (better, friend.prune):
        try:
            step(dir, src)
        except Exception as e:  # never silent: the page shows the last lines of dj.log
            log(dir, f"COPY PROBLEM: {e!r}"[:300])
    convert(dir, src)
    analyse(dir, src)
    songs = library(dir, src)
    place(dir, songs, stick)  # where each sits on the USB now: its library there is read by that
    settle(dir, src, songs, stick)  # whose tempo each song goes by: rekordbox's, a deck's, or an agreed count
    there = seen(dir, src, songs, stick)
    if adopt(dir, songs, there):  # a genre you changed on the decks' side is now your pick
        songs = library(dir, src)
    place(dir, songs, stick, usb, file=True)  # then each into its folder (a song whose genre changed moves)
    lists = playlists(songs, genres.load(dir), friend.load(dir)["lists"], layout.load(dir)["other"], liked.folder(dir))
    wrote = False
    if stick:
        import engine
        try:
            said = engine.write(stick, songs, lists, os.path.join(dir, "dj-backups"))
            if said:
                wrote = True
                log(dir, f'Engine DJ on "{usb}": {said}')
        except Exception as e:  # never silent: the page shows the last lines of dj.log
            wrote = True
            log(dir, f'ENGINE PROBLEM on "{usb}": {e}')
    if stick:  # Serato's crates on the USB: small files of its own, beside the songs
        import serato
        try:
            said = serato.write(stick, songs, lists)
            if said:
                log(dir, f'Serato on "{usb}": {said}')
        except Exception as e:
            log(dir, f'SERATO PROBLEM on "{usb}": {e}')
    wrote = rekordbox(dir, src, songs, lists) or wrote
    if stick:  # after the Mac's library: a track rekordbox knows takes its beat grid and waveform along
        rekordbox_usb(dir, src, songs, lists, stick, usb)
        if options(dir)["cues"]:  # (yours to switch off on the page)
            cues(dir, src, stick, usb, [s["rel"] for s in songs])  # last: every library has its songs by now
    remember(dir, seen(dir, src, songs, stick) if wrote else there)
    if recognise.key(dir) and os.path.exists(PY):  # on its own: it asks the internet, and comes back here when it learns something
        subprocess.Popen([PY, os.path.join(os.path.dirname(os.path.abspath(__file__)), "recognise.py"), dir, src],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=open(os.path.join(dir, "dj.log"), "a"))


def fresh(day, days=30):
    """A better copy that was thrown back is looked for again this long (day: when it was thrown back)."""
    try:
        return time.time() - time.mktime(time.strptime(day, "%Y-%m-%d")) < days * 86400
    except ValueError:
        return False


def better(dir, src):
    """A better copy you asked for on the page (friend.BETTER) has come in from Soulseek: only now does the file it
    replaces go to the Trash (and off the USB, the next time it's in), and its playlists and your genre pick pass
    to the new one. Until then you keep the old file to play."""
    if not friend.wanted(dir):
        return
    import soulseek
    with soulseek.locked(dir):  # with the page's "Find a better copy" and the Soulseek search: one writer at a time
        got = {g[0]: g[2] for g in soulseek.load_got(dir)}
        left, g, changed = [], genres.load(dir), False
        for row in friend.wanted(dir):
            name, link, old = row[0], row[1], row[6]
            new, was = got.get(link, ""), os.path.join(src, old) if old else ""
            if not new or not os.path.isfile(new):
                # still looked for: the file is there to be replaced, or the better copy that came was thrown back
                # (row[7]). A file you threw away meanwhile is looked for no more.
                if os.path.isfile(was) or fresh(row[7]):
                    left.append(row)
                continue
            if os.path.isfile(was) and not os.path.samefile(was, new):
                size = os.path.getsize(was)
                if not soulseek.trash(dir, was):
                    left.append(row)  # (couldn't be moved: tried again next time)
                    continue
                with open(os.path.join(dir, soulseek.USB_THROWN), "a") as f:
                    f.write(f"{was}\t{size}\n")
            now = os.path.relpath(new, src)
            friend.moved(dir, old, now)
            a, b = ("file:" + os.path.splitext(os.path.basename(x))[0] for x in (old, now))
            if a in g["songs"] and b not in g["songs"]:
                g["songs"][b] = g["songs"].pop(a)
                changed = True
            log(dir, f"a better copy of {name} came in from Soulseek ({os.path.splitext(now)[1][1:].upper()}); "
                     "the one it replaces is in the Trash")
        if changed:
            genres.save(dir, g)
        friend.save_wanted(dir, left)


def rekordbox(dir, src, songs, lists):
    """rekordbox on this Mac, through the private Python (rekordbox.py needs pyrekordbox). Quietly nothing when
    either isn't there. True when it did, or tried, anything."""
    if not os.path.exists(PY):
        return False
    here = os.path.dirname(os.path.abspath(__file__))
    job = {"src": src, "backups": os.path.join(dir, "dj-backups"), "songs": songs,
           "lists": [[n, [s["rel"] for s in items]] for n, items in lists]}
    try:
        r = subprocess.run([PY, os.path.join(here, "rekordbox.py")], input=json.dumps(job), capture_output=True,
                           text=True, timeout=900)
    except subprocess.TimeoutExpired:
        log(dir, "REKORDBOX PROBLEM: took over 15 minutes and was stopped; its library is as it was")
        return True
    if r.returncode:
        log(dir, "REKORDBOX PROBLEM: " + (r.stderr.strip().splitlines() or ["stopped"])[-1][:300])
    elif r.stdout.strip():
        log(dir, "rekordbox: " + r.stdout.strip().splitlines()[-1])
    return bool(r.returncode or r.stdout.strip())


def rekordbox_usb(dir, src, songs, lists, stick, usb):
    """The USB's own rekordbox library (rekordbox_usb.py, through the private Python): what rekordbox shows under
    the USB itself and the newest club decks read. Quietly nothing when the private Python isn't there."""
    if not os.path.exists(PY):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    job = {"usb": stick, "src": src, "dir": dir, "backups": os.path.join(dir, "dj-backups"), "songs": songs,
           "lists": [[n, [s["rel"] for s in items]] for n, items in lists]}
    try:
        r = subprocess.run([PY, os.path.join(here, "rekordbox_usb.py")], input=json.dumps(job), capture_output=True,
                           text=True, timeout=900)
    except subprocess.TimeoutExpired:
        log(dir, f'REKORDBOX USB PROBLEM on "{usb}": took over 15 minutes and was stopped')
        return
    if r.returncode:
        log(dir, f'REKORDBOX USB PROBLEM on "{usb}": ' + (r.stderr.strip().splitlines() or ["stopped"])[-1][:300])
    elif r.stdout.strip():
        said = f'rekordbox on "{usb}": ' + r.stdout.strip().splitlines()[-1]
        last = [l for l in read(dir, "dj.log").splitlines()[-40:] if 'rekordbox on "' in l or "REKORDBOX USB" in l]
        if not (last and last[-1].endswith(said)):  # (a USB that is left alone says so once, not at every run)
            log(dir, said)


def cues(dir, src, stick, usb, rels=None, undo=False):
    """Cue points in step (cues.py, through the private Python): hot cues, memory cues and loops set on the Prime 4,
    in rekordbox on this Mac or on a club's decks reach the other two. Nothing is ever deleted; undo puts the last
    run's replaced ones back. Quietly nothing when the private Python isn't there."""
    if not os.path.exists(PY):
        return "The DJ tools aren't set up on this Mac yet." if undo else None
    job = {"dir": dir, "src": src, "usb": stick, **({"undo": True} if undo else {"rels": rels})}
    try:
        r = subprocess.run([PY, os.path.join(os.path.dirname(os.path.abspath(__file__)), "cues.py")],
                           input=json.dumps(job), capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        log(dir, f'CUES PROBLEM on "{usb}": took over 15 minutes and was stopped')
        return "That took too long."
    if r.returncode:
        log(dir, f'CUES PROBLEM on "{usb}": ' + (r.stderr.strip().splitlines() or ["stopped"])[-1][:300])
        return "The cues couldn't be read. Nothing was changed."
    if r.stdout.strip():
        log(dir, ("cues put back: " if undo else "cues: ") + r.stdout.strip().splitlines()[-1][:300])
    return None


def cues_back(dir, src, volumes):
    """The page's Undo for cues: the last run's replaced cues go back. Waits for a run in flight to finish first."""
    usb = read(dir, "usb.txt").strip()
    stick = os.path.join(volumes, usb) if usb and os.path.isdir(os.path.join(volumes, usb)) else ""
    if stick and not usb_ask.ready(dir, stick):
        stick = ""
    with open(os.path.join(dir, ".dj.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return cues(dir, src, stick, usb, undo=True)


def seen(dir, src, songs, stick):
    """The genre each deck library shows for each track right now: {"rekordbox": {rel: genre}, "engine": {...}}.
    A library that isn't there is left out. Reads only. A library that can't be read is left out too: the write
    that follows says what's wrong with it."""
    out = {}
    if os.path.exists(PY):
        here = os.path.dirname(os.path.abspath(__file__))
        try:
            r = subprocess.run([PY, os.path.join(here, "rekordbox.py"), "--genres"], capture_output=True, text=True,
                               input=json.dumps({"src": src, "rels": [s["rel"] for s in songs]}), timeout=300)
            got = json.loads(r.stdout) if not r.returncode else None
        except (subprocess.TimeoutExpired, ValueError):
            got = None
        if isinstance(got, dict):
            out["rekordbox"] = got
    if stick:
        import engine
        try:
            got = engine.genres_there(stick, songs)
        except Exception:
            got = None
        if got is not None:
            out["engine"] = got
    return out


def remember(dir, there):
    """Keeps what each library shows now, so the next run can tell a genre you changed there from one The Crate
    wrote. A library that isn't there this time keeps what was remembered."""
    try:
        was = json.load(open(os.path.join(dir, WRITTEN)))
    except (OSError, ValueError):
        was = {}
    now = {**(was if isinstance(was, dict) else {}), **there}
    if now != was:
        with open(os.path.join(dir, WRITTEN + ".tmp"), "w") as f:
            json.dump(now, f, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(os.path.join(dir, WRITTEN + ".tmp"), os.path.join(dir, WRITTEN))


def adopt(dir, songs, there):
    """A genre you changed in rekordbox (or in Engine DJ, on the USB) becomes your pick on the page, so the page,
    the other library and the genre playlists follow it instead of The Crate writing its own genre back over
    yours. Only a track whose genre is different from what The Crate last saw there counts; a genre you emptied
    doesn't, and neither does the file's own label showing up (the deck software read the file again, you didn't
    type it). Returns how many picks changed."""
    try:
        was = json.load(open(os.path.join(dir, WRITTEN)))
    except (OSError, ValueError):
        return 0
    table = genres.lookup(genres.load(dir)["list"])
    picks, said = {}, []
    for where, name in (("rekordbox", "rekordbox"), ("engine", "Engine DJ")):
        old, now = (was.get(where) or {}) if isinstance(was, dict) else {}, there.get(where) or {}
        for s in songs:
            new = str(now.get(s["rel"]) or "").strip()[:60]
            if s["rel"] not in old or not new or s["key"] in picks or genres.norm(new) == genres.norm(old[s["rel"]]):
                continue
            if genres.norm(new) == genres.norm(s.get("tag_genre")):
                continue
            parts = [genres.match(p, table) for p in re.split(r"[;/,|]", new)]
            mine = [genres.match(new, table)] if genres.match(new, table) else [p for p in parts if p][:3] or [new]
            if s["genres"][:1] == mine[:1]:
                continue  # it already says what the page says, written another way
            picks[s["key"]] = list(dict.fromkeys(mine))
            said.append(f'{" - ".join(x for x in (s["artist"], s["title"]) if x)} is now {mine[0]} (changed in {name})')
    if not picks:
        return 0
    g = genres.load(dir)  # read again right before saving: the page may have saved a pick meanwhile
    for key, names in picks.items():
        for n in names:  # a new one joins your list
            if genres.norm(n) not in {genres.norm(x) for x in g["list"]}:
                g["list"].append(n)
        by = {genres.norm(x): x for x in g["list"]}
        g["songs"][key] = [by[genres.norm(n)] for n in names]
    genres.save(dir, g)
    log(dir, "your genre: " + "; ".join(said[:3]) + (f" and {len(said) - 3} more" if len(said) > 3 else ""))
    return len(picks)


if __name__ == "__main__":
    d, s = sys.argv[1], sys.argv[2]
    if "--list" in sys.argv:
        json.dump(library(d, s), sys.stdout, ensure_ascii=False)
    elif "--cues-back" in sys.argv:
        sys.exit(cues_back(d, s, os.environ.get("VOLUMES") or "/Volumes"))
    else:
        run(d, s, os.environ.get("VOLUMES") or "/Volumes", "--wait" in sys.argv)
