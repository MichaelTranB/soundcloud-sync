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
import os, re, shutil, stat, sys, tempfile, time, urllib.parse, urllib.request, zipfile
import safety
from soulseek import CUT, split
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


def best_audio(tmp, name):
    """The downloaded file itself, or from a zip the top-quality track whose file name carries the song's title
    as whole words (the same matching the Downloads pickup uses); the full title with its version first."""
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
                picks.append((has(b, short), has(b, full), i["lossless"], out, i))
    # One track: it's the download. Several: only one whose file name carries the title, never a guess.
    if len(picks) > 1:
        picks = [p for p in picks if p[0]]
    if not picks:
        return None, None
    *_, path, i = max(picks, key=lambda p: p[:3])
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
    with open(path) as f:
        rows = [l for l in f if l.split("\t")[0] not in done]
    with open(path + ".tmp", "w") as f:
        f.writelines(rows)
    os.replace(path + ".tmp", path)


def inbox(d, out, folder=os.path.expanduser("~/Downloads"), days=30):
    """Takes still-to-get tracks you downloaded by hand (a Hypeddit or Laylo gate, a Bandcamp purchase, any
    link) out of Downloads: the song's title (whole words) and its artist must be in the file's name, and when
    SoundCloud gave a length, within 5 s of it (same version; a SoundCloud preview's length is not used). Top quality only, through the safety check. A zip is opened and stays."""
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
                    files.append((p, st.st_size))
    except OSError:  # no permission to read Downloads (the Crate Helper switch is off)
        return []
    got, new_seen = [], []
    for p, size in files:
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
        # Looked at once for these tracks; looked at again if the file changes or other tracks match it
        # (another song from a kept album zip added to the playlist).
        key = f"{p}\t{size}\t{' '.join(sorted(r[1] for r in cands))}"
        if not cands or key in seen:
            continue
        for row in cands:
            name, link, _, secs = row
            with tempfile.TemporaryDirectory(dir=d, prefix=".inbox-") as tmpdir:  # outside the music folder
                tmp = os.path.join(tmpdir, "download" + (".zip" if p.lower().endswith(".zip") else ""))
                shutil.copyfile(p, tmp)
                path, i = best_audio(tmp, name)
                if not path:
                    if i:
                        print(f"in Downloads but only {i['kbps']} kbps, not kept: {os.path.basename(p)}")
                        break
                    continue  # not audio, or no track of this name in the zip
                if secs and abs(i["secs"] - float(secs)) > 5:
                    continue  # another version of the song
                staged = os.path.join(tmpdir, f"track.{i['ext']}")
                os.replace(path, staged)
                blocked = safety.vet(d, staged)
                if blocked:
                    print(f"in Downloads but BLOCKED by the safety check ({blocked}), not kept: {os.path.basename(p)}")
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
        if os.path.exists(p):
            new_seen.append(key)
    if new_seen:
        with open(seen_path, "a") as f:
            f.writelines(x + "\n" for x in new_seen)
    record(d, got)
    if got:
        safety.check(d, out)
    return got


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
            path, i = best_audio(tmp, name)
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
