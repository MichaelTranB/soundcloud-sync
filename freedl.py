#!/usr/bin/env python3
"""Fetches the artist's own free download when their SoundCloud description links straight to a file host.

  freedl.py inbox DIR OUT   takes still-to-get tracks you downloaded by hand out of ~/Downloads (see inbox())
  freedl.py DIR OUT   reads DIR/to-buy.tsv, downloads what it can into OUT, records it in DIR/free.tsv
                      (link, name, file) and takes it off DIR/to-buy.tsv

Hosts with a plain download URL: Dropbox, Google Drive, pixeldrain, and a direct link to an audio or zip file.
Download gates (Hypeddit, ToneDen and the like), Bandcamp and hosts that need a browser (Mega, WeTransfer,
Mediafire) stay one click on the page. Only top quality is kept: lossless, or MP3/AAC at 320 kbps. A zip is
opened and only its audio is taken. A link that gave a non-audio or low-quality file is not tried again.
"""
import json, os, re, shutil, stat, sys, tempfile, time, urllib.parse, urllib.request, zipfile
import safety
from soulseek import CUT, locked, split
from audio import info, top_quality

MAX = 2_000_000_000  # bytes; nothing an artist gives away is bigger
AUDIO_EXT = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".aac")


def norm(s):
    return re.sub(r"\W+", "", s.lower())


def direct(url):
    """The URL that returns the file itself, or None for hosts that need a browser or a gate."""
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower().removeprefix("www.")
    if host == "dropbox.com":
        q = dict(urllib.parse.parse_qsl(u.query)) | {"dl": "1"}
        return u._replace(query=urllib.parse.urlencode(q)).geturl()
    if host == "dl.dropboxusercontent.com":
        return url
    if host == "drive.google.com":
        m = re.search(r"/file/d/([\w-]+)", u.path) or re.search(r"(?:^|&)id=([\w-]+)", u.query)
        return m and f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
    if host == "pixeldrain.com":
        m = re.match(r"/u/(\w+)", u.path)
        return m and f"https://pixeldrain.com/api/file/{m.group(1)}?download"
    if u.scheme == "https" and u.path.lower().endswith(AUDIO_EXT + (".zip",)):
        return url
    return None


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        size = 0
        while chunk := r.read(1 << 20):
            size += len(chunk)
            if size > MAX:
                raise ValueError("file too big")
            f.write(chunk)


def best_audio(tmp, name, secs=None):
    """The downloaded file itself, or from a zip the top-quality track whose file name carries the song's title
    as whole words (the same matching the Downloads pickup uses); the full title with its version first, then the
    one whose length matches SoundCloud's (a pack often holds the original and an extended mix)."""
    if not zipfile.is_zipfile(tmp):
        i = info(tmp)
        return (tmp, i) if top_quality(i) else (None, i)
    short, full, _ = wanted(name)
    picks = []
    with zipfile.ZipFile(tmp) as z:
        for m in z.infolist():
            base = os.path.basename(m.filename)
            if m.is_dir() or base.startswith(".") or not base.lower().endswith(AUDIO_EXT) or m.file_size > MAX:
                continue
            out = os.path.join(os.path.dirname(tmp), f"member-{len(picks)}{os.path.splitext(base)[1].lower()}")
            with z.open(m) as src, open(out, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            i = info(out)
            if top_quality(i):
                b = words(os.path.splitext(base)[0])
                off = abs(i["secs"] - float(secs)) if secs and i.get("secs") else 0
                picks.append((has(b, short), has(b, full), off <= 5, i["lossless"], -off, out, i))
    # One track: it's the download. Several: only one whose file name carries the title, never a guess.
    if len(picks) > 1:
        picks = [p for p in picks if p[0]]
    if not picks:
        return None, None
    *_, path, i = max(picks, key=lambda p: p[:5])
    return path, i


def song_key(name):
    """The song's own title, squeezed: "Label - Artist - Song (Extended Mix)" -> "song"."""
    title = name.partition(" - ")[2] or name
    return norm(re.sub(r"[(\[][^)\]]*[)\]]", "", title.rsplit(" - ", 1)[-1])), norm(title.rsplit(" - ", 1)[-1])


def words(s):
    return re.findall(r"[^\W_]+", s.lower())


def has(hay, needle):
    """True when the word list needle appears whole and in order in hay ("home" is not in "homecoming")."""
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


# Words that say nothing about which song a file is ("Edit", "Final"...), left out of hint()
GENERIC = {"remix", "edit", "flip", "bootleg", "mix", "extended", "original", "version", "free", "download", "official",
           "audio", "feat", "with", "master", "mastered", "final", "intro", "clean", "dirty", "radio", "club", "dub"}


def hint(name, texts):
    """True when a file's name shares a telling word (4+ letters) with the song: "Everybody (Zach Knows Edit)" for
    "Zach Knows - Everybody - Kanye West, TY Dolla $ign (Zach Knows Edit)". Only used together with a click."""
    w = {x for x in words(name) if len(x) >= 4 and x not in GENERIC}
    return any(w & set(t) for t in texts)


def wanted(name):
    """What a downloaded file's name must show to be this song: (title words, full title words with the
    version, [artist or uploader words])."""
    artist, title = split(name)
    who = [w for w in {tuple(words(artist)), tuple(words(name.partition(" - ")[0] if " - " in name else ""))} if w]
    return words(re.sub(r"[(\[][^)\]]*[)\]]", "", title)), words(title), [list(w) for w in who]


def file_name(out, name, ext, tag):
    safe = re.sub(r'[/:\x00-\x1f]', "-", name).strip(". ")[:200]
    dest = os.path.join(out, f"{safe}.{ext}")
    return dest if not os.path.exists(dest) else os.path.join(out, f"{safe} ({tag}).{ext}")


def record(d, got):
    """Adds (link, name, file) to free.tsv and takes those tracks off to-buy.tsv."""
    if not got:
        return
    with open(os.path.join(d, "free.tsv"), "a") as f:
        f.writelines("\t".join(g) + "\n" for g in got)
    done = {g[1] for g in got}
    path = os.path.join(d, "to-buy.tsv")
    with locked(d):
        with open(path) as f:
            rows = [l for l in f if l.split("\t")[0] not in done]
        with open(path + ".tmp", "w") as f:
            f.writelines(rows)
        os.replace(path + ".tmp", path)


CLAIM_MINS = 45  # how long after a Free Download click a new file in Downloads may count as that track
CLAIMS, WHY = ".inbox-claims.json", ".inbox-why.json"


def load_json(d, name):
    try:
        with open(os.path.join(d, name)) as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(d, name, v):
    path = os.path.join(d, name)
    with open(path + ".tmp", "w") as f:
        json.dump(v, f)
    os.replace(path + ".tmp", path)


def claims(d):
    """{link: when} for the Free Download links clicked in the last CLAIM_MINS minutes."""
    now = time.time()
    return {k: t for k, t in load_json(d, CLAIMS).items()
            if isinstance(t, (int, float)) and now - t < CLAIM_MINS * 60}


def claim(d, link):
    """The Free Download link was just clicked: the next file to land in Downloads may be this track."""
    with locked(d, ".inbox-claims.lock"):
        c = claims(d)
        c[link] = time.time()
        save_json(d, CLAIMS, c)


def inbox(d, out, folder=os.path.expanduser("~/Downloads"), days=30):
    """inbox_() with one pickup at a time (the sync and the app both call it)."""
    with locked(d, ".inbox.lock"):
        return inbox_(d, out, folder, days)


def inbox_(d, out, folder, days):
    """Takes still-to-get tracks you downloaded by hand (a Hypeddit or Laylo gate, a Bandcamp purchase, any
    link) out of Downloads: the song's title (whole words) and its artist must be in the file's name, and when
    SoundCloud gave a length, within 5 s of it, or longer when the full title with its version is there (an extended
    or DJ intro cut; a SoundCloud preview's length is not used). Top quality only, through the safety check. A zip
    is opened, and goes to the Trash once nothing else on the list is in it.
    Right after a Free Download click (claim()), a file that lands in Downloads counts as that track whatever its
    name, when its length is within 2 s of SoundCloud's; when its name also shares a telling word with the song, it's
    trusted like a named file (an extended cut is fine). Just clicked and named with the full title and version, a
    shorter cut is taken too (the artist's own free version; at least 90 s, never a clip). Why a file wasn't kept goes to .inbox-why.json for the
    page."""
    try:
        with open(os.path.join(d, "to-buy.tsv")) as f:
            rows = [(l.rstrip("\n").split("\t") + ["", "", "", ""])[:4] for l in f if l.strip()]
    except OSError:
        return []
    # A clip or preview on SoundCloud: its length says nothing about the full download (as in soulseek.py)
    rows = [r[:3] + [""] if CUT.search(r[0]) else r for r in rows if len(song_key(r[0])[0]) >= 3]
    if not rows:
        return []
    seen_path = os.path.join(d, "inbox-seen.txt")
    try:
        with open(seen_path) as f:
            seen = {l.rstrip("\n") for l in f}
    except OSError:
        seen = set()
    now, files = time.time(), []
    try:
        for root, dirs, names in os.walk(folder):
            dirs[:] = [x for x in dirs if not x.startswith(".") and root == folder]  # Downloads and one level in
            for n in names:
                p = os.path.join(root, n)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if (n.lower().endswith(AUDIO_EXT + (".zip",)) and not n.startswith(".") and stat.S_ISREG(st.st_mode)
                        and 10 < now - st.st_mtime < days * 86400):
                    files.append((p, st.st_size, st.st_mtime))
    except OSError:  # no permission to read Downloads (the Crate Helper switch is off)
        return []
    clicked = claims(d)
    why = {}  # link: why the file that came in for it wasn't kept
    turned = {}  # link: the file turned away for its length only (the page offers "Use this file", take())
    got, new_seen = [], []
    for p, size, mtime in files:
        base = words(os.path.splitext(os.path.basename(p))[0])
        texts = [base]  # a zip: its name with each track's name (an album zip is often only "Artist - Album")
        if p.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(p) as z:
                    texts = [base + words(os.path.splitext(m)[0]) for m in z.namelist() if m.lower().endswith(AUDIO_EXT)]
            except (OSError, zipfile.BadZipFile):
                continue

        def fits(row, full=False):
            short, whole, who = wanted(row[0])
            return any(has(x, whole if full else short) and (not who or any(has(x, w) for w in who)) for x in texts)
        # The title as whole words AND the artist (or uploader) in the same name; the most specific title wins
        # ("Intro" never takes "Intro (VIP)"). Without a length from SoundCloud, the full title with its version.
        cands = sorted((r for r in rows if fits(r) and (r[3] or fits(r, True))), key=lambda r: -len(wanted(r[0])[1]))
        # Just clicked: a single file (not a zip) that came in after the click, if SoundCloud gave a length to check.
        named = {r[1] for r in cands}
        whole = {r[1] for r in cands if fits(r, True)}  # the full title with its version: a longer cut is fine
        hinted = set()
        if not p.lower().endswith(".zip"):
            cands += [r for r in rows if r[1] in clicked and r[3] and r[1] not in named and mtime >= clicked[r[1]] - 5]
            # Just clicked and the name points at the song too (a short name like "Everybody (Zach Knows Edit)"):
            # trusted like a named file, so an extended cut is taken.
            hinted = {r[1] for r in cands if r[1] not in named and hint(r[0], texts)}
        # Looked at once for these tracks; looked at again if the file changes or other tracks match it
        # (another song from a kept album zip added to the playlist).
        key = f"{p}\t{size}\t{' '.join(sorted(r[1] for r in cands))}"
        if not cands or key in seen:
            continue
        took = len(got)
        for row in cands:
            name, link, _, secs = row
            with tempfile.TemporaryDirectory(dir=d, prefix=".inbox-") as tmpdir:  # outside the music folder
                tmp = os.path.join(tmpdir, "download" + (".zip" if p.lower().endswith(".zip") else ""))
                shutil.copyfile(p, tmp)
                path, i = best_audio(tmp, name, secs)
                # Matched only by the click (any name): the length must agree closely (2 s), not just roughly. Named
                # with its full title and version: within 5 s, or longer (an extended or DJ intro cut of the same
                # song, up to 4 minutes more); never shorter (a preview or radio edit).
                off = i["secs"] - float(secs) if i and secs else 0
                sure = link in named or link in hinted
                fits_len = abs(off) <= (5 if sure else 2) or ((link in whole or link in hinted) and 0 < off <= 240)
                # From the song's own gate (just clicked) and named with its full title and version: the artist's own
                # free cut, even when SoundCloud's upload is longer (a mashup or an extended upload). Not a clip.
                fits_len = fits_len or bool(i and link in whole and link in clicked and mtime >= clicked[link] - 5
                                            and i["secs"] >= 90)
                if not path:
                    if i and (link in named or fits_len):
                        print(f"in Downloads but only {i['kbps']} kbps, not kept: {os.path.basename(p)}")
                        why[link] = (f"The file you downloaded ({os.path.basename(p)}) is only {i['kbps']} kbps, so it "
                                     "wasn't kept. Look for a WAV, FLAC or 320 kbps option on the page.")
                        break
                    continue  # not audio, or no track of this name in the zip
                if not fits_len:
                    if link in named:  # the name says it's this song, the length says another (shorter) version
                        why[link] = (f"{os.path.basename(p)} is {mmss(i['secs'])} long, not {mmss(float(secs))}: "
                                     "another version of the song, so it wasn't kept.")
                        turned[link] = p
                    elif i and len(cands) == 1:  # came in just after the click, but its length is another song's
                        why.setdefault(link, f"{os.path.basename(p)} came in after the click but is {mmss(i['secs'])} "
                                             f"long, not {mmss(float(secs))}, so it wasn't taken as this song.")
                        turned.setdefault(link, p)
                    continue  # another version of the song (or, just after a click, another file)
                staged = os.path.join(tmpdir, f"track.{i['ext']}")
                os.replace(path, staged)
                blocked = safety.vet(d, staged)
                if blocked:
                    print(f"in Downloads but BLOCKED by the safety check ({blocked}), not kept: {os.path.basename(p)}")
                    why[link] = f"The safety check stopped {os.path.basename(p)} ({blocked}), so it wasn't kept."
                    break
                dest = file_name(out, name, i["ext"], "download")
                shutil.move(staged, dest)
            if not p.lower().endswith(".zip"):
                os.remove(p)  # moved into the music folder
            got.append((link, name, dest))
            rows.remove(row)
            print(f"from Downloads: {os.path.basename(dest)} ({'lossless' if i['lossless'] else str(i['kbps']) + ' kbps'})")
            if not os.path.exists(p):
                break  # a zip (an album) can hold more than one track still to get
        if len(got) > took and p.lower().endswith(".zip") and os.path.exists(p):
            # Tidy Downloads: a zip a track came from goes to the Trash (recoverable) once nothing else on the
            # list is in it.
            if not any(r in rows for r in cands):
                trash(p)
                continue
        if os.path.exists(p):
            new_seen.append(key)
    if new_seen:
        with open(seen_path, "a") as f:
            f.writelines(x + "\n" for x in new_seen)
    record(d, got)
    if got and clicked:  # picked up: stop watching for these
        with locked(d, ".inbox-claims.lock"):
            save_json(d, CLAIMS, {k: t for k, t in claims(d).items() if k not in {g[0] for g in got}})
    note_why(d, why, {g[0] for g in got} | ({k for k in clicked} - {r[1] for r in rows}), turned)
    if got:
        safety.check(d, out)
    return got


def take(d, out, link, folder=os.path.expanduser("~/Downloads")):
    """"Use this file": you (or Claude or Codex) say the file turned away for its length IS this song (SoundCloud's
    upload is a mashup, a preview or another cut). Still top quality only and through the safety check. Returns
    [(link, name, file)] once kept, else the reason it can't be."""
    with locked(d, ".inbox.lock"):
        p = (load_json(d, WHY).get(link) or {}).get("file", "")
        row = next((r for r in ((l.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
                                for l in open(os.path.join(d, "to-buy.tsv")) if l.strip()) if r[1] == link), None)
        real = os.path.realpath(p) if p else ""
        if not row or not real.startswith(os.path.realpath(folder) + os.sep) or not os.path.isfile(real):
            return "That file isn't in Downloads any more, or the song is no longer on the list."
        name = row[0]
        with tempfile.TemporaryDirectory(dir=d, prefix=".inbox-") as tmpdir:
            tmp = os.path.join(tmpdir, "download" + (".zip" if real.lower().endswith(".zip") else ""))
            shutil.copyfile(real, tmp)
            path, i = best_audio(tmp, name, row[3])
            if not path:
                return "That file isn't top quality (WAV, FLAC, AIFF or a 320 kbps MP3), so it can't be used."
            staged = os.path.join(tmpdir, f"track.{i['ext']}")
            os.replace(path, staged)
            blocked = safety.vet(d, staged)
            if blocked:
                return f"The safety check stopped that file ({blocked})."
            dest = file_name(out, name, i["ext"], "download")
            shutil.move(staged, dest)
        if real.lower().endswith(".zip"):
            trash(real)
        else:
            os.remove(real)  # moved into the music folder
        got = [(link, name, dest)]
        record(d, got)
        note_why(d, {}, {link})
        with locked(d, ".inbox-claims.lock"):
            save_json(d, CLAIMS, {k: t for k, t in claims(d).items() if k != link})
        safety.check(d, out)
        return got


def trash(p):
    """Moves a file to the Trash (it can be put back), never deleting it."""
    t = os.path.expanduser("~/.Trash")
    base, ext = os.path.splitext(os.path.basename(p))
    dest, k = os.path.join(t, base + ext), 1
    while os.path.exists(dest):
        dest, k = os.path.join(t, f"{base} {k}{ext}"), k + 1
    try:
        shutil.move(p, dest)
    except OSError:
        pass


def mmss(secs):
    return f"{int(secs) // 60}:{int(secs) % 60:02d}"


def note_why(d, new, gone, files=None):
    """Keeps a day of 'why it wasn't kept' notes for the page, dropping tracks that are now on the Mac. A file turned
    away only for its length is kept with its note, for the page's "Use this file" (take())."""
    old, now = load_json(d, WHY), time.time()
    keep = {k: v for k, v in old.items() if k not in gone and k not in new and isinstance(v, dict)
            and now - v.get("at", 0) < 86400}
    keep.update({k: {"at": now, "text": t, **({"file": files[k]} if k in (files or {}) else {})}
                 for k, t in new.items() if k not in gone})
    if keep != old:
        save_json(d, WHY, keep)


def main(d, out):
    rows, kept, got = [], [], []
    try:
        with open(os.path.join(d, "to-buy.tsv")) as f:
            rows = [(l.rstrip("\n").split("\t") + ["", "", ""])[:4] for l in f if l.strip()]
    except OSError:
        return
    tried_path = os.path.join(d, "free-tried.txt")
    try:
        with open(tried_path) as f:
            tried = {l.strip() for l in f}
    except OSError:
        tried = set()
    for row in rows:
        name, link, free, _ = row
        url = free and free not in tried and direct(free)
        if not url:
            kept.append(row)
            continue
        with tempfile.TemporaryDirectory(dir=d, prefix=".free-") as tmpdir:  # outside the music folder
            tmp = os.path.join(tmpdir, "download")
            try:
                fetch(url, tmp)
            except Exception as e:  # network trouble: try again next sync
                print(f"free download failed, will retry: {name}: {e}")
                kept.append(row)
                continue
            path, i = best_audio(tmp, name, row[3])
            if not path:
                why = f"only {i['kbps']} kbps" if i else "no audio in it"
                print(f"free download skipped ({why}), not top quality: {name}")
                with open(tried_path, "a") as f:
                    f.write(free + "\n")
                kept.append(row)
                continue
            staged = os.path.join(tmpdir, f"track.{i['ext']}")
            os.replace(path, staged)
            blocked = safety.vet(d, staged)
            if blocked:  # never kept: the link isn't tried again, and the track stays on the list for Soulseek
                print(f"free download BLOCKED by the safety check ({blocked}): {name}")
                with open(tried_path, "a") as f:
                    f.write(free + "\n")
                kept.append(row)
                continue
            dest = file_name(out, name, i["ext"], "free download")
            shutil.move(staged, dest)
            got.append((link, name, dest))
            print(f"free download: {os.path.basename(dest)} ({'lossless' if i['lossless'] else str(i['kbps']) + ' kbps'})")
    record(d, got)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "inbox":
        inbox(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
