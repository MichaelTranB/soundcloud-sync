# The Crate (soundcloud-sync)

Michael's personal tool: keeps a SoundCloud playlist on his Mac as real files and copies them to his DJ USB.
Not Almari work; nothing here touches Almari's repo, board or accounts.

- **Page:** http://localhost:4780 (`app.py`, standard library only, bound to 127.0.0.1). `index.html` is the main page, `dj.html` the DJ library page (`/dj`).
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
  SoundCloud length (same version). Into `From Soulseek/`; the artist's own file replaces it when it arrives.
  Download-only. Sign-in: `soulseek-login.sh` once (Keychain `soundcloud-sync-soulseek`).
- **The right-song check (`soulseek.py` `judge`):** sockseek only sees what the other person's computer says about
  a file, so every file is checked again once it's here: its real length against the playlist's, the song named
  inside it, a remix by someone else, the same size as a file thrown back before. A wrong one is thrown back: into
  the Trash (never deleted), back on the to-get list, remembered in `soulseek-wrong.tsv` so that file and that
  person are never taken again (`--banned-users`); three wrong files in a row and the track rests 30 days. The page
  has "Wrong or bad file" on every Soulseek song for what the check can't hear (a bad copy); a file he marks is
  looked for again at once (`.soulseek-again`, `soulseek-now.sh`: the Soulseek step alone, one at a time with a sync).
- **Safety check (`safety.py`):** every file in the music folder must be real audio: an audio name, that type's own
  first bytes, opened by `afinfo`, and clean in ClamAV (Homebrew's, else `clamav.sh` unpacks Cisco's signed pkg into `~/.local/share/clamav` with wrappers in `~/.local/bin`; `freshclam` daily from `sync.sh`).
  Anything else goes to `Quarantine/` beside the app with its run permission removed. Runs after Soulseek (before a
  track counts as got), at the end of every sync, and before a USB copy. Never loosen it.
- **`usb.sh`:** adds new files to the chosen USB after every sync and whenever a drive is mounted, only those on
  the safety check's list (`safety-ok.tsv`). Never deletes. When new tracks land it ejects the USB and shows a Mac
  notice (off when `usb-keep.txt` exists; the page's switch). An original the safety check blocks is added to
  `blocked-originals.txt` so it counts as not got.
- **DJ library (`dj.py`, page `/dj`):** after every sync and USB copy, every safety-checked track gets tempo and key
  (`dj_analyze.py`: Essentia, cached in `dj-analysis.json`) and its genres (`genres.py`: his pick in `genres.json`
  wins, then the file's tag, SoundCloud's genre, what it sounds like, SoundCloud's tags, a genre word in the title;
  else "No genre yet"), and is
  written into the Engine DJ library on the USB (`engine.py`, plain sqlite3: Denon Prime and other Engine OS decks)
  and rekordbox on the Mac (`rekordbox.py`, pyrekordbox; only while rekordbox is closed). A song can have several
  genres: the first is the decks' Genre column, and it sits in every one of its genre playlists. Both libraries get
  one folder, "The Crate" (All songs, Newest 50, the SoundCloud playlist, one list per genre); nothing outside that
  folder is read or changed, no track is ever deleted, music files are never edited, the decks' own analysis, cues
  and grids are never touched, and the library file is copied to `dj-backups/` before every change (last 20 kept).
  New rows are "not analysed", so the deck draws its own grid and waveform on first load. Problems land in `dj.log`
  with the word PROBLEM and show on the page.
- **Recognising songs by their sound (`recognise.py`):** as MusicBrainz Picard does: a Chromaprint fingerprint (from
  Essentia) is looked up on AcoustID, and MusicBrainz names the recording and its genres (`recognised.json`). Used
  for genres, and to flag (never throw back by itself) a Soulseek file that sounds like another song: flips and
  bootlegs are often not in the database. Needs an AcoustID application key: `acoustid-key.txt` (saved from the DJ
  page, mode 600, never sent back to the page) or `KEY`, the one the app ships with; without a key nothing runs.
  Only the fingerprint and the length leave the Mac, never file names; one question at a time, inside both
  services' limits. Standard library only at import (Essentia only when it runs, in the analyser's Python).
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
