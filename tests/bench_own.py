"""Bench test for backup.py's "My own cloud" path: the real rclone, an `alias` remote on a temp folder (no sign-in)."""
# Run: python3 tests/bench_own.py "$PWD"   (needs rclone; never signs in anywhere)
import hashlib, json, os, shutil, subprocess, sys, tempfile, time, unicodedata
T = tempfile.mkdtemp(prefix="crate-own-")
os.environ["VOLUMES"] = "1"; os.environ["CRATE_BACKUP_RESERVE"] = "1"
os.environ["CRATE_ICLOUD"] = os.path.join(T, "no-icloud")
os.environ["CRATE_RCLONE"] = shutil.which("rclone") or "/opt/homebrew/bin/rclone"
CODE = sys.argv[1]
sys.path.insert(0, CODE)
import backup, owncloud, usb_tidy
DIR, USB, SRC, CLOUD = (os.path.join(T, x) for x in ("app", "Lexar", "music", "cloud"))
for d in (DIR, USB, SRC, CLOUD): os.makedirs(d)
with open(os.path.join(DIR, "rclone.conf"), "w") as f:
    f.write(f"[crate]\ntype = alias\nremote = {CLOUD}\n")
def put(p, n):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f: f.write(os.urandom(n))
fails = []
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or fails.append(m))
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
put(os.path.join(USB, "PIONEER", "rekordbox", "MYSETTING.DAT"), 2000)
for i in range(4): put(os.path.join(USB, "Contents", f"song{i}.mp3"), 50000 + i)
nfd = unicodedata.normalize("NFD", "Beyoncé - Café.mp3")
put(os.path.join(USB, "Contents", nfd), 40000)
backup.save(DIR, place="own")
ok(owncloud.kind(DIR) == "alias" and owncloud.root(DIR) == "crate:The Crate/USB backups", "signed in (alias stand-in)")
# 1. a backup: libraries go up through .up and leave this Mac; songs wait for the pass
got = backup.run(DIR, USB, SRC)
far = os.path.join(CLOUD, "The Crate", "USB backups", "Lexar", got["id"])
ok(got and got["place"] == "own" and got["waiting"] == 5, f"first backup in own cloud, 5 songs waiting ({got and got.get('waiting')})")
ok(os.path.isfile(os.path.join(far, "files", "PIONEER", "rekordbox", "MYSETTING.DAT")), "library file is in the cloud")
ok(not os.path.exists(os.path.join(DIR, "usb-backups", "Lexar", ".up")), "temp folder on the Mac emptied")
ok(not os.path.exists(os.path.join(DIR, "usb-backups", "Lexar", got["id"], "files")), "no library copy kept on the Mac")
# 2. songs straight from the USB; sums.json; nothing of them on the Mac
moved, left = backup._songs(DIR, USB, "Lexar", set())
backup._ASKED.clear()
moved2, left2 = backup._songs(DIR, USB, "Lexar", set())
up = backup.note(DIR, "Lexar")["up"]
songs = [os.path.join(r, f) for r, _, fs in os.walk(os.path.join(far, "files", "Contents")) for f in fs]
ok(len(songs) == 5 and not left2, f"5 songs in the cloud, pass ends ({len(songs)}, left {left2}, {up})")
sums = json.load(open(os.path.join(DIR, "usb-backups", "Lexar", got["id"], "sums.json")))
ok(sums.get("Contents/song1.mp3") == sha(os.path.join(USB, "Contents", "song1.mp3")), "sums.json holds the song's sha256")
ok(sums.get("PIONEER/rekordbox/MYSETTING.DAT") == sha(os.path.join(USB, "PIONEER", "rekordbox", "MYSETTING.DAT")),
   "sums.json holds the library file's sha256")
ok(not os.path.exists(os.path.join(DIR, "usb-backups", "Lexar", ".up-song")), "no song staged on the Mac")
ok(not any(n.endswith((".tmp", ".nosync", ".partial")) for n in os.listdir(os.path.join(far, "files", "Contents"))),
   "no half files in the cloud")
st = backup.status(DIR)
s0 = st["sticks"][0]
ok(s0.get("up") and s0.get("cloud", 0) > 0 and st.get("own", {}).get("kind") == "alias", f"page sees the own cloud ({s0.get('cloud')})")
ok(st.get("free") is not None, "page shows the cloud's room left")
# 3. NFC/NFD: the accented name is found whichever way it's written
ok(owncloud.size(DIR, "crate:The Crate/USB backups/Lexar/" + got["id"] + "/files/Contents/" +
                 unicodedata.normalize("NFC", nfd)) == 40000, "accented name matched (NFC vs NFD)")
# 4. weekly check finds a damaged song (same size, same time, other bytes)
bad = os.path.join(USB, "Contents", "song2.mp3")
good = open(bad, "rb").read()
st2 = os.stat(bad)
with open(bad, "r+b") as f: f.seek(100); f.write(b"\0" * 64)
os.utime(bad, ns=(st2.st_atime_ns, st2.st_mtime_ns))
backup.check(DIR, USB, "Lexar")
n = backup.note(DIR, "Lexar")
ok(n.get("damaged") == ["Contents/song2.mp3"] and n.get("repair"), f"check found the damaged song ({n.get('damaged')})")
ok(backup.status(DIR)["sticks"][0].get("damaged") == 1, "page says 1 damaged")
# 5. repair: the good copy comes back from the cloud, the bad one goes to the USB's Trash
line = backup.restore(DIR, USB, SRC, "Lexar", got["id"])
ok("PROBLEM" not in line and open(bad, "rb").read() == good, "repair put the good copy back")
trash = [os.path.join(b, f) for b in usb_tidy.bins(USB) for f in (os.listdir(b) if os.path.isdir(b) else [])]
ok(any(f.endswith(".mp3") for f in trash), f"bad copy kept in the USB's Trash ({[os.path.basename(t) for t in trash]})")
ok(not os.path.exists(os.path.join(DIR, "usb-backups", "Lexar", ".down")), "download temp folder emptied")
ok(not backup.note(DIR, "Lexar").get("damaged"), "damaged note cleared")
ok(all(os.path.isfile(os.path.join(USB, "Contents", f"song{i}.mp3")) for i in range(4)), "every other song still on the USB")
# 6. a full cloud: said, logged, the song stays waiting
put(os.path.join(USB, "Contents", "big.mp3"), 90000)
got2 = backup.run(DIR, USB, SRC)
real_free = owncloud.free
owncloud.free = lambda d: 10
backup._ASKED.clear()
backup._songs(DIR, USB, "Lexar", set())
up = backup.note(DIR, "Lexar")["up"]
ok(up.get("why") == "full" and up.get("left", 0) >= 1, f"full cloud said, song waits ({up})")
logt = open(os.path.join(DIR, "dj.log")).read()
ok("BACKUP PROBLEM" in logt and "full" in logt, "full cloud logged as a PROBLEM")
owncloud.free = real_free
# 7. the sign-in ran out: the pass stops (nothing silent)
real_put = owncloud.put
owncloud.put = lambda d, a, b: "signin: invalid_grant"
backup._ASKED.clear()
backup._songs(DIR, USB, "Lexar", set())
ok(backup.note(DIR, "Lexar")["up"].get("why") == "signin", "sign-in again said")
ok(owncloud.why("Error: couldn't fetch token: invalid_grant") == "signin" and owncloud.why("insufficientStorage 507") == "full"
   and owncloud.why("dial tcp: no such host") == "net", "rclone's errors read right")
owncloud.put = real_put
backup._ASKED.clear()
backup._songs(DIR, USB, "Lexar", set())
up = backup.note(DIR, "Lexar")["up"]
ok(not up.get("why") and not up.get("left"), f"carries on once room / sign-in is back ({up})")
# 8. sweep_own: a pushed-out backup's files go, by name; the kept ones stay
old = os.path.join(CLOUD, "The Crate", "USB backups", "Lexar", "2020-01-01 000000", "files", "Contents")
put(os.path.join(old, "gone.mp3"), 100)
owncloud._LS.clear()
backup.sweep_own(DIR, "Lexar", out=["2020-01-01 000000"])
ok(not os.path.exists(os.path.join(old, "gone.mp3")), "pushed-out backup's file dropped")
ok(len([1 for r, _, fs in os.walk(far) for f in fs if f.endswith(".mp3")]) == 5, "kept backup's songs untouched")
# 8b. a backup pushed out of the kept ten keeps its sha256s while a kept one counts on its files: check() still hears
day1 = got["id"]
s_before = [x["id"] for x in backup.snaps(DIR, "Lexar")]
real_keep = backup.KEEP
backup.KEEP = 1
backup.prune(DIR, "Lexar")
backup.KEEP = real_keep
gone = os.path.join(DIR, "usb-backups", "Lexar", day1)
ok(day1 not in [x["id"] for x in backup.snaps(DIR, "Lexar")] and os.listdir(gone) == ["sums.json"],
   f"pruned own backup keeps only its sums.json ({s_before}, {os.listdir(gone) if os.path.isdir(gone) else None})")
ok(os.path.isfile(os.path.join(far, "files", "Contents", "song0.mp3")), "its song a kept backup counts on stays in the cloud")
s0p = os.path.join(USB, "Contents", "song0.mp3")
good0, st0 = open(s0p, "rb").read(), os.stat(s0p)
with open(s0p, "r+b") as f: f.seek(10); f.write(b"\1" * 32)
os.utime(s0p, ns=(st0.st_atime_ns, st0.st_mtime_ns))
backup.note(DIR, "Lexar", sums=None)
backup.check(DIR, USB, "Lexar")
ok("Contents/song0.mp3" in (backup.note(DIR, "Lexar").get("damaged") or []), "damage still found after the prune")
with open(s0p, "wb") as f: f.write(good0)
os.utime(s0p, ns=(st0.st_atime_ns, st0.st_mtime_ns))
backup.note(DIR, "Lexar", damaged=None, repair=None, sums=None)
# 8c. a USB whose name is written NFD ("Café"): sweep_own still finds its pushed-out files
cafe = unicodedata.normalize("NFD", "Café")
old2 = os.path.join(CLOUD, "The Crate", "USB backups", backup.safe(cafe), "2020-01-02 000000", "files")
put(os.path.join(old2, "x.mp3"), 100)
os.makedirs(os.path.join(DIR, "usb-backups", backup.safe(cafe)), exist_ok=True)
owncloud._LS.clear()
backup.sweep_own(DIR, cafe, out=["2020-01-02 000000"])
ok(not os.path.exists(os.path.join(old2, "x.mp3")) and not backup.note(DIR, cafe).get("old_own"),
   "NFD-named USB: pushed-out file dropped, nothing left waiting")
# 8d. a repair while your own cloud can't be asked: said, nothing changed, the repair stays offered
backup.save(DIR, place="mac")
backup.note(DIR, "Lexar", repair={"day": got2["id"], "why": "test", "when": 1})
had = {x["id"] for x in backup.snaps(DIR, "Lexar")}
real_ls = owncloud.listing
owncloud.listing = lambda *a, **k: None
line = backup.restore(DIR, USB, SRC, "Lexar", got2["id"])
owncloud.listing = real_ls
ok("PROBLEM" in line and "not repaired" in line and backup.note(DIR, "Lexar").get("repair"),
   f"cloud unreachable: repair stops and says so ({line[:90]})")
backup.note(DIR, "Lexar", repair=None)
for x in backup.snaps(DIR, "Lexar"):  # (the backup the repair made first would make step 9's "now" one a repeat)
    if x["id"] not in had:
        shutil.rmtree(os.path.join(DIR, "usb-backups", "Lexar", x["id"]))
# 8e. a damaged song whose good copy is not in the cloud: the repair leaves it flagged, never "all fine"
had = {x["id"] for x in backup.snaps(DIR, "Lexar")}
backup.note(DIR, "Lexar", damaged=["Contents/song3.mp3"], repair={"day": got2["id"], "why": "test", "when": 1})
real_ls = owncloud.listing
owncloud.listing = lambda *a, **k: {p: n for p, n in (real_ls(*a, **k) or {}).items() if not p.endswith("song3.mp3")}
owncloud._LS.clear()
line = backup.restore(DIR, USB, SRC, "Lexar", got2["id"])
owncloud.listing = real_ls
owncloud._LS.clear()
ok(backup.note(DIR, "Lexar").get("damaged") == ["Contents/song3.mp3"] and "no good copy" in line,
   f"damaged song with no cloud copy stays flagged ({line[-120:]})")
backup.note(DIR, "Lexar", damaged=None, repair=None)
for x in backup.snaps(DIR, "Lexar"):
    if x["id"] not in had:
        shutil.rmtree(os.path.join(DIR, "usb-backups", "Lexar", x["id"]))
# 8f. the page never waits for the cloud's room: an old answer is said, the cloud asked on the side
import json as _j
backup.save(DIR, place="own")
ap = os.path.join(DIR, ".owncloud-about.json")
a0 = _j.load(open(ap)); a0["at"] = 1; _j.dump(a0, open(ap, "w"))
real_rc = owncloud.rc
owncloud.rc = lambda *a, **k: (time.sleep(5), real_rc(*a, **k))[1]
t0 = time.time(); st = backup.status(DIR); took = time.time() - t0
owncloud.rc = real_rc
ok(took < 2 and st.get("free") is not None, f"page answers at once with the last room known ({took:.1f}s)")
# 8g. one file the cloud refuses (it answers, but won't take that one): the others still go up, that one is named once
newest = backup.snaps(DIR, "Lexar")[0]["id"]
wp = os.path.join(DIR, "usb-backups", "Lexar", newest, "waiting.json")
w = json.load(open(wp))
for n in ("r1", "r2"):
    put(os.path.join(USB, "Contents", f"{n}.mp3"), 30000)
    st3 = os.stat(os.path.join(USB, "Contents", f"{n}.mp3"))
    w[f"Contents/{n}.mp3"] = [st3.st_size, st3.st_mtime_ns, "song"]
json.dump(w, open(wp, "w"))
real_put = owncloud.put
owncloud.put = lambda d, a, b: ("net: Error: the name is not allowed" if a.endswith("r1.mp3") else real_put(d, a, b))
backup._ASKED.clear()
backup._songs(DIR, USB, "Lexar", set())
owncloud.put = real_put
up = backup.note(DIR, "Lexar")["up"]
ok(os.path.isfile(os.path.join(CLOUD, "The Crate", "USB backups", "Lexar", newest, "files", "Contents", "r2.mp3"))
   and up.get("why") != "net", f"a refused file doesn't hold the others back ({up.get('why')})")
ok('would not take "Contents/r1.mp3"' in open(os.path.join(DIR, "dj.log")).read(), "the refused file is named in the log")
# 8h. a song gone from the USB since is not "damaged" (the weekly check)
s0p = os.path.join(USB, "Contents", "song0.mp3")
os.rename(s0p, os.path.join(T, "song0.away"))
backup.note(DIR, "Lexar", sums={"day": "x", "at": 1}, damaged=None, repair=None)
backup.check(DIR, USB, "Lexar")
ok(not backup.note(DIR, "Lexar").get("damaged") and not backup.note(DIR, "Lexar").get("repair"),
   f"a song gone from the USB is not called damaged ({backup.note(DIR, 'Lexar').get('damaged')})")
os.rename(os.path.join(T, "song0.away"), s0p)
# 8i. busy is not full; a cloud that can't be asked isn't asked again at once
ok(owncloud.why("Error 429: you have exceeded the rate limit") == "net"
   and owncloud.why("quota exceeded") == "full", "a rate limit reads as busy, not full")
calls = []
owncloud.rc = lambda *a, **k: calls.append(1) or subprocess.CompletedProcess(a, 1, "", "dial tcp: no such host")
first = owncloud.listing(DIR, "crate:Nowhere/x")
second = owncloud.listing(DIR, "crate:Nowhere/x")
owncloud.rc = real_rc
ok(first is None and second is None and len(calls) == 1, f"a failed listing is not asked again at once ({len(calls)} asks)")
owncloud._FAIL.clear()
# 9. Off: no backup at plug-in; "now" still makes one, on this Mac
backup.save(DIR, place="off")
before = len(backup.snaps(DIR, "Lexar"))
subprocess.run([sys.executable, os.path.join(CODE, "backup.py"), "run", DIR, USB, SRC], env=os.environ, check=False)
ok(len(backup.snaps(DIR, "Lexar")) == before, "Off: plug-in makes no backup")
subprocess.run([sys.executable, os.path.join(CODE, "backup.py"), "run", DIR, USB, SRC, "now"], env=os.environ, check=False)
s = backup.snaps(DIR, "Lexar")
ok(len(s) == before + 1 and s[0].get("place") in ("mac", "off", None), f"Back up now with Off: one more, on this Mac ({s[0].get('place')} {before} {[x['id'] for x in s]})")
# 10. never the person's own rclone settings; the token file is private
ok(owncloud.conf(DIR) == os.path.join(DIR, "rclone.conf"), "The Crate's own rclone.conf")
shutil.rmtree(T, ignore_errors=True)
print("FAILED:" if fails else "ALL PASS", fails)
sys.exit(1 if fails else 0)
