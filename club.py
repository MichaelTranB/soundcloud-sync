#!/usr/bin/env python3
"""The club check on the Library Manager page: would this music play on a club's decks tonight?

A club booth is nearly always Pioneer DJ decks (CDJ or XDJ), and they are fussier than a deck at home:
  the USB's format: FAT32 (and Mac OS Extended) is read by every one of them, exFAT only by the newest
    (CDJ-3000, XDJ-AZ, OPUS-QUAD, XDJ-XZ, XDJ-RX3);
  FLAC plays on the CDJ-2000NXS2 and the CDJ-3000, not on the ones before (CDJ-2000NXS, CDJ-900NXS, XDJ-RX, XDJ-RX2,
    XDJ-RR): those skip the file;
  they read playlists, tempo and key from a rekordbox library on the USB itself, and there are two kinds:
    the newer one (OneLibrary: PIONEER/rekordbox/exportLibrary.db), read by the newest decks (CDJ-3000X, XDJ-AZ,
      OPUS-QUAD, OMNIS-DUO) and shown by rekordbox under the USB. The Crate keeps this one up itself
      (rekordbox_usb.py) and notes on the Mac what it holds (dj-rekordbox-usb.json), which is what is read here;
    the older one (Device Library: PIONEER/rekordbox/export.pdb), read by the CDJ-3000, the CDJ-2000NXS2 and the
      decks before them, which only rekordbox itself writes (its Export mode: drag the playlists onto the USB
      under Devices).
(Sources: rekordbox's "USB Device Export" guide, the CDJ-2000NXS2 and CDJ-3000 manuals, AlphaTheta's notice on
USB devices and OneLibrary: alphatheta.com/en/information/important-notice-for-customers-using-usb-devices-with-our-dj-equipment/)

Only looks, never changes anything: not the USB, not rekordbox. Standard library only.

  club.py DIR MUSIC USB    prints the check (USB: where the USB is mounted, e.g. /Volumes/NAME)"""
import json, os, re, subprocess, sys, time, unicodedata

MOUNT = os.environ.get("MOUNT") or "/sbin/mount"  # overridable for tests
FORMATS = {"msdos": "FAT32", "exfat": "exFAT", "hfs": "Mac OS Extended", "apfs": "APFS", "ntfs": "NTFS"}
OLD_DECKS = "CDJ-2000NXS, CDJ-900NXS, XDJ-RX, XDJ-RX2, XDJ-RR"
NEW_DECKS = "CDJ-3000, XDJ-AZ, OPUS-QUAD, XDJ-XZ, XDJ-RX3"
ONE_DECKS = "CDJ-3000X, XDJ-AZ, OPUS-QUAD, OMNIS-DUO"  # the decks that read the newer library (OneLibrary)
EVERY = {"MP3", "WAV", "AIFF", "AIF", "M4A"}  # what every club deck plays
_seen = {}  # the export on the USB, read once per change of it


def fs(usb, text=None):
    """How the USB is formatted, as mount names it ("msdos", "exfat", ...); "" when that can't be told."""
    if text is None:
        try:
            text = subprocess.run([MOUNT], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    for line in text.splitlines():
        m = re.match(r"\S+ on (.+) \(([^,)]+)", line)
        if m and os.path.normpath(m.group(1)) == os.path.normpath(usb):
            return m.group(2).strip().lower()
    return ""


def exported(usb, names):
    """(how many of these file names are in the USB's rekordbox export, when it was made), or None when the USB
    has no export. A song's file name sits in the export as plain text, or two bytes a letter when it has accents."""
    pdb = os.path.join(usb, "PIONEER", "rekordbox", "export.pdb")
    try:
        st = os.stat(pdb)
    except OSError:
        return None
    key = (pdb, st.st_size, st.st_mtime, tuple(names))
    if _seen.get("key") != key:
        try:
            with open(pdb, "rb") as f:
                data = f.read()
        except OSError:
            return None
        def there(name):
            forms = {name, unicodedata.normalize("NFC", name), unicodedata.normalize("NFD", name)}
            return any(n.encode("utf-16-le") in data or (n.isascii() and n.encode() in data) for n in forms)
        _seen.update(key=key, n=sum(there(n) for n in names))
    return _seen["n"], st.st_mtime


def kept(dir, name):
    """The songs in the USB's own rekordbox library, as The Crate last wrote it (rekordbox_usb.py's note), or None
    when it hasn't written this USB's."""
    try:
        with open(os.path.join(dir, "dj-rekordbox-usb.json")) as f:
            was = json.load(f)
        return {unicodedata.normalize("NFC", r) for r in was["rels"]} if name and was.get("usb") == name else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def check(rels, usb="", plugged=False, name="", in_library=None):
    """The lines of the check, each {"ok": True (fine) / False (would go wrong in a club) / None (can't tell yet, or
    just worth knowing), "say": what stands, "do": what to do about it ("" when nothing)}.
    rels: the songs, as they sit in the music folder; usb: where the USB is mounted; name: what the USB is called;
    in_library: the songs in the USB's own rekordbox library that The Crate keeps (kept())."""
    s = lambda n: "" if n == 1 else "s"
    out, n = [], len(rels)
    stick = f'"{name}"' if name else "the USB"
    if not name:
        out.append({"ok": None, "say": "No USB chosen yet.", "do": "Pick one on The Crate's main page."})
    elif not plugged:
        out.append({"ok": None, "say": f"USB {stick} is not plugged in, so its format and its rekordbox export can't "
                    "be checked.", "do": "Plug it in and this fills in by itself."})
    else:
        kind = fs(usb)
        label = FORMATS.get(kind, kind.upper())
        if kind in ("msdos", "hfs"):
            out.append({"ok": True, "say": f"{stick} is {label}: every club deck reads it.", "do": ""})
        elif kind == "exfat":
            out.append({"ok": False, "say": f"{stick} is exFAT: only the newest club decks read it ({NEW_DECKS}). "
                        "On the ones before, like the CDJ-2000NXS2 (still common in booths), it shows up empty.",
                        "do": "For a gig, take a FAT32 stick: a second one, so this one stays as it is and you have "
                        "a spare. Formatting erases a stick; The Crate fills a fresh one by itself."})
        elif kind:
            out.append({"ok": False, "say": f"{stick} is {label}: no club deck reads that.",
                        "do": "For a gig, take a FAT32 stick. Formatting erases a stick; The Crate fills a fresh one "
                        "by itself."})
        else:
            out.append({"ok": None, "say": f"Couldn't tell how {stick} is formatted.", "do": ""})
        folder = os.path.join(usb, "PIONEER", "rekordbox")
        k = sum(unicodedata.normalize("NFC", r) in in_library for r in rels) if in_library is not None else 0
        if in_library is None and os.path.isfile(os.path.join(folder, "export.pdb")) and \
                not os.path.isfile(os.path.join(folder, "exportLibrary.db")):
            out.append({"ok": None, "say": f"{stick} only has rekordbox's older kind of library, so The Crate leaves "
                        "it alone.", "do": "Export to it once from rekordbox 7 (drag a playlist onto it under "
                        "Devices); The Crate keeps its newer library up from then on."})
        elif in_library is None or not n:
            out.append({"ok": None, "say": f"The Crate hasn't put your songs in {stick}'s own rekordbox library yet.",
                        "do": "It does by itself at the next run, with rekordbox closed."})
        elif k >= n:
            out.append({"ok": True, "say": f"{'Your song is' if n == 1 else f'All {n} songs are'} in {stick}'s own "
                        "rekordbox library, kept up by The Crate: rekordbox shows them under the USB, and the newest "
                        f"club decks ({ONE_DECKS}) list them with playlists, tempo and key.", "do": ""})
        else:
            out.append({"ok": None, "say": f"{k} of your {n} song{s(n)} {'is' if k == 1 else 'are'} in {stick}'s own "
                        "rekordbox library so far.", "do": "The rest go in by itself at the next run, with rekordbox "
                        "closed."})
        got = exported(usb, [os.path.basename(r) for r in rels])
        older = "the CDJ-3000, the CDJ-2000NXS2 and the decks before them"
        if got is None:
            out.append({"ok": False, "say": f"{stick} has no older rekordbox export, the one {older} read: those "
                        "would show bare folders, with no playlists, tempo or key.",
                        "do": "Before a gig on those: in rekordbox, with the USB in, drag your playlists onto it "
                        "under Devices."})
        else:
            made = time.strftime("%b %-d", time.localtime(got[1]))
            if not n:
                out.append({"ok": None, "say": f"{stick} has an older rekordbox export (made {made}); no songs here "
                            "yet to look for in it.", "do": ""})
            elif got[0] >= n:
                out.append({"ok": True, "say": f"{'Your song is' if n == 1 else f'All {n} songs are'} in the "
                            f"older rekordbox export on {stick} too (made {made}), the one {older} read.",
                            "do": ""})
            else:
                out.append({"ok": False, "say": f"{got[0]} of your {n} song{s(n)} {'is' if got[0] == 1 else 'are'} "
                            f"in the older rekordbox export on {stick} (made {made}), the one {older} read: those "
                            "only list what's in it.",
                            "do": "Before a gig on those: in rekordbox, with the USB in, drag your playlists onto it "
                            "under Devices."})
    flac = sum(r.lower().endswith(".flac") for r in rels)
    if flac:
        out.append({"ok": None, "say": f"{flac} of your {n} song{s(n)} {'is' if flac == 1 else 'are'} FLAC: fine on "
                    f"the CDJ-2000NXS2 and CDJ-3000, skipped by older decks ({OLD_DECKS}).",
                    "do": "Ask the venue which decks it has before a gig."})
    odd = sorted({os.path.splitext(r)[1][1:].upper() for r in rels} - EVERY - {"FLAC"})
    if odd:
        k = sum(os.path.splitext(r)[1][1:].upper() in odd for r in rels)
        out.append({"ok": False, "say": f"{k} song{s(k)} {'is' if k == 1 else 'are'} in a format club decks don't "
                    f"play ({', '.join(odd)}).", "do": ""})
    elif n and not flac:
        out.append({"ok": True, "say": "Every song is in a format any club deck plays.", "do": ""})
    out.append({"ok": None, "say": "Sticks fail: DJs carry a second one with the same music.",
                "do": "To fill a second stick: choose it on The Crate's main page, let it copy, then choose this one "
                "again."})
    return out


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    import dj
    d, music, usb = sys.argv[1:4]
    name = os.path.basename(os.path.normpath(usb))
    for row in check(dj.tracks(d, music), usb, os.path.isdir(usb), name, kept(d, name)):
        print({True: "ok  ", False: "FIX ", None: "note"}[row["ok"]], row["say"], row["do"])
