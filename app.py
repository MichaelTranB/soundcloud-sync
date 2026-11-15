#!/usr/bin/env python3
"""The Crate: a small local page for the SoundCloud sync. Standard library only.

Listens on 127.0.0.1 only. Every write checks the Host and Origin headers, so another website open
in the browser cannot press the buttons.
"""
import json, os, re, shutil, subprocess, time, urllib.parse
import audio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser("~/Music/SoundCloud Sync")
SLSK = os.path.join(OUT, "From Soulseek")  # soulseek.sh's downloads
PORT = 4780
HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus")
PLAYLIST_RE = re.compile(r"^https://(on\.|m\.|www\.)?soundcloud\.com/\S+$")
PROFILE_RE = re.compile(r"^(?:https?://(?:www\.|m\.)?soundcloud\.com/)?([A-Za-z0-9_-]{1,60})/?$")
# "none" lists public playlists only; the others borrow the SoundCloud session of that browser.
BROWSERS = ("chrome", "safari", "brave", "firefox", "edge", "none")
YTDLP = shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
_signed = {"at": 0.0, "ok": False}
_slsk = {"at": 0.0, "ok": False}


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


def signed_in():
    # The Keychain read is slow-ish; once a minute is plenty.
    if time.time() - _signed["at"] > 60:
        try:
            r = subprocess.run([os.path.expanduser("~/work-os/bin/api-key"), "get", "soundcloud"],
                               capture_output=True, text=True, timeout=10)
            _signed["ok"] = r.returncode == 0 and bool(r.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            _signed["ok"] = False
        _signed["at"] = time.time()
    return _signed["ok"]


def soulseek_ready():
    """True once soulseek-login.sh saved a Soulseek sign-in (reads only the item's name, never the password)."""
    if time.time() - _slsk["at"] > 60:
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", "soundcloud-sync-soulseek"],
                               capture_output=True, text=True, timeout=10)
            _slsk["ok"] = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _slsk["ok"] = False
        _slsk["at"] = time.time()
    return _slsk["ok"]


def account():
    try:
        return json.loads(read("account.json") or "{}")
    except ValueError:
        return {}


def connect(profile, browser):
    """Lists the profile's playlists, signed in through the chosen browser. Returns an error or None."""
    cmd = [YTDLP, "--flat-playlist", "--dump-single-json", f"https://soundcloud.com/{profile}/sets"]
    if browser != "none":
        cmd[1:1] = ["--cookies-from-browser", browser]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "SoundCloud took too long to answer. Try again."
    try:
        entries = json.loads(r.stdout).get("entries") or []
    except ValueError:
        err = [l for l in r.stderr.splitlines() if l.startswith("ERROR")]
        return (err[-1][7:] if err else "Could not read that profile.")[:300]
    lists = [{"title": e.get("title") or e["url"].rstrip("/").split("/")[-1], "url": e["url"]}
             for e in entries if PLAYLIST_RE.match(str(e.get("url", "")))]
    lists.append({"title": "Liked tracks", "url": f"https://soundcloud.com/{profile}/likes"})
    with open(os.path.join(DIR, "account.json"), "w") as f:
        json.dump({"profile": profile, "browser": browser, "playlists": lists}, f)
    # sync.sh reads this one line to know which browser session to borrow.
    with open(os.path.join(DIR, "browser.txt"), "w") as f:
        f.write("" if browser == "none" else browser + "\n")
    return None


def problem():
    """One plain line when the last sync could not sign in or reach SoundCloud; empty when fine."""
    log = read("last-run.log").lower()
    if "cookies" in log and "error" in log or "only available for registered users" in log or "401" in log:
        return "SoundCloud sign-in isn't working. Sign in to SoundCloud in your browser, then press Connect again."
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
    slsk_links = {l.split("\t")[0] for l in read("soulseek.tsv").splitlines() if l}
    buy = []
    for line in read("to-buy.tsv").splitlines():
        name, link, free = (line.split("\t") + ["", ""])[:3]
        if name:
            buy.append({"name": name, "link": link, "free": free, "soulseek": link in slsk_links})
    usb = read("usb.txt")
    history = read("history.log").splitlines()
    slsklog = read("soulseek.log").splitlines()
    usblog = read("usb.log").splitlines()
    return {
        "playlist": read("playlist.txt"), "usb": usb, "volumes": volumes(),
        "usbPlugged": bool(usb) and os.path.isdir(f"/Volumes/{usb}"),
        "running": os.path.exists(os.path.join(DIR, ".running")),
        "signedIn": bool(read("browser.txt")) or signed_in(),
        "profile": acct.get("profile", ""), "browser": acct.get("browser", "chrome"),
        "playlists": acct.get("playlists", []), "problem": problem(),
        "have": have, "buy": buy,
        "soulseekReady": soulseek_ready(), "lastSoulseek": slsklog[-1] if slsklog else "",
        "lastRun": history[-1] if history else "", "lastUsb": usblog[-1] if usblog else "",
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
            if not PLAYLIST_RE.match(url):
                return self.send(400, {"error": "That doesn't look like a SoundCloud link."})
            with open(os.path.join(DIR, "playlist.txt"), "w") as f:
                f.write(url + "\n")
        elif self.path == "/api/connect":
            m = PROFILE_RE.match(str(body.get("profile", "")).strip())
            browser = str(body.get("browser", ""))
            if not m or browser not in BROWSERS:
                return self.send(400, {"error": "Type your SoundCloud profile name, like soundcloud.com/yourname."})
            err = connect(m.group(1), browser)
            if err:
                return self.send(400, {"error": err})
        elif self.path == "/api/pick":
            url = str(body.get("url", ""))
            if url not in [p["url"] for p in account().get("playlists", [])]:
                return self.send(400, {"error": "Pick one of your playlists."})
            with open(os.path.join(DIR, "playlist.txt"), "w") as f:
                f.write(url + "\n")
        elif self.path == "/api/usb":
            name = str(body.get("name", ""))
            if name and name not in volumes():
                return self.send(400, {"error": "That drive isn't plugged in."})
            with open(os.path.join(DIR, "usb.txt"), "w") as f:
                f.write(name + "\n")
            if name:
                subprocess.Popen([os.path.join(DIR, "usb.sh")])
        elif self.path == "/api/sync":
            if not read("playlist.txt"):
                return self.send(400, {"error": "Add your playlist link first."})
            subprocess.Popen([os.path.join(DIR, "sync.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.4)
        elif self.path == "/api/copy":
            subprocess.Popen([os.path.join(DIR, "usb.sh")])
            time.sleep(0.4)
        else:
            return self.send(404, {"error": "not found"})
        self.send(200, state())


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
