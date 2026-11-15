#!/usr/bin/env python3
"""Reads yt-dlp's one-JSON-per-track output on stdin and writes the "still to get" list.

For each track not already downloaded it writes: name, SoundCloud link, the artist's own free-download link
when their description carries one (Hypeddit and the other download gates), and the length in seconds
(soulseek.sh uses it to take only the same version). Tracks freedl.py already fetched (free.tsv) are left out.
Usage: yt-dlp --dump-json ... | tobuy.py archive.txt to-buy.tsv
"""
import json, os, re, sys

# The gates and hosts artists use to give a track away. Only the artist's own description is read.
FREE = re.compile(
    r"https?://(?:www\.)?(?:hypeddit\.com|hypeddit\.co|hype\.to|hyperfollow\.com|toneden\.io|fanlink\.to|fanlink\.tv|"
    r"pumpyoursound\.com|edmdisc\.com|theartistunion\.com|click\.dj|gate\.fm|[\w-]+\.bandcamp\.com|"
    r"dropbox\.com|dl\.dropboxusercontent\.com|drive\.google\.com|mega\.nz|wetransfer\.com|we\.tl|mediafire\.com|"
    r"krakenfiles\.com|pixeldrain\.com|audiomack\.com|ffm\.to|lnk\.to|linktr\.ee)/[^\s\"'<>)]*"
    r"|https://[^\s\"'<>)]+\.(?:wav|flac|aiff?|mp3|m4a|zip)(?:\?[^\s\"'<>)]*)?(?=[\s\"'<>).,]|$)",
    re.I)

DIRECT = re.compile(r"//(?:www\.)?(?:dropbox\.com|dl\.dropboxusercontent\.com|drive\.google\.com|pixeldrain\.com)/"
                    r"|\.(?:wav|flac|aiff?|mp3|m4a|zip)(?:\?|$)", re.I)

archive_path, out_path = sys.argv[1], sys.argv[2]
try:
    with open(archive_path) as f:
        have = {line.split()[-1] for line in f if line.strip()}
except OSError:
    have = set()
try:  # fetched from the artist's free-download link by freedl.py, file still there
    with open(os.path.join(os.path.dirname(os.path.abspath(out_path)), "free.tsv")) as f:
        have |= {g[0] for g in (l.rstrip("\n").split("\t") for l in f) if len(g) == 3 and os.path.exists(g[2])}
except OSError:
    pass

clean = lambda s: re.sub(r"\s+", " ", str(s or "")).strip()
rows = []
for line in sys.stdin:
    try:
        t = json.loads(line)
    except ValueError:
        continue
    if str(t.get("id")) in have or t.get("webpage_url") in have:
        continue
    links = [m.group(0).rstrip(".,") for m in FREE.finditer(t.get("description") or "")]
    # A link straight to the file (freedl.py fetches those) beats a gate or a link page.
    links.sort(key=lambda u: not DIRECT.search(u))
    rows.append("\t".join([clean(f"{t.get('uploader', '')} - {t.get('title', '')}"), clean(t.get("webpage_url")),
                           links[0] if links else "", str(round(t.get("duration") or 0) or "")]))

with open(out_path, "w") as f:
    f.write("\n".join(rows) + ("\n" if rows else ""))
