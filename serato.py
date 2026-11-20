#!/usr/bin/env python3
"""Serato: The Crate's playlists as crates on the USB itself, so Serato shows them when the USB is plugged in.

Serato keeps the crates for music on a drive on that drive: one small file a crate in _Serato_/Subcrates, named
after the crate ("The Crate.crate"; a crate inside it is "The Crate%%House.crate"). A crate is a list of fields,
each a 4-letter name, its length (4 bytes, big end first) and its content; text is UTF-16, big end first; a
track is its path from the top of the drive, with no slash in front.
(Source: the open-source serato-tools library, github.com/bvandercar-vt/serato-tools. Serato publishes no
specification, and this was not tried in Serato itself: the songs are in a plain folder on the USB either way,
which Serato reads through its Files panel.)

Only The Crate's own crates are written ("The Crate" and the ones inside it); every other crate, and Serato's own
database on the drive, is left alone. A crate that already lists the same songs in the same order is left as it
is, so the columns and the sorting you set in Serato stay. The songs stay in their one folder on the USB
("SoundCloud Sync", or where place.py says); nothing is copied or moved. Standard library only.

  write(usb, songs, lists)    usb: where the USB is mounted; songs and lists as dj.py makes them"""
import os, struct, unicodedata

import place

FOLDER = "The Crate"
HEAD = "1.0/Serato ScratchLive Crate"
COLUMNS = ("song", "artist", "bpm", "key", "album", "length", "comment")
KINDS = (".mp3", ".m4a", ".mp4", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".alac")  # what Serato plays

text = lambda s: s.encode("utf-16-be")
field = lambda name, data: struct.pack(">4sI", name.encode(), len(data)) + data


def crate(paths):
    """A crate file listing these tracks (paths from the top of the drive)."""
    out = field("vrsn", text(HEAD)) + field("osrt", field("tvcn", text("key")) + field("brev", b"\x00"))
    for c in COLUMNS:
        out += field("ovct", field("tvcn", text(c)) + field("tvcw", text("0")))
    return out + b"".join(field("otrk", field("ptrk", text(p))) for p in paths)


def fields(data):
    at = 0
    while at + 8 <= len(data):
        name, n = struct.unpack(">4sI", data[at:at + 8])
        yield name.decode("latin-1"), data[at + 8:at + 8 + n]
        at += 8 + n


def tracks(data):
    """The tracks a crate file lists, in its order."""
    return [v.decode("utf-16-be", "replace") for name, body in fields(data) if name == "otrk"
            for k, v in fields(body) if k == "ptrk"]


def safe(name):
    """A playlist's name as a crate's file name (a drive can't hold some signs in a name)."""
    out = "".join("-" if c in '\\/:*?"<>|%' or ord(c) < 32 else c for c in unicodedata.normalize("NFC", name))
    return out.strip(" .") or "Playlist"


def write(usb, songs, lists):
    """Returns what it did, or "" when the crates were already in step."""
    music = place.web(usb)  # The Crate's folder on this USB (place.py)
    path = lambda rel: music + "/" + unicodedata.normalize("NFC", rel).replace(os.sep, "/")
    at = {s["rel"]: s.get("at") or s["rel"] for s in songs}  # the folder each sits in on this USB (layout.py)
    there = {s["rel"] for s in songs if s["rel"].lower().endswith(KINDS)
             and os.path.isfile(os.path.join(place.folder(usb), at[s["rel"]]))}
    folder = os.path.join(usb, "_Serato_", "Subcrates")
    want = {FOLDER + ".crate": [path(at[s["rel"]]) for s in songs if s["rel"] in there]} if there else {}
    for name, items in lists if there else []:
        rels = [s["rel"] if isinstance(s, dict) else s for s in items]
        want[f"{FOLDER}%%{safe(name)}.crate"] = [path(at[r]) for r in rels if r in there]
    try:
        mine = [f for f in os.listdir(folder) if f == FOLDER + ".crate" or f.startswith(FOLDER + "%%")]
    except OSError:
        mine = []
    wrote = gone = 0
    for f in mine:
        if f not in want and f.endswith(".crate"):  # a playlist that is no more
            os.remove(os.path.join(folder, f))
            gone += 1
    for f, paths in want.items():
        file = os.path.join(folder, f)
        try:
            with open(file, "rb") as fh:
                same = tracks(fh.read()) == paths
        except OSError:
            same = False
        if not same:
            os.makedirs(folder, exist_ok=True)
            with open(file + ".tmp", "wb") as fh:
                fh.write(crate(paths))
            os.replace(file + ".tmp", file)
            wrote += 1
    if not wrote and not gone:
        return ""
    s = lambda n: "" if n == 1 else "s"
    return f'{len(there)} track{s(len(there))} in {len(want) - 1} crate{s(len(want) - 1)} in "{FOLDER}"' if want \
        else f'"{FOLDER}" taken out (no songs on the USB)'
