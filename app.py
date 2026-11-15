#!/usr/bin/env python3
"""The Crate: a small local page for the SoundCloud sync. Standard library only.

Listens on 127.0.0.1 only. Every write checks the Host and Origin headers, so another website open
in the browser cannot press the buttons.
"""
import json, os, plistlib, re, shutil, subprocess, sys, threading, time, urllib.parse
import audio, freedl, playlists, safety, soulseek
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser("~/Music/SoundCloud Sync")
SLSK = os.path.join(OUT, "From Soulseek")  # soulseek.sh's downloads
PORT = int(os.environ.get("CRATE_PORT", 4780))  # another port only for trying a copy side by side
HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus")
PLAYLIST_RE = re.compile(r"^https://(on\.|m\.|www\.)?soundcloud\.com/\S+$")


def is_playlist(url):
    """A SoundCloud, Spotify or Apple Music playlist link."""
    return bool(PLAYLIST_RE.match(url) or playlists.service(url))
PROFILE_RE = re.compile(r"^(?:https?://(?:www\.|m\.)?soundcloud\.com/)?([A-Za-z0-9_-]{1,60})/?$")
# "none" lists public playlists only; the others borrow the SoundCloud session of that browser.
BROWSERS = ("chrome", "safari", "brave", "firefox", "edge", "none")
YTDLP = next((p for p in (shutil.which("yt-dlp"), os.path.expanduser("~/.local/bin/yt-dlp"), "/opt/homebrew/bin/yt-dlp",
                          "/usr/local/bin/yt-dlp") if p and os.access(p, os.X_OK)), "yt-dlp")
_slsk = {"at": 0.0, "ok": False, "user": ""}
_lists = threading.Lock()  # one change to saved.json / playlist.txt at a time (the server is threaded)


def read(name, default=""):
    try:
        with open(os.path.join(DIR, name)) as f:
            return f.read().strip()
    except OSError:
        return default


def volumes():
    try:
        return sorted(v for v in os.listdir("/Volumes") if v not in ("Macintosh HD", "Recovery") and not v.startswith("."))
    except OSError:
        return []


BROWSER_APPS = {"com.google.chrome": "chrome", "com.apple.safari": "safari", "com.brave.browser": "brave",
                "com.microsoft.edgemac": "edge", "org.mozilla.firefox": "firefox"}


def default_browser():
    """The Mac's own default web browser (System Settings > Desktop & Dock), when it's one the sync can borrow a
    sign-in from; Safari when none was ever picked. A copy set up before this (it has a playlist) stays on Chrome."""
    if read("playlist.txt"):
        return "chrome"
    try:
        with open(os.path.expanduser(
                "~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"), "rb") as f:
            handlers = plistlib.load(f).get("LSHandlers", [])
    except (OSError, ValueError, plistlib.InvalidFileException):
        handlers = []
    for h in handlers:
        if h.get("LSHandlerURLScheme") in ("https", "http"):
            return BROWSER_APPS.get(str(h.get("LSHandlerRoleAll", "")).lower(), "safari")
    return "safari"


def browser():
    """The browser whose SoundCloud sign-in the sync borrows: the Mac's default until one is picked on the page;
    "none" = no sign-in. The first guess is saved, since sync.sh reads the same file."""
    b = read("browser.txt", None)
    if b is None:
        b = default_browser()
        try:
            with open(os.path.join(DIR, "browser.txt"), "w") as f:
                f.write(b + "\n")
        except OSError:
            pass
    return b or "none"


# Where each browser keeps its sign-ins. macOS lets the sync read them only after Crate Helper gets Full Disk Access.
COOKIE_DIRS = {
    "chrome": "~/Library/Application Support/Google/Chrome",
    "safari": "~/Library/Containers/com.apple.Safari/Data/Library/Cookies",
    "brave": "~/Library/Application Support/BraveSoftware/Brave-Browser",
    "edge": "~/Library/Application Support/Microsoft Edge",
    "firefox": "~/Library/Application Support/Firefox",
}


def sign_in_status(b):
    """ok: the sync can read that browser's sign-in. blocked: macOS needs Full Disk Access for Crate Helper.
    missing: that browser isn't on this Mac. off: no sign-in chosen."""
    if b not in COOKIE_DIRS:
        return "off"
    d = os.path.expanduser(COOKIE_DIRS[b])
    if b == "safari" and os.path.exists(os.path.expanduser("~/Library/Cookies/Cookies.binarycookies")):
        d = os.path.expanduser("~/Library/Cookies")  # where yt-dlp looks first (sync.sh does the same)
    try:
        os.listdir(d)
        return "ok"
    except PermissionError:
        return "blocked"
    except OSError:
        return "missing"


SLSK_SERVICE = "soundcloud-sync-soulseek"  # the Keychain item soulseek.sh reads
SOCKSEEK = os.path.expanduser("~/.local/bin/sockseek")


def soulseek_login(user, pw):
    """Checks a Soulseek name and password with one test search, then saves them in the Keychain.
    Soulseek makes the account the first time a new name signs in. '' when saved, else the reason in plain words."""
    if not user or not pw:
        return "Type a Soulseek name and a password."
    if len(user) > 30 or len(pw) > 64 or any(c in user + pw for c in '"\\\n\r\t'):
        return "Use a name up to 30 characters and a password up to 64, without quotes or backslashes."
    if not os.access(SOCKSEEK, os.X_OK):
        return "The Soulseek downloader isn't installed yet: run the installer again."
    try:  # sockseek takes the sign-in only as arguments; this Mac's own user is the only one who could see them
        r = subprocess.run([SOCKSEEK, "Daft Punk - Around the World", "-s", "--print", "results", "--no-config",
                            "--no-progress", "--user", user, "--pass", pw], capture_output=True, text=True, timeout=90)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "Soulseek didn't answer in time. Check the internet and try again."
    if re.search(r"invalid ?pass|login failed|logged out|unauthor", out, re.I):
        return "Soulseek said no: that name is taken with a different password. Try another name."
    if re.search(r"error|exception", out, re.I):
        return "Couldn't reach Soulseek right now. Try again in a minute."
    while subprocess.run(["security", "delete-generic-password", "-s", SLSK_SERVICE],
                         capture_output=True).returncode == 0:
        pass
    # `security -i` reads the command from stdin, so the password never shows in a process list.
    r = subprocess.run(["security", "-i"], input=f'add-generic-password -U -s {SLSK_SERVICE} -a "{user}" '
                       f'-T /usr/bin/security -w "{pw}"\n', capture_output=True, text=True)
    if r.returncode or r.stderr.strip():
        return "The Mac's Keychain wouldn't save it. Try again."
    _slsk["at"] = 0.0
    return ""


def sync_phase():
    """'' when no sync runs, else what it's doing: reading SoundCloud first, then Soulseek (its log is newer than
    the sync's flag)."""
    if not sync_running():
        return ""
    try:
        started = os.path.getmtime(os.path.join(DIR, ".running"))
        return "soulseek" if os.path.getmtime(os.path.join(DIR, "soulseek-pass.log")) >= started else "soundcloud"
    except OSError:
        return "soundcloud"


SYNC_PLIST = os.path.expanduser("~/Library/LaunchAgents/com.thecrate.sync.plist")
_sched = {"applied": ""}  # the auto-sync time last confirmed in the daily job's schedule


def sync_time():
    """The daily auto-sync time, "HH:MM" (24-hour), picked on the page; 03:10 until then."""
    t = read("sync-time.txt")
    return t if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) else "03:10"


def apply_sync_time():
    """Puts the picked time into the daily sync job (launchd) and reloads it. Reloading would stop a sync that job
    started, so while one runs this waits: state() calls it again on the next refresh. Only this copy's own job."""
    t = sync_time()
    if _sched["applied"] == t:
        return
    try:
        with open(SYNC_PLIST, "rb") as f:
            pl = plistlib.load(f)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return
    if DIR.rstrip("/") + "/" not in json.dumps(pl.get("ProgramArguments", [])):
        return
    h, m = (int(x) for x in t.split(":"))
    job = f"gui/{os.getuid()}"
    if pl.get("StartCalendarInterval") != {"Hour": h, "Minute": m}:
        if sync_running():
            return
        pl["StartCalendarInterval"] = {"Hour": h, "Minute": m}
        with open(SYNC_PLIST, "wb") as f:
            plistlib.dump(pl, f)
        subprocess.run(["launchctl", "bootout", job + "/com.thecrate.sync"], capture_output=True)
    if load_job("com.thecrate.sync", SYNC_PLIST):
        _sched["applied"] = t


def load_job(label, plist):
    """Loads a launchd job if it isn't loaded. Loading right after unloading often fails at first ("Bootstrap
    failed: 5"), so it's tried a few times; True once the job is loaded."""
    job = f"gui/{os.getuid()}"
    for _ in range(3):
        if subprocess.run(["launchctl", "print", f"{job}/{label}"], capture_output=True).returncode == 0:
            return True
        subprocess.run(["launchctl", "bootstrap", job, plist], capture_output=True)
        time.sleep(1)
    print(f"couldn't load {label}; trying again soon", file=sys.stderr)
    return False


def reload_jobs():
    """install.sh (an update) leaves a job that was busy for later, as reloading it would stop the sync or copy it
    runs (.reload-<job>): reloaded here, with its new settings, once it's finished."""
    for label, busy in (("com.thecrate.sync", sync_running), ("com.thecrate.usb", usb_copy)):
        flag = os.path.join(DIR, ".reload-" + label)
        if not os.path.exists(flag) or busy():
            continue
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
        if load_job(label, os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")):
            os.remove(flag)


def usb_copy():
    """The copy to the USB running now (usb.sh writes .usb-copy): its stage ("checking" the files first, then
    "copying"), the tracks copied so far and how many it's copying. None when no copy runs."""
    try:
        pid, stage, total = read(".usb-copy").split()[:3]
        os.kill(int(pid), 0)
        total = int(total)
    except (ValueError, OSError):
        return None
    done = sum(1 for l in read(".usb-progress").splitlines() if l and not l.endswith("/"))
    return {"stage": stage, "done": min(done, total), "total": total}


def usb_result(lines):
    """How the last copy ended (usb.log), for the page: when, whether it worked, and what to say."""
    for i in range(len(lines) - 1, max(len(lines) - 30, -1), -1):
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d)  (copied to \"(.*)\" \((\d+) new(?:, (\d+) on it)?(, sync still running)?\)"
                     r"|COPY FAILED to \"(.*?)\"(?:: (.*))?)$", lines[i])
        if m:
            at = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M"))
            if m.group(3) is not None:
                n, usb, total, mid = int(m.group(4)), m.group(3), m.group(5), bool(m.group(6))
                ejected = any("ejected" in l for l in lines[i + 1:])
                tracks = lambda k: f"{k} new track{'s' if k != 1 else ''}"
                if mid:  # a sync is still getting tracks: the page copies the next ones over by itself
                    text = (f"{tracks(n)} copied so far" if n else "Up to date so far") + (f" ({total} on {usb})" if total else "") + \
                        ". Still syncing: new tracks go on as they arrive, then it's ejected. Keep it plugged in."
                else:
                    text = (f"Done: {tracks(n)} copied" + (f"; {usb} has all {total}." if total else f" to {usb}.") if n else
                            f"Done: {usb} has all {total} tracks." if total else f"{usb} already has every track.") + \
                        (" Ejected: safe to unplug." if ejected else "")
                return {"at": at, "ok": True, "mid": mid, "text": text}
            return {"at": at, "ok": False, "text": f"Couldn't copy to {m.group(7)}: " + (m.group(8) or "something went wrong. Try Copy Now again.")}
    return None


def sync_running():
    """True while sync.sh runs: .running holds its process number (a flag left by a killed sync doesn't count)."""
    try:
        with open(os.path.join(DIR, ".running")) as f:
            os.kill(int(f.read().strip()), 0)
        return True
    except PermissionError:
        return True  # the process exists
    except (OSError, ValueError):
        return False


def soulseek_ready():
    """True once a Soulseek sign-in is saved (reads only the item's name, never the password)."""
    if time.time() - _slsk["at"] > 60:
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", "soundcloud-sync-soulseek"],
                               capture_output=True, text=True, timeout=10)
            _slsk["ok"] = r.returncode == 0
            m = re.search(r'"acct"<blob>="([^"]*)"', r.stdout)  # the saved name; the password is never read
            _slsk["user"] = m.group(1) if m and r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            _slsk["ok"], _slsk["user"] = False, ""
        _slsk["at"] = time.time()
    return _slsk["ok"]


def saved():
    """Playlists he added or picked, newest first: [{'title', 'url'}]. Before the first save, the playlist
    already syncing (set up before this list existed) shows as the one entry."""
    raw = read("saved.json")
    if not raw:
        cur = read("playlist.txt")
        return [{"title": cur.rstrip("/").split("/")[-1].replace("-", " "), "url": cur}] if is_playlist(cur) else []
    try:
        return [p for p in json.loads(raw) if is_playlist(str(p.get("url", "")))]
    except (ValueError, AttributeError):
        return []


def save_list(lists):
    tmp = os.path.join(DIR, "saved.json.tmp")
    with open(tmp, "w") as f:
        json.dump(lists, f, indent=1)
    os.replace(tmp, os.path.join(DIR, "saved.json"))


def remember(url, title):
    """Adds (or moves to the front) a playlist in the saved list and makes it the one that syncs."""
    with _lists:
        _remember(url, title)


def _remember(url, title):
    save_list([{"title": title, "url": url}] + [p for p in saved() if p["url"] != url])
    with open(os.path.join(DIR, "playlist.txt"), "w") as f:
        f.write(url + "\n")


def title_of(url):
    """The playlist's name from SoundCloud (no sign-in needed for a public playlist or a private Share link),
    Spotify or Apple Music (public playlists)."""
    if playlists.service(url):
        try:
            p = playlists.read(url)
        except Exception:  # their page changed or didn't answer: the plain message below says so
            return None
        return p["title"][:120] if p["tracks"] else None
    try:
        r = subprocess.run([YTDLP, "--flat-playlist", "--dump-single-json", "--no-warnings", url],
                           capture_output=True, text=True, timeout=120)
        d = json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        d = {}
    if not d:
        return None
    return (d.get("title") or url.rstrip("/").split("/")[-1])[:120]


def account():
    try:
        return json.loads(read("account.json") or "{}")
    except ValueError:
        return {}


def connect(profile, browser):
    """Lists the profile's playlists, signed in through the chosen browser. Returns an error or None."""
    cmd = [YTDLP, "--flat-playlist", "--dump-single-json", f"https://soundcloud.com/{profile}/sets"]
    if browser != "none":
        cmd[1:1] = ["--cookies-from-browser", cookie_arg(browser)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "SoundCloud took too long to answer. Try again."
    try:
        entries = json.loads(r.stdout).get("entries") or []
    except ValueError:
        err = [l for l in r.stderr.splitlines() if l.startswith("ERROR")]
        if re.search(r"cookies database|operation not permitted|permission denied", r.stderr, re.I):
            return ("macOS doesn't let The Crate read your browser's sign-in yet: turn on Crate Helper in System "
                    "Settings > Privacy & Security > Full Disk Access. Or paste your playlist link above instead.")
        return (err[-1][7:] if err else "Could not read that profile.")[:300]
    lists = [{"title": e.get("title") or e["url"].rstrip("/").split("/")[-1], "url": e["url"]}
             for e in entries if PLAYLIST_RE.match(str(e.get("url", "")))]
    lists.append({"title": "Liked tracks", "url": f"https://soundcloud.com/{profile}/likes"})
    with open(os.path.join(DIR, "account.json"), "w") as f:
        json.dump({"profile": profile, "browser": browser, "playlists": lists}, f)
    set_browser(browser)
    return None


def set_browser(b):
    # sync.sh reads this one line to know which browser's sign-in to borrow (empty: none).
    if b == browser():
        return
    with open(os.path.join(DIR, "browser.txt"), "w") as f:
        f.write("" if b == "none" else b + "\n")
    try:  # a new browser: its signed-in profile is found again
        os.remove(os.path.join(DIR, "profile.txt"))
    except OSError:
        pass
    _login.update(at=0.0, state="", profile="")


def login_seen(text):
    """What a yt-dlp run says about the SoundCloud sign-in: ok, invalid, none (no SoundCloud sign-in in that
    browser), or '' (no browser sign-in was used). yt-dlp only says "Verifying login token" when the browser
    holds a SoundCloud sign-in. One track's original refused (401) while signed in is that track, not the sign-in."""
    t = text.lower()
    if "authorization token is invalid" in t:
        return "invalid"
    if "verifying login token" in t:
        return "ok"
    return "none" if re.search(r"extracted \d+ cookies from", t) else ""


_login = {"at": 0.0, "state": "", "profile": "", "busy": False, "soon": 0.0}  # the page's own re-check (sign_in_check)
LOGIN_FILE = os.path.join(DIR, ".signin-check.json")  # kept on disk, so a restart doesn't forget a fresh sign-in
try:
    with open(LOGIN_FILE) as f:
        _saved = json.load(f)
    if _saved.get("browser") == browser():
        _login.update(at=float(_saved["at"]), state=str(_saved["state"]), profile=str(_saved.get("profile", "")))
except (OSError, ValueError, KeyError, TypeError, NameError):
    pass


def save_login(b):
    try:
        with open(LOGIN_FILE, "w") as f:
            json.dump({"browser": b, "at": _login["at"], "state": _login["state"], "profile": _login["profile"]}, f)
    except OSError as e:
        print(f"couldn't save the sign-in check: {e!r}", file=sys.stderr)


def has_cookies(folder):
    """A browser profile folder with a cookie store (newer Chrome keeps it in Network/)."""
    return os.path.exists(os.path.join(folder, "Cookies")) or os.path.exists(os.path.join(folder, "Network", "Cookies"))


def cookie_arg(b):
    """yt-dlp's --cookies-from-browser value: the browser, plus the profile that holds the SoundCloud sign-in
    once one was found (profile.txt); without it yt-dlp reads the most recently used profile."""
    saved, _, p = read("profile.txt").strip().partition(":")  # "browser:folder"
    ok = b in ("chrome", "brave", "edge") and saved == b and p and has_cookies(
        os.path.join(os.path.expanduser(COOKIE_DIRS[b]), p))
    return f"{b}:{p}" if ok else b


def ask_soundcloud(arg, url, extra=()):
    """(state, profile folder) from one track looked up with that sign-in; state '' when SoundCloud didn't answer."""
    try:
        r = subprocess.run([YTDLP, "-v", "--cookies-from-browser", arg, "--simulate", "--no-playlist",
                            "--ignore-no-formats-error", "--extractor-args", "soundcloud:formats=none", *extra, url],
                           capture_output=True, text=True, errors="replace", timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    out = r.stdout + r.stderr
    m = re.search(r'Extracting cookies from: "([^"]+)"', out)
    state = login_seen(out)
    answered = state == "ok" or "downloading info json" in out.lower()
    folder = os.path.dirname(m.group(1)) if m else ""
    if os.path.basename(folder) == "Network":  # newer Chrome: <profile>/Network/Cookies
        folder = os.path.dirname(folder)
    return (state if answered else ""), folder


def sign_in_check(b):
    """Asks SoundCloud about one playlist track with the browser's sign-in, so the page notices a fresh sign-in
    without waiting for the next sync. When that profile has no SoundCloud sign-in, tries the browser's other
    profiles and keeps the first one that is signed in (profile.txt), so the sync uses it too."""
    try:
        # One track from the last sync's list; before the first sync, the first track of the playlist itself.
        first = read(".playlist").split("\n")[0].split(" ")
        url, extra = (first[1], ()) if len(first) > 1 and "soundcloud.com/" in first[1] else (read("playlist.txt").strip(), ("--playlist-items", "1"))
        if "soundcloud.com/" not in url:
            return
        arg = cookie_arg(b)
        state, folder = ask_soundcloud(arg, url, extra)
        if state == "ok" and folder and arg == b and b in ("chrome", "brave", "edge") and browser() == b:
            # Signed in on the profile used most recently right now: keep that one, since yt-dlp otherwise
            # reads whichever profile was used last, and by the next sync that can be one with no sign-in.
            with open(os.path.join(DIR, "profile.txt"), "w") as f:
                f.write(f"{b}:{os.path.basename(folder)}\n")
        if state in ("none", "invalid") and b in ("chrome", "brave", "edge"):
            root = os.path.expanduser(COOKIE_DIRS[b])
            others = [d for d in sorted(os.listdir(root)) if (d == "Default" or d.startswith("Profile "))
                      and os.path.join(root, d) != folder and has_cookies(os.path.join(root, d))]
            for d in others[:8]:
                if browser() != b:
                    return  # he switched browsers meanwhile: this answer is for the old one
                s2, f2 = ask_soundcloud(f"{b}:{d}", url, extra)
                if s2 == "ok":
                    with open(os.path.join(DIR, "profile.txt"), "w") as f:
                        f.write(f"{b}:{d}\n")
                    state, folder = s2, f2
                    break
        if state and browser() == b:
            _login.update(state=state, profile=profile_name(b, folder) if folder else "")
    except Exception as e:  # logged, and the next check still runs
        print(f"sign-in check failed: {e!r}", file=sys.stderr)
    finally:
        _login.update(at=time.time(), busy=False)
        save_login(b)


def profile_name(b, folder):
    """The name the browser shows for that profile folder, when it has more than one profile; else ''."""
    try:
        with open(os.path.join(os.path.dirname(folder), "Local State")) as f:
            cache = json.load(f)["profile"]["info_cache"]
        return cache[os.path.basename(folder)]["name"] if len(cache) > 1 else ""
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def login_state(log=None):
    """The SoundCloud sign-in as last seen: the page's own re-check when it is newer than the last sync, else what
    that sync's log says (login_seen)."""
    if log is None:
        log = (read("last-run.log") + read("signin.log")).lower()
    try:
        ran = os.path.getmtime(os.path.join(DIR, "last-run.log"))
    except OSError:
        ran = 0.0
    return _login["state"] if _login["at"] > ran and _login["state"] else login_seen(log)


def watch_login(svc):
    """While the SoundCloud sign-in isn't confirmed, asks SoundCloud again in the background: every 2 minutes, and
    every 15 seconds for 5 minutes after the sign-in button or coming back to the page (/api/signin), so a fresh
    sign-in ticks within seconds instead of after the next sync. Not while the sync itself is asking SoundCloud."""
    b = browser()
    if svc or not read("playlist.txt") or _login["busy"] or sign_in_status(b) != "ok" or login_state() == "ok":
        return
    if time.time() - _login["at"] > (15 if time.time() < _login["soon"] else 120) and sync_phase() != "soundcloud":
        _login["busy"] = True
        threading.Thread(target=sign_in_check, args=(b,), daemon=True).start()


def problem():
    """One plain line when the last sync could not sign in or reach SoundCloud; empty when fine."""
    svc = playlists.service(read("playlist.txt"))
    if svc:  # a Spotify or Apple Music playlist: no SoundCloud sign-in involved
        if "couldn't read the playlist page" in read("last-run.log").lower():
            return (f"The last sync couldn't read this {'Spotify' if svc == 'spotify' else 'Apple Music'} playlist. "
                    "Check it's public (Share > Copy link to playlist), then press Sync now.")
        return ""
    log = (read("last-run.log") + read("signin.log")).lower()
    b = browser()
    name = {"chrome": "Chrome", "safari": "Safari", "brave": "Brave", "edge": "Edge", "firefox": "Firefox"}.get(b, "")
    if name and ("operation not permitted" in log or "permission denied" in log or sign_in_status(b) == "blocked"):
        return ("Originals need one switch: System Settings > Privacy & Security > Full Disk Access > turn on "
                "Crate Helper. Until then, missing tracks come from Soulseek and the shops.")
    state = login_state(log)
    if name and state in ("none", "invalid"):
        where = f"{name} (profile \"{_login['profile']}\")" if _login["profile"] else name
        first = ("SoundCloud's sign-in in {w} has run out" if state == "invalid"
                 else "You're not signed in to SoundCloud in {w}").format(w=where)
        return (f"{first}, so the artists' original files can't download. Sign in with the link below "
                "and come back here: this clears within seconds.")
    if "unable to download" in log and "getaddrinfo" in log or "network is unreachable" in log:
        return "The last sync couldn't reach SoundCloud (no internet). It will try again tonight."
    return ""


_quality = {}  # path -> (mtime, kbps or 0 for lossless): afinfo runs once per file


def lossy_kbps(p):
    """Bitrate of a lossy file (0 when lossless or unreadable), so the page can flag anything under 320."""
    m = os.path.getmtime(p)
    if _quality.get(p, (None,))[0] != m:
        i = audio.info(p)
        _quality[p] = (m, i["kbps"] if i and not i["lossless"] else 0)
    return _quality[p][1]


def state():
    apply_sync_time()  # a time picked while a sync ran goes in once it's done
    acct = account()
    have = []
    free = {l.split("\t")[2] for l in read("free.tsv").splitlines() if l.count("\t") == 2}
    for folder, src in ((OUT, ""), (SLSK, "Soulseek")):
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                if f.lower().endswith(AUDIO):
                    p = os.path.join(folder, f)
                    name, ext = os.path.splitext(f)
                    have.append({"name": name, "kind": ext[1:].upper(), "mb": round(os.path.getsize(p) / 1e6, 1),
                                 "src": src or ("Free download" if p in free else ""), "kbps": lossy_kbps(p)})
    have.sort(key=lambda t: t["name"].lower())
    got = soulseek.got_links(DIR, SLSK)  # on the Mac from Soulseek, even mid-run: not still to get
    # What a running sync is doing: reading SoundCloud first, then Soulseek (its log is newer than the sync's flag).
    phase = sync_phase()
    running = bool(phase)
    prog = soulseek.progress(DIR, phase == "soulseek")
    buy = []
    for line in read("to-buy.tsv").splitlines():
        name, link, free = (line.split("\t") + ["", ""])[:3]
        if name and link not in got:
            st, why = prog.get(link, ("missing", ""))
            buy.append({"name": name, "link": link, "free": free, "state": st, "why": why})
    try:
        unread = int(read("unread.txt") or 0)
    except ValueError:
        unread = 0
    usb = read("usb.txt")
    history = read("history.log").splitlines()
    slsklog = read("soulseek.log").splitlines()
    usblog = read("usb.log").splitlines()
    safelog = read("safety.log").splitlines()
    qdir = os.path.join(DIR, "Quarantine")
    svc = playlists.service(read("playlist.txt"))
    try:  # Spotify shows only its first 100 tracks to a page without a Spotify sign-in
        capped = bool(svc) and json.loads(read(".service") or "{}").get("service") == svc and \
            json.loads(read(".service"))["capped"]
    except (ValueError, KeyError):
        capped = False
    watch_login(svc)
    return {
        "playlist": read("playlist.txt"), "service": svc, "capped": capped, "usb": usb, "unread": unread, "volumes": volumes(),
        "usbPlugged": bool(usb) and os.path.isdir(f"/Volumes/{usb}"),
        "usbEject": not os.path.exists(os.path.join(DIR, "usb-keep.txt")),
        "usbCopy": usb_copy(), "usbResult": usb_result(usblog),
        # new tracks passed the safety check since the last copy: they go on the next time it's plugged in
        "usbBehind": bool(usb) and newer("safety-ok.tsv", ".usb-done"),
        "running": running, "phase": phase, "syncTime": sync_time(),
        "signIn": sign_in_status(browser()),
        "profile": acct.get("profile", ""), "browser": browser(),
        "playlists": acct.get("playlists", []), "saved": saved(), "problem": problem(),
        "have": have, "buy": buy, "watching": watching(),
        "inboxWhy": {k: v.get("text", "") for k, v in freedl.load_json(DIR, freedl.WHY).items() if isinstance(v, dict)},
        "justGot": [k for k, t in _just_got.items() if time.time() - t < 600],
        "soulseekReady": soulseek_ready(), "soulseekUser": _slsk["user"],
        # the last run's sign-in was turned down (soulseek.sh logs "Soulseek PROBLEM" with the reason)
        "soulseekBad": bool(slsklog) and bool(re.search(r"PROBLEM.*(login|pass)", slsklog[-1], re.I)),
        "lastSoulseek": slsklog[-1] if slsklog else "",
        "lastRun": history[-1] if history else "", "lastUsb": usblog[-1] if usblog else "",
        # for the Get started list: the SoundCloud sign-in as last seen, the helper's switch, the virus scanner
        "scLogin": "" if svc else login_state(), "scChecking": _login["busy"], "helper": os.path.exists(HELPER),
        "virusBusy": bool(_virus["proc"]) and _virus["proc"].poll() is None,
        "virusFailed": _virus["failed"],
        "safety": {"virusScan": bool(safety.clam()), "last": safelog[-1] if safelog else "",
                   "blocked": len(os.listdir(qdir)) if os.path.isdir(qdir) else 0},
    }


HELPER = os.path.join(DIR, "Crate Helper.app")
APPS = {"chrome": "Google Chrome", "safari": "Safari", "brave": "Brave Browser", "edge": "Microsoft Edge",
        "firefox": "Firefox"}
_virus = {"proc": None, "failed": ""}  # the virus scanner install the Get started list started (clamav.sh)


def open_for_setup(what):
    """The Get started list's buttons: open the one place on this Mac each step needs. '' when done, else why not."""
    if what == "fda":  # the Full Disk Access list, and Crate Helper in Finder to drag into it
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
        if os.path.exists(HELPER):
            subprocess.run(["open", "-R", HELPER])
    elif what == "soundcloud":  # SoundCloud's sign-in page in the browser the sync reads
        _login["soon"] = time.time() + 300  # then watch for the sign-in closely (watch_login)
        app = APPS.get(browser())
        if not app or subprocess.run(["open", "-a", app, "https://soundcloud.com/signin"]).returncode:
            subprocess.run(["open", "https://soundcloud.com/signin"])
    elif what == "virus":
        if not (_virus["proc"] and _virus["proc"].poll() is None):
            _virus["failed"] = ""
            with open(os.path.join(DIR, "clamav.log"), "a") as log:
                _virus["proc"] = p = subprocess.Popen(["/bin/zsh", os.path.join(DIR, "clamav.sh")], stdout=log,
                                                      stderr=subprocess.STDOUT, start_new_session=True)

            def done():
                if p.wait():
                    lines = [l for l in read("clamav.log").splitlines() if l.strip()]
                    _virus["failed"] = lines[-1] if lines else "The virus scanner didn't install."
            threading.Thread(target=done, daemon=True).start()
    else:
        return "not found"
    return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Host") not in HOSTS:
            return self.send(403, {"error": "wrong host"})
        if self.path == "/":
            with open(os.path.join(DIR, "index.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if self.path in ("/icon.svg", "/icon.png", "/apple-touch-icon.png", "/favicon.ico"):
            svg = self.path == "/icon.svg"
            with open(os.path.join(DIR, "icon.svg" if svg else "icon.png"), "rb") as f:
                return self.send(200, f.read(), "image/svg+xml" if svg else "image/png")
        if self.path == "/api/state":
            return self.send(200, state())
        self.send(404, {"error": "not found"})

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if self.headers.get("Host") not in HOSTS or urllib.parse.urlparse(origin).netloc not in HOSTS:
            return self.send(403, {"error": "wrong origin"})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad request"})
        if self.path == "/api/playlist":
            url = str(body.get("url", "")).strip()
            if not is_playlist(url):
                return self.send(400, {"error": "That doesn't look like a SoundCloud, Apple Music or Spotify playlist link."})
            url = url.split("?")[0].rstrip("/")
            title = title_of(url)
            svc = {"spotify": "Spotify", "apple": "Apple Music"}.get(playlists.service(url))
            if not title and svc:
                return self.send(400, {"error": f"{svc} didn't open that playlist. Make sure it's public "
                                                "(Share > Copy link to playlist), then paste it again."})
            if not title:
                return self.send(400, {"error": "SoundCloud didn't open that link. For a private playlist, use its "
                                                "Share link (it ends in /s-…)."})
            remember(url, title)
        elif self.path == "/api/connect":
            m = PROFILE_RE.match(str(body.get("profile", "")).strip())
            browser = str(body.get("browser", ""))
            if not m or browser not in BROWSERS:
                return self.send(400, {"error": "Type your SoundCloud profile name, like soundcloud.com/yourname."})
            err = connect(m.group(1), browser)
            if err:
                return self.send(400, {"error": err})
        elif self.path == "/api/soulseek":
            err = soulseek_login(str(body.get("user", "")).strip(), str(body.get("pass", "")))
            if err:
                return self.send(400, {"error": err})
        elif self.path == "/api/browser":
            b = str(body.get("browser", ""))
            if b not in BROWSERS:
                return self.send(400, {"error": "Pick a browser."})
            set_browser(b)
        elif self.path == "/api/pick":
            url = str(body.get("url", ""))
            known = {p["url"]: p["title"] for p in account().get("playlists", []) + saved()}
            if url not in known:
                return self.send(400, {"error": "Pick one of your playlists."})
            remember(url, known[url])
        elif self.path == "/api/forget":
            url = str(body.get("url", ""))
            with _lists:
                save_list([p for p in saved() if p["url"] != url])
                if read("playlist.txt") == url:
                    os.remove(os.path.join(DIR, "playlist.txt"))
        elif self.path == "/api/usb":
            name = str(body.get("name", ""))
            if name and name not in volumes():
                return self.send(400, {"error": "That drive isn't plugged in."})
            with open(os.path.join(DIR, "usb.txt"), "w") as f:
                f.write(name + "\n")
            if name:
                subprocess.Popen([os.path.join(DIR, "usb.sh")], start_new_session=True)
        elif self.path == "/api/eject":
            keep = os.path.join(DIR, "usb-keep.txt")
            if body.get("on"):
                if os.path.exists(keep):
                    os.remove(keep)
            else:
                open(keep, "w").close()
        elif self.path == "/api/synctime":
            t = str(body.get("time", ""))
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
                return self.send(400, {"error": "Pick a time."})
            with open(os.path.join(DIR, "sync-time.txt"), "w") as f:
                f.write(t + "\n")
            apply_sync_time()
        elif self.path == "/api/sync":
            if not read("playlist.txt"):
                return self.send(400, {"error": "Add your playlist link first."})
            # its own session: restarting the page (an update) never stops a sync or a copy halfway
            subprocess.Popen([os.path.join(DIR, "sync.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            time.sleep(0.4)
        elif self.path == "/api/open":
            if open_for_setup(str(body.get("what", ""))):
                return self.send(404, {"error": "not found"})
        elif self.path == "/api/signin":  # the sign-in link was used, or the page is back in front
            _login["soon"] = time.time() + 300
        elif self.path == "/api/watch":
            link = str(body.get("link", ""))
            if link:
                if not any(l.split("\t")[1:2] == [link] for l in read("to-buy.tsv").splitlines()):
                    return self.send(400, {"error": "That track isn't on the list."})
                freedl.claim(DIR, link)
            _watch.set()
        elif self.path == "/api/copy":
            usb = read("usb.txt")
            if not usb or not os.path.isdir(f"/Volumes/{usb}"):
                return self.send(400, {"error": f"Plug in {usb or 'your USB'} first."})
            if not usb_copy():  # one already running: the page just shows it
                subprocess.Popen([os.path.join(DIR, "usb.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                for _ in range(10):  # until it says it has started, so the page shows it straight away
                    time.sleep(0.1)
                    if usb_copy():
                        break
        else:
            return self.send(404, {"error": "not found"})
        self.send(200, state())


_watch = threading.Event()  # set by a Free Download click or the page coming back into view: look now
_just_got = {}  # name: when, for tracks just picked up from Downloads (the page's "Got it")


def watching():
    """The still-to-get tracks whose Free Download was clicked in the last few minutes."""
    return list(freedl.claims(DIR))


def newer(a, b):
    """True when file a changed after file b (or b doesn't exist yet)."""
    try:
        return os.path.getmtime(os.path.join(DIR, a)) > os.path.getmtime(os.path.join(DIR, b))
    except FileNotFoundError:
        return os.path.exists(os.path.join(DIR, a))


def usb_follow():
    """While a sync runs and the USB is plugged in, tracks that passed the safety check since the last copy go on it
    as they arrive (usb.sh doesn't eject mid-sync; the sync's own last copy does, or this once the sync is over)."""
    usb = read("usb.txt")
    if not usb or not os.path.isdir(f"/Volumes/{usb}") or usb_copy():
        return
    if sync_running():
        if not newer("safety-ok.tsv", ".usb-done"):
            return
        env = None
    elif (usb_result(read("usb.log").splitlines()) or {}).get("mid"):
        env = {**os.environ, "CRATE_FINAL": "1"}  # the sync ended without its last copy (stopped, or an older sync.sh)
    else:
        return
    subprocess.Popen([os.path.join(DIR, "usb.sh")], start_new_session=True, env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def watch_downloads():
    """Still-to-get tracks bought or unlocked by hand land in Downloads; take them (freedl.inbox), then copy
    anything new to the USB when it's plugged in. Every minute, or every 3 s for 15 min after a Free Download
    click. Not while a sync reads SoundCloud (it rewrites the list then); its Soulseek step is fine."""
    while True:
        _watch.wait(3 if freedl.claims(DIR) else 30 if sync_running() else 60)
        _watch.clear()
        reload_jobs()
        usb_follow()
        if sync_phase() == "soundcloud":
            continue
        try:
            got = freedl.inbox(DIR, OUT)
        except Exception as e:  # never stop the page; the error goes to free.log
            got = []
            with open(os.path.join(DIR, "free.log"), "a") as f:
                f.write(f"{time.strftime('%F %R')}  Downloads pickup FAILED: {e!r}\n")
        if got:
            now = time.time()
            for k in [k for k, t in _just_got.items() if now - t > 600]:
                del _just_got[k]
            _just_got.update({os.path.splitext(os.path.basename(g[2]))[0]: now for g in got})
            with open(os.path.join(DIR, "free.log"), "a") as f:
                f.writelines(f"{time.strftime('%F %R')}  from Downloads: {os.path.basename(g[2])}\n" for g in got)
            subprocess.Popen([os.path.join(DIR, "usb.sh")], start_new_session=True,  # a page restart never stops it
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    threading.Thread(target=watch_downloads, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
