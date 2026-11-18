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

import friend, genres, recognise, usb_tidy

AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus")
# The private Python with Essentia, Mutagen and pyrekordbox (dj-setup.sh); the second is where the first build kept it.
PY = next((p for p in map(os.path.expanduser, ("~/.local/share/crate-dj/python/bin/python3",
                                               "~/.local/share/crate-dj/venv/bin/python")) if os.path.exists(p)),
          os.path.expanduser("~/.local/share/crate-dj/python/bin/python3"))
CACHE = "dj-analysis.json"
SOUNDCLOUD = "My SoundCloud playlists"  # every SoundCloud playlist of yours in one
WRITTEN = "dj-written.json"  # the genre each deck library showed for each track after The Crate last wrote it


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


def follow(dir, src):
    """Soulseek files once sat in a folder of their own; soulseek.py moved them in with the rest and noted each move
    (soulseek-moved.tsv). The notes kept per file here go along, so no track is listened to again and the decks'
    libraries are pointed at the new place instead of getting every track twice. Returns {where it is: where it was}."""
    was = {}
    for line in read(dir, "soulseek-moved.tsv").splitlines():
        old, _, new = line.partition("\t")
        if old and new:
            was[os.path.relpath(new, src)] = os.path.relpath(old, src)
    if not was:
        return was

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
    rename(CACHE)
    rename(recognise.FILE)
    rename(WRITTEN, inner=True)
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
    pairs = pair(dir, src, rels, rows)
    known = recognise.load(dir)  # what each track sounds like, when recognise.py has asked
    g = genres.load(dir)
    table = genres.lookup(g["list"])
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
                "bpm": a.get("bpm", 0), "musical_key": a.get("key", ""),
                "tag_genre": a.get("genre", ""), "sc_genre": (row or {}).get("genre", ""),
                "mb_genres": (known.get(rel) or {}).get("genres") or [],
                "sounds_like": " - ".join(x for x in ((known.get(rel) or {}).get("names") or [["", ""]])[0] if x),
                "sc_tags": (row or {}).get("tags", []), "url": (row or {}).get("url", ""),
                "playlist": (row or {}).get("playlist", ""), "index": (row or {}).get("index", 0),
                "was": was.get(rel, "")}  # where this file sat before it was moved: the decks' libraries follow
        f = came["songs"].get(rel) or {}  # from another USB: its name, the playlists it was in there, and what that
        song.update(friend=f.get("from", ""), lists=lists_of.get(rel, []), anlz=f.get("anlz", ""),  # USB's rekordbox
                    friend_bpm=f.get("bpm", 0), friend_key=f.get("key", ""), cues=f.get("cues") or [])  # knew of it
        try:
            st = os.stat(os.path.join(src, rel))
            song["size"], song["mtime"] = st.st_size, int(st.st_mtime)
        except OSError:
            song["size"], song["mtime"] = 0, 0
        song["genres"], song["from"] = genres.decide(song, g, table)
        song["heard"] = genres.heard(song)
        out.append(song)
    out.sort(key=lambda s: (s["artist"].lower(), s["title"].lower()))
    return out


def playlists(songs, g, came=None):
    """The playlists the decks get, in order: [(name, [songs])]. All inside one "The Crate" folder there.
    came: the playlists copied in from another USB (friend.py's record): {name: {"rels": [...]}}."""
    lists = [("All songs", songs), ("Newest 50", sorted(songs, key=lambda s: -s["mtime"])[:50])]
    mine = list(dict.fromkeys(s["playlist"] for s in songs if s["playlist"]))
    if len(mine) > 1:  # every SoundCloud playlist of yours in one, playlist after playlist
        spot = {n: i for i, n in enumerate(mine)}
        lists.append((SOUNDCLOUD, sorted((s for s in songs if s["playlist"]),
                                         key=lambda s: (spot[s["playlist"]], s["index"]))))
    for name in mine:
        lists.append((name, sorted((s for s in songs if s["playlist"] == name), key=lambda s: s["index"])))
    by = {s["rel"]: s for s in songs}
    for name, l in (came or {}).items():  # in the order they had on the other USB
        items = [by[r] for r in l.get("rels", []) if r in by]
        if items:
            lists.append((name, items))
    order = {n: i for i, n in enumerate(g["list"])}
    used = sorted({x for s in songs for x in s["genres"]}, key=lambda n: (order.get(n, 999), n.lower()))
    for name in used:
        lists.append((name, [s for s in songs if name in s["genres"]]))
    none = [s for s in songs if not s["genres"]]
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
    if r.returncode:
        log(dir, "ANALYSER PROBLEM: " + (r.stderr.strip().splitlines() or ["stopped"])[-1][:300])


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
        if not wait:
            return
        fcntl.flock(lock, fcntl.LOCK_EX)
    while os.path.exists(again):
        os.remove(again)
        once(dir, src, volumes)


def busy(dir):
    """True while a run is going (the page says so)."""
    try:
        with open(os.path.join(dir, ".dj.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError as e:
        return isinstance(e, BlockingIOError)


def once(dir, src, volumes):
    usb = read(dir, "usb.txt").strip()
    stick = os.path.join(volumes, usb) if usb and os.path.isdir(os.path.join(volumes, usb)) else ""
    if stick:  # first, so it's right away: a song you threw back leaves the USB too (usb.sh does this as well)
        try:
            said = usb_tidy.say(*usb_tidy.tidy(dir, src, os.path.join(stick, "SoundCloud Sync")))
            if said:
                log(dir, f'USB "{usb}": {said}')
        except Exception as e:  # never silent: the page shows the last lines of dj.log
            log(dir, f'USB PROBLEM on "{usb}": {e}')
    for step in (better, friend.prune):
        try:
            step(dir, src)
        except Exception as e:  # never silent: the page shows the last lines of dj.log
            log(dir, f"COPY PROBLEM: {e!r}"[:300])
    analyse(dir, src)
    songs = library(dir, src)
    there = seen(dir, src, songs, stick)
    if adopt(dir, songs, there):  # a genre you changed on the decks' side is now your pick
        songs = library(dir, src)
    lists = playlists(songs, genres.load(dir), friend.load(dir)["lists"])
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
    else:
        run(d, s, os.environ.get("VOLUMES") or "/Volumes", "--wait" in sys.argv)
