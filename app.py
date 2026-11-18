#!/usr/bin/env python3
"""The Crate: a small local page for the SoundCloud sync. Standard library only.

Listens on 127.0.0.1 only. Every write checks the Host and Origin headers, so another website open
in the browser cannot press the buttons.
"""
import glob, json, os, plistlib, re, shlex, shutil, subprocess, sys, threading, time, unicodedata, urllib.parse
import audio, freedl, links, playlists, safety, soulseek
import aiff, club, details, dj, friend, genres, layout, liked, recognise, scplaylists, usb_ask, waveform
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.expanduser("~/Music/SoundCloud Sync")
SLSK = OUT  # soulseek.sh's downloads land in the music folder, with everything else
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


def agent_app(who):
    """Claude Code (its claude command) or the Codex app, when this Mac has one: the Free links button hands it the
    list. The Crate works the same without them."""
    if who == "claude":
        places = (shutil.which("claude"), "~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude",
                  "/usr/local/bin/claude")
        return next((p for p in map(lambda x: x and os.path.expanduser(x), places) if p and os.access(p, os.X_OK)), "")
    if who == "codex":  # the Codex app, or the ChatGPT app for Mac, which is now the same app (it includes Codex)
        import plistlib
        for p in ("/Applications/Codex.app", "~/Applications/Codex.app", "/Applications/ChatGPT.app",
                  "~/Applications/ChatGPT.app"):
            p = os.path.expanduser(p)
            try:
                with open(os.path.join(p, "Contents/Info.plist"), "rb") as f:
                    if plistlib.load(f).get("CFBundleIdentifier") == "com.openai.codex":
                        return p
            except (OSError, ValueError):
                pass
    return ""


CHROME = "Google Chrome"
EXT = {"claude": "fcoeoabgfenejglbffodgkkbkcdhcgfn", "codex": "hehggadaopoacecdllhhajmbjkdcmajg"}  # their Chrome add-ons


def chrome_app():
    return next((p for p in (f"/Applications/{CHROME}.app", os.path.expanduser(f"~/Applications/{CHROME}.app"))
                 if os.path.isdir(p)), "")


def open_chrome(page="/free"):
    """Opens Chrome on The Crate's list (free links, or songs for SoundCloud playlists) before the assistant starts,
    so its Chrome add-on is already connected when it looks (a just-started Chrome takes a few seconds). True when
    Chrome had to be started."""
    cold = subprocess.run(["pgrep", "-xq", CHROME]).returncode != 0
    subprocess.run(["open", "-a", CHROME, f"http://localhost:{PORT}{page}"], check=False)
    return cold


def agent_uses():
    """Which assistant this person already uses, from what's on the Mac (an app or command is there; nothing in it is
    read): picks the one the Claude/Codex guide opens on when neither is set up yet."""
    there = lambda *ps: any(os.path.exists(os.path.expanduser(p)) for p in ps)
    return {"claude": bool(agent_app("claude")) or there("/Applications/Claude.app", "~/Applications/Claude.app"),
            "codex": bool(agent_app("codex")) or bool(shutil.which("codex")) or there(
                "/Applications/ChatGPT.app", "~/Applications/ChatGPT.app", "/opt/homebrew/bin/codex",
                "/usr/local/bin/codex", "~/.local/bin/codex")}


def in_chrome(who):
    """That assistant's Chrome add-on is in one of this Mac's Chrome profiles (its folder is there; nothing in it is
    read)."""
    import glob
    return bool(glob.glob(os.path.expanduser(f"~/Library/Application Support/Google/Chrome/*/Extensions/{EXT[who]}")))


def in_terminal(name, script):
    """Runs a short script in a Terminal window the friend can watch and answer in."""
    run = os.path.join(DIR, name)
    with open(run, "w") as f:
        f.write("#!/bin/zsh\n" + script)
    os.chmod(run, 0o700)
    subprocess.Popen(["open", "-a", "Terminal", run])


# What Claude or Codex is asked to do: the friend's own assistant, in their own signed-in Chrome, with them watching.
# It asks them once what it may do in their name, never pays or types a password, and only fetches audio.
AGENT_BRIEF = """{lead}Please get the free downloads waiting in my music app, The Crate, using my Chrome (I'm signed in there).

Open this page in Chrome (The Crate has just opened it there): {page}
It lists {n} songs whose artists give them away free, usually behind a gate (Hypeddit, ToneDen, Laylo...) that asks
for a follow, like, repost, comment or email first. The Crate picks up each file that lands in my Downloads folder.

Before you start, ask me ONCE which gate steps you may do in my name, so you don't have to ask again for each:
following or liking on SoundCloud (or Spotify, Instagram...), reposting, a comment (and what text), signing up with
my email (which one), connecting an account. Skip any song that needs something I didn't allow.

Then for each song on that page, top to bottom:
1. Click its Free Download link ON THAT PAGE: the click tells The Crate which song is coming, so no renaming is
   needed. (Don't type the link's address yourself.)
2. Do the gate steps I allowed and download the best quality offered: WAV, FLAC or AIFF over MP3; MP3 only at
   320 kbps.
3. Once the file has started downloading, close every tab that song opened (the gate page, SoundCloud, the
   download page): keep only the list page open, so a long list doesn't fill Chrome and slow the Mac. Then go back
   to the list page and wait a few seconds before the next song, so none of my accounts looks like a bot.
If a song isn't free after all (it costs money, it's for paying Patreon members only, or the link is dead), or you
skip it, don't buy anything: under that song on the list page open "Can't get it free?", pick what it is, write
the price or the reason in a few words (like "$1.50 or more on Bandcamp" or "$5/month Patreon tier"), and press
Save. The Crate shows that beside the song (paid, members-only and dead links leave the list).
Reload the list page whenever you like: songs that have arrived drop off it. If a song you downloaded stays on the
list with a "Use this file" button, The Crate turned the file away (usually its length differs from SoundCloud's):
if it's the song you downloaded for that row, click the button. At the end, close every tab you opened.

Keep going until every song is done or skipped: don't stop in the middle to wait for me. If a song needs me (a
sign-in, a code sent to my phone, a "prove you're human" check), leave its tab open, tell me in one line which tab
and what to do there, and carry on with the next song. Every few songs, look at those tabs again: once I've done my
part, finish that song. When only those are left, keep checking them now and then for up to 30 minutes before you
give me your final list.

Never: pay or enter card details, type a password or a sign-in code (that's mine to do, as above), download
or open an app or installer (.dmg, .pkg, .exe, .app), or join a paid membership (skip a Patreon post that's members
only). Don't touch anything else in The Crate. If you can't reach my Chrome yet, it may still be starting: wait 15 seconds
and try again, up to 4 times, before you tell me and stop. Use my own Google Chrome, not a built-in browser.

At the end, tell me in a short list what you got, and what you skipped and why.
"""


def free_rows(every=False):
    """The songs still to get that have the artist's own free link: (name, track link, free link). Not the ones
    found paid, for paying members only or gone (links.py), unless every."""
    ls = links.load(DIR)
    return [p[:3] for p in (l.split("\t") for l in read("to-buy.tsv").splitlines())
            if len(p) > 2 and re.match(r"https?://\S+$", p[2]) and (every or links.status(ls, p[1], p[2])["kind"] not in links.NOT_FREE)]


_checking = threading.Lock()


def check_links():
    """Reads what each free link needs (price, gone...) in the background, once a day per link."""
    if _checking.acquire(blocking=False):
        def run():
            try:
                links.refresh(DIR, [(t, f) for _, t, f in free_rows(every=True)])
            except Exception as e:
                print("link check:", e, file=sys.stderr)
            finally:
                _checking.release()
        threading.Thread(target=run, daemon=True).start()


def helper_name():
    try:
        return (json.loads(read(".agent-run.json") or "{}") or {}).get("who") or "helper"
    except ValueError:
        return "helper"


def helper_run():
    """While Claude or Codex works through the free links: who, how many it started with, how many are done, and the
    song it's on (its last click on its list page, in the last 10 minutes). None when it isn't working."""
    try:
        run = json.loads(read(".agent-run.json") or "null") or {}
        cur = json.loads(read(".agent-current.json") or "null") or {}
    except ValueError:
        return None
    now = time.time()
    if not run or now - run.get("at", 0) > 3 * 3600 or run.get("job") == "scpl":
        return None
    live = run.get("who") == "claude" and subprocess.run(["pgrep", "-fq", "agent-settings.json"]).returncode == 0
    recent = now - max(run.get("at", 0), cur.get("at", 0)) < 15 * 60
    if not (live or recent):
        return None
    left = {p[1] for p in (l.split("\t") for l in read("to-buy.tsv").splitlines()) if len(p) > 1}
    left -= soulseek.got_links(DIR, SLSK)
    return {"who": run.get("who", ""), "n": run.get("n", 0), "done": sum(t not in left for t in run.get("links", [])),
            "on": cur.get("link", "") if now - cur.get("at", 0) < 10 * 60 else ""}


def agent_task(who="claude"):
    n = len(free_rows())
    lead = "@Chrome " if who == "codex" else ""
    return AGENT_BRIEF.format(lead=lead, page=f"http://localhost:{PORT}/free", n=n), n


def free_page():
    """The list Claude or Codex works from: each song's Free Download link and nothing else of The Crate. A click
    here tells The Crate which song is coming (as in the app), so the downloaded file needs no renaming."""
    from html import escape
    rows = free_rows()
    why = {k: v for k, v in freedl.load_json(DIR, freedl.WHY).items()
           if isinstance(v, dict) and v.get("file") and os.path.exists(v["file"])}
    form = lambda t: (f'<details><summary>Can\'t get it free?</summary><form data-needs="{escape(t)}">'
                      '<select name="kind"><option value="paid">Paid</option><option value="members">Paying members only'
                      '</option><option value="gone">Link gone</option><option value="skipped">Skipped</option></select>'
                      '<input name="note" maxlength="140" placeholder="The price, or why (e.g. $5/month Patreon tier)">'
                      '<button>Save</button></form></details>')
    items = "".join(f'<li><span>{escape(n)}</span> <a href="{escape(f)}" target="_blank" rel="noopener" '
                    f'data-link="{escape(t)}">Free Download</a>'
                    + (f'<br><small>{escape(why[t]["text"])}</small> <button data-take="{escape(t)}">Use this file'
                       '</button>' if t in why else "") + form(t) + '</li>' for n, t, f in rows)
    return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Crate: free downloads</title>
<style>body{{font:16px/1.5 -apple-system,system-ui,sans-serif;background:#0c0c12;color:#f0eef8;max-width:760px;margin:32px auto;padding:0 16px}}
p{{color:#a4a2b6}} li{{margin:10px 0}} a{{color:#ff6b7d;font-weight:600;margin-left:8px}}
small{{color:#f0a868}} summary{{color:#a4a2b6;font-size:14px;cursor:pointer}}
form{{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}} select,input{{font:inherit;font-size:14px;padding:3px 8px;border-radius:8px;border:1px solid #3a3a48;background:#16161e;color:#f0eef8}} input{{flex:1;min-width:220px}}
button{{font:inherit;font-size:14px;margin-left:8px;padding:2px 10px;border-radius:8px;border:1px solid #ff6b7d;background:none;color:#ff6b7d;cursor:pointer}}</style>
<h1>Free downloads: {len(rows)} left</h1>
<p>Click each song's Free Download link here, one at a time: the click tells The Crate which song is coming.
Songs that have arrived drop off this list when the page is reloaded.</p>
<ol>{items}</ol>
<script>const post = (u, b) => fetch(u, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(b) }});
for (const a of document.querySelectorAll('a[data-link]')) a.addEventListener('click', () => post('/api/watch', {{ link: a.dataset.link, from: 'helper' }}));
for (const f of document.querySelectorAll('form[data-needs]')) f.addEventListener('submit', async e => {{
  e.preventDefault(); const r = await post('/api/needs', {{ link: f.dataset.needs, kind: f.kind.value, note: f.note.value, from: 'helper' }});
  if (r.ok) location.reload(); else alert((await r.json()).error); }});
for (const b of document.querySelectorAll('button[data-take]')) b.addEventListener('click', async () => {{
  b.disabled = true; const r = await post('/api/take', {{ link: b.dataset.take }});
  if (r.ok) location.reload(); else {{ b.disabled = false; alert((await r.json()).error); }} }});</script>
"""


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
                        ". Still syncing: new tracks go on as they arrive" + \
                        (", then it's ejected. Keep it plugged in." if os.path.exists(os.path.join(DIR, "usb-eject.txt")) else ".")
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


AGAIN = os.path.join(DIR, soulseek.AGAIN)
_again = {"on": False, "lock": threading.Lock()}


def search_again(new=True):
    """A file was just thrown back: Soulseek is asked for another copy right away (soulseek-now.sh), not at the next
    sync. The note (.soulseek-again) is the queue: while a sync or an earlier search is still going, it waits, and
    the search starts the moment that one is done, so files can be thrown back one after another."""
    if new:
        if not soulseek_ready():
            return  # no Soulseek sign-in yet: the first sync after it looks
        open(AGAIN, "w").close()
    with _again["lock"]:
        if _again["on"]:
            return
        _again["on"] = True

    def go():
        tries = 0
        try:
            while os.path.exists(AGAIN):
                if not sync_running():
                    if tries == 3:  # never a loop that starts it for ever: the next sync looks instead
                        os.remove(AGAIN)
                        with open(os.path.join(DIR, "soulseek.log"), "a") as f:
                            f.write(time.strftime("%F %R") + "  Soulseek PROBLEM: the search for another copy "
                                    "couldn't start; the next sync looks for it\n")
                        break
                    tries += 1
                    subprocess.Popen([os.path.join(DIR, "soulseek-now.sh")], start_new_session=True,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    tries = 0  # it started (or a sync is on): the note left now is a newer one
                time.sleep(4)
        except OSError:
            pass
        finally:
            _again["on"] = False
    threading.Thread(target=go, daemon=True).start()


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


_quality = {}  # path -> (mtime, kbps or 0 for lossless, length in seconds): afinfo runs once per file


def _afinfo(p):
    m = os.path.getmtime(p)
    if _quality.get(p, (None,))[0] != m:
        i = audio.info(p)
        _quality[p] = (m, i["kbps"] if i and not i["lossless"] else 0, round(i["secs"]) if i else 0)
    return _quality[p]


def lossy_kbps(p):
    """Bitrate of a lossy file (0 when lossless or unreadable), so the page can flag anything under 320."""
    return _afinfo(p)[1]


_names = [None, {}, {}]  # .listing's mtime, then "uploader - title" (folded) -> link, and link -> (name, seconds)


def song_of():
    """Which playlist song each file is, so the page can show the playlist's name beside the file's: Soulseek and
    free-link files by their record (soulseek.tsv, free.tsv), the artist's own uploads by their name."""
    try:
        m = os.path.getmtime(os.path.join(DIR, ".listing"))
    except OSError:
        m = 0
    if _names[0] != m:
        by_name, by_link = {}, {}
        for line in read(".listing").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("webpage_url"):
                name = f"{r.get('uploader')} - {r.get('title')}"
                by_name[soulseek.norm(name)] = r["webpage_url"]
                by_link[r["webpage_url"]] = (name, round(r.get("duration") or 0))
        _names[:] = [m, by_name, by_link]
    by_path = {}
    for name in ("soulseek.tsv", "free.tsv"):
        for link, title, p in soulseek.rows_of(DIR, name, 3):
            by_path[p] = (link, title)
    return _names[1], _names[2], by_path


def state():
    apply_sync_time()  # a time picked while a sync ran goes in once it's done
    acct = account()
    have = []
    free = {l.split("\t")[2] for l in read("free.tsv").splitlines() if l.count("\t") == 2}
    wrong = soulseek.suspects(DIR)  # Soulseek files that don't look like their playlist song, and why
    slsk = soulseek.ours(DIR, SLSK)
    by_name, by_link, by_path = song_of()
    came, spot = soulseek.load_from(DIR), {}
    # (The folder Soulseek files had to themselves is still listed until the next sync moves them in with the rest.)
    folders = [(OUT, ""), (os.path.join(OUT, soulseek.OLD), soulseek.OLD)]
    # Liked Songs' own folder, and any folder they went to before the user renamed it
    for sub in sorted({os.path.relpath(os.path.dirname(g[2]), OUT) for g in soulseek.load_got(DIR)} | {liked.folder(DIR)}):
        if sub and sub not in (".", soulseek.OLD) and not sub.startswith(".."):
            folders.append((os.path.join(OUT, sub), sub))
    for folder, old in folders:
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                if f.lower().endswith(AUDIO):
                    p = os.path.join(folder, f)
                    name, ext = os.path.splitext(f)
                    try:
                        mb = round(os.path.getsize(p) / 1e6, 1)
                        _, kbps, secs = _afinfo(p)
                    except OSError:  # thrown back this instant
                        continue
                    # The song it should be: its playlist name, link and length, to set beside the file's own.
                    link, title = by_path.get(p) or (by_name.get(soulseek.norm(name)), None)
                    want = by_link.get(link, (None, 0))[1]
                    if link and "open.spotify.com/track/" in link:
                        spot = spot or liked._load(DIR, ".spotify-cache.json", {})
                        want = round((spot.get(link.rsplit("/", 1)[1]) or {}).get("secs") or 0)
                    peer = (came.get(p) or ("", ""))[1]
                    have.append({"name": name, "kind": ext[1:].upper(), "mb": mb, "kbps": kbps,
                                 "src": "Soulseek" if old == soulseek.OLD or p in slsk else "Free download" if p in free else "",
                                 "file": os.path.join(old, f), "wrong": wrong.get(p, ""),
                                 "song": title or by_link.get(link, (None,))[0] or "", "link": link or "",
                                 "secs": secs, "want": want, "came": re.split(r"[\\/]", peer)[-1] if peer else "",
                                 "liked": bool(old) and old != soulseek.OLD})
    have.sort(key=lambda t: t["name"].lower())
    got = soulseek.got_links(DIR, SLSK)  # on the Mac from Soulseek, even mid-run: not still to get
    # What a running sync is doing: reading SoundCloud first, then Soulseek (its log is newer than the sync's flag).
    phase = sync_phase()
    running = bool(phase)
    prog = soulseek.progress(DIR, phase == "soulseek")
    buy, ls = [], links.load(DIR)
    for line in read("to-buy.tsv").splitlines():
        name, link, free = (line.split("\t") + ["", ""])[:3]
        if name and link not in got:
            st, why = prog.get(link, ("missing", ""))
            buy.append({"name": name, "link": link, "free": free, "state": st, "why": why,
                        **({"needs": links.status(ls, link, free)} if re.match(r"https?://", free) else {})})
    if any("needs" in t for t in buy):
        check_links()
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
    try:  # Spotify's page shows its first 100 songs, Apple's its first 300
        info = json.loads(read(".service") or "{}")
        info = info if svc and info.get("service") == svc else {}
    except ValueError:
        info = {}
    capped = bool(info.get("capped"))
    pasted = len(playlists.pasted(DIR, read("playlist.txt").strip())) if svc == "spotify" else 0
    try:  # how far a long playlist read has got, while a sync runs
        reading = json.loads(read(".reading.json") or "null") if sync_running() else None
    except ValueError:
        reading = None
    watch_login(svc)
    return {
        "liked": liked.status(DIR), "likedOpts": liked.settings(DIR),
        "playlist": read("playlist.txt"), "service": svc, "capped": capped, "pasted": pasted,
        "missing": info.get("missing", 0), "reading": reading, "usb": usb, "unread": unread, "volumes": volumes(),
        "usbPlugged": bool(usb) and os.path.isdir(os.path.join(os.environ.get("VOLUMES") or "/Volumes", usb)),
        "usbEject": os.path.exists(os.path.join(DIR, "usb-eject.txt")),  # off unless ticked
        "usbAsk": usb_asking(),
        "usbCopy": usb_copy(), "usbResult": usb_result(usblog),
        # new tracks passed the safety check since the last copy: they go on the next time it's plugged in
        "usbBehind": bool(usb) and newer("safety-ok.tsv", ".usb-done"),
        "running": running, "phase": phase, "syncTime": sync_time(),
        "signIn": sign_in_status(browser()),
        "profile": acct.get("profile", ""), "browser": browser(),
        "playlists": acct.get("playlists", []), "saved": saved(), "problem": problem(),
        "have": have, "buy": buy, "watching": watching(), "helperRun": helper_run(), "scpl": scplaylists.counts(DIR),
        "agents": [w for w in ("claude", "codex") if agent_app(w)], "claudeInChrome": in_chrome("claude"), "codexInChrome": in_chrome("codex"), "chrome": bool(chrome_app()), "agentUses": agent_uses(),
        "inboxWhy": {k: v.get("text", "") for k, v in freedl.load_json(DIR, freedl.WHY).items() if isinstance(v, dict)},
        "inboxFile": {k: os.path.basename(v["file"]) for k, v in freedl.load_json(DIR, freedl.WHY).items()
                      if isinstance(v, dict) and v.get("file") and os.path.exists(v["file"])},
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


_dj = {"timer": None}  # the wait after a genre edit before the decks' libraries are written (several edits, one write)


def dj_run(wait=0):
    """Brings the decks' libraries in step (dj.py), now or after a quiet moment. On its own, so a page restart
    never stops it halfway."""
    def go():
        _dj["timer"] = None
        subprocess.Popen([sys.executable, os.path.join(DIR, "dj.py"), DIR, OUT], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if _dj["timer"]:
        _dj["timer"].cancel()
    _dj["timer"] = threading.Timer(wait, go)
    _dj["timer"].daemon = True
    _dj["timer"].start()


def rekordbox_closes():
    """rekordbox's library can only be written while rekordbox is closed (rekordbox.py), and a genre you change
    in rekordbox is read back at the next run. So when rekordbox closes, the decks' libraries are brought in step
    right then, with no button. Also at start, when the last run had to leave rekordbox alone and it's closed now."""
    def is_open():
        try:
            return subprocess.run(["/usr/bin/pgrep", "-x", "rekordbox"], capture_output=True).returncode == 0
        except OSError:
            return False
    log = dj.read(DIR, "dj.log").splitlines()[-40:]
    waits = lambda *words: "rekordbox is open" in ([l for l in log if any(w in l for w in words)] or [""])[-1]
    was = is_open() or waits("rekordbox: ", "REKORDBOX PROBLEM") or waits('rekordbox on "', "REKORDBOX USB PROBLEM")
    while True:
        now = is_open()
        if was and not now:
            dj_run(5)
        was = now
        time.sleep(30)


def dj_problem(lines):
    """The newest PROBLEM line that still stands: one the same deck's later run didn't put right."""
    fine = {"ENGINE": "Engine DJ on", "REKORDBOX": "rekordbox: ", "REKORDBOX USB": 'rekordbox on "',
            "SERATO": "Serato on", "ANALYSER": "listened to", "RECOGNISE": "song recognition",
            "COPY": "USB copy from"}
    for i in range(len(lines) - 1, -1, -1):
        if "PROBLEM" in lines[i]:
            m = re.search(r"((?:REKORDBOX )?[A-Z]+) PROBLEM", lines[i])
            after = fine.get(m.group(1)) if m else None
            if not (after and any(after in l and "PROBLEM" not in l for l in lines[i + 1:])):
                return lines[i]
    return ""


def usb_asking():
    """Where the chosen USB stands with "ask before changing a USB that has things on it" (usb_ask.py): None when it
    isn't plugged in, else its state, and for the question itself what would change, in numbers."""
    usb = read("usb.txt").strip()
    at = os.path.join(os.environ.get("VOLUMES") or "/Volumes", usb)
    if not usb or not os.path.isdir(at):
        return None
    s = usb_ask.state(DIR, at)
    return usb_ask.what(DIR, OUT, at) if s == "ask" else {"name": usb, "state": s, "content": usb_ask.content(at)}


def usb_answer(yes):
    """Your answer to "this USB has things on it: may The Crate add to it?". A yes starts the copy. Returns an error
    line, or None."""
    usb = read("usb.txt").strip()
    at = os.path.join(os.environ.get("VOLUMES") or "/Volumes", usb)
    if not usb or not os.path.isdir(at):
        return "That drive isn't plugged in."
    try:
        usb_ask.answer(DIR, at, bool(yes))
    except OSError:
        return "Couldn't write on that drive. Is it locked or full?"
    if yes:
        subprocess.Popen([os.path.join(DIR, "usb.sh")], start_new_session=True)
    return None


_fix = {}  # the song list's jobs started from the page (aiff.py, details.py): one of each kind at a time


def fix_start(kind, how, feed):
    """Starts one of the song list's jobs on its own (a page restart never stops it): aiff.py or details.py with the
    private Python, the ticked songs on its stdin. False while the last one of its kind is still at work."""
    if (_fix.get(kind) and _fix[kind].poll() is None) or progress("." + kind + "-progress"):
        return False
    with open(os.path.join(DIR, "dj.log"), "a") as log:
        _fix[kind] = p = subprocess.Popen([dj.PY, os.path.join(DIR, kind + ".py"), how, DIR, OUT],
                                          stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                          start_new_session=True)
    threading.Thread(target=lambda: p.communicate(feed.encode()), daemon=True).start()
    return True


def progress(name):
    """A job's own note while it runs ("done<TAB>of<TAB>its pid": aiff.py, details.py): [done, of], else None."""
    try:
        done, of, pid = read(name).split("\t")
        os.kill(int(pid), 0)
        return [int(done), int(of)]
    except (ValueError, OSError):
        return None


def on_usb(at, plugged):
    """The names in The Crate's folder on the chosen USB, however the drive spells them (None: not plugged in)."""
    try:
        return set(layout.where(os.path.join(at, usb_ask.FOLDER))) if plugged else None  # (in any of its folders)
    except OSError:
        return set()


def fix_song(rel, lacks, det, back, left, on):
    """What the song list's filters go by, for one song: only what is so, to keep the page's load small."""
    d, out = det.get(rel) or {}, {}
    if lacks.get(rel):
        out["lacks"] = lacks[rel]
    if d.get("ask"):
        out["ask"] = [{k: c.get(k) for k in ("title", "artist", "album", "year", "genre", "cover", "source") if c.get(k)}
                      for c in d["ask"][:3]]
    elif d.get("looked") and lacks.get(rel):
        out["none"] = True  # looked up, nothing sure enough to offer
    if d.get("undoable"):
        out["filled"] = sorted({f["field"] for f in d["filled"]})
    if rel in back:
        out["back"] = True
    if rel in left:
        out["left"] = left[rel]
    if on is not None:
        out["usb"] = unicodedata.normalize("NFC", rel).casefold() in on if os.sep not in rel else \
            os.path.isfile(os.path.join(os.environ.get("VOLUMES") or "/Volumes", read("usb.txt"), usb_ask.FOLDER, rel))
    return out


def dj_state():
    """Everything the DJ library page shows: each track with its tempo, key and genres, the genre list, and where
    the decks' libraries stand."""
    g = genres.load(DIR)
    lib = dj.library(DIR, OUT)
    looked = {r[6] for r in friend.wanted(DIR)}  # songs a better copy is being looked for
    songs = [{"key": s["key"], "title": s["title"], "artist": s["artist"], "bpm": s["bpm"], "tone": s["musical_key"],
              "genres": s["genres"], "from": s["from"], "heard": s["heard"], "playlist": s["playlist"],
              "sounds": s["sounds_like"], "file": s["rel"], "kbps": kbps_of(s), "low": low_song(s),
              "lists": s["lists"], "friend": s["friend"], "better": s["rel"] in looked,
              "kind": os.path.splitext(s["rel"])[1][1:].upper()} for s in lib]
    log = read("dj.log").splitlines()
    usb = read("usb.txt")
    at = os.path.join(os.environ.get("VOLUMES") or "/Volumes", usb)  # as usb.sh and dj.py: overridable for tests
    plugged = bool(usb) and os.path.isdir(at)
    rec, lacks, det, back, on = aiff.load(DIR), details.have(DIR), details.status(DIR), aiff.undoable(DIR), on_usb(at, plugged)
    for s in songs:
        s.update(fix_song(s["file"], lacks, det, back, rec["skip"], on))
        if club.deep(os.path.join(OUT, s["file"])):
            s["deep"] = True  # 32-bit: no club deck plays it; its row offers a 24-bit copy
    last = lambda *words: next((l for l in reversed(log[-40:]) if any(w in l for w in words)), "")
    return {"songs": songs, "list": g["list"], "waiting": bool(_dj["timer"]), "busy": dj.busy(DIR),
            "analyser": os.path.exists(dj.PY), "usb": usb, "usbIn": plugged, "usbAsk": usb_asking(),
            "fix": {"auto": rec["auto"], "autoDetails": details.load(DIR)["auto"],
                    "aiff": progress(".aiff-progress"), "details": progress(".details-progress"),
                    "lastAiff": last("AIFF: ", "AIFF PROBLEM"), "lastDetails": last("details: ", "DETAILS PROBLEM"),
                    "lastCues": last("cues: ", "cues put back: ", "CUES PROBLEM"),
                    "cuesNote": read("cues-unmapped.txt").splitlines()[:6]},
            "layout": layout.load(DIR), "rbApp": bool(rekordbox_app()),
            "recognise": bool(recognise.key(DIR)), "club": club.check([s["rel"] for s in lib], at, plugged, usb, club.kept(DIR, usb), OUT),
            "lastRecognise": last("song recognition", "RECOGNISE PROBLEM"),
            "engine": plugged and os.path.isfile(os.path.join(at, "Engine Library", "Database2", "m.db")),
            "rekordbox": os.path.isfile(os.path.expanduser("~/Library/Pioneer/rekordbox/master.db")),
            "lastEngine": last("Engine DJ on") or last("ENGINE PROBLEM"),
            "lastRekordbox": last("rekordbox: ") or last("REKORDBOX PROBLEM"),
            "lastRekordboxUsb": last('rekordbox on "', "REKORDBOX USB PROBLEM"),
            "lastSerato": last("Serato on", "SERATO PROBLEM"),
            # another USB with songs on it: the page asks what's on each (/api/dj/usbs) only when this list changes
            "others": friend.volumes(), "copy": friend.progress(DIR), "lastFriend": last("USB copy from", "COPY PROBLEM"),
            "problem": dj_problem(log[-6:])}


def layout_plan(mode):
    """Before a USB layout is picked (layout.py): how many songs each folder would hold, and how many would move on
    the USB that is plugged in. Nothing is touched."""
    cfg = layout.load(DIR)
    cfg["mode"] = mode if mode in layout.MODES else cfg["mode"]
    usb = read("usb.txt").strip()
    at = os.path.join(os.environ.get("VOLUMES") or "/Volumes", usb)
    ready = bool(usb) and os.path.isdir(at) and usb_ask.ready(DIR, at)
    return layout.plan(os.path.join(at, usb_ask.FOLDER) if ready else "", dj.library(DIR, OUT), cfg)


def rekordbox_app():
    """rekordbox on this Mac ("" when it isn't installed): the newest one, where its installer puts it."""
    one = os.environ.get("REKORDBOX_APP")  # for tests
    found = [one] if one else sorted(glob.glob("/Applications/rekordbox*/rekordbox.app"), reverse=True) + ["/Applications/rekordbox.app"]
    return next((p for p in found if os.path.isdir(p)), "")


def kbps_of(s):
    """A song's bitrate as the page shows it: lossy kinds only (0 for the rest, and when it can't be read)."""
    if not s["rel"].lower().endswith((".mp3", ".m4a", ".aac", ".mp4", ".ogg", ".opus")):
        return 0
    try:
        return round(s["bitrate"]) or lossy_kbps(os.path.join(OUT, s["rel"]))
    except (OSError, TypeError, ValueError):
        return 0


def low_song(s):
    """Below gig quality (friend.low: an MP3 under 320, an AAC under 256)."""
    return friend.low(os.path.splitext(s["rel"])[1].lower(), kbps_of(s))


TYPES = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav", ".aif": "audio/aiff", ".aiff": "audio/aiff",
         ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".opus": "audio/ogg"}


def song_path(rel):
    """Where a song of the music folder is ("" for anything that isn't one: the page only ever plays or shows those)."""
    root = os.path.normpath(OUT)
    p = os.path.normpath(os.path.join(root, str(rel)))
    ok = rel and p.startswith(root + os.sep) and os.path.splitext(p)[1].lower() in TYPES and os.path.isfile(p)
    return p if ok else ""


def better_back(file):
    """After "Wrong or bad file" on the page (soulseek.bad). A better copy that was itself thrown back goes on being
    looked for, for a month: its row moves from the to-get list back to better.tsv (the to-get list is SoundCloud's,
    rewritten at each sync), with the day. And a song you threw away while a better copy was being looked for is looked for no more."""
    with soulseek.locked(DIR):
        tsv = os.path.join(DIR, "to-buy.tsv")
        try:
            with open(tsv) as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        ours = lambda l: l.split("\t")[1:2] and l.split("\t")[1].startswith("better:")
        back = [l.split("\t") for l in lines if ours(l)]
        rows = was = friend.wanted(DIR)
        if back:
            with open(tsv + ".tmp", "w") as f:
                f.writelines(l + "\n" for l in lines if not ours(l))
            os.replace(tsv + ".tmp", tsv)
            for p in back:
                old = next((r for r in rows if r[1] == p[1]), None)
                rows = [r for r in rows if r[1] != p[1]] + [[p[0], p[1], "", p[3] if len(p) > 3 else "",
                                                             old[4] if old else "", old[5] if old else "",
                                                             old[6] if old else file, time.strftime("%F")]]
        elif file:
            rows = [r for r in rows if r[6] != file]
        if rows != was:
            friend.save_wanted(DIR, rows)


def genre_name(raw):
    """A genre name as typed, tidied; "" when it can't be one."""
    name = " ".join(str(raw or "").split())[:40]
    return name if name and name.isprintable() and name != genres.NONE else ""


def follow():
    """A song's file changed (details added or taken out again): the decks' lists follow, and the USB's copy when it
    is plugged in."""
    usb = read("usb.txt")
    if usb and os.path.isdir(os.path.join(os.environ.get("VOLUMES") or "/Volumes", usb)):
        subprocess.Popen([os.path.join(DIR, "usb.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        dj_run(5)
    return None


def fix_post(path, body):
    """The song list's buttons: the ticked songs become AIFFs (or one goes back), get their missing cover and details
    looked up (or one put back, or your pick of the candidates written), or go onto the USB. Ticking and pressing is
    the yes. Each runs on its own and the decks' lists follow when it is done."""
    have = {s["rel"] for s in dj.library(DIR, OUT)}
    names = lambda v: [r for r in (v if isinstance(v, list) else [v]) if isinstance(r, str) and r in have]
    if path == "/api/dj/usb-ok":  # the same answer as on the main page, from this page
        return usb_answer(body.get("yes"))
    if path == "/api/dj/cues":  # Undo: the cues the last run replaced go back (dj.py waits for a run in flight)
        try:
            r = subprocess.run([sys.executable, os.path.join(DIR, "dj.py"), DIR, OUT, "--cues-back"],
                               capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return "That took too long. Try again in a moment."
        return (r.stderr.strip().splitlines() or [""])[-1][:200] or None
    if path == "/api/dj/put":
        usb = read("usb.txt")
        if not usb or not os.path.isdir(os.path.join(os.environ.get("VOLUMES") or "/Volumes", usb)):
            return f"Plug in {usb or 'your USB'} first."
        subprocess.Popen([os.path.join(DIR, "usb.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return None
    if not os.path.exists(dj.PY):
        return "The DJ tools aren't set up on this Mac yet."
    kind = path.rsplit("/", 1)[1]
    if kind == "aiff" and "auto" in body:
        rec = aiff.load(DIR)
        rec["auto"] = bool(body["auto"])
        aiff.save(DIR, rec)
        return None
    if kind == "details" and "auto" in body:
        details.save(DIR, {**details.load(DIR), "auto": bool(body["auto"])})
        return None
    if kind == "details" and "pick" in body:  # your pick among the candidates of a song that needs a look
        rel, n = names(body["pick"]), body.get("n")
        if not rel or not isinstance(n, int):
            return "That song isn't in your library any more."
        r = subprocess.run([dj.PY, os.path.join(DIR, "details.py"), "pick", DIR, OUT, rel[0], str(n)],
                           capture_output=True, text=True, timeout=90)
        if r.returncode:
            return "Couldn't write that one: " + (r.stderr.strip().splitlines() or ["no reason given"])[-1][:160]
        return follow()
    back = "undo" in body
    rels = names(body.get("undo") if back else body.get("files"))
    if not rels:
        return "Tick the songs first."
    if kind == "details" and back:
        try:
            subprocess.run([dj.PY, os.path.join(DIR, "details.py"), "undo", DIR, OUT, *rels[:200]],
                           capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            return "That took too long. Try fewer songs at once."
        return follow()
    how = ("undo" if back else "deep" if body.get("deep") is True else "pick") if kind == "aiff" else "fill"
    if not fix_start(kind, how, json.dumps(rels) if kind == "aiff" else "\n".join(rels)):
        return "Still working on the last ones. Try again when it's done."
    return None


def dj_post(path, body):
    """The DJ library page's buttons. Returns an error line, or None when done."""
    if path == "/api/dj/recognise":  # the AcoustID key for recognising songs by their sound; "" switches it off
        key, file = "".join(str(body.get("key", "")).split()), os.path.join(DIR, recognise.KEY_FILE)
        if key and not re.fullmatch(r"[A-Za-z0-9]{6,40}", key):
            return "That doesn't look like an AcoustID key: it's the short code under \"API key\" on your application's page."
        if key:
            with open(os.open(file + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                f.write(key + "\n")
            os.replace(file + ".tmp", file)
        elif os.path.exists(file):
            os.remove(file)
        dj_run(0)
        return None
    if path == "/api/dj/copy":  # songs from another USB into your library (friend.py), on its own: it can take a while
        usb, ids = str(body.get("usb", "")), body.get("lists")
        if usb not in friend.volumes():
            return "That USB isn't plugged in any more."
        if not isinstance(ids, list) or not ids or len(ids) > 2000 or not all(
                isinstance(i, str) and re.fullmatch(r"rb:(all|\d+)|tree:Contents|dir:[^\x00-\x1f]{1,400}", i) for i in ids):
            return "Tick what to copy first."
        if friend.progress(DIR):
            return "A copy from another USB is still running."
        p = subprocess.Popen([sys.executable, os.path.join(DIR, "friend.py"), "copy", DIR, OUT, usb],
                             start_new_session=True, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        with open(os.path.join(DIR, friend.PROGRESS), "w") as f:  # shown at once; the copy keeps it up from here
            json.dump({"pid": p.pid, "usb": usb, "done": 0, "total": 0}, f)
        p.stdin.write(json.dumps(ids).encode())
        p.stdin.close()
        threading.Thread(target=p.wait, daemon=True).start()
        return None
    if path in ("/api/dj/aiff", "/api/dj/details", "/api/dj/put", "/api/dj/usb-ok", "/api/dj/cues"):
        return fix_post(path, body)
    if path == "/api/dj/layout":  # how the songs sit inside The Crate's folder on the USB (layout.py: one folder, or
        mode, other = body.get("mode"), body.get("other")  # by genre), and which genres aren't EDM. The run files them.
        if (mode is not None and mode not in layout.MODES) or (other is not None and not isinstance(other, list)):
            return "That isn't one of the folder layouts."
        layout.save(DIR, mode, other)
        dj_run(0)
        return None
    if path == "/api/dj/rekordbox":  # the song handed to rekordbox, which comes to the front. Not while the decks'
        p, rb = song_path(body.get("file", "")), rekordbox_app()  # libraries are written: rekordbox's needs it closed.
        if not p:
            return "That file isn't on your Mac any more."
        if not rb:
            return "rekordbox isn't on this Mac."
        if dj.busy(DIR):
            return "Your decks are being updated right now. Try again in a moment."
        subprocess.Popen(["open", "-a", rb, p], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return None
    if path == "/api/dj/show":  # a song's file in Finder (for a kind of file the browser can't play)
        p = song_path(body.get("file", ""))
        if not p:
            return "That file isn't on your Mac any more."
        subprocess.Popen(["open", "-R", p], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return None
    if path == "/api/dj/better":  # a song below gig quality: Soulseek is asked for a better copy, and the file you
        key = str(body.get("key", ""))  # have stays to play until one lands (dj.better swaps them); off: stop looking
        s = next((s for s in dj.library(DIR, OUT) if s["key"] == key), None)
        if not s:
            return "That track isn't on your Mac any more."
        rel, off = s["rel"], bool(body.get("off"))
        if not off:
            if not key.startswith("file:") or not low_song(s):
                return "That song is fine as it is."
            if not soulseek_ready():
                return "Sign in to Soulseek on The Crate's main page first: that's where better copies come from."
        with soulseek.locked(DIR):
            if off and any(g[0] == "better:" + rel and os.path.isfile(g[2]) for g in soulseek.load_got(DIR)):
                return "A better copy just came in: it takes this one's place in a moment."
            rows = [r for r in friend.wanted(DIR) if r[6] != rel]
            if not off:
                name = " - ".join(x for x in (s["artist"], s["title"]) if x) or os.path.splitext(rel)[0]
                rows.append([name, "better:" + rel, "", round(s["length"] or 0) or "", s["artist"], s["title"], rel, ""])
            friend.save_wanted(DIR, rows)
        if not off:
            search_again()
        return None
    g = genres.load(DIR)
    if path == "/api/dj/genres":  # your pick for one track: its genres, the first the main one; null = automatic again
        key, picked = str(body.get("key", "")), body.get("genres")
        if key not in {s["key"] for s in dj.library(DIR, OUT)}:
            return "That track isn't on your Mac any more."
        if picked is None:
            g["songs"].pop(key, None)
        else:
            if not isinstance(picked, list) or len(picked) > 8:
                return "Up to 8 genres a track."
            names = list(dict.fromkeys(n for n in map(genre_name, picked) if n))
            for n in names:  # a new one joins your list
                if genres.norm(n) not in {genres.norm(x) for x in g["list"]}:
                    g["list"].append(n)
            table = {genres.norm(x): x for x in g["list"]}
            g["songs"][key] = [table[genres.norm(n)] for n in names]
    elif path == "/api/dj/list":  # your genre list: add one, or take one off (and off every track you gave it to)
        name = genre_name(body.get("add") or body.get("remove"))
        if not name:
            return "Type a genre name."
        same = [x for x in g["list"] if genres.norm(x) == genres.norm(name)]
        if body.get("add"):
            if same:
                return f"{same[0]} is already on your list."
            if len(g["list"]) >= 60:
                return "That's a lot of genres: take one off first."
            g["list"].append(name)
        else:
            g["list"] = [x for x in g["list"] if x not in same]
            g["songs"] = {k: [x for x in v if x not in same] for k, v in g["songs"].items()}
    elif path != "/api/dj/run":
        return "not found"
    if path != "/api/dj/run":
        genres.save(DIR, g)
    dj_run(0 if path == "/api/dj/run" else 15)
    return None


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
        if self.path == "/dj":  # the DJ library page: genres, tempo, key, and the decks' libraries
            with open(os.path.join(DIR, "dj.html"), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/dj":
            return self.send(200, dj_state())
        if self.path == "/api/dj/usbs":  # what each other plugged-in USB offers to copy
            return self.send(200, friend.scan(DIR, OUT))
        if self.path.split("?")[0] == "/api/dj/layout":  # what a USB layout would do, before it is picked
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self.send(200, layout_plan((q.get("mode") or [""])[0]))
        if self.path.split("?")[0] == "/play":
            return self.play()
        if self.path.split("?")[0] == "/wave":  # a song's waveform, for the player (this page only, as /play)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            p = song_path((q.get("f") or [""])[0])
            got = p and self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none") and waveform.get(DIR, p)
            return self.send(200, got) if got else self.send(404, {"error": "no waveform"})
        if self.path.split("?")[0] == "/to-soundcloud":  # the songs for SoundCloud playlists, for Claude, Codex or you
            return self.send(200, scplaylists.page(DIR).encode(), "text/html; charset=utf-8")
        if self.path == "/api/scpl":  # what each plugged-in USB offers for SoundCloud playlists, and the Options
            return self.send(200, {"usbs": scplaylists.sources(DIR), "settings": scplaylists.settings(DIR),
                                   "run": scplaylists.counts(DIR)})
        if self.path.split("?")[0] == "/free":  # the list Claude or Codex works from
            return self.send(200, free_page().encode(), "text/html; charset=utf-8")
        self.send(404, {"error": "not found"})

    def play(self):
        """A song of the music folder, for the page's player: this page only, and in parts (Range), so a long WAV
        starts at once and can be skipped through."""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        p = song_path((q.get("f") or [""])[0])
        if not p or self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return self.send(404, {"error": "not found"})
        size = os.path.getsize(p)
        start, end, part = 0, size - 1, False
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            part = True
            if m.group(1):
                start, end = int(m.group(1)), min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                return self.end_headers()
        self.send_response(206 if part else 200)
        self.send_header("Content-Type", TYPES[os.path.splitext(p)[1].lower()])
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if part:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(p, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(262144, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except OSError:  # the player moved on (skipped, another song): nothing to do
            pass

    def liked(self, text):
        """Saves pasted Liked Songs and starts reading them (details, then EDM or not) in the background."""
        n = liked.paste(DIR, text)
        if not n:
            return self.send(400, {"error": "No Spotify song links in that. In Liked Songs, click the newest song, "
                                            "Shift-click the oldest you want, press ⌘C and paste here."})
        with open(os.path.join(DIR, "liked.log"), "a") as log:
            subprocess.Popen([sys.executable, os.path.join(DIR, "liked.py"), "read", DIR], stdout=log, stderr=log,
                             start_new_session=True)
        return self.send(200, {**state(), "likedPasted": n})

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if self.headers.get("Host") not in HOSTS or urllib.parse.urlparse(origin).netloc not in HOSTS:
            return self.send(403, {"error": "wrong origin"})
        try:
            # a pasted song list is ~55 bytes a song; the playlists and folders ticked to copy from another USB
            cap = 600_000 if self.path in ("/api/spotify-songs", "/api/liked", "/api/dj/aiff", "/api/dj/details") else \
                200_000 if self.path in ("/api/dj/copy", "/api/dj/layout", "/api/scpl/start") else 4096
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), cap)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad request"})
        if self.path.startswith("/api/dj/"):
            if not isinstance(body, dict):
                return self.send(400, {"error": "bad request"})
            bad = dj_post(self.path, body)
            return self.send(404 if bad == "not found" else 400, {"error": bad}) if bad else self.send(200, dj_state())
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
        elif self.path == "/api/spotify-songs":
            url = read("playlist.txt")
            if playlists.service(url) != "spotify":  # no Spotify playlist chosen: these are his Liked Songs
                return self.liked(str(body.get("text", "")))
            n = playlists.paste(DIR, url, str(body.get("text", "")))
            if not n:
                return self.send(400, {"error": "No Spotify song links in that. In Spotify, click one song, press "
                                                "⌘A then ⌘C, and paste here."})
            if not sync_running():  # read them now, not at the next timed sync
                subprocess.Popen([os.path.join(DIR, "sync.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                time.sleep(0.4)
        elif self.path == "/api/liked":
            return self.liked(str(body.get("text", "")))
        elif self.path == "/api/liked/forget":
            liked.forget(DIR)
        elif self.path == "/api/liked/settings":
            err = liked.set_settings(DIR, body)
            if err:
                return self.send(400, {"error": err})
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
        elif self.path == "/api/usb/ok":  # your answer to "this USB has things on it: may The Crate add to it?"
            bad = usb_answer(body.get("yes"))
            if bad:
                return self.send(400, {"error": bad})
        elif self.path == "/api/eject":
            flag = os.path.join(DIR, "usb-eject.txt")
            if body.get("on"):
                open(flag, "w").close()
            elif os.path.exists(flag):
                os.remove(flag)
        elif self.path == "/api/agent":  # the Free links list, handed to Claude or Codex on this Mac
            who = str(body.get("who", ""))
            if who == "install-claude":  # Anthropic's own installer, in a window they watch
                in_terminal("claude-install.command", "curl -fsSL https://claude.ai/install.sh | bash && echo && "
                            "echo 'Claude is installed. Go back to The Crate and press Next.'\n")
                return self.send(200, state())
            app = agent_app(who)
            if not app:
                return self.send(400, {"error": "That assistant isn't on this Mac."})
            if not chrome_app():
                return self.send(400, {"error": "Get Google Chrome first: both assistants work in it."})
            job = "scpl" if body.get("job") == "scpl" else "free"
            if job == "scpl":  # USB songs into private SoundCloud playlists
                task, n = scplaylists.brief(DIR, who, f"http://localhost:{PORT}/to-soundcloud")
                if not n:
                    return self.send(400, {"error": "No songs left to add: pick a USB's folders first."})
            else:
                task, n = agent_task(who)
                if not n:
                    return self.send(400, {"error": "No free links to get right now."})
            with open(os.path.join(DIR, ".agent-run.json"), "w") as f:  # the page shows its progress
                json.dump({"who": who, "job": job, "at": time.time(), "n": n,
                           "links": [t for _, t, _ in free_rows()] if job == "free" else []}, f)
            page = "/to-soundcloud" if job == "scpl" else "/free"
            if who == "claude":
                # A Terminal window the friend watches and answers in: Claude with its Chrome connection, started
                # in Downloads (where it renames the files), with the list as its first message.
                brief = os.path.join(DIR, "agent-task.md")
                with open(brief, "w") as f:
                    f.write(task)
                wait = "echo 'Waiting a moment for Chrome to start...'; sleep 12\n" if open_chrome(page) else ""
                # A check that runs each time Claude goes to stop: while free links are left, it's sent back to
                # the list once (agent_stop.py), so a sign-in or a question mid-list doesn't end the run.
                hook = f"{shlex.quote(sys.executable)} {shlex.quote(os.path.join(DIR, 'agent_stop.py'))}"
                with open(os.path.join(DIR, "agent-settings.json"), "w") as f:
                    json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": hook}]}]}}, f)
                in_terminal("agent-run.command", f"cd {shlex.quote(os.path.expanduser('~/Downloads'))} || exit 1\n"
                            f"{wait}exec {shlex.quote(app)} --chrome --settings "
                            f"{shlex.quote(os.path.join(DIR, 'agent-settings.json'))} \"$(cat {shlex.quote(brief)})\"\n")
                msg = (f"Claude is opening in Terminal with your {n} songs for SoundCloud. It works in Chrome and "
                       "marks each one on the list as it goes." if job == "scpl" else
                       f"Claude is opening in Terminal with your {n} free links. It asks you once what it may do "
                       "(follow, repost...), then works in Chrome. Files come in here by themselves.")
            else:
                subprocess.run(["pbcopy"], input=task.encode(), check=False)
                open_chrome(page)
                subprocess.Popen(["open", app])
                msg = (f"Codex is opening, and the request for your {n} " + ("songs for SoundCloud" if job == "scpl"
                       else "free links") + " is copied: in a new Codex chat type @Chrome, pick it, then paste (⌘V).")
            return self.send(200, dict(state(), agentMsg=msg))
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
        elif self.path == "/api/take":  # "Use this file": the file turned away for its length is this song
            got = freedl.take(DIR, OUT, str(body.get("link", "")))
            if isinstance(got, str):
                return self.send(400, {"error": got})
            picked_up(got)
        elif self.path == "/api/soulseek-bad":  # "Wrong or bad file": to the Trash, never taken again, looked for anew
            file = str(body.get("file", ""))
            if not file and not body.get("all"):
                return self.send(400, {"error": "Which file?"})
            went = soulseek.bad(DIR, SLSK, file, YTDLP)
            if not went or isinstance(went, str):
                return self.send(400, {"error": went or "That file couldn't be moved to the Trash."})
            better_back(file)  # (a better copy asked for on the Library Manager page keeps its own list)
            dj_run(0)  # the decks' playlists follow, and its copy on the USB goes too (now, or when the USB is next in)
            search_again()  # and Soulseek is asked for another copy now, not at the next sync
        elif self.path == "/api/watch":
            link = str(body.get("link", ""))
            if link:
                if not any(l.split("\t")[1:2] == [link] for l in read("to-buy.tsv").splitlines()):
                    return self.send(400, {"error": "That track isn't on the list."})
                freedl.claim(DIR, link)
                if body.get("from") == "helper":  # Claude or Codex, on its list page: the song it's on now
                    with open(os.path.join(DIR, ".agent-current.json"), "w") as f:
                        json.dump({"link": link, "at": time.time()}, f)
            _watch.set()
        elif self.path in ("/api/scpl/settings", "/api/scpl/start", "/api/scpl/mark", "/api/scpl/made",
                           "/api/scpl/forget"):  # USB songs into private SoundCloud playlists
            try:
                if self.path == "/api/scpl/settings":
                    scplaylists.set_settings(DIR, body)
                elif self.path == "/api/scpl/start":
                    scplaylists.start(DIR, str(body.get("usb", "")), [str(i) for i in body.get("ids") or []][:400])
                elif self.path == "/api/scpl/mark":
                    scplaylists.mark(DIR, str(body.get("k", "")), str(body.get("status", "")), str(body.get("url", "")),
                                     str(body.get("note", "")), helper_name() if body.get("from") == "helper" else "you")
                elif self.path == "/api/scpl/made":
                    scplaylists.made(DIR, str(body.get("name", "")), str(body.get("url", "")))
                else:
                    scplaylists.forget(DIR)
            except ValueError as e:
                return self.send(400, {"error": str(e)})
        elif self.path == "/api/needs":  # what a free link needs: paid, members only, gone, skipped (or cleared)
            link, kind = str(body.get("link", "")), str(body.get("kind", ""))
            row = next((p for p in (l.split("\t") for l in read("to-buy.tsv").splitlines()) if p[1:2] == [link]), None)
            if not row or len(row) < 3 or not re.match(r"https?://", row[2]):
                return self.send(400, {"error": "That song has no free link on the list."})
            if kind and kind not in links.KINDS:
                return self.send(400, {"error": "Pick what it needs."})
            links.mark(DIR, link, row[2], kind, str(body.get("note", "")),
                       helper_name() if body.get("from") == "helper" else "you")
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
    anything new to the USB when it's plugged in. Every minute, or every 3 s for 45 min after a Free Download
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
            picked_up(got)


def picked_up(got):
    """Songs just taken from Downloads: marked new on the page, logged, and copied to the USB if it's plugged in."""
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
    threading.Thread(target=rekordbox_closes, daemon=True).start()
    # Soulseek files kept before the right-song check existed are looked at once (the page marks the odd ones).
    threading.Thread(target=soulseek.check_all, args=(DIR, SLSK), daemon=True).start()
    if os.path.exists(AGAIN):  # a file thrown back just before the page restarted still gets its search
        search_again(new=False)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
