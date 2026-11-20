"""A song's rekordbox analysis files (ANLZ0000.DAT and .EXT), made from what beats.py found, laid out as rekordbox 7
writes them: its beat grid, its waveforms (the blue overview, the coloured detail and the three-band ones the
CDJ-3000 draws) and empty cue lists. rekordbox and the decks then show the song as analysed.

The files are kept on the Mac beside The Crate's notes (dj-grids/); rekordbox_usb.py copies them onto the USB with
the song's place on the USB written into them, where rekordbox on this Mac hasn't analysed the song itself.
Standard library and numpy."""
import struct

import numpy as np

import beats

# Each waveform's values from five measures of the sound in that slice (peak, loudness, bass, mids, highs): fitted
# on 10 songs rekordbox 7.2 analysed (r = 0.71 to 0.97 per value).
FIT = {
    "w3h": [14.258, 2.836, -1.52, 1.348, 3.706, 1.606, 1.658, -1.037],
    "w3w": [0.76, -0.939, -1.943, -1.239, -2.579, -5.967, 1.511, 7.031],
    "w5h": [13.225, 3.576, -0.868, 3.059, 4.686, 2.026, 2.641, -1.373],
    "w5b": [0.476, -13.699, 10.895, 8.593, 6.163, -2.66, 7.552, 4.54],
    "w5g": [-0.037, -9.194, 6.953, 7.761, 4.116, -4.902, -4.492, 6.548],
    "w5r": [-0.074, -5.725, 4.824, 5.217, 2.607, 9.493, 0.634, -0.422],
    "w4": [[43.457, 25.263, -15.798, 22.975, -45.84, 14.352, 38.663, 18.319],
           [-36.99, 16.651, -22.884, 0.249, -5.764, 7.426, -11.583, 204.581],
           [20.133, -23.985, 73.015, 65.561, 32.762, 27.789, -41.771, 7.641],
           [11.818, -84.439, 167.951, 43.465, 40.385, 23.19, -15.931, -1.98],
           [2.829, -38.725, 46.77, 196.499, -0.909, -12.119, -5.323, 5.59],
           [0.957, -12.628, 52.296, -19.641, 345.201, -34.333, -45.385, 14.594]],
}
NAMES = ("ANLZ0000.DAT", "ANLZ0000.EXT")
ENGINE = "engine.bin"  # Engine DJ's overview waveform, kept beside them (engine.py writes it into the USB's library)


def basis(X):
    pk, rms, lo, mid, hi = (X[:, i] for i in range(5))
    tot = lo + mid + hi + 1e-9
    return np.stack([pk ** 2, rms, lo, mid, hi, lo / tot, hi / tot, np.ones(len(X))], 1)


def fit(X, name, top):
    return np.clip(np.round(basis(X) @ np.array(FIT[name])), 0, top).astype(int)


def columns(W, n):
    """The slices gathered into n columns: the loudest peak in each, and the loudness of the rest."""
    e = np.linspace(0, len(W), n + 1).astype(int)
    out = np.zeros((n, 5))
    for i, (a, b) in enumerate(zip(e[:-1], e[1:])):
        if b > a:
            out[i, 0] = W[a:b, 0].max()
            out[i, 1:] = np.sqrt((W[a:b, 1:].astype(np.float64) ** 2).mean(0))
    return out


def section(four, head, body=b""):
    """One part of the file: its name, its header's length, its whole length, the rest of its header, its body."""
    return four + struct.pack(">II", 12 + len(head), 12 + len(head) + len(body)) + head + body


def whole(parts):
    body = b"".join(parts)
    return b"PMAI" + struct.pack(">II", 28, 28 + len(body)) + bytes.fromhex("00000001000100000001000000000000") + body


def pqtz(grid):
    """The beat grid part: one entry a beat (its place in the bar, the tempo x100, its time in ms)."""
    ticks = beats.times(grid)
    q = b"".join(struct.pack(">HHI", n, int(round(grid["bpm"] * 100)), int(round(t * 1000))) for t, n in ticks)
    return section(b"PQTZ", struct.pack(">III", 0, 0x80000, len(ticks)), q)


def ppth(path):
    p = path.encode("utf-16-be") + b"\0\0"
    return section(b"PPTH", struct.pack(">I", len(p)), p)


def cues():
    """Empty hot cue and memory cue lists, as rekordbox writes them for a song without cues."""
    return [section(b"PCOB", struct.pack(">IHHI", 1, 0, 0, 0xFFFFFFFF)),
            section(b"PCOB", struct.pack(">IHHI", 0, 0, 0, 0xFFFFFFFF))]


def mp3_samples(path):
    """An MP3's length in samples, counted frame by frame (rekordbox keeps it in the .DAT file). 0 for other files."""
    if not path.lower().endswith(".mp3"):
        return 0
    BR = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
          2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
    RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
    try:
        with open(path, "rb") as f:
            d = f.read()
    except OSError:
        return 0
    i, n, spf = 0, 0, 1152
    if d[:3] == b"ID3" and len(d) >= 10:
        i = 10 + ((d[6] & 127) << 21 | (d[7] & 127) << 14 | (d[8] & 127) << 7 | (d[9] & 127)) + (10 if d[5] & 16 else 0)
    while i + 4 <= len(d):
        h = struct.unpack(">I", d[i:i + 4])[0]
        ver, lay, bri, sri, pad = (h >> 19) & 3, (h >> 17) & 3, (h >> 12) & 15, (h >> 10) & 3, (h >> 9) & 1
        if (h >> 21) & 0x7FF != 0x7FF or lay != 1 or bri in (0, 15) or sri == 3 or ver == 1:
            if n == 0:
                i += 1
                continue
            break
        sr = RATES[ver][sri]
        spf = 1152 if ver == 3 else 576
        size = (144 if ver == 3 else 72) * BR[1 if ver == 3 else 2][bri] * 1000 // sr + pad
        if i + size > len(d):
            break
        n, i = n + 1, i + size
    return n * spf


def files(grid, W, path, file=""):
    """(the .DAT file, the .EXT file) as bytes. grid: beats.analyse's; W: its waveform slices; path: the song's
    place written inside (rekordbox_usb.py puts the USB's in when it copies them); file: the song on the Mac."""
    shift = int(round(grid["lead"] * beats.PER))  # rekordbox's clock runs this many slices later for this file
    W = np.concatenate([np.zeros((shift, 5), np.float32), W]) if shift else W
    if not len(W):
        W = np.zeros((1, 5), np.float32)
    pvbr = section(b"PVBR", struct.pack(">I", 0), bytes(1600) + struct.pack(">I", mp3_samples(file)))
    # the small overviews: rekordbox's blue one (400 columns) and the oldest decks' (100)
    C = columns(W, 400)
    top = C[:, 1].max() or 1
    h = np.clip(np.round(C[:, 1] / top * 25), 0, 31).astype(int)
    pwav = section(b"PWAV", struct.pack(">II", 400, 0x10000), bytes((fit(C, "w3w", 7) << 5 | h).astype(np.uint8)))
    C = columns(W, 100)
    pwv2 = section(b"PWV2", struct.pack(">II", 100, 0x10000),
                   bytes(np.clip(np.round(C[:, 1] / (C[:, 1].max() or 1) * 15), 0, 15).astype(np.uint8)))
    dat = whole([ppth(path), pvbr, pqtz(grid), pwav, pwv2, *cues()])
    # the detail waveforms, one value each 1/150 s: blue, then coloured; and the coloured overview (1200 columns)
    n = len(W)
    w3 = (fit(W, "w3w", 7) << 5 | fit(W, "w3h", 31)).astype(np.uint8)
    pwv3 = section(b"PWV3", struct.pack(">III", 1, n, 0x00960000), bytes(w3))
    w5 = (fit(W, "w5r", 7) << 13 | fit(W, "w5g", 7) << 10 | fit(W, "w5b", 7) << 7 | fit(W, "w5h", 31) << 2).astype(">u2")
    pwv5 = section(b"PWV5", struct.pack(">III", 2, n, 0x00960305), w5.tobytes())
    C = basis(columns(W, 1200))
    w4 = np.stack([np.clip(np.round(C @ np.array(c)), 0, 255 if i == 1 else 127) for i, c in enumerate(FIT["w4"])], 1)
    pwv4 = section(b"PWV4", struct.pack(">III", 6, 1200, 0), bytes(w4.astype(np.uint8).ravel()))
    pco2 = [section(b"PCO2", struct.pack(">IHH", t, 0, 0)) for t in (1, 0)]
    ext = whole([ppth(path), pwv3, *cues(), *pco2, pwv5, pwv4])
    return dat, ext


def engine_overview(W, samples):
    """Engine DJ's overview waveform (1024 columns of bass, mids and highs, then the loudest of each), as it keeps
    it before packing. Scaled as Engine 4 draws its own: the bass's loudest column at 255 (benched on a Prime 4
    library)."""
    C = columns(W, 1024) if len(W) else np.zeros((1024, 5))
    m = C[:, 2].max() or 1
    bands = np.stack([C[:, 2] / m * 255, C[:, 3] / m * 289, C[:, 4] / m * 195.5], 1)
    b = np.clip(np.round(bands), 0, 255).astype(np.uint8)
    return struct.pack(">qqd", 1024, 1024, samples / 1024) + b.tobytes() + bytes(b.max(0))


def rekordbox_grid(dat, ours):
    """rekordbox's own beat grid in an analysis file, as The Crate keeps a grid (beats.py), so Engine DJ gets the
    same beats rekordbox plays. ours: The Crate's grid of the song (its clock and length). None when the file has no
    grid, or one whose tempo changes along the song."""
    try:
        with open(dat, "rb") as f:
            d = f.read()
    except OSError:
        return None
    if d[:4] != b"PMAI" or len(d) < 12:
        return None
    o = struct.unpack(">I", d[4:8])[0]
    while 12 <= o and o + 12 <= len(d):
        four, head, size = d[o:o + 4], *struct.unpack(">II", d[o + 4:o + 12])
        if four == b"PQTZ" and head >= 24:
            n = struct.unpack(">I", d[o + 20:o + 24])[0]
            n = min(n, max(0, (len(d) - o - head) // 8))
            q = [struct.unpack(">HHI", d[o + head + 8 * i:o + head + 8 * i + 8]) for i in range(n)]
            if len(q) < 8 or len({b for _, b, _ in q}) != 1 or not q[0][1]:
                return None
            bpm = q[0][1] / 100
            P = 60 / bpm
            t0 = float(np.mean([ms / 1000 - i * P for i, (_, _, ms) in enumerate(q)]))  # (each beat is kept to the ms)
            return {**ours, "bpm": bpm, "first": round(t0 - beats.LATE - ours["lead"], 4), "bar": (1 - q[0][0]) % 4,
                    "from": "rekordbox"}
        if size < 12:
            break
        o += size
    return None
