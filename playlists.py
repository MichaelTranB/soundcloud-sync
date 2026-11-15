#!/usr/bin/env python3
"""Reads a public Spotify or Apple Music playlist from its own web page: the name and each track's artist, title,
length and link. Nothing to sign in to. These songs can't be downloaded from Spotify or Apple (they only stream),
so the sync looks for each one on Soulseek and lists shop links, the same as a SoundCloud track that isn't free.

Spotify's public player page shows the first 100 tracks of a playlist; a longer one is read up to there and the
page says so. Apple Music's page holds the whole list.

Usage: playlists.py tobuy URL DIR    writes DIR/to-buy.tsv (tracks not on the Mac yet) and DIR/.service
"""
import html, json, os, re, sys, urllib.request

SPOTIFY = re.compile(r"^https://open\.spotify\.com/(?:intl-[a-z-]+/)?(?:embed/)?playlist/([A-Za-z0-9]{10,40})(?:[/?#]\S*)?$")
APPLE = re.compile(r"^https://(?:embed\.)?music\.apple\.com/[a-z]{2}/playlist/(?:[^/?#\s]+/)?(pl\.[A-Za-z0-9.-]+)(?:[/?#]\S*)?$")
SPOTIFY_CAP = 100  # what Spotify's public player page shows
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


def service(url):
    """'spotify', 'apple' or '' (anything else: SoundCloud's own reader handles it)."""
    return "spotify" if SPOTIFY.match(url or "") else "apple" if APPLE.match(url or "") else ""


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(8_000_000).decode("utf-8", "replace")


def script(page, attr):
    m = re.search(r"<script[^>]*" + attr + r"[^>]*>(.*?)</script>", page, re.S)
    return json.loads(html.unescape(m.group(1)) if m.group(1).lstrip().startswith("&") else m.group(1)) if m else None


def spotify(url):
    pid = SPOTIFY.match(url).group(1)
    data = script(fetch(f"https://open.spotify.com/embed/playlist/{pid}"), r'id="__NEXT_DATA__"')
    e = data["props"]["pageProps"]["state"]["data"]["entity"]
    tracks = []
    for t in e.get("trackList") or []:
        tid = str(t.get("uri", "")).rpartition(":")[2]
        artists = [a.strip() for a in str(t.get("subtitle", "")).replace("\xa0", " ").split(", ") if a.strip()]
        if t.get("title") and tid:
            tracks.append({"artist": ", ".join(artists), "title": t["title"], "secs": round((t.get("duration") or 0) / 1000),
                           "link": f"https://open.spotify.com/track/{tid}"})
    return {"title": e.get("name") or e.get("title") or "Spotify playlist", "tracks": tracks,
            "capped": len(tracks) >= SPOTIFY_CAP}


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
    return {"title": name or "Apple Music playlist", "tracks": tracks, "capped": bool(m) and len(tracks) < int(m.group(1))}


def read(url):
    """{'title', 'tracks': [{'artist','title','secs','link'}], 'capped'} for a Spotify or Apple Music playlist."""
    return spotify(url) if service(url) == "spotify" else apple(url)


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
    p = read(url)
    if not p["tracks"]:
        raise SystemExit("No tracks on that playlist page (is it public?)")
    have, clean = got(d), lambda s: re.sub(r"[\t\n]+", " ", str(s)).strip()
    rows = ["\t".join([clean(f"{t['artist']} - {t['title']}"), t["link"], "", str(t["secs"] or ""),
                       clean(t["artist"]), clean(t["title"])]) for t in p["tracks"] if t["link"] not in have]
    with open(os.path.join(d, "to-buy.tsv"), "w") as f:
        f.write("\n".join(rows) + ("\n" if rows else ""))
    with open(os.path.join(d, ".service"), "w") as f:  # what the page shows: which service, and Spotify's cap
        json.dump({"service": service(url), "count": len(p["tracks"]), "capped": p["capped"]}, f)
    print(f"{service(url)}: {len(p['tracks'])} tracks, {len(rows)} to get")


if __name__ == "__main__":
    if sys.argv[1:2] == ["tobuy"] and len(sys.argv) == 4:
        tobuy(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2:
        print(json.dumps(read(sys.argv[1]), indent=1, ensure_ascii=False)[:3000])
    else:
        sys.exit(__doc__)
