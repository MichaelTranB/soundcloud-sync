#!/bin/zsh
# Syncs a SoundCloud playlist to the Mac: downloads the ORIGINAL file (WAV/FLAC/AIFF/MP3 as uploaded)
# for every track whose artist switched downloads on, and lists the rest in "To Buy.txt". A Spotify or Apple Music
# playlist goes straight to the Soulseek and shop-link steps (those services only stream).
# It never records the stream: Go+ covers streaming, not keeping files.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="${0:A:h}"
OUT="$HOME/Music/SoundCloud Sync"
URL="${1:-$(cat "$DIR/playlist.txt" 2>/dev/null)}"
[ -z "$URL" ] && { echo "No playlist link yet. Add it in the app."; exit 1; }
# .running holds the sync's process number; one left by a sync that was killed (no clean exit) is ignored.
kill -0 "$(cat "$DIR/.running" 2>/dev/null)" 2>/dev/null && { echo "A sync is already running."; exit 0; }
echo $$ >"$DIR/.running"; touch "$DIR/archive.txt"; trap 'rm -f "$DIR/.running"' EXIT
mkdir -p "$OUT"

# Keep the downloader current by itself (SoundCloud changes often): at most once a week.
if [ -z "$(find "$DIR/.updated" -mtime -7 2>/dev/null)" ]; then
  { if command -v uv >/dev/null && uv tool list 2>/dev/null | grep -q '^yt-dlp '; then uv tool upgrade yt-dlp
    elif command -v brew >/dev/null && brew list yt-dlp >/dev/null 2>&1; then brew upgrade yt-dlp
    else yt-dlp -U; fi; } >>"$DIR/update.log" 2>&1  # however it was installed (install.sh's own copy: -U)
  touch "$DIR/.updated"
fi
# The virus scanner's list of known viruses: fresh every day (ClamAV's servers limit how often).
zsh "$DIR/clamav.sh" >>"$DIR/update.log" 2>&1  # installs it if missing; refreshes the list at most daily

# A Spotify or Apple Music playlist: those services only stream, so nothing downloads from them. playlists.py reads
# the track list from the playlist's public page and writes the to-get list; Soulseek, Downloads and the shop links
# then work the same as for SoundCloud tracks that aren't free.
case "$URL" in https://open.spotify.com/*|https://music.apple.com/*|https://embed.music.apple.com/*) STREAM=1 ;; esac
if [ -n "$STREAM" ]; then
  if ! python3 "$DIR/playlists.py" tobuy "$URL" "$DIR" >"$DIR/last-run.log" 2>&1; then
    # Nothing from an earlier playlist is searched or shown; the page says the playlist page couldn't be read.
    echo "Couldn't read the playlist page" >>"$DIR/last-run.log"
    : >"$DIR/to-buy.tsv"; rm -f "$DIR/.service"
  fi
  echo 0 >"$DIR/unread.txt"
  HAVE=$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print(s["count"])' "$DIR/.service" 2>/dev/null || echo 0)
  HAVE=$(( HAVE - $(cat "$DIR/to-buy.tsv" 2>/dev/null | wc -l) ))
else
# Original files only download for a signed-in account: the SoundCloud sign-in already in his browser
# (Chrome unless he picked another in the app; an empty browser.txt means none). macOS lets yt-dlp read it
# only when this runs through Crate Helper with Full Disk Access on.
BROWSER="$(cat "$DIR/browser.txt" 2>/dev/null || echo chrome)"
AUTH=()
case "$BROWSER" in
  chrome) STORE="$HOME/Library/Application Support/Google/Chrome" ;;
  safari) STORE="$HOME/Library/Cookies"  # where yt-dlp looks first; newer Macs keep it in Safari's container
          [ -e "$STORE/Cookies.binarycookies" ] || STORE="$HOME/Library/Containers/com.apple.Safari/Data/Library/Cookies" ;;
  brave) STORE="$HOME/Library/Application Support/BraveSoftware/Brave-Browser" ;;
  edge) STORE="$HOME/Library/Application Support/Microsoft Edge" ;;
  firefox) STORE="$HOME/Library/Application Support/Firefox" ;;
  *) STORE="" ;;
esac
# A sign-in macOS won't let us read would stop yt-dlp altogether; then the sync runs without it (no originals,
# the rest still works) and the page says how to turn it on.
: >"$DIR/signin.log"
# profile.txt: the browser profile signed in to SoundCloud, when the app found it isn't the most recently used one.
# It reads "browser:folder"; one saved for another browser, or a folder since removed, is ignored.
PROFILE="$(cat "$DIR/profile.txt" 2>/dev/null)"
case "$BROWSER:$PROFILE" in chrome:chrome:*|brave:brave:*|edge:edge:*) PROFILE="${PROFILE#*:}" ;; *) PROFILE="" ;; esac
[ -n "$PROFILE" ] && { [ -e "$STORE/$PROFILE/Cookies" ] || [ -e "$STORE/$PROFILE/Network/Cookies" ]; } || PROFILE=""
if [ -n "$STORE" ] && ls "$STORE" >/dev/null 2>&1; then AUTH=(--cookies-from-browser "$BROWSER${PROFILE:+:$PROFILE}")
elif [ -n "$STORE" ] && [ -d "$STORE" ]; then echo "sign-in blocked: operation not permitted ($BROWSER)" >"$DIR/signin.log"; fi

# ONE pass over the playlist does both jobs: each track's details are saved for the to-get list (.listing), and
# its original is downloaded when the artist allows it. New tracks only: archive.txt remembers what is already here.
# SoundCloud refuses (HTTP 403) a Mac that asks too fast, so this asks for as little as it can: one request per
# track (formats=none skips SoundCloud's stream links, which we never use; the original is asked for separately),
# one at a time, about a second apart.
get() { # seconds between requests, then the links
  yt-dlp "${AUTH[@]}" -f download --download-archive "$DIR/archive.txt" --ignore-errors --ignore-no-formats-error \
    --no-overwrites --extractor-args "soundcloud:formats=none" --sleep-requests "$1" \
    --print-to-file pre_process:"%()j" "$DIR/.listing" \
    --print-to-file after_move:"%(extractor_key)s %(id)s	%(filepath)s" "$DIR/.originals" \
    --embed-metadata -o "$OUT/%(uploader)s - %(title)s.%(ext)s" "${@:2}"
}
: >"$DIR/.originals"; : >"$DIR/.listing"
get 1 "$URL" >"$DIR/last-run.log" 2>&1
# The playlist's own track list (one request): what the pass above should have seen.
yt-dlp --flat-playlist --print "%(id)s %(url)s" "$URL" >"$DIR/.playlist" 2>>"$DIR/last-run.log"
# The safety check right away: an original it blocks (moved to Quarantine) counts as not got, so the free
# download, Downloads pickup and Soulseek still look for it (blocked-originals.txt; never downloaded again).
python3 "$DIR/safety.py" check "$DIR" "$OUT" 2>>"$DIR/safety.log"
while IFS=$'\t' read -r key p; do
  [ -n "$p" ] && [ ! -e "$p" ] && echo "${key:l}" >>"$DIR/blocked-originals.txt"
done <"$DIR/.originals"
touch "$DIR/blocked-originals.txt"
grep -vxFf "$DIR/blocked-originals.txt" "$DIR/archive.txt" >"$DIR/.archive-have" || :  # (exit 1: none left)

# Tracks SoundCloud refused (or whose original was blocked) are asked again after a pause, slower. What it still
# won't show is counted on the page and asked again at the next sync.
unread() { python3 "$DIR/tobuy.py" --unread "$DIR/.playlist" "$DIR/.archive-have" "$DIR/.listing" >"$DIR/.unread"; }
for pause in 120 600; do
  unread; [ -s "$DIR/.unread" ] || break
  echo "SoundCloud refused $(wc -l < "$DIR/.unread" | tr -d ' ') track(s); asking again in $pause s" >>"$DIR/last-run.log"
  sleep $pause
  get 3 -a "$DIR/.unread" >>"$DIR/last-run.log" 2>&1
  # A blocked original is in archive.txt, so the pass above skips it: its details only, no download.
  unread; [ -s "$DIR/.unread" ] && yt-dlp "${AUTH[@]}" --skip-download --ignore-errors --ignore-no-formats-error \
    --extractor-args "soundcloud:formats=none" --sleep-requests 3 --print-to-file pre_process:"%()j" "$DIR/.listing" \
    --download-archive "$DIR/.archive-have" -a "$DIR/.unread" >>"$DIR/last-run.log" 2>&1
done
unread; wc -l < "$DIR/.unread" | tr -d ' ' >"$DIR/unread.txt"
python3 "$DIR/tobuy.py" "$DIR/.archive-have" "$DIR/to-buy.tsv" <"$DIR/.listing"
HAVE=$(wc -l < "$DIR/.archive-have" | tr -d ' ')
fi
# The Free Download button under each track still to get (yt-dlp doesn't report it): its link joins the list.
python3 "$DIR/tobuy.py" --buttons "$DIR" 2>&1 | sed "s/^/$(date '+%F %R')  /" >>"$DIR/free.log"
# The artist's own free download, when the description links straight to a file (Dropbox, Drive...): top quality only.
python3 "$DIR/freedl.py" "$DIR" "$OUT" 2>&1 | sed "s/^/$(date '+%F %R')  /" >>"$DIR/free.log"
# Tracks bought or unlocked by hand (Beatport, Hypeddit, Laylo...) waiting in Downloads.
python3 "$DIR/freedl.py" inbox "$DIR" "$OUT" 2>&1 | sed "s/^/$(date '+%F %R')  /" >>"$DIR/free.log"

echo "$(date '+%F %R')  have: $HAVE  to buy: $(wc -l < "$DIR/to-buy.tsv" | tr -d ' ')" | tee -a "$DIR/history.log"
# Last fallback for whatever is still to get: Soulseek, through sockseek (download-only).
"$DIR/soulseek.sh"
# The list for the USB, after every source had its turn (a track on the Mac is never on it).
awk -F'\t' '{ print $1 "  " ($3 != "" ? "FREE: " $3 : $2) }' "$DIR/to-buy.tsv" > "$OUT/To Buy.txt"
# Every new file must be real audio (and pass the virus scan) before it stays or reaches the USB.
python3 "$DIR/safety.py" check "$DIR" "$OUT" 2>>"$DIR/safety.log"
CRATE_FINAL=1 "$DIR/usb.sh"  # the sync's last copy: the one that may eject
# The Crate keeps itself up to date: once a day it takes the newest version from GitHub (only a clean step forward on
# main; a copy someone changed by hand is left alone). The page restarts on it at once; the sync's own parts are new
# from the next sync. Running the install line again does the same by hand.
if [ "$(git -C "$DIR" symbolic-ref -q --short HEAD 2>/dev/null)" = main ] && [ -z "$(find "$DIR/.app-updated" -mtime -1 2>/dev/null)" ]; then
  OLD="$(git -C "$DIR" rev-parse HEAD)"
  if git -C "$DIR" pull -q --ff-only origin main >>"$DIR/update.log" 2>&1; then
    touch "$DIR/.app-updated"
    if [ "$(git -C "$DIR" rev-parse HEAD)" != "$OLD" ]; then
      echo "$(date '+%F %R')  The Crate updated itself to $(git -C "$DIR" log -1 --format='%h, %cd' --date=short)" >>"$DIR/update.log"
      launchctl kickstart -k "gui/$(id -u)/com.thecrate.app" 2>/dev/null
    fi
  else
    echo "$(date '+%F %R')  Couldn't update The Crate; tries again next sync." >>"$DIR/update.log"
  fi
fi
