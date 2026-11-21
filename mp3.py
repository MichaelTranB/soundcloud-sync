#!/usr/bin/env python3
"""Your own lossless songs (FLAC, WAV, AIFF) as 320 MP3s on this Mac and the USB, with the lossless original kept in
iCloud Drive: a quarter of the room, and a file every deck plays.

  how      ffmpeg reads the song and LAME (the real encoder: its gapless note is one Pioneer gear reads) writes a
           320 kbps MP3, at the song's own rate (above 48 kHz: 48 or 44.1, the most an MP3 holds). The details and
           cover are copied across. The MP3 is then played back and held to the original: the same length (within
           0.15 s) and the same loudness from moment to moment (each 50 ms, 98% alike). Anything else: the original
           stays and nothing changes;
  kept     only once the MP3 passes the safety check does the original move to iCloud Drive, in The Crate's folder
           there ("Lossless originals", in the same folders as here), and once iCloud has it, its room on this Mac is
           given back. Never the Trash. Without iCloud Drive it waits in "Lossless originals" beside The Crate's own
           files on this Mac;
  follows  as with an AIFF (aiff.py): every note kept per file goes along, and dj.py points rekordbox, the USB's
           rekordbox lists and Engine DJ at the MP3, so playlists, cues, loops and grids stay with the song. On the
           USB the old file goes to the USB's own Trash and the MP3 takes its place (usb_tidy.py);
  when     switched on (mp3.json, "Keep MP3 copies" on the Library Manager page): every lossless song of yours at
           each deck update, and each new one as it arrives, so the USB only ever gets the MP3. A song you brought
           back stays lossless. Songs from a friend's USB are left as they came;
  undo     the original comes back from iCloud (downloaded first when only iCloud has it) and the MP3 goes to the
           Trash.

  mp3.py auto DIR SRC     the lossless songs waiting, then gives back the room of originals now safely in iCloud
  mp3.py pick DIR SRC     the songs named on stdin (a JSON list of names inside the music folder), then the decks
  mp3.py undo DIR SRC     the same, back

Needs ffmpeg and lame (Homebrew) and mutagen (the DJ tools' own Python, dj-setup.sh)."""
import array, fcntl, json, math, os, shutil, subprocess, sys, time

import aiff, backup, friend, soulseek, usb_tidy

REC, TMP, PROGRESS, LOCK = "mp3.json", ".mp3-tmp", ".mp3-progress", ".mp3.lock"
KINDS = (".flac", ".wav", ".aiff", ".aif")
HOME = "Lossless originals"
RATE = 8000  # the rate the two are heard at to compare them: plenty for loudness over time
AFTER = 0.15  # seconds the two may differ in length
ALIKE = 0.98


def load(dir):
    try:
        with open(os.path.join(dir, REC)) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        rec = {}
    rec = rec if isinstance(rec, dict) else {}
    return {"on": rec.get("on") is True, "skip": rec.get("skip") or {}, "kept": rec.get("kept") or [],
            "up": rec.get("up") or []}


def save(dir, rec):
    with open(os.path.join(dir, REC + ".tmp"), "w") as f:
        json.dump(rec, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(os.path.join(dir, REC + ".tmp"), os.path.join(dir, REC))


def tool(name):
    return shutil.which(name) or next((p for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}")
                                       if os.path.exists(p)), "")


def home(dir):
    """Where originals go: The Crate's folder in iCloud Drive, or beside its own files on this Mac without it."""
    up = backup.cloud()
    return os.path.join(os.path.dirname(up), HOME) if up else os.path.join(dir, HOME)


def undoable(dir):
    """MP3s whose original is still kept: {the MP3: where its original is}."""
    return {new: to for new, (old, to) in aiff.history(dir).items()
            if new.lower().endswith(".mp3") and old.lower().endswith(KINDS) and to and os.path.lexists(to)}


# ---- one song

def heard(path):
    """(seconds, loudness each 50 ms) of a song, as ffmpeg plays it."""
    r = subprocess.run([tool("ffmpeg"), "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", str(RATE),
                        "-c:a", "pcm_s16le", "-f", "s16le", "-"], capture_output=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise aiff.Problem("ffmpeg couldn't play it to its end: the original stays")
    a = array.array("h")
    a.frombytes(r.stdout[:len(r.stdout) - len(r.stdout) % 2])
    if sys.byteorder != "little":
        a.byteswap()
    step = RATE // 20
    return len(a) / RATE, [math.sqrt(sum(x * x for x in a[i:i + step]) / step) for i in range(0, len(a) - step + 1, step)]


def alike(a, b):
    """How alike two loudness curves are (1: the same shape)."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if not n:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va < 1e-6 or vb < 1e-6:  # silence (or one steady tone): alike when equally loud
        return 1.0 if abs(ma - mb) <= max(1.0, 0.05 * max(ma, mb)) else 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def same(path, out):
    """Is the MP3 at out this song (length and loudness over time)?"""
    (la, ea), (lb, eb) = heard(path), heard(out)
    return la > 0 and abs(la - lb) <= AFTER and alike(ea, eb) >= ALIKE


def full(out):
    """Is the MP3 at out a 320 one (not an older, smaller copy of the song)?"""
    from mutagen.mp3 import MP3
    try:
        return round(MP3(out).info.bitrate / 1000) >= 320
    except Exception:
        return False


def details(src, out):
    from mutagen.mp3 import MP3
    m = MP3(out)
    if m.tags is None:
        m.add_tags()
    info = {}
    if src.lower().endswith(".wav"):
        try:
            info = aiff.wav_info(src, True)
        except (aiff.Problem, OSError, ValueError):
            pass
    aiff.fill(m.tags, src, info)
    m.save(v2_version=3)


def convert(path, out):
    """Writes path's MP3 at out. Raises Problem, leaving nothing behind, unless it plays as the original does."""
    ff, lame = tool("ffmpeg"), tool("lame")
    if not ff or not lame:
        raise aiff.Problem("this Mac needs ffmpeg and lame to make MP3s (brew install ffmpeg lame)")
    r = subprocess.run([tool("ffprobe") or ff.replace("ffmpeg", "ffprobe"), "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=sample_rate,channels", "-of", "json", path], capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)["streams"][0]
        rate, channels = int(s["sample_rate"]), int(s["channels"])
    except (ValueError, KeyError, IndexError, TypeError):
        raise aiff.Problem("ffmpeg couldn't read it", True)
    if channels > 2:
        raise aiff.Problem(f"{channels} channels: an MP3 holds two", True)
    to = [] if rate in (32000, 44100, 48000) else ["-ar", "44100" if rate % 44100 == 0 else "48000"]
    try:
        dec = subprocess.Popen([ff, "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0", "-map_metadata", "-1", *to,
                                "-c:a", "pcm_s24le", "-f", "wav", "-"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
        enc = subprocess.run([lame, "--silent", "-b", "320", "--cbr", "-q", "0", "-", out], stdin=dec.stdout,
                             capture_output=True)
        dec.stdout.close()
        if dec.wait() or enc.returncode or not os.path.isfile(out):
            raise aiff.Problem("the MP3 couldn't be made: the original stays")
        details(path, out)
        if not same(path, out):
            raise aiff.Problem("the MP3 didn't play like the original: the original stays", True)
        st = os.stat(path)
        os.utime(out, (st.st_atime, st.st_mtime))  # as old as the original: it keeps its place by date
    except BaseException:
        if os.path.exists(out):
            os.remove(out)
        raise


def keep(dir, path, rel):
    """The original into its place among the kept ones (iCloud Drive), in the same folders; where it went."""
    to = os.path.join(home(dir), rel)
    if os.path.lexists(to):
        stem, ext = os.path.splitext(to)
        to = f"{stem} ({time.strftime('%Y-%m-%d %H%M%S')}){ext}"
    backup.into(path, to)
    return to


def fetch(path):
    """A file only iCloud has, downloaded (reading it brings it down). False when it couldn't be."""
    try:
        with open(path, "rb") as f:
            while f.read(1 << 22):
                pass
        return not os.stat(path).st_flags & backup.DATALESS
    except OSError:
        return False


def free(dir):
    """Originals now safely in iCloud give their room on this Mac back. Returns how many did."""
    rec = load(dir)
    up = [p for p in rec["up"] if os.path.lexists(p)]
    if not up:
        if rec["up"]:
            rec["up"] = []
            save(dir, rec)
        return 0
    got = backup.look(dir, up, free=True)
    rec = load(dir)
    rec["up"] = [p for p in up if got.get(p) not in ("e", "c")]
    save(dir, rec)
    return sum(got.get(p) in ("e", "c") for p in up)


def note(dir, done, rels):
    with open(os.path.join(dir, PROGRESS + ".tmp"), "w") as f:
        f.write(f"{done}\t{len(rels)}\t{os.getpid()}")
    os.replace(os.path.join(dir, PROGRESS + ".tmp"), os.path.join(dir, PROGRESS))


def run(dir, src, rels, back=False, show=False):
    """Converts each named song (back: undoes it). Returns (names done, {name: why not}); None when another run is
    at it."""
    done, why, ready = [], {}, []
    tmp = os.path.join(dir, TMP)
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(dir, LOCK), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        there, was = (undoable(dir), aiff.history(dir)) if back else ({}, {})
        for n, rel in enumerate(rels):
            if show:
                note(dir, n, rels)
            path = os.path.join(src, rel)
            try:
                if back:
                    old = was.get(rel, ("",))[0]
                    old = old and os.path.splitext(rel)[0] + os.path.splitext(old)[1]
                    if rel not in there or not old:
                        raise aiff.Problem("its original is no longer kept")
                    if os.path.lexists(os.path.join(src, old)):
                        raise aiff.Problem("a file with the original's name is in the folder")
                    if not fetch(there[rel]):
                        raise aiff.Problem("its original couldn't be brought down from iCloud: try again when online")
                    shutil.move(there[rel], os.path.join(src, old))
                    ready.append((rel, old))
                    continue
                new = os.path.splitext(rel)[0] + ".mp3"
                out = os.path.join(src, new)
                if not rel.lower().endswith(KINDS) or not os.path.isfile(path):
                    continue
                if os.path.lexists(out):  # made on an earlier run that was cut short, or another song by that name
                    if not full(out) or not same(path, out):
                        raise aiff.Problem("another file by that name is already an MP3", True)
                else:
                    room = shutil.disk_usage(src).free
                    if room < os.path.getsize(path) + (2 << 30):
                        why[rel] = f"not enough room on this Mac ({room / 1e9:.0f} GB free)"
                        break
                    made = os.path.join(tmp, f"{os.getpid()}-{n}.mp3")
                    convert(path, made)
                    shutil.move(made, out)
                ready.append((rel, new))
            except aiff.Problem as e:
                why[rel] = str(e)
                if e.lasting and not back:
                    rec = load(dir)
                    rec["skip"][rel] = str(e)
                    save(dir, rec)
            except Exception as e:  # never silent, and never the end of the others
                why[rel] = f"{e!r}"[:160]
        if ready:
            ok = aiff.safe(dir, src)
            day = time.strftime("%Y-%m-%d")
            with soulseek.locked(dir):
                for rel, new in ready:
                    if new not in ok:
                        why[rel] = "the new file hasn't passed the safety check yet: both stay for now"
                        if back:  # the original goes back where it was kept, so Undo is still there next time
                            try:
                                backup.into(os.path.join(src, new), there[rel])
                            except OSError as e:
                                aiff.log(dir, f"MP3 PROBLEM: {new} couldn't go back to iCloud ({e!r})"[:300])
                        continue
                    try:
                        to = aiff.trash(dir, os.path.join(src, rel), "undone") if back else keep(dir, os.path.join(src, rel), rel)
                    except OSError as e:
                        to, why[rel] = "", f"its original couldn't be moved to iCloud ({e.strerror or e})"
                    if not to:
                        why.setdefault(rel, "its old file couldn't be moved to the Trash")
                        continue
                    with open(os.path.join(dir, aiff.DONE), "a", encoding="utf-8") as f:  # noted first: undo needs it
                        f.write(f"{rel}\t{new}\t{to}\t{day}\n")
                    done.append(new)
                    rec = load(dir)
                    rec["skip"].pop(rel, None)
                    if back:
                        rec["kept"] = sorted(set(rec["kept"]) | {new})  # brought back by you: it stays lossless
                    else:
                        rec["kept"] = [k for k in rec["kept"] if k != rel]
                        if to.startswith(backup.CLOUD + os.sep):
                            rec["up"] = rec["up"] + [to]
                    save(dir, rec)
                    try:
                        aiff.follow(dir, src, rel, new)
                    except Exception as e:  # the song itself is fine; said, never silent
                        aiff.log(dir, f"MP3 PROBLEM: the notes for {new} didn't all follow ({e!r})"[:300])
    if show:
        try:
            os.remove(os.path.join(dir, PROGRESS))
        except OSError:
            pass
    return done, why


def waiting(dir, src):
    """The songs to convert by themselves now: every lossless song of yours, when switched on."""
    rec = load(dir)
    if not rec["on"]:
        return []
    theirs = set(friend.load(dir)["songs"])  # a friend's songs stay as they came
    kept = set(rec["kept"]) | set(rec["skip"]) | theirs
    return [r for r in usb_tidy.checked(dir, src) if r.lower().endswith(KINDS) and r not in kept]


def say(done, why, back=False):
    """One line for dj.log; "" when nothing happened."""
    bits, s = [], lambda n: "s" if n != 1 else ""
    if done:
        n = len(done)
        bits.append(f"{n} song{s(n)} back as {'it was' if n == 1 else 'they were'} (the MP3 is in the Trash)" if back
                    else f"{n} song{s(n)} now 320 MP3, the lossless original{s(n)} kept in iCloud")
    if why:
        first = next(iter(why))
        bits.append(f"{len(why)} left as {'it is' if len(why) == 1 else 'they are'} ({os.path.splitext(first)[0][:60]}: {why[first]})")
    return "MP3: " + "; ".join(bits) if bits else ""


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("auto", "pick", "undo"):
        sys.exit(__doc__)
    how, dir, src = sys.argv[1:]
    if how == "auto":
        if load(dir)["on"]:
            aiff.safe(dir, src)  # a song that just arrived is checked first, so it is converted before it reaches the USB
            got = run(dir, src, waiting(dir, src), show=True)
            if got:
                aiff.log(dir, say(*got))
        n = free(dir)
        if n:
            aiff.log(dir, f"MP3: {n} lossless original{'s' if n != 1 else ''} safely in iCloud, room on this Mac given back")
    else:
        names = [r for r in json.load(sys.stdin) if isinstance(r, str) and not os.path.isabs(r) and ".." not in r.split(os.sep)]
        got = run(dir, src, names, back=how == "undo", show=True)
        if got:
            aiff.log(dir, say(*got, back=how == "undo"))
        if got and got[0]:
            aiff.decks(dir, src)
