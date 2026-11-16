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
   (Spotify and Apple Music: a public playlist. Spotify shows The Crate its first 100 songs; for the rest, click a
   song in the Spotify app, press ⌘A then ⌘C, and paste into the same box. In the web player, click the first song
   and Shift-click the last instead of ⌘A. Apple Music shows up to 300 songs.)
2. **Turn on Full Disk Access** (SoundCloud playlists only). Why: your browser keeps your SoundCloud sign-in in a
   folder macOS locks, and this switch lets The Crate use it, so you get original files without typing a SoundCloud
   password into it. The sign-in only ever goes to SoundCloud. The button opens System Settings and a Finder window:
   drag **Crate Helper** into the list and switch it on.
3. **Sign in to SoundCloud** in your web browser (Safari, Chrome, Brave, Edge or Firefox), as usual. Artists who allow downloads give their
   original WAV/FLAC only to signed-in people.
4. **Soulseek (recommended):** finds what SoundCloud, Spotify and Apple Music won't give you. Make up a new name
   and a password you use nowhere else; Soulseek creates the account the first time. Kept in your Mac's Keychain.
5. **Virus scanner:** installed already; if not, the button installs it.
6. **USB (optional):** plug in your DJ USB and pick it.
7. **Sync Now.** After that it runs by itself every day at the time under **Auto sync** (3:10am to start). Keep the Mac on and plugged in then; if it's asleep, it syncs when it wakes.

**Questions?** The **? How it works** button on the page explains where tracks come from, the quality, the
safety check and Full Disk Access.

## Where tracks come from, best first

1. The artist's **original upload** on SoundCloud, when downloads are on.
2. The artist's **free download link** when it points straight to a file (Dropbox, Google Drive, pixeldrain...).
   The Crate also reads each missing track's **Free Download button** (the link under the track on SoundCloud, often
   Hypeddit or ToneDen), which the description doesn't always repeat. Gates that ask for a follow first go in the
   **Free links** list for you to click; the file then comes in through step 4.
3. **Soulseek:** lossless first, then MP3 at a real 320 kbps, same title and same length as the SoundCloud track.
   Every file is checked again once it's on your Mac (its real length, and the song named inside it); a wrong one
   goes to the Trash and that file is never taken again. Got the wrong song or a bad copy anyway? Press **Wrong or
   bad file** under it (every song on your Mac has the button, wherever it came from): The Crate throws it back,
   takes it off your USB too, and starts looking for another copy right away. Soulseek songs sit in the music
   folder with everything else, not in a folder of their own.
4. **Downloads folder:** got one yourself? A free gate (Hypeddit, Laylo), Bandcamp "name your price", or bought
   it (Beatport, Bandcamp, Traxsource...)? Just leave the file in Downloads. The Crate picks it up within a minute
   if it's on your list, top quality only.
5. Anything still missing is listed on the page (and in *To Buy.txt* in the music folder on the Mac; only music goes on the USB) with links to get it.

Spotify and Apple Music only stream, so their songs come from Soulseek, Downloads or a shop (steps 3 to 5).
Never YouTube rips or recorded streams: low quality.

## The USB

- New tracks are copied after every sync (daily at your **Auto sync** time, or **Sync Now**) and the moment the USB is plugged in.
- When new tracks land, it tells you. Tick **Eject the USB…** on the page to have it ejected then too, so you can
  just pull it out (off unless you tick it; never while a sync is still adding tracks).
- It only adds files. Nothing on the USB is ever deleted or overwritten. The one exception: a song you threw back
  with **Wrong or bad file** leaves the USB as well (right away if it's plugged in, else the next time you plug it
  in). It goes to the USB's own Trash, so you can still take it back until you empty the Trash; only The Crate's
  own folder on the USB is ever touched.

## Your DJ decks (Engine DJ and rekordbox)

Open **DJ library** on the page. Every song is listed with its tempo, key and genres, and The Crate puts them
straight into your decks' libraries, with no dragging and no clicks:

- **Denon Prime and other Engine DJ decks:** the songs are added to the Engine library on your USB (plug the USB
  into the deck once first, so it makes its library). On the deck: *Playlists → The Crate*.
- **rekordbox (Pioneer DDJ controllers, and its own USB export for CDJs):** the songs are added to rekordbox on
  this Mac, in a playlist folder called *The Crate*, with their cover when the file carries one. This happens
  while rekordbox is closed; if it's open, it catches up by itself the moment you close it.
- **Genres:** each song is sorted by what's written on it (the file, SoundCloud's genre and tags). Songs nothing
  describes land in *No genre yet*: tap their genre on the page. Wrong genre? Tap **Edit**. A song can have several
  genres; it shows in each one's playlist, and the first is the Genre column on the decks. Your picks always win,
  and you can add or remove genres from the list. Change a song's genre in rekordbox (or in Engine DJ on the USB)
  instead, and that becomes your pick on the page too.
- **Recognise songs by their sound (optional):** The Crate can listen to each song and look it up in MusicBrainz,
  the way the free app MusicBrainz Picard does. It fills in genres for songs nothing describes, and flags a
  Soulseek file that sounds like a different song. It needs a free AcoustID key, once: the page has the link and
  a box to paste it in. Only a fingerprint of the sound and the song's length leave your Mac, never file names.
  Remixes, flips and bootlegs are often not in that database; those stay as they are.
- **What it never touches:** your own playlists, cues, loops and beat grids, and the music files themselves. No
  song is ever removed from a library. A copy of the library is kept before every change (*dj-backups* in the app
  folder, the last 20).
- The first time you load a song, the deck (or rekordbox) draws its own beat grid and waveform, as for any new file.

Tempo and key come from a free listening tool (Essentia) that The Crate sets up by itself the first time (about
a 100 MB download, kept in your home folder). Until then the songs still reach your decks, which analyse them on load.

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
