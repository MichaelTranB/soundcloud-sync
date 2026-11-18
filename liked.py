#!/usr/bin/env python3
"""Your Spotify Liked Songs, a few at a time: EDM first, newest first, and never more than the Mac has room for.

How the songs get in: in Spotify, open Liked Songs (sorted by Date added), click the newest song, Shift-click the
oldest one you still want, copy (Cmd+C) and paste into The Crate. Where you stop is your cutoff. No sign-in, no
300-song playlists: the song links are all it needs (saved in liked.json).

Each song's artist, title and length come from its public Spotify page (shared cache with playlists.py). Its kind
comes from the song's title words (genres.py) or, failing that, Deezer's free catalogue: the matching song (same
artist, length within 5 s) and its album's genre. Dance or Electro counts as EDM; anything not matched waits after
the EDM songs, and the rest (Hip Hop, Pop...) comes last.

Every sync adds the next batch to the to-get list (to-buy.tsv), so Soulseek looks for them like any playlist song.
A batch is at most BATCH songs and only what fits: the Mac keeps FLOOR_GB free, and a batch that can't start says
so on the page (liked-state.json) and in liked.log.

Usage: liked.py read DIR       read details and kinds of every pasted song (the page starts it after a paste)
       liked.py add DIR OUT    the sync's step: add the next batch to DIR/to-buy.tsv
"""
import json, os, re, shutil, sys, time, unicodedata, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

import genres, playlists, soulseek

FILE = "liked.json"  # {"ids": [...newest first], "at": when pasted}
KINDS = ".liked-kinds.json"  # song id -> "EDM" | "Other" | "" (Deezer had no match)
STATE = "liked-state.json"  # what the page shows
LIKED = "https://open.spotify.com/collection/tracks"  # Spotify's own address for Liked Songs
BATCH = 150  # songs a sync adds at most (Soulseek allows only so many searches a minute)
FLOOR_GB = 10  # always left free on the Mac
SONG_MB = 50  # a lossless song, roughly (AIFF ~60, FLAC ~35, MP3 320 ~12)
EDM_IDS = {106, 113}  # Deezer: Electro, Dance
UA = "TheCrate (+https://github.com/MichaelTranB/soundcloud-sync)"


def _load(d, name, default):
    try:
        with open(os.path.join(d, name)) as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError):
        return default


def _save(d, name, obj):
    p = os.path.join(d, name)
    with open(p + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(p + ".tmp", p)


def ids(d):
    return _load(d, FILE, {}).get("ids", [])


def paste(d, text):
    """Saves the pasted Liked Songs (newest first, as Spotify copies them). Returns how many."""
    got = list(dict.fromkeys(playlists.SONG.findall(text or "")))
    if got:
        _save(d, FILE, {"ids": got, "at": time.time()})
    return len(got)


def forget(d):
    for name in (FILE, STATE):
        try:
            os.remove(os.path.join(d, name))
        except OSError:
            pass


def _fold(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def deezer_kind(artist, title, secs, albums):
    """'EDM' or 'Other' from Deezer's catalogue, or '' when no song there is clearly this one."""
    first = artist.split(", ")[0]
    bare = re.sub(r"[(\[].*?[)\]]", "", title)  # without '(Extended Mix)' and the like
    q = urllib.parse.quote(f"{first} {bare}".strip())
    for t in (_get(f"https://api.deezer.com/search?q={q}&limit=5").get("data") or []):
        same_artist = _fold(first) in _fold(t.get("artist", {}).get("name")) or _fold(t.get("artist", {}).get("name")) in _fold(artist)
        same_len = not secs or abs((t.get("duration") or 0) - secs) <= 5
        if not (same_artist and same_len):
            continue
        aid = (t.get("album") or {}).get("id")
        if aid not in albums:
            a = _get(f"https://api.deezer.com/album/{aid}")
            albums[aid] = [g.get("id") for g in (a.get("genres") or {}).get("data") or []] or [a.get("genre_id")]
            time.sleep(0.2)
        return "EDM" if EDM_IDS & set(albums[aid]) else "Other" if albums[aid] and albums[aid] != [None] else ""
    return ""


EDM_WORDS = {g for g in genres.DEFAULT if g not in ("Hip Hop", "R&B", "Pop", "Rock")}


def title_kind(title):
    """'EDM' when the version part of the title names an EDM style ('Song (Dubstep Remix)', 'Song - DnB Flip'),
    else ''. Only that part: a song called 'House of Gold' is not House."""
    table = genres.lookup(genres.DEFAULT)
    part = " ".join(re.findall(r"[(\[]([^)\]]*)[)\]]", title) + re.findall(r"\s-\s(.+)$", title))
    words = _fold(part).split()
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            g = table.get("-".join(words[i:i + n]))
            if g in EDM_WORDS:
                return "EDM"
    return ""


def read_all(d, say=print):
    """Details and kind for every pasted song not read yet. Slow and polite; safe to stop and run again."""
    todo_ids = ids(d)
    cpath = os.path.join(d, ".spotify-cache.json")
    cache = _load(d, ".spotify-cache.json", {})
    missing = [i for i in todo_ids if i not in cache]
    if missing:
        say(f"reading {len(missing)} song page(s) on Spotify")

        def one(tid):
            try:
                s = playlists.song(tid)
            except Exception:
                return None
            time.sleep(0.3)
            return tid, s
        with ThreadPoolExecutor(3) as pool:
            for n, r in enumerate(pool.map(one, missing), 1):
                if r and r[1]["title"]:
                    cache[r[0]] = r[1]
                if n % 100 == 0:
                    playlists.save(cache, cpath)
                    _state(d, reading=f"Reading songs: {n} of {len(missing)}")
        playlists.save(cache, cpath)
    kinds, albums = _load(d, KINDS, {}), {}
    left = [i for i in todo_ids if i in cache and i not in kinds]
    for n, i in enumerate(left, 1):
        s = cache[i]
        k = title_kind(s["title"])
        if not k:
            try:
                k = deezer_kind(s["artist"], s["title"], s.get("secs"), albums)
            except Exception:  # Deezer busy or away: this one is tried again next time
                continue
            time.sleep(0.25)
        kinds[i] = k
        if n % 50 == 0:
            _save(d, KINDS, kinds)
            _state(d, reading=f"Sorting EDM from the rest: {n} of {len(left)}")
    _save(d, KINDS, kinds)
    _state(d)


def free_gb(path):
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return 0.0


def _state(d, out=None, **extra):
    all_ids, cache, kinds = ids(d), _load(d, ".spotify-cache.json", {}), _load(d, KINDS, {})
    have = playlists.got(d)
    link = lambda i: f"https://open.spotify.com/track/{i}"
    count = lambda k: sum(1 for i in all_ids if kinds.get(i) == k)
    st = {"total": len(all_ids), "edm": count("EDM"), "other": count("Other"),
          "unsure": sum(1 for i in all_ids if i in cache and not kinds.get(i)),
          "have": sum(1 for i in all_ids if link(i) in have), "at": time.time()}
    old = _load(d, STATE, {})
    for k in ("queued", "paused", "freeGb"):
        if k in old and k not in extra:
            st[k] = old[k]
    st.update(extra)
    _save(d, STATE, st)
    return st


def status(d):
    """What the page shows, or None before anything was pasted."""
    if not ids(d):
        return None
    return _load(d, STATE, {}) or {"total": len(ids(d))}


def order(d):
    """Song ids in the order they're fetched: EDM newest first, then not sure, then the rest."""
    all_ids, kinds = ids(d), _load(d, KINDS, {})
    rank = {"EDM": 0, "": 1, None: 1, "Other": 2}
    return sorted(all_ids, key=lambda i: rank.get(kinds.get(i), 1))  # stable: newest first within each


def add(d, out, say=print):
    """Adds the next batch to to-buy.tsv (rows playlists.tobuy writes). Returns how many were added."""
    if not ids(d):
        return 0
    read_all(d, say)
    cache = _load(d, ".spotify-cache.json", {})
    path = os.path.join(d, "to-buy.tsv")
    try:
        with open(path) as f:
            rows = [l for l in f.read().splitlines() if l]
    except OSError:
        rows = []
    listed = {r.split("\t")[1] for r in rows if r.count("\t") >= 1}
    have, miss, now = playlists.got(d), soulseek.load_missed(d), time.time()
    gb = free_gb(out if os.path.isdir(out) else os.path.expanduser("~"))
    room = max(0, int((gb - FLOOR_GB) * 1000 / SONG_MB))
    clean = lambda v: re.sub(r"[\t\n]+", " ", str(v)).strip()
    name = lambda s: clean(f"{s['artist']} - " + re.sub(r"^(.+?)\s+-\s+(.+)$", r"\1 (\2)", s["title"]))
    try:  # a song already on the Mac under the same name (from SoundCloud, say) isn't fetched twice
        on_mac = {soulseek.norm(os.path.splitext(f)[0]) for f in os.listdir(out)}
    except OSError:
        on_mac = set()
    fresh, waiting = [], []
    for i in order(d):
        s, link = cache.get(i), f"https://open.spotify.com/track/{i}"
        if not s or link in have or link in listed or soulseek.norm(name(s)) in on_mac:
            continue
        m = miss.get(link)
        if m and not soulseek.due(m, m[0], now):
            waiting.append((link, s))  # Soulseek had none lately: kept listed so its wait is remembered
        elif len(fresh) < min(BATCH, room):
            fresh.append((link, s))
    new =["\t".join([name(s), link, "", str(s.get("secs") or ""), clean(s["artist"]), clean(s["title"])])
           for link, s in fresh + waiting]
    with open(path, "w") as f:
        f.write("\n".join(rows + new) + ("\n" if rows or new else ""))
    left = sum(1 for i in ids(d) if f"https://open.spotify.com/track/{i}" not in have)
    paused = room == 0 and left > 0
    _state(d, queued=len(fresh), paused=paused, freeGb=round(gb, 1))
    msg = f"Liked Songs: {len(fresh)} added to look for" + (f", {len(waiting)} waiting" if waiting else "")
    if paused:
        msg = f"Liked Songs PAUSED: only {gb:.0f} GB free on the Mac (keeps {FLOOR_GB} GB free); {left} songs wait"
    say(msg)
    return len(fresh)


if __name__ == "__main__":
    log = lambda m: print(f"{time.strftime('%F %R')}  {m}", flush=True)
    if sys.argv[1:2] == ["read"] and len(sys.argv) == 3:
        read_all(sys.argv[2], log)
    elif sys.argv[1:2] == ["add"] and len(sys.argv) == 4:
        add(sys.argv[2], sys.argv[3], log)
    else:
        sys.exit(__doc__)
