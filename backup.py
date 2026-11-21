#!/usr/bin/env python3
"""Keeps a copy of what your decks saved on your USB, on this Mac or in your iCloud Drive, and puts it back when a
USB goes wrong.

  Every time the USB is plugged in (usb.sh runs this first, before anything on it is changed), the USB's DJ libraries
  are copied to usb-backups/<the USB's name>/<day and time>/: rekordbox's (PIONEER: its lists, its history and the
  analysis files a club deck saves hot cues and memory cues in), Engine DJ's (Engine Library: the database a Prime
  saves cues, loops and playlists in) and Serato's (_Serato_). With them go the songs that are only on the USB (not
  in your music folder on this Mac), so a lost USB can be made whole again; your library's own songs come back from
  the Mac by the usual copy.
  It only READS the USB. Nothing changed since the last backup: nothing is copied. A file that didn't change is
  shared with the backup before it (a hard link), so ten backups cost little more than one.
  Each backup is checked: every file could be read, the Engine DJ database is sound, rekordbox's files are
  rekordbox's, a library that was there is still there. A backup that fails is kept but marked damaged, and never
  pushes out a good one (the last KEEP good ones stay, and the last BAD damaged ones).
  restore puts a backup back: first what is on the USB now is backed up, then each library file that differs is
  replaced and each backed-up song that is missing (or a different size) is copied back, then the usual copy
  (usb.sh) puts your library's songs and playlists on it again. Nothing else on the USB is touched and nothing is
  ever erased: a USB that can't be opened at all has to be erased by you first (Disk Utility), then restored.

  The place is a choice on the page: this Mac (above), or the person's own iCloud Drive, for a Mac that is short of
  room. There the files go to "The Crate/USB backups/<the USB's name>/<day and time>/files/" as they sit on the
  USB, and a file that didn't change is kept once, in the backup that first had it (iCloud has no shared files: the
  list beside each backup says which day holds each file). The small lists stay on this Mac, in usb-backups/, so
  the page never waits for iCloud. At plug-in only the libraries go (they are small, and they hold the cues); the
  songs that are only on the USB follow on their own (songs): a few at a time (on a Mac with less than RESERVE free,
  THROUGH at most waits here, and FLOOR always stays free), and each one gives its room on this Mac back once macOS
  says it is safely in iCloud. So a full USB fits through a Mac with little room. It carries on at the next plug-in
  if the USB is unplugged first. iCloud Drive off, or not to be opened: the backup is made on this Mac that time,
  and says so.
  Everything bound for iCloud Drive is gathered on this Mac first (usb-backups/<USB>/.up) and moved in whole, under
  its own name: never under a ".nosync" one, since macOS keeps a folder or file made under such a name out of iCloud
  for good, even after a rename (heal() rebuilds a backup an older version left that way). What is really uploaded
  is asked of macOS itself (look()), never assumed: the page and each backup's about.json say how much is in iCloud
  and how much still waits on this Mac.

  Or the person's own cloud (OneDrive, Dropbox or pCloud, owncloud.py, through rclone): laid out as in iCloud Drive,
  with no copy on this Mac at all. The libraries pass through a small folder on this Mac (usb-backups/<USB>/.up), are
  checked there and leave it once they are up; the songs go straight from the USB. Each file's sha256 is in the
  backup's sums.json, so a song on the USB that went bad (same size and time, other bytes) is still found (the songs
  pass checks the USB against it once per backup, slowly) and Repair puts the good copy back. A full cloud is said
  on the page, and the songs wait for room. "Off": no backup at plug-in.

  backup.py run DIR USB SRC                at plug-in, and the page's "Back up now"
  backup.py songs DIR USB SRC              started by run: the USB-only songs go up to iCloud Drive or the own cloud
  backup.py restore DIR USB SRC NAME DAY   the page's "Repair": the backup DAY of the USB called NAME, onto USB

Standard library only."""
import errno, fcntl, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, threading, time, unicodedata, urllib.parse

from concurrent.futures import ThreadPoolExecutor

import owncloud, usb_ask, usb_tidy

ROOT, SET, KEEP, BAD = "usb-backups", "usb-backup.json", 10, 2
PLACES, FAR = ("mac", "icloud", "own", "off"), ("icloud", "own")  # FAR: kept away from this Mac
WHERE = {"icloud": "iCloud Drive", "own": "your own cloud", "mac": "this Mac"}
RESERVE = int(os.environ.get("CRATE_BACKUP_RESERVE") or 20 * 1024 ** 3)  # the room that always stays free on this Mac
# iCloud Drive: songs pass through this Mac on their way up and leave it once they are up, so a Mac with less than
# RESERVE free still sends them, a batch of THROUGH at a time, as long as FLOOR stays free
FLOOR, THROUGH = RESERVE // 4, 2 * 1024 ** 3
LIBS = (("rekordbox", "pioneer"), ("Engine DJ", "engine library"), ("Serato", "_serato_"))
MAIN = (("rekordbox", "pioneer/rekordbox/export.pdb"), ("rekordbox", "pioneer/rekordbox/exportlibrary.db"),
        ("Engine DJ", "engine library/database2/m.db"))  # a library is gone when one of these was there and isn't
SKIP = usb_ask.SYSTEM + ("thrown back by the crate",)
# iCloud Drive on this Mac, and The Crate's folder in it (CRATE_ICLOUD: another folder stands in for it, for tests)
CLOUD = os.environ.get("CRATE_ICLOUD") or os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")
INSIDE = ("The Crate", "USB backups")
DATALESS = 0x40000000  # (stat.SF_DATALESS) a file whose content is in iCloud only: its name, size and time are here
# Asks macOS about each file in a list, one letter each: "x" kept out of iCloud (macOS's own "excluded from sync"),
# "-" not in iCloud Drive at all, "w" in iCloud Drive but not uploaded yet, "u" uploaded (its content still here),
# "e" uploaded and its room on this Mac given back just now (only asked with "free": macOS itself refuses that for a
# file that has not gone up, which is the safety), "?" macOS could not say.
JXA = """ObjC.import("Foundation");
function run(argv) {
  var out = "", fm = $.NSFileManager.defaultManager, free = argv[1] === "free";
  var keys = $(["NSURLIsUbiquitousItemKey", "NSURLUbiquitousItemIsUploadedKey", "NSURLUbiquitousItemIsExcludedFromSyncKey"]);
  var names = ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null)).split("\\n");
  for (var i = 0; i < names.length; i++) {
    if (!names[i]) continue;
    var u = $.NSURL.fileURLWithPath(names[i]), d = u.resourceValuesForKeysError(keys, null);
    var is = function (k) { return !!ObjC.unwrap(d.objectForKey(k)); };
    if (d.isNil()) out += "?";
    else if (is("NSURLUbiquitousItemIsExcludedFromSyncKey")) out += "x";
    else if (!is("NSURLIsUbiquitousItemKey")) out += "-";
    else if (!is("NSURLUbiquitousItemIsUploadedKey")) out += "w";
    else out += free && fm.evictUbiquitousItemAtURLError(u, null) ? "e" : "u";
  }
  return out;
}"""


def read(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write(path, data):
    with open(path + ".tmp", "w") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)


def load(dir):
    """The two settings, both on the page: songs that are only on the USB are kept too (on unless switched off), and
    the place the backups are kept: "mac", "icloud" (the person's own iCloud Drive), "own" (their own cloud,
    owncloud.py) or "off" (no backup at plug-in; a repair still keeps what is on the USB first, on this Mac). Not
    chosen yet: iCloud Drive when this Mac has it on (it spares this Mac the room), else this Mac."""
    cfg = read(os.path.join(dir, SET), {})
    cfg = cfg if isinstance(cfg, dict) else {}
    return {"songs": cfg.get("songs", True) is not False,
            "place": cfg.get("place") if cfg.get("place") in PLACES else "icloud" if os.path.isdir(CLOUD) else "mac"}


def save(dir, songs=None, place=None):
    cfg = load(dir)
    write(os.path.join(dir, SET), {"songs": cfg["songs"] if songs is None else bool(songs),
                                   "place": cfg["place"] if place is None else place if place in PLACES else "mac"})


def log(dir, text):
    with open(os.path.join(dir, "dj.log"), "a") as f:
        f.write(time.strftime("%F %R") + "  " + text + "\n")


def safe(name):
    return re.sub(r"[/\\:\0]", "_", name).strip(". ") or "USB"


def home(dir, name):
    return os.path.join(dir, ROOT, safe(name))


def cloud(wait=8):
    """The Crate's folder in iCloud Drive ("": iCloud Drive is off, or can't be opened on this Mac). Asked on the side
    and not waited for long: the first time, macOS may ask whether The Crate may use iCloud Drive, and until that is
    answered a backup is made on this Mac instead of standing still."""
    got = []

    def look():
        try:
            if os.path.isdir(CLOUD):
                to = os.path.join(CLOUD, *INSIDE)
                os.makedirs(to, exist_ok=True)
                os.listdir(to)
                got.append(to if os.access(to, os.W_OK) else "")
        except OSError:
            pass
    t = threading.Thread(target=look, daemon=True)
    t.start()
    t.join(wait)
    return got[0] if got else ""


def far(dir, place):
    """Where backups kept away from this Mac go now ("": nowhere, this time): The Crate's folder in iCloud Drive, or in
    the person's own cloud as rclone names it (owncloud.root)."""
    return cloud() if place == "icloud" else owncloud.root(dir) if place == "own" else ""


def has(dir, up, path, n):
    """A file a backup lists is where it is kept: in your own cloud, asked of the cloud (its size must be n); in iCloud
    Drive or on this Mac, the file is there (iCloud-only ones included)."""
    return owncloud.size(dir, path) == n if owncloud.ours(up) else os.path.isfile(path)


def sums_of(dir, name, day):
    """Your own cloud: the sha256 of each file a backup holds itself ({path on the USB: sha256}), taken from the USB as
    it went up. A song on the USB is checked against it (check), and a file had back for a repair."""
    got = read(os.path.join(home(dir, name), day, "sums.json"), {})
    return got if isinstance(got, dict) else {}


def spot(dir, name, day, rel, row, up=""):
    """Where a backup keeps one file. On this Mac: in its own day's folder. In iCloud Drive (a row with a fourth part,
    the day that holds the file): in that day's folder there."""
    if len(row) > 3:
        return "/".join([up or os.path.join(CLOUD, *INSIDE), safe(name), row[3], "files", rel])
    return os.path.join(home(dir, name), day, "files", *rel.split("/"))


def local(path):
    """A file that is there with its content on this Mac (one in iCloud Drive may be there in name only)."""
    try:
        return not os.stat(path).st_flags & DATALESS
    except (OSError, AttributeError):
        return False


def fetch(path):
    """Reads a file through, which brings one kept in iCloud Drive back onto this Mac. False: it can't be had now."""
    try:
        with open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except OSError:
        return False


def look(dir, paths, free=False):
    """What macOS says of each file in iCloud Drive: {path: letter} (JXA above). A file whose content is in iCloud
    only is "c" without asking (macOS gives a file's room back only once it is up). free: each one that is uploaded
    gives its room on this Mac back ("e"). macOS can't be asked: "?" for each (nothing is freed then)."""
    out, ask = {}, []
    for p in dict.fromkeys(paths):
        try:
            out[p] = "c" if os.stat(p).st_flags & DATALESS else ask.append(p) or "?"
        except OSError:
            out[p] = "?"
    if not ask:
        return out
    f = os.path.join(dir, ROOT, ".cloud.txt")
    try:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w") as o:
            o.write("\n".join(ask))
        got = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA, f] + ["free"] * bool(free), capture_output=True,
                             text=True, timeout=120 + len(ask) // 20)
        said = got.stdout.strip() if got.returncode == 0 else ""
        if len(said) == len(ask):
            out.update(zip(ask, said))
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        if os.path.exists(f):
            os.remove(f)
    return out


def evict(dir, paths):
    """Files that are safely in iCloud give their room on this Mac back. Returns how many did; None when this Mac
    can't be asked (then macOS frees the room itself, when it runs short: "Optimise Mac Storage")."""
    if not paths:
        return 0
    got = look(dir, paths, free=True)
    return None if all(v == "?" for v in got.values()) else sum(v == "e" for v in got.values())


def into(a, b):
    """Moves a file or folder made on this Mac into iCloud Drive in one step, so iCloud only ever sees it whole and
    under its own name."""
    os.makedirs(os.path.dirname(b), exist_ok=True)
    try:
        os.replace(a, b)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        shutil.move(a, b)  # (iCloud Drive on another disk than this Mac's lists: copied, then taken from here)


def heal(dir, up, name):
    """A backup's folder in iCloud Drive that macOS keeps out of iCloud (an older version gathered it under a
    ".nosync" name, and macOS keeps an item made under such a name out for good, even after a rename) is built
    again: fresh folders under the very same names, and each file MOVED into them (never copied, so it takes no
    room, and never deleted; only the empty old folders go, and a cut-short ".nosync" copy, which no list counts on).
    Returns how many backups were healed."""
    far = os.path.join(up, safe(name))
    try:
        tops = [os.path.join(far, d) for d in sorted(os.listdir(far)) if when(d) or d.endswith(" (moving)")]
    except OSError:
        return 0
    said, n = look(dir, [t for t in tops if not t.endswith(" (moving)")]), 0
    for top in tops:
        old = top if top.endswith(" (moving)") else top + " (moving)"
        top = old[:-len(" (moving)")]
        if said.get(top) == "x" and not os.path.exists(old):
            os.rename(top, old)
        elif not os.path.isdir(old):
            continue  # (one cut short before is carried on with)
        for root, dirs, names in os.walk(old):
            to = os.path.normpath(os.path.join(top, os.path.relpath(root, old)))
            os.makedirs(to, exist_ok=True)
            for f in names:
                if f.endswith(".nosync") or f == ".DS_Store":
                    os.remove(os.path.join(root, f))
                elif not os.path.lexists(os.path.join(to, f)):
                    os.rename(os.path.join(root, f), os.path.join(to, f))
        for root, dirs, names in os.walk(old, topdown=False):
            try:
                os.rmdir(root)  # (only when nothing is left in it)
            except OSError:
                pass
        n += 1
        if os.path.isdir(old):
            log(dir, f'BACKUP PROBLEM: "{name}": some files of the backup {os.path.basename(top)} could not be moved '
                f'back into iCloud: they are kept in "{old}".')
    if n:
        log(dir, f'backup: "{name}": {n} {"backup" if n == 1 else "backups"} in iCloud Drive that macOS had kept out of '
            "iCloud (an older version of The Crate gathered them under a .nosync name) are put right: they go up now.")
    return n


def quota():
    """The room left in the person's iCloud, in bytes (None: it can't be told, and nothing is held back for it)."""
    if os.environ.get("CRATE_ICLOUD"):
        return None
    try:
        got = re.match(r"\s*(\d+) bytes", subprocess.run(["brctl", "quota"], capture_output=True, text=True, timeout=20).stdout)
        return int(got.group(1)) if got else None
    except (OSError, subprocess.SubprocessError):
        return None


_ROOM = {"t": 0.0, "free": None}


def room(wait=0):
    """iCloud's free room, asked at most every few minutes, on the side: the page never waits for it."""
    if time.time() - _ROOM["t"] > 300:
        _ROOM["t"] = time.time()
        t = threading.Thread(target=lambda: _ROOM.update(free=quota()), daemon=True)
        t.start()
        t.join(wait)
    return _ROOM["free"]


def when(day):
    """A backup's folder name ("2026-11-19 140233") as the clock time it was made."""
    try:
        return int(time.mktime(time.strptime(day, "%Y-%m-%d %H%M%S")))
    except ValueError:
        return 0


def snaps(dir, name):
    """The backups kept of the USB with this name, newest first: each one's short note (about.json)."""
    out = []
    try:
        days = sorted(os.listdir(home(dir, name)), reverse=True)
    except OSError:
        return out
    for day in days:
        about = read(os.path.join(home(dir, name), day, "about.json"))
        if isinstance(about, dict) and when(day):
            out.append({**about, "id": day, "when": when(day)})
    return out


def files_of(dir, name, day):
    """Every file in one backup: {path on the USB: [size, time, kind]} (kind: "song", or the library it belongs to).
    The time is the file's own, as exact as the USB keeps it (in nanoseconds): two saves within one second differ."""
    got = read(os.path.join(home(dir, name), day, "manifest.json"), {})
    return got if isinstance(got, dict) else {}


def progress(dir, done=None, of=0, what=""):
    """While a backup or a restore runs the page shows how far it is. Called with no count: reads it (None: none)."""
    p = os.path.join(dir, ".backup-progress")
    if done is None:
        try:
            with open(p) as f:
                done, of, pid, what = f.read().split("\t")
            os.kill(int(pid), 0)
            return {"done": int(done), "of": int(of), "what": what}
        except (ValueError, OSError):
            return None
    with open(p + ".tmp", "w") as f:
        f.write(f"{done}\t{of}\t{os.getpid()}\t{what}")
    os.replace(p + ".tmp", p)


def key(name):
    return unicodedata.normalize("NFC", name).lower()


def library(src):
    """The songs in your music folder on this Mac, as (name, size): a USB file that matches one needs no backup."""
    return {(key(f), usb_tidy.size(os.path.join(root, f))) for root, _, names in os.walk(src) for f in names
            if f.lower().endswith(usb_tidy.AUDIO)}


def listing(usb, mine, songs=True):
    """What is worth keeping on the USB: {path: [size, time, kind]}, and what could not be looked at. Its own Trash,
    hidden files and the drive's system folders are left out, as are songs your music folder already has."""
    out, stuck = {}, []
    for root, dirs, names in os.walk(usb, onerror=lambda e: stuck.append(str(e.filename or ""))):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in SKIP)
        rel = os.path.relpath(root, usb).replace(os.sep, "/")
        rel = "" if rel == "." else rel + "/"
        lib = next((n for n, p in LIBS if rel.lower().startswith(p + "/")), "")
        for f in sorted(names):
            if f.startswith("."):
                continue
            audio = f.lower().endswith(usb_tidy.AUDIO)
            if not (audio and songs) and not (lib and not audio):
                continue
            try:
                st = os.stat(os.path.join(root, f))
            except OSError:
                stuck.append(rel + f)
                continue
            if audio and (key(f), st.st_size) in mine:
                continue
            out[rel + f] = [st.st_size, st.st_mtime_ns, "song" if audio else lib]
    return out, stuck


def sqlite_ok(path):
    try:
        with open(path, "rb") as f:
            if f.read(16) != b"SQLite format 3\0":
                return False
        db = sqlite3.connect("file:" + urllib.parse.quote(path) + "?mode=ro&immutable=1", uri=True)
        try:
            return db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            db.close()
    except (OSError, sqlite3.Error):
        return False


def pdb_ok(path):
    """rekordbox's export.pdb: four empty bytes, then its page size, and the file is whole pages."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
        page, size = int.from_bytes(head[4:8], "little"), os.path.getsize(path)
        return head[:4] == b"\0\0\0\0" and page >= 512 and page & (page - 1) == 0 and size >= page and size % page == 0
    except OSError:
        return False


def one_ok(dir, path):
    """rekordbox's newer library (exportLibrary.db) opens. It is locked, so this needs the private Python the tempo
    and key step installed; without it, only that the file is there and not empty. Opened as a copy: never the backup."""
    try:
        if os.path.getsize(path) < 4096:
            return False
        import dj
        if not os.path.exists(dj.PY):
            return True
        tmp = os.path.join(dir, ROOT, ".check.db")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        shutil.copyfile(path, tmp)
        try:
            code = ("import sys\nsys.path.insert(0, sys.argv[1])\ntry:\n    import rekordbox_usb, pyrekordbox\n"
                    "    from sqlalchemy import text\nexcept Exception:\n    sys.exit(0)\ntry:\n"
                    "    rekordbox_usb.opened(sys.argv[2]).session.execute(text('SELECT count(*) FROM sqlite_master')).fetchone()\n"
                    "except Exception:\n    sys.exit(3)\n")
            return subprocess.run([dj.PY, "-c", code, os.path.dirname(os.path.abspath(__file__)), tmp],
                                  capture_output=True, timeout=120).returncode != 3
        finally:
            for end in ("", "-wal", "-shm"):
                if os.path.exists(tmp + end):
                    os.remove(tmp + end)
    except (OSError, subprocess.SubprocessError):
        return True


def wrong(dir, rel, path):
    """Why a library file just read from the USB can't be right ("" when it looks fine)."""
    low = rel.lower()
    if low.startswith("engine library/") and low.endswith(".db"):
        return "" if sqlite_ok(path) else "its Engine DJ library is damaged"
    if low == "pioneer/rekordbox/export.pdb":
        return "" if pdb_ok(path) else "its rekordbox library is damaged"
    if low == "pioneer/rekordbox/exportlibrary.db":
        return "" if one_ok(dir, path) else "its rekordbox library is damaged"
    if low.startswith("pioneer/usbanlz/") and low.endswith((".dat", ".ext", ".2ex")):
        try:
            with open(path, "rb") as f:
                return "" if f.read(4) == b"PMAI" else "some of its rekordbox analysis files (cues, waveforms) are damaged"
        except OSError:
            return "some of its rekordbox analysis files (cues, waveforms) are damaged"
    return ""


def link(old, new):
    try:
        os.link(old, new)
    except OSError:
        shutil.copy2(old, new)


def copy(a, b, mtime):
    shutil.copyfile(a, b)
    os.utime(b, ns=(mtime, mtime))


def weigh(folder):
    """How much room a USB's backups take on this Mac (a file shared by several backups counts once)."""
    seen = {}
    for root, _, names in os.walk(folder):
        for f in names:
            try:
                st = os.lstat(os.path.join(root, f))
                seen[st.st_ino] = st.st_size
            except OSError:
                pass
    return sum(seen.values())


def note(dir, name, **new):
    """What is remembered about a USB's backups beside the backups (state.json): when it was last looked at, the room
    they take, and "repair": the good backup to put back since it was last seen damaged. A value of None forgets."""
    p = os.path.join(home(dir, name), "state.json")
    got = read(p, {})
    got = got if isinstance(got, dict) else {}
    if new:
        got = {k: v for k, v in {**got, **new}.items() if v is not None}
        if os.path.isdir(home(dir, name)):
            write(p, got)
    return got


def fine(dir, name):
    """"It's fine": a USB seen damaged is no longer offered a repair, and its warning goes. The next backup that
    finds something wrong says so again."""
    got = snaps(dir, name)
    note(dir, name, repair=None, fine=got[0]["id"] if got and not got[0].get("ok") else None)
    log(dir, f'backup: "{name}" is fine as it is, you said.')


def prune(dir, name, keep=""):
    keep, good, bad, out = {keep, (note(dir, name).get("repair") or {}).get("day")}, 0, 0, []
    for s in snaps(dir, name):
        good, bad = good + bool(s.get("ok")), bad + (not s.get("ok"))
        if s["id"] not in keep and (good > KEEP if s.get("ok") else bad > BAD):
            at = os.path.join(home(dir, name), s["id"])
            for f in os.listdir(at) if os.path.isdir(at) else ():
                # your own cloud: its sha256s stay while a kept backup may still count on its files (sweep_own)
                if not (s.get("place") == "own" and f == "sums.json"):
                    p = os.path.join(at, f)
                    shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
            try:
                os.rmdir(at)
            except OSError:
                pass
            out += [(s.get("place"), s["id"])]
    sweep(dir, name, [d for p, d in out if p == "icloud"])
    sweep_own(dir, name, [d for p, d in out if p == "own"])


def sweep(dir, name, out=()):
    """A backup that was pushed out leaves iCloud Drive too: each file in its folder that no kept backup still counts
    on. Only ever in the folders of backups this Mac itself pushed out (never one it doesn't know), and not at all
    while iCloud Drive can't be opened or a kept backup's list can't be read: then it waits for the next time."""
    old = sorted(d for d in set(note(dir, name).get("old") or []) | set(out) if isinstance(d, str) and when(d))
    if not old:
        return
    up, used, nfc = cloud(), set(), lambda t: unicodedata.normalize("NFC", t)
    sure = bool(up)
    for s in snaps(dir, name):
        if s.get("place") == "icloud":
            rows = files_of(dir, name, s["id"])
            sure = sure and (bool(rows) or not s.get("files"))
            used |= {(row[3], nfc(rel)) for rel, row in rows.items() if len(row) > 3}
    left = [] if sure else old
    for day in old if sure else ():
        top = os.path.join(up, safe(name), day)
        for root, _, names in os.walk(os.path.join(top, "files"), topdown=False):
            for f in names:
                rel = os.path.relpath(os.path.join(root, f), os.path.join(top, "files")).replace(os.sep, "/")
                if (day, nfc(rel)) not in used:
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass
            try:
                os.rmdir(root)  # (only when nothing is left in it)
            except OSError:
                pass
        for f in ("manifest.json", "about.json", ".DS_Store"):  # it is no backup any more, only a holder of files
            if os.path.isfile(os.path.join(top, f)):
                os.remove(os.path.join(top, f))
        try:
            os.rmdir(top)
        except OSError:
            pass
        if os.path.isdir(top):
            left.append(day)  # a kept backup still counts on files in it: looked at again next time
    note(dir, name, old=left or None)


def sweep_own(dir, name, out=()):
    """sweep() for your own cloud: a pushed-out backup's files leave it, each that no kept backup still counts on, asked
    of the cloud itself; never while the cloud can't be asked or a kept backup's list can't be read."""
    old = sorted(d for d in set(note(dir, name).get("old_own") or []) | set(out) if isinstance(d, str) and when(d))
    if not old:
        return
    up, used, nfc = far(dir, "own"), set(), lambda t: unicodedata.normalize("NFC", t)
    sure = bool(up)
    for s in snaps(dir, name):
        if s.get("place") == "own":
            rows = files_of(dir, name, s["id"])
            sure = sure and (bool(rows) or not s.get("files"))
            used |= {(row[3], nfc(rel)) for rel, row in rows.items() if len(row) > 3}
    there = owncloud.listing(dir, os.path.join(up, safe(name)), fresh=True) if sure else None
    if there is None:
        note(dir, name, old_own=old)
        return
    left = []
    for day in old:
        pre = nfc("/".join([up, safe(name), day]) + "/")  # (the listing's names are NFC: a USB called "Café" too)
        mine = [p for p in there if nfc(p).startswith(pre)]
        stay = [p for p in mine if nfc(p).startswith(pre + "files/") and (day, nfc(p)[len(pre) + 6:]) in used]
        if owncloud.drop(dir, [p for p in mine if p not in stay]) or stay:
            left.append(day)  # a kept backup still counts on files in it (or one could not go): looked at next time
        else:  # nothing of it is left in the cloud: its sha256s, kept by prune(), go too
            at = os.path.join(home(dir, name), day)
            if not os.path.isfile(os.path.join(at, "about.json")):
                shutil.rmtree(at, ignore_errors=True)
    note(dir, name, old_own=left or None)


SAID = {"full": "your own cloud is full: make room there (or get more), and the backup carries on by itself",
        "signin": "your own cloud needs you to sign in again (Options, My own cloud)",
        "net": "your own cloud could not be reached (is this Mac online?): tried again later"}

_ASKED = {}
_REFUSED = set()  # (USB, song) the own cloud refused this run: logged once


def tally(dir, name, up, pool, lists, free=True, every=300):
    """What of a USB's backups in iCloud Drive is really in iCloud, asked of macOS (look), never assumed: every file a
    kept backup counts on. Each song that is up gives its room on this Mac back (free). Each backup's about.json gets
    "sent" (bytes in iCloud) and "unsent" (bytes only on this Mac so far). Returns {"sent", "unsent", "out": bytes
    macOS keeps out of iCloud, "here": files still to go up or to leave this Mac, "freed", "asked": when}, or None
    when it was asked less than `every` seconds ago (asking takes a while on many files)."""
    if time.time() - _ASKED.get(name, 0) < every:
        return None
    _ASKED[name] = time.time()
    size, lib = {}, set()
    for s in pool:
        for rel, row in lists[s["id"]].items():
            if len(row) > 3:
                size[spot(dir, name, s["id"], rel, row, up)] = row[0]
                if row[2] != "song":
                    lib.add(spot(dir, name, s["id"], rel, row, up))
    own = owncloud.ours(up)
    if own:  # your own cloud: what its own listing shows, at the size the backup lists ("u"), or not yet ("w")
        there = owncloud.listing(dir, os.path.join(up, safe(name)), fresh=True)
        said = {p: "?" if there is None else "u" if there.get(owncloud.nfc(p)) == n else "w" for p, n in size.items()}
    else:
        # Only songs give their room back: the decks' libraries (under a GB, but thousands of small files that iCloud
        # hands back slowly) stay on this Mac too, so a repair takes minutes, not hours
        said = look(dir, [p for p in size if p not in lib], free=free)
        said.update(look(dir, [p for p in size if p in lib]))
    if size and all(v == "?" for v in said.values()):
        return None  # macOS can't be asked now: what was said last stands
    got = {"sent": sum(size[p] for p, v in said.items() if v in "cue"), "freed": sum(v == "e" for v in said.values()),
           "unsent": sum(size[p] for p, v in said.items() if v not in "cue"),
           "out": sum(size[p] for p, v in said.items() if v == "x"),
           "here": 0 if own else sum(v not in ("cue" if p in lib else "ce") for p, v in said.items()),
           "asked": int(time.time())}
    # (a library file counts until it is up: it stays on this Mac then)
    # ("here" counts every file not yet off this Mac, one iCloud hasn't registered yet ("-") or couldn't say ("?")
    # included: the songs job keeps asking until each is up and gone from here, or a day passes with no change)
    for s in pool:
        at = os.path.join(home(dir, name), s["id"], "about.json")
        about, mine = read(at, {}), [spot(dir, name, s["id"], rel, row, up) for rel, row in lists[s["id"]].items()
                                     if len(row) > 3]
        sent = sum(size[p] for p in mine if said.get(p, "?") in "cue")
        new = {"sent": sent, "unsent": sum(size[p] for p in mine) - sent}
        if isinstance(about, dict) and about and {k: about.get(k) for k in new} != new:
            write(at, {**about, **new})
            twin(dir, name, s["id"], up)
    return got


def lifted(dir, name):
    """How much of a USB's backups is kept in the cloud the newest one went to (a file kept once counts once)."""
    seen, got = {}, snaps(dir, name)
    far = next((s.get("place") for s in got if s.get("place") in FAR), None)  # the newest one kept in a cloud
    for s in got:
        if s.get("place") in FAR and s.get("place") == far:
            seen.update({(row[3], rel): row[0] for rel, row in files_of(dir, name, s["id"]).items() if len(row) > 3})
    return sum(seen.values())


def say(names):
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1] if names else ""


def run(dir, usb, src, keep="", fail=None):
    """One backup of the USB, when anything on it changed since the last one. Returns that backup's note. fail: a
    list that gets the reason when what is on the USB now could not be kept (restore() then changes nothing)."""
    name = os.path.basename(os.path.normpath(usb))
    os.makedirs(os.path.join(dir, ROOT), exist_ok=True)
    with open(os.path.join(dir, ".backup.lock"), "w") as lock, open(os.path.join(dir, ".dj.lock"), "a") as deck:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one at a time; a second one waits and then finds nothing left to do
        # No deck library is written while it is read (dj.py's lock, shared: dj.py waits until the backup is done),
        # so a backup never holds a library from half way through an update.
        fcntl.flock(deck, fcntl.LOCK_SH)
        try:
            return _run(dir, usb, src, name, keep, [] if fail is None else fail)
        finally:
            if os.path.exists(os.path.join(dir, ".backup-progress")):
                os.remove(os.path.join(dir, ".backup-progress"))


def _run(dir, usb, src, name, keep, fail):
    at, got = home(dir, name), snaps(dir, name)
    last = got[0] if got else None
    before = files_of(dir, name, last["id"]) if last else {}
    cfg = load(dir)
    up = far(dir, cfg["place"])  # (iCloud Drive or your own cloud chosen but not to be had now: this Mac, this time)
    own = owncloud.ours(up)
    top, tail = os.path.join(up, safe(name)) if up else "", cfg["place"] if up else "mac"
    if up and not own:
        heal(dir, up, name)
    # A backup builds on the newest one kept in the same place: what didn't change since is shared with it
    base = next((s for s in got if (s.get("place") or "mac") == tail), None)
    # In iCloud Drive a file is kept once, by the backup that first held it: every backup kept there is looked at, so
    # a song that was away for one backup (or put back by a repair) doesn't go up a second time
    pool, old, was = [s for s in got if s.get("place") == tail] if up else [base] if base else [], {}, {}
    for s in reversed(pool):  # (the newest one's word counts)
        rows = before if s is last else files_of(dir, name, s["id"])
        old.update(rows)
        was.update({r: (s.get("bad") or {}).get(r) for r in rows})  # a copy that read as damaged still does
    seen, stuck = listing(usb, library(src), cfg["songs"])
    if not seen and not last:
        return None  # an empty USB with no backup yet: nothing to keep
    held = lambda rel, row: (rel in old and old[rel][:2] == row[:2]
                             and has(dir, up, spot(dir, name, base["id"], rel, old[rel], up), old[rel][0]))
    new = lambda rows: sum(v[0] for r, v in rows.items() if old.get(r, [])[:2] != v[:2])
    skipped, waiting, free = [], {}, shutil.disk_usage(dir).free
    if cfg["place"] in FAR and not up:
        # (its songs wait for the cloud: they are the room this Mac is spared)
        seen = {r: v for r, v in seen.items() if v[2] != "song"}
        skipped.append(("iCloud Drive could not be opened" if cfg["place"] == "icloud" else
                        "your own cloud is not signed in") + ": this backup is on this Mac, without the songs that are "
                       "only on the USB")
    if up:
        # iCloud Drive: only the libraries now (they are small, and they hold the cues). The songs that are only on
        # the USB go up after this, as this Mac has room (songs below), so plugging in never waits for them.
        waiting = {r: v for r, v in seen.items() if v[2] == "song" and not held(r, v)}
    elif free - new(seen) < RESERVE:  # the libraries always go first: they are small, and they hold the cues
        songs = [r for r, v in seen.items() if v[2] == "song"]
        seen = {r: v for r, v in seen.items() if v[2] != "song"}
        skipped.append(f"{len(songs)} songs that are only on it were left out: this Mac is short of room")
    if free - new({r: v for r, v in seen.items() if r not in waiting}) < RESERVE // 10:
        log(dir, f'BACKUP PROBLEM: "{name}" was not backed up: this Mac has no room left for it.')
        fail.append("this Mac has no room left for it")
        return None
    skipped = "; ".join(skipped)
    mark = hashlib.sha1(json.dumps([sorted(seen.items()), sorted(stuck)]).encode()).hexdigest()
    # Nothing on it changed since the last backup: that one stands. Unless a file could not be read then: it is
    # tried again every time, so a read that only failed once doesn't leave the backup short for good.
    if (last and base is last and last.get("seen") == mark and not last.get("unread")
            and (not up or (owncloud.isdir(dir, os.path.join(top, last["id"])) if own
                            else os.path.isdir(os.path.join(top, last["id"]))))):
        note(dir, name, checked=int(time.time()))
        return last
    t = int(time.time())
    stamp = lambda: time.strftime("%Y-%m-%d %H%M%S", time.localtime(t))
    while os.path.exists(os.path.join(at, stamp())) or (up and (owncloud.isdir(dir, os.path.join(top, stamp())) if own
                                                                else os.path.exists(os.path.join(top, stamp())))):
        t += 1  # (two backups within one second: each gets a folder of its own)
    day, part = time.strftime("%Y-%m-%d %H%M%S", time.localtime(t)), os.path.join(at, ".part")
    # For iCloud Drive the files are gathered on this Mac and moved in whole once they all are (into); for your own
    # cloud they are sent from there, and leave this Mac as each one is up (owncloud.send)
    box = os.path.join(at, ".up") if up else part
    for d in {part, box} | ({os.path.join(top, ".part.nosync")} if up and not own else set()):
        shutil.rmtree(d, ignore_errors=True)  # (what a backup cut short left behind; .part.nosync: an older version's)
    files, bad, unread, sums = {}, {}, list(stuck), {}
    todo = sorted((rel, row) for rel, row in seen.items() if rel not in waiting)

    def stands(rel, row):  # the copy the backup before has stands for this one too
        if up:
            files[rel] = [*row[:3], old[rel][3]]
        else:
            os.makedirs(os.path.dirname(to), exist_ok=True)
            link(spot(dir, name, base["id"], rel, old[rel]), to)
            files[rel] = row
    for i, (rel, row) in enumerate(todo):
        if i % 20 == 0:
            progress(dir, i, len(todo), "backup")
        to = os.path.join(box, "files", *rel.split("/"))
        if held(rel, row):
            stands(rel, row)
            if was.get(rel):
                bad[rel] = was[rel]
            continue
        try:
            os.makedirs(os.path.dirname(to), exist_ok=True)
            copy(os.path.join(usb, *rel.split("/")), to, row[1])
            if os.path.getsize(to) != row[0]:
                raise OSError("cut short")
            files[rel] = row + [day] * bool(up)
            why = wrong(dir, rel, to) if row[2] != "song" else ""
            sums[rel] = owncloud.sha256(to) if own else None
            if why:  # a library that changed under the copy reads as damaged: once more
                st = os.stat(os.path.join(usb, *rel.split("/")))
                row = [st.st_size, st.st_mtime_ns, row[2]]
                files[rel] = row + [day] * bool(up)
                copy(os.path.join(usb, *rel.split("/")), to, row[1])
                why = wrong(dir, rel, to)
                sums[rel] = owncloud.sha256(to) if own else None
            if why:
                bad[rel] = why
        except OSError:
            if not os.path.isdir(usb):  # unplugged half way: no backup this time, the last one stands
                for d in {part, box}:
                    shutil.rmtree(d, ignore_errors=True)
                log(dir, f'backup: "{name}" was unplugged before its backup was done. It is made the next time.')
                fail.append("it was unplugged")
                return last
            unread.append(rel)
            if os.path.exists(to):
                os.remove(to)
            files.pop(rel, None)
            sums.pop(rel, None)
            if rel in old and has(dir, up, spot(dir, name, base["id"], rel, old[rel], up), old[rel][0]):
                stands(rel, old[rel])  # the last copy that could be read stays in the backup
    if last and base is last and last.get("seen") == mark and sorted(unread) == last.get("unread") and files == before:
        for d in {part, box}:
            shutil.rmtree(d, ignore_errors=True)  # (tried again, and it still can't be read: the last backup stands)
        note(dir, name, checked=int(time.time()))
        return last
    low = {r.lower() for r in files}
    why = sorted(set(bad.values()))
    # gone: a library's main file was there and isn't, or (Serato has no one main file) every file of it is gone
    gone = [lib for lib, p in MAIN if p in {r.lower() for r in before} and p not in low]
    gone += [lib for lib, _ in LIBS if any(v[2] == lib for v in before.values())
             and not any(v[2] == lib for v in files.values())]
    why += [f"its {lib} library is gone" for lib in dict.fromkeys(gone) if f"its {lib} library is damaged" not in why]
    if unread:
        why.append(f"{len(unread)} {'file' if len(unread) == 1 else 'files'} on it could not be read")
    libs = [n for n, _ in LIBS if any(v[2] == n for v in files.values())]
    about = {"name": name, "ok": not why, "why": "; ".join(why), "bad": bad, "seen": mark, "libs": libs,
             "songs": sum(1 for v in files.values() if v[2] == "song"), "files": len(files),
             "bytes": sum(v[0] for v in files.values()), "skipped": skipped, "unread": sorted(unread),
             "place": tail, "waiting": len(waiting)}
    os.makedirs(part, exist_ok=True)
    write(os.path.join(part, "manifest.json"), files)
    write(os.path.join(part, "about.json"), about)
    if up:
        write(os.path.join(part, "waiting.json"), waiting)
        os.makedirs(box, exist_ok=True)
        if own:
            write(os.path.join(part, "sums.json"), {r: h for r, h in sums.items() if h})
            err = owncloud.send(dir, box, os.path.join(top, day))
            if err:  # none of it counts: the last backup stands, and what got there is cleared away later (sweep_own)
                for d in {part, box}:
                    shutil.rmtree(d, ignore_errors=True)
                note(dir, name, old_own=sorted(set(note(dir, name).get("old_own") or []) | {day}),
                     up={**(note(dir, name).get("up") or {}), "why": err.split(":")[0], "said": err, "at": int(time.time())})
                log(dir, f'BACKUP PROBLEM: "{name}" was not backed up to your own cloud: ' + SAID.get(err.split(":")[0], "")
                    + f" ({err.split(': ', 1)[-1]})")
                fail.append("your own cloud could not take it")
                return last
        else:
            into(box, os.path.join(top, day))
    os.rename(part, os.path.join(at, day))
    twin(dir, name, day, up)
    prune(dir, name, keep)
    # (songs that went up before and haven't left this Mac yet still count: after() sends them off, with or without
    # new songs to go up)
    was = note(dir, name).get("up") or {}
    note(dir, name, checked=int(time.time()), size=weigh(at), kept=lifted(dir, name), cloud=None,
         up={**was, "left": len(waiting), "here": was.get("here") or 0, "why": "", "said": "", "at": int(time.time())}
         if up else None)
    good = next((s for s in snaps(dir, name) if s.get("ok")), None)
    if why and good and not note(dir, name).get("repair"):
        # it stays "to repair" until a backup is put back or you say it's fine: a USB you erased gets new, empty
        # libraries from the next copy, which look sound but hold none of your cues
        note(dir, name, repair={"day": good["id"], "why": about["why"], "when": int(time.time())})
    if why:
        log(dir, f'BACKUP PROBLEM: "{name}" looks damaged ({about["why"]}). ' + (
            f'Its last good backup is from {time.strftime("%b %-d, %H:%M", time.localtime(good["when"]))}: '
            "Repair on the Library Manager page puts it back." if good else "There is no good backup of it yet."))
        if not os.environ.get("VOLUMES") and good:
            subprocess.run(["osascript", "-e", f'display notification "{name} looks damaged. Open the Library Manager '
                            'to repair it from its last backup." with title "The Crate"'], capture_output=True)
    else:
        n = about["songs"]
        log(dir, f'backup: "{name}" backed up to {WHERE[tail]} ({say(libs) or "no DJ library on it"}'
            + (f", {n} {'song' if n == 1 else 'songs'} that {'is' if n == 1 else 'are'} only on it" if n else "")
            + (f", {len(waiting)} more {'song goes' if len(waiting) == 1 else 'songs go'} up next" if waiting else "")
            + (")" if not skipped else "). " + skipped[0].upper() + skipped[1:] + "."))
    return {**about, "id": day, "when": when(day)}


def twin(dir, name, day, up):
    """A backup in iCloud Drive or your own cloud carries a copy of its lists, so its folder there says by itself what
    it holds (and, in your own cloud, each file's sha256)."""
    for f in ("manifest.json", "about.json", "sums.json") if up else ():
        a = os.path.join(home(dir, name), day, f)
        try:
            if owncloud.ours(up):
                if os.path.isfile(a):
                    owncloud.put(dir, a, "/".join([up, safe(name), day, f]))
            elif f != "sums.json":
                shutil.copyfile(a, os.path.join(up, safe(name), day, f))
        except OSError:
            pass


def alive(dir, name=None):
    """This USB's songs (any USB's, with no name) are on their way up to iCloud Drive right now: songs below is at
    work. Each USB has a pass of its own (.backup-songs-<USB>), so a second USB never waits for the first one's."""
    try:
        mark = ".backup-songs-" + (safe(name) if name else "")
        found = [mark] if name else [n for n in os.listdir(dir) if n.startswith(mark)]
    except OSError:
        return False
    for n in found:
        try:
            with open(os.path.join(dir, n)) as f:
                os.kill(int(f.read()), 0)
            return True
        except (OSError, ValueError):
            pass
    return False


def songs(dir, usb, src=""):
    """iCloud Drive or your own cloud: the songs that are only on the USB go up after its libraries, in short turns
    (_songs), so a backup at plug-in or a repair never waits long for it. It ends when every song is up (and, for
    iCloud, off this Mac), when your own cloud needs a sign-in again,
    when the USB is unplugged (it carries on at the next plug-in), or after a day in which nothing moved (a full
    iCloud is waited for that long: room made there is seen within minutes, and the songs carry on)."""
    name = os.path.basename(os.path.normpath(usb))
    p = os.path.join(dir, ".backup-songs-" + safe(name))
    if alive(dir, name):
        return
    with open(p, "w") as f:
        f.write(str(os.getpid()))
    try:
        idle, skip, start = 0, set(), ((snaps(dir, name) or [{}])[0]).get("waiting")
        with open(os.path.join(dir, ".backup.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            up = cloud() if load(dir)["place"] == "icloud" else ""
            if up:
                heal(dir, up, name)  # (a backup an older version left out of iCloud goes up now)
        why = ""
        while idle < 2880:
            with open(os.path.join(dir, ".backup.lock"), "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                moved, left = _songs(dir, usb, name, skip)
            why = (note(dir, name).get("up") or {}).get("why")
            if not left or why == "signin":  # (a sign-in only you can give: the next plug-in tries again)
                break
            idle = 0 if moved else idle + 1
            if not moved:
                time.sleep(30)
        end = (snaps(dir, name) or [{}])[0]
        if skip and os.path.isdir(usb):
            log(dir, f'BACKUP PROBLEM: "{name}": {len(skip)} {"song" if len(skip) == 1 else "songs"} that '
                f'{"is" if len(skip) == 1 else "are"} only on it could not be read, so '
                f'{"it is" if len(skip) == 1 else "they are"} not in {WHERE.get(end.get("place"), "the cloud")} yet. '
                'Tried again at the next backup.')
        if start and end.get("place") in FAR and not end.get("waiting"):
            log(dir, f'backup: "{name}": every song that is only on it is in {WHERE[end["place"]]} now ({end.get("songs", 0)}).')
        if end.get("place") == "own" and not end.get("waiting") and why != "signin":
            check(dir, usb, name)
        if end.get("place") == "icloud":
            homeward(dir, name)
    finally:
        try:
            with open(p) as f:
                mine = f.read() == str(os.getpid())
            if mine:
                os.remove(p)
        except OSError:
            pass


def homeward(dir, name):
    """The newest iCloud backup's library files that are in iCloud only (an older version, or macOS short of room,
    gave their room back) come back onto this Mac, a few at a time: a repair then needs nothing from iCloud but the
    songs. Returns how many came back."""
    up = cloud()
    last = next((s for s in snaps(dir, name) if s.get("place") == "icloud"), None)
    if not up or not last:
        return 0
    away = [a for a in (spot(dir, name, last["id"], rel, row, up) for rel, row in files_of(dir, name, last["id"]).items()
                        if len(row) > 3 and row[2] != "song") if os.path.isfile(a) and not local(a)]
    with ThreadPoolExecutor(16) as pool:
        return sum(pool.map(fetch, away))


def fits(free, size, queued):
    """A song of SIZE may pass through this Mac on its way to iCloud now (free: this Mac's room; queued: what already
    waits on it to go up)."""
    return free - size >= RESERVE or (free - size >= FLOOR and (not queued or queued + size <= THROUGH))


def _songs(dir, usb, name, skip, turn=20):
    """One short turn of songs(): returns (something moved, how much it can still do)."""
    kept = snaps(dir, name)
    last = kept[0] if kept else None
    place = load(dir)["place"]
    up = far(dir, place) if last and last.get("place") == place else ""
    if not up:
        return False, 0
    own = owncloud.ours(up)
    pool = [s for s in kept if s.get("place") == place]  # (the newest first)
    lists = {s["id"]: files_of(dir, name, s["id"]) for s in pool}
    # Room first: what macOS says is safely in iCloud leaves this Mac. Every backup kept there is looked through, not
    # just the newest: a song the USB lost since is still in an older one.
    was = note(dir, name).get("up") or {}
    seen = tally(dir, name, up, pool, lists)
    here, freed = (seen["here"], seen["freed"]) if seen else (was.get("here") or 0, 0)
    why, said, did, rest, left0, tmp = "", "", False, 0, 0, os.path.join(home(dir, name), ".up-song")
    if own:  # your own cloud: straight from the USB, nothing of it on this Mac; the room that counts is the cloud's
        free, left, t0, margin = float("inf"), owncloud.free(dir), time.time(), 0
    else:
        # (a song is copied on this Mac first, into .up-song: the room that counts is the smaller of both disks)
        free, left, t0 = min(shutil.disk_usage(up).free, shutil.disk_usage(home(dir, name)).free), room(30), time.time()
        margin = 1024 ** 3
    # (iCloud: what waits on this Mac to go up, kept out of iCloud by macOS aside; it grows by each song put in below)
    queued = 0 if own else max(((seen or was).get("unsent") or 0) - ((seen or was).get("out") or 0), 0)
    # What iCloud Drive holds by now, by its place on the USB, its size and its time: {...: the day that holds it}
    have = {(rel, row[0], row[1]): row[3] for s in reversed(pool) for rel, row in lists[s["id"]].items() if len(row) > 3}
    # The newest backup's waiting songs go up, and then what an older one kept there still waits for: a song the copy
    # to the USB replaced before it went up is in no newer backup's list, and is kept by the one that listed it.
    for n, s in enumerate(pool):
        day, at = s["id"], os.path.join(home(dir, name), s["id"])
        waiting = read(os.path.join(at, "waiting.json"), {})
        waiting = waiting if isinstance(waiting, dict) else {}
        files, got, sums = lists[day], {}, sums_of(dir, name, day) if own else {}
        newest = waiting if not n else newest
        for rel, row in sorted(waiting.items()):
            mark = (day, rel) if n else rel
            if mark in skip:
                continue
            if why or time.time() - t0 > turn:
                rest += 1  # (not looked at this turn)
                continue
            if n:
                d = have.get((rel, row[0], row[1]))
                if d and has(dir, up, spot(dir, name, day, rel, row[:3] + [d], up), row[0]):
                    got[rel] = row[:3] + [d]  # a newer backup took it up: kept once, counted on by both
                    continue
            a = os.path.join(usb, *rel.split("/"))
            try:
                st = os.stat(a)
                moved = [st.st_size, st.st_mtime_ns] != row[:2]
            except (FileNotFoundError, NotADirectoryError):
                moved = True
            except OSError:
                if not os.path.isdir(usb):
                    why = "unplugged"
                    rest += 1
                    continue
                skip.add(mark)  # it is there but can't be read now: it stays on the list, tried again at the next plug-in
                continue
            if moved:
                if not os.path.isdir(usb):
                    why = "unplugged"
                    rest += 1
                    continue
                # Gone or changed since the backup listed it. The copy to the USB does that (the library's own file in
                # its place, a double taken off): what was there is in the USB's Trash then, and is kept from there.
                a = binned(usb, rel, row)
                if not a:
                    got[rel] = None  # nothing of it left to keep: the next backup lists what is there now
                    continue
            elif n:
                # Still on the USB as it was: the newest backup's to take up (seen again here once it has). One it
                # doesn't list any more is in your music folder now, or songs are no longer kept: nothing to do.
                if (newest.get(rel) or [])[:2] != row[:2]:
                    got[rel] = None
                continue
            if left is not None and left - row[0] < margin:
                why = "full"
                rest += 1
                continue
            if not fits(free, row[0], queued):
                why = "room"  # this Mac keeps its room: more go once what is here has gone up
                rest += 1
                continue
            to = spot(dir, name, day, rel, row + [day], up)
            if own:
                try:
                    if owncloud.size(dir, to) != row[0] or rel not in sums:
                        sums[rel] = owncloud.sha256(a)  # (read from the USB as it goes up)
                    err = owncloud.put(dir, a, to) if owncloud.size(dir, to) != row[0] else ""
                except OSError:
                    err = "unread"
                if err == "unread" or (err and not os.path.isdir(usb)):
                    if not os.path.isdir(usb):
                        why = "unplugged"
                        rest += 1
                    else:
                        skip.add(mark)
                    continue
                if err and err.split(":")[0] == "net" and owncloud.reachable(dir):
                    # The cloud answers, but won't take this one file (a name or size it refuses): the others go on,
                    # and this one is said once, by name; it is tried again at the next plug-in.
                    skip.add(mark)
                    if (name, rel) not in _REFUSED:
                        _REFUSED.add((name, rel))
                        log(dir, f'BACKUP PROBLEM: "{name}": your own cloud would not take "{rel}": '
                            f"{err.split(': ', 1)[-1] or 'no reason given'}. The other songs carry on.")
                    continue
                if err:  # full, a sign-in to give again, or offline: said on the page, and this turn ends here
                    why, said = err.split(":")[0], err
                    rest += 1
                    continue
                if left is not None:
                    left -= row[0]
                got[rel] = row + [day]
                have[(rel, row[0], row[1])] = day
                continue
            try:
                if os.path.exists(to + ".nosync"):
                    os.remove(to + ".nosync")  # (an older version's copy, cut short: no list counts on it)
                if usb_tidy.size(to) != row[0]:  # (one that got there just before a stop is taken as it is)
                    # copied on this Mac first, then moved in whole (into): iCloud never sees half a song
                    copy(a, tmp, row[1])
                    if os.path.getsize(tmp) != row[0]:
                        raise OSError("cut short")
                    into(tmp, to)
                    free, queued = free - row[0], queued + row[0]
                    if left is not None:
                        left = _ROOM["free"] = left - row[0]
                got[rel] = row + [day]
                have[(rel, row[0], row[1])] = day
                here += 1
            except OSError:
                if os.path.exists(tmp):
                    os.remove(tmp)
                if not os.path.isdir(usb):
                    why = "unplugged"
                    rest += 1
                    continue
                skip.add(mark)  # it can't be read now: tried again at the next plug-in
        if got:
            did = True
            for rel, row in got.items():
                waiting.pop(rel, None)
                if row:
                    files[rel] = row
            about = {**read(os.path.join(at, "about.json"), {}), "files": len(files), "waiting": len(waiting),
                     "songs": sum(1 for v in files.values() if v[2] == "song"), "bytes": sum(v[0] for v in files.values())}
            write(os.path.join(at, "manifest.json"), files)
            write(os.path.join(at, "waiting.json"), waiting)
            write(os.path.join(at, "about.json"), about)
            if own:
                write(os.path.join(at, "sums.json"), {r: h for r, h in sums.items() if r in files})
            twin(dir, name, day, up)
        if not n:
            left0 = len(waiting)
    why = why or ("unread" if any(r in skip for r in newest) else "")
    keep = {k: v for k, v in (seen or was).items() if k in ("sent", "unsent", "out", "asked")}
    if not own:  # (what went in this turn waits here too, until the next look at iCloud counts it)
        keep["unsent"] = queued + (keep.get("out") or 0)
    if own and why in SAID and why != (was.get("why") or ""):  # (iCloud's own words are said by the page)
        log(dir, f'BACKUP PROBLEM: "{name}": songs wait to go up: {SAID[why]}.' + (f" ({said.split(': ', 1)[-1]})" if said else ""))
    note(dir, name, up={**keep, "left": left0, "here": here, "why": why, "said": said, "at": int(time.time())},
         **({"kept": lifted(dir, name)} if did else {}))
    # (iCloud full: the songs still wait, and go up by themselves once there is room again; it is asked every few minutes)
    can = 0 if why == "unplugged" else rest
    return bool(did or freed), can + here


def binned(usb, rel, row):
    """A song that waited to go up, and that the copy to the USB has put in the USB's Trash since (the library's own
    file took its place, or it was a double): where it is in there now, told by its name, size and time. "" if not."""
    stem, ext = os.path.splitext(os.path.basename(rel))
    for folder in usb_tidy.bins(usb):
        try:
            found = sorted(os.listdir(folder))
        except OSError:
            continue
        for f in found:
            if f == stem + ext or (f.startswith(stem + " ") and f.endswith(ext)):
                try:
                    st = os.stat(os.path.join(folder, f))
                except OSError:
                    continue
                if [st.st_size, st.st_mtime_ns] == row[:2]:
                    return os.path.join(folder, f)
    return ""


WEEK = 7 * 86400


def check(dir, usb, name):
    """Your own cloud: at most once a week, each song on the USB that the newest backup holds (same size and time) is
    read and its sha256 compared with the one taken as it went up. One that went bad on the USB is said on the page,
    and Repair puts the good copy from the cloud in its place (the bad one goes to the USB's Trash). Only reads."""
    got = snaps(dir, name)
    last, was = (got[0] if got else None), note(dir, name).get("sums") or {}
    if not last or last.get("place") != "own" or time.time() - (was.get("at") or 0) < WEEK and was.get("day") == last["id"]:
        return
    rows, by, bad = files_of(dir, name, last["id"]), {}, []
    for rel, row in sorted(rows.items()):
        if row[2] != "song" or len(row) < 4:
            continue
        if row[3] not in by:
            by[row[3]] = sums_of(dir, name, row[3])
        sha = by[row[3]].get(rel)
        a = os.path.join(usb, *rel.split("/"))
        if not os.path.lexists(a) and os.path.isdir(usb):
            continue  # gone from the USB since (taken off, or moved): not damaged; the next backup lists what is there
        try:
            st = os.stat(a)
            if not sha or [st.st_size, st.st_mtime_ns] != row[:2]:
                continue  # (changed since: the next backup holds it as it is)
            if owncloud.sha256(a) != sha:
                bad.append(rel)
        except OSError:
            if not os.path.isdir(usb):
                return  # unplugged: checked at the next plug-in
            bad.append(rel)  # there, the right size, and it can't be read: the good copy is in the cloud
    note(dir, name, sums={"day": last["id"], "at": int(time.time()), "bad": len(bad)}, damaged=bad or None)
    if bad:
        why = f"{len(bad)} {'song' if len(bad) == 1 else 'songs'} on it {'is' if len(bad) == 1 else 'are'} damaged"
        if not note(dir, name).get("repair"):
            note(dir, name, repair={"day": last["id"], "why": why, "when": int(time.time())})
        log(dir, f'BACKUP PROBLEM: "{name}": {why} (not the same as when {"it" if len(bad) == 1 else "they"} went up). '
            "Repair on the Library Manager page puts the good copy back from your own cloud.")


def after(dir, usb, src):
    """Starts songs() on its own, so it outlives the copy that called this: when songs wait to go up to iCloud Drive,
    or wait to leave this Mac once they are up."""
    name = os.path.basename(os.path.normpath(usb))
    last = (snaps(dir, name) or [None])[0]
    place = load(dir)["place"]
    if place not in FAR or not last or last.get("place") != place or alive(dir, name):
        return
    # (an older backup kept there can still wait for a song too: one the copy to the USB replaced before it went up)
    # (and once after each backup, so macOS is asked what of it is up, and what is gives its room on this Mac back)
    up = note(dir, name).get("up") or {}
    if (not any(s.get("waiting") for s in snaps(dir, name) if s.get("place") == place)
            and not up.get("here") and (up.get("asked") or 0) >= last.get("when", 0)
            and (place != "own" or time.time() - ((note(dir, name).get("sums") or {}).get("at") or 0) < WEEK)):
        return
    with open(os.path.join(dir, "dj.log"), "a") as out:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "songs", dir, usb, src], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=out)


def same(a, b):
    """Two files hold the very same bytes."""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as x, open(b, "rb") as y:
            while True:
                one, two = x.read(1 << 20), y.read(1 << 20)
                if one != two:
                    return False
                if not one:
                    return True
    except OSError:
        return False


def restore(dir, usb, src, name, day):
    """Puts the backup DAY of the USB called NAME back onto USB (see the top). Returns a line for the log."""
    here, at = os.path.basename(os.path.normpath(usb)), os.path.join(home(dir, name), day)
    files = files_of(dir, name, day)
    place = (read(os.path.join(at, "about.json")) or {}).get("place")
    place = place if place in FAR else ""  # (kept away from this Mac: in iCloud Drive or your own cloud)
    up, own = far(dir, place) if place else "", place == "own"
    if not files or not os.path.isdir(at if place else os.path.join(at, "files")):
        return "BACKUP PROBLEM: that backup is not on this Mac any more."
    if place and not up:
        return ("BACKUP PROBLEM: that backup is in " + ("iCloud Drive, which can't be opened right now. " if not own else
                "your own cloud, which is not signed in (Options, My own cloud). ") + "Nothing on the USB was changed.")
    # songs your own cloud's check found damaged on it (check): their good copy goes back, the bad one to its Trash
    bad = set(note(dir, here).get("damaged") or []) if own and name == here else set()
    down = os.path.join(home(dir, name), ".down")
    if not os.path.isdir(usb) or not os.access(usb, os.W_OK):
        return f'BACKUP PROBLEM: "{here}" can only be read (locked, or damaged so far that it has to be erased first).'
    for _ in range(900):  # a copy to the USB that is running finishes first
        try:
            with open(os.path.join(dir, ".usb-copy")) as f:
                os.kill(int(f.read().split()[0]), 0)
            time.sleep(1)
        except (OSError, ValueError, IndexError):
            break
    fail = []
    try:
        kept = run(dir, usb, src, keep=day if name == here else "", fail=fail)  # what is on it now is kept first
    except OSError as e:
        kept = fail.append(e.strerror or str(e))
    if fail:  # never a repair over something that isn't kept
        return (f'BACKUP PROBLEM: "{here}" was not repaired: what is on it now could not be backed up first '
                f"({fail[0]}). Nothing on it was changed.")
    # A song on it now is replaced only when that backup holds it as it is now (size and time): one left out of it
    # ("Back up songs that are only on the USB" is off, this Mac was short of room, or it could not be read) stays
    # as it is. A song that is gone is put back.
    now = files_of(dir, here, kept["id"]) if kept and kept.get("id") else {}
    done = {"lib": 0, "song": 0, "left": 0, "aside": 0, "fixed": 0, "away": 0, "lost": 0}

    def held(rel, b):  # that backup holds this file of the USB as it is now
        try:
            st = os.stat(b)
        except OSError:
            return False
        return now.get(rel, [])[:2] == [st.st_size, st.st_mtime_ns]

    def notes(rel, b):  # a database's side notes that aren't in the backup would spoil it: to the USB's Trash
        n = 0
        for end in ("-wal", "-shm", "-journal"):
            if rel.lower().endswith(".db") and os.path.isfile(b + end) and rel + end not in files:
                if not usb_tidy.trash(usb, b + end):
                    raise OSError(errno.EIO, "a file in the way could not be moved")
                n += 1
        return n

    def ok(rel, row, path):  # a file had from your own cloud is the one that went up (size, sha256, a sound library)
        sha = sums_of(dir, name, row[3] if len(row) > 3 else day).get(rel)
        try:
            return (os.path.getsize(path) == row[0] and (not sha or owncloud.sha256(path) == sha)
                    and (row[2] == "song" or not wrong(dir, rel, path)))
        except OSError:
            return False
    gone = (f'BACKUP PROBLEM: "{here}" was not repaired: its backup could not be had whole from your own cloud (is '
            "this Mac online, and still signed in?). Nothing on it was changed.")
    if own and owncloud.listing(dir, "/".join([up, safe(name)]), fresh=True) is None:
        return gone  # the cloud can't be asked now: nothing is skipped as if it weren't there
    shutil.rmtree(down, ignore_errors=True)
    with open(os.path.join(dir, ".backup.lock"), "w") as lock, open(os.path.join(dir, ".dj.lock"), "w") as deck:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fcntl.flock(deck, fcntl.LOCK_EX)  # no deck library is written under it
        try:
            todo, stale, pre = [], [], []
            if place == "icloud":
                # Every library file is had from iCloud first, many at once: one at a time, a rekordbox library's
                # thousands of small files would take hours. (They leave this Mac again with the next backup's look.)
                pre = [a for a in (spot(dir, name, day, rel, row, up) for rel, row in files.items() if row[2] != "song")
                       if os.path.isfile(a) and not local(a)]
                with ThreadPoolExecutor(64) as pool:
                    for i, got in enumerate(pool.map(fetch, pre)):
                        if i % 50 == 0:
                            progress(dir, i, len(pre) + len(files) * 2, "restore")
                        if not got:
                            return (f'BACKUP PROBLEM: "{here}" was not repaired: its backup could not be fetched from '
                                    "iCloud Drive (is this Mac online?). Nothing on it was changed.")
            for i, (rel, row) in enumerate(sorted(files.items())):
                if i % 20 == 0:
                    progress(dir, len(pre) + i, len(pre) + len(files) * 2, "restore")
                a, b = spot(dir, name, day, rel, row, up), os.path.join(usb, *rel.split("/"))
                if not has(dir, up, a, row[0]):
                    if own and row[2] != "song":
                        return gone  # a library from your own cloud is put back whole or not at all
                    done["lost"] += rel in bad  # (a damaged song with no good copy there stays flagged)
                    continue
                # From the cloud every library file is had first, before anything on the USB is changed: a repair
                # never stops half way because this Mac is offline
                if own and row[2] != "song":
                    to = os.path.join(down, *rel.split("/"))
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    if owncloud.get(dir, a, to) or not ok(rel, row, to):
                        return gone
                    a = to
                elif place == "icloud" and row[2] != "song" and not fetch(a):
                    return (f'BACKUP PROBLEM: "{here}" was not repaired: its backup could not be fetched from iCloud '
                            "Drive (is this Mac online?). Nothing on it was changed.")
                have = usb_tidy.size(b)
                if row[2] != "song":
                    (stale if same(a, b) else todo).append((rel, row, a, b))
                elif have < 0 or (have != row[0] and held(rel, b)) or (rel in bad and have == row[0]):
                    todo.append((rel, row, a, b))
                elif have != row[0]:
                    done["left"] += 1
            # Room is checked before anything on it is changed, file by file in the order they go back: each one is
            # written whole beside the one it replaces first, and a file that is set aside stays on the USB, in its
            # Trash. So a repair never stops half way for want of room, with libraries from two different days.
            todo.sort(key=lambda t: t[1][2] == "song")  # the libraries first: they hold the cues
            room = short = shutil.disk_usage(usb).free
            for rel, row, _, b in todo:
                room -= row[0]
                short = min(short, room)
                if held(rel, b) and rel not in bad:  # (a damaged one goes to the USB's Trash: its room stays taken)
                    room += max(usb_tidy.size(b), 0)
            if short < 0:
                return (f'BACKUP PROBLEM: "{here}" has no room for its backup ({-short // 1024 ** 2 + 1} MB more is '
                        "needed). Nothing on it was changed.")
            try:  # a database that is the same already, with newer side notes beside it: those go, or it isn't put back
                for rel, _, _, b in stale:
                    done["lib"] += bool(notes(rel, b))
            except OSError as e:
                return f'BACKUP PROBLEM: "{here}" could not be written ({e.strerror or e}). It may have to be erased first.'
            for i, (rel, row, a, b) in enumerate(todo):
                progress(dir, len(pre) + len(files) + i * len(files) // len(todo), len(pre) + len(files) * 2, "restore")
                back = place == "icloud" and row[2] == "song" and not local(a)  # (had from iCloud: leaves this Mac again)
                if back and not fetch(a):
                    done["away"] += 1
                    continue
                try:
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    if own and row[2] == "song":  # straight from your own cloud onto the USB, checked before it counts
                        if owncloud.get(dir, a, b + ".crate-tmp") or not ok(rel, row, b + ".crate-tmp"):
                            if os.path.exists(b + ".crate-tmp"):
                                os.remove(b + ".crate-tmp")
                            done["away"] += 1
                            continue
                    else:
                        copy(a, b + ".crate-tmp", row[1])
                    if os.path.lexists(b) and (not held(rel, b) or rel in bad):
                        # what is there could not be read into that backup (or changed since): it is not written
                        # over, it goes to the USB's Trash, where it can still be got at
                        if not usb_tidy.trash(usb, b):
                            os.remove(b + ".crate-tmp")
                            raise OSError(errno.EIO, "a file that could not be backed up first is in the way")
                        done["fixed" if rel in bad else "aside"] += 1
                    os.replace(b + ".crate-tmp", b)
                    os.utime(b, ns=(row[1], row[1]))
                    done["song" if row[2] == "song" else "lib"] += 1
                    notes(rel, b)
                    if back:
                        evict(dir, [a])
                except OSError as e:
                    if not os.path.isdir(usb):
                        return f'BACKUP PROBLEM: "{here}" was unplugged before its backup was back on it. Plug it in and repair again.'
                    return f'BACKUP PROBLEM: "{here}" could not be written ({e.strerror or e}). It may have to be erased first.'
        finally:
            shutil.rmtree(down, ignore_errors=True)
            if os.path.exists(os.path.join(dir, ".backup-progress")):
                os.remove(os.path.join(dir, ".backup-progress"))
    # your yes for this USB's library stands for the same library put back (usb_ask.py); a USB never allowed still asks
    if usb_ask.state(dir, usb) == "ask" and any(isinstance(v, dict) and v.get("yes") and v.get("name") == name
                                                 for v in usb_ask.load(dir).values()):
        try:
            usb_ask.answer(dir, usb, True)
        except OSError:
            pass
    note(dir, here, repair=None, **({"damaged": None, "sums": None} if bad and not done["away"] and not done["lost"] else {}))
    stamp = time.strftime("%b %-d, %H:%M", time.localtime(when(day)))
    return (f'backup: "{here}" put back from the backup of {stamp}'
            + (f' of "{name}"' if name != here else "")
            + f" ({done['lib']} library {'file' if done['lib'] == 1 else 'files'}, {done['song']} "
            f"{'song' if done['song'] == 1 else 'songs'})."
            + (f" {done['left']} {'song' if done['left'] == 1 else 'songs'} on it that this Mac has no backup of "
               f"{'was' if done['left'] == 1 else 'were'} left as {'it is' if done['left'] == 1 else 'they are'}."
               if done["left"] else "")
            + (f" {done['aside']} {'file' if done['aside'] == 1 else 'files'} on it that could not be backed up first "
               f"{'is' if done['aside'] == 1 else 'are'} in its Trash." if done["aside"] else "")
            + (f" {done['fixed']} damaged {'song' if done['fixed'] == 1 else 'songs'} replaced with the good copy (the "
               f"damaged {'one is' if done['fixed'] == 1 else 'ones are'} in its Trash)." if done["fixed"] else "")
            + (f" {done['away']} {'song' if done['away'] == 1 else 'songs'} could not be fetched from {WHERE[place]}: "
               "repair again when this Mac is online." if done["away"] else "")
            + (f" {done['lost']} damaged {'song' if done['lost'] == 1 else 'songs'} on it {'has' if done['lost'] == 1 else 'have'}"
               f" no good copy in {WHERE[place]} and {'stays' if done['lost'] == 1 else 'stay'} as {'it is' if done['lost'] == 1 else 'they are'}:"
               " still flagged on the page." if done["lost"] else "")
            + " Your library's songs and playlists follow now.")


def status(dir):
    """For the page: each USB with backups (newest backup first), a backup or restore running now, the place they are
    kept and, for iCloud Drive, the room left in it and whether songs are on their way up."""
    sticks, cfg = [], load(dir)
    try:
        names = sorted(os.listdir(os.path.join(dir, ROOT)))
    except OSError:
        names = []
    for n in names:
        got = snaps(dir, n)
        if got:
            st = note(dir, n)
            sticks.append({"name": got[0].get("name") or n, "size": st.get("size", 0), "checked": st.get("checked", 0),
                           "repair": st.get("repair"), "fine": st.get("fine"),
                           # in iCloud: only what macOS said is uploaded ("kept": what the backups' lists hold)
                           "cloud": (st.get("up") or {}).get("sent", 0), "kept": st.get("kept", st.get("cloud", 0)),
                           "up": st.get("up") if got[0].get("place") in FAR else None, "going": alive(dir, n),
                           "damaged": len(st.get("damaged") or []),
                           "snaps": [{k: s.get(k) for k in ("id", "when", "ok", "why", "libs", "songs", "bytes", "skipped",
                                                            "place", "waiting", "sent", "unsent")} for s in got]})
    return {"songs": cfg["songs"], "place": cfg["place"],
            "free": room() if cfg["place"] == "icloud" else owncloud.free(dir, wait=False) if cfg["place"] == "own" else None,
            "own": owncloud.status(dir), "going": alive(dir), "sticks": sticks, "doing": progress(dir)}


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) in (4, 5) and a[0] == "run":
        # Backup "Off" in Options: no backup at plug-in; "Back up now" on the page ("now") still makes one, on this Mac
        if os.path.isdir(a[2]) and (load(a[1])["place"] != "off" or a[4:] == ["now"]):
            run(a[1], a[2], a[3])
            after(a[1], a[2], a[3])
    elif len(a) == 4 and a[0] == "songs":
        songs(a[1], a[2], a[3])
    elif len(a) == 6 and a[0] == "restore":
        line = restore(a[1], a[2], a[3], a[4], a[5])
        log(a[1], line)
        if "PROBLEM" not in line:  # the usual copy: your library's songs and its playlists go back on
            subprocess.call([os.path.join(a[1], "usb.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        sys.exit(__doc__)
