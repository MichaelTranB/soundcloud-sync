# The Crate (soundcloud-sync)

Michael's personal tool: keeps a SoundCloud playlist on his Mac as real files and copies them to his DJ USB.
Not Almari work; nothing here touches Almari's repo, board or accounts.

- **Page:** http://localhost:4780 (`app.py`, standard library only, bound to 127.0.0.1). `index.html` is the whole interface.
- **`sync.sh`:** downloads the artist's ORIGINAL file for every playlist track with downloads switched on; the rest
  go to `to-buy.tsv` (and `To Buy.txt` in the music folder). Nightly at 3:10am, or Sync Now on the page.
- **`usb.sh`:** adds new files to the chosen USB after every sync and whenever a drive is mounted. Never deletes.
- **`install.sh`:** (re)creates the three launchd jobs. Run it after moving the folder.
- **Music lives in** `~/Music/SoundCloud Sync/`. State (`playlist.txt`, `usb.txt`, `archive.txt`, logs) is git-ignored.
- **Sign-in:** the SoundCloud token is read from the Keychain (`~/work-os/bin/api-key get soundcloud`), never a file.

## The one rule
Only files the artist or label offers: SoundCloud's own download button, the artist's free-download link, or a shop.
No recording the Go+ stream and no file-sharing networks (Soulseek and the like): a new source is added only if the
rights holder is the one giving the file away.
