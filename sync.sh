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

# Original files only download for a signed-in account: the token comes from the Keychain, never a file.
TOKEN="$("$HOME/work-os/bin/api-key" get soundcloud 2>/dev/null)"
AUTH=(); [ -n "$TOKEN" ] && AUTH=(--username oauth --password "$TOKEN")

# New tracks only (archive.txt remembers what is already here).
yt-dlp "${AUTH[@]}" -f download --download-archive "$DIR/archive.txt" --ignore-errors --no-overwrites \
  --embed-metadata -o "$OUT/%(uploader)s - %(title)s.%(ext)s" "$URL" >"$DIR/last-run.log" 2>&1

# Everything in the playlist with no artist download: the list to buy (name, tab, link).
yt-dlp "${AUTH[@]}" --skip-download --ignore-errors --ignore-no-formats-error \
  --print "%(id)s	%(uploader)s - %(title)s	%(webpage_url)s" "$URL" 2>>"$DIR/last-run.log" |
  while IFS=$'\t' read -r id name link; do
    grep -q "soundcloud $id\$" "$DIR/archive.txt" || printf '%s\t%s\n' "$name" "$link"
  done > "$DIR/to-buy.tsv"
tr '\t' ' ' < "$DIR/to-buy.tsv" > "$OUT/To Buy.txt"

echo "$(date '+%F %R')  have: $(wc -l < "$DIR/archive.txt" | tr -d ' ')  to buy: $(wc -l < "$DIR/to-buy.tsv" | tr -d ' ')" | tee -a "$DIR/history.log"
"$DIR/usb.sh"
