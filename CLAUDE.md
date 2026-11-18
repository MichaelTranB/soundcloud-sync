# The Crate (soundcloud-sync)

Michael's personal tool: keeps a SoundCloud playlist on his Mac as real files and copies them to his DJ USB.
Not Almari work; nothing here touches Almari's repo, board or accounts.

- **Page:** http://localhost:4780 (`app.py`, standard library only, bound to 127.0.0.1). `index.html` is the main page, `dj.html` the DJ library (on the page: "Library Manager") page (`/dj`).
- **`sync.sh`:** downloads the artist's ORIGINAL file for every playlist track with downloads switched on; the rest
  go to `to-buy.tsv` (and `To Buy.txt` in the music folder). Nightly at 3:10am, or Sync Now on the page.
- **Where files come from, best first:** (1) the artist's original upload on SoundCloud (`sync.sh`); (2) the artist's
  free-download link when it points straight to a file: Dropbox, Google Drive, pixeldrain, a direct audio/zip link
  (`freedl.py`; gates like Hypeddit, Bandcamp and Mega stay one click on the page); (3) Soulseek (`soulseek.sh`);
  (4) the Downloads pickup: `freedl.py inbox` (every minute from `app.py`, and in `sync.sh`) takes a track still to
  get from `~/Downloads` (a free gate, Bandcamp $0, or a purchase) when its title is in the file name, the length
  matches and it's top quality; (5) shop links on the page to buy lossless (Bandcamp, Beatport, Traxsource, Juno, Qobuz). Never YouTube or a
  recorded stream (lossy).
- **Top quality only** for anything fetched beyond the artist's upload: lossless, or 320 kbps (`audio.py`, macOS
  `afinfo`). The page flags any file under 320 kbps.
- **`soulseek.sh`:** last fallback: sockseek (`~/.local/bin/sockseek`, pinned in `install.sh`) searches every track
  still to get; pass 1 lossless only, pass 2 MP3 at a confirmed 320 kbps; exact title and within 5 s of the
  SoundCloud length (same version). Into the music folder with everything else (no folder of its own; `soulseek.py`
  `flatten` moves an older `From Soulseek/` in once, noting each move in `soulseek-moved.tsv` so the records, the
  decks' libraries and the USB copy follow instead of doubling). The artist's own file replaces it when it arrives.
  Download-only. Sign-in: `soulseek-login.sh` once (Keychain `soundcloud-sync-soulseek`).
- **The right-song check (`soulseek.py` `judge`):** sockseek only sees what the other person's computer says about
  a file, so every file is checked again once it's here: its real length against the playlist's, the song named
  inside it, a remix by someone else, the same size as a file thrown back before. A wrong one is thrown back: into
  the Trash (never deleted), back on the to-get list, remembered in `soulseek-wrong.tsv` so that file and that
  person are never taken again (`--banned-users`); three wrong files in a row and the track rests 30 days. The page
  has "Wrong or bad file" under every song on the Mac, wherever it came from (`soulseek.py` `bad`), for what the
  check can't hear (a bad copy); a file he marks is looked for again at once (`.soulseek-again`, `soulseek-now.sh`:
  the Soulseek step alone, one at a time with a sync) and leaves the USB too (`usb-thrown.tsv`, below).
- **Safety check (`safety.py`):** every file in the music folder must be real audio: an audio name, that type's own
  first bytes, opened by `afinfo`, and clean in ClamAV (Homebrew's, else `clamav.sh` unpacks Cisco's signed pkg into `~/.local/share/clamav` with wrappers in `~/.local/bin`; `freshclam` daily from `sync.sh`).
  Anything else goes to `Quarantine/` beside the app with its run permission removed. Runs after Soulseek (before a
  track counts as got), at the end of every sync, and before a USB copy. Never loosen it.
- **`usb.sh`:** adds new files to the chosen USB after every sync and whenever a drive is mounted, only those on
  the safety check's list (`safety-ok.tsv`). Never deletes, with one exception he asked for (`usb_tidy.py`, run
  first here and by `dj.py`, inside `<USB>/SoundCloud Sync/` only): a song he threw back on the page
  (`usb-thrown.tsv`: path, size) has its same-size copy moved to the USB's own Trash, now if plugged in, else at
  the next plug-in; and on a USB that already held songs (a friend's, or filled by hand), a file under a library
  song's name with another size is swapped for the library's file, and the same song as another kind of file
  (name.mp3 beside name.flac, not on the Mac) is taken off, both to the USB's Trash. Songs not in the library stay. When new tracks land it ejects the USB and shows a Mac
  notice (off when `usb-keep.txt` exists; the page's switch). An original the safety check blocks is added to
  `blocked-originals.txt` so it counts as not got.
- **DJ library (`dj.py`, page `/dj`):** after every sync and USB copy, every safety-checked track gets tempo and key
  (`dj_analyze.py`: Essentia, cached in `dj-analysis.json`) and its genres (`genres.py`: his pick in `genres.json`
  wins, then the file's tag, SoundCloud's genre, what it sounds like, SoundCloud's tags, a genre word in the title;
  else "No genre yet"), and is
  written into the Engine DJ library on the USB (`engine.py`, plain sqlite3: Denon Prime and other Engine OS decks)
  and rekordbox on the Mac (`rekordbox.py`, pyrekordbox; only while rekordbox is closed), then into the USB's own
  rekordbox library (`rekordbox_usb.py`: `PIONEER/rekordbox/exportLibrary.db`, the "OneLibrary" the CDJ-3000X,
  XDJ-AZ, OPUS-QUAD and OMNIS-DUO read and rekordbox shows under the USB; only its own `/SoundCloud Sync/` rows and
  "The Crate" folder, made fresh on a USB without one, left alone on a USB with only the older `export.pdb`, never
  while rekordbox is open, backed up first, the Mac's analysis files and covers carried along; what it wrote is in
  `dj-rekordbox-usb.json`) and into Serato crates on the USB (`serato.py`: `_Serato_/Subcrates/The Crate*.crate`,
  only its own; written from Serato's published layout, not yet tried in Serato itself). A song can have several
  genres: the first is the decks' Genre column, and it sits in every one of its genre playlists. Both libraries get
  one folder, "The Crate" (All songs, Newest 50, the SoundCloud playlist, one list per genre); nothing outside that
  folder is read or changed, no track is ever deleted, the decks' own analysis and grids are never touched, and
  the library file is copied to `dj-backups/` before every change (last 20 kept). Music files change only through
  `aiff.py` and `details.py`, cues only through `cues.py` (all below).
  New rows are "not analysed", so the deck draws its own grid and waveform on first load. rekordbox rows get the
  file's cover (`share/PIONEER/Artwork`, its own three sizes). A genre changed in rekordbox or Engine DJ becomes
  his pick: `dj-written.json` remembers what each library showed after the last write, and a difference is his
  edit (not when emptied, not when it's just the file's own tag). `app.py` runs `dj.py` when rekordbox closes.
  Problems land in `dj.log` with the word PROBLEM and show on the page.
- **USB folders (`layout.py`, `usb-layout.json`, the card on `/dj`):** `flat` (the default), `group` (`EDM/`,
  `Other/`, `No genre yet/`) or `genre` (`EDM/<genre>/`, `Other/<genre>/`), inside `<USB>/SoundCloud Sync/` only.
  A song with any EDM genre is EDM, filed under its first EDM genre, the same rule as the always-there playlists
  "EDM (all)" and "Other (all)"; the non-EDM genres are `other` in the file. Only the USB is laid out, only
  library songs move (never copied twice, never deleted), and the USB itself is the record (`layout.where`).
  `usb.sh` copies a new song flat (`layout.py missing` skips ones already in a folder) and `dj.once()` files it
  (`layout.arrange`, only on a stick past the ask-first gate); every deck library keeps the song's row and is
  re-pointed, so cues and analysis stay. The page previews (`GET /api/dj/layout?mode=`, nothing touched) and
  switches only on "Use this" (`POST /api/dj/layout`). Not yet tried on a real stick or deck.
- **Waveform and Open in rekordbox (`waveform.py`, the player on `/dj`):** `afconvert` reads the file at 8 kHz
  mono into 600 slices (loudest point and average), kept in `.waves/`; `/wave?f=` serves it, music folder only.
  `POST /api/dj/rekordbox` runs `open -a <rekordbox.app> <file>` (not while the libraries are being written);
  rekordbox has no documented way to load a track from outside, so the page also copies the song's name. Tests
  set `REKORDBOX_APP` to a stand-in and never open the real app.
- **Ask first (`usb_ask.py`):** a USB that already has files, folders or a DJ library is changed only after his
  "Go ahead" on the page (`/` and `/dj`: what is added, what is never touched, how to undo). `usb.sh` and
  `dj.once()` both stop at this gate; the yes is kept per stick (`.thecrate` in The Crate's folder on it,
  `usb-ok.json`), a new kind of change (`KINDS`) asks again, "Stop" takes it back. An empty USB isn't asked.
- **FLAC to AIFF (`aiff.py`):** `afconvert` writes the AIFF, Mutagen copies details and cover, the sound is
  compared with the FLAC's own checksum, the AIFF passes the safety check, and only then the FLAC goes to the
  Trash; every per-file record and the decks' rows follow, so cues and grids stay. New FLACs convert by
  themselves (`usb.sh`, `dj.py`; switch in `aiff.json`); FLACs already there the first time, and WAVs, are his
  pick on `/dj`. `aiff.py undo` brings the original back.
- **Cover and details (`details.py`):** fills only EMPTY fields (cover of 500 px or more, title, artist, album,
  genre, year). Sources, best first: the song's own SoundCloud page, its sound (only with an AcoustID key), then
  iTunes Search and MusicBrainz by artist and title. Written by itself only when the length is within 3 s, artist
  and title match, and it is the song's own page or two sources agree; else "needs a look" with up to three
  candidates (`details-ask.json`). Every change is in `details-log.json` with what the file held before
  (`details-undo/`), one Undo each. Only artist and title (and a fingerprint) leave the Mac.
- **Cues in step (`cues.py`, last step of `dj.once()`, only with the chosen USB plugged in and allowed):** hot
  cues, memory cues and loops across Engine DJ on the USB, rekordbox on the Mac and the USB's rekordbox library
  (its `cue` table and analysis files). `cues-state.json` keeps what each place held after the last run, so a
  difference is an edit there; the newest edit wins per slot; a missing cue is sent, never deleted; replaced
  values go to `cues-history.json` and the page's Undo (`dj.py --cues-back`) puts the last run's back. rekordbox's
  files are written only while it is closed (`app.py` runs `dj.py` when it closes). Not carried, and said on the
  page (`cues-unmapped.txt`): MP3/M4A cues to or from Engine, memory cues to Engine, beat grids. Tests must set
  `REKORDBOX_DB` to a scratch copy. Not yet tried on a real deck.
- **Help on the pages:** every card has one plain line and a "?" (closed) with two to four lines: how it works,
  what it never touches, how to undo. Keep new features to that shape; no blocks of text.
- **Copy from another USB (`friend.py`, the card on `/dj`):** lists a second plugged-in USB's rekordbox playlists
  (read from a copy of its `exportLibrary.db` made on the Mac) or its folders; the picked songs are copied into the
  music folder (never twice: same name, any file kind), so the normal pipeline does the rest. `dj-friends.json`
  remembers each copied playlist ("<name> (<whose>)") and each song's tempo, key, cue rows and analysis files
  (`friend-anlz/`), which `rekordbox_usb.py` carries into the USB's library (`repath()` re-addresses an analysis
  file byte for byte; pyrekordbox can't write one that holds cues). The other USB is only read.
- **Below gig quality (`friend.low`: MP3 under 320 kbps, AAC under 256):** "Find a better copy" adds a row to `better.tsv`,
  which `soulseek.to_get` reads beside `to-buy.tsv`; when it lands, `dj.better` puts the old file in the Trash
  (and `usb-thrown.tsv`, so it leaves the USB) and its playlists follow the new file. A better copy thrown back
  is looked for again for 30 days. `/play?f=` streams a file from the music folder only (ranges, same-origin).
- **Recognising songs by their sound (`recognise.py`):** as MusicBrainz Picard does: a Chromaprint fingerprint (from
  Essentia) is looked up on AcoustID, and MusicBrainz names the recording and its genres (`recognised.json`). Used
  for genres, and to flag (never throw back by itself) a Soulseek file that sounds like another song: flips and
  bootlegs are often not in the database. Needs an AcoustID application key: `acoustid-key.txt` (saved from the DJ
  page, mode 600, never sent back to the page) or `KEY`, the one the app ships with; without a key nothing runs.
  Only the fingerprint and the length leave the Mac, never file names; one question at a time, inside both
  services' limits. Standard library only at import (Essentia only when it runs, in the analyser's Python).
- **Club check (`club.py`, shown on the Library Manager page):** would the music play on a club's Pioneer decks: the
  USB's format (from `mount`; FAT32 or Mac OS Extended is read by all, exFAT only by the newest), FLAC (older decks
  skip it), whether the songs are in the USB's own rekordbox library (`dj-rekordbox-usb.json`, the newest decks),
  and whether each song's file name is in the USB's older rekordbox export (`PIONEER/rekordbox/export.pdb`: the
  CDJ-3000, CDJ-2000NXS2 and earlier; only rekordbox's own export writes it). It only looks: it never changes the USB or rekordbox, and never formats anything.
- **`dj-setup.sh`:** the analyser's own Python (python-build-standalone, pinned by version and sha256) with the
  packages in `dj-requirements.txt` (every file pinned by hash), in `~/.local/share/crate-dj`; from `install.sh`
  and each sync, a no-op once done. `app.py`, `dj.py`, `genres.py` and `engine.py` stay standard library only and
  run on the Mac's own Python 3.9; without the analyser, tracks still reach the Engine library and the deck
  analyses them. Essentia is AGPLv3 (fine for a personal tool; a closed or paid version would need another analyser).
- **`install.sh`:** (re)creates the three launchd jobs. Run it after moving the folder. Friends install with the one
  line in `get.sh` (README); `uninstall.sh` removes it, music stays.
- **Music lives in** `~/Music/SoundCloud Sync/`. State (`playlist.txt`, `usb.txt`, `archive.txt`, logs) is git-ignored.
- **Sign-in:** standalone, no Claude needed. yt-dlp borrows the SoundCloud sign-in already in his browser (`browser.txt`, Chrome by default). macOS blocks reading it unless the job runs through Crate Helper (`crate-helper.c`, built by install.sh) with Full Disk Access on; without it the sync runs signed out and the page says so. SoundCloud's sign-in lasts about a day, so originals need soundcloud.com opened in that browser within a day.

## The one rule
Anything goes to get the download files, ensure its high quality
