#!/usr/bin/env python3
"""rekordbox_pdb.py: keeps the older rekordbox library on a USB in step with the newer one.

A USB made by rekordbox 7 carries two libraries side by side: exportLibrary.db ("OneLibrary", read by the newest
players) and export.pdb ("Device Library", read by the CDJ-3000, CDJ-2000NXS2, XDJ-RX3, XDJ-XZ, XDJ-1000MK2 and
everything before them). rekordbox_usb.py writes The Crate's songs and playlists into the first. This file mirrors
that part into the second, row for row and id for id, so rekordbox finds the same playlists in both and the older
players show The Crate's songs too, where they sit in The Crate's own folder (nothing is copied into /Contents).

Only The Crate's own rows are ever touched: the tracks under its folder, its "The Crate" playlist folder with the
lists in it and their entries, and the artist, album, key, genre, label and artwork rows those tracks need (added
when missing; never changed, never removed). Every other row, page and table stays byte for byte where it is, which
check_kept() proves on the finished bytes before anything reaches the USB. It is done the way rekordbox does it
itself, as read from its own files: a changed row is rewritten in place when it still fits, else its slot is
switched off and the row is added at the end of its table; a full table gets the page rekordbox had set aside.

Plain Python, no rekordbox and no extra library needed. The file's layout follows the public notes of the
Deep Symmetry "DJ Link Ecosystem Analysis" and the rekordcrate project.
"""
import os
import struct
import unicodedata

PAGE, HEAP, ROOM = 4096, 0x28, 4096 - 0x28
TRACKS, GENRES, ARTISTS, ALBUMS, LABELS, KEYS, COLORS, TREE, ENTRIES, ARTWORK = 0, 1, 2, 3, 4, 5, 6, 7, 8, 13
MINE = (TRACKS, GENRES, ARTISTS, ALBUMS, LABELS, KEYS, TREE, ENTRIES, ARTWORK)  # the only tables ever written
NONE = 0x1FFF
TRACK = struct.Struct("<2H18I6H2B2H21H")  # a track row up to its strings (0x88 bytes)


class Bad(Exception):
    """The file is not laid out the way this code knows, or the two libraries have drifted apart: nothing is written."""


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def up4(n):
    return (n + 3) & ~3


def text(s):
    """A string the way the file stores it: short ASCII, long ASCII, or UTF-16."""
    s = nfc(s)
    try:
        b = s.encode("ascii")
    except UnicodeEncodeError:
        b = s.encode("utf-16-le")
        return b"\x90" + struct.pack("<H", len(b) + 4) + b"\0" + b
    if len(b) <= 126:
        return bytes([((len(b) + 1) << 1) | 1]) + b
    return b"\x40" + struct.pack("<H", len(b) + 4) + b"\0" + b


def isrc(s):
    b = nfc(s).encode("ascii", "ignore")
    return b"\x90" + struct.pack("<H", len(b) + 6) + b"\0\x03" + b + b"\0" if b else b"\x03"


def read(d, o):
    """(the string at o, the bytes it takes)."""
    k = d[o]
    if k & 1:
        n = k >> 1
        return d[o + 1:o + n].decode("ascii", "replace"), max(n, 1)
    n = struct.unpack_from("<H", d, o + 1)[0]
    if k == 0x40:
        return d[o + 4:o + n].decode("ascii", "replace"), n
    if k == 0x90:  # (a track's ISRC is kept this way too, with its own layout: never read here)
        return bytes(d[o + 4:o + n]).decode("utf-16-le", "replace"), n
    raise Bad(f"a string of a kind not seen before ({k:#x})")


LONGEST = 255  # letters in a name, a title or a comment: a row has to fit in one page of the file


def clip(s):
    return nfc(s or "")[:LONGEST]


def fitted(want):
    """`want` with every free-text field cut to LONGEST letters (a 4,000-letter comment tag would not fit a page).
    Paths and file names are never cut: they have to match the file."""
    out = dict(want)
    out["tracks"] = [dict(t, title=clip(t.get("title")), comment=clip(t.get("comment"))) for t in want["tracks"]]
    for key in ("artists", "albums", "keys", "genres", "labels"):
        out[key] = {i: dict(r, name=clip(r.get("name"))) for i, r in want.get(key, {}).items()}
    out["lists"] = [(key, clip(title), members) for key, title, members in want["lists"]]
    return out


# ---- rows: each maker returns the whole slot (padded the way rekordbox pads its own) ----

def track_row(t, shift):
    words = [b"\x03"] * 21
    put = lambda i, s: words.__setitem__(i, text(s)) if s else None
    words[0] = isrc(t.get("isrc"))
    put(2, t.get("info")), put(3, t.get("anlzCount")), put(6, "ON" if t.get("kuvo") else ""), put(7, "ON" if t.get("auto") else "")
    put(10, t.get("added")), put(14, t.get("anlz")), put(15, t.get("anlzDate")), put(16, t.get("comment"))
    put(17, t.get("title")), put(19, t.get("fileName")), put(20, t["path"])
    at, body = [], b""
    for w in words:  # (short strings sit one after the other; a long one starts on a 4-byte step, as rekordbox's do)
        if not w[0] & 1:
            body = body.ljust(up4(TRACK.size + len(body)) - TRACK.size, b"\0")
        at.append(TRACK.size + len(body))
        body += w
    g = lambda k: int(t.get(k) or 0)
    head = TRACK.pack(
        0x24, shift, g("link"), g("rate"), g("composer"), g("size"), g("masterId"), g("masterDb"), g("image"), g("key"),
        g("original"), g("label"), g("remixer"), g("bitrate"), g("trackNo"), g("bpm"), g("genre"), g("album"),
        g("artist"), g("id"), g("disc"), 0, g("year"), g("depth"), g("length"), g("bits"), g("color"), g("rating"),
        g("kind"), 3, *at)
    row = head + body
    return row.ljust(max(0x8C + sum(up4(len(w)) for w in words), up4(len(row))), b"\0")


def named_row(kind):
    def make(r, shift):
        name = text(r["name"])
        far = 0 if name[0] & 1 else 2  # (a long name starts on a 4-byte step, as rekordbox's do)
        if kind == ARTISTS:
            row = struct.pack("<HHIBB", 0x60, shift, r["id"], 3, 10 + far) + bytes(far) + name
            return row.ljust(up4(len(row) - far + 6), b"\0")
        if kind == ALBUMS:
            row = struct.pack("<HHIIIIBB", 0x80, shift, 0, r.get("artist") or 0, r["id"], 0, 3, 22 + far) + bytes(far) + name
            return row.ljust(up4(len(row) - far + 6), b"\0")
        if kind == KEYS:
            row = struct.pack("<II", r["id"], r["id"]) + name
        else:  # genres, labels, artwork: an id and a name (artwork: its path)
            row = struct.pack("<I", r["id"]) + name
        return row.ljust(up4(len(row)), b"\0")
    return make


def tree_row(r, shift):
    row = struct.pack("<5I", r["parent"], 0, r["seq"], r["id"], 1 if r["folder"] else 0) + text(r["name"])
    return row.ljust(up4(len(row)), b"\0")


def entry_row(r, shift):
    return struct.pack("<3I", r["n"], r["track"], r["list"])


MAKE = {TRACKS: track_row, TREE: tree_row, ENTRIES: entry_row,
        **{k: named_row(k) for k in (GENRES, ARTISTS, ALBUMS, LABELS, KEYS, ARTWORK)}}


class Pdb:
    """export.pdb held in memory. Reading checks the layout strictly; writing happens here only."""

    def __init__(self, data):
        self.d = d = bytearray(data)
        if len(d) < PAGE * 2 or len(d) % PAGE or self.u32(0) or self.u32(4) != PAGE:
            raise Bad("not a rekordbox library this code knows")
        self.count = self.u32(8)
        if not 9 <= self.count <= 64:
            raise Bad("its table list is not as expected")
        self.touched, self.new = {}, set()  # page -> the row slots written in this run
        self.tables = {}
        for i in range(self.count):
            kind, empty, first, last = struct.unpack_from("<4I", d, 0x1C + 16 * i)
            if kind in self.tables:
                raise Bad("a table is listed twice")
            self.tables[kind] = {"at": 0x1C + 16 * i, "empty": empty, "first": first, "last": last}
        self.chains = {k: self.chain(k) for k in self.tables}

    u16 = lambda self, o: struct.unpack_from("<H", self.d, o)[0]
    u32 = lambda self, o: struct.unpack_from("<I", self.d, o)[0]
    w16 = lambda self, o, v: struct.pack_into("<H", self.d, o, v)
    w32 = lambda self, o, v: struct.pack_into("<I", self.d, o, v)
    pages = property(lambda self: len(self.d) // PAGE)

    def chain(self, kind):
        """The table's data pages in order, each checked: its type, its counts and that its sizes add up."""
        t, out, seen = self.tables[kind], [], set()
        pg = t["first"]
        while True:
            b = pg * PAGE
            if pg in seen or not 0 < pg < self.pages or self.u32(b + 4) != pg or self.u32(b + 8) != kind:
                raise Bad(f"table {kind}'s pages don't link up as expected")
            seen.add(pg)
            flags = self.d[b + 0x1B]
            if not flags & 0x40:
                n, live = self.counts(pg)
                if flags not in (0x24, 0x34) or self.u16(b + 0x1C) + self.u16(b + 0x1E) + self.index(n) != ROOM \
                        or live != sum(1 for _, _, on in self.slots(pg) if on):
                    raise Bad(f"page {pg}'s sizes don't add up")
                out.append(pg)
            elif pg != t["first"]:
                raise Bad(f"table {kind} has a page of a kind not seen before")
            if pg == t["last"]:
                break
            pg = self.u32(b + 0x0C)
        if self.u32(t["last"] * PAGE + 0x0C) != t["empty"] or self.d[t["first"] * PAGE + 0x1B] != 0x64:
            raise Bad(f"table {kind}'s spare page is not where expected")
        return out

    def counts(self, pg):
        v = self.u32(pg * PAGE + 0x18) & 0xFFFFFF
        return v & 0x1FFF, v >> 13

    @staticmethod
    def index(n):
        return 2 * n + 4 * ((n + 15) // 16)

    def slots(self, pg):
        """(row number, where its bytes start, switched on?) for every slot of a data page."""
        b, n = pg * PAGE, self.counts(pg)[0]
        used = self.u16(b + 0x1E)
        for i in range(n):
            end = b + PAGE - (i // 16) * 0x24
            off = self.u16(end - 6 - 2 * (i % 16))
            if off >= used or off % 4:
                raise Bad(f"page {pg} has a row outside its own space")
            yield i, b + HEAP + off, bool(self.u16(end - 4) >> (i % 16) & 1)

    def size(self, pg, at):
        """How many bytes the slot starting at `at` has (up to the next row, or the top of the heap)."""
        b = pg * PAGE
        after = [o for _, o, _ in self.slots(pg) if o > at]
        return (min(after) if after else b + HEAP + self.u16(b + 0x1E)) - at

    def rows(self, kind, live=True):
        for pg in self.chains[kind]:
            for i, at, on in self.slots(pg):
                if on or not live:
                    yield pg, i, at

    # ---- writing ----

    def mark(self, pg, i=None):
        self.touched.setdefault(pg, set())
        if i is not None:
            self.touched[pg].add(i)

    def drop(self, pg, i):
        """Switch a row off the way rekordbox does: its bytes stay, its slot is no longer counted."""
        b = pg * PAGE
        end = b + PAGE - (i // 16) * 0x24
        bits = self.u16(end - 4)
        if not bits >> (i % 16) & 1:
            raise Bad("a row to take out is already out")
        self.w16(end - 4, bits & ~(1 << (i % 16)))
        n, live = self.counts(pg)
        self.d[b + 0x18:b + 0x1B] = struct.pack("<I", n | (live - 1) << 13)[:3]
        self.d[b + 0x1B] = 0x34
        self.mark(pg)

    def rewrite(self, pg, i, at, row):
        self.d[at:at + len(row)] = row
        self.mark(pg, i)

    def add(self, kind, make):
        """A new row at the end of the table; returns (page, row number)."""
        t = self.tables[kind]
        size = len(make(0))
        pg = t["last"] if self.chains[kind] else None
        if pg is not None:
            b = pg * PAGE
            n = self.counts(pg)[0]
            if self.u16(b + 0x1C) < size + 2 + (4 if n % 16 == 0 else 0) or n >= 0x1FFF - 1:
                pg = None
        if pg is None:
            pg = self.page(kind)
        b = pg * PAGE
        n, live = self.counts(pg)
        used, free = self.u16(b + 0x1E), self.u16(b + 0x1C)
        if free < size + 2 + (4 if n % 16 == 0 else 0):  # (a path far longer than any disk allows)
            raise Bad("a row is too long to fit in the older library")
        row = make(0x20 * n & 0xFFFF)
        self.d[b + HEAP + used:b + HEAP + used + size] = row
        end = b + PAGE - (n // 16) * 0x24
        if n % 16 == 0:
            self.d[end - 4:end] = b"\0\0\0\0"
        self.w16(end - 6 - 2 * (n % 16), used)
        self.w16(end - 4, self.u16(end - 4) | 1 << (n % 16))
        self.d[b + 0x18:b + 0x1B] = struct.pack("<I", (n + 1) | (live + 1) << 13)[:3]
        self.w16(b + 0x1C, free - size - 2 - (4 if n % 16 == 0 else 0))
        self.w16(b + 0x1E, used + size)
        self.mark(pg, n)
        return pg, n

    def page(self, kind):
        """The table's spare page becomes its new last data page (rekordbox set it aside for exactly this)."""
        t = self.tables[kind]
        pg, spare = t["empty"], self.u32(0x0C)
        if pg >= self.pages:
            self.d.extend(bytes((pg + 1 - self.pages) * PAGE))
        b = pg * PAGE
        if any(self.d[b:b + PAGE]) or pg in self.new or spare <= pg:
            raise Bad(f"table {kind}'s spare page is already in use")
        struct.pack_into("<4I", self.d, b, 0, pg, kind, spare)
        self.d[b + 0x1B] = 0x24
        self.w16(b + 0x1C, ROOM)
        if not self.chains[kind]:  # the table's very first row: its index page now names its first data page
            first = t["first"] * PAGE
            if self.u32(first + 0x2C) != 0x03FFFFFF or self.u32(first + 0x0C) != pg:
                raise Bad(f"table {kind}'s index page is not as expected")
            self.w32(first + 0x2C, pg)
            self.mark(t["first"])
        t["empty"], t["last"] = spare, pg
        self.w32(0x0C, spare + 1)
        struct.pack_into("<3I", self.d, t["at"] + 4, spare, t["first"], pg)
        self.chains[kind].append(pg)
        self.new.add(pg)
        self.mark(pg)
        return pg

    def done(self):
        """Stamp what was written (page numbers of the write, which rows it wrote) and return the bytes."""
        seq = self.u32(0x14)
        for pg, wrote in self.touched.items():
            b = pg * PAGE
            self.w32(b + 0x10, seq + 1)
            if self.d[b + 0x1B] & 0x40:
                continue
            n = self.counts(pg)[0]
            for g in range((n + 15) // 16):
                end = b + PAGE - g * 0x24
                self.w16(end - 2, sum(1 << (i % 16) for i in wrote if i // 16 == g))
            self.w16(b + 0x20, len(wrote) if wrote else NONE)
            self.w16(b + 0x22, min(wrote) if wrote else NONE)
        if self.touched:
            self.w32(0x14, seq + 2)
        return bytes(self.d)


# ---- reading what is there ----

def tracks(p):
    """Every live track row: (page, row number, where, id, path)."""
    for pg, i, at in p.rows(TRACKS):
        if p.u16(at) != 0x24:
            raise Bad("a track row of a kind not seen before")
        yield pg, i, at, p.u32(at + 0x48), nfc(read(p.d, at + p.u16(at + 0x5E + 40))[0])


def ids(p, kind):
    """id -> (page, row number, where, name) for a table of named things."""
    out = {}
    for pg, i, at in p.rows(kind):
        if kind == ARTISTS:
            if p.u16(at) != 0x60:
                raise Bad("an artist row of a kind not seen before")
            key, name = p.u32(at + 4), at + p.d[at + 9]
        elif kind == ALBUMS:
            if p.u16(at) != 0x80:
                raise Bad("an album row of a kind not seen before")
            key, name = p.u32(at + 12), at + p.d[at + 21]
        elif kind == KEYS:
            key, name = p.u32(at), at + 8
        else:
            key, name = p.u32(at), at + 4
        out[key] = (pg, i, at, nfc(read(p.d, name)[0]))
    return out


def tree(p):
    """id -> {parent, seq, folder, name, page, row, at} for every live playlist or folder."""
    out = {}
    for pg, i, at in p.rows(TREE):
        parent, _, seq, key, folder = struct.unpack_from("<5I", p.d, at)
        out[key] = {"parent": parent, "seq": seq, "folder": bool(folder), "name": nfc(read(p.d, at + 20)[0]),
                    "page": pg, "row": i, "at": at}
    return out


def entries(p):
    """playlist id -> [(position, track id, page, row number, where)] in the order they sit in the file."""
    out = {}
    for pg, i, at in p.rows(ENTRIES):
        n, track, pl = struct.unpack_from("<3I", p.d, at)
        out.setdefault(pl, []).append((n, track, pg, i, at))
    return out


def lists(data, folder):
    """What a player sees of The Crate in this file: [(playlist, [song paths in order])], or None when its folder
    is not in it. Used to check the two libraries against each other after every copy."""
    p = Pdb(data)
    t = tree(p)
    top = [k for k, r in t.items() if r["folder"] and r["parent"] == 0 and r["name"] == nfc(folder)]
    if not top:
        return None
    path = {key: where for _, _, _, key, where in tracks(p)}
    e = entries(p)
    kids = sorted((r["seq"], k) for k, r in t.items() if r["parent"] == top[0])
    return [(t[k]["name"], [path.get(tr, "?") for _, tr, *_ in sorted(e.get(k, []))]) for _, k in kids]


# ---- the mirror ----

def sync(data, want):
    """The file's bytes with The Crate's part brought in step with `want` (see rekordbox_usb.mirror()), and what
    was done: {"new", "changed", "gone", "lists"}. Returns (None, {}) when it is in step already."""
    p, want = Pdb(data), fitted(want)
    roots = tuple(nfc(r) for r in want["roots"])
    did = {"new": 0, "changed": 0, "gone": 0, "lists": 0}

    def put(kind, row, old=None):
        """Bring one row to `row`: kept when it is there already, rewritten in place when its slot is big
        enough, else its slot is switched off and the row goes to the end of the table."""
        make = lambda shift: MAKE[kind](row, shift)
        if old:
            pg, i, at = old
            now = make(p.u16(at + 2) if kind in (TRACKS, ARTISTS, ALBUMS) else 0)
            if bytes(p.d[at:at + len(now)]) == now:
                return False
            if len(now) <= p.size(pg, at):
                p.rewrite(pg, i, at, now)
                return True
            p.drop(pg, i)
        p.add(kind, make)
        return True

    # the things its tracks point at: added when missing, never changed (someone else's track may use them)
    for kind, key, word in ((ARTISTS, "artists", "artist"), (ALBUMS, "albums", "album"), (KEYS, "keys", "key"),
                            (GENRES, "genres", "genre"), (LABELS, "labels", "label"), (ARTWORK, "artwork", "cover")):
        have = ids(p, kind)
        for i, r in sorted(want.get(key, {}).items()):
            r = dict(r, id=i)
            if i not in have:
                put(kind, r)
            elif clip(have[i][3]) != nfc(r["name"]):
                raise Bad(f"the two libraries on the USB name {word} {i} differently "
                          f"({have[i][3]!r} and {nfc(r['name'])!r})")

    there = {key: (pg, i, at, path) for pg, i, at, key, path in tracks(p)}
    wanted = {t["id"]: t for t in want["tracks"]}
    for key, t in sorted(wanted.items()):
        old = there.get(key)
        if old and not old[3].startswith(roots):
            raise Bad(f"track {key} is someone else's in the older library ({old[3]})")
        if not nfc(t["path"]).startswith(roots):
            raise Bad(f"a song outside The Crate's folder was handed over ({t['path']})")
        if put(TRACKS, t, old[:3] if old else None):
            did["changed" if old else "new"] += 1
    for key, (pg, i, at, path) in sorted(there.items()):
        if key not in wanted and path.startswith(roots):
            p.drop(pg, i)
            did["gone"] += 1

    t, e = tree(p), entries(p)
    name = nfc(want["folder"])
    tops = [k for k, r in t.items() if r["folder"] and r["parent"] == 0 and r["name"] == name]
    mine = set(tops) | {k for k, r in t.items() if r["parent"] in tops}
    rows = {}
    if want.get("top") and want["lists"]:
        rows[want["top"]["id"]] = {"id": want["top"]["id"], "parent": 0, "seq": want["top"]["seq"], "folder": True,
                                   "name": name}
        for seq, (key, title, _) in enumerate(want["lists"]):
            rows[key] = {"id": key, "parent": want["top"]["id"], "seq": seq, "folder": False, "name": title}
    for key in rows:
        if key in t and key not in mine:
            raise Bad(f"playlist {key} is someone else's in the older library ({t[key]['name']!r})")
    for key, r in sorted(rows.items()):
        old = t.get(key)
        if put(TREE, r, (old["page"], old["row"], old["at"]) if old else None):
            did["lists"] += 1
    for key in sorted(mine - set(rows)):
        p.drop(t[key]["page"], t[key]["row"])
        did["lists"] += 1
    songs = {key: members for key, _, members in (want["lists"] if rows else [])}
    for key in sorted(mine | set(songs)):
        old, new = e.get(key, []), songs.get(key, [])
        if any(tr not in wanted for tr in new):
            raise Bad("a playlist names a song that was not handed over")
        changed = False
        for n, tr in enumerate(new, 1):
            row = {"n": n, "track": tr, "list": key}
            changed |= put(ENTRIES, row, old[n - 1][2:] if n <= len(old) else None)
        for _, _, pg, i, _ in old[len(new):]:
            p.drop(pg, i)
            changed = True
        if changed and key in rows and not did["lists"]:
            did["lists"] = 1
    if not p.touched:
        return None, {}
    return p.done(), did


def check_kept(old, new, roots, folder):
    """Proof that nothing but The Crate's part changed: every row that is not its own sits at the same place with
    the same bytes, every other table and page is untouched, and the file still reads cleanly. Raises Bad."""
    a, b = Pdb(old), Pdb(new)
    roots, folder = tuple(nfc(r) for r in roots), nfc(folder)
    if a.count != b.count or set(a.tables) != set(b.tables) or b.u32(0x14) <= max(
            b.u32(pg * PAGE + 0x10) for pg in range(1, b.pages)):
        raise Bad("the file's header came out wrong")
    for kind in a.tables:
        if kind not in MINE and (a.tables[kind] != b.tables[kind] or a.chains[kind] != b.chains[kind]):
            raise Bad(f"table {kind} was touched")
        if b.chains[kind][:len(a.chains[kind])] != a.chains[kind]:
            raise Bad(f"table {kind}'s pages changed order")
    held = {pg for kind in MINE for pg in b.chains[kind]} | {b.tables[k]["first"] for k in MINE}
    for pg in range(1, a.pages):
        if pg not in held and old[pg * PAGE:(pg + 1) * PAGE] != new[pg * PAGE:(pg + 1) * PAGE]:
            raise Bad(f"page {pg} was touched")

    def own(p):
        t = tree(p)
        tops = {k for k, r in t.items() if r["folder"] and r["parent"] == 0 and r["name"] == folder}
        pl = tops | {k for k, r in t.items() if r["parent"] in tops}
        out = {(TRACKS, pg, i) for pg, i, _, _, path in tracks(p) if path.startswith(roots)}
        out |= {(TREE, r["page"], r["row"]) for k, r in t.items() if k in pl}
        return out | {(ENTRIES, pg, i) for k, rows in entries(p).items() if k in pl for _, _, pg, i, _ in rows}
    mine_a, mine_b = own(a), own(b)
    for kind in MINE:
        after = {(pg, i): at for pg, i, at in b.rows(kind)}
        for pg, i, at in a.rows(kind):
            if (kind, pg, i) in mine_a:
                continue
            n = a.size(pg, at)
            if after.get((pg, i)) != at or (kind, pg, i) in mine_b or old[at:at + n] != new[at:at + n]:
                raise Bad(f"a row that is not The Crate's changed (table {kind}, page {pg}, row {i})")
    return True


def update(file, want, keep, check=None):
    """Bring the USB's export.pdb in step. `keep(file)` copies the file aside first and returns where (it is only
    called when something will change); `check(new bytes)` may refuse them (by raising) before anything is
    written. Returns {} when there was nothing to do, else what was done."""
    with open(file, "rb") as f:
        old = f.read()
    new, did = sync(old, want)
    if new is None:
        return {}
    check_kept(old, new, want["roots"], want["folder"])
    if sync(new, want)[0] is not None:
        raise Bad("the result did not come out in step")
    if check:
        check(new)
    keep(file)
    tmp = file + ".crate-tmp"
    with open(tmp, "wb") as f:
        f.write(new)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, file)
    return did
