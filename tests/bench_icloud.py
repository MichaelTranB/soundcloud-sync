"""Bench test for backup.py's iCloud path (stand-in iCloud folder, fake USB, look() faked where macOS would answer)."""
# Run: python3 tests/bench_icloud.py "$PWD"   (a stand-in iCloud folder; never touches the real one)
import json, os, shutil, sys, tempfile, time
T = tempfile.mkdtemp(prefix="crate-bench-")
os.environ["CRATE_ICLOUD"] = os.path.join(T, "icloud"); os.environ["VOLUMES"] = "1"; os.environ["CRATE_BACKUP_RESERVE"] = "1"
sys.path.insert(0, sys.argv[1])
import backup
DIR, USB, SRC = os.path.join(T, "app"), os.path.join(T, "Lexar"), os.path.join(T, "music")
for d in (DIR, USB, SRC, os.environ["CRATE_ICLOUD"]): os.makedirs(d)
def put(p, n):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f: f.write(os.urandom(n))
put(os.path.join(USB, "PIONEER", "rekordbox", "MYSETTING.DAT"), 2000)
for i in range(5): put(os.path.join(USB, "Contents", f"song{i}.mp3"), 50000 + i)
backup.save(DIR, place="icloud")
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or fails.append(m))
fails = []
# 1. a backup: the libraries move in whole, no .nosync / .part anywhere in iCloud Drive
got = backup.run(DIR, USB, SRC)
far = os.path.join(os.environ["CRATE_ICLOUD"], "The Crate", "USB backups", "Lexar")
names = [os.path.join(r, f) for r, ds, fs in os.walk(far) for f in fs + ds]
ok(got and got["place"] == "icloud" and got["waiting"] == 5, "first backup in iCloud, 5 songs waiting")
ok(not any(".nosync" in n or ".part" in n for n in names), "nothing named .nosync/.part in iCloud Drive")
ok(os.path.isfile(os.path.join(far, got["id"], "files", "PIONEER", "rekordbox", "MYSETTING.DAT")), "library file in place")
ok(not os.path.exists(os.path.join(DIR, "usb-backups", "Lexar", ".up")), "staging box on the Mac is gone after the move")
# 2. songs pass: macOS faked: everything in iCloud Drive says "w" (waiting), so nothing is freed and counts are honest
said = {}
real_look = backup.look
def fake(dir, paths, free=False):
    out = {}
    for p in paths:
        v = said.get(p, "w")
        if free and v == "u": v = "e"
        out[p] = v
    return out
backup.look = fake
moved, left = backup._songs(DIR, USB, "Lexar", set())
up = backup.note(DIR, "Lexar")["up"]
ok(moved and up["left"] == 0, "songs went up in one turn")
names = [os.path.join(r, f) for r, ds, fs in os.walk(far) for f in fs + ds]
ok(not any(".nosync" in n for n in names), "songs copied without a .nosync name")
ok(not os.path.exists(os.path.join(DIR, "usb-backups", "Lexar", ".up-song")), "song staging file gone")
backup._ASKED.clear()
moved, left = backup._songs(DIR, USB, "Lexar", set())
up = backup.note(DIR, "Lexar")["up"]
ok(up["sent"] == 0 and up["unsent"] == 2000 + sum(50000 + i for i in range(5)), f"nothing uploaded yet: sent 0, unsent all ({up})")
ok(left > 0, "the pass keeps going while files wait to upload")
about = json.load(open(os.path.join(DIR, "usb-backups", "Lexar", got["id"], "about.json")))
ok(about.get("sent") == 0 and about.get("unsent") == up["unsent"], "about.json says sent 0 / unsent all")
st = backup.status(DIR)["sticks"][0]
ok(st["cloud"] == 0 and st["kept"] > 0, "page's 'in iCloud' is 0 until macOS says uploaded")
# 3. macOS says uploaded: freed, counted as sent
song0 = None
for r, ds, fs in os.walk(far):
    for f in fs: said[os.path.join(r, f)] = "u"; song0 = song0 or (os.path.join(r, f) if f.endswith(".mp3") else None)
backup._ASKED.clear()
moved, left = backup._songs(DIR, USB, "Lexar", set())
up = backup.note(DIR, "Lexar")["up"]
ok(up["unsent"] == 0 and up["sent"] > 0 and up["here"] == 0 and left == 0, f"all uploaded and freed, pass can end ({up}, left {left})")
about = json.load(open(os.path.join(DIR, "usb-backups", "Lexar", got["id"], "about.json")))
ok(about.get("unsent") == 0 and about.get("sent") == up["sent"], "about.json updated")
twin = json.load(open(os.path.join(far, got["id"], "about.json")))
ok(twin.get("sent") == up["sent"], "iCloud's copy of about.json updated too")
# 3b. a file iCloud hasn't registered yet ("-") or couldn't say ("?") keeps the pass going
said[song0] = "-"; backup._ASKED.clear()
moved, left = backup._songs(DIR, USB, "Lexar", set())
ok(backup.note(DIR, "Lexar")["up"]["here"] == 1 and left > 0, "a not-yet-registered file is still pending work")
said[song0] = "u"
# 4. heal: a backup folder macOS keeps out: rebuilt with fresh folders, files moved (same inode), .nosync leftover gone
day = os.path.join(far, got["id"])
song = os.path.join(day, "files", "Contents", "song1.mp3"); ino = os.stat(song).st_ino
put(os.path.join(day, "files", "Contents", "half.mp3.nosync"), 10)
said.clear(); said[day] = "x"
n = backup.heal(DIR, os.path.join(os.environ["CRATE_ICLOUD"], "The Crate", "USB backups"), "Lexar")
ok(n == 1, "heal found the excluded backup")
ok(os.path.isfile(song) and os.stat(song).st_ino == ino, "song moved, not copied (same inode)")
ok(not os.path.exists(day + " (moving)"), "old folder gone (empty)")
ok(not os.path.exists(os.path.join(day, "files", "Contents", "half.mp3.nosync")), ".nosync fragment removed")
cnt = sum(len(fs) for _, _, fs in os.walk(day))
ok(cnt == 1 + 5 + 2, f"every file still there ({cnt})")
said.clear()
ok(backup.heal(DIR, os.path.join(os.environ["CRATE_ICLOUD"], "The Crate", "USB backups"), "Lexar") == 0, "heal does nothing on a sound folder")
# 5. heal cut short: a "(moving)" folder is carried on with
os.rename(day, day + " (moving)"); os.makedirs(day)
ok(backup.heal(DIR, os.path.join(os.environ["CRATE_ICLOUD"], "The Crate", "USB backups"), "Lexar") == 1 and os.path.isfile(song), "a heal cut short is finished")
# 6. Mac short of room: the songs pass leaves songs on the USB (reserve)
backup.look = real_look
put(os.path.join(USB, "Contents", "big.mp3"), 70000)
got2 = backup.run(DIR, USB, SRC)
backup.RESERVE = 10 ** 15
backup._ASKED.clear()
moved, left = backup._songs(DIR, USB, "Lexar", set())
ok(backup.note(DIR, "Lexar")["up"]["why"] == "room" and backup.note(DIR, "Lexar")["up"]["left"] == 1, "Mac reserve keeps the song on the USB")
ok(backup.RESERVE == 10 ** 15 and int(os.environ["CRATE_BACKUP_RESERVE"]) == 1, "")
# 7. the real look() on the stand-in folder: macOS says "-" (not in iCloud Drive), never "e"
said = backup.look(DIR, [song])
ok(said[song] in "-?", f"real macOS ask on a non-iCloud file: {said[song]!r}")
shutil.rmtree(T)
print("FAILED:" if fails else "ALL PASS", fails)
sys.exit(1 if fails else 0)
