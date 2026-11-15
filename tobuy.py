#!/usr/bin/env python3
"""Reads yt-dlp's one-JSON-per-track output on stdin and writes the "still to get" list.

For each track not already downloaded it writes: name, SoundCloud link, and the artist's own
free-download link when their description carries one (Hypeddit and the other download gates).
Usage: yt-dlp --dump-json ... | tobuy.py archive.txt to-buy.tsv
"""
import json, re, sys

# The gates and hosts artists use to give a track away. Only the artist's own description is read.
FREE = re.compile(
    r"https?://(?:www\.)?(?:hypeddit\.com|hypeddit\.co|hype\.to|hyperfollow\.com|toneden\.io|fanlink\.to|fanlink\.tv|"
    r"pumpyoursound\.com|edmdisc\.com|theartistunion\.com|click\.dj|gate\.fm|[\w-]+\.bandcamp\.com|"
    r"dropbox\.com|dl\.dropboxusercontent\.com|drive\.google\.com|mega\.nz|wetransfer\.com|we\.tl|mediafire\.com|"
    r"krakenfiles\.com|pixeldrain\.com|audiomack\.com|ffm\.to|lnk\.to|linktr\.ee)/[^\s\"'<>)]*",
    re.I)

archive_path, out_path = sys.argv[1], sys.argv[2]
try:
    with open(archive_path) as f:
        have = {line.split()[-1] for line in f if line.strip()}
except OSError:
    have = set()

clean = lambda s: re.sub(r"\s+", " ", str(s or "")).strip()
rows = []
for line in sys.stdin:
    try:
        t = json.loads(line)
    except ValueError:
        continue
    if str(t.get("id")) in have:
        continue
    m = FREE.search(t.get("description") or "")
    rows.append("\t".join([clean(f"{t.get('uploader', '')} - {t.get('title', '')}"), clean(t.get("webpage_url")),
                           m.group(0).rstrip(".,") if m else ""]))

with open(out_path, "w") as f:
    f.write("\n".join(rows) + ("\n" if rows else ""))
