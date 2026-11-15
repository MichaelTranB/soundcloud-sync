# The Crate

Keeps a SoundCloud, Apple Music or Spotify playlist on your Mac as real, top-quality music files, and puts them on
your DJ USB by itself.
Free sources come first. Everything runs on your own Mac; no account with us, nothing to pay.

## Install (Mac, about 10 minutes)

1. Open **Terminal**: press **Cmd + Space**, type `Terminal`, press **Return**.
2. Copy this whole line, paste it into Terminal (**Cmd + V**), press **Return**:

```bash
curl -fsSL https://raw.githubusercontent.com/MichaelTranB/soundcloud-sync/main/get.sh | zsh
```

3. If a window asks to install Apple's **command line tools**, click **Install**, wait until it's done, then paste
   the same line again.
4. Wait while it sets everything up by itself (the music downloaders and a free virus scanner). No password needed.
5. The Crate opens in your browser. Its **Get started** list walks you through the rest, one button per step.

Paste the same line again any time to update. The Crate is also in your **Applications** folder.

## Get started (on the page)

The page ticks off each step by itself:

1. **Add a playlist:** in SoundCloud, Spotify or Apple Music, open the playlist, **Share > Copy link**, and paste it.
   (Spotify and Apple Music: a public playlist. Spotify shows The Crate its first 100 songs.)
2. **Let The Crate use your SoundCloud sign-in** (SoundCloud playlists only): the button opens System Settings at
   *Full Disk Access* and a Finder window. Drag **Crate Helper** into the list and switch it on. macOS asks this of
   any app that reads a browser's sign-in; nothing is sent anywhere.
3. **Sign in to SoundCloud** in Chrome (or the browser you picked), as usual. Artists who allow downloads give their
   original WAV/FLAC only to signed-in people.
4. **Soulseek (recommended):** finds what SoundCloud, Spotify and Apple Music won't give you. Make up a new name
   and a password you use nowhere else; Soulseek creates the account the first time. Kept in your Mac's Keychain.
5. **Virus scanner:** installed already; if not, the button installs it.
6. **USB (optional):** plug in your DJ USB and pick it.
7. **Sync Now.** After that it runs by itself every night at 3:10 while the Mac is on.

**Stuck?** On the page, tap **Copy a message for ChatGPT or Claude** and paste it into either one: it says where
you are, and they'll walk you through it. Or send them this page's link and say which step.

## Where tracks come from, best first

1. The artist's **original upload** on SoundCloud, when downloads are on.
2. The artist's **free download link** when it points straight to a file (Dropbox, Google Drive, pixeldrain...).
3. **Soulseek:** lossless first, then MP3 at a real 320 kbps, same title and same length as the SoundCloud track.
4. **Downloads folder:** got one yourself? A free gate (Hypeddit, Laylo), Bandcamp "name your price", or bought
   it (Beatport, Bandcamp, Traxsource...)? Just leave the file in Downloads. The Crate picks it up within a minute
   if it's on your list, top quality only.
5. Anything still missing is listed on the page (and in *To Buy.txt* on the USB) with links to get it.

Spotify and Apple Music only stream, so their songs come from Soulseek, Downloads or a shop (steps 3 to 5).
Never YouTube rips or recorded streams: low quality.

## The USB

- New tracks are copied after every sync (nightly at 3:10am, or **Sync Now**) and the moment the USB is plugged in.
- When new tracks land, it ejects the USB and tells you it's safe to unplug. (Turn that off on the page if you'd
  rather keep it plugged in.)
- It only adds files. Nothing on the USB is ever deleted or overwritten.

## Safety

Every file is checked before it counts or goes on the USB: it must be real audio (name, contents, and macOS can
play it) and clean in the free ClamAV virus scanner (installed by The Crate: Cisco's own signed package, checked
before it's used, kept in your home folder; its virus list updates daily). Anything else goes to *Quarantine* and
can't run.

## Uninstall

```bash
zsh ~/TheCrate/uninstall.sh
```

Your music stays in Music > SoundCloud Sync.

Mac only (it uses macOS's own tools for the background jobs, audio checks and Keychain). Windows: not yet.
