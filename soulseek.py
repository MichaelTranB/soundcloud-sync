#!/usr/bin/env python3
"""Soulseek helper for soulseek.sh (sockseek does the searching and downloading).

  soulseek.py prepare DIR SLSK   writes DIR/soulseek.csv (Artist,Title,Length for every track still to get) and
                                 removes a Soulseek copy once the artist's own file has landed in the music folder
  soulseek.py record  DIR SLSK   updates DIR/soulseek.tsv (SoundCloud link, name, file) from sockseek's index
  soulseek.py missed  DIR SLSK   after both passes: notes each track Soulseek had nothing for (soulseek-missed.tsv)
  soulseek.py banned  DIR SLSK   prints sockseek's options that keep thrown-back files from being taken again

Every file sockseek brings is looked at before it counts (judge): its real length and the song named inside it must
be the playlist's song. A wrong one goes to the Trash and is remembered (soulseek-wrong.tsv); its track is looked
for again, from someone else. The page can throw a file back the same way ("Wrong or bad file").

DIR is the app folder (to-buy.tsv lives there); SLSK is the "From Soulseek" folder inside the music folder.
Standard library only.

Soulseek's server bans an account for 30 minutes after too many searches, so sockseek allows 34 every 220 s and
searching is what makes a sync slow. Most tracks still to get are bootlegs nobody shares; searching each one again
every sync costs the most and finds the least. So a track Soulseek had nothing at all for (no file in top quality,
both passes) waits before it's searched again: 1 day after the first miss, then 2, 4, and at most 7 days. New
tracks, and tracks that were there but whose sharers were offline, are searched every sync.
"""
import contextlib, csv, fcntl, json, os, re, shutil, subprocess, sys, time, unicodedata

# Bumped when the search itself gets better: every track it missed before is then looked for again at once.
SEARCH = "#search 2 (desperate, artist maybe wrong)\n"
WAIT_DAYS = (1, 2, 4, 7)  # after 1, 2, 3, 4+ misses in a row
SLACK = 3600  # a sync at about the same time the next day still counts as a day later

WRONG = "soulseek-wrong.tsv"  # every file thrown back: link, when, bytes, peer, the peer's file, who, why
AGAIN = ".soulseek-again"  # left by the page when a file is thrown back: Soulseek is asked again right away
FROM = "soulseek-from.tsv"  # where each kept file came from: file, peer, the peer's file
CHECKED = "soulseek-checked.json"  # each kept file, looked at once: file -> [bytes, time, why it looks wrong or ""]
STRIKES, STRIKE_DAYS = 3, 30  # 3 wrong files in a row for one track: Soulseek has only other songs by that name
# Words that don't say which song it is.
FILLER = set("the and with feat featuring free download remix flip edit bootleg vip rework mashup refix original mix "
             "version extended radio prod official audio".split())

AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus", ".alac", ".aac")
# A title like this is a short excerpt of the track, so its length says nothing about the real file.
CUT = re.compile(r"\b(?:clip|preview|snippet|teaser)\b", re.I)
# Promo text uploaders put in titles; Soulseek files never carry it, so it only hurts the search.
PROMO = re.compile(r"\s*[(\[][^)\]]*\b(?:free|download|dl|out now|premiere|buy|preview|clip|exclusive|support)\b[^)\]]*[)\]]", re.I)
VERSION = re.compile(r"[(\[][^)\]]*\b(?:remix|flip|edit|bootleg|vip|rework|mashup|refix)\b[^)\]]*[)\]]", re.I)
PREFIX = re.compile(r"^\s*(?:premiere|free download|free dl|out now)\s*[:|\-]\s*", re.I)


def norm(s):
    """Loose key for comparing names across yt-dlp's and sockseek's file-name clean-ups."""
    return re.sub(r"\W+", "", s.lower())


REMASTER = re.compile(r"\s+-\s+(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?(?:\s+version)?\s*$", re.I)


def split(name):
    """'Uploader - Title' (to-buy.tsv) -> (artist, title). A title like 'Artist - Track' wins over the uploader,
    which is often a label or a premiere channel."""
    # Written the way people type them: "Artist – Track" (long dash), "Artist- Track", "{Flip}" braces, stray
    # control characters between words. All made plain first, so the search sees "Artist - Track (Flip)".
    name = re.sub(r"[\x00-\x1f\x7f]+", " ", name).replace("{", "(").replace("}", ")")
    name = re.sub(r"\s+", " ", re.sub(r"\s+[\u2013\u2014]\s+|(?<=\w)[-\u2013\u2014]\s+(?=\S)", " - ", name)).strip()
    uploader, _, title = name.partition(" - ")
    if not title:
        return "", PROMO.sub("", uploader).strip()
    title = PREFIX.sub("", PROMO.sub("", title)).strip(" *|")
    if " - " in title:
        artist, _, track = title.partition(" - ")
        # "Feel Good Inc (Hairitage Remix) - Gorillaz": the remix tag marks the track, so the halves are swapped.
        if VERSION.search(artist) and not VERSION.search(track):
            artist, track = track, artist
        return artist.strip(), track.strip()
    return uploader.strip(), title


def to_get(d):
    rows = []
    try:
        with open(os.path.join(d, "to-buy.tsv")) as f:
            for line in f:
                name, link, _, secs, artist, title = (line.rstrip("\n").split("\t") + [""] * 5)[:6]
                if name and link:
                    # Spotify and Apple Music rows carry the artist and title apart (playlists.py): taken as they
                    # are, first artist only (the one in file names), without a " - Remastered 2011" kind of tail.
                    at = (artist.split(", ")[0], REMASTER.sub("", title)) if artist and title else split(name)
                    rows.append((link, name, *at, "" if CUT.search(name) else secs))
    except OSError:
        pass
    return rows


def load_got(d):
    try:
        with open(os.path.join(d, "soulseek.tsv")) as f:
            return [l.rstrip("\n").split("\t") for l in f if l.count("\t") == 2]
    except OSError:
        return []


def save_got(d, got):
    tmp = os.path.join(d, "soulseek.tsv.tmp")
    with open(tmp, "w") as f:
        f.writelines("\t".join(g) + "\n" for g in got)
    os.replace(tmp, os.path.join(d, "soulseek.tsv"))


def prepare(d, slsk):
    record(d, slsk)  # a track sockseek got in a run that stopped early counts before anything is searched again
    rows = to_get(d)
    wanted = {link for link, *_ in rows}
    music = os.path.dirname(slsk)
    originals = {norm(os.path.splitext(f)[0]) for f in os.listdir(music) if f.lower().endswith(AUDIO)}
    kept = []
    with locked(d):  # the page can throw a file back while a sync runs: one writer of soulseek.tsv at a time
        for link, name, path in load_got(d):
            # Got once, never fetched again: a copy moved or deleted by hand (it's on the USB) stays remembered.
            if os.path.exists(path) and link not in wanted and norm(name) in originals:
                os.remove(path)  # the artist's own file is here now; it replaces the Soulseek copy
                print(f"replaced by the original: {os.path.basename(path)}")
                continue
            kept.append([link, name, path])
        save_got(d, kept)
    have = {k[0] for k in kept}
    miss, now, thrown = load_missed(d), time.time(), strikes(d)
    seen, out, later = set(), [], 0
    for link, name, artist, title, secs in rows:
        key = (artist.lower(), title.lower())
        if link in have or not title or key in seen:
            continue
        seen.add(key)
        if resting(thrown.get(link), now) or not due(miss.get(link), query(artist, title), now):
            later += 1
            continue
        out.append((artist, title, secs))
    with open(os.path.join(d, "soulseek.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Artist", "Title", "Length"])
        w.writerows(out)
    print(f"searching Soulseek for {len(out)} track(s)" + (f"; {later} not on Soulseek lately, looked for later" if later else ""))


def query(artist, title):
    return f"{artist} - {title}" if artist else title


def load_missed(d):
    """link -> (query, misses in a row, last miss time) for tracks Soulseek had nothing for."""
    out = {}
    try:
        with open(os.path.join(d, "soulseek-missed.tsv")) as f:
            if f.readline() != SEARCH:
                return out  # missed by an older, weaker search: all searched again now
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) == 4 and p[2].isdigit():
                    try:
                        out[p[0]] = (p[1], int(p[2]), float(p[3]))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def next_look(entry):
    """When a missed track is searched again (epoch seconds)."""
    _, n, last = entry
    return last + WAIT_DAYS[min(n, len(WAIT_DAYS)) - 1] * 86400 - SLACK


def due(entry, q, now):
    # a track searched under other words (its title was read differently since) gets a fresh look
    return not entry or entry[0] != q or entry[1] < 1 or now >= next_look(entry)


def outcomes(d, log):
    """link -> set of (state, reason) for every finished sockseek job in DIR/log."""
    label = {query(artist, title): link for link, name, artist, title, _ in to_get(d)}
    out = {}
    try:
        with open(os.path.join(d, log), errors="replace") as f:
            for line in f:
                m = JOB.search(line)
                if not m or m.group(1) not in ("succeeded", "failed"):
                    continue
                rest = m.group(3).rstrip("\n")
                for lab, link in label.items():
                    if rest == lab or rest.startswith(lab + ": "):
                        out.setdefault(link, set()).add((m.group(1), (m.group(2) or "").lower()))
                        break
    except OSError:
        pass
    return out


def missed(d, slsk):
    """After this sync's passes: a track whose every search came back empty is counted as missed (looked for
    again later, see WAIT_DAYS); one found, or there but not downloaded, is searched again every sync."""
    rows = {link: query(artist, title) for link, name, artist, title, _ in to_get(d)}
    old, now = load_missed(d), time.time()
    new = {}
    res = outcomes(d, "soulseek-run.log")
    for link, q in rows.items():
        if link in res:
            if res[link] == {("failed", "no search results")}:
                n = old[link][1] + 1 if link in old and old[link][0] == q else 1
                new[link] = (q, n, now)
        elif link in old:
            new[link] = old[link]  # not searched this sync (still waiting): kept as it was
    tmp = os.path.join(d, "soulseek-missed.tsv.tmp")
    with open(tmp, "w") as f:
        f.write(SEARCH)
        f.writelines(f"{link}\t{q}\t{n}\t{int(t)}\n" for link, (q, n, t) in new.items())
    os.replace(tmp, os.path.join(d, "soulseek-missed.tsv"))


def got_links(d, slsk):
    """SoundCloud links of every track Soulseek has got: recorded ones and, during a run, ones sockseek just
    finished (so the page never shows a track as both downloaded and still to get)."""
    links = {g[0] for g in load_got(d)}
    done = finished(slsk)
    return links | {link for link, name, artist, title, _ in to_get(d) if (artist.lower(), title.lower()) in done}


def finished(slsk):
    """(artist, title) -> file, for each track sockseek finished and whose file is there."""
    index = os.path.join(slsk, ".index.sldl")
    done = {}
    try:
        with open(index, newline="") as f:
            for r in csv.DictReader(f):
                if r.get("state") == "1" and r.get("filepath"):
                    p = r["filepath"]
                    p = p if os.path.isabs(p) else os.path.normpath(os.path.join(slsk, p))
                    if os.path.exists(p):
                        done[(r.get("artist", "").lower(), r.get("title", "").lower())] = p
    except OSError:
        pass
    return done


@contextlib.contextmanager
def locked(d, name=".to-buy.lock"):
    """One writer at a time: the sync and the app's Downloads pickup both take tracks off to-buy.tsv."""
    with open(os.path.join(d, name), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def words(s):
    """The words that tell songs apart: lower case, no accents, 3 letters or more, no filler."""
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return {w for w in re.findall(r"[a-z0-9]{3,}", s)} - FILLER


def version_words(s):
    """Who made this version: the words inside "(X Remix)", "[Y Flip]" and the like."""
    return set().union(*(words(m.group(0)) for m in VERSION.finditer(str(s or "").replace("{", "(").replace("}", ")")))) \
        if s else set()


def inside(path):
    """(seconds, artist, title) of a file: its real length and the names written inside it (macOS's afinfo)."""
    try:
        out = subprocess.run(["afinfo", "-i", path], capture_output=True, encoding="utf-8", errors="replace",
                             timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return 0.0, "", ""
    secs = re.search(r"^estimated duration:\s*([\d.]+)", out, re.M)

    def tag(k):
        m = re.search(r'^\s+%s\s*: "(.*)"\s*$' % k, out, re.M)
        return m.group(1).strip() if m else ""
    return float(secs.group(1)) if secs else 0.0, tag("artist"), tag("title")


def mmss(secs):
    return f"{int(secs) // 60}:{int(secs) % 60:02d}"


def judge(path, name, secs, remote="", thrown=()):
    """Is this file the playlist's song? "" when it is, else why not, in plain words. name: "Uploader - Title" as on
    the playlist; secs: the playlist song's length (0 = unknown, or the upload is only a clip); remote: the file's
    name on the peer's computer; thrown: the sizes of files already thrown back for this track.
      - more than 15 s longer or shorter: another song or version, or a download that stopped halfway;
      - 5 to 15 s off: only kept when the song named inside the file is this one;
      - a different song named inside: wrong, whatever the length;
      - "(A Remix)" asked for, "(B Remix)" in the file's name: another version."""
    try:
        if os.path.getsize(path) in thrown:
            return "the same file that was thrown back before"
    except OSError:
        return ""
    real, artist, title = inside(path)
    want = words(name.partition(" - ")[2] or name)
    named = None  # nothing written inside: no say
    if want and words(title):
        named = len(want & words(artist + " " + title)) * 2 >= len(want)
    if secs and real:
        off = abs(real - secs)
        if off > 15 or (off > 5 and not named):
            return f"it is {mmss(real)} long, the playlist's song is {mmss(secs)}"
    if named is False:
        return f"inside it is another song: {artist + ' - ' if artist else ''}{title}"[:160]
    mine = version_words(name)
    for other in (title, os.path.splitext(remote.replace("\\", "/").rsplit("/", 1)[-1])[0]):
        theirs = version_words(other)
        if mine and theirs and not mine & theirs:
            return f"another version: {other}"[:160]
    return ""


def lengths(d):
    """SoundCloud link -> the song's length in seconds, from the playlist as last read and the to-get list."""
    out = {}
    try:
        with open(os.path.join(d, ".listing"), errors="replace") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("webpage_url") and r.get("duration"):
                        out[r["webpage_url"]] = float(r["duration"])
                except (ValueError, TypeError, AttributeError):
                    pass
    except OSError:
        pass
    for link, name, artist, title, secs in to_get(d):
        try:
            out[link] = float(secs) if secs else out.get(link, 0)
        except ValueError:
            pass
    return out


def length_of(secs, link, name):
    return 0 if CUT.search(name) else secs.get(link, 0)


def sources(d):
    """SoundCloud link -> (peer, the peer's file), from sockseek's "succeeded" lines of the last passes."""
    label = {query(artist, title): link for link, name, artist, title, _ in to_get(d)}
    out = {}
    for log in ("soulseek-run.log", "soulseek-pass.log"):
        try:
            with open(os.path.join(d, log), errors="replace") as f:
                for line in f:
                    m = JOB.search(line)
                    if not m or m.group(1) != "succeeded":
                        continue
                    rest = m.group(3).rstrip("\n")
                    for lab, link in label.items():
                        if rest.startswith(lab + ": "):
                            peer, _, file = rest[len(lab) + 2:].partition("\\")
                            out[link] = (peer.strip(), file.strip())
                            break
        except OSError:
            pass
    return out


def rows_of(d, name, n):
    try:
        with open(os.path.join(d, name), errors="replace") as f:
            return [p for p in (l.rstrip("\n").split("\t") for l in f) if len(p) == n]
    except OSError:
        return []


def load_wrong(d):
    """Every file thrown back: [link, when, bytes, peer, the peer's file, who ("you" or "check"), why]."""
    return [w for w in rows_of(d, WRONG, 7) if w[1].isdigit() and w[2].isdigit()]


def strikes(d):
    """link -> (files thrown back for it, when the last one was, who, why)."""
    out = {}
    for link, when, _, _, _, who, why in load_wrong(d):
        out[link] = (out.get(link, (0,))[0] + 1, int(when), who, why)
    return out


def resting(strike, now):
    """True while a track that only brought wrong files waits before Soulseek is asked again. Never after a file
    you threw back yourself: that one is looked for again at once."""
    return bool(strike) and strike[2] != "you" and strike[0] % STRIKES == 0 and now - strike[1] < STRIKE_DAYS * 86400


def load_from(d):
    return {p[0]: (p[1], p[2]) for p in rows_of(d, FROM, 3)}


def save_from(d, came):
    tmp = os.path.join(d, FROM + ".tmp")
    with open(tmp, "w") as f:
        f.writelines("\t".join([p, *v]) + "\n" for p, v in came.items() if os.path.exists(p))
    os.replace(tmp, os.path.join(d, FROM))


def trash(d, path):
    """Out of the music folder and into the Trash, never deleted (beside the app when the Trash can't be written).
    Returns where it went, or "" when it couldn't be moved."""
    name, ext = os.path.splitext(os.path.basename(path))
    for folder in (os.path.expanduser("~/.Trash"), os.path.join(d, "Thrown back")):
        try:
            os.makedirs(folder, exist_ok=True)
            now = time.time()  # to the millisecond: a name of its own, so nothing in the Trash is written over
            to = os.path.join(folder, f"{name} (thrown back {time.strftime('%Y-%m-%d %H%M%S', time.localtime(now))}"
                                      f".{int(now * 1000) % 1000:03d}){ext}")
            shutil.move(path, to)
            return to
        except OSError:
            continue
    return ""


def throw_back(d, path, link, who, why, src=None):
    """One file out: to the Trash, and remembered so the same file is never taken again."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    peer, remote = src or load_from(d).get(path, ("", ""))
    if not trash(d, path):
        return False
    with open(os.path.join(d, WRONG), "a") as f:
        f.write("\t".join([link, str(int(time.time())), str(size), peer, remote, who,
                           re.sub(r"\s+", " ", why).strip()]) + "\n")
    return True


def banned(d):
    """sockseek's options, one a line: peers whose file you threw back are never asked again; peers whose file the
    check threw back come last (their other files may be fine)."""
    wrong = [w for w in load_wrong(d) if w[3] and "," not in w[3] and not w[3].startswith("-")]
    hard = sorted({w[3] for w in wrong if w[5] == "you"})
    soft = sorted({w[3] for w in wrong} - set(hard))
    return (["--banned-users", ",".join(hard)] if hard else []) + (["--pref-banned-users", ",".join(soft)] if soft else [])


def load_checked(d):
    try:
        with open(os.path.join(d, CHECKED)) as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def check_all(d, slsk):
    """Looks once at every Soulseek file already kept (the ones from before this check, and any that changed). A file
    that doesn't look like its playlist song is only marked: the page shows it and asks before it's thrown back."""
    seen, secs, came, out = load_checked(d), lengths(d), load_from(d), {}
    for link, name, path in load_got(d):
        try:
            st = os.stat(path)
        except OSError:
            continue
        old = seen.get(path)
        if isinstance(old, list) and old[:2] == [st.st_size, int(st.st_mtime)]:
            out[path] = old
        else:
            out[path] = [st.st_size, int(st.st_mtime),
                         judge(path, name, length_of(secs, link, name), came.get(path, ("", ""))[1])]
    if out != seen:
        tmp = os.path.join(d, CHECKED + ".tmp")
        with open(tmp, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=0)
        os.replace(tmp, os.path.join(d, CHECKED))
    return out


def suspects(d):
    """file -> why, for the kept files that don't look like their playlist song."""
    return {p: v[2] for p, v in load_checked(d).items() if isinstance(v, list) and len(v) == 3 and v[2] and os.path.exists(p)}


def bad(d, slsk, file=""):
    """From the page: one Soulseek file is the wrong song or a bad file (file: its name), or, with no name, every
    file the check marked. Each goes to the Trash, is never taken again, and its track is back on the to-get list.
    Returns how many went."""
    marked, secs, kept, back = suspects(d), lengths(d), [], []
    with locked(d):
        for link, name, path in load_got(d):
            mine = os.path.basename(path) == file if file else path in marked
            if mine and os.path.exists(path) and throw_back(
                    d, path, link, "you" if file else "check",
                    ("you marked it wrong or bad" + (": " + marked[path] if path in marked else "")) if file else marked[path]):
                back.append((link, name))
            else:
                kept.append([link, name, path])
        if file and not back and file == os.path.basename(file):  # a file in the folder The Crate has no note of
            path = os.path.join(slsk, file)
            if os.path.isfile(path) and throw_back(d, path, "", "you", "you marked it wrong or bad"):
                return 1
        if back:
            save_got(d, kept)
            tsv = os.path.join(d, "to-buy.tsv")
            try:
                with open(tsv) as f:
                    lines = f.read().splitlines()
            except OSError:
                lines = []
            there = {l.split("\t")[1] for l in lines if l.count("\t")}
            lines += [f"{name}\t{link}\t\t{round(secs.get(link, 0)) or ''}" for link, name in back if link not in there]
            with open(tsv + ".tmp", "w") as f:
                f.write("".join(l + "\n" for l in lines))
            os.replace(tsv + ".tmp", tsv)
    return len(back)


def record(d, slsk):
    """Adds what sockseek got to soulseek.tsv and takes those tracks off to-buy.tsv (got once, never again). First
    each new file is looked at (judge): one that isn't the playlist's song is thrown back and its track stays on
    the list."""
    done = finished(slsk)
    with locked(d):  # with the page's "Wrong or bad file" (bad): one writer at a time
        got = load_got(d)
        have = {g[0] for g in got}
        src, secs, wrong, came = sources(d), lengths(d), load_wrong(d), load_from(d)
        for link, name, artist, title, _ in to_get(d):
            p = done.get((artist.lower(), title.lower()))
            if p and link not in have and os.path.exists(p):
                at = src.get(link, ("", ""))
                why = judge(p, name, length_of(secs, link, name), at[1], {int(w[2]) for w in wrong if w[0] == link})
                if why and throw_back(d, p, link, "check", why, at):
                    print(f"thrown back, not the playlist's song: {os.path.basename(p)} ({why})")
                    continue
                got.append([link, name, p])
                have.add(link)
                came[p] = at
        save_got(d, got)
        save_from(d, came)
        path = os.path.join(d, "to-buy.tsv")
        try:
            with open(path) as f:
                rows = [l for l in f if l.split("\t")[1:2] and l.split("\t")[1] not in have]
            with open(path + ".tmp", "w") as f:
                f.writelines(rows)
            os.replace(path + ".tmp", path)
        except OSError:
            pass
    check_all(d, slsk)


# sockseek's per-track log lines ("[004] SongJob: failed [No search results]: Artist - Title"), in plain words.
JOB = re.compile(r"SongJob: (searching|downloading|succeeded|failed)(?: \[([^\]]*)\])?: (.*)")
WHY = {
    "no search results": "Not on Soulseek in top quality (lossless or a real 320 MP3, same length).",
    "all downloads failed": "On Soulseek, but everyone sharing it was offline or busy. The app will try again next sync.",
}


def progress(d, live):
    """SoundCloud link -> (state, why) for each track still to get, from sockseek's logs: "searching" or
    "downloading" while a sync is on it right now, "queued" when this sync will look for it, else "missing" with
    the reason from the last time Soulseek looked. live: a sync is running and its Soulseek step has started."""
    label = {}
    for link, name, artist, title, _ in to_get(d):
        label[f"{artist} - {title}" if artist else title] = link
    def events(log):
        last = {}
        try:
            with open(os.path.join(d, log), errors="replace") as f:
                for line in f:
                    m = JOB.search(line)
                    if not m:
                        continue
                    rest = m.group(3).rstrip("\n")
                    for lab, link in label.items():
                        if rest == lab or rest.startswith(lab + ": "):
                            last[link] = (m.group(1), (m.group(2) or "").lower())
                            break
        except OSError:
            pass
        return last
    # soulseek-run.log: every finished pass (of this sync while one runs, else of the last one);
    # soulseek-pass.log: the pass running now (lossless first, then 320 MP3 for what that didn't find).
    done, now = events("soulseek-run.log"), events("soulseek-pass.log") if live else {}
    queued = set()
    if live:
        try:
            with open(os.path.join(d, "soulseek.csv"), newline="") as f:
                want = {(r["Artist"], r["Title"]) for r in csv.DictReader(f)}
            queued = {link for link, name, artist, title, _ in to_get(d) if (artist, title) in want}
        except (OSError, KeyError):
            pass
    miss, t, thrown = load_missed(d), time.time(), strikes(d)
    soon = os.path.exists(os.path.join(d, AGAIN))  # a file was just thrown back: a search starts as soon as it can
    out = {}
    for link, name, artist, title, _ in to_get(d):
        state, reason = (now.get(link) or ("queued", "")) if link in queued else done.get(link, ("", ""))
        m = miss.get(link)
        if m and m[0] != query(artist, title):
            m = None
        if live and state in ("searching", "downloading", "queued"):
            out[link] = (state, "")
        elif link in thrown and state in ("", "succeeded"):  # the file Soulseek brought last was thrown back
            n, when, who, said = thrown[link]
            if soon and not resting(thrown[link], t):
                out[link] = ("queued", "")
                continue
            again = ("on " + time.strftime("%b %-d", time.localtime(when + STRIKE_DAYS * 86400))
                     if resting(thrown[link], t) else "next sync")
            what = "you threw back Soulseek's file" if who == "you" else f"Soulseek's file wasn't this song ({said})"
            out[link] = ("missing", f"Not found yet: {what}. Looks for another copy {again}.")
        elif state == "failed" and reason != "no search results":
            out[link] = ("missing", WHY.get(reason, f"Soulseek: {reason}." if reason else "Not found on Soulseek."))
        elif m:  # nothing on Soulseek the last time(s) it looked: when it looks again
            when = next_look(m)
            again = "next sync" if when <= t else "on " + time.strftime("%b %-d", time.localtime(when))
            out[link] = ("missing", f"{WHY['no search results'][:-1]}; looks again {again}.")
        else:  # not looked for yet, or only by an older search (SEARCH): looked for next sync
            out[link] = ("missing", "")
    return out

if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("prepare", "record", "missed", "banned"):
        sys.exit(__doc__)
    if sys.argv[1] == "banned":
        print("\n".join(banned(sys.argv[2])))
    else:
        {"prepare": prepare, "record": record, "missed": missed}[sys.argv[1]](sys.argv[2], sys.argv[3])
