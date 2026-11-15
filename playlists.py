#!/usr/bin/env python3
"""Reads a public Spotify or Apple Music playlist from its own web page: the name and each track's artist, title,
length and link. Nothing to sign in to. These songs can't be downloaded from Spotify or Apple (they only stream),
so the sync looks for each one on Soulseek and lists shop links, the same as a SoundCloud track that isn't free.

Spotify's public player page shows the first 100 tracks of a playlist. For a longer one, the song links copied
from Spotify itself can be pasted into the app (saved in spotify-songs.json): each song's own public page gives its
artist, title and length, a few at a time and slowed down if Spotify asks, and remembered (.spotify-cache.json) so
a later sync reads only songs it hasn't seen. Apple Music's page holds up to 300 songs; a longer one is read up to
there and the page says so. While a long read runs, .reading.json says how far it got (the app shows it).

Usage: playlists.py tobuy URL DIR    writes DIR/to-buy.tsv (tracks not on the Mac yet) and DIR/.service
"""
import html, json, os, re, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

SPOTIFY = re.compile(r"^https://open\.spotify\.com/(?:intl-[a-z-]+/)?(?:embed/)?playlist/([A-Za-z0-9]{10,40})(?:[/?#]\S*)?$")
APPLE = re.compile(r"^https://(?:embed\.)?music\.apple\.com/[a-z]{2}/playlist/(?:[^/?#\s]+/)?(pl\.[A-Za-z0-9.-]+)(?:[/?#]\S*)?$")
SPOTIFY_CAP = 100  # what Spotify's public player page shows
APPLE_CAP = 300  # what Apple Music's public page holds (its own count then says 300 too)
SONG = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z-]+/)?track/|spotify:track:)([A-Za-z0-9]{22})")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


def service(url):
    """'spotify', 'apple' or '' (anything else: SoundCloud's own reader handles it)."""
    return "spotify" if SPOTIFY.match(url or "") else "apple" if APPLE.match(url or "") else ""


def fetch(url, tries=4):
    """The page; a busy answer (429, 5xx) or a dropped connection waits and asks again, longer each time."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read(8_000_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 or n == tries - 1:
                raise
            wait = e.headers.get("Retry-After", "")
            time.sleep(min(int(wait) if wait.isdigit() else 5 * 2 ** n, 60))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if n == tries - 1:
                raise
            time.sleep(5 * 2 ** n)


def script(page, attr):
    m = re.search(r"<script[^>]*" + attr + r"[^>]*>(.*?)</script>", page, re.S)
    return json.loads(html.unescape(m.group(1)) if m.group(1).lstrip().startswith("&") else m.group(1)) if m else None


def pid(url):
    return SPOTIFY.match(url).group(1)


def pasted(d, url):
    """The song ids pasted for this Spotify playlist, in order ([] if none)."""
    try:
        with open(os.path.join(d, "spotify-songs.json")) as f:
            return json.load(f).get(pid(url), [])
    except (OSError, ValueError, AttributeError):
        return []


def paste(d, url, text):
    """Saves the songs pasted for this playlist (Spotify song links or spotify:track: codes, any order or spacing).
    Returns how many."""
    ids = list(dict.fromkeys(SONG.findall(text or "")))
    path = os.path.join(d, "spotify-songs.json")
    try:
        with open(path) as f:
            allp = json.load(f)
    except (OSError, ValueError):
        allp = {}
    allp[pid(url)] = ids
    with open(path + ".tmp", "w") as f:
        json.dump(allp, f)
    os.replace(path + ".tmp", path)
    return len(ids)


def song(tid):
    """One Spotify song from its own public player page: {'artist','title','secs'}."""
    e = script(fetch(f"https://open.spotify.com/embed/track/{tid}"), r'id="__NEXT_DATA__"')
    e = e["props"]["pageProps"]["state"]["data"]["entity"]
    artists = [a.get("name", "").strip() for a in e.get("artists") or [] if a.get("name")]
    return {"artist": ", ".join(artists), "title": e.get("name") or e.get("title") or "",
            "secs": round((e.get("duration") or 0) / 1000)}


def save(obj, path):
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)


def progress(d, done, total):
    if d:
        with open(os.path.join(d, ".reading.json.tmp"), "w") as f:
            json.dump({"done": done, "total": total}, f)
        os.replace(os.path.join(d, ".reading.json.tmp"), os.path.join(d, ".reading.json"))


def spotify(url, d=None):
    data = script(fetch(f"https://open.spotify.com/embed/playlist/{pid(url)}"), r'id="__NEXT_DATA__"')
    e = data["props"]["pageProps"]["state"]["data"]["entity"]
    tracks = []
    for t in e.get("trackList") or []:
        tid = str(t.get("uri", "")).rpartition(":")[2]
        artists = [a.strip() for a in str(t.get("subtitle", "")).replace("\xa0", " ").split(", ") if a.strip()]
        if t.get("title") and tid:
            tracks.append({"artist": ", ".join(artists), "title": t["title"], "secs": round((t.get("duration") or 0) / 1000),
                           "link": f"https://open.spotify.com/track/{tid}"})
    title = e.get("name") or e.get("title") or "Spotify playlist"
    ids = pasted(d, url) if d else []
    if not ids:
        return {"title": title, "tracks": tracks, "capped": len(tracks) >= SPOTIFY_CAP}
    # The pasted list is the playlist. (Not merged with the public first 100: Spotify's own playlists differ per
    # listener, so the two can hold different songs. Songs added later: paste again.)
    known = {t["link"].rpartition("/")[2]: t for t in tracks}
    order = ids
    cpath = os.path.join(d, ".spotify-cache.json")
    try:
        with open(cpath) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    todo = [i for i in order if i not in known and i not in cache]
    lock, done = threading.Lock(), [len(order) - len(todo)]

    def one(tid):
        try:
            s = song(tid)
        except Exception:  # this song's page didn't answer: left out now, asked again next sync
            s = None
        time.sleep(0.3)  # 3 at a time, about 10 a second at most: gentle on Spotify
        with lock:
            if s and s["title"]:
                cache[tid] = s
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == len(order):
                progress(d, done[0], len(order))
            if done[0] % 50 == 0:  # a sync stopped halfway keeps what it read
                save(cache, cpath)

    if todo:
        progress(d, done[0], len(order))
        with ThreadPoolExecutor(3) as pool:
            list(pool.map(one, todo))
        save(cache, cpath)
    out = []
    for i in order:
        s = known.get(i) or cache.get(i)
        if s:
            out.append({**s, "link": f"https://open.spotify.com/track/{i}"} if "link" not in s else s)
    return {"title": title, "tracks": out, "capped": False, "pasted": len(ids), "missing": len(order) - len(out)}


def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def apple(url):
    page = fetch(url)
    tracks, seen = [], set()
    for d in walk(script(page, r'id="serialized-server-data"') or []):
        link = (d.get("contentDescriptor") or {}).get("url") if isinstance(d.get("contentDescriptor"), dict) else None
        artist = [s.get("title") for s in d.get("subtitleLinks") or [] if isinstance(s, dict) and s.get("title")]
        if d.get("title") and link and artist and d.get("duration") and link not in seen:
            seen.add(link)
            tracks.append({"artist": ", ".join(artist), "title": d["title"], "secs": round(d["duration"] / 1000), "link": link})
    name = ""
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            j = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(j, dict) and j.get("@type") == "MusicPlaylist":
            name = j.get("name") or ""
    if not name:
        m = re.search(r'<meta property="og:title" content="([^"]*)"', page)
        name = html.unescape(m.group(1)).split(" - Apple Music")[0].split(" on Apple Music")[0] if m else ""
    m = re.search(r'"numTracks":\s*(\d+)', page)
    return {"title": name or "Apple Music playlist", "tracks": tracks,
            "capped": len(tracks) >= APPLE_CAP or bool(m) and len(tracks) < int(m.group(1))}


def read(url, d=None):
    """{'title', 'tracks': [{'artist','title','secs','link'}], 'capped'} for a Spotify or Apple Music playlist
    (with d, the app's folder: a pasted Spotify song list is read too)."""
    return spotify(url, d) if service(url) == "spotify" else apple(url)


def got(d):
    """Links already on the Mac: from the artist's own link or Downloads (free.tsv) or from Soulseek (soulseek.tsv)."""
    have = set()
    for name, col, n in (("free.tsv", 0, 3), ("soulseek.tsv", 0, 3)):
        try:
            with open(os.path.join(d, name)) as f:
                have |= {g[col] for g in (l.rstrip("\n").split("\t") for l in f) if len(g) == n}
        except OSError:
            pass
    return have


def tobuy(url, d):
    try:
        p = read(url, d)
    finally:
        try:
            os.remove(os.path.join(d, ".reading.json"))
        except OSError:
            pass
    if not p["tracks"]:
        raise SystemExit("No tracks on that playlist page (is it public?)")
    have, clean = got(d), lambda s: re.sub(r"[\t\n]+", " ", str(s)).strip()
    # The name reads "Artist - Song (Remastered 2011)": the other readers (Downloads pickup, To Buy.txt) take the
    # part after the last " - " as the song, so Spotify's "Song - Remastered 2011" / "- Radio Edit" go in brackets.
    name = lambda t: clean(f"{t['artist']} - " + re.sub(r"^(.+?)\s+-\s+(.+)$", r"\1 (\2)", t["title"]))
    rows = ["\t".join([name(t), t["link"], "", str(t["secs"] or ""),
                       clean(t["artist"]), clean(t["title"])]) for t in p["tracks"] if t["link"] not in have]
    with open(os.path.join(d, "to-buy.tsv"), "w") as f:
        f.write("\n".join(rows) + ("\n" if rows else ""))
    with open(os.path.join(d, ".service"), "w") as f:  # what the page shows: which service, and Spotify's cap
        json.dump({"service": service(url), "count": len(p["tracks"]), "capped": p["capped"],
                   "pasted": p.get("pasted", 0), "missing": p.get("missing", 0)}, f)
    print(f"{service(url)}: {len(p['tracks'])} tracks, {len(rows)} to get")


if __name__ == "__main__":
    if sys.argv[1:2] == ["tobuy"] and len(sys.argv) == 4:
        tobuy(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2:
        print(json.dumps(read(sys.argv[1]), indent=1, ensure_ascii=False)[:3000])
    else:
        sys.exit(__doc__)
