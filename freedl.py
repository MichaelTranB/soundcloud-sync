#!/usr/bin/env python3
"""Fetches the artist's own free download when their SoundCloud description links straight to a file host.

  freedl.py DIR OUT   reads DIR/to-buy.tsv, downloads what it can into OUT, records it in DIR/free.tsv
                      (link, name, file) and takes it off DIR/to-buy.tsv

Hosts with a plain download URL: Dropbox, Google Drive, pixeldrain, and a direct link to an audio or zip file.
Download gates (Hypeddit, ToneDen and the like), Bandcamp and hosts that need a browser (Mega, WeTransfer,
Mediafire) stay one click on the page. Only top quality is kept: lossless, or MP3/AAC at 320 kbps. A zip is
opened and only its audio is taken. A link that gave a non-audio or low-quality file is not tried again.
"""
import os, re, sys, tempfile, urllib.parse, urllib.request, zipfile
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


def best_audio(tmp, title):
    """The downloaded file itself, or from a zip the top-quality track whose name matches the title best."""
    if not zipfile.is_zipfile(tmp):
        i = info(tmp)
        return (tmp, i) if top_quality(i) else (None, i)
    picks, key = [], norm(re.sub(r"[(\[][^)\]]*[)\]]", "", title)) or norm(title)
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
                picks.append((key in norm(base), i["lossless"], out, i))
    # One track: it's the download. Several: only one whose file name carries the title, never a guess.
    if len(picks) > 1:
        picks = [p for p in picks if p[0]]
    if not picks:
        return None, None
    _, _, path, i = max(picks, key=lambda p: p[:2])
    return path, i


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
        with tempfile.TemporaryDirectory(dir=out, prefix=".free-") as tmpdir:
            tmp = os.path.join(tmpdir, "download")
            try:
                fetch(url, tmp)
            except Exception as e:  # network trouble: try again next sync
                print(f"free download failed, will retry: {name}: {e}")
                kept.append(row)
                continue
            path, i = best_audio(tmp, name.partition(" - ")[2] or name)
            if not path:
                why = f"only {i['kbps']} kbps" if i else "no audio in it"
                print(f"free download skipped ({why}), not top quality: {name}")
                with open(tried_path, "a") as f:
                    f.write(free + "\n")
                kept.append(row)
                continue
            safe = re.sub(r'[/:\x00-\x1f]', "-", name).strip(". ")[:200]
            dest = os.path.join(out, f"{safe}.{i['ext']}")
            if os.path.exists(dest):
                dest = os.path.join(out, f"{safe} (free download).{i['ext']}")
            os.replace(path, dest)
            got.append((link, name, dest))
            print(f"free download: {os.path.basename(dest)} ({'lossless' if i['lossless'] else str(i['kbps']) + ' kbps'})")
    if got:
        with open(os.path.join(d, "free.tsv"), "a") as f:
            f.writelines("\t".join(g) + "\n" for g in got)
        tmp = os.path.join(d, "to-buy.tsv.tmp")
        with open(tmp, "w") as f:
            f.writelines("\t".join(r) + "\n" for r in kept)
        os.replace(tmp, os.path.join(d, "to-buy.tsv"))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
