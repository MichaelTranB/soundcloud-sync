"""The safety check: every file in the music folder must really be audio before it stays there or reaches the USB.

Downloads from Soulseek come from strangers, so a file is kept only when all of these hold:
  1. its name ends in an audio type (.flac .wav .aiff .aif .mp3 .m4a .aac): an .exe, .zip, .app, .dmg, .pkg,
     shortcut or script is never kept, whatever it calls itself;
  2. its first bytes are that audio type's own signature (a program renamed "song.flac" fails here);
  3. macOS's own audio reader (afinfo) opens it as that type, with a real length;
  4. the ClamAV virus scanner, when installed, finds nothing.
A file that fails is moved to the Quarantine folder beside the app (outside the music folder, so it is never
copied to the USB) with its "can run" permission removed, and the page says so. Files that pass lose any
"can run" permission too. Each file is checked once (by path, size and time); usb.sh copies only files on the
checked list.

  python3 safety.py check <app folder> <music folder>
"""
import fcntl, os, shutil, stat, subprocess, sys, time

import audio

AUDIO = {".flac": "flac", ".wav": "wav", ".aiff": "aiff", ".aif": "aiff", ".mp3": "mp3", ".m4a": "m4a", ".aac": "aac"}
OWN = {".DS_Store", ".index.sldl", ".localized", "To Buy.txt"}  # kept there by macOS, sockseek and sync.sh
BUSY = (".part", ".ytdl", ".incomplete", ".tmp")  # a download still being written: checked once it is finished
CLAM = [p for p in ("/opt/homebrew/bin/clamscan", "/usr/local/bin/clamscan", "/usr/local/clamav/bin/clamscan")
        if os.access(p, os.X_OK)]


def signature(path, kind):
    """True when the file starts the way a real file of this audio type does."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:3] == b"ID3" and kind in ("flac", "mp3", "aac"):  # a tag block first, then the audio
            if len(head) < 10:
                return False  # cut off inside its own tag: not a playable file
            size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
            f.seek(10 + size)
            body = f.read(4)
            if kind == "mp3":
                return True  # ID3 is how most MP3s start
            head = body
    if kind == "flac":
        return head[:4] == b"fLaC"
    if kind == "wav":
        return head[:4] in (b"RIFF", b"RF64", b"BW64") and head[8:12] in (b"WAVE", b"BW64")
    if kind == "aiff":
        return head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC")
    if kind == "mp3":
        return len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
    if kind == "m4a":
        return head[4:8] == b"ftyp"
    if kind == "aac":
        return len(head) > 1 and head[0] == 0xFF and head[1] & 0xF0 == 0xF0
    return False


def why_not(path):
    """'' when the file is real audio of the type its name says, else the plain reason it isn't."""
    name = os.path.basename(path)
    if os.path.islink(path):
        return "a shortcut, not a file"
    ext = os.path.splitext(name)[1].lower()
    kind = AUDIO.get(ext)
    if not kind:
        return f"not an audio file ({ext or 'no type'})"
    try:
        if not signature(path, kind):
            return f"named {ext} but isn't one inside"
    except OSError as e:
        return f"unreadable ({e.strerror})"
    except Exception:  # anything odd in the first bytes is a reason to block, never to stop the whole check
        return "broken or not audio inside"
    i = audio.info(path)
    if not i or i["secs"] <= 0:
        return "macOS can't play it as audio"
    if AUDIO[ext] != i["ext"] and not (kind == "m4a" and i["ext"] in ("m4a", "aac")):
        return f"named {ext} but is really {i['ext']}"
    return ""


def virus_scan(paths):
    """{path: virus name} for files ClamAV flags; None when the scanner couldn't run."""
    if not CLAM or not paths:
        return {}
    r = subprocess.run([CLAM[0], "--no-summary", "--infected", "--stdout", "--"] + paths,
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        return None
    found = {}
    for line in r.stdout.splitlines():
        if line.endswith(" FOUND") and ": " in line:
            p, v = line[:-6].rsplit(": ", 1)
            found[p] = v
    return found


def quarantine(d, path, reason, log):
    q = os.path.join(d, "Quarantine")
    os.makedirs(q, exist_ok=True)
    dest = os.path.join(q, f"{time.strftime('%Y%m%d-%H%M%S')} {os.path.basename(path)}")
    try:
        shutil.move(path, dest)
        if not os.path.islink(dest):
            os.chmod(dest, 0o600 if os.path.isfile(dest) else 0o700)
    except OSError:
        return  # already gone (another run moved it)
    log(f"BLOCKED {os.path.basename(path)}: {reason}. Moved to Quarantine.")


def check(d, music):
    stamp = time.strftime("%F %R")
    with open(os.path.join(d, "safety.log"), "a") as logf, open(os.path.join(d, ".safety.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        log = lambda m: logf.write(f"{stamp}  {m}\n")
        ok_path = os.path.join(d, "safety-ok.tsv")
        ok = {}
        try:
            with open(ok_path) as f:
                for line in f:
                    p, size, mtime = line.rstrip("\n").split("\t")
                    ok[p] = (int(size), int(mtime))
        except (OSError, ValueError):
            pass
        keep, new, blocked = {}, [], 0
        for root, dirs, files in os.walk(music):
            for dn in list(dirs):  # a linked folder could point anywhere on the Mac
                if os.path.islink(os.path.join(root, dn)):
                    dirs.remove(dn)
                    quarantine(d, os.path.join(root, dn), "a shortcut to another folder", log)
                    blocked += 1
            for fn in files:
                p = os.path.join(root, fn)
                if fn in OWN:
                    continue
                rel = os.path.relpath(p, music)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if fn.lower().endswith(BUSY) and time.time() - st.st_mtime < 6 * 3600:
                    continue
                sig = (st.st_size, int(st.st_mtime))
                if ok.get(rel) == sig:
                    keep[rel] = sig
                    continue
                reason = "a hidden file" if fn.startswith(".") else why_not(p)
                if reason:
                    quarantine(d, p, reason, log)
                    blocked += 1
                else:
                    new.append((rel, p, sig))
        found = virus_scan([p for _, p, _ in new])
        if found is None:  # not marked safe: they wait (and stay off the USB) until the scanner works again
            log(f"Virus scan FAILED to run (ClamAV): {len(new)} new file(s) wait, not copied to the USB, "
                "until it works again.")
            new = []
            found = {}
        for rel, p, sig in new:
            if p in found:
                quarantine(d, p, f"virus found ({found[p]})", log)
                blocked += 1
                continue
            mode = stat.S_IMODE(os.lstat(p).st_mode)
            if mode & 0o111:
                os.chmod(p, mode & ~0o111)  # a song never needs to run (this leaves its time unchanged)
            keep[rel] = sig
        tmp = ok_path + ".tmp"
        with open(tmp, "w") as f:
            f.writelines(f"{p}\t{s}\t{m}\n" for p, (s, m) in sorted(keep.items()))
        os.replace(tmp, ok_path)
        if new or blocked:
            log(f"checked {len(new) + blocked} new: {len(new) - sum(1 for _, p, _ in new if p in found)} kept, "
                f"{blocked} blocked" + ("" if CLAM else " (no virus scanner installed; audio check only)"))
    return blocked


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "check":
        sys.exit(__doc__)
    check(sys.argv[2], sys.argv[3])
