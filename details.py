"""Fills in a song's MISSING cover and details (title, artist, album, genre, year), accuracy first. What is already
in a file is never changed; only empty fields are filled.

    details.py auto DIR SRC              songs that arrived since the first look are filled in by themselves (usb.sh
                                         and dj.py run this); the ones already here are yours to pick on the page
    details.py fill DIR SRC              songs to look at on stdin, one per line (none: every safety-checked song);
                                         then the decks' lists and the USB follow
    details.py scan DIR SRC              notes what each song lacks (details-have.json: the page reads only that)
    details.py pick DIR SRC REL N        writes candidate N (1, 2 or 3) of a song that needs a look
    details.py undo DIR SRC REL          puts back exactly what the song held before
    details.py status DIR [SRC]          JSON for the page (with SRC: what every song still lacks, too)

Where it looks, best first:
  1. the song's own SoundCloud page: the sync's listing (.listing) paired to the file as dj.py does, else a
     SoundCloud link written inside the file (its public page, read once);
  2. its sound (recognise.py), only when an AcoustID key is already saved; without one this step is skipped;
  3. two free catalogues, by artist and title only: Apple's iTunes Search and MusicBrainz (+ Cover Art Archive).
Before anything is written by itself: the length is within 3 s of the file's, artist and title match (a remix only
matches the same remix), and either it is the song's own SoundCloud page or two sources agree. Albums come from a
single or EP before a compilation. Anything less sure is written nowhere and kept as "needs a look" with the top
candidates. Covers are embedded at 500 px or more.

Records in DIR: details-log.json (every change: rel, field, old, new, source, time), details-ask.json (needs a look,
and songs nothing was found for: asked again after 30 days), details-undo/ (what a file held before its first change),
details-have.json (what each song lacks), details.json (the automatic switch, and the songs here before it began),
details-changed.tsv (songs whose USB copy is now the older one: usb_tidy.py swaps it for the library's file).
A changed file keeps its time (it did not just arrive) and its tempo and key (the sound is the same).
Runs with the private Python (Mutagen). Only a song's artist and title leave the Mac (plus a fingerprint when the
sound step runs); nothing about the Mac or its owner."""
import contextlib, fcntl, hashlib, json, os, re, struct, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from difflib import SequenceMatcher

import links

FIELDS = ("cover", "title", "artist", "album", "genre", "year")
LOG, ASK, UNDO = "details-log.json", "details-ask.json", "details-undo"
HAVE, SET, PROGRESS, CHANGED = "details-have.json", "details.json", ".details-progress", "details-changed.tsv"
# the only places asked, whatever link a file or a catalogue names (the last three serve the covers)
HOSTS = ("itunes.apple.com", "musicbrainz.org", "coverartarchive.org", "soundcloud.com", "mzstatic.com", "sndcdn.com",
         "archive.org")
NEAR = 3.0  # seconds: further apart than this, it is another version of the song
AGAIN = 30 * 86400  # a song nothing was found for is looked up again after this
MIN_PX = 500
ITUNES = "https://itunes.apple.com/search"
MB = "https://musicbrainz.org/ws/2/recording/"
CAA = "https://coverartarchive.org/release/"
PAUSE = {"itunes": 3.1, "mb": 1.1, "sc": 2.0, "img": 0.0}  # iTunes allows about 20 a minute, MusicBrainz 1 a second
_last = {}
ID3 = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "genre": "TCON", "year": "TDRC"}
VORBIS = {"title": "title", "artist": "artist", "album": "album", "genre": "genre", "year": "date"}
MP4 = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "genre": "\xa9gen", "year": "\xa9day"}
VERSION = re.compile(r"\b(re-?mix|mix|edit|flip|bootleg|vip|rework|refix|cover|dub|version|extended|radio|club|slowed|"
                     r"sped|reprise|live|acoustic|instrumental|mash-?up|remake|redo|reboot|blend|rmx|part|pt|"
                     r"intro|outro|interlude)\b", re.I)
PLAIN = re.compile(r"^(original|original mix|main|main mix|album version|explicit|clean|extended mix)$", re.I)
JUNK_GENRE = {"", "none", "music", "other", "unknown", "soundcloud"}


# ---------- reading and writing the file's own tags ----------

def _open(path):
    import mutagen
    return mutagen.File(path)


def _kind(f):
    n = type(f).__name__
    return "flac" if n == "FLAC" else "mp4" if n == "MP4" else "id3"


def _now(f):
    """{field: value} of what the file holds now, and 'cover' when it has a picture."""
    out, t, k = {}, f.tags, _kind(f)
    if t is None and k != "flac":
        return out
    for field in FIELDS[1:]:
        try:
            if k == "id3":
                fr = t.get(ID3[field]) or (t.get("TYER") if field == "year" else None)
                v = str(fr.text[0]) if fr and fr.text else ""
            else:
                v = (t.get(VORBIS[field] if k == "flac" else MP4[field]) or [""]) if t is not None else [""]
                v = str(v[0]) if v else ""
        except (ValueError, KeyError, IndexError):
            v = ""
        if v.strip():
            out[field] = v.strip()[:4] if field == "year" else v.strip()
    if k == "flac":
        has = bool(f.pictures)
    elif k == "mp4":
        has = bool(t.get("covr"))
    else:
        has = any(str(x).startswith("APIC") for x in t.keys())
    if has:
        out["cover"] = "yes"
    return out


def missing(path):
    """What a file lacks among cover, title, artist, album, genre, year (FLAC, AIFF, WAV, MP3, M4A)."""
    try:
        f = _open(path)
    except Exception:
        return []
    if f is None:
        return []
    have = _now(f)
    return [x for x in FIELDS if x not in have]


def _length(path):
    try:
        return float(_open(path).info.length or 0)
    except Exception:
        return 0.0


def _tagdump(path):
    """Everything in a file's tags, pictures by their hash (the undo test compares these)."""
    f = _open(path)
    if f is None or f.tags is None:
        return {}
    out = {}
    for k, v in sorted(f.tags.items(), key=lambda kv: str(kv[0])):
        out[str(k)] = hashlib.sha1(v.data).hexdigest() if hasattr(v, "data") else repr(v)
    for i, p in enumerate(getattr(f, "pictures", []) or []):
        out[f"picture{i}"] = hashlib.sha1(p.data).hexdigest()
    return out


def _write(path, fields, cover=None):
    """Writes the given fields (only into empty ones) and the cover (bytes, mime). Returns what each was before."""
    from mutagen import id3, flac, mp4
    f = _open(path)
    k, have = _kind(f), _now(f)
    before = {"had_tags": f.tags is not None, "fields": {}}
    if f.tags is None:
        f.add_tags()
    t = f.tags
    for field, val in fields.items():
        if not val or field in have:
            continue
        before["fields"][field] = None
        if k == "id3":
            t.add(getattr(id3, ID3[field])(encoding=3, text=[val]))
        elif k == "flac":
            t[VORBIS[field]] = [val]
        else:
            t[MP4[field]] = [val]
    if cover and "cover" not in have:
        data, mime = cover
        before["fields"]["cover"] = None
        if k == "id3":
            t.add(id3.APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        elif k == "flac":
            p = flac.Picture()
            p.type, p.mime, p.data = 3, mime, data
            p.width, p.height = _size(data)
            f.add_picture(p)
        else:
            t["covr"] = [mp4.MP4Cover(data, mp4.MP4Cover.FORMAT_PNG if "png" in mime else mp4.MP4Cover.FORMAT_JPEG)]
    if before["fields"]:
        if k == "id3":
            f.save(v2_version=4 if getattr(t, "version", (2, 3))[1] == 4 and before["had_tags"] else 3)
        else:
            f.save()
    return before


def _unwrite(path, entries, had_tags):
    """Takes out what The Crate wrote (entries: log rows), where the file still holds exactly that."""
    f = _open(path)
    if f is None or f.tags is None:
        return 0
    k, t, n = _kind(f), f.tags, 0
    for e in entries:
        field = e["field"]
        if field == "cover":
            want = e.get("hash")
            if k == "id3":
                for key in [x for x in t.keys() if str(x).startswith("APIC")]:
                    if hashlib.sha1(t[key].data).hexdigest() == want:
                        del t[key]
                        n += 1
            elif k == "flac":
                keep = [p for p in f.pictures if hashlib.sha1(p.data).hexdigest() != want]
                if len(keep) != len(f.pictures):
                    f.clear_pictures()
                    for p in keep:
                        f.add_picture(p)
                    n += 1
            else:
                keep = [c for c in t.get("covr", []) if hashlib.sha1(bytes(c)).hexdigest() != want]
                if len(keep) != len(t.get("covr", [])):
                    if keep:
                        t["covr"] = keep
                    else:
                        del t["covr"]
                    n += 1
            continue
        if _now(f).get(field, "") != (e["new"][:4] if field == "year" else e["new"]):
            continue  # changed since (by him): left as it is
        if k == "id3":
            t.delall(ID3[field])
            if field == "year":
                t.delall("TYER")
        else:
            key = VORBIS[field] if k == "flac" else MP4[field]
            if key in t:
                del t[key]
        n += 1
    if not n:
        return 0
    empty = not len(t.keys()) and not getattr(f, "pictures", None)
    if empty and not had_tags and k != "flac":
        f.delete()  # it had no tag block at all before: none again
    elif k == "id3":
        f.save(v2_version=t.version[1] if t.version[1] in (3, 4) else 3)
    else:
        f.save()
    return n


# ---------- comparing names ----------

def flat(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s.replace("&", " and ").replace("$", "s")).strip()


def split_title(t):
    """(the song's own name, the version words): 'Work (Crankdat Remix)' -> ('work', {'crankdat', 'remix'})."""
    t = str(t or "")
    groups = re.findall(r"[\(\[]([^\)\]]*)[\)\]]", t)
    base = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", t)
    m = re.search(r"\s[-–]\s([^-–]*\b(?:re-?mix|edit|flip|bootleg|vip|rework|version|mix)\b[^-–]*)$", base, re.I)
    if m:  # 'Song - Someone Remix'
        groups.append(m.group(1))
        base = base[:m.start()]
    base = re.split(r"\s(?:feat\.?|ft\.?|featuring)\s", base, flags=re.I)[0]
    version = set()
    for g in groups:
        g = g.strip()
        if re.match(r"(feat\.?|ft\.?|featuring|with)\s", g, re.I) or PLAIN.match(g) or not VERSION.search(g):
            continue
        version |= set(flat(g).split()) - {"x", "and", "vs", "the", "s", "rmx"}
    if "rmx" in flat(" ".join(groups)).split():
        version.add("remix")
    version = {"remix" if w == "re" else w for w in version}
    return flat(base), version


def same_title(a, b):
    """Both names are the same song in the same version (a remix is never its original)."""
    (ba, va), (bb, vb) = split_title(a), split_title(b)
    if va != vb and not (va and vb and len(va ^ vb) <= 1 and len(va & vb) >= 2):
        return False
    if not ba or not bb:
        return False
    return ba == bb or SequenceMatcher(None, ba, bb).ratio() >= 0.9


def names(s):
    """The people in an artist field: 'A x B feat. C' -> {'a', 'b', 'c'}."""
    parts = re.split(r"\s*(?:,|，|／|/|;|&|\+|\bx\b|\bvs\.?|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\band\b)\s*",
                     unicodedata.normalize("NFKC", str(s or "")), flags=re.I)
    return {flat(p) for p in parts if flat(p)}


def same_artist(want, cand_artist, cand_title=""):
    """One of the people asked for is credited (as artist, or as the remixer or guest in the title)."""
    have = names(cand_artist) | names(" ".join(re.findall(r"[\(\[]([^\)\]]*)[\)\]]", cand_title or "")))
    have_flat = flat(cand_artist + " " + (cand_title or ""))
    for w in names(want):
        if len(w) < 2:
            continue
        if w in have or any(SequenceMatcher(None, w, h).ratio() >= 0.88 for h in have):
            return True
        if len(w) >= 4 and re.search(r"\b" + re.escape(w) + r"\b", have_flat):
            return True
    return False


def guesses(artist, title):
    """Ways to read 'artist - title' when the title itself holds a ' - ' (a label's upload, a flip of a song)."""
    out = [(artist, title)]
    m = re.match(r"(.+?)\s[-–:]\s(.+)", title or "")
    if m:
        out += [(m.group(1), m.group(2)), (m.group(2), m.group(1))]
    return [(a.strip(), t.strip()) for a, t in out if a and t]


# ---------- asking the sources ----------

def _get(who, url, raw=False):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if not url.startswith("https://") or not any(host == h or host.endswith("." + h) for h in HOSTS):
        raise ValueError("not one of the sources")
    wait = _last.get(who, 0) + PAUSE[who] - time.time()
    if wait > 0:
        time.sleep(wait)
    accept = "*/*" if raw else "application/json"
    req = urllib.request.Request(url, headers={"User-Agent": links.UA, "Accept": accept})
    try:
        for n in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read(15_000_000)
                return data if raw else json.loads(data.decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code in (403, 429, 503) and n < 2:
                    time.sleep(10 * (n + 1))
                    continue
                raise
    finally:
        _last[who] = time.time()


def _year(s):
    m = re.match(r"(\d{4})", str(s or ""))
    return m.group(1) if m else ""


def itunes(artist, title):
    """Songs on Apple Music by artist and title."""
    q = urllib.parse.urlencode({"term": f"{artist} {split_title(title)[0]} {' '.join(sorted(split_title(title)[1]))}",
                                "entity": "song", "limit": 25, "media": "music"})
    out = []
    for r in (_get("itunes", ITUNES + "?" + q).get("results") or []):
        if r.get("kind") != "song":
            continue
        album = re.sub(r"\s-\s(Single|EP)$", "", r.get("collectionName") or "")
        out.append({"title": r.get("trackName") or "", "artist": r.get("artistName") or "", "album": album,
                    "year": _year(r.get("releaseDate")), "genre": r.get("primaryGenreName") or "",
                    "length": (r.get("trackTimeMillis") or 0) / 1000,
                    "cover": (r.get("artworkUrl100") or "").replace("100x100bb", "1000x1000bb"),
                    "single": (r.get("trackCount") or 99) <= 6 or bool(re.search(r"\s-\s(Single|EP)$",
                                                                                r.get("collectionName") or "")),
                    "compilation": (r.get("collectionArtistName") or "").lower() == "various artists",
                    "source": "Apple Music", "url": r.get("trackViewUrl") or ""})
    return out


def musicbrainz(artist, title):
    """Recordings on MusicBrainz, each with its best release (a single or EP before an album, never a compilation
    when there is another)."""
    def q(s):
        return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", s)
    base, version = split_title(title)
    query = f"recording:({q(base + ' ' + ' '.join(sorted(version)))}) AND artist:({q(artist)})"
    got = _get("mb", MB + "?" + urllib.parse.urlencode({"query": query, "limit": 10, "fmt": "json"}))
    out = []
    for r in got.get("recordings") or []:
        if (r.get("score") or 0) < 60:
            continue
        credit = "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in r.get("artist-credit") or [])
        rels = []
        for rel in r.get("releases") or []:
            g = rel.get("release-group") or {}
            comp = "Compilation" in (g.get("secondary-types") or []) or \
                   any((c.get("name") or "").lower() == "various artists" for c in rel.get("artist-credit") or [])
            kind = g.get("primary-type") or ""
            rank = (comp, {"Single": 0, "EP": 1, "Album": 2}.get(kind, 3), rel.get("date") or "9999")
            rels.append((rank, rel, comp, kind))
        rels.sort(key=lambda x: x[0])
        best = rels[0] if rels else None
        out.append({"title": r.get("title") or "", "artist": credit, "album": best[1].get("title", "") if best else "",
                    "year": _year(r.get("first-release-date") or (best[1].get("date") if best else "")), "genre": "",
                    "length": (r.get("length") or 0) / 1000,
                    "cover": CAA + best[1]["id"] + "/front-500" if best else "",
                    "single": bool(best and best[3] in ("Single", "EP")), "compilation": bool(best and best[2]),
                    "source": "MusicBrainz", "url": "https://musicbrainz.org/recording/" + (r.get("id") or "")})
    return out


def _sc_artist(title, pub, uploader):
    """Who a SoundCloud track is by: the artist the uploader filled in, else 'Artist - Title', else the uploader."""
    pub = re.sub(r"\s*，\s*", ", ", pub or "").strip()
    m = re.match(r"(.+?)\s[-–]\s(.+)", title or "")
    if m and names(m.group(1)) <= (names(pub) | names(uploader)):  # 'Levity - Salamander' by Levity
        return (pub or m.group(1)).strip(), m.group(2).strip()
    by = names(pub) or names(uploader)
    if m and by and all(flat(n) in flat(m.group(2)) for n in by):  # 'Lil Wayne - Lollipop (Tape B Flip)' by Tape B
        return m.group(1).strip(), m.group(2).strip()
    if pub and (not m or flat(pub) in flat(title)):
        return pub, title
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return (pub or uploader or "").strip(), title


def soundcloud_row(r):
    """A candidate from the sync's own listing of the song's SoundCloud page."""
    artist, title = _sc_artist(r.get("title"), r.get("artist"), r.get("uploader"))
    thumbs = {t.get("id"): t.get("url") for t in r.get("thumbnails") or []}
    art = thumbs.get("t500x500") or r.get("thumbnail") or ""  # an avatar is not cover art: only 'artworks-'
    genre = (r.get("genre") or "").strip()
    return {"title": title, "artist": artist, "album": "", "genre": "" if genre.lower() in JUNK_GENRE else genre,
            "year": str(r.get("release_year") or "") or _year(r.get("upload_date")), "length": r.get("duration") or 0,
            "cover": art if "/artworks-" in art else "", "single": False, "compilation": False,
            "source": "SoundCloud", "url": r.get("webpage_url") or "", "exact": True}


def soundcloud_page(url):
    """The same from the track's public SoundCloud page (for a file that names its own link)."""
    page = _get("sc", url, raw=True).decode("utf-8", "replace")
    m = re.search(r"window\.__sc_hydration\s*=\s*(\[.*?\]);\s*</script>", page, re.S)
    for h in json.loads(m.group(1)) if m else []:
        if h.get("hydratable") == "sound":
            d = h.get("data") or {}
            art = (d.get("artwork_url") or "").replace("-large.", "-t500x500.")  # never the uploader's avatar
            return soundcloud_row({"title": d.get("title"), "artist": (d.get("publisher_metadata") or {}).get("artist"),
                                   "uploader": (d.get("user") or {}).get("username"), "genre": d.get("genre"),
                                   "release_year": _year(d.get("release_date")),
                                   "upload_date": _year(d.get("created_at")),
                                   "duration": (d.get("duration") or 0) / 1000, "webpage_url": d.get("permalink_url"),
                                   "thumbnails": [{"id": "t500x500", "url": art}]})
    return None


def _image(url):
    """(bytes, mime) of a cover at least 500 px on its short side, else None."""
    if not url:
        return None
    try:
        data = _get("img", url, raw=True)
    except (OSError, ValueError):
        return None
    w, h = _size(data)
    if min(w, h) < MIN_PX:
        return None
    return data, "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"


def _size(data):
    """(width, height) of a JPEG or PNG."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    i = 2
    while data[:2] == b"\xff\xd8" and i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        mark, n = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if mark in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + n
    return 0, 0


# ---------- deciding ----------

def _fits(c, wants, secs):
    """How well a candidate fits: (passes every check, score). wants: [(artist, title)] readings of the file."""
    near = bool(secs and c.get("length") and abs(c["length"] - secs) <= NEAR)
    title = any(same_title(t, c["title"]) or same_title(t, a + " - " + c["title"]) for a, t in wants)
    artist = any(same_artist(a, c["artist"], c["title"]) for a, t in wants)
    sim = max(SequenceMatcher(None, flat(a + " " + t), flat(c["artist"] + " " + c["title"])).ratio() for a, t in wants)
    return near and title and artist, (near + title + artist) * 10 + sim


def _same_song(a, b):
    ta, tb = a["title"], b["title"]
    if not same_title(ta, tb):
        ta, tb = ta.split(" - ", 1)[-1], tb.split(" - ", 1)[-1]  # 'Flume - Holdin On (X Flip)' / 'Holdin On (X Flip)'
    return same_title(ta, tb) and (same_artist(a["artist"], b["artist"], b["title"])
                                                   or same_artist(b["artist"], a["artist"], a["title"]))


def _genre(raw, table):
    """The genre on his list (genres.py) a label means: 'hoodtrap' -> 'Trap'; a broad one ('Dance') -> ''."""
    import genres
    found = [genres.match(p, table) for p in re.split(r"[;/,|]", raw or "")]
    return next((g for g in found if g), "")


def decide(cands, wants, secs, table=None):
    """(what to write by itself {field: (value, source)}, the cover candidates, candidates for 'needs a look')."""
    if table is None:
        import genres
        table = genres.lookup(genres.DEFAULT)
    scored = []
    for c in cands:
        ok, s = _fits(c, wants, secs)
        scored.append((ok, s, c))
    good = [c for ok, s, c in scored if ok]
    exact = [c for c in good if c.get("exact")]
    sure = []
    if exact:
        sure = [exact[0]] + [c for c in good if not c.get("exact") and _same_song(c, exact[0])]
    else:
        for c in good:
            others = [d for d in good if d["source"] != c["source"] and _same_song(c, d)]
            clash = [d for d in good if not _same_song(c, d)]
            if others and not clash:
                sure = [c] + others
                break
    # an exact source that disagrees with an agreeing pair of catalogues: nothing is sure
    if exact and any(d["source"] != "SoundCloud" for d in good) and \
            not any(_same_song(d, exact[0]) for d in good if not d.get("exact")) and \
            len({d["source"] for d in good if not d.get("exact")}) >= 2:
        sure = []
    write, covers = {}, []
    if sure:  # the release's own spelling when a catalogue confirms the song, else the best source's
        main = next((c for c in sure if not c.get("exact") and c["source"] != "AcoustID" and not c["compilation"]),
                    sure[0])
        write["title"] = (main["title"], main["source"])
        write["artist"] = (main["artist"], main["source"])
        rel = sorted([c for c in sure if c.get("album")], key=lambda c: (c["compilation"], not c["single"],
                                                                         c.get("year") or "9999"))
        rel = [c for c in rel if not c["compilation"]] or []
        if rel:
            write["album"] = (rel[0]["album"], rel[0]["source"])
        years = [c for c in sure if c.get("year") and not c.get("exact") and not c["compilation"]]
        y = min(years, key=lambda c: c["year"]) if years else (main if main.get("year") else None)
        if y:
            write["year"] = (y["year"], y["source"])
        votes = {}  # genre is taste: only when two sources map to the same genre on his list (genres.py)
        for c in sure:
            mine = _genre(c.get("genre"), table)
            if mine:
                votes.setdefault(mine, {}).setdefault(c["source"].split(" (")[0], c["source"])
        g = next(((k, list(v.values())[0]) for k, v in votes.items() if len(v) >= 2), None)
        if g:
            write["genre"] = g
        covers = [c for c in sure if c.get("cover") and not c["compilation"]]
    ask = []
    seen = []
    for ok, s, c in sorted(scored, key=lambda x: -x[1]):
        if not any(same_title(t, c["title"]) or same_title(t, a + " - " + c["title"]) for a, t in wants) or \
                any(_same_song(c, d) and c.get("album") == d.get("album") for d in seen):
            continue
        seen.append(c)
        ask.append({k: c.get(k, "") for k in ("title", "artist", "album", "year", "length", "source", "cover", "url")}
                   | {"genre": _genre(c.get("genre"), table), "checks": "pass" if ok else "unsure"})
        if len(ask) == 3:
            break
    return write, covers, ask


# ---------- records ----------

def _load(d, name, empty):
    try:
        with open(os.path.join(d, name)) as f:
            v = json.load(f)
        return v if isinstance(v, type(empty)) else empty
    except (OSError, ValueError):
        return empty


def _save(d, name, v):
    p = os.path.join(d, name)
    with open(p + ".tmp", "w") as f:
        json.dump(v, f, ensure_ascii=False, indent=0)
    os.replace(p + ".tmp", p)


def _undo_dir(d, rel):
    p = os.path.join(d, UNDO, hashlib.sha1(rel.encode()).hexdigest()[:16])
    os.makedirs(p, exist_ok=True)
    return p


@contextlib.contextmanager
def _same_time(path):
    """A file whose details change did not just arrive: its time stays where it was (the newest-songs list goes by
    it), one second on, so the safety check reads the changed file again."""
    st = os.stat(path)
    try:
        yield
    finally:
        try:
            if os.stat(path).st_mtime_ns != st.st_mtime_ns:
                os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
        except OSError:
            pass


def _safe(d, src):
    """The safety check, once, for the files whose details just changed (before a copy of them goes anywhere)."""
    import aiff
    aiff.safe(d, src)


def _after(d, src, rel):
    """A file's details changed: the notes kept about it follow. What it lacks now; its tags as the decks' lists read
    them (tempo and key stay: the sound is the same); and that the USB's copy is now the older one."""
    path = os.path.join(src, rel)
    st = os.stat(path)
    notes = _load(d, HAVE, {})
    notes[rel] = [st.st_size, int(st.st_mtime), missing(path)]
    _save(d, HAVE, notes)
    try:
        import dj_analyze
        cache = _load(d, "dj-analysis.json", {})
        if rel in cache:
            now = dj_analyze.tags(path)  # a tag taken out (an undo) leaves the notes too, not only a new one joins
            kept = {k: v for k, v in cache[rel].items() if k in now or k not in
                    ("title", "artist", "album", "genre", "year", "label", "remixer", "comment")}
            cache[rel] = {**kept, **now, "size": st.st_size, "mtime": int(st.st_mtime)}
            with open(os.path.join(d, "dj-analysis.json.tmp"), "w") as f:
                json.dump(cache, f, ensure_ascii=False, indent=0, sort_keys=True)
            os.replace(os.path.join(d, "dj-analysis.json.tmp"), os.path.join(d, "dj-analysis.json"))
    except Exception:
        pass  # then the analyser reads the file again: slower, never wrong
    try:
        import soulseek
        seen = soulseek.load_checked(d)
        if isinstance(seen.get(path), list):
            seen[path] = [st.st_size, int(st.st_mtime), *seen[path][2:]]
            soulseek.dump(d, soulseek.CHECKED, seen)
    except Exception:
        pass
    with open(os.path.join(d, CHANGED), "a", encoding="utf-8") as f:
        f.write(f"{rel}\t{int(time.time())}\n")


def tell(d, text):
    if text:
        with open(os.path.join(d, "dj.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %R')}  {text}\n")


def note(d, done, total):
    """How far a run from the page is ("done<TAB>of<TAB>pid"): the page shows it."""
    with open(os.path.join(d, PROGRESS + ".tmp"), "w") as f:
        f.write(f"{done}\t{total}\t{os.getpid()}")
    os.replace(os.path.join(d, PROGRESS + ".tmp"), os.path.join(d, PROGRESS))


def _apply(d, src, rel, write, cover, how=""):
    """Writes the fields and cover into the file, notes each change, keeps what was there before."""
    path = os.path.join(src, rel)
    fields = {k: v for k, (v, _) in write.items()}
    keep = os.path.join(_undo_dir(d, rel), "before.json")
    if not os.path.exists(keep):  # the first change to this file: what it held then, covers as their own files
        f = _open(path)
        snap = {"rel": rel, "had_tags": f.tags is not None, "fields": _now(f), "covers": []}
        pics = list(getattr(f, "pictures", []) or [])
        if f.tags is not None and _kind(f) == "id3":
            pics = [t for k, t in f.tags.items() if str(k).startswith("APIC")]
        elif f.tags is not None and _kind(f) == "mp4":
            pics = [bytes(c) for c in f.tags.get("covr", [])]
        for i, p in enumerate(pics):
            name = f"cover{i}.bin"
            with open(os.path.join(os.path.dirname(keep), name), "wb") as out:
                out.write(p if isinstance(p, bytes) else p.data)
            snap["covers"].append(name)
        with open(keep + ".tmp", "w") as out:
            json.dump(snap, out, ensure_ascii=False)
        os.replace(keep + ".tmp", keep)
    with _same_time(path):
        before = _write(path, fields, cover[0] if cover else None)
    if before["fields"]:
        _after(d, src, rel)
    log, now = _load(d, LOG, []), int(time.time())
    for field in before["fields"]:
        if field == "cover":
            data = cover[0][0]
            w, h = _size(data)
            log.append({"rel": rel, "field": "cover", "old": "", "new": f"{w}x{h}", "source": cover[1] + how,
                        "hash": hashlib.sha1(data).hexdigest(), "at": now})
        else:
            log.append({"rel": rel, "field": field, "old": "", "new": fields[field], "source": write[field][1] + how,
                        "at": now})
    _save(d, LOG, log)
    return list(before["fields"])


def _cover(covers):
    for c in covers:
        got = _image(c["cover"])
        if got:
            return got, c["source"]
    return None


def look(d, src, rel, row=None):
    """Every source's candidates for one song: (candidates, [(artist, title)] readings, length, reachable)."""
    path = os.path.join(src, rel)
    f = _open(path)
    have, secs = _now(f), float(f.info.length or 0)
    stem = os.path.splitext(os.path.basename(rel))[0]
    a, sep, t = stem.partition(" - ")
    wants = []
    if have.get("artist") and have.get("title"):
        wants += guesses(have["artist"], have["title"])
    wants += guesses(a, t) if sep else [("", stem)]
    cands, reached = [], False
    if row is None:
        import soulseek
        for url in soulseek.links_inside(path)[:2]:
            url = re.sub(r"(?<=[a-z0-9-])(T[A-Z0-9]{3}|COMM|APIC|W[A-Z]{3})$", "", url)  # the next tag's name, stuck on
            try:
                row = soundcloud_page(url)
                reached = True
            except (OSError, ValueError):
                row = None
            if row and any(same_title(t, row["title"]) or same_title(t, row["artist"] + " - " + row["title"])
                           for _, t in wants):
                break
            row = None
    if row:
        cands.append(row)
        wants += guesses(row["artist"], row["title"])
    try:
        import recognise
        if recognise.key(d):
            heard = (recognise.load(d).get(rel) or {}).get("names") or []
            for artist, title in heard[:1]:
                cands.append({"title": title, "artist": artist, "album": "", "year": "", "genre": "", "length": secs,
                              "cover": "", "single": False, "compilation": False, "source": "AcoustID"})
    except Exception:
        pass
    asked = set()
    for artist, title in wants[:3]:
        if not artist or (flat(artist), flat(title)) in asked:
            continue
        asked.add((flat(artist), flat(title)))
        for fn in (itunes, musicbrainz):
            try:
                cands += fn(artist, title)
                reached = True
            except (OSError, ValueError):
                pass
        if any(_fits(c, wants, secs)[0] for c in cands if not c.get("exact")):
            break
    return cands, wants, secs, reached


def fill(d, src, rels, say=None, show=False, again=False):
    """Looks up every song that lacks something; writes what passes the checks, files the rest as needs-a-look.
    show: the page follows how far it is. again: you asked for these yourself, so a song nothing was found for is
    looked up again now, not after 30 days. Returns the counts; None while another run is at it."""
    import dj
    say = say or (lambda text: tell(d, text))
    lock = open(os.path.join(d, ".details.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    raw = {}
    for line in dj.read(d, ".listing").splitlines():
        try:
            r = json.loads(line)
            raw[r.get("webpage_url") or r.get("original_url") or ""] = r
        except ValueError:
            pass
    pairs = dj.pair(d, src, rels, dj.listing(d))
    import genres
    table = genres.lookup(genres.load(d)["list"])
    asks, now, n = _load(d, ASK, {}), int(time.time()), {"filled": 0, "fields": 0, "ask": 0, "none": 0}
    for i, rel in enumerate(rels):
        if show:
            note(d, i, len(rels))
        path = os.path.join(src, rel)
        miss = missing(path)
        if not miss:
            continue
        st = os.stat(path)
        old = asks.get(rel)
        if old and old.get("size") == st.st_size and old.get("mtime") == int(st.st_mtime) and \
                (old.get("candidates") or (not again and now - old.get("at", 0) < AGAIN)):
            continue
        r = raw.get((pairs.get(rel) or {}).get("url", ""))
        try:
            cands, wants, secs, reached = look(d, src, rel, soundcloud_row(r) if r else None)
        except Exception as e:
            say(f"details: {rel}: couldn't look it up ({str(e)[:120]})")
            continue
        write, covers, ask = decide(cands, wants, secs, table)
        write = {k: v for k, v in write.items() if k in miss}
        cover = _cover(covers) if "cover" in miss and covers else None
        done = _apply(d, src, rel, write, cover) if write or cover else []
        if done:
            n["filled"] += 1
            n["fields"] += len(done)
        left = missing(path)
        st = os.stat(path)
        ask = [c for c in ask if any(c.get(f) for f in left)]  # only candidates that would fill something
        if left and ask:
            asks[rel] = {"missing": left, "candidates": ask, "at": now, "size": st.st_size, "mtime": int(st.st_mtime)}
            n["ask"] += 1
        elif left and reached and not done:
            asks[rel] = {"missing": left, "candidates": [], "at": now, "size": st.st_size, "mtime": int(st.st_mtime)}
            n["none"] += 1
        else:
            asks.pop(rel, None)
        _save(d, ASK, asks)
    if show:
        try:
            os.remove(os.path.join(d, PROGRESS))
        except OSError:
            pass
    s = lambda k: f"{n[k]} song{'' if n[k] == 1 else 's'}"
    said = [f"added {n['fields']} detail{'' if n['fields'] == 1 else 's'} to {s('filled')}"] if n["filled"] else []
    said += [f"{s('ask')} need{'s' if n['ask'] == 1 else ''} your pick"] if n["ask"] else []
    said += [f"nothing found for {s('none')}"] if n["none"] else []
    if n["filled"]:
        _safe(d, src)
    if said or show:
        say("details: " + ("; ".join(said) or "nothing to add"))
    return n


def pick(d, src, rel, n):
    """Writes candidate n (1 = first) of a song that needs a look, into its still-empty fields."""
    asks = _load(d, ASK, {})
    c = (asks.get(rel) or {}).get("candidates") or []
    if not 1 <= n <= len(c):
        raise SystemExit(f"no candidate {n} for {rel}")
    c = c[n - 1]
    miss = missing(os.path.join(src, rel))
    write = {k: (c[k], c["source"]) for k in ("title", "artist", "album", "genre", "year") if c.get(k) and k in miss}
    cover = None
    if "cover" in miss and c.get("cover"):
        got = _image(c["cover"])
        cover = (got, c["source"]) if got else None
    done = _apply(d, src, rel, write, cover, " (your pick)")
    if done:
        tell(d, f"details: added {', '.join(done)} to {os.path.basename(rel)} (your pick)")
    asks.pop(rel, None)
    _save(d, ASK, asks)
    return done


def undo(d, src, rel):
    """Puts back what the song held before The Crate filled it in."""
    log = _load(d, LOG, [])
    mine = [e for e in log if e["rel"] == rel and not e.get("undone")]
    if not mine:
        return 0
    try:
        with open(os.path.join(_undo_dir(d, rel), "before.json")) as f:
            had = json.load(f).get("had_tags", True)
    except (OSError, ValueError):
        had = True
    with _same_time(os.path.join(src, rel)):
        n = _unwrite(os.path.join(src, rel), mine, had)
    if n:
        _after(d, src, rel)
        tell(d, f"details: took {n} added detail{'' if n == 1 else 's'} out of {os.path.basename(rel)} again")
    now = int(time.time())
    for e in mine:
        e["undone"] = now
    _save(d, LOG, log)
    asks = _load(d, ASK, {})  # back on the list, so he can pick another candidate (or leave it)
    path = os.path.join(src, rel)
    st = os.stat(path)
    asks.setdefault(rel, {"candidates": []})
    asks[rel].update({"missing": missing(path), "at": now, "size": st.st_size, "mtime": int(st.st_mtime),
                      "undone": True})
    _save(d, ASK, asks)
    return n


def moved(d, old, new):
    """The song goes by another name now (its FLAC became an AIFF, or came back): what was filled in, what waits for
    your pick, and the undo all follow it."""
    log = _load(d, LOG, [])
    if any(e["rel"] == old for e in log):
        _save(d, LOG, [{**e, "rel": new} if e["rel"] == old else e for e in log])
    for name in (ASK, HAVE):
        rec = _load(d, name, {})
        if old in rec:
            rec[new] = rec.pop(old)
            _save(d, name, rec)
    path = os.path.join(d, CHANGED)  # a tag change still to reach the USB follows too, so its copy there is redone
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    if any(l.partition("\t")[0] == old for l in lines):
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.writelines((new + l[len(old):] if l.partition("\t")[0] == old else l) + "\n" for l in lines)
        os.replace(path + ".tmp", path)
    a, b = (os.path.join(d, UNDO, hashlib.sha1(r.encode()).hexdigest()[:16]) for r in (old, new))
    if os.path.isdir(a) and not os.path.exists(b):
        os.rename(a, b)


def status(d, src=None):
    """{rel: {missing, filled: [{field, new, source, at}], ask: [candidates], undoable}} for the page."""
    out = {}
    for e in _load(d, LOG, []):
        s = out.setdefault(e["rel"], {"missing": [], "filled": [], "ask": [], "undoable": False})
        if not e.get("undone"):
            s["filled"].append({k: e.get(k) for k in ("field", "new", "source", "at")})
            s["undoable"] = True
    for rel, a in _load(d, ASK, {}).items():
        s = out.setdefault(rel, {"missing": [], "filled": [], "ask": [], "undoable": False})
        s["missing"], s["ask"] = a.get("missing") or [], a.get("candidates") or []
        s["looked"] = a.get("at", 0)
    if src:
        import dj
        for rel in dj.tracks(d, src):
            m = missing(os.path.join(src, rel))
            if m or rel in out:
                out.setdefault(rel, {"missing": [], "filled": [], "ask": [], "undoable": False})["missing"] = m
    return out


def scan(d, src, rels):
    """Notes what each song lacks (details-have.json), opening only the files that changed since the last look."""
    old, new = _load(d, HAVE, {}), {}
    for rel in rels:
        try:
            st = os.stat(os.path.join(src, rel))
        except OSError:
            continue
        o = old.get(rel)
        new[rel] = o if isinstance(o, list) and o[:2] == [st.st_size, int(st.st_mtime)] else \
            [st.st_size, int(st.st_mtime), missing(os.path.join(src, rel))]
    if new != old:
        _save(d, HAVE, new)
    return new


def have(d):
    """{song: what it lacks}, as last noted. Opens no music file: the page asks every few seconds."""
    return {rel: v[2] for rel, v in _load(d, HAVE, {}).items() if isinstance(v, list) and len(v) == 3 and v[2]}


def load(d):
    """{"auto": new songs are filled in by themselves, "seen": the songs here before that began, by name without the
    ending (None: not looked yet)}."""
    rec = _load(d, SET, {})
    return {"auto": rec.get("auto") is not False, "seen": rec["seen"] if isinstance(rec.get("seen"), list) else None}


def save(d, rec):
    _save(d, SET, rec)


def auto(d, src, rels):
    """Fills in the songs that arrived since the first look. The ones already here then are yours to pick on the
    page, and so is every song that arrives while the switch is off."""
    rec, stem = load(d), lambda r: os.path.splitext(r)[0]
    scan(d, src, rels)
    if rec["seen"] is None or not rec["auto"]:
        save(d, {"auto": rec["auto"], "seen": sorted(set(rec["seen"] or []) | {stem(r) for r in rels})})
        return None
    seen = set(rec["seen"])
    new = [r for r in rels if stem(r) not in seen]
    if not new:
        return None
    n = fill(d, src, new)
    if n is None:
        return None
    asks, lacks, logged = _load(d, ASK, {}), have(d), {e["rel"] for e in _load(d, LOG, [])}
    # looked at: full now, filed for your pick, or filled as far as it goes. One no source answered for (no internet)
    # is tried again next time.
    seen |= {stem(r) for r in new if r not in lacks or r in asks or r in logged}
    save(d, {"auto": True, "seen": sorted(seen)})
    return n


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] in ("auto", "scan"):
        import dj
        (auto if a[0] == "auto" else scan)(a[1], a[2], dj.tracks(a[1], a[2]))
    elif len(a) >= 3 and a[0] == "fill":
        import aiff, dj
        rels = [l.strip("\n") for l in sys.stdin if l.strip()] if not sys.stdin.isatty() else []
        had = set(dj.tracks(a[1], a[2]))
        n = fill(a[1], a[2], [r for r in rels if r in had] or sorted(had), show=True, again=bool(rels))
        if n and n["filled"]:
            aiff.decks(a[1], a[2])
    elif len(a) == 5 and a[0] == "pick":
        done = pick(a[1], a[2], a[3], int(a[4]))
        _safe(a[1], a[2]) if done else None
        print(json.dumps(done))
    elif len(a) >= 4 and a[0] == "undo":
        n = sum(undo(a[1], a[2], rel) for rel in a[3:])
        _safe(a[1], a[2]) if n else None
        print(n)
    elif len(a) in (2, 3) and a[0] == "status":
        print(json.dumps(status(a[1], a[2] if len(a) == 3 else None), ensure_ascii=False))
    else:
        raise SystemExit(__doc__)
