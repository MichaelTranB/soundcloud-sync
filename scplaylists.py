#!/usr/bin/env python3
"""Private SoundCloud playlists made from the folders and playlists on a USB.

The Crate lists each song (artist, title, length) on a page of its own. Claude or Codex, in the person's own
signed-in Chrome, finds each one on SoundCloud, checks it is the same song and about the same length, and adds it to
a private playlist named after its folder (or to one playlist for them all, as picked under Options). Anyone can do
the same by hand from that page. Songs it isn't sure of are left for a look, never guessed.

What was done is kept in sc-playlists.json, so a run can stop and pick up again without adding a song twice.
Never uploads a file, never makes anything public, never changes the USB.
"""
import contextlib, fcntl, json, os, re, subprocess, threading, time, unicodedata

import friend

FILE = "sc-playlists.json"
DEFAULTS = {"mode": "each", "name": "From my USB"}  # mode: "each" (a playlist per folder, named after it) or "one"
CAP = 500  # the most songs SoundCloud takes in one playlist: bigger ones become "Name (2)", "Name (3)"...
STATUS = {"added": "Added", "unsure": "Not sure", "none": "Not on SoundCloud"}


def load(d):
    try:
        with open(os.path.join(d, FILE)) as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d, s):
    p = os.path.join(d, FILE)
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, p)


_mine = threading.Lock()


@contextlib.contextmanager
def _edit(d):
    """One change at a time (two tabs marking songs at once both count): yields the state; saved on the way out."""
    with _mine, open(os.path.join(d, ".sc-playlists.lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        s = load(d)
        yield s
        _save(d, s)


def settings(d):
    got = load(d).get("settings") or {}
    return {k: got.get(k, v) for k, v in DEFAULTS.items()}


def set_settings(d, body):
    now = settings(d)
    if body.get("mode") in ("each", "one"):
        now["mode"] = body["mode"]
    if "name" in body:
        name = re.sub(r"\s+", " ", str(body["name"])).strip()[:80]
        if not name:
            raise ValueError("Give the playlist a name.")
        now["name"] = name
    with _edit(d) as s:
        s["settings"] = now
    return now


def sources(d):
    """What each plugged-in USB offers: {usb: [(id, name, how many songs)]}. Its folders of songs (The Crate's own
    category folders too) and, when it has a rekordbox library, its playlists."""
    out = {}
    for vol in friend.volumes():
        base = os.path.join(friend.root(), vol)
        got = []
        lib = friend.library_of(d, vol)
        if lib:
            names, _ = friend.named(lib)
            for i, name in names.items():
                n = sum(1 for c in lib["members"].get(i, []) if c in lib["tracks"])
                if n:
                    got.append(("rb:" + i, "rekordbox: " + name, n))
        elif os.path.isdir(os.path.join(base, "Contents")):  # library unreadable: its songs as one source, as pick() does
            n = len(friend.tree(base, "Contents"))
            if n:
                got.append(("tree:Contents", "Everything rekordbox put on it", n))
        for rel, songs in friend.folders(base, False, not lib and not os.path.isdir(os.path.join(base, "Contents"))):
            if rel:
                got.append(("dir:" + rel, rel.replace(os.sep, " / "), len(songs)))
        if got:
            out[vol] = got
    return out


def _seconds(path, lens):
    """A file's length in seconds (afinfo, kept by size and date so a USB is read once)."""
    try:
        st = os.stat(path)
    except OSError:
        return 0
    stamp = [st.st_size, int(st.st_mtime)]
    if path in lens and lens[path][:2] == stamp:
        return lens[path][2]
    try:
        out = subprocess.run(["afinfo", path], capture_output=True, text=True, timeout=20).stdout
        m = re.search(r"estimated duration:\s*([\d.]+)", out)
        secs = round(float(m.group(1))) if m else 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        secs = 0
    lens[path] = stamp + [secs]
    return secs


def split_name(file):
    """Artist and title from a file name like "01 Artist - Title (Extended Mix).mp3"."""
    s = os.path.splitext(os.path.basename(file))[0]
    # a track number only when it looks like one ("01 ", "3. ", "12 - "): "50 Cent" and "808 State" keep theirs
    cut = re.sub(r"^(?:0\d{1,2}\s*[-._)]?\s*|\d{1,3}\s*[-._)]\s+)", "", s)
    s = (cut if " - " in cut or " - " not in s else s).replace("_", " ").strip()  # "112 - Cupid": 112 is the artist
    if " - " in s:
        a, t = s.split(" - ", 1)
        return a.strip(), t.strip()
    return "", s


def songs_of(d, vol, sid, lens):
    """One source's songs: [{"artist", "title", "secs", "file"}], in its own order."""
    base = os.path.join(friend.root(), vol)
    lib = friend.library_of(d, vol) or {"tracks": {}, "members": {}}
    by_path = {t["path"]: t for t in lib["tracks"].values()}
    if sid.startswith("rb:"):
        items = [lib["tracks"][c] for c in lib["members"].get(sid[3:], []) if c in lib["tracks"]]
        files = [t["path"] for t in items]
    elif sid.startswith("dir:"):
        rel = sid[4:]
        full = friend.within(base, rel) if rel else ""
        if not full or not os.path.isdir(full):
            return []
        files = ["/" + os.path.join(rel, n) for n in sorted(os.listdir(full), key=str.lower)
                 if not n.startswith(".") and n.lower().endswith(friend.TAKEN)]
    elif sid == "tree:Contents" and not lib["tracks"]:
        files = ["/" + p for p in friend.tree(base, "Contents")]
    else:
        return []
    out = []
    for p in files:
        t = by_path.get(p) or {}
        artist, title = (t.get("artist") or "", t.get("title") or "")
        if not title:
            artist, title = split_name(p)
        secs = round(t.get("length") or 0) or _seconds(base + p, lens)
        out.append({"artist": artist, "title": title, "secs": secs, "file": p})
    return out


def key(list_name, song):
    # the whole "artist - title" (no file ending to drop: "Song (feat. Alice)" and "(feat. Bob)" stay two songs)
    # letters of every alphabet count (봄날 and 쩔어 stay two songs); accents, spaces and punctuation don't
    s = unicodedata.normalize("NFKD", (song["artist"] + " - " + song["title"]) if song["artist"] else song["title"])
    return list_name + "\n" + (re.sub(r"[\W_]+", "", s.lower()) or s.lower())


def parts(name, songs, before, owner):
    """Splits a playlist's songs into SoundCloud-sized parts. Songs placed in a part by an earlier run stay in it
    (the playlist on SoundCloud already holds them); new songs go to the last part, then to new ones. owner maps each
    playlist name in the run to the folder it belongs to, so a part never takes a name another folder has."""
    def free():
        n = 2
        while f"{name} ({n})" in owner:
            n += 1
        owner[f"{name} ({n})"] = name
        return f"{name} ({n})"

    old = [l for l in before if l.get("group") == name]
    here = {x["k"]: x for x in songs}
    out = [{"name": l["name"], "songs": [here.pop(x["k"]) for x in l["songs"] if x["k"] in here]} for l in old]
    held = [max(l.get("held", 0), len(l["songs"])) for l in old]  # what each SoundCloud playlist already holds
    new = [x for x in songs if x["k"] in here]
    if not out:
        out, held = [{"name": name if owner.get(name) == name else free(), "songs": []}], [0]
    while new:
        if held[-1] >= CAP:
            out.append({"name": free(), "songs": []})
            held.append(0)
        take, new = new[:CAP - held[-1]], new[CAP - held[-1]:]
        out[-1]["songs"] += take
        held[-1] += len(take)
    return [dict(l, group=name, held=h) for l, h in zip(out, held) if l["songs"]]


def start(d, vol, ids):
    """Sets up a run: the playlists to make from those sources of a USB, with their songs. Songs already done in an
    earlier run keep what was found for them."""
    if vol not in friend.volumes():
        raise ValueError("That USB isn't plugged in.")
    offered = dict((i, n) for i, n, _ in sources(d).get(vol, []))
    ids = [i for i in ids if i in offered]
    if not ids:
        raise ValueError("Tick at least one folder or playlist.")
    lens = load(d).get("lens") or {}
    opts = settings(d)
    path = {i: offered[i].split(": ", 1)[-1].split(" / ") for i in ids}
    last = [p[-1] for p in path.values()]
    named = dict(load(d).get("named") or {})  # each folder keeps the playlist name it was first given
    sid = lambda i: vol + "\n" + i

    def own(i):  # a playlist per folder, named after it; two folders called "House" become "House (2025)" and so on
        if sid(i) in named:
            return named[sid(i)]
        p = path[i]
        taken = {v for k, v in named.items() if k != sid(i)}
        for name in (p[-1], f"{p[-1]} ({' / '.join(p[:-1])})", " / ".join(p)):
            if name not in taken and (name != p[-1] or last.count(p[-1]) < 2 or len(p) < 2):
                break
        named[sid(i)] = name
        return name

    groups = []  # (playlist name, songs)
    for i in ids:
        songs = songs_of(d, vol, i, lens)
        name = own(i) if opts["mode"] == "each" else opts["name"]
        g = next((g for g in groups if g[0] == name), None)
        if g:
            g[1].extend(songs)
        else:
            groups.append((name, songs))
    with _edit(d) as s:
        before = (s.get("run") or {}).get("lists") or []
        owner = {name: name for name, _ in groups}  # each folder keeps its own name; earlier parts keep theirs
        owner.update((l["name"], l["group"]) for l in before if l.get("group") in owner)
        lists = []
        for name, songs in groups:
            seen, uniq = set(), []
            for x in songs:
                k = key(name, x)
                if k not in seen:
                    seen.add(k)
                    uniq.append(dict(x, k=k))
            lists.extend(parts(name, uniq, before, owner))
        s["named"] = {**(s.get("named") or {}), **named}
        s.update(lens={**(s.get("lens") or {}), **lens}, run={"usb": vol, "ids": ids, "at": time.time(), "lists": lists})
    return counts(d)


def mark(d, k, status, url="", note="", by="you"):
    if status and status not in STATUS:
        raise ValueError("Pick Added, Not sure or Not on SoundCloud.")
    url = url.strip()
    if url and not re.match(r"https://(on\.|m\.|www\.)?soundcloud\.com/\S+$", url):
        raise ValueError("That isn't a SoundCloud link.")
    with _edit(d) as s:
        done = s.setdefault("songs", {})
        if status:
            done[k] = {"status": status, "url": url, "note": re.sub(r"\s+", " ", note).strip()[:140], "by": by,
                       "at": time.time()}
        else:
            done.pop(k, None)


def made(d, name, url):
    """The link of a playlist once it's made on SoundCloud."""
    url = url.strip()
    if url and not re.match(r"https://(on\.|m\.|www\.)?soundcloud\.com/[^/\s]+/sets/\S+$", url):
        raise ValueError("Paste the playlist's own link (it has /sets/ in it).")
    with _edit(d) as s:
        s.setdefault("made", {})[name] = url


def forget(d):
    with _edit(d) as s:
        s.pop("run", None)


def counts(d):
    """How far the run is: songs in it, added, not sure, not on SoundCloud, left; and its playlists."""
    s = load(d)
    run = s.get("run") or {}
    done = s.get("songs") or {}
    c = {"songs": 0, "added": 0, "unsure": 0, "none": 0, "left": 0}
    for pl in run.get("lists", []):
        for x in pl["songs"]:
            c["songs"] += 1
            st = (done.get(x["k"]) or {}).get("status")
            c[st if st in STATUS else "left"] += 1
    c["lists"] = [{"name": pl["name"], "n": len(pl["songs"]), "url": (s.get("made") or {}).get(pl["name"], "")}
                  for pl in run.get("lists", [])]
    c["usb"] = run.get("usb", "")
    return c


def mmss(secs):
    return f"{secs // 60}:{secs % 60:02d}" if secs else "?"


BRIEF = """{lead}Please make private SoundCloud playlists from my USB, for my music app The Crate, using my Chrome
(I'm signed in to SoundCloud there).

Open this page in Chrome (The Crate has just opened it there): {page}
It lists {n} songs to add, in these playlists: {names}.

For each playlist on that page, top to bottom:
1. If its "Playlist link" box is empty, make it on SoundCloud with exactly that name, set to PRIVATE (never public):
   with the first song you add, open "More" (the ... button) > "Add to playlist" > "Create a playlist", type the
   name, pick Private, Save. Then paste the new playlist's link into its box on the list page and press Save. If the
   box has a link, the playlist is already made: add to that one.
2. For each song under it: click its "Search SoundCloud" link ON THAT PAGE. Pick the result whose artist and title
   match and whose length is within 5 seconds of the length shown. Watch the mix: an "Extended Mix", "Radio Edit",
   remix or bootleg is a different song unless the list says so. Prefer the artist's or label's own upload.
   Add it to the playlist (... > Add to playlist > that playlist), then on the list page set the song to "Added",
   paste the track's link, and press Save.
   Not sure (no exact match, the length is off by more than 5 seconds, only another mix)? Don't add it: set "Not
   sure", paste the closest link, write why in a few words, Save. I'll look at those. Nothing there at all: set
   "Not on SoundCloud".
3. Close the tabs that song opened (keep only the list page), and wait a few seconds before the next song, so my
   account doesn't look like a bot.
Reload the list page whenever you like: songs that are done drop off it. A playlist holds 500 songs at most: The
Crate has already split bigger ones into "Name (2)" and so on.

Keep going until every song is done: don't stop in the middle to wait for me. If something needs me (a sign-in, a
"prove you're human" check), leave its tab open, tell me in one line, and carry on; look at it again now and then.

Never: make a playlist or anything else public, upload a file, delete or rename anything, remove a song from a
playlist, follow, like, repost or comment, pay, or type a password or code (that's mine to do). Don't touch anything
else in The Crate. If you can't reach my Chrome yet, it may still be starting: wait 15 seconds and try again, up to
4 times, before you tell me and stop. Use my own Google Chrome, not a built-in browser.

At the end, tell me in a short list: the playlists made (with their links), how many songs were added, and how many
are "Not sure" or not on SoundCloud.
"""


def brief(d, who, page):
    c = counts(d)
    names = ", ".join(f'"{x["name"]}"' for x in c["lists"]) or "none"
    return BRIEF.format(lead="@Chrome " if who == "codex" else "", page=page, n=c["left"], names=names), c["left"]


def page(d):
    """The list Claude or Codex (or you) works from: each playlist, its songs still to add with a SoundCloud search
    and the length to match, and the ones that need a look."""
    from html import escape as e
    from urllib.parse import quote_plus
    s = load(d)
    run = s.get("run") or {}
    done = s.get("songs") or {}
    links = s.get("made") or {}
    c = counts(d)
    parts, look = [], []
    for pl in run.get("lists", []):
        left = [x for x in pl["songs"] if (done.get(x["k"]) or {}).get("status") not in STATUS]
        for x in pl["songs"]:
            r = done.get(x["k"]) or {}
            if r.get("status") == "unsure":
                look.append((pl["name"], x, r))
        url = links.get(pl["name"], "")
        items = "".join(
            f'<li><b>{e(x["artist"] + " – " if x["artist"] else "")}{e(x["title"])}</b> <span class="len">'
            f'{mmss(x["secs"])}</span> <a href="https://soundcloud.com/search/sounds?q='
            f'{quote_plus((x["artist"] + " " + x["title"]).strip())}" target="_blank" rel="noopener">Search SoundCloud</a>'
            f'<form data-k="{e(x["k"])}"><select name="status">'
            + "".join(f'<option value="{k}">{v}</option>' for k, v in STATUS.items())
            + '</select><input name="url" placeholder="The track\'s SoundCloud link"><input name="note" maxlength="140" '
              'placeholder="Why (if not sure)"><button>Save</button></form></li>' for x in left)
        parts.append(
            f'<section><h2>{e(pl["name"])} <small>private · {len(pl["songs"])} songs · {len(left)} left</small></h2>'
            f'<form class="pl" data-name="{e(pl["name"])}"><input name="url" value="{e(url)}" '
            f'placeholder="Playlist link, once it\'s made"><button>Save</button>'
            + (f' <a href="{e(url)}" target="_blank" rel="noopener">Open ↗</a>' if url else "")
            + f'</form><ol>{items}</ol></section>')
    looks = "".join(
        f'<li><b>{e(x["artist"] + " – " if x["artist"] else "")}{e(x["title"])}</b> <span class="len">{mmss(x["secs"])}'
        f'</span> in {e(n)}<br><small>{e(r.get("note") or "")}</small>'
        + (f' <a href="{e(r["url"])}" target="_blank" rel="noopener">Closest match ↗</a>' if r.get("url") else "")
        + f'<form data-k="{e(x["k"])}"><select name="status"><option value="added">Added</option><option value="none">'
          'Not on SoundCloud</option></select><input name="url" placeholder="The track\'s SoundCloud link" value="'
        + e(r.get("url") or "") + '"><button>Save</button></form></li>' for n, x, r in look)
    body = "".join(parts) or "<p>Nothing to add yet: pick a USB's folders in The Crate first.</p>"
    return f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Crate: to SoundCloud</title>
<style>body{{font:16px/1.5 -apple-system,system-ui,sans-serif;background:#0c0c12;color:#f0eef8;max-width:760px;margin:32px auto;padding:0 16px}}
p,h2 small{{color:#a4a2b6;font-weight:400;font-size:14px}} li{{margin:12px 0}} a{{color:#ff6b7d;font-weight:600;margin-left:8px}}
.len{{color:#f0a868;font-variant-numeric:tabular-nums}} small{{color:#f0a868}} section{{margin:28px 0}}
form{{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}} select,input{{font:inherit;font-size:14px;padding:3px 8px;border-radius:8px;border:1px solid #3a3a48;background:#16161e;color:#f0eef8}} input{{flex:1;min-width:180px}}
button{{font:inherit;font-size:14px;padding:2px 10px;border-radius:8px;border:1px solid #ff6b7d;background:none;color:#ff6b7d;cursor:pointer}}</style>
<h1>To SoundCloud: {c["left"]} left</h1>
<p>Each playlist is private. Search each song, add the one whose artist, title and length match, then mark it here.
Not sure? Mark it so, with the closest link: it waits below for a look. Done songs drop off when the page is reloaded.</p>
{body}
{f'<section><h2>Needs a look <small>{len(look)}</small></h2><ol>{looks}</ol></section>' if look else ''}
<script>const post = (u, b) => fetch(u, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(b) }});
const send = async (f, u, b) => {{ const r = await post(u, b); if (r.ok) location.reload(); else alert((await r.json()).error); }};
for (const f of document.querySelectorAll('form[data-k]')) f.addEventListener('submit', e => {{ e.preventDefault();
  send(f, '/api/scpl/mark', {{ k: f.dataset.k, status: f.status.value, url: f.url.value, note: f.note ? f.note.value : '', from: 'helper' }}); }});
for (const f of document.querySelectorAll('form.pl')) f.addEventListener('submit', e => {{ e.preventDefault();
  send(f, '/api/scpl/made', {{ name: f.dataset.name, url: f.url.value }}); }});</script>
"""
