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
   **Your Spotify Liked Songs** (optional, any size): in Spotify open Liked Songs, click the newest song, Shift-click
   the oldest you still want, press ⌘C and paste into **Spotify Liked Songs**. Each sync looks for the next batch on
   Soulseek: EDM first, newest first, everything else after. It only takes what fits and always leaves 10 GB free on
   your Mac (the page says when it's paused for space). No Spotify sign-in, nothing changes in Spotify.
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
- **A USB that already has things on it is asked about first.** The page shows what would be added, what is never
  touched and how to undo, with **Go ahead** or **Not now**. Until you say so, nothing on it is changed. The yes is
  remembered for that stick (**Stop** on the Library Manager page takes it back); an empty USB needs no asking.
- It only adds files. Nothing on the USB is ever deleted or overwritten. The one exception: a song you threw back
  with **Wrong or bad file** leaves the USB as well (right away if it's plugged in, else the next time you plug it
  in). It goes to the USB's own Trash, so you can still take it back until you empty the Trash; only The Crate's
  own folder on the USB is ever touched.

## Your DJ decks (Engine DJ, rekordbox and Serato)

Open **Library Manager** on the page. Every song is listed with its tempo, key and genres, and The Crate puts them
straight into your decks' libraries, with no dragging and no clicks:

- **Denon Prime and other Engine DJ decks:** the songs are added to the Engine library on your USB (plug the USB
  into the deck once first, so it makes its library). On the deck: *Playlists → The Crate*.
- **rekordbox (Pioneer DDJ controllers, and its own USB export for CDJs):** the songs are added to rekordbox on
  this Mac, in a playlist folder called *The Crate*, with their cover when the file carries one. This happens
  while rekordbox is closed; if it's open, it catches up by itself the moment you close it.
- **rekordbox on the USB itself (the newest club decks):** the same songs and playlists are written into the USB's
  own rekordbox library, so they show under the USB in rekordbox (*Devices*, under the USB: *OneLibrary*) and on
  the CDJ-3000X, XDJ-AZ, OPUS-QUAD and OMNIS-DUO, with the beat grids and waveforms rekordbox already made. A USB
  without a rekordbox library gets one; a USB that someone else's rekordbox filled keeps everything of theirs.
  Older club decks (CDJ-3000, CDJ-2000NXS2 and before) read an older kind of list that only rekordbox itself can
  write: before a gig on those, export once from rekordbox (drag your playlists onto the USB under *Devices*).
- **Serato:** the USB also gets Serato crates (*The Crate*, with a crate per playlist inside it), which Serato
  shows when the USB is plugged in. They point at the same files; nothing is copied.
- **One folder, each song once:** all of The Crate's music sits in The Crate's own folder on the USB (*SoundCloud Sync* at its top,
  or inside a folder you already keep music in: Library Manager > USB folders > Change; only that one folder moves, and
  the decks' lists follow with their cues), and
  every library above points at those same files. A USB that already had some of the songs (a friend's, or one
  filled by hand) gets no doubles: a file that is another download of a song is swapped for your library's, the
  same song as another kind of file is taken off, and the songs you threw back leave it too. Those go to the
  USB's own Trash, never deleted, and songs that aren't from your library are left alone.
- **Copy from another USB:** plug a friend's USB in beside yours and the page lists its rekordbox playlists (or
  its folders). Tick the ones you want and press **Copy to my library**. The songs land in your music folder, so
  they get everything your own songs get (safety check, tempo, key, genres, every deck library, your USB), each
  playlist keeps its name with whose it was, and a song you already have is never copied twice. Hot cues and beat
  grids set in rekordbox come along (USB to USB). The other USB is only ever read.
- **USB folders:** pick how the songs sit inside that folder: **One folder** (as it always was), **EDM and
  Other**, or **By genre** (*EDM/Dubstep*, *Other/Hip Hop*, and *No genre yet*). A song with any EDM genre counts
  as EDM and sits under its first EDM genre; which genres aren't EDM is yours to change. The page shows what
  would move and asks before anything does; after that new songs are filed by themselves, and a song whose genre
  changes moves at the next update. Playlists and cues follow, each song stays on the USB once, nothing is
  deleted, and nothing outside The Crate's own folder is touched. **One folder** puts every song back. Only the
  USB is laid out; the music folder on the Mac stays as it is.
- **Spotify Liked Songs:** they keep their own folder (on the Mac and on the USB) and their own playlist on
  every deck, newest like first. They stay out of the genre playlists and folders until you file one: open the
  **Spotify Liked Songs** list and press **Add to playlist**. It joins that genre's playlist and stays on the
  Liked list and in its folder. A song you move into another folder of your music folder yourself is followed
  the same way: its tempo, key, genres and cues go along, and it moves on the USB instead of being copied twice.
- **EDM (all) and Other (all):** two playlists that are always there: every song with an EDM genre in one, the
  rest in the other, beside the playlist for each genre.
- **Below gig quality:** MP3s under 320 kbps and M4As under 256 are marked. On each: **Find a better copy** (it joins the
  Soulseek search at once, and takes the old file's place in its playlists when it lands; the old one goes to the
  Trash) or **Throw away**.
- **AIFF for club decks:** older club decks skip FLAC, so a FLAC that arrives becomes an AIFF by itself: the very
  same sound (compared sample for sample), with its details and cover. Only once the AIFF is checked does the
  FLAC go to the Trash, so no song is ever there twice, and its playlists and cues follow the new file. FLACs you
  already had, and WAVs, are your pick in the song list. **Undo** brings the original back.
- **32-bit songs:** no club deck plays a 32-bit file, so its row says so and offers **Make a 24-bit copy**: a
  24-bit AIFF with no difference you can hear, the original in the Trash, **Undo** to bring it back. It is never
  done by itself, because the copy isn't bit for bit the same file. A 32-bit FLAC needs `ffmpeg` on the Mac to be
  read (The Crate doesn't install it); a song above 96 kHz is only pointed out.
- **Cover and details:** a song missing its cover, title, artist, album, genre or year gets them filled in. Only
  empty fields are filled; nothing already there is changed. It writes by itself only when the song's own
  SoundCloud page says so or two sources agree, and the length matches within 3 seconds; anything less sure is
  shown as *needs a look* with up to three choices. Every change is listed with an **Undo**.
- **Cues in step:** hot cues, memory cues and saved loops you set in one place reach the others at the next
  update: Engine DJ on the USB (Prime 4), rekordbox on this Mac, and the USB's rekordbox library (where club
  decks save the cues you set on them). The newest edit of a cue wins, no cue is ever deleted, and **Undo** on
  the Cues line puts back what the last update replaced. rekordbox's side is written when rekordbox is closed.
  Not carried: MP3 and M4A cues between rekordbox and Engine DJ (the two start those files at slightly different
  points), memory cues to the Prime 4 (it keeps hot cues and loops), and beat grids (each app draws its own).
- **Options** (top of the page): every choice in one place, each a switch or a link to its card: AIFF for new
  FLACs, covers and details, cues in step, Liked Songs kept apart, the USB folders and the genres. The way
  described here is how it starts; change any of them, any time.
- **The song list:** search by artist, title, genre, key or kind of file; filter to *Needs AIFF*, *No cover*,
  *Missing details*, *Names to fix*, *Not on USB* or *Below club quality*; tick songs (or all) and press
  **Convert to AIFF**, **Add cover & details** or **Put on USB**. Songs you added yourself or copied from a friend's
  USB are in it too.
- **Names that are mixed up:** a title with the artist in it, or the two the wrong way round, gets a line on its
  row with **Fix**; **Fix all names** does every one in one go. A name is written (in the file, and your decks
  follow) only when it is plain or a music catalogue agrees; otherwise you pick between the ways it could read.
  A Soulseek file whose own details name another song is marked "may be the wrong song": **Wrong file** sends it
  back, or say it's the right one and its name is fixed. **Undo** on the row puts the old name back.
- **A "?" beside each part** of both pages opens a few plain lines: how it works, what it never touches, how to
  undo. **How it works** at the top has the rest.
- **Listen first:** ▶ beside any song plays it on the page, with its waveform: tap it to jump, and a file that
  is very quiet or has a silent stretch in the middle is said. **Open in rekordbox** hands the song to rekordbox
  and copies its name (paste it into rekordbox's search if the song isn't loaded by itself); **Show in Finder**
  opens the file.
- **My SoundCloud playlists:** one playlist with every song from all of your SoundCloud playlists.
- **Genres:** each song is sorted by what's written on it (the file, SoundCloud's genre and tags). Songs nothing
  describes land in *No genre yet*: tap their genre on the page. Wrong genre? Tap **Edit**. A song can have several
  genres; it shows in each one's playlist, and the first is the Genre column on the decks. Your picks always win,
  and you can add or remove genres from the list. Change a song's genre in rekordbox (or in Engine DJ on the USB)
  instead, and that becomes your pick on the page too.
- **Recognise songs by their sound (a set-up step on the page):** The Crate can listen to each song and look it up in MusicBrainz,
  the way the free app MusicBrainz Picard does. It fills in genres for songs nothing describes, and flags a
  Soulseek file that sounds like a different song. It needs a free AcoustID key, once: the page has the link and
  a box to paste it in. Only a fingerprint of the sound and the song's length leave your Mac, never file names.
  Remixes, flips and bootlegs are often not in that database; those stay as they are.
- **Club check:** the page also says whether your USB would work on a club's decks (nearly always Pioneer CDJs):
  how the USB is formatted (FAT32 is read by every club deck, exFAT only by the newest), how many songs are FLAC
  (older club decks skip those), songs no club deck plays at all (32-bit files, or above 96 kHz), whether your songs are in the USB's own rekordbox library (the newest decks), and
  whether they are in rekordbox's older export, which the CDJ-3000, the CDJ-2000NXS2 and the decks before them need
  for playlists, tempo and key (in rekordbox, with the USB in: drag your playlists onto it under *Devices*). It only
  looks; it changes nothing.
- **What it never touches:** your own playlists and folders, beat grids, and any song that isn't The Crate's. A
  music file is changed only to fill an empty detail or to become an AIFF, each with an Undo; cues are only added
  or brought up to date, never deleted. No song is ever removed from a library. A copy of the library is kept before every change (*dj-backups* in the app
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
