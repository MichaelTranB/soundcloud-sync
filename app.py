#!/usr/bin/env python3
"""The Crate: a small local page for the SoundCloud sync. Standard library only.

Listens on 127.0.0.1 only. Every write checks the Host and Origin headers, so another website open
in the browser cannot press the buttons.
"""
import json, os, re, shutil, subprocess, sys, threading, time, urllib.parse
import audio, freedl, playlists, safety, soulseek
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser("~/Music/SoundCloud Sync")
SLSK = os.path.join(OUT, "From Soulseek")  # soulseek.sh's downloads
PORT = 4780
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


def browser():
    """The browser whose SoundCloud sign-in the sync borrows: Chrome until he picks another; "none" = no sign-in."""
    b = read("browser.txt", None)
    return "chrome" if b is None else (b or "none")


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


_login = {"at": 0.0, "state": "", "profile": "", "busy": False}  # the page's own re-check (sign_in_check)


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


def ask_soundcloud(arg, url):
    """(state, profile folder) from one track looked up with that sign-in; state '' when SoundCloud didn't answer."""
    try:
        r = subprocess.run([YTDLP, "-v", "--cookies-from-browser", arg, "--simulate", "--no-playlist",
                            "--ignore-no-formats-error", "--extractor-args", "soundcloud:formats=none", url],
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
        url = read(".playlist").split("\n")[0].split(" ")[1]
        arg = cookie_arg(b)
        state, folder = ask_soundcloud(arg, url)
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
                s2, f2 = ask_soundcloud(f"{b}:{d}", url)
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


def profile_name(b, folder):
    """The name the browser shows for that profile folder, when it has more than one profile; else ''."""
    try:
        with open(os.path.join(os.path.dirname(folder), "Local State")) as f:
            cache = json.load(f)["profile"]["info_cache"]
        return cache[os.path.basename(folder)]["name"] if len(cache) > 1 else ""
    except (OSError, ValueError, KeyError, TypeError):
        return ""


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
    try:
        ran = os.path.getmtime(os.path.join(DIR, "last-run.log"))
    except OSError:
        ran = 0.0
    state = _login["state"] if _login["at"] > ran and _login["state"] else login_seen(log)
    if name and state in ("none", "invalid"):
        # Re-check every 2 minutes while the page is open, so the line goes away soon after he signs in.
        # Not while the sync itself is asking SoundCloud (the Soulseek part doesn't touch it).
        if not _login["busy"] and time.time() - _login["at"] > 120 and sync_phase() != "soundcloud":
            _login["busy"] = True
            threading.Thread(target=sign_in_check, args=(b,), daemon=True).start()
        where = f"{name} (profile \"{_login['profile']}\")" if _login["profile"] else name
        first = ("SoundCloud's sign-in in {w} has run out" if state == "invalid"
                 else "You're not signed in to SoundCloud in {w}").format(w=where)
        return (f"{first}, so the artists' original files can't download. Sign in at soundcloud.com in {where}; "
                "this line goes away within 2 minutes, then press Sync now.")
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
    return {
        "playlist": read("playlist.txt"), "service": svc, "capped": capped, "usb": usb, "unread": unread, "volumes": volumes(),
        "usbPlugged": bool(usb) and os.path.isdir(f"/Volumes/{usb}"),
        "usbEject": not os.path.exists(os.path.join(DIR, "usb-keep.txt")),
        "running": running, "phase": phase,
        "signIn": sign_in_status(browser()),
        "profile": acct.get("profile", ""), "browser": browser(),
        "playlists": acct.get("playlists", []), "saved": saved(), "problem": problem(),
        "have": have, "buy": buy,
        "soulseekReady": soulseek_ready(), "soulseekUser": _slsk["user"],
        # the last run's sign-in was turned down (soulseek.sh logs "Soulseek PROBLEM" with the reason)
        "soulseekBad": bool(slsklog) and bool(re.search(r"PROBLEM.*(login|pass)", slsklog[-1], re.I)),
        "lastSoulseek": slsklog[-1] if slsklog else "",
        "lastRun": history[-1] if history else "", "lastUsb": usblog[-1] if usblog else "",
        "safety": {"virusScan": bool(safety.CLAM), "last": safelog[-1] if safelog else "",
                   "blocked": len(os.listdir(qdir)) if os.path.isdir(qdir) else 0},
    }


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
        elif self.path == "/api/sync":
            if not read("playlist.txt"):
                return self.send(400, {"error": "Add your playlist link first."})
            # its own session: restarting the page (an update) never stops a sync or a copy halfway
            subprocess.Popen([os.path.join(DIR, "sync.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            time.sleep(0.4)
        elif self.path == "/api/copy":
            subprocess.Popen([os.path.join(DIR, "usb.sh")])
            time.sleep(0.4)
        else:
            return self.send(404, {"error": "not found"})
        self.send(200, state())


def watch_downloads():
    """Every minute: still-to-get tracks bought or unlocked by hand land in Downloads; take them (freedl.inbox),
    then copy anything new to the USB when it's plugged in."""
    while True:
        time.sleep(60)
        if sync_running():
            continue  # a sync is running; it does the same at its end
        try:
            got = freedl.inbox(DIR, OUT)
        except Exception as e:  # never stop the page; the error goes to free.log
            got = []
            with open(os.path.join(DIR, "free.log"), "a") as f:
                f.write(f"{time.strftime('%F %R')}  Downloads pickup FAILED: {e!r}\n")
        if got:
            with open(os.path.join(DIR, "free.log"), "a") as f:
                f.writelines(f"{time.strftime('%F %R')}  from Downloads: {os.path.basename(g[2])}\n" for g in got)
            subprocess.Popen([os.path.join(DIR, "usb.sh")])


if __name__ == "__main__":
    threading.Thread(target=watch_downloads, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
