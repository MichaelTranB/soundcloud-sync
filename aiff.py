#!/usr/bin/env python3
"""Turns FLAC songs into AIFF: the very same sound, in a kind of file every deck plays (older club decks skip
FLAC). Unlike WAV, an AIFF keeps the song's details and cover.

  how      macOS's own converter (afconvert) writes the AIFF, the details and cover are copied across, and the sound
           in the new file is then compared with the old one, sample for sample (the FLAC's own checksum);
  clean    the AIFF passes the safety check like any new file, and only then does the original go to the Trash
           (never deleted). No song is ever there twice;
  follows  every note kept per file goes along (where it came from, tempo and key, playlists copied from another
           USB), and dj.py points the decks' lists at the AIFF, so cues, loops and grids stay with the song. On the
           USB the old file goes to the USB's own Trash and the AIFF takes its place (usb_tidy.py, usb.sh);
  when     FLACs that arrive from now on are converted by themselves at each deck update (dj.py). The ones already
           there the first time wait for your pick on the page, and so do WAVs (they play everywhere; an AIFF only
           adds details and cover);
  32-bit   no club deck plays a 32-bit file (24-bit is the most), so one is never converted by itself: "Make a
           24-bit copy" on its row writes a 24-bit AIFF (each sample's lowest 8 bits are dropped: far below
           anything you can hear), checked against the original, which goes to the Trash like any other. A 32-bit
           FLAC is beyond macOS's own reader: that one needs ffmpeg on the Mac.

  aiff.py auto DIR SRC     the new FLACs (dj.py runs this)
  aiff.py pick DIR SRC     the songs named on stdin (a JSON list of names inside the music folder), then the decks
  aiff.py deep DIR SRC     the same, and a 32-bit song among them gets its 24-bit copy
  aiff.py undo DIR SRC     the same, back: the original returns from the Trash and the AIFF goes there

The details need mutagen (the DJ tools' own Python, dj-setup.sh); everything else is the standard library."""
import fcntl, hashlib, json, os, shutil, struct, subprocess, sys, time

import friend, soulseek, usb_tidy

REC, DONE, TMP, PROGRESS = "aiff.json", "dj-converted.tsv", ".aiff-tmp", ".aiff-progress"
KINDS = (".flac", ".wav")
# A FLAC's named details as an AIFF keeps them (ID3 frames); any other is kept under its own name (TXXX).
FRAMES = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2", "album artist": "TPE2",
          "genre": "TCON", "date": "TDRC", "year": "TDRC", "bpm": "TBPM", "tbpm": "TBPM", "initialkey": "TKEY",
          "initial key": "TKEY", "key": "TKEY", "label": "TPUB", "organization": "TPUB", "publisher": "TPUB",
          "isrc": "TSRC", "remixer": "TPE4", "mixartist": "TPE4", "composer": "TCOM", "copyright": "TCOP",
          "grouping": "TIT1"}
INFO = {b"INAM": "TIT2", b"IART": "TPE1", b"IPRD": "TALB", b"IGNR": "TCON", b"ICRD": "TDRC"}  # a WAV's older notes


class Problem(Exception):
    """Why one song was left as it is. lasting: it will be the same next time, so it isn't tried at every run."""
    def __init__(self, text, lasting=False):
        super().__init__(text)
        self.lasting = lasting


def load(dir):
    try:
        with open(os.path.join(dir, REC)) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        rec = {}
    rec = rec if isinstance(rec, dict) else {}
    return {"auto": rec.get("auto", True) is not False, "before": rec.get("before"), "skip": rec.get("skip") or {}}


def save(dir, rec):
    with open(os.path.join(dir, REC + ".tmp"), "w") as f:
        json.dump(rec, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(os.path.join(dir, REC + ".tmp"), os.path.join(dir, REC))


def rows(dir):
    """Each conversion and each undo, oldest first: [the name before, the name now, where the other went, day]."""
    try:
        with open(os.path.join(dir, DONE), encoding="utf-8", errors="replace") as f:
            return [(l.rstrip("\n").split("\t") + ["", ""])[:4] for l in f if l.count("\t") >= 2]
    except OSError:
        return []


def history(dir):
    """Each song's last conversion: {its name now: (its name before, where the other file went)}. A song moved or
    renamed since (into the Liked Songs folder, or a sign a USB can't hold swapped by usbsafe) is followed there."""
    last = {}
    for old, new, to, _ in rows(dir):
        last[new] = (old, to)
        last.pop(old, None)
    for old, new in usb_tidy.rows(dir, usb_tidy.MOVES):
        if old in last and new not in last:
            last[new] = last.pop(old)
    return last


def undoable(dir):
    """AIFFs whose original is still in the Trash: {the AIFF: where its original is}."""
    return {new: to for new, (old, to) in history(dir).items()
            if new.lower().endswith(".aiff") and old.lower().endswith(KINDS) and to and os.path.isfile(to)}


# ---- reading the three kinds of file: what the sound is, and where its samples sit

def flac_info(path):
    with open(path, "rb") as f:
        head = f.read(10)
        f.seek(10 + ((head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]) if head[:3] == b"ID3" else 0)
        b = f.read(42)
    if b[:4] != b"fLaC" or len(b) < 42 or b[4] & 0x7F:
        raise Problem("it isn't a FLAC inside", True)
    x = int.from_bytes(b[18:26], "big")
    return {"rate": x >> 44, "channels": ((x >> 41) & 7) + 1, "bits": ((x >> 36) & 31) + 1,
            "frames": x & ((1 << 36) - 1), "md5": b[26:42].hex()}


def wav_info(path, loose=False):
    """loose: a floating-point WAV is read too (its "pcm" is False, "float" True) instead of being a Problem."""
    out, notes, size = None, {}, os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:] != b"WAVE":
            raise Problem("it isn't a WAV inside", True)
        while True:
            h = f.read(8)
            if len(h) < 8:
                break
            name, n = h[:4], struct.unpack("<I", h[4:])[0]
            if name == b"fmt ":
                d = f.read(n + (n & 1))
                kind, channels, rate, _, _, bits = struct.unpack("<HHIIHH", d[:16])
                if kind == 0xFFFE and len(d) >= 26:  # the long form: the real kind and bit count sit further on
                    kind = struct.unpack("<H", d[24:26])[0] if struct.unpack("<H", d[18:20])[0] == bits else 0
                out = {"rate": rate, "channels": channels, "bits": bits, "pcm": kind == 1, "float": kind == 3}
            elif name == b"data":
                start = f.tell()
                n = min(n, size - start)  # some writers leave the size open
                if out:
                    out.update(start=start, frames=n // max(1, out["channels"] * out["bits"] // 8))
                f.seek(n + (n & 1), 1)
            elif name == b"LIST" and n < 1 << 20:
                d = f.read(n + (n & 1))
                at = 4 if d[:4] == b"INFO" else len(d)
                while at + 8 <= len(d):
                    k, m = d[at:at + 4], struct.unpack("<I", d[at + 4:at + 8])[0]
                    notes[k] = d[at + 8:at + 8 + m].split(b"\0")[0].decode("utf-8", "replace").strip()
                    at += 8 + m + (m & 1)
            else:
                f.seek(n + (n & 1), 1)
    if not out or "start" not in out:
        raise Problem("it has no sound inside", True)
    if not out["pcm"] and not (loose and out["float"]):
        raise Problem("it is a floating-point or packed WAV: left as it is", True)
    return {**out, "info": notes}


def aiff_info(path):
    out, at = {}, None
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"FORM" or head[8:] not in (b"AIFF", b"AIFC"):
            raise Problem("it isn't an AIFF inside", True)
        while True:
            h = f.read(8)
            if len(h) < 8:
                break
            name, n = h[:4], struct.unpack(">I", h[4:])[0]
            if name == b"COMM":
                d = f.read(n + (n & 1))
                channels, frames, bits = struct.unpack(">hLh", d[:8])
                rate = int.from_bytes(d[10:18], "big") * 2.0 ** ((((d[8] & 0x7F) << 8) | d[9]) - 16383 - 63)
                packed = d[18:22] if head[8:] == b"AIFC" else b"NONE"
                out = {"rate": int(round(rate)), "channels": channels, "bits": bits, "frames": frames,
                       "pcm": packed in (b"NONE", b"twos", b"sowt"), "little": packed == b"sowt"}
            elif name == b"SSND":
                at = f.tell() + 8 + struct.unpack(">I", f.read(4))[0]
                f.seek(n - 4 + (n & 1), 1)
            else:
                f.seek(n + (n & 1), 1)
    if not out or at is None or not out["pcm"]:
        raise Problem("it has no plain sound inside", True)
    return {**out, "start": at}


def samples_md5(path, start, size, width, swap):
    """The checksum of the samples as a FLAC counts them (low byte first)."""
    m, left = hashlib.md5(), size
    with open(path, "rb") as f:
        f.seek(start)
        while left > 0:
            b = f.read(min(width * 262144, left))
            if not b:
                break
            left -= len(b)
            if swap and width > 1:
                b = b[:len(b) - len(b) % width]
                turned = bytearray(len(b))
                for i in range(width):
                    turned[i::width] = b[width - 1 - i::width]
                b = turned
            m.update(b)
    return m.hexdigest() if not left else ""


def sound(path):
    """What a song's sound is: (rate, channels, bits, frames, checksum of its samples)."""
    ext = os.path.splitext(path)[1].lower()
    i = flac_info(path) if ext == ".flac" else wav_info(path) if ext == ".wav" else aiff_info(path)
    width = i["bits"] // 8
    if ext == ".flac":
        md5 = i["md5"] if i["md5"].strip("0") else ""
    else:
        md5 = samples_md5(path, i["start"], i["frames"] * i["channels"] * width, width, ext != ".wav" and not i["little"])
    return i["rate"], i["channels"], i["bits"], i["frames"], md5


# ---- one song

def details(src, out, info):
    """The song's details and cover, copied into the AIFF."""
    from mutagen import id3
    from mutagen.aiff import AIFF
    a = AIFF(out)
    if a.tags is None:
        a.add_tags()
    t = a.tags
    if src.lower().endswith(".flac"):
        from mutagen.flac import FLAC
        f = FLAC(src)
        got = {k.lower(): [v for v in vs if v] for k, vs in (f.tags.as_dict() if f.tags else {}).items()}
        for name, values in got.items():
            if not values:
                continue
            frame = FRAMES.get(name)
            if frame and frame not in t:
                t.add(getattr(id3, frame)(encoding=3, text=values))
            elif name in ("comment", "description") and not t.getall("COMM"):
                t.add(id3.COMM(encoding=3, lang="eng", desc="", text=values))
            elif name in ("lyrics", "unsyncedlyrics") and not t.getall("USLT"):
                t.add(id3.USLT(encoding=3, lang="eng", desc="", text="\n".join(values)))
            elif name in ("tracknumber", "discnumber"):
                total = (got.get(name[:5] + "total") or got.get("total" + name[:5] + "s") or [""])[0]
                t.add((id3.TRCK if name[0] == "t" else id3.TPOS)(encoding=3, text=values[0] + ("/" + total if total and "/" not in values[0] else "")))
            elif not frame and name not in ("tracktotal", "totaltracks", "disctotal", "totaldiscs"):
                t.add(id3.TXXX(encoding=3, desc=name.upper(), text=values))
        for n, p in enumerate(f.pictures):
            t.add(id3.APIC(encoding=3, mime=p.mime or "image/jpeg", type=p.type, desc=(p.desc or "") + ("" if not n else f" {n + 1}"), data=p.data))
    else:
        from mutagen.wave import WAVE
        try:
            for frame in (WAVE(src).tags or {}).values():
                t.add(frame)
        except Exception:
            pass
        for k, frame in INFO.items():
            if info.get("info", {}).get(k) and frame not in t:
                t.add(getattr(id3, frame)(encoding=3, text=[info["info"][k]]))
        if info.get("info", {}).get(b"ICMT") and not t.getall("COMM"):
            t.add(id3.COMM(encoding=3, lang="eng", desc="", text=[info["info"][b"ICMT"]]))
    a.save(v2_version=3)  # the older spelling: every deck and DJ program reads it


def ffmpeg():
    """ffmpeg, when this Mac has it (The Crate doesn't bring its own): the one reader of a 32-bit FLAC."""
    return shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
                                                       os.path.expanduser("~/.local/bin/ffmpeg")) if os.path.exists(p)), "")


def deep(info):
    """Finer than any club deck plays (above 24-bit, or floating-point): it needs a 24-bit copy, not the same sound."""
    return info["bits"] > 24 or info.get("float", False)


def read32(path, info):
    """The song's samples at 32 bits each (low byte first), a piece at a time."""
    if info.get("pcm") and info["bits"] == 32:  # a plain 32-bit WAV: its samples as they sit in the file
        left = info["frames"] * info["channels"] * 4
        with open(path, "rb") as f:
            f.seek(info["start"])
            while left > 0:
                b = f.read(min(1 << 20, left))
                if not b:
                    break
                left -= len(b)
                yield b
        return
    ff = ffmpeg()
    if not ff:
        raise Problem("this Mac needs ffmpeg to read it (a 32-bit FLAC is beyond macOS's own reader)")
    p = subprocess.Popen([ff, "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0", "-f", "s32le", "-c:a", "pcm_s32le", "-"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            b = p.stdout.read(1 << 20)
            if not b:
                break
            yield b
        if p.wait():
            raise Problem("ffmpeg couldn't read it to its end: the original stays")
    finally:
        p.stdout.close()
        if p.poll() is None:
            p.kill()
            p.wait()


def narrow(path, info, out=None):
    """The song at 24-bit: the top 24 bits of each 32-bit sample, written as an AIFF at out (only read, without out).
    Returns (frames, the checksum of those 24-bit samples as sound() counts them, the checksum of the 32-bit ones)."""
    full, cut, n, f = hashlib.md5(), hashlib.md5(), 0, open(out, "wb") if out else None
    try:
        if f:
            f.write(b"\0" * 54)  # the head, filled in once the length is known
        for b in read32(path, info):
            b = b[:len(b) - len(b) % 4]
            k = len(b) // 4
            full.update(b)
            low = bytearray(3 * k)  # low byte first, as a FLAC counts its checksum
            low[0::3], low[1::3], low[2::3] = b[1::4], b[2::4], b[3::4]
            cut.update(low)
            if f:
                low[0::3], low[2::3] = b[3::4], b[1::4]  # high byte first, as an AIFF holds them
                f.write(low)
            n += k
        if f:
            size, rate = 3 * n, int(info["rate"])
            if size + 54 >= 1 << 32:
                raise Problem("it is too long for an AIFF", True)
            f.write(b"\0" * (size & 1))
            f.seek(0)
            f.write(b"FORM" + struct.pack(">I", 46 + size + (size & 1)) + b"AIFFCOMM"
                    + struct.pack(">IhLh", 18, info["channels"], n // info["channels"], 24)
                    + struct.pack(">HQ", 16383 + rate.bit_length() - 1, rate << (64 - rate.bit_length()))
                    + b"SSND" + struct.pack(">III", size + 8, 0, 0))
    finally:
        if f:
            f.close()
    return n // info["channels"], cut.hexdigest(), full.hexdigest()


def convert(path, out, tmp, cut=False):
    """Writes path's AIFF at out. Raises Problem, leaving nothing behind, unless the sound in it is the very same
    (cut: a 32-bit song's is its top 24 bits, checked as closely). True when it was cut to 24-bit."""
    ext = os.path.splitext(path)[1].lower()
    info = flac_info(path) if ext == ".flac" else wav_info(path, cut)
    if info["channels"] > 2 or not info["rate"]:
        raise Problem(f"{info['channels']} channels: not a kind decks play as AIFF", True)
    if deep(info):
        if info["rate"] > 96000:  # a 24-bit copy at that rate still plays on no deck: left as it is
            raise Problem("32-bit and above 96 kHz: no club deck plays it", True)
        if not cut:
            raise Problem('32-bit: no club deck plays it. "Make a 24-bit copy" on its row does it', True)
        try:
            frames, small, full = narrow(path, info, out)
            if not frames or (info.get("frames") and frames != info["frames"]) or \
                    (info.get("md5", "").strip("0") and full != info["md5"]):
                raise Problem("it didn't read back as the file says it should: the original stays")
            details(path, out, info)
            if sound(out) != (info["rate"], info["channels"], 24, frames, small):
                raise Problem("the 24-bit copy didn't come out right: the original stays")
            st = os.stat(path)
            os.utime(out, (st.st_atime, st.st_mtime))
        except BaseException:
            if os.path.exists(out):
                os.remove(out)
            raise
        return True
    if info["bits"] not in (16, 24):
        raise Problem(f"{info['bits']}-bit: not a kind decks play as AIFF", True)
    try:
        r = subprocess.run(["/usr/bin/afconvert", "-f", "AIFF", "-d", f"BEI{info['bits']}", path, out],
                           capture_output=True, text=True)
        if r.returncode or not os.path.isfile(out):
            raise Problem("the converter couldn't read it" + (": " + r.stderr.strip().splitlines()[-1][:120] if r.stderr.strip() else ""), True)
        details(path, out, info)
        was, now = sound(path), sound(out)
        if not was[4]:  # a FLAC without its checksum: read once more, another way, and compare that
            again = os.path.join(tmp, f"{os.getpid()}-again.wav")
            try:
                subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", f"LEI{info['bits']}", path, again], capture_output=True)
                was = (*was[:3], was[3] or now[3], sound(again)[4])
            finally:
                if os.path.exists(again):
                    os.remove(again)
        if was != now or not now[4]:
            raise Problem("the AIFF didn't come out with the very same sound: the original stays")
        st = os.stat(path)
        os.utime(out, (st.st_atime, st.st_mtime))  # as old as the original: it keeps its place by date
    except BaseException:
        if os.path.exists(out):
            os.remove(out)
        raise


def trash(dir, path, why):
    """To the Trash under a name that says why (beside the app when the Trash can't be written). "" when it couldn't."""
    name, ext = os.path.splitext(os.path.basename(path))
    for folder in (os.path.expanduser("~/.Trash"), os.path.join(dir, "Thrown back")):
        try:
            os.makedirs(folder, exist_ok=True)
            now = time.time()
            to = os.path.join(folder, f"{name} ({why} {time.strftime('%Y-%m-%d %H%M%S', time.localtime(now))}"
                                      f".{int(now * 1000) % 1000:03d}){ext}")
            shutil.move(path, to)
            return to
        except OSError:
            continue
    return ""


def follow(dir, src, old, new):
    """Every note kept for the file under its old name now goes by the new one (names inside the music folder)."""
    a, b = os.path.join(src, old), os.path.join(src, new)
    at = lambda p: b if os.path.normpath(p) == os.path.normpath(a) else p
    try:
        st = os.stat(b)
    except OSError:
        return
    soulseek.save_got(dir, [[link, name, at(p)] for link, name, p in soulseek.load_got(dir)])
    came = soulseek.load_from(dir)
    if any(at(p) != p for p in came):
        soulseek.save_from(dir, {at(p): v for p, v in came.items()})
    seen = soulseek.load_checked(dir)
    if any(at(p) != p for p in seen):  # looked at once already: the same sound isn't looked at again
        soulseek.dump(dir, soulseek.CHECKED, {at(p): ([st.st_size, int(st.st_mtime), *v[2:]] if at(p) != p and isinstance(v, list) else v)
                                              for p, v in seen.items()})
    rec = friend.load(dir)
    if old in rec["songs"] or any(old in l.get("rels", []) for l in rec["lists"].values()):
        if old in rec["songs"]:
            rec["songs"][new] = rec["songs"].pop(old)  # its carried grid and cues still fit: the sound is the same
        for l in rec["lists"].values():
            l["rels"] = list(dict.fromkeys(new if r == old else r for r in l.get("rels", [])))
        friend.save(dir, rec)
    want = friend.wanted(dir)
    if any(w[6] == old for w in want):
        friend.save_wanted(dir, [[*w[:6], new if w[6] == old else w[6], *w[7:]] for w in want])
    try:  # tempo and key were heard from this very sound: kept, not listened to again
        with open(os.path.join(dir, "dj-analysis.json")) as f:
            cache = json.load(f)
        if old in cache:
            bits, heard = sound(b), cache.pop(old)
            cache[new] = {**heard, "size": st.st_size, "mtime": int(st.st_mtime),
                          "bitrate": int(round(bits[0] * bits[1] * bits[2] / 1000)) if b.lower().endswith(".aiff")
                          else int(round(st.st_size * 8 / max(1, heard.get("length") or 1) / 1000))}
            with open(os.path.join(dir, "dj-analysis.json.tmp"), "w") as f:
                json.dump(cache, f, ensure_ascii=False, indent=0, sort_keys=True)
            os.replace(os.path.join(dir, "dj-analysis.json.tmp"), os.path.join(dir, "dj-analysis.json"))
    except (OSError, ValueError, Problem):
        pass
    import details, naming
    details.moved(dir, old, new)  # a cover or details filled in before stay undoable
    naming.moved(dir, old, new)  # and so does a name that was fixed


def safe(dir, src):
    """The safety check, once, for the files just put in the folder; the names that passed."""
    with open(os.path.join(dir, "safety.log"), "a") as err:
        subprocess.run(["/usr/bin/python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "safety.py"),
                        "check", dir, src], stderr=err)
    return set(usb_tidy.checked(dir, src))


def note(dir, done, rels):
    with open(os.path.join(dir, PROGRESS + ".tmp"), "w") as f:
        f.write(f"{done}\t{len(rels)}\t{os.getpid()}")
    os.replace(os.path.join(dir, PROGRESS + ".tmp"), os.path.join(dir, PROGRESS))


def own(path, out, cut):
    """Is the AIFF at out this very song's (made on a run that was cut short)?"""
    b = sound(out)
    if cut is not None:
        info = flac_info(path) if path.lower().endswith(".flac") else wav_info(path, True)
        if deep(info):
            frames, small, _ = narrow(path, info)
            return b == (info["rate"], info["channels"], 24, frames, small)
    a = sound(path)
    return bool(a[4]) and a[4] == b[4] and a[:3] == b[:3]


def run(dir, src, rels, back=False, show=False, cut=None):
    """Converts each named song (back: undoes it). Returns (names done, {name: why not}); None when another run is
    at it. cut: a list (then a 32-bit song gets its 24-bit copy, and its new name is added to the list); without
    one, a 32-bit song is left as it is."""
    done, why, ready = [], {}, []
    tmp = os.path.join(dir, TMP)
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(dir, ".aiff.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        there, was = (undoable(dir), history(dir)) if back else ({}, {})
        for n, rel in enumerate(rels):
            if show:
                note(dir, n, rels)
            path = os.path.join(src, rel)
            try:
                if back:
                    old = was.get(rel, ("",))[0]  # (back beside the song, as it's called now, in its own kind)
                    old = old and os.path.splitext(rel)[0] + os.path.splitext(old)[1]
                    if rel not in there or not old:
                        raise Problem("its original is no longer in the Trash")
                    if os.path.lexists(os.path.join(src, old)):
                        raise Problem("a file with the original's name is in the folder")
                    shutil.move(there[rel], os.path.join(src, old))
                    ready.append((rel, old))
                    continue
                new = os.path.splitext(rel)[0] + ".aiff"
                out = os.path.join(src, new)
                if not rel.lower().endswith(KINDS) or not os.path.isfile(path):
                    continue
                if os.path.lexists(out):  # made on an earlier run that was cut short, or another song by that name
                    if not own(path, out, cut):
                        raise Problem("another file by that name is already an AIFF", True)
                else:
                    free = shutil.disk_usage(src).free
                    if free < 3 * os.path.getsize(path) + (2 << 30):
                        why[rel] = f"not enough room on this Mac ({free / 1e9:.0f} GB free): empty the Trash, then again"
                        break
                    made = os.path.join(tmp, f"{os.getpid()}-{n}.aiff")
                    if convert(path, made, tmp, cut is not None):
                        cut.append(new)
                    shutil.move(made, out)
                ready.append((rel, new))
            except Problem as e:
                why[rel] = str(e)
                if e.lasting and not back:
                    rec = load(dir)
                    rec["skip"][rel] = str(e)
                    save(dir, rec)
            except Exception as e:  # never silent, and never the end of the others
                why[rel] = f"{e!r}"[:160]
        if ready:
            ok = safe(dir, src)
            day = time.strftime("%Y-%m-%d")
            with soulseek.locked(dir):
                for rel, new in ready:
                    if new not in ok:
                        why[rel] = "the new file hasn't passed the safety check yet: both stay for now"
                        continue
                    to = trash(dir, os.path.join(src, rel), "undone" if back else "now AIFF")
                    if not to:
                        why[rel] = "its old file couldn't be moved to the Trash"
                        continue
                    with open(os.path.join(dir, DONE), "a", encoding="utf-8") as f:  # noted first: undo needs it
                        f.write(f"{rel}\t{new}\t{to}\t{day}\n")
                    done.append(new)
                    rec = load(dir)
                    if rec["skip"].pop(rel, None) is not None:  # left before (a 32-bit one), done now
                        save(dir, rec)
                    try:
                        follow(dir, src, rel, new)
                    except Exception as e:  # the song itself is fine; said, never silent
                        log(dir, f"AIFF PROBLEM: the notes for {new} didn't all follow ({e!r})"[:300])
            if back and done:  # brought back by you: it stays a FLAC until you pick it again
                rec = load(dir)
                rec["before"] = sorted(set(rec["before"] or []) | set(done))
                save(dir, rec)
    if show:
        try:
            os.remove(os.path.join(dir, PROGRESS))
        except OSError:
            pass
    return done, why


def waiting(dir, src):
    """The FLACs to convert by themselves now: the ones that arrived after the first look."""
    rec = load(dir)
    flacs = [r for r in usb_tidy.checked(dir, src) if r.lower().endswith(".flac")]
    if rec["before"] is None:  # the first look: what is already here is yours to pick on the page
        rec["before"] = flacs
        save(dir, rec)
        return []
    if not rec["auto"]:
        return []
    kept = set(rec["before"]) | set(rec["skip"])
    return [r for r in flacs if r not in kept]


def say(done, why, back=False, cut=()):
    """One line for dj.log; "" when nothing happened. cut: the ones among done that are 24-bit copies."""
    bits, s = [], lambda n: "s" if n != 1 else ""
    k = len([d for d in done if d in cut])
    n = len(done) - k
    if n:
        bits.append(f"{n} song{s(n)} back as {'it was' if n == 1 else 'they were'} (the AIFF is in the Trash)" if back
                    else f"{n} song{s(n)} now AIFF: the same sound, the original{s(n)} in the Trash")
    if k:
        bits.append(f"{k} song{s(k)} now 24-bit AIFF (from 32-bit, which no club deck plays), the original{s(k)} in the Trash")
    if why:
        first = next(iter(why))
        bits.append(f"{len(why)} left as {'it is' if len(why) == 1 else 'they are'} ({os.path.splitext(first)[0][:60]}: {why[first]})")
    return "AIFF: " + "; ".join(bits) if bits else ""


def decks(dir, src):
    """The decks' lists follow now (and your USB, when it's in), as after any new song."""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(dir, "usb.txt")) as f:
            mine = f.read().strip()
    except OSError:
        mine = ""
    env = {**os.environ, "SRC": src}
    if mine and os.path.isdir(os.path.join(os.environ.get("VOLUMES") or "/Volumes", mine)):
        subprocess.run([os.path.join(here, "usb.sh")], env=env, stdin=subprocess.DEVNULL)
    else:
        with open(os.path.join(dir, "dj.log"), "a") as err:
            subprocess.run(["/usr/bin/python3", os.path.join(here, "dj.py"), dir, src, "--wait"], env=env, stderr=err)


def log(dir, text):
    if text:
        with open(os.path.join(dir, "dj.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %R')}  {text}\n")


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("auto", "pick", "deep", "undo"):
        sys.exit(__doc__)
    how, dir, src = sys.argv[1:]
    if how == "auto":
        safe(dir, src)  # a song that just arrived is checked first, so it is converted before it reaches the USB
        got = run(dir, src, waiting(dir, src))
        if got:
            log(dir, say(*got))
    else:
        names = [r for r in json.load(sys.stdin) if isinstance(r, str) and not os.path.isabs(r) and ".." not in r.split(os.sep)]
        cut = [] if how == "deep" else None
        got = run(dir, src, names, back=how == "undo", show=True, cut=cut)
        if got:
            log(dir, say(*got, back=how == "undo", cut=cut or ()))
        if got and got[0]:
            decks(dir, src)
