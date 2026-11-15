#!/usr/bin/env python3
"""Soulseek helper for soulseek.sh (sockseek does the searching and downloading).

  soulseek.py prepare DIR SLSK   writes DIR/soulseek.csv (Artist,Title,Length for every track still to get) and
                                 removes a Soulseek copy once the artist's own file has landed in the music folder
  soulseek.py record  DIR SLSK   updates DIR/soulseek.tsv (SoundCloud link, name, file) from sockseek's index

DIR is the app folder (to-buy.tsv lives there); SLSK is the "From Soulseek" folder inside the music folder.
Standard library only.
"""
import csv, os, re, sys

AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus", ".alac", ".aac")
# A title like this is a short excerpt of the track, so its length says nothing about the real file.
CUT = re.compile(r"\b(?:clip|preview|snippet|teaser)\b", re.I)
# Promo text uploaders put in titles; Soulseek files never carry it, so it only hurts the search.
PROMO = re.compile(r"\s*[(\[][^)\]]*\b(?:free|download|dl|out now|premiere|buy|preview|clip|exclusive|support)\b[^)\]]*[)\]]", re.I)
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
    seen, out = set(), []
    for link, name, artist, title, secs in rows:
        key = (artist.lower(), title.lower())
        if link in have or not title or key in seen:
            continue
        seen.add(key)
        out.append((artist, title, secs))
    with open(os.path.join(d, "soulseek.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Artist", "Title", "Length"])
        w.writerows(out)
    print(f"searching Soulseek for {len(out)} track(s)")


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
    out = {}
    for link, name, *_ in to_get(d):
        state, reason = (now.get(link) or ("queued", "")) if link in queued else done.get(link, ("", ""))
        if live and state in ("searching", "downloading", "queued"):
            out[link] = (state, "")
        elif state == "failed":
            out[link] = ("missing", WHY.get(reason, f"Soulseek: {reason}." if reason else "Not found on Soulseek."))
        else:
            out[link] = ("missing", "")
    return out

if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("prepare", "record"):
        sys.exit(__doc__)
    {"prepare": prepare, "record": record}[sys.argv[1]](sys.argv[2], sys.argv[3])
