#!/usr/bin/env python3
"""Puts a song's name right: its title and artist, as every deck shows them.

    python3 naming.py fix DIR SRC <songs    the songs on stdin (one a line; none: every song whose name looks off):
                                            each is checked and, when it is sure, fixed
    python3 naming.py one DIR SRC REL       the same for one song; prints {"fixed": true} or {"ask": true}
    python3 naming.py set DIR SRC REL N     your pick: way N (1 = first) of a song it wasn't sure of
    python3 naming.py undo DIR SRC REL...   the names these songs had before
    python3 naming.py list DIR SRC          what looks off, as the page shows it (nothing is changed)

What looks off is read from the names alone (look(): no file is opened and nothing leaves the Mac):

    the title holds the artist too   "Mac Miller - Funny Papers (GRiZ Flip)" by "GRiZ" (the uploader's name)
    a version after a dash           "Shadows - Bloom Remix"  ->  "Shadows (Bloom Remix)"
    words that aren't the name       "[FREE DOWNLOAD]", "(Official Audio)"
    another song's name              a file from Soulseek that says it is another song than the one it was got as:
                                     maybe the wrong file. Never fixed by itself: you listen and say.

"Artist - Title" or "Title - Artist"? What the song sounds like (recognise.py) or a music catalogue (Apple Music,
MusicBrainz: only the artist and title are asked) says which. A name is written by itself only when one way is
confirmed and whoever was named as artist is still credited in it; anything less sure waits for your pick. The
file's name on disk never changes, and a mash-up of two songs keeps the name it has.

Record in DIR: names.json  {"fixed": what each fixed song held before (the undo), "was": the names a song has gone
by (a deck's row that still shows one of them follows the fix; a name you typed on a deck stays), "ask": the ways
of a song it wasn't sure of, "fine": the songs you said are fine as they are}. A fixed file keeps its time, tempo
and key. Runs with the private Python (Mutagen)."""
import json, os, re, sys, time, unicodedata
from difflib import SequenceMatcher

import details
from details import flat, same_artist, split_title

FILE, PROGRESS = "names.json", ".naming-progress"
STOP = {"the", "and", "for", "you", "feat", "with", "from"}
SEP = re.compile(r"\s+[-–—]\s+")
BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
MASH = re.compile(r"\s(?:/|//|\||:)\s")  # two songs in one name: left as it is
JUNK = re.compile(r"\s*[\(\[\{]\s*(?:free\s*(?:download|dl)|out\s+now|official\s+(?:audio|video|music\s+video|"
                  r"visuali[sz]er|lyric\s+video)|premiere|lyrics?|lyric\s+video|hq|hd|buy\s*=\s*free[^\)\]\}]*|"
                  r"click\s+buy[^\)\]\}]*)\s*!*\s*[\)\]\}]", re.I)
TAIL = re.compile(r"\s*[-–—|*~]*\s*\b(?:free\s*(?:download|dl)|out\s+now)\s*!*\s*$", re.I)
HEAD = re.compile(r"^\s*(?:premiere|exclusive|free\s*(?:download|dl))\s*[:|]\s*", re.I)
VERSION = re.compile(r"\b(?:re-?mix|rmx|edit|flip|bootleg|vip|rework|refix|version|mix|dub|remaster(?:ed)?|"
                     r"instrumental|acoustic|a\s?cappella|reverb)\s*(?:\d{4})?\s*$|"
                     r"^(?:(?:super|ultra|extra)\s+)?(?:slowed|sped\s+up|nightcore)\b|"
                     r"^live(?:\s+(?:at|in|from|version|session|edit|mix)\b|\s*$)", re.I)
# the words of a version that name no one: "Radio Edit", "Extended Mix", "Slowed + Reverb"
GENERIC = set("radio extended original club short long full album single super ultra extra clean dirty explicit intro "
              "outro vocal version edit mix remix rmx remaster remastered slowed reverb sped up live acoustic "
              "instrumental nightcore flip bootleg vip rework refix dub and x s".split())
CREDIT = re.compile(r"^\W*(?:feat|ft|featuring|with|prod)\b", re.I)


# ---------- what looks off (the names alone) ----------

def clean(t):
    """The title without the words that aren't its name."""
    out, last = HEAD.sub("", t or ""), None
    while last != out:
        last, out = out, TAIL.sub("", JUNK.sub("", out))
    return re.sub(r"\s{2,}", " ", out).strip() or (t or "").strip()


def parts(t):
    """The title cut at its dashes; a dash inside brackets is left alone."""
    mask = BRACKETS.sub(lambda m: "\0" * len(m.group()), t)
    out, at = [], 0
    for m in SEP.finditer(mask):
        out.append(t[at:m.start()])
        at = m.end()
    out = [p.strip() for p in out + [t[at:]]]
    return out if all(out) else [t.strip()]


def repeats(part, artist):
    """This piece of the title is only the artist over again."""
    a, b = details.names(part), details.names(artist)
    return bool(a) and bool(b) and (a <= b or flat(part) == flat(artist))


def bare(t):
    return re.sub(r"\s{2,}", " ", BRACKETS.sub(" ", t)).strip()


def ways(artist, title):
    """The ways this name can be read: ([{"artist", "title"}, ...] the likeliest first, sure). sure: the first way
    is right whatever a catalogue says (only a repeat, a version's dash or junk words changed)."""
    t = clean(title)
    if MASH.search(bare(t)):
        return [{"artist": artist, "title": t}], True
    p = parts(t)
    while len(p) > 1 and artist and repeats(p[0], artist):  # "Artist - Song" by Artist
        p = p[1:]
    if len(p) > 2 and VERSION.search(p[-1]):  # "Artist - Song - Someone Remix"
        p = p[:-2] + [f"{p[-2]} ({p[-1]})"]
    if len(p) == 1:
        return [{"artist": artist, "title": p[0]}], True
    if len(p) > 2:  # too many pieces to tell: only the junk words go
        return [{"artist": artist, "title": t}], True
    x, y = p
    out = []
    if VERSION.search(y):
        dash = {"artist": artist, "title": f"{x} ({y})"}  # "Song - Someone Remix" by its artist
        # the dash names no one ("Radio Edit"), or only the artist ("<artist> Remix"): the song is x either way
        who = {w for w in flat(y).split() if w not in GENERIC and not w.isdigit()}
        if not who or (artist and who <= set(flat(artist).split())):
            return [dash], True
        out.append(dash)
    # "Song (Someone Flip) - Artist": brackets that hold a version or a guest sit on a song, never on an artist
    song_x = any(VERSION.search(b[1:-1]) or CREDIT.match(b[1:-1]) for b in BRACKETS.findall(x))
    if not VERSION.fullmatch(y) and bare(y) and not song_x:
        out.append({"artist": x, "title": y})  # "Artist - Song (Someone Flip)"
    if bare(y) and not VERSION.search(bare(y)) and bare(x):
        tail = " ".join(BRACKETS.findall(y))
        out.append({"artist": bare(y), "title": (x + " " + tail).strip()})  # "Song - Artist (Someone Flip)"
    return out or [{"artist": artist, "title": t}], song_x and len(out) == 1


def related(a, b):
    """Two titles name the same song, give or take its version."""
    def cores(t):
        return {flat(bare(p)) for p in parts(clean(t)) if not VERSION.search(p) and flat(bare(p))} or {flat(bare(t))}
    for x in cores(a):
        for y in cores(b):
            if x and y and (x == y or (min(len(x), len(y)) >= 4 and (x in y or y in x))
                            or SequenceMatcher(None, x, y).ratio() >= 0.75):
                return True
            wx, wy = ({w for w in t.split() if len(w) >= 3 and w not in STOP} for t in (x, y))
            if wx and wy and len(wx & wy) >= max(1, 0.6 * min(len(wx), len(wy))):  # most of the shorter one's words
                return True
    return False


def follows(song, title, artist):
    """What a deck's row should say now: {"title": ..., "artist": ...}, each only when the row still shows a name
    the song went by before (song["named"]: was()). A name you typed on a deck is none of those, so it stays."""
    nfc, went, out = lambda s: unicodedata.normalize("NFC", str(s or "")).strip(), song.get("named") or {}, {}
    for field, shown in (("title", title), ("artist", artist)):
        want = nfc(song.get(field))
        if want and nfc(shown) != want and nfc(shown) in {nfc(x) for x in went.get(field) or []}:
            out[field] = want
    return out


def split_name(rel):
    a, sep, t = os.path.splitext(os.path.basename(rel))[0].partition(" - ")
    return (a.strip(), t.strip()) if sep else ("", "")


def sig(artist, title):
    return f"{artist}\t{title}"


def look(song, got=False, rec=None):
    """What looks off about one song (dj.library's): None, or
    {"kind": "fix" | "ask" | "wrong", "ways": [...], "sure": bool, "want": "the name it was got as"}."""
    rec = rec or {}
    rel, artist, title = song["rel"], song.get("artist") or "", song.get("title") or ""
    here = sig(artist, title)
    if (rec.get("fine") or {}).get(rel) == here:
        return None
    fa, ft = split_name(rel)
    if song.get("tagged") and fa and ft and artist and not related(title, ft):
        want = ways(fa, ft)[0][0]  # the name of the file itself, tidied: the song it was got as
        # the file's details and its name say the two the other way round: one of them has them swapped, and
        # only a catalogue can say which (one()), so nothing is written on a guess
        if related(artist, ft) and related(title, fa):
            asked = (rec.get("ask") or {}).get(rel)
            return {"kind": "ask" if asked and asked.get("sig") == here else "fix", "ways": [want], "sure": False,
                    "swap": True}
        # a file's name can be "Song - Artist" too: another song only when its title is in neither half
        if got and not related(title, fa) and not related(artist, ft):
            return {"kind": "wrong", "ways": [want], "sure": False, "want": f"{want['artist']} · {want['title']}"}
    asked = (rec.get("ask") or {}).get(rel)
    if asked and asked.get("sig") == here and asked.get("ways"):
        return {"kind": "ask", "ways": asked["ways"], "sure": False}
    found, sure = ways(artist, title)
    found = [w for w in found if (w["artist"], w["title"]) != (artist, title)]
    if not found or (sure and (found[0]["artist"], found[0]["title"]) == (artist, title)):
        return None
    return {"kind": "fix", "ways": found, "sure": sure}


def got(d, src):
    """The songs Soulseek found (soulseek.tsv): a file from there can be the wrong one."""
    out = set()
    try:
        with open(os.path.join(d, "soulseek.tsv"), encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    out.add(os.path.relpath(os.path.realpath(p[2]), os.path.realpath(src)))
    except OSError:
        pass
    return out


def status(d, src, songs):
    """{rel: what the page shows for it}: {"kind", "to", "ways", "want"} for a name that looks off, {"from": the
    name it had} for one The Crate fixed (the undo)."""
    rec, mine, out = load(d), got(d, src), {}
    for s in songs:
        rel = s["rel"]
        fixed = rec["fixed"].get(rel)
        if fixed:
            out[rel] = {"from": fixed.get("shown") or ""}
            continue
        l = look(s, rel in mine, rec)
        if l:
            out[rel] = {"kind": l["kind"], "sure": l["sure"], "ways": l["ways"][:3],
                        **({"want": l["want"]} if l.get("want") else {}), **({"swap": True} if l.get("swap") else {})}
    return out


# ---------- which way is right ----------

def _matches(way, artist, title):
    return same_artist(way["artist"], artist) and related(way["title"], title)


def confirm(found, heard=(), ask=True):
    """The one way a second source agrees with (its place in the list), else None. heard: the names the song was
    recognised as by its sound; then the catalogues, when ask."""
    hits = [i for i, w in enumerate(found) if any(_matches(w, a, t) for a, t in heard)]
    if len(hits) == 1:
        return hits[0]
    if hits or not ask:
        return None
    asked, cands = set(), []
    for w in found:  # Apple Music searches by words: one ask serves every way made of the same words
        key = frozenset(flat(bare(w["artist"]) + " " + bare(w["title"])).split())
        if key not in asked:
            asked.add(key)
            try:
                cands += details.itunes(bare(w["artist"]), bare(w["title"]))
            except Exception:
                pass
    hits = [i for i, w in enumerate(found) if any(_matches(w, c.get("artist") or "", c.get("title") or "") for c in cands)]
    if not hits:  # MusicBrainz asks for the artist and the title each by name: once a way
        for i, w in enumerate(found):
            try:
                cands = details.musicbrainz(bare(w["artist"]), bare(w["title"]))
            except Exception:
                cands = []
            if any(_matches(w, c.get("artist") or "", c.get("title") or "") for c in cands):
                hits.append(i)
    return hits[0] if len(hits) == 1 else None


# ---------- the record, and writing a name ----------

def load(d):
    rec = details._load(d, FILE, {})
    return {k: rec[k] if isinstance(rec.get(k), dict) else {} for k in ("fixed", "was", "ask", "fine")}


def save(d, rec):
    details._save(d, FILE, rec)


def was(d):
    """{rel: {"title": [...], "artist": [...]}}: the names each song has gone by. A deck's row that still shows one
    of them takes the song's name of today."""
    return load(d)["was"]


def _set(path, fields):
    """Writes these title and artist tags over what is there ("" takes the tag out). Returns what each held."""
    from mutagen import id3
    f = details._open(path)
    k, now = details._kind(f), details._now(f)
    had = f.tags is not None
    if f.tags is None:
        f.add_tags()
    t, before = f.tags, {}
    for field, val in fields.items():
        if (now.get(field) or "") == val:
            continue
        before[field] = now.get(field) or ""
        key = details.ID3[field] if k == "id3" else details.VORBIS[field] if k == "flac" else details.MP4[field]
        if not val:
            if k == "id3":
                t.delall(key)
            elif key in t:
                del t[key]  # not pop(): a FLAC's tags are a list underneath
        elif k == "id3":
            t.setall(key, [getattr(id3, key)(encoding=3, text=[val])])
        else:
            t[key] = [val]
    if before:
        if k == "id3":
            f.save(v2_version=4 if getattr(t, "version", (2, 3))[1] == 4 and had else 3)
        else:
            f.save()
    return before


def _went(rec, rel, **names):
    w = rec["was"].setdefault(rel, {"title": [], "artist": []})
    for field, vals in names.items():
        for v in vals:
            if v and v not in w[field]:
                w[field].append(v)


def apply(d, src, song, way, how=""):
    """Writes this name into the song's file. The name it had is kept for the undo."""
    rel, path = song["rel"], os.path.join(src, song["rel"])
    with details._same_time(path):
        before = _set(path, {"title": way["title"], "artist": way["artist"]})
    rec = load(d)
    rec["ask"].pop(rel, None)
    if not before:  # the file already said so (only the list was behind)
        save(d, rec)
        return False
    old = rec["fixed"].get(rel) or {}
    shown = f"{song.get('artist') or 'Unknown artist'} · {song.get('title') or ''}"
    rec["fixed"][rel] = {"title": [(old.get("title") or [before.get("title")])[0], way["title"]] if "title" in before or "title" in old else None,
                         "artist": [(old.get("artist") or [before.get("artist")])[0], way["artist"]] if "artist" in before or "artist" in old else None,
                         "shown": old.get("shown") or shown, "at": int(time.time())}
    _went(rec, rel, title=[song.get("title"), before.get("title")], artist=[song.get("artist"), before.get("artist")])
    save(d, rec)
    details._after(d, src, rel)
    details.tell(d, f'names: "{shown}" is now "{way["artist"]} · {way["title"]}"{how}')
    return True


def undo(d, src, rel):
    """The name the song had before The Crate fixed it. A name changed since (by you, in another app) stays."""
    rec = load(d)
    fixed = rec["fixed"].pop(rel, None)
    if not fixed:
        return 0
    path = os.path.join(src, rel)
    now = details._now(details._open(path))
    back = {f: fixed[f][0] for f in ("title", "artist") if fixed.get(f) and (now.get(f) or "") == fixed[f][1]}
    with details._same_time(path):
        n = len(_set(path, back))
    _went(rec, rel, **{f: [fixed[f][1]] for f in back})
    save(d, rec)
    if n:
        details._after(d, src, rel)
        details.tell(d, f"names: {os.path.basename(rel)} has the name it had before again")
    return n


def fine(d, rel, artist, title):
    """You said this name is fine as it is: not asked about again (until the name changes)."""
    rec = load(d)
    rec["fine"][rel] = sig(artist, title)
    rec["ask"].pop(rel, None)
    save(d, rec)


def moved(d, old, new=None):
    """The song goes by another file name now (its FLAC became an AIFF, or came back; it moved into another folder):
    its record follows, so the name stays fixed and can still be put back. old: one name, or {new: old} for several."""
    rec, hit = load(d), False
    for new, old in (old if isinstance(old, dict) else {new: old}).items():
        for k in rec:
            if old in rec[k]:
                rec[k][new], hit = rec[k].pop(old), True
    if hit:
        save(d, rec)


# ---------- the jobs ----------

def _songs(d, src):
    import dj
    return {s["rel"]: s for s in dj.library(d, src)}


def _heard(song):
    a, sep, t = (song.get("sounds_like") or "").partition(" - ")
    return [(a, t)] if sep else []


def one(d, src, song, mine, ask=True):
    """Checks one song and fixes it when sure. "fixed", "ask" (it waits for your pick), or "" (nothing to do)."""
    rec = load(d)
    l = look(song, song["rel"] in mine, rec)
    if not l or l["kind"] == "wrong":
        return ""
    found = l["ways"]
    if l["sure"]:
        return "fixed" if apply(d, src, song, found[0]) else ""
    if l.get("swap") and l["kind"] == "fix":  # swapped in the file's details, or only in its file name?
        now = {"artist": song.get("artist") or "", "title": song.get("title") or ""}
        hit = confirm([found[0], now], _heard(song), ask)
        if hit == 0:
            return "fixed" if apply(d, src, song, found[0]) else ""
        rec = load(d)
        if hit == 1:  # the details are right as they are: not looked at again
            rec["fine"][song["rel"]] = sig(now["artist"], now["title"])
        else:
            rec["ask"][song["rel"]] = {"sig": sig(now["artist"], now["title"]), "ways": found[:1], "at": int(time.time())}
        save(d, rec)
        return "" if hit == 1 else "ask"
    hit = confirm(found, _heard(song), ask) if l["kind"] == "fix" else None
    old = song.get("artist") or ""
    if hit is not None and (not old or same_artist(old, found[hit]["artist"], found[hit]["title"])):
        return "fixed" if apply(d, src, song, found[hit]) else ""
    if hit is not None:  # confirmed, but the name it replaces isn't credited in it: yours to say, that way first
        found = [found[hit]] + [w for i, w in enumerate(found) if i != hit]
    rec = load(d)
    rec["ask"][song["rel"]] = {"sig": sig(song.get("artist") or "", song.get("title") or ""), "ways": found[:3],
                               "at": int(time.time())}
    save(d, rec)
    return "ask"


def note(d, done, total):
    with open(os.path.join(d, PROGRESS + ".tmp"), "w") as f:
        f.write(f"{done}\t{total}\t{os.getpid()}")
    os.replace(os.path.join(d, PROGRESS + ".tmp"), os.path.join(d, PROGRESS))


def fix(d, src, rels):
    """Every named song (none named: every song whose name looks off) is checked and, when sure, fixed."""
    songs, mine, rec = _songs(d, src), got(d, src), load(d)
    todo = [r for r in (rels or sorted(songs)) if r in songs and (look(songs[r], r in mine, rec) or {}).get("kind") == "fix"]
    done = {"fixed": 0, "ask": 0}
    try:
        for i, rel in enumerate(todo):
            note(d, i, len(todo))
            try:
                r = one(d, src, songs[rel], mine)
            except Exception as e:
                details.tell(d, f"NAMES PROBLEM: {os.path.basename(rel)}: {str(e)[:120]}")
                continue
            if r:
                done[r] += 1
    finally:
        try:
            os.remove(os.path.join(d, PROGRESS))
        except OSError:
            pass
    s = lambda n: "" if n == 1 else "s"
    said = [f"{done['fixed']} name{s(done['fixed'])} fixed"] if done["fixed"] or not done["ask"] else []
    if done["ask"]:
        said.append(f"{done['ask']} need{'s' if done['ask'] == 1 else ''} your pick (under Names to fix)")
    details.tell(d, "names: " + ", ".join(said) + ".")
    return done


def pick(d, src, rel, n):
    songs, rec = _songs(d, src), load(d)
    l = look(songs[rel], rel in got(d, src), rec) if rel in songs else None
    if not l or not 1 <= n <= len(l["ways"]):
        raise SystemExit(f"no way {n} for {rel}")
    return apply(d, src, songs[rel], l["ways"][n - 1], " (your pick)")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "fix":
        import aiff
        rels = [l.strip("\n") for l in sys.stdin if l.strip()] if not sys.stdin.isatty() else []
        if fix(a[1], a[2], rels)["fixed"]:
            details._safe(a[1], a[2])
            aiff.decks(a[1], a[2])
    elif len(a) == 4 and a[0] == "one":
        songs = _songs(a[1], a[2])
        r = one(a[1], a[2], songs[a[3]], got(a[1], a[2])) if a[3] in songs else ""
        details._safe(a[1], a[2]) if r == "fixed" else None
        print(json.dumps({r: True} if r else {}))
    elif len(a) == 5 and a[0] == "set":
        details._safe(a[1], a[2]) if pick(a[1], a[2], a[3], int(a[4])) else None
    elif len(a) >= 4 and a[0] == "undo":
        n = sum(undo(a[1], a[2], rel) for rel in a[3:])
        details._safe(a[1], a[2]) if n else None
        print(n)
    elif len(a) == 3 and a[0] == "list":
        print(json.dumps(status(a[1], a[2], list(_songs(a[1], a[2]).values())), ensure_ascii=False, indent=1))
    else:
        raise SystemExit(__doc__)
