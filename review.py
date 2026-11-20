#!/usr/bin/env python3
"""Checks each downloaded song against the playlist it came from, and keeps two lists for you:

    Maybe the wrong file   its name says another song, or another version, than the playlist's (or the check after
                           the download doubted it). You listen and say: "It's the right song", or throw it back
                           (another copy is looked for at once). Never changed by itself, never in "Tidy all".
    Names to tidy          the right song, but its title or artist isn't written the way the playlist has it, like
                           "Capochino - Tipsy" as the title of Capochino's "Tipsy". Tidy one, or Tidy all; Undo puts
                           the name back.

    python3 review.py list DIR SRC              both lists, as the page shows them (JSON; nothing is changed)
    python3 review.py tidy DIR SRC [REL...]     these songs (none: every song on Names to tidy) get the playlist's name
    python3 review.py keep DIR SRC REL          "It's the right song": off Maybe the wrong file
    python3 review.py asis DIR SRC REL          "Keep this name": off Names to tidy
    python3 review.py undo DIR SRC REL          the name and file name it had before
    python3 review.py renames DIR SRC           the file names still waiting for a quiet moment (run by the sync)

The playlist's name is the truth, exactly as the playlist shows it:
    SoundCloud   the artist the upload credits (else whoever uploaded it) and the title, less promo words ("[FREE
                 DL]", "Premiere:") and less the artist's own name in front ("Capochino - Tipsy" -> "Tipsy"). Any
                 other dash stays: "Selena Gomez - Slow Down (COSTA FLIP)" by COSTA is how SoundCloud has it.
    Spotify      its artist and title.
    Apple Music  the name it was got as, "Artist - Title".

Tidying writes the title and artist inside the file (what rekordbox, Engine DJ and every deck show; naming.py keeps
the undo, and the decks and the USB follow). A song from Soulseek also gets the file name "Artist - Title": its
record follows by the file's place (dj-moved.tsv, aiff.follow), and its copy on the USB is renamed, not copied twice.
A song SoundCloud handed over itself (the artist's own file, or a free download) keeps its file name: The Crate knows
it by that name. A file name waits while a conversion or a deck run is at work, and is done on the next sync.

Record in DIR: review.json {"keep": {link: the file's size you said is right}, "asis": {link: "artist<TAB>title"
you kept}, "done": {link: {"was": its file name before, "at": time, "rename": true while its file name waits}}}.
Runs with the private Python (Mutagen)."""
import contextlib, fcntl, json, os, re, sys, time, unicodedata

import details, naming, soulseek, usbsafe

FILE, LOCK = "review.json", ".review.lock"
NEW = 3 * 86400  # a song downloaded in the last 3 days is marked New
LONG = 180  # bytes: a file name longer than this is cut (most file systems hold 255)


def text(s):
    """A name as it's written, with stray spaces and look-alike letters made one: what "exactly the same" compares."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s or ""))).strip()


def read(d, name):
    try:
        with open(os.path.join(d, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


LABEL = {"records", "recordings", "recs", "music", "label", "labels", "audio", "sounds", "network", "nation",
         "collective", "digital", "entertainment", "worldwide", "premiere", "premieres", "tunes", "group"}


def tokens(s):
    return set(re.findall(r"[a-z0-9]+", details.flat(s))) - {"x", "and", "feat", "ft", "with", "vs"}


def sc_name(r):
    """(artist, title) as SoundCloud shows this upload. The artist is the one the upload credits, else whoever
    uploaded it. A title that starts with the artist ("Capochino - Tipsy") is the song's own name after it; one that
    starts with someone else is that one's song when the uploader's name is in its brackets, a remix ("Selena Gomez -
    Slow Down (COSTA FLIP)" by COSTA is Selena Gomez's "Slow Down (COSTA FLIP)", as DJ stores name them, so no title
    carries an artist), and is kept whole otherwise ("Texas Love - Young Thug" by FreeSlatt), unless a label uploaded it ("House Call Records" uploading "Dr. Fresch & Capochino -
    Frostbite"), named nowhere in it: then the artist is the one the title names."""
    up = text(r.get("uploader"))
    credit = text(str(r.get("artist") or "").replace("，", ", "))
    artist = credit or up
    title = text(soulseek.PROMO.sub("", soulseek.PREFIX.sub("", str(r.get("title") or ""))))
    lead, sep, rest = title.partition(" - ")
    lead, rest = lead.strip(), rest.strip()
    if sep and rest and tokens(lead):
        if tokens(lead) <= tokens(artist) | tokens(up):
            return (lead if tokens(lead) == tokens(artist) else artist), rest
        mine, v = soulseek.words(artist) | soulseek.words(up), soulseek.version_words
        if v(rest) & mine and not v(lead):  # a remix: its own artist first, the remixer's name in brackets after
            return lead, rest
        if v(lead) & mine and not v(rest) and not soulseek.VERSION.search(rest) and "(" not in rest:
            return rest, lead  # the same, written "Song (X Remix) - Artist"
        if tokens(up) & LABEL and (not credit or tokens(credit) == tokens(up)) and \
                details.flat(up) not in details.flat(title):
            return lead, rest
    return artist, title


def truth(d):
    """{link: (artist, title)}: each song's name as its playlist shows it."""
    out = {}
    for line in read(d, ".listing").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        url = r.get("webpage_url") or r.get("original_url")
        if url:
            out[url] = sc_name(r)
    try:
        with open(os.path.join(d, ".spotify-cache.json")) as f:
            spot = json.load(f)
    except (OSError, ValueError):
        spot = {}
    for link, name, _ in soulseek.load_got(d) + [r for r in soulseek.rows_of(d, "free.tsv", 3)]:
        if link in out:
            continue
        s = spot.get(link.split("/track/")[1].split("?")[0]) or {} if "open.spotify.com/track/" in link else {}
        if s.get("title"):
            out[link] = (text(s.get("artist")), text(s.get("title")))
        elif "soundcloud.com/" not in link and " - " in name:  # Apple Music, and Spotify songs the playlist's own
            # page listed (not kept in the cache): the name it was got as, made from the playlist's artist and title
            a, _, t = name.partition(" - ")
            out[link] = (text(a), text(t))
    return out


def sources(d, src):
    """{rel: (link, how)}: "soulseek" (renamed with its record) or "free" (known by its file name)."""
    root, out = os.path.realpath(src), {}
    for how, rows in (("free", soulseek.rows_of(d, "free.tsv", 3)), ("soulseek", soulseek.load_got(d))):
        for link, _, path in rows:
            out[os.path.relpath(os.path.realpath(path), root)] = (link, how)
    return out


def load(d):
    try:
        with open(os.path.join(d, FILE)) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        rec = {}
    return {k: rec[k] if isinstance(rec.get(k), dict) else {} for k in ("keep", "asis", "done")}


def save(d, rec):
    tmp = os.path.join(d, FILE + ".tmp")
    with open(tmp, "w") as f:
        json.dump(rec, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, os.path.join(d, FILE))


@contextlib.contextmanager
def locked(d):
    with open(os.path.join(d, LOCK), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def credited(artist, title, hay, their):
    """Someone the playlist names (its artist, the one before a dash in its title) is named in the file too."""
    from difflib import SequenceMatcher
    people = details.names(artist) | (details.names(title.partition(" - ")[0]) if " - " in title else set())
    people = {p for p in people if len(p) >= 2}
    flat, theirs = f" {details.flat(hay)} ", details.names(their)
    made = soulseek.version_words(title) - soulseek.words("remix flip edit bootleg vip rework mashup refix")
    if made & soulseek.words(their):  # the file names the remix's maker ("Trademark USA (STVSH FLIP)" by Stvsh)
        return True
    return not people or any(f" {p} " in flat or any(SequenceMatcher(None, p, h).ratio() >= 0.88 for h in theirs)
                             for p in people)


def peers(d, src):
    """{rel: the file's name as the Soulseek peer had it (folders too)}: what a Soulseek file was before The Crate
    named it from the search, so the one thing it can't say about itself."""
    root, out = os.path.realpath(src), {}
    for row in soulseek.rows_of(d, soulseek.FROM, 3):
        out[os.path.relpath(os.path.realpath(row[0]), root)] = row[2].replace("\\", " ").replace("_", " ")
    return out


MIX = re.compile(r"[(\[]([^)\]]*\b(?:mix|edit|version|dub|instrumental|acapella|vip|remix|bootleg|flip|rework|refix)\b"
                 r"[^)\]]*)[)\]]", re.I)


def mixes(s):
    """The words that say which cut a name is, from its brackets: "Club Mix" is {"club"}, "Radio Edit" {"radio"}."""
    low = lambda m: re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", m).lower())  # (soulseek.words drops "radio")
    return {w for m in MIX.findall(s or "") for w in low(m)} - {"mix", "edit", "version", "the", "a", "and", "x"}


CUT = re.compile(r"(?:[(\[]|\s-\s)[^)\]]*?\b(instrumental|a ?cc?app?ella|karaoke|live|sped up|slowed|nightcore|dub|demo"
                 r"|cover)\b", re.I)  # another recording of the song, not a name for the same one ("Extended Mix" is)


def cuts(title, *names):
    """The words saying a file is another recording ("Song (Instrumental)", "Song - Live") the playlist's title lacks."""
    low = unicodedata.normalize("NFKD", title or "").lower()
    return {w for n in names for w in (m.lower() for m in CUT.findall(n or "")) if not re.search(rf"\b{w}\b", low)}


ORIGINAL = re.compile(r"\boriginal (?:mix|version|edit)\b|[(\[]\s*original\s*[)\]]", re.I)


def doubt(artist, title, song, rel, cur, peer=""):
    """Why this file may be another song than the playlist's ("" when its name agrees). cur: (artist, title) inside
    the file. What's inside it and the name it came with are read together: either may be the one that says it. A
    Soulseek file's own name was made from the search, so for it the peer's name stands in (peer)."""
    stem = peer or os.path.splitext(os.path.basename(rel))[0]
    named = {w for w in soulseek.words(cur[1]) if not w.isdigit()} - {"track", "untitled", "unknown", "audio"}
    if named:  # what's written inside the file says it best; its name only when inside it says nothing
        stem = ""
    have = soulseek.words(stem) | soulseek.words(cur[1])
    base = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", " ", title)
    people = soulseek.words(artist) | soulseek.words(cur[0])  # (a name in the title isn't the song's name)
    main = ((soulseek.words(base) or soulseek.words(title)) - soulseek.EDITS - people) or \
        (soulseek.words(base) - soulseek.EDITS)
    if main and len(main & (have | soulseek.words(cur[0]))) * 2 < len(main):
        return f'its name has little of "{title}" in it'
    if not credited(artist, title, f"{cur[0]} {cur[1]} {stem}", cur[0]):
        return f"it says it's by {cur[0] or 'someone else'}, the playlist's is by {artist}"
    # (the version the peer's name gave stays evidence even when the tags name the song)
    want = soulseek.version_words(title)
    got = soulseek.version_words(stem) | soulseek.version_words(cur[1]) | soulseek.version_words(peer)
    if got and want and not got & want:
        return "it says it's another version: " + " ".join(sorted(got))
    wm, gm = mixes(title), mixes(cur[1]) | mixes(stem) | mixes(peer)
    if wm and gm and not wm & gm:  # ("Club Mix" asked, "Radio Edit" got: words version_words leaves out)
        return "it says it's another cut: " + " ".join(sorted(gm - wm))
    other = cuts(title, cur[1], stem, peer)
    if other:  # ("Song" asked, "Song (Instrumental)" got: neither check above sees it)
        return "it says it's another recording: " + " ".join(sorted(other))
    if want and not got and ORIGINAL.search(f"{cur[1]} {stem} {peer}"):  # ("Original Mix" holds no version words)
        return "it says it's the original, the playlist's is a version: " + " ".join(sorted(want))
    if got and not want and got - soulseek.words(artist) - soulseek.words(title):
        return "it says it's a version of the song, the playlist's isn't: " + " ".join(sorted(got))
    return ""


def wanted(artist, title, ext):
    """The file name a song gets: "Artist - Title", in signs every USB holds."""
    stem = usbsafe.safe(f"{artist} - {title}".replace("/", "／")).strip(". ")
    while len(stem.encode()) > LONG:
        stem = stem[:-1]
    return stem.rstrip(". ") + ext


def songs(d, src):
    return naming._songs(d, src)  # dj.library: every song with the title and artist inside its file


def has(src, rel, s):
    """(artist, title) written inside the file now ("" for one it doesn't hold); the library's notes only when the
    file can't be opened."""
    try:  # the file itself: the library fills an empty artist from the file name, which the decks don't show
        now = naming._tags(details._open(os.path.join(src, rel)))[1]
    except Exception:
        return (text(s.get("artist")), text(s.get("title"))) if s.get("tagged") else ("", "")
    return text(now.get("artist")), text(now.get("title"))


def lists(d, src, lib=None):
    """{"wrong": [...], "tidy": [...], "done": [...]} for the page, the newest downloads first."""
    lib = lib if lib is not None else songs(d, src)
    rec, tr, where, now = load(d), truth(d), sources(d, src), time.time()
    them = peers(d, src)
    sus = {os.path.relpath(os.path.realpath(p), os.path.realpath(src)): why for p, why in soulseek.suspects(d).items()}
    wrong, tidy, done = [], [], []
    for rel, s in lib.items():
        link, how = where.get(rel) or (s.get("url") or "", "own")
        if link not in tr:
            continue
        artist, title = tr[link]
        cur = has(src, rel, s)
        ext = os.path.splitext(rel)[1]
        item = {"file": rel, "link": link, "from": how, "artist": cur[0], "title": cur[1],
                "want": {"artist": artist, "title": title}, "name": os.path.basename(rel),
                "mtime": s.get("mtime") or 0, "new": now - (s.get("mtime") or 0) < NEW}
        was = rec["done"].get(link)
        if was:
            done.append({**item, "was": was.get("was", ""), "said": was.get("said") or [], "at": was.get("at", 0),
                         "waiting": bool(was.get("rename"))})
        why = sus.get(rel) or (doubt(artist, title, s, rel, cur, them.get(rel, "") if how == "soulseek" else "")
                               if how != "own" else "")
        if why and rec["keep"].get(link) != s.get("size"):
            wrong.append({**item, "why": why})
            continue
        named = how != "soulseek" or os.path.basename(rel) == wanted(artist, title, ext)
        if cur == (artist, title) and named:
            continue
        if was and was.get("rename") and cur == (artist, title):
            continue  # tidied: its file name waits for a quiet moment
        if rec["asis"].get(link) == naming.sig(*cur):
            continue
        tidy.append({**item, "rename": not named and how == "soulseek",
                     "to": wanted(artist, title, ext) if not named and how == "soulseek" else ""})
    order = lambda x: (-x["mtime"], x["name"].lower())
    return {"wrong": sorted(wrong, key=order), "tidy": sorted(tidy, key=order),
            "done": sorted(done, key=lambda x: -x["at"])[:50]}


def tidy(d, src, rels=()):
    """The playlist's name for these songs (none: every song on Names to tidy). Returns how many changed."""
    lib = songs(d, src)
    todo = {t["file"]: t for t in lists(d, src, lib)["tidy"]}
    n = 0
    for rel in (rels or list(todo)):
        t, s = todo.get(rel), lib.get(rel)
        if not t or not s:
            continue
        way = t["want"]
        snap = prior = None
        if (t["artist"], t["title"]) != (way["artist"], way["title"]):
            try:  # what Undo puts back: these very tags, and the Library Manager's own undo note as it was
                now = naming._tags(details._open(os.path.join(src, rel)))[1]
                snap = {f: now.get(f) or "" for f in ("artist", "title")}
                with naming.locked(d):
                    prior = naming.load(d)["fixed"].get(rel)
            except Exception as e:
                print(f"{rel}: its name now couldn't be read ({e}), so it's left as it is", file=sys.stderr)
                continue
            naming.apply(d, src, s, way, " (the playlist's name)")
        naming.fine(d, rel, way["artist"], way["title"])  # the Library Manager doesn't suggest another way round
        with locked(d):
            rec = load(d)
            old = rec["done"].get(t["link"]) or {}
            rec["done"][t["link"]] = {"was": old.get("was") or t["name"], "at": int(time.time()),
                                      "said": old.get("said") or [t["artist"], t["title"]],
                                      **({"tags": old["tags"], "fixed": old.get("fixed")} if "tags" in old else
                                         {"tags": snap or {}, "fixed": prior}),  # {}: only its file name was tidied
                                      "to": [way["artist"], way["title"]],
                                      **({"rename": True} if t["rename"] else {})}
            rec["asis"].pop(t["link"], None)
            _still_kept(rec, t["link"], os.path.join(src, rel))
            save(d, rec)
        n += 1
    renames(d, src)
    return n


@contextlib.contextmanager
def quiet(d):
    """No conversion, deck run or Soulseek record at work (none is waited for): yields False when one is."""
    held = []
    try:
        for name in (".aiff.lock", ".dj.lock", ".to-buy.lock"):
            held.append(open(os.path.join(d, name), "a"))
            fcntl.flock(held[-1], fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        for f in held:
            f.close()
        yield False
        return
    try:
        yield True
    finally:
        for f in held:
            f.close()


def _move(d, src, link, to):
    """Renames the Soulseek file got for this link to `to` (a name in the same folder). (old, new) or None."""
    root = os.path.realpath(src)
    for l, _, path in soulseek.load_got(d):
        if l != link or not os.path.isfile(path):
            continue
        b = os.path.join(os.path.dirname(path), to)
        if os.path.basename(path) == to:
            return "same"
        if os.path.lexists(b):
            print(f'"{to}" is taken already: "{os.path.basename(path)}" keeps its file name', file=sys.stderr)
            return None
        try:
            if time.time() - os.path.getmtime(path) < usbsafe.FRESH:
                return None
            os.rename(path, b)
        except OSError as e:
            print(f'"{os.path.basename(path)}" couldn\'t be renamed ({e.strerror})', file=sys.stderr)
            return None
        return os.path.relpath(os.path.realpath(path), root), os.path.relpath(os.path.realpath(b), root)
    return None


def renames(d, src, back=None):
    """The file names waiting (back: {link: the file name to give back}, for Undo). Returns [(old, new), ...]."""
    with quiet(d) as ok:
        if not ok:
            return []
        tr, moved = truth(d), []
        with locked(d):
            rec = load(d)
            todo = back or {l: "" for l, v in rec["done"].items() if v.get("rename") and l in tr}
            for link, name in todo.items():
                cur = next((p for l, _, p in soulseek.load_got(d) if l == link), "")
                ext = os.path.splitext(cur)[1]  # (its FLAC may have become an AIFF since)
                to = (os.path.splitext(name)[0] + ext if back else wanted(*tr[link], ext)) if cur else ""
                got = _move(d, src, link, to) if to else None
                if got and got != "same":
                    moved.append(got)
                    usbsafe.noted(d, src, [got], "its playlist's name" if not back else "its name before, by Undo")
                if got and not back and link in rec["done"]:
                    rec["done"][link].pop("rename", None)
            save(d, rec)
        return moved


def _link(d, src, rel, lib=None):
    hit = sources(d, src).get(rel)
    return hit[0] if hit else ((lib if lib is not None else songs(d, src)).get(rel) or {}).get("url") or ""


def keep(d, src, rel):
    """"It's the right song": off Maybe the wrong file, until the file changes."""
    link = _link(d, src, rel)
    if not link or not os.path.isfile(os.path.join(src, rel)):
        return False
    with locked(d):
        rec = load(d)
        rec["keep"][link] = os.path.getsize(os.path.join(src, rel))
        save(d, rec)
    return True


def asis(d, src, rel, lib=None):
    """"Keep this name": off Names to tidy, until the name changes."""
    lib = lib if lib is not None else songs(d, src)
    s, link = lib.get(rel), _link(d, src, rel, lib)
    if not s or not link:
        return False
    a, t = has(src, rel, s)
    with locked(d):
        rec = load(d)
        rec["asis"][link] = naming.sig(a, t)
        save(d, rec)
    naming.fine(d, rel, s.get("artist") or "", s.get("title") or "")
    return True


def _still_kept(rec, link, path):
    """"It's the right song" holds while the file is the same: a name written by this list changes its size, not
    the song."""
    if link in rec["keep"]:
        try:
            rec["keep"][link] = os.path.getsize(path)
        except OSError:
            pass


def back_tags(d, src, rel, was):
    """The title and artist the file held just before it was tidied, and the Library Manager's undo note as it was
    then. A name changed since (by you, in another app) stays."""
    path, to = os.path.join(src, rel), dict(zip(("artist", "title"), was.get("to") or []))
    with naming.locked(d):
        nrec = naming.load(d)
        now = naming._tags(details._open(path))[1]
        back = {f: v for f, v in was["tags"].items() if f in to and (now.get(f) or "") == to[f]}
        with details._same_time(path):
            n = len(naming._set(path, back))
        naming._went(nrec, rel, **{f: [to[f]] for f in back})  # the decks' rows that showed the tidied name follow
        if was.get("fixed"):
            nrec["fixed"][rel] = was["fixed"]
        else:
            nrec["fixed"].pop(rel, None)
        naming.save(d, nrec)
    if n:
        details._after(d, src, rel)
        details.tell(d, f"names: {os.path.basename(rel)} has the name it had before again")


def undo(d, src, rel):
    """The title, artist and file name it had before it was tidied; then it's kept as it is (not suggested again)."""
    link = _link(d, src, rel)
    was = load(d)["done"].get(link)
    if not link or not was:
        return False
    if "tags" in was:
        if was["tags"]:  # (empty: only its file name was tidied, so its tags stay as they are)
            back_tags(d, src, rel, was)
    else:  # (tidied before Undo kept its own note)
        naming.undo(d, src, rel)
    stem = lambda n: os.path.splitext(n)[0]  # (converted since, to AIFF say: its kind stays as it is now)
    if was.get("was") and stem(was["was"]) != stem(os.path.basename(rel)) and sources(d, src).get(rel, ("", ""))[1] == "soulseek":
        moved = renames(d, src, {link: was["was"]})
        if not moved:
            return "Its name is back. Its file name comes back when The Crate isn't busy: try Undo again in a moment."
        rel = moved[0][1]
    with locked(d):
        rec = load(d)
        rec["done"].pop(link, None)
        _still_kept(rec, link, os.path.join(src, rel))
        try:
            now = naming._tags(details._open(os.path.join(src, rel)))[1]
            rec["asis"][link] = naming.sig(text(now.get("artist")), text(now.get("title")))
        except Exception:
            pass
        save(d, rec)
    return True


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 3:  # the notes keep each song's full path: a music folder reached through a link is followed
        a[2] = os.path.realpath(a[2])
    if len(a) >= 3 and a[0] == "list":
        print(json.dumps(lists(a[1], a[2]), ensure_ascii=False))
    elif len(a) >= 3 and a[0] == "tidy":
        print(json.dumps({"tidied": tidy(a[1], a[2], a[3:])}))
    elif len(a) == 4 and a[0] in ("keep", "asis", "undo"):
        r = {"keep": keep, "asis": asis, "undo": undo}[a[0]](a[1], a[2], a[3])
        if isinstance(r, str):
            print(r, file=sys.stderr)
        print(json.dumps({"ok": r is True}))
        sys.exit(0 if r is True else 1)
    elif len(a) == 3 and a[0] == "renames":
        for old, new in renames(a[1], a[2]):
            print(f'renamed "{old}" to "{new}"')
    else:
        sys.exit(__doc__)
