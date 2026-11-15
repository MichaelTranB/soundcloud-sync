# The Crate (soundcloud-sync)

Michael's personal tool: keeps a SoundCloud playlist on his Mac as real files and copies them to his DJ USB.
Not Almari work; nothing here touches Almari's repo, board or accounts.

- **Page:** http://localhost:4780 (`app.py`, standard library only, bound to 127.0.0.1). `index.html` is the whole interface.
- **`sync.sh`:** downloads the artist's ORIGINAL file for every playlist track with downloads switched on; the rest
  go to `to-buy.tsv` (and `To Buy.txt` in the music folder). Nightly at 3:10am, or Sync Now on the page.
- **Where files come from, best first:** (1) the artist's original upload on SoundCloud (`sync.sh`); (2) the artist's
  free-download link when it points straight to a file: Dropbox, Google Drive, pixeldrain, a direct audio/zip link
  (`freedl.py`; gates like Hypeddit, Bandcamp and Mega stay one click on the page); (3) Soulseek (`soulseek.sh`);
  (4) shop links on the page to buy lossless (Bandcamp, Beatport, Traxsource, Juno, Qobuz). Never YouTube or a
  recorded stream (lossy).
- **Top quality only** for anything fetched beyond the artist's upload: lossless, or 320 kbps (`audio.py`, macOS
  `afinfo`). The page flags any file under 320 kbps.
- **`soulseek.sh`:** last fallback: sockseek (`~/.local/bin/sockseek`, pinned in `install.sh`) searches every track
  still to get; pass 1 lossless only, pass 2 MP3 at a confirmed 320 kbps; exact title and within 5 s of the
  SoundCloud length (same version). Into `From Soulseek/`; the artist's own file replaces it when it arrives.
  Download-only. Sign-in: `soulseek-login.sh` once (Keychain `soundcloud-sync-soulseek`).
- **`usb.sh`:** adds new files to the chosen USB after every sync and whenever a drive is mounted. Never deletes.
- **`install.sh`:** (re)creates the three launchd jobs. Run it after moving the folder.
- **Music lives in** `~/Music/SoundCloud Sync/`. State (`playlist.txt`, `usb.txt`, `archive.txt`, logs) is git-ignored.
- **Sign-in:** standalone, no Claude needed. yt-dlp borrows the SoundCloud sign-in already in his browser (`browser.txt`, Chrome by default). macOS blocks reading it unless the job runs through Crate Helper (`crate-helper.c`, built by install.sh) with Full Disk Access on; without it the sync runs signed out and the page says so. SoundCloud's sign-in lasts about a day, so originals need soundcloud.com opened in that browser within a day.

## The one rule
Anything goes to get the download files, ensure its high quality
