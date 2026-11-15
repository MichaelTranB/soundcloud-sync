#!/usr/bin/env python3
"""Reads yt-dlp's one-JSON-per-track output on stdin and writes the "still to get" list.

For each track not already downloaded it writes: name, SoundCloud link, the artist's own free-download link
when their description carries one (Hypeddit and the other download gates), and the length in seconds
(soulseek.sh uses it to take only the same version). Tracks freedl.py already got (free.tsv) are left out.
Tracks Soulseek got (soulseek.tsv) are left out too: a track on the Mac is never still to get.
Usage: yt-dlp --dump-json ... | tobuy.py archive.txt to-buy.tsv
       tobuy.py --unread PLAYLIST ARCHIVE LISTING   prints the links of playlist tracks (PLAYLIST: "id url" lines,
           from --flat-playlist) not in ARCHIVE and missing from LISTING (SoundCloud refused them: ask again)
       tobuy.py --buttons DIR   adds each track's Free Download button link (read from its public page) to DIR/to-buy.tsv
"""
import json, os, re, sys

if sys.argv[1:2] == ["--unread"]:
    def ids(path, f):
        try:
            with open(path) as fh:
                return {x for x in (f(l) for l in fh if l.strip()) if x}
        except OSError:
            return set()
    def listed(l):
        try:
            return str(json.loads(l).get("id"))
        except ValueError:
            return None
    known = ids(sys.argv[3], lambda l: l.split()[-1]) | ids(sys.argv[4], listed)
    try:
        with open(sys.argv[2]) as f:
            for l in f:
                tid, _, url = l.strip().partition(" ")
                if tid and url and tid not in known:
                    print(url)
    except OSError:
        pass
    sys.exit(0)

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

# The Free Download button under a SoundCloud track (its "buy link", e.g. "FREE DL" -> Hypeddit) is where most
# artists put their free download, and yt-dlp doesn't report it: the track's public page is read for it, like a person
# opening it (no sign-in, one page every 3 seconds). Once per track; a track without one is looked at again after
# 30 days (artists add one later). Only a free one counts: a gate or file host, or a button that says free/download.
STORE = r"//(?:[\w-]+\.)*(?:beatport|spotify|apple|itunes|amazon|tidal|deezer|youtube|youtu|traxsource|junodownload)\.\w+/"
if sys.argv[1:2] == ["--buttons"]:
    import fcntl, time, urllib.request
    d = sys.argv[2]
    tsv, seen_path, now = os.path.join(d, "to-buy.tsv"), os.path.join(d, "buttons.tsv"), time.time()
    seen = {}  # SoundCloud link -> (free link or "", when looked)
    try:
        with open(seen_path) as f:
            for l in f:
                p = l.rstrip("\n").split("\t")
                if len(p) == 3:
                    try:
                        seen[p[0]] = (p[1], float(p[2]))
                    except ValueError:
                        pass
    except OSError:
        pass
    try:
        with open(tsv) as f:
            todo = [p[1] for p in (l.rstrip("\n").split("\t") for l in f) if len(p) > 2 and not p[2]
                    and re.match(r"https://soundcloud\.com/", p[1])]
    except OSError:
        todo = []
    looked = 0
    for link in todo:
        if link in seen and (seen[link][0] or now - seen[link][1] < 30 * 86400):
            continue
        if looked:
            time.sleep(3)
        looked += 1
        try:
            with urllib.request.urlopen(link, timeout=20) as r:
                page = r.read(3_000_000).decode("utf-8", "replace")
        except Exception:
            continue  # not reachable now: looked at next sync
        m = re.search(r'"purchase_url":("(?:[^"\\]|\\.)*")', page)
        t = re.search(r'"purchase_title":("(?:[^"\\]|\\.)*")', page)
        url, title = (json.loads(m.group(1)) if m else ""), (json.loads(t.group(1)) if t else "")
        # Free when the button says so ("Free Download", "FREE DL", "DL", Bandcamp's "Grab"), or it's a download gate;
        # never a store or streaming page, whatever the button says.
        free = re.match(r"https?://", url or "") and not re.search(STORE, url, re.I) and (
            re.search(r"free|download|\bdl\b|\bgrab\b", title or "", re.I) or (FREE.match(url) and not re.search(
                r"bandcamp\.com|linktr\.ee|ffm\.to|lnk\.to|fanlink\.|audiomack\.com", url)))
        seen[link] = (url if free else "", now)
    if looked:
        with open(seen_path + ".tmp", "w") as f:
            f.writelines(f"{k}\t{u}\t{w:.0f}\n" for k, (u, w) in seen.items())
        os.replace(seen_path + ".tmp", seen_path)
    # Into the list's free-link column, under the lock the app's Downloads pickup also takes (it removes rows).
    with open(os.path.join(d, ".to-buy.lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(tsv) as f:
                lines = f.read().splitlines()
        except OSError:
            sys.exit(0)
        out, n = [], 0
        for l in lines:
            p = l.split("\t")
            if len(p) > 2 and not p[2] and seen.get(p[1], ("",))[0]:
                p[2] = seen[p[1]][0]
                n += 1
            out.append("\t".join(p))
        if n:
            with open(tsv + ".tmp", "w") as f:
                f.write("".join(x + "\n" for x in out))
            os.replace(tsv + ".tmp", tsv)
    print(f"Free Download buttons: {n} new" + (f" ({looked} track page(s) read)" if looked else ""))
    sys.exit(0)

archive_path, out_path = sys.argv[1], sys.argv[2]
try:
    with open(archive_path) as f:
        have = {line.split()[-1] for line in f if line.strip()}
except OSError:
    have = set()
try:  # fetched from the artist's free-download link or taken from Downloads (freedl.py); got once, never again,
    # even when the file was later moved or deleted by hand
    with open(os.path.join(os.path.dirname(os.path.abspath(out_path)), "free.tsv")) as f:
        have |= {g[0] for g in (l.rstrip("\n").split("\t") for l in f) if len(g) == 3}
except OSError:
    pass
try:  # got from Soulseek (soulseek.py); the artist's own file still replaces it when it comes (sync.sh pass 1)
    with open(os.path.join(os.path.dirname(os.path.abspath(out_path)), "soulseek.tsv")) as f:
        have |= {l.split("\t")[0] for l in f if l.count("\t") == 2}
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
