#!/bin/zsh
# Syncs a SoundCloud playlist to the Mac: downloads the ORIGINAL file (WAV/FLAC/AIFF/MP3 as uploaded)
# for every track whose artist switched downloads on, and lists the rest in "To Buy.txt".
# It never records the stream: Go+ covers streaming, not keeping files.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="${0:A:h}"
OUT="$HOME/Music/SoundCloud Sync"
URL="${1:-$(cat "$DIR/playlist.txt" 2>/dev/null)}"
[ -z "$URL" ] && { echo "No playlist link yet. Add it in the app."; exit 1; }
[ -e "$DIR/.running" ] && { echo "A sync is already running."; exit 0; }
touch "$DIR/.running" "$DIR/archive.txt"; trap 'rm -f "$DIR/.running"' EXIT
mkdir -p "$OUT"

# Keep the downloader current by itself (SoundCloud changes often): at most once a week.
if [ -z "$(find "$DIR/.updated" -mtime -7 2>/dev/null)" ]; then
  { if command -v uv >/dev/null && uv tool list 2>/dev/null | grep -q '^yt-dlp '; then uv tool upgrade yt-dlp
    elif command -v brew >/dev/null && brew list yt-dlp >/dev/null 2>&1; then brew upgrade yt-dlp
    else yt-dlp -U; fi; } >>"$DIR/update.log" 2>&1  # however it was installed (install.sh's own copy: -U)
  touch "$DIR/.updated"
fi
# The virus scanner's list of known viruses: fresh every day (ClamAV's servers limit how often).
if command -v freshclam >/dev/null && [ -z "$(find "$DIR/.virusdb" -mmin -1200 2>/dev/null)" ]; then
  freshclam --quiet >>"$DIR/update.log" 2>&1; touch "$DIR/.virusdb"
fi

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
if [ -n "$STORE" ] && ls "$STORE" >/dev/null 2>&1; then AUTH=(--cookies-from-browser "$BROWSER")
elif [ -n "$STORE" ] && [ -d "$STORE" ]; then echo "sign-in blocked: operation not permitted ($BROWSER)" >"$DIR/signin.log"; fi

# New tracks only (archive.txt remembers what is already here).
: >"$DIR/.originals"
yt-dlp "${AUTH[@]}" -f download --download-archive "$DIR/archive.txt" --ignore-errors --no-overwrites \
  --print-to-file after_move:"%(extractor_key)s %(id)s	%(filepath)s" "$DIR/.originals" \
  --embed-metadata -o "$OUT/%(uploader)s - %(title)s.%(ext)s" "$URL" >"$DIR/last-run.log" 2>&1
# The safety check right away: an original it blocks (moved to Quarantine) counts as not got, so the free
# download, Downloads pickup and Soulseek still look for it (blocked-originals.txt; never downloaded again).
python3 "$DIR/safety.py" check "$DIR" "$OUT" 2>>"$DIR/safety.log"
while IFS=$'\t' read -r key p; do
  [ -n "$p" ] && [ ! -e "$p" ] && echo "${key:l}" >>"$DIR/blocked-originals.txt"
done <"$DIR/.originals"
touch "$DIR/blocked-originals.txt"
grep -vxFf "$DIR/blocked-originals.txt" "$DIR/archive.txt" >"$DIR/.archive-have" || :  # (exit 1: none left)

# Everything in the playlist with no artist download: the list still to get, each with the artist's
# own free-download link when their description has one.
# Tracks already downloaded are skipped by ID before SoundCloud is asked about them, so a playlist that keeps
# growing doesn't make every sync re-read all of it (yt-dlp only reads the archive here; it never writes it
# without a download or --force-write-archive).
yt-dlp "${AUTH[@]}" --download-archive "$DIR/.archive-have" --skip-download --ignore-errors --ignore-no-formats-error --dump-json "$URL" 2>>"$DIR/last-run.log" |
  python3 "$DIR/tobuy.py" "$DIR/.archive-have" "$DIR/to-buy.tsv"
# The artist's own free download, when the description links straight to a file (Dropbox, Drive...): top quality only.
python3 "$DIR/freedl.py" "$DIR" "$OUT" 2>&1 | sed "s/^/$(date '+%F %R')  /" >>"$DIR/free.log"
# Tracks bought or unlocked by hand (Beatport, Hypeddit, Laylo...) waiting in Downloads.
python3 "$DIR/freedl.py" inbox "$DIR" "$OUT" 2>&1 | sed "s/^/$(date '+%F %R')  /" >>"$DIR/free.log"
awk -F'\t' '{ print $1 "  " ($3 != "" ? "FREE: " $3 : $2) }' "$DIR/to-buy.tsv" > "$OUT/To Buy.txt"

echo "$(date '+%F %R')  have: $(wc -l < "$DIR/.archive-have" | tr -d ' ')  to buy: $(wc -l < "$DIR/to-buy.tsv" | tr -d ' ')" | tee -a "$DIR/history.log"
# Last fallback for whatever is still to get: Soulseek, through sockseek (download-only).
"$DIR/soulseek.sh"
# Every new file must be real audio (and pass the virus scan) before it stays or reaches the USB.
python3 "$DIR/safety.py" check "$DIR" "$OUT" 2>>"$DIR/safety.log"
"$DIR/usb.sh"
