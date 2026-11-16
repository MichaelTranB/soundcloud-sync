"""Which genres each track belongs to. Standard library only.

A track can carry several genres; the first is its main one (the Genre column on the decks), and it sits in the
playlist of every genre it has. Where a genre comes from, best first:
  1. your own pick on the page (never overwritten by anything below)
  2. the genre written inside the file
  3. the genre the uploader chose on SoundCloud
  4. the uploader's tags on SoundCloud
  5. a genre word in the title ("... (DnB Flip)")
Anything none of these settle goes to "No genre yet" on the page, one click to fix.

genres.json (yours, git-ignored): {"list": [the genres you use], "songs": {song: [genres you picked]}}.
A song is known by its SoundCloud link when it has one (so your pick survives the Soulseek copy being replaced by
the artist's own file), else by its file name."""
import json, os, re, unicodedata

FILE = "genres.json"
NONE = "No genre yet"
# The starting list. Change it on the page: add your own, remove what you don't play.
DEFAULT = ["Dubstep", "Riddim", "Midtempo", "Future Bass", "Trap", "Drum & Bass", "House", "Bass House",
           "UK Garage", "Techno", "Trance", "Electro", "Funk & Disco", "Hip Hop", "R&B", "Pop", "Rock"]
# Other names for the same thing, as uploaders write them.
ALSO = {
    "Dubstep": "dubstep brostep deepdubstep deep-dubstep tearout wubs wubz wub melodic-dubstep color-bass colour-bass "
               "colorbass heavy-dubstep briddim",
    "Riddim": "riddim riddim-dubstep",
    "Midtempo": "midtempo mid-tempo midtempo-bass",
    "Future Bass": "future-bass futurebass melodic-bass kawaii-bass wave future-beats",
    "Trap": "trap hybrid-trap heaventrap future-trap hoodtrap festival-trap trap-edm edm-trap",
    "Drum & Bass": "dnb d&b drum-and-bass drum-&-bass drum-n-bass drumnbass drum-bass jungle liquid-dnb neurofunk "
                   "liquid-drum-and-bass",
    "House": "house tech-house deep-house progressive-house future-house slap-house afro-house",
    "Bass House": "bass-house basshouse g-house speed-house",
    "UK Garage": "uk-garage ukg garage 2-step 2step speed-garage",
    "Techno": "techno hard-techno melodic-techno",
    "Trance": "trance psytrance psy-trance hardstyle hard-dance",
    "Electro": "electro electro-house complextro electroclash",
    "Funk & Disco": "funk disco nu-disco future-funk electro-funk glitch-hop glitchhop",
    "Hip Hop": "hip-hop hiphop rap hip-hop-&-rap hip-hop-rap hip-hop/rap boom-bap",
    "R&B": "r&b rnb r-&-b r&b-&-soul soul",
    "Pop": "pop k-pop kpop hyperpop indie-pop electropop dance-pop",
    "Rock": "rock alternative-rock alternative indie punk metal pop-punk",
}
# Too broad to sort by: these say "electronic music", not which kind.
BROAD = {"electronic", "dance", "dance-&-edm", "edm", "bass", "bass-music", "remix", "flip", "bootleg", "music",
         "electronica", "other", "unknown", "soundcloud", "free-download", "freedownload", "free"}


def norm(s):
    """'Hip-hop & Rap' and 'hip hop & rap' are the same name."""
    s = unicodedata.normalize("NFKC", str(s or "")).lower().strip()
    return re.sub(r"[\s_]+", "-", s)


def load(dir):
    try:
        g = json.load(open(os.path.join(dir, FILE)))
    except (OSError, ValueError):
        g = {}
    names = [str(x).strip() for x in g.get("list") or DEFAULT if str(x).strip()]
    songs = {k: [str(x) for x in v] for k, v in (g.get("songs") or {}).items() if isinstance(v, list)}
    return {"list": list(dict.fromkeys(names)), "songs": songs}


def save(dir, g):
    p = os.path.join(dir, FILE)
    with open(p + ".tmp", "w") as f:
        json.dump(g, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(p + ".tmp", p)


def lookup(names):
    """Every way of writing a genre -> the name on your list. Your own genres match by their own name."""
    table = {}
    for name in names:
        table[norm(name)] = name
        for other in ALSO.get(name, "").split():
            table.setdefault(other, name)
    return table


def match(raw, table):
    """The genre on your list a raw label means, or None."""
    n = norm(raw)
    if not n or n in BROAD:
        return None
    return table.get(n) or table.get(n.replace("-", "")) or table.get(n.replace("&", "and"))


def decide(song, g, table=None):
    """(genres, where they came from). song: {key, tag_genre, sc_genre, mb_genres, sc_tags, title}."""
    table = table or lookup(g["list"])
    mine = g["songs"].get(song.get("key", ""))
    if mine is not None:
        return list(dict.fromkeys(mine)), "your pick"
    for raw, where in ((song.get("tag_genre"), "the file"), (song.get("sc_genre"), "SoundCloud")):
        found = [m for m in (match(part, table) for part in re.split(r"[;/,|]", raw or "")) if m]
        if found:
            return list(dict.fromkeys(found))[:3], where
    found = [m for m in (match(t, table) for t in song.get("mb_genres") or []) if m]
    if found:  # recognise.py: what MusicBrainz files the recording (then its artist) under
        return list(dict.fromkeys(found))[:2], "its sound (MusicBrainz)"
    found = [m for m in (match(t, table) for t in song.get("sc_tags") or []) if m]
    if found:
        return list(dict.fromkeys(found))[:2], "SoundCloud tags"
    # a genre word in the title, whole words only ("house" not "warehouse"); longest names first
    title = " " + re.sub(r"[^a-z0-9&]+", " ", norm(song.get("title", "")).replace("-", " ")) + " "
    for other in sorted(table, key=len, reverse=True):
        if len(other) > 3 and " " + other.replace("-", " ") + " " in title:
            return [table[other]], "the title"
    return [], ""


def heard(song):
    """What the labels said that we could not place: shown on the page so the pick is one glance."""
    out = [song.get("tag_genre"), song.get("sc_genre"), *(song.get("mb_genres") or []), *(song.get("sc_tags") or [])]
    return list(dict.fromkeys(str(x).strip() for x in out if x and str(x).strip()))[:8]
