"""The DJ library: every track in the music folder with its tempo, key and genres, written into the libraries the
decks read, with no clicks.

    dj.py <app folder> <music folder>            analyse new tracks, then update every library that is there
    dj.py <app folder> <music folder> --wait     the same, and not back before it's done (usb.sh, before an eject)
    dj.py <app folder> <music folder> --list     print the library as JSON (what the page shows)

Libraries, each only when it exists on this Mac or the plugged-in USB:
  - Engine DJ on the USB (Denon Prime, SC, Mixstream...): engine.py
  - rekordbox on this Mac (Pioneer DDJ controllers, and its own USB export for CDJs): rekordbox.py
Standard library only. Tempo and key need the private Python dj-setup.sh sets up (dj_analyze.py); without it tracks
still reach the decks, which then analyse them on load."""
import fcntl, json, os, re, subprocess, sys, time, unicodedata

import genres

AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus")
# The private Python with Essentia, Mutagen and pyrekordbox (dj-setup.sh); the second is where the first build kept it.
PY = next((p for p in map(os.path.expanduser, ("~/.local/share/crate-dj/python/bin/python3",
                                               "~/.local/share/crate-dj/venv/bin/python")) if os.path.exists(p)),
          os.path.expanduser("~/.local/share/crate-dj/python/bin/python3"))
CACHE = "dj-analysis.json"


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
    try:
        cache = json.load(open(os.path.join(dir, CACHE)))
    except (OSError, ValueError):
        cache = {}
    rows = listing(dir)
    pairs = pair(dir, src, rels, rows)
    g = genres.load(dir)
    table = genres.lookup(g["list"])
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
                "sc_tags": (row or {}).get("tags", []), "url": (row or {}).get("url", ""),
                "playlist": (row or {}).get("playlist", ""), "index": (row or {}).get("index", 0)}
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


def playlists(songs, g):
    """The playlists the decks get, in order: [(name, [songs])]. All inside one "The Crate" folder there."""
    lists = [("All songs", songs), ("Newest 50", sorted(songs, key=lambda s: -s["mtime"])[:50])]
    for name in dict.fromkeys(s["playlist"] for s in songs if s["playlist"]):
        lists.append((name, sorted((s for s in songs if s["playlist"] == name), key=lambda s: s["index"])))
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
    analyse(dir, src)
    songs = library(dir, src)
    lists = playlists(songs, genres.load(dir))
    import engine
    usb = read(dir, "usb.txt").strip()
    if usb and os.path.isdir(os.path.join(volumes, usb)):
        try:
            said = engine.write(os.path.join(volumes, usb), songs, lists, os.path.join(dir, "dj-backups"))
            if said:
                log(dir, f'Engine DJ on "{usb}": {said}')
        except Exception as e:  # never silent: the page shows the last lines of dj.log
            log(dir, f'ENGINE PROBLEM on "{usb}": {e}')
    rekordbox(dir, src, songs, lists)


def rekordbox(dir, src, songs, lists):
    """rekordbox on this Mac, through the private Python (rekordbox.py needs pyrekordbox). Quietly nothing when
    either isn't there."""
    if not os.path.exists(PY):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    job = {"src": src, "backups": os.path.join(dir, "dj-backups"), "songs": songs,
           "lists": [[n, [s["rel"] for s in items]] for n, items in lists]}
    try:
        r = subprocess.run([PY, os.path.join(here, "rekordbox.py")], input=json.dumps(job), capture_output=True,
                           text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return log(dir, "REKORDBOX PROBLEM: took over 15 minutes and was stopped; its library is as it was")
    if r.returncode:
        log(dir, "REKORDBOX PROBLEM: " + (r.stderr.strip().splitlines() or ["stopped"])[-1][:300])
    elif r.stdout.strip():
        log(dir, "rekordbox: " + r.stdout.strip().splitlines()[-1])

if __name__ == "__main__":
    d, s = sys.argv[1], sys.argv[2]
    if "--list" in sys.argv:
        json.dump(library(d, s), sys.stdout, ensure_ascii=False)
    else:
        run(d, s, os.environ.get("VOLUMES") or "/Volumes", "--wait" in sys.argv)
