"""Which tempo each song is shown and written with (the note dj-tempo.json).

A deck's or rekordbox's own analysis is the tempo wherever there is one, else The Crate's own beat grid (beats.py),
which goes onto the USB with the song. In this order:
  1. rekordbox on this Mac: the beat grid in its analysis of the song (what plays, not the number in its list);
  2. the analysis a song brought along from another USB (friend.py);
  3. Engine DJ on the USB, once a deck has analysed the song itself there;
  4. The Crate's beat grid, counted at double or half where the song's main genre is counted so (OCTAVE) or where
     you tapped x2 or /2 on the page; where its other counter (dj_analyze.py, or Beat This where it's set up) says
     another tempo, the song is on the page's "check tempo" list;
  5. The Crate's first count, when its second count is within 2% of it (a song it couldn't draw a grid for).
Where rekordbox's grid is the one (1, 2), it's also kept here as The Crate keeps its own, so Engine DJ gets the same
beats (anlz.rekordbox_grid).
A source that can't be reached now (the USB is out) keeps what it said for as long as the file is the same one.
Run by dj.py through the private Python (rekordbox's library is read with pyrekordbox). Reads only; the one file
it writes is its note.

    tempo.py    a job on stdin: {"dir", "src", "usb", "songs"}; prints one line when the note changed"""
import json, os, struct, sys
from collections import Counter

NOTE = "dj-tempo.json"
TAPS = "dj-tempo-taps.json"  # your x2, /2 and Keep on the page: {song key: 0.5, 1 or 2 times The Crate's own count}
# Genres DJs count outside [90, 180), where The Crate's own count lands: its grid is doubled or halved to fit.
OCTAVE = {"Drum & Bass": (150, 200), "Hip Hop": (60, 160), "R&B": (55, 160)}
RANK = {"rekordbox": 5, "usb": 4, "engine": 3, "grid": 2, "crate": 1}  # whose word counts most
CLOSE = 0.02  # two counts this near each other are the same tempo
SOURCES = {"rekordbox": "rekordbox's analysis", "usb": "the analysis it came with", "engine": "the deck's analysis",
           "grid": "The Crate's analysis", "crate": "counted twice on this Mac"}  # how the page says where a tempo is from


def grid(dat, steady=False):
    """The tempo x100 of the beat grid in a rekordbox analysis file (.DAT): the one most of its beats are at.
    0 when the file holds no grid or can't be read; with steady, also when the tempo changes along the song."""
    try:
        with open(dat, "rb") as f:
            d = f.read()
    except OSError:
        return 0
    if d[:4] != b"PMAI" or len(d) < 12:
        return 0
    o = struct.unpack(">I", d[4:8])[0]
    while 12 <= o and o + 12 <= len(d):
        four, head, whole = d[o:o + 4], *struct.unpack(">II", d[o + 4:o + 12])
        if four == b"PQTZ" and head >= 24 and o + 24 <= len(d):
            n = struct.unpack(">I", d[o + 20:o + 24])[0]
            at = o + head
            tempos = Counter(struct.unpack(">H", d[at + 8 * i + 2:at + 8 * i + 4])[0]
                             for i in range(min(n, max(0, (len(d) - at) // 8))))
            tempos.pop(0, None)
            return tempos.most_common(1)[0][0] if tempos and not (steady and len(tempos) > 1) else 0
        if whole < 12:
            break
        o += whole
    return 0


def agreed(own, second):
    """Do The Crate's two counts say the same tempo?"""
    try:
        own, second = float(own or 0), float(second or 0)
    except (TypeError, ValueError):
        return False
    return own > 0 and second > 0 and abs(own - second) <= CLOSE * own


def load(dir):
    """{song: {"bpm", "from", "size", "mtime"}}, as last settled."""
    try:
        with open(os.path.join(dir, NOTE)) as f:
            got = json.load(f)
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def check(song):
    """Should you check this song's tempo? Where it goes by The Crate's grid and the other counter (Beat This where
    it's set up, else dj_analyze's) says something else, more than 2% apart (often double or half). Not once you
    tapped x2, /2 or Keep; and where the genre settled double or half, only a count that is off by more than that."""
    if song.get("bpm_from") != "grid" or song.get("octave") == "you":
        return False
    other = float(song.get("bpm3") or song.get("own_bpm") or 0)
    if not other or agreed(song.get("bpm"), other):
        return False
    return not (song.get("octave") == "genre" and any(agreed(song.get("bpm"), other * f) for f in (2, 0.5)))


def grid_said(note, song):
    """rekordbox's beat grid for a song, as The Crate keeps one, when it's the one the song goes by; else None."""
    e = note.get(song["rel"])
    if not isinstance(e, dict) or e.get("size") != song.get("size") or e.get("mtime") != song.get("mtime"):
        return None
    return e.get("grid") if isinstance(e.get("grid"), dict) else None


def taps(dir):
    """{song key: 0.5, 1 or 2}: your taps on the page's "check tempo" list."""
    try:
        with open(os.path.join(dir, TAPS)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if v in (0.5, 1, 2)} if isinstance(d, dict) else {}


def tap(dir, key, factor):
    """Keep your tap for a song (None: The Crate decides again)."""
    d = taps(dir)
    if factor is None:
        d.pop(key, None)
    else:
        d[key] = factor
    tmp = os.path.join(dir, TAPS + ".tmp")
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(dir, TAPS))


def fold(g, f):
    """A beat grid (beats.py) counted twice as fast (f=2) or half as fast (f=0.5), its bars starting where they did."""
    if not isinstance(g, dict) or not g.get("bpm") or f not in (0.5, 2):
        return g
    if f == 2:
        return {**g, "bpm": round(g["bpm"] * 2, 2), "bar": 2 * g["bar"] % 4}
    odd = g["bar"] % 2  # (every other beat stays: the ones the bar starts on)
    return {**g, "bpm": round(g["bpm"] / 2, 2), "first": round(g["first"] + odd * 60 / g["bpm"], 4), "bar": g["bar"] // 2}


def octave(song, tapped):
    """(how many times The Crate's own count the song goes by, why: "you", "genre" or ""). Your tap, else the
    range its main genre is counted in, else as counted."""
    t = tapped.get(song.get("key"))
    if t in (0.5, 1, 2):
        return t, "you"
    r = OCTAVE.get((song.get("genres") or [""])[0])
    b = float((song.get("own_grid") or {}).get("bpm") or 0)
    if r and b and not r[0] <= b < r[1]:
        for f in (2, 0.5):
            if r[0] <= b * f < r[1]:
                return f, "genre"
    return 1, ""


def said(note, song):
    """(tempo, whose) for a song from the note, (0, "") when it has none or the file is another one since."""
    e = note.get(song["rel"])
    if not isinstance(e, dict) or e.get("size") != song.get("size") or e.get("mtime") != song.get("mtime"):
        return 0, ""
    try:
        return float(e.get("bpm") or 0), str(e.get("from") or "")
    except (TypeError, ValueError):
        return 0, ""


def moved(dir, old, new, size, mtime):
    """A song that became another file with the same sound (a FLAC turned into an AIFF): its tempo goes along."""
    note = load(dir)
    if old in note and new not in note:
        note[new] = {**note.pop(old), "size": size, "mtime": mtime}
        save(dir, note)


def touched(dir, rel, size, mtime):
    """A song whose tags or cover changed (details.py): the sound is the same, so its tempo stays."""
    note = load(dir)
    if isinstance(note.get(rel), dict):
        note[rel] = {**note[rel], "size": size, "mtime": mtime}
        save(dir, note)


def save(dir, note):
    tmp = os.path.join(dir, NOTE + ".tmp")
    with open(tmp, "w") as f:
        json.dump(note, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, os.path.join(dir, NOTE))


def decks(usb, songs, dir):
    """What Engine DJ on the USB found for each song a deck has analysed itself there: {song: tempo}. Reads only.
    (A row The Crate analysed isn't counted: engine.theirs.)"""
    import sqlite3
    import engine, place
    if not usb:
        return {}
    try:
        have = {p: b for p, b in engine.theirs(usb, os.path.join(dir, "dj-backups")).items() if b}
    except sqlite3.Error:
        return {}
    out, roots = {}, [place.web(usb)] + place.others(usb)
    for s in songs:
        n = s.get("at") or s["rel"]
        b = next((have[p] for p in (engine.nfc(f"../{m}/{n}") for m in roots) if p in have), 0)
        if isinstance(b, (int, float)) and 20 < b < 400:
            out[s["rel"]] = float(b)
    return out


def settle(job, master=None):
    """Works out every song's tempo afresh and keeps it in the note. Returns (the note, a line for the log or "")."""
    import rekordbox_usb
    dir, songs = job["dir"], job["songs"]
    old = load(dir)
    mac = rekordbox_usb.mac(job, master)
    deck = decks(job.get("usb") or "", songs, dir)
    import anlz
    out = {}
    for s in songs:
        rel, now, rb = s["rel"], (0, ""), ""
        m = mac.get(rel)
        if m and m.get("bpm"):
            now, rb = (m["bpm"] / 100, "rekordbox"), m.get("anlz") or ""
        if not now[0]:
            came = (grid(s["anlz"]) if s.get("anlz") else 0) or int(s.get("friend_bpm") or 0)
            if came:
                now, rb = (came / 100, "usb"), s.get("anlz") or ""
        if not now[0] and deck.get(rel):
            now = (deck[rel], "engine")
        g = s.get("own_grid") if isinstance(s.get("own_grid"), dict) else None  # (The Crate's, dj_analyze.py)
        if not now[0] and g and g.get("bpm"):
            now = (float(g["bpm"]), "grid")
        if not now[0] and agreed(s.get("own_bpm"), s.get("bpm2")):
            now = (float(s["own_bpm"]), "crate")
        had = said(old, s)
        if had[0] and RANK.get(had[1], 0) > RANK.get(now[1], 0):  # (its source is out of reach just now)
            now = had
        if now[0]:
            out[rel] = {"bpm": round(now[0], 2), "from": now[1], "size": s.get("size"), "mtime": s.get("mtime")}
            theirs = anlz.rekordbox_grid(rb, g) if rb and g and now[1] in ("rekordbox", "usb") else None
            if theirs:  # Engine DJ gets the beats rekordbox plays
                out[rel]["grid"] = theirs
            elif now == had and isinstance((old.get(rel) or {}).get("grid"), dict):
                out[rel]["grid"] = old[rel]["grid"]  # (rekordbox's library is out of reach just now)
    line = ""
    if out != old or not os.path.exists(os.path.join(dir, NOTE)):
        save(dir, out)
        n = Counter(e["from"] for e in out.values())
        parts = [f"{n[k]} from {w}" for k, w in (("rekordbox", "rekordbox"), ("usb", "another USB"), ("engine", "the decks"),
                                                 ("grid", "The Crate's analysis")) if n[k]]
        parts += [f"{n['crate']} counted here"] if n["crate"] else []
        left = len(songs) - len(out)
        parts += [f"{left} left for the decks to analyse"] if left else []
        line = "tempo: " + ", ".join(parts) if parts else ""
    return out, line


if __name__ == "__main__":
    print(settle(json.load(sys.stdin))[1])
