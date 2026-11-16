"""Recognises each track by its sound, the way MusicBrainz Picard does: a fingerprint of the audio (Chromaprint,
made by Essentia) is looked up on AcoustID, and MusicBrainz says which recording it is and what genres it's filed
under.

    recognise.py <app folder> <music folder>     with the private Python (dj-setup.sh); dj.py starts it, on its own

What the answer is used for:
  - genres, for tracks whose own labels don't say (genres.py: your pick, the file's label and SoundCloud's genre
    still come first);
  - a second opinion on Soulseek files: one that sounds like another song is flagged on the page (soulseek.py).
    Only flagged, never thrown back by itself: a flip or bootleg is often not in the database at all.
Needs an AcoustID application key (free: acoustid.org/new-application), saved from the DJ library page into
acoustid-key.txt in the app folder; KEY below is the one the app ships with. Without a key this does nothing.
What leaves the Mac: the fingerprint and the track's length to AcoustID, a recording number to MusicBrainz. No file
names, no account. One at a time; answers are kept in recognised.json, and a track nobody knows yet is asked about
again after 30 days."""
import fcntl, json, os, sys, time, urllib.error, urllib.parse, urllib.request

KEY = ""  # The Crate's own AcoustID application key, once it has one
KEY_FILE = "acoustid-key.txt"
FILE = "recognised.json"
ACOUSTID = os.environ.get("ACOUSTID_URL") or "https://api.acoustid.org/v2/lookup"
MUSICBRAINZ = os.environ.get("MUSICBRAINZ_URL") or "https://musicbrainz.org/ws/2/recording/"
AGENT = "TheCrate/1.0 (music library app)"
SURE = 0.85  # AcoustID's score from 0 to 1: under this the match is a guess and is left out
AGAIN_DAYS = 30
PAUSE = {"acoustid": 0.4, "musicbrainz": 1.1}  # both ask for no more than 3 and 1 questions a second
_last = {}


class BadKey(Exception):
    pass


def key(dir):
    try:
        with open(os.path.join(dir, KEY_FILE)) as f:
            return f.read().strip() or KEY
    except OSError:
        return KEY


def load(dir):
    try:
        with open(os.path.join(dir, FILE)) as f:
            got = json.load(f)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def save(dir, got):
    tmp = os.path.join(dir, FILE + ".tmp")
    with open(tmp, "w") as f:
        json.dump(got, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, os.path.join(dir, FILE))


def ask(who, url, data=None):
    """One question to AcoustID or MusicBrainz, never faster than they allow. The answer as JSON."""
    wait = _last.get(who, 0) + PAUSE[who] - time.time()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None,
                                 headers={"User-Agent": AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:  # AcoustID says what was wrong in the body of its 400
            return json.load(e)
        except ValueError:
            raise e
    finally:
        _last[who] = time.time()


def fingerprint(path):
    """(the fingerprint AcoustID knows, the track's length in seconds)."""
    import dj_analyze
    import essentia.standard as es
    audio = dj_analyze.load(path)
    if len(audio) < 44100 * 10:
        raise ValueError("too short to recognise")
    return es.Chromaprinter(maxLength=120)(audio), len(audio) / 44100.0


def lookup(client, print_, secs):
    """AcoustID's best answer: (score, [(recording id, artist, title)]), or (0, []) when nobody knows the track."""
    r = ask("acoustid", ACOUSTID, {"client": client, "format": "json", "meta": "recordings", "duration": int(round(secs)),
                                   "fingerprint": print_})
    if r.get("status") != "ok":
        err = r.get("error") or {}
        if err.get("code") in (4, 5, 6):  # invalid, missing or disabled key
            raise BadKey(err.get("message") or "the key wasn't accepted")
        raise RuntimeError(err.get("message") or "AcoustID couldn't answer")
    for res in sorted(r.get("results") or [], key=lambda x: -(x.get("score") or 0)):
        recs = [(x.get("id") or "", ", ".join(a.get("name") or "" for a in x.get("artists") or []), x.get("title") or "")
                for x in res.get("recordings") or [] if x.get("title")]
        if recs:
            return float(res.get("score") or 0), recs[:5]
    return 0.0, []


def filed_under(mbid):
    """The genres MusicBrainz files a recording under, then the ones most people give its artists."""
    r = ask("musicbrainz", MUSICBRAINZ + urllib.parse.quote(mbid) + "?inc=artists+genres&fmt=json")
    top = lambda gs, least: [g["name"] for g in sorted(gs or [], key=lambda g: -g.get("count", 0)) if g.get("count", 0) >= least]
    out = top(r.get("genres"), 1)
    for credit in r.get("artist-credit") or []:
        gs = (credit.get("artist") or {}).get("genres") or []
        most = max([g.get("count", 0) for g in gs] or [0])
        out += top(gs, max(2, most / 3))
    return list(dict.fromkeys(out))[:8]


def run(dir, src, log=lambda text: None):
    """Asks about every track not asked about yet. Returns how many new answers came in."""
    import dj
    client = key(dir)
    if not client:
        return 0
    lock = open(os.path.join(dir, ".recognise.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    rels, got, now, new, known = dj.tracks(dir, src), load(dir), int(time.time()), 0, 0
    todo = []
    for rel in rels:
        try:
            st = os.stat(os.path.join(src, rel))
        except OSError:
            continue
        old = got.get(rel) or {}
        same = old.get("size") == st.st_size and old.get("mtime") == int(st.st_mtime)
        if same and (old.get("names") or now - old.get("at", 0) < AGAIN_DAYS * 86400):
            continue
        todo.append((rel, st))
    try:
        for rel, st in todo:
            out = {"size": st.st_size, "mtime": int(st.st_mtime), "at": now, "path": os.path.realpath(os.path.join(src, rel))}
            try:
                print_, secs = fingerprint(os.path.join(src, rel))
            except Exception as e:
                out["error"] = (str(e) or type(e).__name__)[:200]
            else:
                score, recs = lookup(client, print_, secs)
                if recs and score >= SURE:
                    out.update({"score": round(score, 2), "id": recs[0][0], "names": [[a, t] for _, a, t in recs]})
                    try:
                        out["genres"] = filed_under(recs[0][0])
                    except (OSError, ValueError):
                        out["genres"] = []
                    known += 1
            got[rel] = out
            new += 1
            if new % 10 == 0:
                save(dir, got)
    except BadKey as e:
        log(f"RECOGNISE PROBLEM: AcoustID didn't take the key ({e}). Save it again on the DJ library page.")
    except RuntimeError as e:  # AcoustID answered, with a problem of its own: the rest waits for the next run
        log(f"song recognition stopped for now (AcoustID said: {str(e)[:120]}); it carries on at the next run")
    except OSError:  # no internet, or one of the two is down
        log("song recognition stopped for now (no answer from AcoustID or MusicBrainz: is the internet on?); it carries on at the next run")
    for rel in [r for r in got if r not in set(rels)]:  # a track no longer in the folder leaves the list
        del got[rel]
    if new or len(got) != len(load(dir)):
        save(dir, got)
    if new:
        log(f"song recognition: listened to {new} track{'s' if new != 1 else ''}, {known} known to MusicBrainz")
    return new


if __name__ == "__main__":
    import dj
    d, s = sys.argv[1], sys.argv[2]
    if run(d, s, lambda text: dj.log(d, text)):
        dj.run(d, s, os.environ.get("VOLUMES") or "/Volumes")  # the new genres reach the decks
