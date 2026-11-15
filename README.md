# The Crate

Keeps a SoundCloud playlist on your Mac as real, top-quality music files, and puts them on your DJ USB by itself.
Free sources come first. Everything runs on your own Mac; no account with us, nothing to pay.

## Install (Mac)

Open **Terminal** (press Cmd+Space, type Terminal, press Return), paste this line, press Return:

```bash
curl -fsSL https://raw.githubusercontent.com/MichaelTranB/soundcloud-sync/main/get.sh | zsh
```

- If your Mac asks to install Apple's command line tools, click **Install**, wait, then paste the line again.
- When it's done, The Crate opens in your browser (http://localhost:4780). It's also in **Applications**.
- Paste the same line again any time to update.

## First use (about 2 minutes)

1. **Playlist:** paste your SoundCloud playlist link on the page.
2. **SoundCloud sign-in:** be signed in to soundcloud.com in Chrome (or Safari). The Crate borrows that sign-in, so
   it can fetch the artists' original files.
3. **One switch:** a Finder window and System Settings open on *Full Disk Access*. Drag **Crate Helper** into the
   list and switch it on. (macOS needs this before any app can read your browser's sign-in.)
4. **Soulseek (optional, for tracks the artist didn't make free):** sign in on the page with a free Soulseek
   account. The password is kept in your Mac's Keychain.
5. **USB:** plug your DJ USB in and pick it on the page. That's it.

## Where tracks come from, best first

1. The artist's **original upload** on SoundCloud, when downloads are on.
2. The artist's **free download link** when it points straight to a file (Dropbox, Google Drive, pixeldrain...).
3. **Soulseek:** lossless first, then MP3 at a real 320 kbps, same title and same length as the SoundCloud track.
4. **Downloads folder:** got one yourself? A free gate (Hypeddit, Laylo), Bandcamp "name your price", or bought
   it (Beatport, Bandcamp, Traxsource...)? Just leave the file in Downloads. The Crate picks it up within a minute
   if it's on your list, top quality only.
5. Anything still missing is listed on the page (and in *To Buy.txt* on the USB) with links to get it.

Never YouTube rips or recorded streams: low quality.

## The USB

- New tracks are copied after every sync (nightly at 3:10am, or **Sync Now**) and the moment the USB is plugged in.
- When new tracks land, it ejects the USB and tells you it's safe to unplug. (Turn that off on the page if you'd
  rather keep it plugged in.)
- It only adds files. Nothing on the USB is ever deleted or overwritten.

## Safety

Every file is checked before it counts or goes on the USB: it must be real audio (name, contents, and macOS can
play it), and, if you have Homebrew, clean in the free ClamAV virus scanner. Anything else goes to *Quarantine*
and can't run.

## Uninstall

```bash
zsh ~/TheCrate/uninstall.sh
```

Your music stays in Music > SoundCloud Sync.

Windows: not yet.
