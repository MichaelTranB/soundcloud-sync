#!/usr/bin/env python3
"""The Crate: a small local page for the SoundCloud sync. Standard library only.

Listens on 127.0.0.1 only. Every write checks the Host and Origin headers, so another website open
in the browser cannot press the buttons.
"""
import json, os, re, subprocess, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser("~/Music/SoundCloud Sync")
PORT = 4780
HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
AUDIO = (".wav", ".flac", ".aif", ".aiff", ".mp3", ".m4a", ".ogg", ".opus")
PLAYLIST_RE = re.compile(r"^https://(on\.|m\.|www\.)?soundcloud\.com/\S+$")
_signed = {"at": 0.0, "ok": False}


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


def state():
    have = []
    if os.path.isdir(OUT):
        for f in sorted(os.listdir(OUT), key=str.lower):
            if f.lower().endswith(AUDIO):
                p = os.path.join(OUT, f)
                name, ext = os.path.splitext(f)
                have.append({"name": name, "kind": ext[1:].upper(), "mb": round(os.path.getsize(p) / 1e6, 1)})
    buy = []
    for line in read("to-buy.tsv").splitlines():
        name, _, link = line.partition("\t")
        if name:
            buy.append({"name": name, "link": link})
    usb = read("usb.txt")
    history = read("history.log").splitlines()
    usblog = read("usb.log").splitlines()
    return {
        "playlist": read("playlist.txt"), "usb": usb, "volumes": volumes(),
        "usbPlugged": bool(usb) and os.path.isdir(f"/Volumes/{usb}"),
        "running": os.path.exists(os.path.join(DIR, ".running")), "signedIn": signed_in(),
        "have": have, "buy": buy,
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
