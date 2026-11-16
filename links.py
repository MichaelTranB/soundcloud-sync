#!/usr/bin/env python3
"""What each song's free-download link really needs, shown beside the song: free behind a follow or an email, paid
(and how much), for paying members only, or gone.

Two places fill it in (link-status.json, by the song's own link):
- The Crate itself, once a day per link: a Bandcamp page says its price, and a link that answers "not found" is gone.
  Pages that need a browser (Patreon, Laylo...) are left to the next one.
- Claude or Codex, while getting the free downloads: on its list page it marks a song paid, members only, gone or
  skipped, with a short note (the price, or why).
A song marked paid, members only or gone drops off the assistant's list, so it isn't tried again.
"""
import html, json, os, re, time, urllib.error, urllib.request

FILE = "link-status.json"
UA = "TheCrate (+https://github.com/MichaelTranB/soundcloud-sync)"  # who's asking, said plainly
KINDS = {"paid", "members", "gone", "skipped", "free"}
NOT_FREE = {"paid", "members", "gone"}  # the assistant leaves these out
DAY = 86400
SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$", "AUD": "A$", "JPY": "¥"}


def load(d):
    try:
        with open(os.path.join(d, FILE)) as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d, s):
    p = os.path.join(d, FILE)
    with open(p + ".tmp", "w") as f:
        json.dump(s, f)
    os.replace(p + ".tmp", p)


def mark(d, link, url, kind, note="", by="you"):
    """Sets (or with kind '', clears) what a song's free link needs."""
    s = load(d)
    if kind:
        s[link] = {"kind": kind, "note": re.sub(r"\s+", " ", note).strip()[:140], "url": url, "by": by, "at": time.time()}
    else:
        s.pop(link, None)
    _save(d, s)


def hint(url):
    """What the kind of page usually asks, from its address alone: (kind, note)."""
    h = re.sub(r"^www\.", "", (re.match(r"https?://([^/?#]+)", url or "") or [None, ""])[1].lower())
    if h.endswith("laylo.com"):
        return "gate", "Asks for your email or phone number"
    if h.endswith("patreon.com"):
        return "patreon", "Patreon post: often for paying members only"
    if h.endswith("bandcamp.com"):
        return "", "On Bandcamp"
    if any(h.endswith(g) for g in ("hypeddit.com", "toneden.io", "valorizd.app", "ffm.to", "fanlink.tv", "gate.fm",
                                   "show.co", "smarturl.it", "push.fm", "feature.fm")):
        return "gate", "Asks for a follow first"
    return "", ""


def check(url):
    """What the page itself says, when it can be read without a browser: (kind, note), or None."""
    if "patreon.com" in url:  # Patreon turns away anything but a browser
        return None
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read(3_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return ("gone", "The link is dead: the artist took it down. Buy it or ask the artist.") if e.code in (404, 410) else None
    except Exception:
        return None
    m = re.search(r'data-tralbum="([^"]*)"', page)  # a Bandcamp track or album
    if not m:
        return None
    try:
        t = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return None
    if t.get("freeDownloadPage"):
        return "free", "Free download on Bandcamp"
    low = (t.get("current") or {}).get("minimum_price")
    if not isinstance(low, (int, float)):
        return None
    if low <= 0:
        return "free", "Name your price on Bandcamp: $0 works"
    cur = re.search(r'"currency"\s*:\s*"(\w{3})"', html.unescape(page))
    cur = cur.group(1) if cur else "USD"
    return "paid", f"{SYMBOL.get(cur, cur + ' ')}{low:.2f} or more on Bandcamp"


def refresh(d, rows):
    """Reads each free link The Crate hasn't read today (rows: (track link, free link)). Slow and polite: run it in
    the background. What Claude, Codex or you set is left alone."""
    for link, url in rows:
        e = load(d).get(link)
        if e and e.get("url") == url and (e.get("by") != "app" or time.time() - e.get("at", 0) < DAY):
            continue
        got = check(url)
        s = load(d)  # read again: the assistant may have marked something meanwhile
        e = s.get(link)
        if e and e.get("url") == url and e.get("by") != "app":
            continue
        s[link] = {"kind": got[0] if got else "", "note": got[1] if got else "", "url": url, "by": "app", "at": time.time()}
        _save(d, s)
        time.sleep(2)


def status(s, link, url):
    """{'kind','note','by'} for the page: what was found or set, else what the page usually asks."""
    e = s.get(link)
    if e and e.get("url") == url and e.get("kind"):
        return {"kind": e["kind"], "note": e.get("note", ""), "by": e.get("by", "")}
    k, n = hint(url)
    return {"kind": k, "note": n, "by": ""}
