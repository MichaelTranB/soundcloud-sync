#!/usr/bin/env python3
"""A song's waveform, for the Library Manager's player: how loud it is from start to end.

    python3 waveform.py FILE          # prints it

Drawn so you can see what is wrong with a file before it reaches a deck: a start or an end that is cut off, a
silent stretch, or a song that is far too quiet. macOS's own converter
(afconvert) reads the file; nothing is written to it. Each waveform is worked out once and kept in .waves in The
Crate's folder (small: a few KB a song). Standard library only."""
import array, hashlib, json, os, subprocess, sys, tempfile, wave

N = 600       # how many slices of the song the page draws
RATE = 8000   # plenty for loudness, and quick
KEEP = ".waves"


def name(path):
    """The kept waveform's file name: another file (or the same one changed) gets another."""
    st = os.stat(path)
    return hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest() + ".json"


def work(path, n=N):
    """{"secs", "top": the loudest point of each slice, "avg": its average loudness (both 0 to 255)}. None when
    macOS can't read that kind of file."""
    tmp = tempfile.mkdtemp(prefix="crate-wave-")
    out = os.path.join(tmp, "w.wav")
    try:
        r = subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", path, out],
                           capture_output=True, timeout=120)
        if r.returncode or not os.path.isfile(out):
            return None
        with wave.open(out, "rb") as w:
            a = array.array("h")
            a.frombytes(w.readframes(w.getnframes()))
        if sys.byteorder == "big":
            a.byteswap()
    except (OSError, EOFError, wave.Error, subprocess.SubprocessError):
        return None
    finally:
        for f in (out, tmp):
            try:
                os.remove(f) if f == out else os.rmdir(f)
            except OSError:
                pass
    if not a:
        return None
    step = max(1, len(a) // n)
    top, avg = [], []
    for i in range(0, step * n, step):
        part = a[i:i + step]
        if not part:
            break
        hi = max(max(part), -min(part))
        thin = part[::4]  # every fourth point is enough for an average
        top.append(min(255, hi * 255 // 32767))
        avg.append(min(255, int((sum(x * x for x in thin) / len(thin)) ** .5 * 255 / 32767)))
    return {"secs": round(len(a) / RATE, 1), "top": top, "avg": avg}


def get(dir, path):
    """The song's waveform, from the kept one when the file hasn't changed since."""
    try:
        kept = os.path.join(dir, KEEP, name(path))
    except OSError:
        return None
    try:
        with open(kept) as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    got = work(path)
    if got:
        try:
            os.makedirs(os.path.dirname(kept), exist_ok=True)
            with open(kept + ".tmp", "w") as f:
                json.dump(got, f, separators=(",", ":"))
            os.replace(kept + ".tmp", kept)
        except OSError:
            pass  # not kept: worked out again next time
    return got


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    got = work(sys.argv[1])
    print(json.dumps(got) if got else "macOS can't read that kind of file")
