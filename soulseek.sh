#!/bin/zsh
# Last fallback, run by sync.sh after the artist downloads: every track still to get is searched on Soulseek
# with sockseek, and the best match (lossless first) lands in "From Soulseek" inside the music folder.
# sockseek only downloads; it shares nothing. When the artist's own file arrives later, the Soulseek copy on
# the Mac is removed (usb.sh never deletes, so the USB keeps what it already has).
export PATH="/opt/homebrew/bin:$PATH"
DIR="${0:A:h}"
SLSK="${SLSK:-$HOME/Music/SoundCloud Sync/From Soulseek}"   # overridable for tests
SOCKSEEK="${SOCKSEEK:-$HOME/.local/bin/sockseek}"
SERVICE=soundcloud-sync-soulseek   # Keychain item made by soulseek-login.sh
LOG="$DIR/soulseek.log"
say() { echo "$(date '+%F %R')  $1" | tee -a "$LOG"; }

[ -x "$SOCKSEEK" ] || { say "Soulseek skipped: sockseek isn't installed (run install.sh)"; exit 0; }
SUSER="$(security find-generic-password -s "$SERVICE" 2>/dev/null | sed -n 's/^ *"acct"<blob>="\(.*\)"$/\1/p')"
SPASS="$(security find-generic-password -s "$SERVICE" -w 2>/dev/null)"
[ -z "$SUSER" ] || [ -z "$SPASS" ] && { say "Soulseek skipped: not set up yet (run soulseek-login.sh)"; exit 0; }

mkdir -p "$SLSK"
python3 "$DIR/soulseek.py" prepare "$DIR" "$SLSK" >>"$LOG" 2>&1 || { say "Soulseek FAILED: could not read the to-get list"; exit 1; }
if [ "$(wc -l < "$DIR/soulseek.csv")" -gt 1 ]; then
  # --no-config: only these settings count. Exit 1 just means some tracks weren't found.
  "$SOCKSEEK" "$DIR/soulseek.csv" --input-type csv --no-config --user "$SUSER" --pass "$SPASS" \
    -o "$SLSK" --index-path "$SLSK/.index.sldl" --name-format '{sartist( - )stitle|slsk-filename}' \
    --strict-title --format mp3,flac,wav,aiff,aif,alac,m4a --pref-format flac,wav,aiff,aif --pref-min-bitrate 320 \
    --no-progress >"$DIR/soulseek-run.log" 2>&1
  python3 "$DIR/soulseek.py" record "$DIR" "$SLSK" >>"$LOG" 2>&1
  RESULT="$(grep -E 'Completed:' "$DIR/soulseek-run.log" | tail -1 | sed 's/^\[cli\] //')"
  say "Soulseek: ${RESULT:-FAILED, see soulseek-run.log: $(grep -i -E 'error|fail' "$DIR/soulseek-run.log" | tail -1)}"
else
  say "Soulseek: nothing new to look for"
fi
