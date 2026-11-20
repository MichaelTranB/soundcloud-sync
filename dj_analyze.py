"""Listens to each track once and writes what a DJ deck wants to know: tempo (BPM), musical key, length, and the tags
already inside the file. Run by dj.py with the private Python that has Essentia and Mutagen (see install.sh); the
rest of The Crate stays standard-library only and works without it (tracks then reach the decks unanalysed).

    dj_analyze.py <music folder> <cache.json> [relative paths, one per line, on stdin]

Only files that changed since the last run (size or time) are analysed again. The tempo is counted twice, by two
different counters ("bpm" and "bpm2"): tempo.py shows The Crate's own count only where they agree."""
import json, os, sys
from multiprocessing import Pool

VERSION = 2  # raise it to listen to everything again after a change to how tempo or key is found
FLAT = {"Db": "C#", "D#": "Eb", "Gb": "F#", "G#": "Ab", "A#": "Bb"}


def tags(path):
    """Title, artist, album, genre, year, comment, label and the audio facts, whatever the file type."""
    import mutagen
    out = {}
    try:
        f = mutagen.File(path, easy=False)
    except Exception:
        f = None
    if f is None:
        return out
    info = f.info
    out["length"] = round(getattr(info, "length", 0) or 0, 2)
    out["bitrate"] = int((getattr(info, "bitrate", 0) or 0) / 1000)
    out["rate"] = int(getattr(info, "sample_rate", 0) or 0)
    t = f.tags or {}

    def first(*names):
        for n in names:
            try:
                v = t.get(n)
            except (ValueError, KeyError):  # a tag name this file type doesn't allow
                continue
            if v is None:
                continue
            if isinstance(v, list):
                v = v[0] if v else ""
            v = getattr(v, "text", v)
            if isinstance(v, list):
                v = v[0] if v else ""
            v = str(v).strip()
            if v:
                return v
        return ""
    out["title"] = first("TIT2", "title", "TITLE", "\xa9nam")
    out["artist"] = first("TPE1", "artist", "ARTIST", "\xa9ART")
    out["album"] = first("TALB", "album", "ALBUM", "\xa9alb")
    out["genre"] = first("TCON", "genre", "GENRE", "\xa9gen")
    out["year"] = first("TDRC", "TYER", "date", "DATE", "year", "\xa9day")[:4]
    out["label"] = first("TPUB", "organization", "label", "LABEL")
    out["remixer"] = first("TPE4", "remixer", "REMIXER")
    out["comment"] = next((str(v.text[0]) for k, v in t.items() if str(k).startswith("COMM") and v.text), "") \
        if hasattr(t, "items") and any(str(k).startswith("COMM") for k in t.keys()) else first("comment", "COMMENT", "description")
    return {k: v for k, v in out.items() if v not in ("", 0)}


def sharpen(audio, bpm, sr=44100, hop=256, n=1024):
    """The first estimate is within a beat or two a minute. This finds the exact tempo near it: the one whose beat
    spacing lines up best with where the track's hits really fall, over 64 beats. Produced music sits on a whole
    number, so a whole number wins unless something else fits clearly better."""
    import numpy as np
    frames = np.lib.stride_tricks.sliding_window_view(audio, n)[::hop]
    mag = np.abs(np.fft.rfft(frames * np.hanning(n), axis=1))
    env = np.maximum(np.diff(np.log1p(100 * mag), axis=0), 0).sum(axis=1)
    env = env - env.mean()
    size = len(env)
    f = np.fft.rfft(env, 2 * size)
    acf = np.fft.irfft(f * np.conj(f))[:size]
    acf = acf / (acf[0] or 1)
    fps = sr / hop

    def score(t):
        x = np.arange(1, 65) * (60 / t * fps)
        x = x[x < size - 2]
        i = x.astype(int)
        return float(np.mean(acf[i] * (1 - (x - i)) + acf[i + 1] * (x - i))) if len(x) else 0.0
    fine = np.arange(bpm - 4, bpm + 4.001, 0.02)
    scores = [score(t) for t in fine]
    best, top = float(fine[int(np.argmax(scores))]), max(scores)
    whole_score, whole = max((score(t), t) for t in range(int(bpm - 4), int(bpm + 5)))
    return float(whole) if whole_score >= 0.9 * top else round(best, 2)


def load(path):
    """The audio as one channel at 44.1 kHz."""
    import essentia
    essentia.log.warningActive = False
    essentia.log.infoActive = False
    import essentia.standard as es
    audio = es.MonoLoader(filename=path, sampleRate=44100)()
    if not len(audio):  # a file Essentia's reader can't open (32-bit FLAC): ffmpeg or macOS reads it for us
        import shutil, subprocess, tempfile
        ff = shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
                                                         os.path.expanduser("~/.local/bin/ffmpeg")) if os.path.exists(p)), "")
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "a.wav")
            cmd = [ff, "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", wav] if ff else \
                ["afconvert", "-f", "WAVE", "-d", "LEI16@44100", "-c", "1", path, wav]
            if subprocess.run(cmd, capture_output=True).returncode:
                raise ValueError("this Mac can't read the audio in this file")
            audio = es.MonoLoader(filename=wav, sampleRate=44100)()
    return audio


def second(audio):
    """The tempo once more, by a counter that works another way (Percival's): 0 when it finds none."""
    import essentia.standard as es
    try:
        return round(float(es.PercivalBpmEstimator()(audio)), 2)
    except Exception:
        return 0


def listen(path):
    """Tempo and key from the audio itself."""
    import essentia.standard as es
    audio = load(path)
    again = second(audio)
    bpm, beats, conf, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    key, scale, strength = es.KeyExtractor(profileType="edma")(audio)
    bpm = float(bpm)
    # DJs count bass music at full speed: 70 is 140, 87 is 174. Outside 78 to 180, fold it in.
    while 0 < bpm < 78:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    try:
        bpm = sharpen(audio, bpm)
    except Exception:
        pass
    if bpm < 40:
        raise ValueError("no steady beat found")
    return {"bpm": round(bpm, 2), "bpm2": again, "bpm_sure": round(float(conf), 2), "key": FLAT.get(key, key) + ("m" if scale == "minor" else ""),
            "key_sure": round(float(strength), 2), "first_beat": round(float(beats[0]), 3) if len(beats) else 0.0}


def one(job):
    root, rel, had = job
    path = os.path.join(root, rel)
    if had:  # listened to before the second count existed: only that is added, nothing else is heard again
        try:
            return rel, {**had, "bpm2": second(load(path))}
        except Exception:
            return rel, {**had, "bpm2": 0}
    st = os.stat(path)
    out = {"size": st.st_size, "mtime": int(st.st_mtime), "v": VERSION}
    try:
        out.update(tags(path))
    except Exception as e:
        out["tag_error"] = (str(e) or type(e).__name__)[:200]
    try:
        out.update(listen(path))
    except Exception as e:
        out["listen_error"] = (str(e) or type(e).__name__)[:200]
        try:  # the key is still worth having when the tempo isn't found
            import essentia.standard as es
            key, scale, strength = es.KeyExtractor(profileType="edma")(es.MonoLoader(filename=path, sampleRate=44100)())
            out.update({"key": FLAT.get(key, key) + ("m" if scale == "minor" else ""), "key_sure": round(float(strength), 2)})
        except Exception:
            pass
    return rel, out


def main():
    root, cache_path = sys.argv[1], sys.argv[2]
    rels = [l.rstrip("\n") for l in sys.stdin if l.strip()]
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}
    jobs = []
    for rel in rels:
        try:
            st = os.stat(os.path.join(root, rel))
        except OSError:
            continue
        c = cache.get(rel)
        if c and c.get("size") == st.st_size and c.get("mtime") == int(st.st_mtime) and ("bpm" in c or "listen_error" in c) and "tag_error" not in c and c.get("v") == VERSION:
            if "bpm" not in c or "bpm2" in c:
                continue
            jobs.append((root, rel, c))
            continue
        jobs.append((root, rel, None))
    done, only = 0, {j[1] for j in jobs if j[2]}  # (only: those whose second count alone is added)
    with Pool(min(6, os.cpu_count() or 2)) as pool:
        for rel, out in pool.imap_unordered(one, jobs):
            cache[rel] = out
            done += 1
            print(f"{'again ' if rel in only else ''}{done}/{len(jobs)}  {out.get('bpm', '?')}  {out.get('key', '?')}  {rel}", flush=True)
            if done % 10 == 0:
                save(cache, cache_path)
    for rel in list(cache):  # a track no longer in the folder leaves the cache
        if rel not in rels:
            del cache[rel]
    save(cache, cache_path)


def save(cache, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
