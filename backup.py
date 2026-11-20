#!/usr/bin/env python3
"""Keeps a copy on this Mac of what your decks saved on your USB, and puts it back when a USB goes wrong.

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

  backup.py run DIR USB SRC                at plug-in, and the page's "Back up now"
  backup.py restore DIR USB SRC NAME DAY   the page's "Repair": the backup DAY of the USB called NAME, onto USB

Standard library only."""
import errno, fcntl, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, time, unicodedata, urllib.parse

import usb_ask, usb_tidy

ROOT, SET, KEEP, BAD = "usb-backups", "usb-backup.json", 10, 2
RESERVE = int(os.environ.get("CRATE_BACKUP_RESERVE") or 5 * 1024 ** 3)  # the room that always stays free on this Mac
LIBS = (("rekordbox", "pioneer"), ("Engine DJ", "engine library"), ("Serato", "_serato_"))
MAIN = (("rekordbox", "pioneer/rekordbox/export.pdb"), ("rekordbox", "pioneer/rekordbox/exportlibrary.db"),
        ("Engine DJ", "engine library/database2/m.db"))  # a library is gone when one of these was there and isn't
SKIP = usb_ask.SYSTEM + ("thrown back by the crate",)


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
    """The one setting: songs that are only on the USB are kept too (on unless switched off on the page)."""
    cfg = read(os.path.join(dir, SET), {})
    return {"songs": cfg.get("songs", True) is not False} if isinstance(cfg, dict) else {"songs": True}


def save(dir, songs):
    write(os.path.join(dir, SET), {"songs": bool(songs)})


def log(dir, text):
    with open(os.path.join(dir, "dj.log"), "a") as f:
        f.write(time.strftime("%F %R") + "  " + text + "\n")


def home(dir, name):
    return os.path.join(dir, ROOT, re.sub(r"[/\\:\0]", "_", name).strip(". ") or "USB")


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
    keep, good, bad = {keep, (note(dir, name).get("repair") or {}).get("day")}, 0, 0
    for s in snaps(dir, name):
        good, bad = good + bool(s.get("ok")), bad + (not s.get("ok"))
        if s["id"] not in keep and (good > KEEP if s.get("ok") else bad > BAD):
            shutil.rmtree(os.path.join(home(dir, name), s["id"]), ignore_errors=True)


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
    at, last = home(dir, name), (snaps(dir, name) or [None])[0]
    before = files_of(dir, name, last["id"]) if last else {}
    seen, stuck = listing(usb, library(src), load(dir)["songs"])
    if not seen and not last:
        return None  # an empty USB with no backup yet: nothing to keep
    new = lambda rows: sum(v[0] for r, v in rows.items() if before.get(r, [])[:2] != v[:2])
    skipped, free = "", shutil.disk_usage(dir).free
    if free - new(seen) < RESERVE:  # the libraries always go first: they are small, and they hold the cues
        songs = [r for r, v in seen.items() if v[2] == "song"]
        seen = {r: v for r, v in seen.items() if v[2] != "song"}
        skipped = f"{len(songs)} songs that are only on it were left out: this Mac is short of room"
        if free - new(seen) < RESERVE // 10:
            log(dir, f'BACKUP PROBLEM: "{name}" was not backed up: this Mac has no room left for it.')
            fail.append("this Mac has no room left for it")
            return None
    mark = hashlib.sha1(json.dumps([sorted(seen.items()), sorted(stuck)]).encode()).hexdigest()
    # Nothing on it changed since the last backup: that one stands. Unless a file could not be read then: it is
    # tried again every time, so a read that only failed once doesn't leave the backup short for good.
    if last and last.get("seen") == mark and not last.get("unread"):
        note(dir, name, checked=int(time.time()))
        return last
    t = int(time.time())
    while os.path.exists(os.path.join(at, time.strftime("%Y-%m-%d %H%M%S", time.localtime(t)))):
        t += 1  # (two backups within one second: each gets a folder of its own)
    day, part = time.strftime("%Y-%m-%d %H%M%S", time.localtime(t)), os.path.join(at, ".part")
    shutil.rmtree(part, ignore_errors=True)  # (what a backup cut short left behind)
    files, bad, unread, was = {}, {}, list(stuck), (last or {}).get("bad") or {}
    for i, (rel, row) in enumerate(sorted(seen.items())):
        if i % 20 == 0:
            progress(dir, i, len(seen), "backup")
        to = os.path.join(part, "files", *rel.split("/"))
        os.makedirs(os.path.dirname(to), exist_ok=True)
        had = os.path.join(at, last["id"], "files", *rel.split("/")) if last else ""
        if before.get(rel, [])[:2] == row[:2] and os.path.isfile(had):
            link(had, to)
            files[rel] = row
            if rel in was:
                bad[rel] = was[rel]
            continue
        try:
            copy(os.path.join(usb, *rel.split("/")), to, row[1])
            if os.path.getsize(to) != row[0]:
                raise OSError("cut short")
            files[rel] = row
            why = wrong(dir, rel, to) if row[2] != "song" else ""
            if why:  # a library that changed under the copy reads as damaged: once more
                st = os.stat(os.path.join(usb, *rel.split("/")))
                files[rel] = row = [st.st_size, st.st_mtime_ns, row[2]]
                copy(os.path.join(usb, *rel.split("/")), to, row[1])
                why = wrong(dir, rel, to)
            if why:
                bad[rel] = why
        except OSError:
            if not os.path.isdir(usb):  # unplugged half way: no backup this time, the last one stands
                shutil.rmtree(part, ignore_errors=True)
                log(dir, f'backup: "{name}" was unplugged before its backup was done. It is made the next time.')
                fail.append("it was unplugged")
                return last
            unread.append(rel)
            if os.path.exists(to):
                os.remove(to)
            if os.path.isfile(had):  # the last copy that could be read stays in the backup
                link(had, to)
                files[rel] = before[rel]
    if last and last.get("seen") == mark and sorted(unread) == last.get("unread") and files == before:
        shutil.rmtree(part, ignore_errors=True)  # (tried again, and it still can't be read: the last backup stands)
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
             "bytes": sum(v[0] for v in files.values()), "skipped": skipped, "unread": sorted(unread)}
    os.makedirs(part, exist_ok=True)
    write(os.path.join(part, "manifest.json"), files)
    write(os.path.join(part, "about.json"), about)
    os.rename(part, os.path.join(at, day))
    prune(dir, name, keep)
    note(dir, name, checked=int(time.time()), size=weigh(at))
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
        log(dir, f'backup: "{name}" backed up to this Mac ({say(libs) or "no DJ library on it"}'
            + (f", {about['songs']} {'song' if about['songs'] == 1 else 'songs'} that are only on it" if about["songs"] else "")
            + (")" if not skipped else "). " + skipped[0].upper() + skipped[1:] + "."))
    return {**about, "id": day, "when": when(day)}


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
    here, at = os.path.basename(os.path.normpath(usb)), os.path.join(home(dir, name), day, "files")
    files = files_of(dir, name, day)
    if not files or not os.path.isdir(at):
        return "BACKUP PROBLEM: that backup is not on this Mac any more."
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
    # A song on it now is replaced only when that backup holds it as it is: one left out of it ("Back up songs that
    # are only on the USB" is off, or this Mac was short of room) stays as it is. A song that is gone is put back.
    now = files_of(dir, here, kept["id"]) if kept and kept.get("id") else {}
    done = {"lib": 0, "song": 0, "left": 0, "aside": 0}

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
            todo = []
            for i, (rel, row) in enumerate(sorted(files.items())):
                if i % 20 == 0:
                    progress(dir, i, len(files) * 2, "restore")
                a, b = os.path.join(at, *rel.split("/")), os.path.join(usb, *rel.split("/"))
                if not os.path.isfile(a):
                    continue
                have = usb_tidy.size(b)
                if row[2] != "song":
                    if not same(a, b):
                        todo.append((rel, row, a, b))
                    else:
                        try:  # the same file, with newer side notes beside it: those go, or it isn't put back
                            done["lib"] += bool(notes(rel, b))
                        except OSError as e:
                            return f'BACKUP PROBLEM: "{here}" could not be written ({e.strerror or e}). It may have to be erased first.'
                elif have < 0 or (have != row[0] and now.get(rel, [-1])[0] == have):
                    todo.append((rel, row, a, b))
                elif have != row[0]:
                    done["left"] += 1
            # Room is checked before anything on it is changed, file by file in the order they go back: each one is
            # written whole beside the one it replaces first, and a file that is set aside stays on the USB, in its
            # Trash. So a repair never stops half way for want of room, with libraries from two different days.
            room = short = shutil.disk_usage(usb).free
            for rel, row, _, b in todo:
                room -= row[0]
                short = min(short, room)
                if row[2] == "song" or held(rel, b):
                    room += max(usb_tidy.size(b), 0)
            if short < 0:
                return (f'BACKUP PROBLEM: "{here}" has no room for its backup ({-short // 1024 ** 2 + 1} MB more is '
                        "needed). Nothing on it was changed.")
            for i, (rel, row, a, b) in enumerate(todo):
                progress(dir, len(todo) + i, len(todo) * 2, "restore")
                try:
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    copy(a, b + ".crate-tmp", row[1])
                    if row[2] != "song" and os.path.lexists(b) and not held(rel, b):
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
            + " Your library's songs and playlists follow now.")


def status(dir):
    """For the page: each USB with backups on this Mac (newest backup first), and a backup or restore running now."""
    sticks = []
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
                           "snaps": [{k: s.get(k) for k in ("id", "when", "ok", "why", "libs", "songs", "bytes", "skipped")}
                                     for s in got]})
    return {"songs": load(dir)["songs"], "sticks": sticks, "doing": progress(dir)}


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "run":
        if os.path.isdir(a[2]):
            run(a[1], a[2], a[3])
    elif len(a) == 6 and a[0] == "restore":
        line = restore(a[1], a[2], a[3], a[4], a[5])
        log(a[1], line)
        if "PROBLEM" not in line:  # the usual copy: your library's songs and its playlists go back on
            subprocess.call([os.path.join(a[1], "usb.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        sys.exit(__doc__)
