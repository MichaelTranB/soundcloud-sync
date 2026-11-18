"""Who has seen the guided tour: a small JSON in the app's own folder (tour.json, not in git), so it survives a cleared
browser, another browser and app updates. Standard library only.

The first time it is asked, it records whether this was already a working install (a playlist set up, the DJ
library used). That answer is kept, so a tour left half-way, or a playlist added during it, never changes it.

Per page ("home" = The Crate, "dj" = the Library Manager), status() is one of:
  "auto"  first-time user: the tour starts by itself
  "offer" an install that was working before the tour existed, on a page it never used: a one-line offer only
  "seen"  finished or skipped, or an existing install: nothing shows by itself
"""
import json, os, time

PAGES = ("home", "dj")
FILE = "tour.json"


def _path(d):
    return os.path.join(d, FILE)


def _load(d):
    try:
        with open(_path(d)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("seen"), dict) else None
    except (OSError, ValueError):
        return None


def _save(d, data):
    tmp = _path(d) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _path(d))


def state(d, existing, dj_used):
    """{'home': status, 'dj': status}. `existing`: a playlist is set up; `dj_used`: the DJ library has been written."""
    data = _load(d)
    if data is None:  # first ask: remember what this install was
        data = {"existing": bool(existing), "djUsed": bool(dj_used), "seen": {}}
        try:
            _save(d, data)
        except OSError:  # a read-only folder: still answer, from what is here now
            pass
    seen, old = data["seen"], bool(data.get("existing"))

    def one(page):
        if seen.get(page):
            return "seen"
        if page == "home":
            return "seen" if old else "auto"
        if old:
            return "seen" if data.get("djUsed") else "offer"
        return "auto"
    return {p: one(p) for p in PAGES}


def mark(d, page, existing=False, dj_used=False):
    """The tour on `page` was finished, skipped or its offer dismissed."""
    if page not in PAGES:
        return False
    state(d, existing, dj_used)  # makes the file, with the first-ask facts, if it isn't there yet
    data = _load(d) or {"existing": bool(existing), "djUsed": bool(dj_used), "seen": {}}
    data["seen"][page] = time.strftime("%Y-%m-%d")
    _save(d, data)
    return True
