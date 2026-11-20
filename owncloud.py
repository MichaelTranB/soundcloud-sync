#!/usr/bin/env python3
"""The person's own cloud storage (OneDrive, Dropbox or pCloud) as a place for the USB backups (backup.py), through
rclone (rclone.org, MIT licence): no second USB, and no copy of the backup on this Mac.

  Sign-in is the provider's own page in the person's browser: rclone opens it and keeps what comes back (the access
  The Crate gets to that account) in rclone.conf beside the app, readable by this Mac's user only. The Crate never
  sees a password and makes no account, app or key of its own: rclone's own sign-in is used. Google Drive is not
  offered: rclone says its shared sign-in for Google Drive stops working during 2026 (rclone.org/drive), and each
  person would have to make their own Google Cloud app first.
  Everything goes to "The Crate/USB backups/<the USB's name>/<day and time>/" in that cloud, laid out as in iCloud
  Drive. Songs go straight from the USB (rclone checks each upload against the provider's own checksum); the small
  library files pass through this Mac first (they are checked there), and leave it as soon as they are up.
  What is really there is asked of the cloud itself (a listing), never assumed, and its room (rclone about): a full
  cloud is said plainly on the page, and the songs wait until there is room.

  owncloud.py setup                  rclone into ~/.local/bin (pinned version, checked by its sha256), when missing
  owncloud.py connect DIR KIND       the provider's sign-in in the browser; the page starts this
  owncloud.py disconnect DIR         The Crate's access to that cloud is taken back here (the backups there stay)

Standard library only."""
import configparser, hashlib, json, os, platform, re, shutil, subprocess, sys, tempfile, time, unicodedata, urllib.request, zipfile

REMOTE, CONF, STATE = "crate", "rclone.conf", ".owncloud.json"
TOP = "The Crate/USB backups"
KINDS = {"onedrive": "OneDrive", "dropbox": "Dropbox", "pcloud": "pCloud"}
VERSION = "v1.76.0"  # downloads.rclone.org/v1.76.0/SHA256SUMS
SUMS = {"arm64": "e72dc90b70f4947a7b72b61bde4a4fbba5777b2874fb448951ffdde67ebd0ab7",
        "amd64": "4f5835733d52b818340f97b1fc0348a70461534d123363a183ca2b660219595a"}
MINE = os.path.expanduser("~/.local/bin/rclone")
MARGIN = 50 * 1024 ** 2  # room left free in the cloud (its own lists still fit)


def binary():
    """rclone on this Mac ("" when there is none): the one The Crate put there, else Homebrew's or any on the PATH."""
    for p in (os.environ.get("CRATE_RCLONE"), MINE, "/opt/homebrew/bin/rclone", "/usr/local/bin/rclone",
              shutil.which("rclone")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return ""


def setup():
    """rclone, when this Mac has none: the official build of VERSION, taken only when its sha256 is the one above."""
    if binary():
        return binary()
    arch = "arm64" if platform.machine() == "arm64" else "amd64"
    name = f"rclone-{VERSION}-osx-{arch}"
    with tempfile.TemporaryDirectory() as t:
        z = os.path.join(t, name + ".zip")
        urllib.request.urlretrieve(f"https://downloads.rclone.org/{VERSION}/{name}.zip", z)
        if sha256(z) != SUMS[arch]:
            raise OSError("the rclone download is not the one expected (sha256): not used")
        with zipfile.ZipFile(z) as zf, zf.open(f"{name}/rclone") as src:
            os.makedirs(os.path.dirname(MINE), exist_ok=True)
            with open(MINE + ".tmp", "wb") as out:
                shutil.copyfileobj(src, out)
        os.chmod(MINE + ".tmp", 0o755)
        subprocess.run(["xattr", "-d", "com.apple.quarantine", MINE + ".tmp"], capture_output=True)
        os.replace(MINE + ".tmp", MINE)
    return MINE


def conf(dir):
    return os.path.join(dir, CONF)


def rc(dir, *args, timeout=3600, conf_at=None):
    """rclone with The Crate's own settings file (never the person's own rclone setup)."""
    exe = binary()
    if not exe:
        return subprocess.CompletedProcess(args, 127, "", "rclone is not on this Mac")
    try:
        return subprocess.run([exe, "--config", conf_at or conf(dir), "--low-level-retries", "3", "--retries", "2",
                               *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "it took too long (is this Mac online?)")
    except OSError as e:
        return subprocess.CompletedProcess(args, 126, "", str(e))


def kind(dir):
    """The kind of cloud The Crate is signed in to ("" when none)."""
    c = configparser.ConfigParser(interpolation=None)
    try:
        c.read(conf(dir))
        return c.get(REMOTE, "type", fallback="")
    except configparser.Error:
        return ""


def label(dir):
    k = kind(dir)
    return KINDS.get(k, k.capitalize() if k else "")


def root(dir):
    """Where the backups go in that cloud, as rclone names it ("": not signed in, or no rclone)."""
    return f"{REMOTE}:{TOP}" if kind(dir) and binary() else ""


def ours(path):
    return isinstance(path, str) and path.startswith(REMOTE + ":")


def why(text):
    """What went wrong, in a word the page explains: "full", "signin" (sign in again) or "net"."""
    t = text or ""
    if re.search(r"quota|insufficient.?storage|not enough (space|storage)|storage.{0,20}full|exceed\w* .{0,30}(limit|space)"
                 r"|\b507\b|space_left|insufficient_space", t, re.I):
        return "full"
    if re.search(r"invalid_grant|token.{0,30}(expired|revoked|invalid)|unauthori[sz]ed|\b401\b|re-?auth"
                 r"|couldn't fetch token|empty token", t, re.I):
        return "signin"
    return "net"


def tail(text):
    lines = [x for x in (text or "").strip().splitlines() if x.strip()]
    return lines[-1][-300:] if lines else ""


# What is in the cloud under one USB's folder, by full rclone path: {path: size}. Asked once and kept up to date by
# what is sent and dropped here; asked again after LS seconds, or after a send failed.
_LS, LS, _REAL = {}, 600, {}


def nfc(path):
    """Names compared the same however their accents are written (macOS, a USB and a cloud each may differ)."""
    return unicodedata.normalize("NFC", path)


def real(path):
    """The name the cloud itself uses for a file the listing holds (for a fetch or a drop)."""
    return _REAL.get(nfc(path), path)


def _key(path):
    return "/".join(path.split("/")[:3])  # crate:The Crate / USB backups / <USB>


def listing(dir, path, fresh=False):
    """{path: size} of every file under a USB's folder in the cloud (None: the cloud can't be asked now)."""
    k = _key(path)
    got = _LS.get(k)
    if got and not fresh and time.time() - got[0] < LS:
        return got[1]
    r = rc(dir, "lsjson", "-R", "--files-only", "--no-mimetype", "--fast-list", k, timeout=600)
    if r.returncode == 3 or (r.returncode and "directory not found" in r.stderr):
        files = {}
    elif r.returncode:
        return None
    else:
        try:
            files = {}
            for x in json.loads(r.stdout or "[]"):
                p = f"{k}/{x['Path']}"
                files[nfc(p)] = x["Size"]
                if nfc(p) != p:
                    _REAL[nfc(p)] = p
        except (ValueError, KeyError, TypeError):
            return None
    _LS[k] = (time.time(), files)
    return files


def size(dir, path):
    """A file's size in the cloud (-1: not there, or the cloud can't be asked)."""
    got = listing(dir, path)
    return -1 if got is None else got.get(nfc(path), -1)


def isdir(dir, path):
    got = listing(dir, path) or {}
    path = nfc(path.rstrip("/")) + "/"
    return any(p.startswith(path) for p in got)


def _seen(path, n):
    k = _key(path)
    if k in _LS:
        if n < 0:
            _LS[k][1].pop(nfc(path), None)
        else:
            _LS[k][1][nfc(path)] = n


def put(dir, local, path):
    """One file up (rclone checks it against the cloud's own checksum). Returns "" or why it didn't go."""
    r = rc(dir, "copyto", local, path)
    if r.returncode:
        return why(r.stderr) + ": " + tail(r.stderr)
    _seen(path, os.path.getsize(local))
    return ""


def send(dir, folder, path):
    """A folder's files up, each leaving this Mac once it is up and checked (rclone move). "" or why not."""
    sizes = {os.path.relpath(os.path.join(r, f), folder).replace(os.sep, "/"): os.path.getsize(os.path.join(r, f))
             for r, _, fs in os.walk(folder) for f in fs}
    r = rc(dir, "move", folder, path, "--delete-empty-src-dirs")
    if r.returncode:
        _LS.pop(_key(path), None)
        return why(r.stderr) + ": " + tail(r.stderr)
    for rel, n in sizes.items():
        _seen(f"{path}/{rel}", n)
    shutil.rmtree(folder, ignore_errors=True)
    return ""


def get(dir, path, local):
    """One file down from the cloud. "" or why not."""
    r = rc(dir, "copyto", real(path), local)
    return why(r.stderr) + ": " + tail(r.stderr) if r.returncode else ""


def drop(dir, paths):
    """Files of pushed-out backups leave the cloud (each one by name; never a folder as a whole). Returns how many
    could not be dropped (they are tried again next time)."""
    paths, bad = list(paths), 0
    for p in paths:
        r = rc(dir, "deletefile", real(p), timeout=300)
        if r.returncode and size(dir, p) >= 0:
            bad += 1
        else:
            _seen(p, -1)
    if paths:
        rc(dir, "rmdirs", _key(paths[0]), "--leave-root", timeout=300)  # (only empty folders go)
    return bad


def about(dir, every=300):
    """The cloud's room: {"total", "used", "free", "at"} in bytes (a provider that doesn't tell one: None), kept for
    `every` seconds so the page never waits. {"why": ...} when the cloud can't be asked."""
    p = os.path.join(dir, ".owncloud-about.json")
    try:
        with open(p) as f:
            got = json.load(f)
        if time.time() - got.get("at", 0) < every and got.get("kind") == kind(dir):
            return got
    except (OSError, ValueError, AttributeError):
        pass
    if not root(dir):
        return None
    r = rc(dir, "about", f"{REMOTE}:", "--json", timeout=60)
    try:
        if r.returncode:
            raise ValueError(r.stderr)
        a = json.loads(r.stdout)
        got = {"total": a.get("total"), "used": a.get("used"), "free": a.get("free")}
    except ValueError:
        got = {"why": why(r.stderr), "said": tail(r.stderr)}
    got.update(at=int(time.time()), kind=kind(dir))
    try:
        with open(p + ".tmp", "w") as f:
            json.dump(got, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass
    return got


def free(dir):
    """Room left in the cloud to fill, MARGIN kept back (None: it can't be told)."""
    a = about(dir) or {}
    return None if a.get("free") is None else a["free"] - MARGIN


def state(dir):
    try:
        with open(os.path.join(dir, STATE)) as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _state(dir, **new):
    got = {k: v for k, v in {**state(dir), **new}.items() if v is not None}
    with open(os.path.join(dir, STATE) + ".tmp", "w") as f:
        json.dump(got, f)
    os.replace(os.path.join(dir, STATE) + ".tmp", os.path.join(dir, STATE))


def connecting(dir):
    """A sign-in started from the page that is still open in the browser."""
    pid = state(dir).get("pid")
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, OSError):
        return False


def status(dir):
    """For the page: which cloud, signed in or not, a sign-in at work, its room, and the last thing that went wrong."""
    return {"kind": kind(dir), "label": label(dir), "kinds": KINDS, "connecting": connecting(dir),
            "said": state(dir).get("said"), "about": about(dir, every=3600) if kind(dir) else None}


def connect(dir, k):
    """The provider's own sign-in page opens in the browser (rclone runs it, on this Mac only); once the person has
    signed in and allowed The Crate, the access is kept in rclone.conf. Waits up to 10 minutes for that."""
    if k not in KINDS:
        return f"Not a cloud The Crate can use: {k}."
    _state(dir, pid=os.getpid(), said="", at=int(time.time()))
    new = conf(dir) + ".new"
    try:
        try:
            setup()
        except OSError as e:
            return _said(dir, f"rclone could not be set up ({e}).")
        with open(new, "w"):
            pass
        os.chmod(new, 0o600)
        r = rc(dir, "config", "create", REMOTE, k, "config_is_local=true", conf_at=new, timeout=600)
        if r.returncode or not open(new).read().strip():
            return _said(dir, "The sign-in did not finish (closed, or 10 minutes passed). Try again.")
        t = rc(dir, "lsf", "--max-depth", "1", f"{REMOTE}:", conf_at=new, timeout=60)
        if t.returncode:
            return _said(dir, f"Signed in, but {KINDS[k]} could not be opened: {tail(t.stderr)}")
        os.replace(new, conf(dir))
        if os.path.exists(os.path.join(dir, ".owncloud-about.json")):
            os.remove(os.path.join(dir, ".owncloud-about.json"))
        _LS.clear()
        return _said(dir, f"backup: signed in to {KINDS[k]}: USB backups can go there now.", ok=True)
    finally:
        if os.path.exists(new):
            os.remove(new)
        _state(dir, pid=None)


def _said(dir, text, ok=False):
    _state(dir, said="" if ok else text)
    with open(os.path.join(dir, "dj.log"), "a") as f:
        f.write(time.strftime("%F %R") + "  " + (text if ok else "BACKUP PROBLEM: " + text) + "\n")
    return text


def disconnect(dir):
    """The Crate's access to that cloud goes (the provider is told where rclone can). The backups there stay."""
    if kind(dir):
        rc(dir, "config", "disconnect", REMOTE + ":", timeout=60)
    for p in (CONF, ".owncloud-about.json", STATE):
        try:
            os.remove(os.path.join(dir, p))
        except OSError:
            pass
    _LS.clear()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["setup"]:
        print(setup())
    elif len(a) == 3 and a[0] == "connect":
        print(connect(a[1], a[2]))
    elif len(a) == 2 and a[0] == "disconnect":
        disconnect(a[1])
    else:
        sys.exit(__doc__)
