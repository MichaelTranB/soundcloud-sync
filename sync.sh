#!/bin/zsh
# Syncs a SoundCloud playlist to the Mac: downloads the ORIGINAL file (WAV/FLAC/AIFF/MP3 as uploaded)
# for every track whose artist switched downloads on, and lists the rest in "To Buy.txt".
# It never records the stream: Go+ covers streaming, not keeping files.
export PATH="/opt/homebrew/bin:$PATH"
DIR="${0:A:h}"
OUT="$HOME/Music/SoundCloud Sync"
URL="${1:-$(cat "$DIR/playlist.txt" 2>/dev/null)}"
[ -z "$URL" ] && { echo "No playlist link yet. Add it in the app."; exit 1; }
[ -e "$DIR/.running" ] && { echo "A sync is already running."; exit 0; }
touch "$DIR/.running" "$DIR/archive.txt"; trap 'rm -f "$DIR/.running"' EXIT
mkdir -p "$OUT"

# Keep the downloader current by itself (SoundCloud changes often): at most once a week.
if [ -z "$(find "$DIR/.updated" -mtime -7 2>/dev/null)" ]; then
  brew upgrade yt-dlp >>"$DIR/update.log" 2>&1; touch "$DIR/.updated"
fi

# Original files only download for a signed-in account: a Keychain token, or the browser he signed in with.
TOKEN="$("$HOME/work-os/bin/api-key" get soundcloud 2>/dev/null)"
BROWSER="$(cat "$DIR/browser.txt" 2>/dev/null)"
AUTH=()
if [ -n "$TOKEN" ]; then AUTH=(--username oauth --password "$TOKEN")
elif [ -n "$BROWSER" ]; then AUTH=(--cookies-from-browser "$BROWSER"); fi  # the session of the browser picked in the app

# New tracks only (archive.txt remembers what is already here).
yt-dlp "${AUTH[@]}" -f download --download-archive "$DIR/archive.txt" --ignore-errors --no-overwrites \
  --embed-metadata -o "$OUT/%(uploader)s - %(title)s.%(ext)s" "$URL" >"$DIR/last-run.log" 2>&1

# Everything in the playlist with no artist download: the list still to get, each with the artist's
# own free-download link when their description has one.
yt-dlp "${AUTH[@]}" --skip-download --ignore-errors --ignore-no-formats-error --dump-json "$URL" 2>>"$DIR/last-run.log" |
  python3 "$DIR/tobuy.py" "$DIR/archive.txt" "$DIR/to-buy.tsv"
awk -F'\t' '{ print $1 "  " ($3 != "" ? "FREE: " $3 : $2) }' "$DIR/to-buy.tsv" > "$OUT/To Buy.txt"

echo "$(date '+%F %R')  have: $(wc -l < "$DIR/archive.txt" | tr -d ' ')  to buy: $(wc -l < "$DIR/to-buy.tsv" | tr -d ' ')" | tee -a "$DIR/history.log"
"$DIR/usb.sh"
