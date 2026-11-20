"""Finds a song's beat grid and draws its waveforms, the way a deck would on loading it, so the song reaches the USB
already analysed: rekordbox and the decks show its tempo, beat grid, bars and waveform without analysing it again.

    beats.py FILE        prints what it found (tempo, first beat, where the bars start)

Benched against rekordbox's own analysis of 300 songs: the same tempo on 9 in 10 (a whole-number tempo exactly on
229 of 231), the first beat within 20 ms on 8 in 10, the bar's first beat right on 8 in 10. Where The Crate's other
tempo counter (dj_analyze.py) says something else, the song goes on the page's "check tempo" list.

How: the song is read once at 44.1 kHz (ffmpeg; Essentia's reader when ffmpeg isn't there). Each 6 ms the sound is
split into 24 pitch bands and the rise in each band is summed: the hits. The tempo is the beat spacing those hits repeat
at most strongly (with its double and quadruple), counted in [90, 180) as DJs count, and a whole number when within
0.15 of one. The first beat is where the hits pile up when the song is folded onto one beat; the bar starts on the beat
with the most bass and the most change. Runs on numpy alone (macOS, Windows, Linux)."""
import os, shutil, struct, subprocess, sys

try:
    import numpy as np
except ImportError:  # (engine.py reads only the beat times below, with the Mac's own Python)
    np = None

RATE = 44100
N, HOP = 2048, 256          # 46 ms windows, 5.8 ms apart
FPS = RATE / HOP
EDGES = np.geomspace(30, 11000, 25) if np else None
M = 1 << 20                 # tempo resolution: about 0.01 BPM
LATE = 0.031                # decks put the beat this long after the hit's window starts
ENGINE_MP3 = 0.010          # Engine DJ starts an MP3 a little later than a WAV (benched on a Prime 4 library)
PER = 150                   # waveform slices a second (rekordbox's)
LOW, HIGH = 200, 2500       # the waveform's three colours: bass below 200 Hz, mids, highs above 2500 Hz


def ffmpeg():
    return shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
                                                       os.path.expanduser("~/.local/bin/ffmpeg")) if os.path.exists(p)), "")


def decode(path):
    """The audio as one channel at 44.1 kHz, float32. ffmpeg trims an MP3's encoder delay, as Engine DJ does."""
    ff = ffmpeg()
    if ff:
        r = subprocess.run([ff, "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
                           capture_output=True)
        y = np.frombuffer(r.stdout, np.float32)
        if len(y):
            return y
    try:
        import essentia
        essentia.log.warningActive = essentia.log.infoActive = False
        import essentia.standard as es
        y = np.asarray(es.MonoLoader(filename=path, sampleRate=RATE)(), np.float32)
    except Exception:
        y = np.zeros(0, np.float32)
    if not len(y):
        raise ValueError("couldn't read the audio in this file")
    return y


def lead(path):
    """How much later rekordbox's clock runs than ffmpeg's for this file, in seconds. An MP3 made by LAME (its tag
    in the Xing/Info header) starts 48 ms later in rekordbox, one made by ffmpeg's encoder 22 ms; others match."""
    if not path.lower().endswith(".mp3"):
        return 0.0
    try:
        with open(path, "rb") as f:
            d = f.read(1 << 20)
    except OSError:
        return 0.0
    i = 0  # past the ID3 tag (its text can hold "Info"), to the first frame, where the encoder's tag sits
    if d[:3] == b"ID3" and len(d) >= 10:
        i = 10 + ((d[6] & 127) << 21 | (d[7] & 127) << 14 | (d[8] & 127) << 7 | (d[9] & 127)) + (10 if d[5] & 16 else 0)
    while i + 1 < len(d) and not (d[i] == 0xFF and d[i + 1] & 0xE0 == 0xE0):
        i += 1
    at = [j for j in (d.find(b"Xing", i, i + 64), d.find(b"Info", i, i + 64)) if j >= 0]
    if not at:
        return 0.0
    return {b"LAME": 0.048, b"Lavc": 0.022}.get(d[min(at) + 120:min(at) + 124], 0.0)


def hits(y):
    """[frames, 24]: how much each pitch band rose at each step (positive change of its loudness)."""
    n = 1 + (len(y) - N) // HOP
    if n < 2:
        raise ValueError("too short to find a beat")
    f = np.fft.rfftfreq(N, 1 / RATE)
    cols = [(f >= a) & (f < b) for a, b in zip(EDGES[:-1], EDGES[1:])]
    w = np.hanning(N).astype(np.float32)
    out, prev = np.empty((n, 24), np.float32), None
    for i in range(0, n, 2048):
        k = min(n, i + 2048)
        idx = np.arange(N)[None, :] + HOP * np.arange(i, k)[:, None]
        S = np.abs(np.fft.rfft(y[idx] * w, axis=1)) / 2  # (/2: the same scale as the 22 kHz bench)
        L = np.log1p(1000 * np.stack([S[:, c].sum(1) for c in cols], 1))
        d = np.diff(L, axis=0, prepend=L[:1] if prev is None else prev)
        out[i:k] = np.maximum(0, d)
        prev = L[-1:]
    return out


def even(e):
    """The hits less their 1-second average, on one scale."""
    k = max(1, min(len(e), int(FPS)))
    x = np.maximum(0, e - np.convolve(e, np.ones(k) / k, mode="same"))
    return x / (x.std() + 1e-9)


def tempo(e):
    """The beat spacing the hits repeat at most strongly, as BPM in [90, 180)."""
    spec = np.abs(np.fft.rfft(even(e), M))
    step = FPS / M * 60

    def at(b):
        i = np.asarray(b) / step
        i0 = np.minimum(np.floor(i).astype(int), len(spec) - 2)
        fr = i - i0
        return spec[i0] * (1 - fr) + spec[i0 + 1] * fr
    grid = np.arange(70, 180, 0.05)
    score = at(grid) + 0.5 * at(grid * 2) + 0.25 * at(grid * 4)
    b0 = grid[int(np.argmax(score))]
    lo, hi = int((b0 - 0.15) / step), int((b0 + 0.15) / step) + 1
    b = (lo + int(np.argmax(spec[lo:hi]))) * step
    while b < 90:
        b *= 2
    while b >= 180:
        b /= 2
    return float(round(b)) if abs(b - round(b)) < 0.15 else round(float(b), 2)


def first(e, bpm):
    """Where in a beat the hits pile up, in seconds after the start (0 to one beat)."""
    P = 60 / bpm
    nb = max(8, int(P / 0.002))
    ph = (np.arange(len(e)) / FPS) % P
    j = (ph / P * nb).astype(int) % nb
    h = np.bincount(j, weights=e, minlength=nb) / np.maximum(np.bincount(j, minlength=nb), 1)
    k = np.exp(-0.5 * (np.arange(-5, 6) / 2.0) ** 2)
    hs = np.convolve(np.concatenate([h[-5:], h, h[:5]]), k / k.sum(), "same")[5:-5]
    return (int(np.argmax(hs)) + 0.5) / nb * P


def bar(F, t0, bpm):
    """Which of the first four beats (0-3) starts a bar: the one with the most bass and the most change, bar by bar."""
    P = 60 / bpm
    n = int((len(F) / FPS - t0) / P)
    idx = np.round((t0 + np.arange(max(n, 0)) * P) * FPS).astype(int)
    idx = idx[idx < len(F) - 3]
    if len(idx) < 8:
        return 0
    lo = F[:, :6].sum(1)
    win = np.array([lo[max(0, i - 2):i + 3].max() for i in idx])
    span = max(1, int(P * FPS))
    B = np.array([F[i:i + span].sum(0) for i in idx])
    change = np.r_[0, np.abs(np.diff(np.log1p(B), axis=0)).sum(1)]
    z = lambda x: (x - x.mean()) / (x.std() + 1e-9)
    v = z(win) + z(change)
    return int(np.argmax([v[k::4].mean() for k in range(4)]))


def slices(y):
    """[n, 5] for each 1/150 s: peak, loudness (rms), and the loudness of the bass, mids and highs."""
    spe = RATE / PER
    n = int(len(y) / spe)
    if n < 1:
        return np.zeros((0, 5), np.float32)
    B = 1 << 18
    f = np.fft.rfftfreq(B, 1 / RATE)
    masks = (f < LOW, (f >= LOW) & (f < HIGH), f >= HIGH)
    parts = [np.empty(len(y), np.float32) for _ in masks]
    for i in range(0, len(y), B):
        s = y[i:i + B]
        Y = np.fft.rfft(s, B)
        for out, m in zip(parts, masks):
            out[i:i + len(s)] = np.fft.irfft(Y * m, B)[:len(s)]
    edges = (np.arange(n + 1) * spe).astype(int)
    cnt = np.diff(edges)
    out = np.zeros((n, 5), np.float32)
    out[:, 0] = np.maximum.reduceat(np.abs(y[:edges[-1]]), edges[:-1])
    for j, x in enumerate((y, *parts), 1):
        out[:, j] = np.sqrt(np.add.reduceat(x[:edges[-1]].astype(np.float64) ** 2, edges[:-1]) / cnt)
    return out


def analyse(path, rate=0):
    """{"bpm", "first": the first beat in seconds (ffmpeg's clock), "bar": which of beats 0-3 starts a bar, "lead":
    rekordbox's clock less ffmpeg's, "secs", "rate": the file's own sample rate, "samples" at that rate} and the
    waveform slices ([n, 5], ffmpeg's clock)."""
    y = decode(path)
    F = hits(y)
    e = F.sum(1)
    bpm = tempo(e)
    t0 = first(e, bpm)
    secs = len(y) / RATE
    rate = int(rate or RATE)
    return {"bpm": bpm, "first": round(t0, 4), "bar": bar(F, t0, bpm), "lead": lead(path), "secs": round(secs, 3),
            "rate": rate, "samples": int(round(secs * rate))}, slices(y)


def times(g, clock="rekordbox"):
    """Every beat of a grid as (time in seconds on that app's clock, beat in bar 1-4), from the first at or after 0."""
    P = 60 / g["bpm"]
    late = LATE + (g["lead"] if clock == "rekordbox" else ENGINE_MP3 if g["lead"] else 0)
    t, k = g["first"] + late, 0
    while t - P >= 0:
        t, k = t - P, k - 1
    out = []
    while t < g["secs"]:
        out.append((t, (k - g["bar"]) % 4 + 1))
        t, k = t + P, k + 1
    return out


if __name__ == "__main__":
    g, w = analyse(sys.argv[1])
    print(f"{g['bpm']} BPM, first beat {times(g)[0][0]:.3f} s (rekordbox), bar starts on beat {g['bar'] + 1}, "
          f"{g['secs']:.0f} s, {len(w)} waveform slices")
