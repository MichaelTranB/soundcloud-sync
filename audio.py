"""What a file really is (macOS's own afinfo, no extra tools): used to keep only top-quality audio."""
import re, subprocess

LOSSLESS = {"WAVE": "wav", "AIFF": "aiff", "AIFC": "aiff", "flac": "flac"}  # File type ID -> extension
LOSSY = {"MPG3": "mp3", "m4af": "m4a", "mp4f": "m4a", "adts": "aac"}


def info(path):
    """{'ext', 'lossless', 'kbps', 'secs'} for a real audio file, or None (HTML page, broken file, not audio)."""
    try:
        out = subprocess.run(["afinfo", path], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    ftype = re.search(r"^File type ID:\s*(\S+)", out, re.M)
    if not ftype or ftype.group(1) not in {**LOSSLESS, **LOSSY}:
        return None
    t = ftype.group(1)
    fmt = (re.search(r"^Data format:(.*)$", out, re.M) or [None, ""])[1]
    kbps = re.search(r"^bit rate:\s*(\d+)", out, re.M)
    secs = re.search(r"^estimated duration:\s*([\d.]+)", out, re.M)
    lossless = t in LOSSLESS or " alac " in fmt
    return {"ext": LOSSLESS.get(t) or LOSSY[t], "lossless": lossless,
            "kbps": round(int(kbps.group(1)) / 1000) if kbps else 0, "secs": float(secs.group(1)) if secs else 0}


def top_quality(i):
    """Lossless, or lossy at 320 kbps (afinfo reports 320 kbps as 319.999)."""
    return bool(i) and (i["lossless"] or i["kbps"] >= 318)
