#!/usr/bin/env python3
"""Soulseek helper for soulseek.sh (sockseek does the searching and downloading).

  soulseek.py prepare DIR SLSK   writes DIR/soulseek.csv (Artist,Title,Length for every track still to get) and
                                 removes a Soulseek copy once the artist's own file has landed in the music folder
  soulseek.py record  DIR SLSK   updates DIR/soulseek.tsv (SoundCloud link, name, file) from sockseek's index
  soulseek.py missed  DIR SLSK   after both passes: notes each track Soulseek had nothing for (soulseek-missed.tsv)

DIR is the app folder (to-buy.tsv lives there); SLSK is the "From Soulseek" folder inside the music folder.
Standard library only.

Soulseek's server bans an account for 30 minutes after too many searches, so sockseek allows 34 every 220 s and
searching is what makes a sync slow. Most tracks still to get are bootlegs nobody shares; searching each one again
every sync costs the most and finds the least. So a track Soulseek had nothing at all for (no file in top quality,
both passes) waits before it's searched again: 1 day after the first miss, then 2, 4, and at most 7 days. New
tracks, and tracks that were there but whose sharers were offline, are searched every sync.
"""
import csv, os, re, sys, time

# Bumped when the search itself gets better: every track it missed before is then looked for again at once.
SEARCH = "#search 2 (desperate, artist maybe wrong)\n"
WAIT_DAYS = (1, 2, 4, 7)  # after 1, 2, 3, 4+ misses in a row
SLACK = 3600  # a sync at about the same time the next day still counts as a day later

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
    for link, name, path in load_got(d):
        # Got once, never fetched again: a copy moved or deleted by hand (it's on the USB) stays remembered.
        if os.path.exists(path) and link not in wanted and norm(name) in originals:
            os.remove(path)  # the artist's own file is here now; it replaces the Soulseek copy
            print(f"replaced by the original: {os.path.basename(path)}")
            continue
        kept.append([link, name, path])
    save_got(d, kept)
    have = {k[0] for k in kept}
    miss, now = load_missed(d), time.time()
    seen, out, later = set(), [], 0
    for link, name, artist, title, secs in rows:
        key = (artist.lower(), title.lower())
        if link in have or not title or key in seen:
            continue
        seen.add(key)
        if not due(miss.get(link), query(artist, title), now):
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


def record(d, slsk):
    """Adds what sockseek got to soulseek.tsv and takes those tracks off to-buy.tsv (got once, never again)."""
    done = finished(slsk)
    got = load_got(d)
    have = {g[0] for g in got}
    for link, name, artist, title, _ in to_get(d):
        p = done.get((artist.lower(), title.lower()))
        if p and link not in have and os.path.exists(p):
            got.append([link, name, p])
            have.add(link)
    save_got(d, got)
    path = os.path.join(d, "to-buy.tsv")
    try:
        with open(path) as f:
            rows = [l for l in f if l.split("\t")[1:2] and l.split("\t")[1] not in have]
    except OSError:
        return
    with open(path + ".tmp", "w") as f:
        f.writelines(rows)
    os.replace(path + ".tmp", path)



# sockseek's per-track log lines ("[004] SongJob: failed [No search results]: Artist - Title"), in plain words.
JOB = re.compile(r"SongJob: (searching|downloading|succeeded|failed)(?: \[([^\]]*)\])?: (.*)")
WHY = {
    "no search results": "Not on Soulseek in top quality (lossless or a real 320 MP3, same length).",
    "all downloads failed": "On Soulseek, but everyone sharing it was offline or busy. Tried again next sync.",
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
    miss, t = load_missed(d), time.time()
    out = {}
    for link, name, artist, title, _ in to_get(d):
        state, reason = (now.get(link) or ("queued", "")) if link in queued else done.get(link, ("", ""))
        m = miss.get(link)
        if m and m[0] != query(artist, title):
            m = None
        if live and state in ("searching", "downloading", "queued"):
            out[link] = (state, "")
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
    if len(sys.argv) != 4 or sys.argv[1] not in ("prepare", "record", "missed"):
        sys.exit(__doc__)
    {"prepare": prepare, "record": record, "missed": missed}[sys.argv[1]](sys.argv[2], sys.argv[3])
