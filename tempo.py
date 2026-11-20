"""Which tempo each song is shown and written with (the note dj-tempo.json).

A deck's or rekordbox's own analysis is the tempo wherever there is one. The Crate's own count is used only when a
second, different counter agrees with it; otherwise the song has no tempo here and the decks work it out when they
load it: a guess is never put in front of you as a fact. In this order:
  1. rekordbox on this Mac: the beat grid in its analysis of the song (what plays, not the number in its list);
  2. the analysis a song brought along from another USB (friend.py);
  3. Engine DJ on the USB, once a deck has analysed the song there;
  4. The Crate's own count (dj_analyze.py), when its second count is within 2% of it.
A source that can't be reached now (the USB is out) keeps what it said for as long as the file is the same one.
Run by dj.py through the private Python (rekordbox's library is read with pyrekordbox). Reads only; the one file
it writes is its note.

    tempo.py    a job on stdin: {"dir", "src", "usb", "songs"}; prints one line when the note changed"""
import json, os, struct, sys
from collections import Counter

NOTE = "dj-tempo.json"
RANK = {"rekordbox": 4, "usb": 3, "engine": 2, "crate": 1}  # whose word counts most
CLOSE = 0.02  # two counts this near each other are the same tempo
SOURCES = {"rekordbox": "rekordbox's analysis", "usb": "the analysis it came with", "engine": "the deck's analysis",
           "crate": "counted twice on this Mac"}  # how the page says where a tempo is from


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


def save(dir, note):
    tmp = os.path.join(dir, NOTE + ".tmp")
    with open(tmp, "w") as f:
        json.dump(note, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, os.path.join(dir, NOTE))


def decks(usb, songs):
    """What Engine DJ on the USB found for each song a deck has analysed there: {song: tempo}. Reads only."""
    import sqlite3
    import engine, place
    db = engine.db_path(usb) if usb else ""
    if not db or not os.path.isfile(db):
        return {}
    try:
        con = sqlite3.connect(db, timeout=20)
        try:
            have = {engine.nfc(p): b for p, b in
                    con.execute("SELECT path, bpmAnalyzed FROM Track WHERE isAnalyzed = 1") if p and b}
        finally:
            con.close()
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
    deck = decks(job.get("usb") or "", songs)
    out = {}
    for s in songs:
        rel, now = s["rel"], (0, "")
        m = mac.get(rel)
        if m and m.get("bpm"):
            now = (m["bpm"] / 100, "rekordbox")
        if not now[0]:
            came = (grid(s["anlz"]) if s.get("anlz") else 0) or int(s.get("friend_bpm") or 0)
            if came:
                now = (came / 100, "usb")
        if not now[0] and deck.get(rel):
            now = (deck[rel], "engine")
        if not now[0] and agreed(s.get("own_bpm"), s.get("bpm2")):
            now = (float(s["own_bpm"]), "crate")
        had = said(old, s)
        if had[0] and RANK.get(had[1], 0) > RANK.get(now[1], 0):  # (its source is out of reach just now)
            now = had
        if now[0]:
            out[rel] = {"bpm": round(now[0], 2), "from": now[1], "size": s.get("size"), "mtime": s.get("mtime")}
    line = ""
    if out != old or not os.path.exists(os.path.join(dir, NOTE)):
        save(dir, out)
        n = Counter(e["from"] for e in out.values())
        parts = [f"{n[k]} from {w}" for k, w in (("rekordbox", "rekordbox"), ("usb", "another USB"), ("engine", "the decks"))
                 if n[k]]
        parts += [f"{n['crate']} counted here"] if n["crate"] else []
        left = len(songs) - len(out)
        parts += [f"{left} left for the decks to analyse"] if left else []
        line = "tempo: " + ", ".join(parts) if parts else ""
    return out, line


if __name__ == "__main__":
    print(settle(json.load(sys.stdin))[1])
