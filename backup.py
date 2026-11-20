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
  songs that are only on the USB follow on their own (songs): a few at a time, only while this Mac keeps RESERVE
  free, and each one gives its room on this Mac back once it is safely in iCloud. So a full USB fits through a Mac
  with little room. It carries on at the next plug-in if the USB is unplugged first. iCloud Drive off, or not to be
  opened: the backup is made on this Mac that time, and says so.

  backup.py run DIR USB SRC                at plug-in, and the page's "Back up now"
  backup.py songs DIR USB SRC              started by run: the USB-only songs go up to iCloud Drive
  backup.py restore DIR USB SRC NAME DAY   the page's "Repair": the backup DAY of the USB called NAME, onto USB

Standard library only."""
import errno, fcntl, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, threading, time, unicodedata, urllib.parse

import usb_ask, usb_tidy

ROOT, SET, KEEP, BAD = "usb-backups", "usb-backup.json", 10, 2
RESERVE = int(os.environ.get("CRATE_BACKUP_RESERVE") or 5 * 1024 ** 3)  # the room that always stays free on this Mac
LIBS = (("rekordbox", "pioneer"), ("Engine DJ", "engine library"), ("Serato", "_serato_"))
MAIN = (("rekordbox", "pioneer/rekordbox/export.pdb"), ("rekordbox", "pioneer/rekordbox/exportlibrary.db"),
        ("Engine DJ", "engine library/database2/m.db"))  # a library is gone when one of these was there and isn't
SKIP = usb_ask.SYSTEM + ("thrown back by the crate",)
# iCloud Drive on this Mac, and The Crate's folder in it (CRATE_ICLOUD: another folder stands in for it, for tests)
CLOUD = os.environ.get("CRATE_ICLOUD") or os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")
INSIDE = ("The Crate", "USB backups")
DATALESS = 0x40000000  # (stat.SF_DATALESS) a file whose content is in iCloud only: its name, size and time are here
# Asks macOS, for each path in a list: is it safely in iCloud? Then its room on this Mac is given back (the file
# stays in iCloud Drive and comes back when it is opened). macOS itself refuses one that has not gone up yet.
JXA = """ObjC.import("Foundation");
function run(argv) {
  var out = "", fm = $.NSFileManager.defaultManager;
  var names = ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError(argv[0], $.NSUTF8StringEncoding, null)).split("\\n");
  for (var i = 0; i < names.length; i++) {
    if (!names[i]) continue;
    var u = $.NSURL.fileURLWithPath(names[i]);
    var d = u.resourceValuesForKeysError($(["NSURLUbiquitousItemIsUploadedKey"]), null);
    var up = !d.isNil() && !!ObjC.unwrap(d.objectForKey("NSURLUbiquitousItemIsUploadedKey"));
    out += up && fm.evictUbiquitousItemAtURLError(u, null) ? "1" : "0";
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
    the place the backups are kept: "mac", or "icloud" (the person's own iCloud Drive)."""
    cfg = read(os.path.join(dir, SET), {})
    cfg = cfg if isinstance(cfg, dict) else {}
    return {"songs": cfg.get("songs", True) is not False, "place": "icloud" if cfg.get("place") == "icloud" else "mac"}


def save(dir, songs=None, place=None):
    cfg = load(dir)
    write(os.path.join(dir, SET), {"songs": cfg["songs"] if songs is None else bool(songs),
                                   "place": cfg["place"] if place is None else "icloud" if place == "icloud" else "mac"})


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


def spot(dir, name, day, rel, row, up=""):
    """Where a backup keeps one file. On this Mac: in its own day's folder. In iCloud Drive (a row with a fourth part,
    the day that holds the file): in that day's folder there."""
    if len(row) > 3:
        return os.path.join(up or os.path.join(CLOUD, *INSIDE), safe(name), row[3], "files", *rel.split("/"))
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


def evict(dir, paths):
    """Files that are safely in iCloud give their room on this Mac back (JXA above). Returns how many did; None when
    this Mac can't be asked (then macOS frees the room itself, when it runs short: "Optimise Mac Storage")."""
    if not paths:
        return 0
    p = os.path.join(dir, ROOT, ".cloud.txt")
    try:
        with open(p, "w") as f:
            f.write("\n".join(paths))
        got = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA, p], capture_output=True, text=True, timeout=600)
        return got.stdout.count("1") if got.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if os.path.exists(p):
            os.remove(p)


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
            shutil.rmtree(os.path.join(home(dir, name), s["id"]), ignore_errors=True)
            out += [s["id"]] if s.get("place") == "icloud" else []
    sweep(dir, name, out)


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


def lifted(dir, name):
    """How much of a USB's backups is kept in iCloud Drive (a file kept once counts once)."""
    seen = {}
    for s in snaps(dir, name):
        if s.get("place") == "icloud":
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
    up = cloud() if cfg["place"] == "icloud" else ""  # (iCloud Drive chosen but not to be opened: this Mac, this time)
    far, tail = os.path.join(up, safe(name)) if up else "", "icloud" if up else "mac"
    # A backup builds on the newest one kept in the same place: what didn't change since is shared with it
    base = next((s for s in got if (s.get("place") or "mac") == tail), None)
    # In iCloud Drive a file is kept once, by the backup that first held it: every backup kept there is looked at, so
    # a song that was away for one backup (or put back by a repair) doesn't go up a second time
    pool, old, was = [s for s in got if s.get("place") == "icloud"] if up else [base] if base else [], {}, {}
    for s in reversed(pool):  # (the newest one's word counts)
        rows = before if s is last else files_of(dir, name, s["id"])
        old.update(rows)
        was.update({r: (s.get("bad") or {}).get(r) for r in rows})  # a copy that read as damaged still does
    seen, stuck = listing(usb, library(src), cfg["songs"])
    if not seen and not last:
        return None  # an empty USB with no backup yet: nothing to keep
    held = lambda rel, row: (rel in old and old[rel][:2] == row[:2]
                             and os.path.isfile(spot(dir, name, base["id"], rel, old[rel], up)))
    new = lambda rows: sum(v[0] for r, v in rows.items() if old.get(r, [])[:2] != v[:2])
    skipped, waiting, free = [], {}, shutil.disk_usage(dir).free
    if cfg["place"] == "icloud" and not up:
        # (its songs wait for iCloud Drive: they are the room this Mac is spared)
        seen = {r: v for r, v in seen.items() if v[2] != "song"}
        skipped.append("iCloud Drive could not be opened: this backup is on this Mac, without the songs that are "
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
            and (not up or os.path.isdir(os.path.join(far, last["id"])))):
        note(dir, name, checked=int(time.time()))
        return last
    t = int(time.time())
    stamp = lambda: time.strftime("%Y-%m-%d %H%M%S", time.localtime(t))
    while os.path.exists(os.path.join(at, stamp())) or (up and os.path.exists(os.path.join(far, stamp()))):
        t += 1  # (two backups within one second: each gets a folder of its own)
    day, part = time.strftime("%Y-%m-%d %H%M%S", time.localtime(t)), os.path.join(at, ".part")
    # In iCloud Drive the files are gathered under a name iCloud leaves alone (".nosync") and go up once they are whole
    box = os.path.join(far, ".part.nosync") if up else part
    for d in {part, box}:
        shutil.rmtree(d, ignore_errors=True)  # (what a backup cut short left behind)
    files, bad, unread = {}, {}, list(stuck)
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
            if why:  # a library that changed under the copy reads as damaged: once more
                st = os.stat(os.path.join(usb, *rel.split("/")))
                row = [st.st_size, st.st_mtime_ns, row[2]]
                files[rel] = row + [day] * bool(up)
                copy(os.path.join(usb, *rel.split("/")), to, row[1])
                why = wrong(dir, rel, to)
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
            if rel in old and os.path.isfile(spot(dir, name, base["id"], rel, old[rel], up)):
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
        os.rename(box, os.path.join(far, day))
    os.rename(part, os.path.join(at, day))
    twin(dir, name, day, up)
    prune(dir, name, keep)
    # (songs that went up before and haven't left this Mac yet still count: after() sends them off, with or without
    # new songs to go up)
    here = (note(dir, name).get("up") or {}).get("here") or 0
    note(dir, name, checked=int(time.time()), size=weigh(at), cloud=lifted(dir, name),
         up={"left": len(waiting), "here": here, "why": "", "at": int(time.time())} if up else None)
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
        log(dir, f'backup: "{name}" backed up to {"iCloud Drive" if up else "this Mac"} ({say(libs) or "no DJ library on it"}'
            + (f", {n} {'song' if n == 1 else 'songs'} that {'is' if n == 1 else 'are'} only on it" if n else "")
            + (f", {len(waiting)} more {'song goes' if len(waiting) == 1 else 'songs go'} up next" if waiting else "")
            + (")" if not skipped else "). " + skipped[0].upper() + skipped[1:] + "."))
    return {**about, "id": day, "when": when(day)}


def twin(dir, name, day, up):
    """A backup in iCloud Drive carries a copy of its two lists, so its folder there says by itself what it holds."""
    for f in ("manifest.json", "about.json") if up else ():
        try:
            shutil.copyfile(os.path.join(home(dir, name), day, f), os.path.join(up, safe(name), day, f))
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
    """iCloud Drive only: the songs that are only on the USB go up after its libraries, in short turns (_songs), so a
    backup at plug-in or a repair never waits long for it. It ends when every song is in iCloud and off this Mac,
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
        while idle < 2880:
            with open(os.path.join(dir, ".backup.lock"), "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                moved, left = _songs(dir, usb, name, skip)
            if not left:
                break
            idle = 0 if moved else idle + 1
            if not moved:
                time.sleep(30)
        end = (snaps(dir, name) or [{}])[0]
        if skip and os.path.isdir(usb):
            log(dir, f'BACKUP PROBLEM: "{name}": {len(skip)} {"song" if len(skip) == 1 else "songs"} that '
                f'{"is" if len(skip) == 1 else "are"} only on it could not be read, so '
                f'{"it is" if len(skip) == 1 else "they are"} not in iCloud Drive yet. Tried again at the next backup.')
        if start and end.get("place") == "icloud" and not end.get("waiting"):
            log(dir, f'backup: "{name}": every song that is only on it is in iCloud Drive now ({end.get("songs", 0)}).')
    finally:
        try:
            with open(p) as f:
                mine = f.read() == str(os.getpid())
            if mine:
                os.remove(p)
        except OSError:
            pass


def _songs(dir, usb, name, skip, turn=20):
    """One short turn of songs(): returns (something moved, how much it can still do)."""
    kept = snaps(dir, name)
    last = kept[0] if kept else None
    up = cloud() if last and last.get("place") == "icloud" and load(dir)["place"] == "icloud" else ""
    if not up:
        return False, 0
    pool = [s for s in kept if s.get("place") == "icloud"]  # (the newest first)
    lists = {s["id"]: files_of(dir, name, s["id"]) for s in pool}
    # Room first: songs that are safely in iCloud leave this Mac (the libraries stay: they are small). Every backup
    # kept there is looked through, not just the newest: a song the USB lost since is still in an older one.
    held = {spot(dir, name, day, rel, row, up) for day, rows in lists.items() for rel, row in rows.items()
            if row[2] == "song" and len(row) > 3}
    here = sorted(p for p in held if local(p))
    freed = evict(dir, here)
    here, why, did, rest, left0 = len(here) - (freed or 0), "", False, 0, 0
    free, left, t0 = shutil.disk_usage(up).free, room(30), time.time()
    # What iCloud Drive holds by now, by its place on the USB, its size and its time: {...: the day that holds it}
    have = {(rel, row[0], row[1]): row[3] for s in reversed(pool) for rel, row in lists[s["id"]].items() if len(row) > 3}
    # The newest backup's waiting songs go up, and then what an older one kept there still waits for: a song the copy
    # to the USB replaced before it went up is in no newer backup's list, and is kept by the one that listed it.
    for n, s in enumerate(pool):
        day, at = s["id"], os.path.join(home(dir, name), s["id"])
        waiting = read(os.path.join(at, "waiting.json"), {})
        waiting = waiting if isinstance(waiting, dict) else {}
        files, got = lists[day], {}
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
                if d and os.path.isfile(spot(dir, name, day, rel, row[:3] + [d], up)):
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
            if left is not None and left - row[0] < 1024 ** 3:
                why = "full"
                rest += 1
                continue
            if free - row[0] < RESERVE:
                why = "room"  # this Mac keeps its room: more go once what is here has gone up
                rest += 1
                continue
            to = spot(dir, name, day, rel, row + [day], up)
            try:
                if usb_tidy.size(to) != row[0]:  # (one that got there just before a stop is taken as it is)
                    os.makedirs(os.path.dirname(to), exist_ok=True)
                    copy(a, to + ".nosync", row[1])
                    if os.path.getsize(to + ".nosync") != row[0]:
                        raise OSError("cut short")
                    os.replace(to + ".nosync", to)
                    free -= row[0]
                    if left is not None:
                        left = _ROOM["free"] = left - row[0]
                got[rel] = row + [day]
                have[(rel, row[0], row[1])] = day
                here += 1
            except OSError:
                if os.path.exists(to + ".nosync"):
                    os.remove(to + ".nosync")
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
            twin(dir, name, day, up)
        if not n:
            left0 = len(waiting)
    why = why or ("unread" if any(r in skip for r in newest) else "")
    note(dir, name, up={"left": left0, "here": here, "why": why, "at": int(time.time())},
         **({"cloud": lifted(dir, name)} if did else {}))
    # (iCloud full: the songs still wait, and go up by themselves once there is room again; it is asked every few minutes)
    can = 0 if why == "unplugged" else rest
    return bool(did or freed), can + (here if freed is not None else 0)


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


def after(dir, usb, src):
    """Starts songs() on its own, so it outlives the copy that called this: when songs wait to go up to iCloud Drive,
    or wait to leave this Mac once they are up."""
    name = os.path.basename(os.path.normpath(usb))
    last = (snaps(dir, name) or [None])[0]
    if load(dir)["place"] != "icloud" or not last or last.get("place") != "icloud" or alive(dir, name):
        return
    # (an older backup kept there can still wait for a song too: one the copy to the USB replaced before it went up)
    if (not any(s.get("waiting") for s in snaps(dir, name) if s.get("place") == "icloud")
            and not (note(dir, name).get("up") or {}).get("here")):
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
    far = (read(os.path.join(at, "about.json")) or {}).get("place") == "icloud"
    up = cloud() if far else ""
    if not files or not os.path.isdir(at if far else os.path.join(at, "files")):
        return "BACKUP PROBLEM: that backup is not on this Mac any more."
    if far and not up:
        return ("BACKUP PROBLEM: that backup is in iCloud Drive, which can't be opened right now. "
                "Nothing on the USB was changed.")
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
    done = {"lib": 0, "song": 0, "left": 0, "aside": 0, "away": 0}

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
    with open(os.path.join(dir, ".backup.lock"), "w") as lock, open(os.path.join(dir, ".dj.lock"), "w") as deck:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fcntl.flock(deck, fcntl.LOCK_EX)  # no deck library is written under it
        try:
            todo, stale = [], []
            for i, (rel, row) in enumerate(sorted(files.items())):
                if i % 20 == 0:
                    progress(dir, i, len(files) * 2, "restore")
                a, b = spot(dir, name, day, rel, row, up), os.path.join(usb, *rel.split("/"))
                if not os.path.isfile(a):
                    continue
                # From iCloud Drive every library file is had first, before anything on the USB is changed: a repair
                # never stops half way because this Mac is offline
                if far and row[2] != "song" and not fetch(a):
                    return (f'BACKUP PROBLEM: "{here}" was not repaired: its backup could not be fetched from iCloud '
                            "Drive (is this Mac online?). Nothing on it was changed.")
                have = usb_tidy.size(b)
                if row[2] != "song":
                    (stale if same(a, b) else todo).append((rel, row, a, b))
                elif have < 0 or (have != row[0] and held(rel, b)):
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
                if held(rel, b):
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
                progress(dir, len(todo) + i, len(todo) * 2, "restore")
                back = far and row[2] == "song" and not local(a)  # a song had from iCloud for this leaves this Mac again
                if back and not fetch(a):
                    done["away"] += 1
                    continue
                try:
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    copy(a, b + ".crate-tmp", row[1])
                    if os.path.lexists(b) and not held(rel, b):
                        # what is there could not be read into that backup (or changed since): it is not written
                        # over, it goes to the USB's Trash, where it can still be got at
                        if not usb_tidy.trash(usb, b):
                            os.remove(b + ".crate-tmp")
                            raise OSError(errno.EIO, "a file that could not be backed up first is in the way")
                        done["aside"] += 1
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
            if os.path.exists(os.path.join(dir, ".backup-progress")):
                os.remove(os.path.join(dir, ".backup-progress"))
    # your yes for this USB's library stands for the same library put back (usb_ask.py); a USB never allowed still asks
    if usb_ask.state(dir, usb) == "ask" and any(isinstance(v, dict) and v.get("yes") and v.get("name") == name
                                                 for v in usb_ask.load(dir).values()):
        try:
            usb_ask.answer(dir, usb, True)
        except OSError:
            pass
    note(dir, here, repair=None)
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
            + (f" {done['away']} {'song' if done['away'] == 1 else 'songs'} could not be fetched from iCloud Drive: "
               "repair again when this Mac is online." if done["away"] else "")
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
                           "repair": st.get("repair"), "fine": st.get("fine"), "cloud": st.get("cloud", 0),
                           "up": st.get("up") if got[0].get("place") == "icloud" else None, "going": alive(dir, n),
                           "snaps": [{k: s.get(k) for k in ("id", "when", "ok", "why", "libs", "songs", "bytes", "skipped",
                                                            "place", "waiting")} for s in got]})
    return {"songs": cfg["songs"], "place": cfg["place"], "free": room() if cfg["place"] == "icloud" else None,
            "going": alive(dir), "sticks": sticks, "doing": progress(dir)}


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "run":
        if os.path.isdir(a[2]):
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
