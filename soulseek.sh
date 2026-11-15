#!/bin/zsh
# Last fallback, run by sync.sh after the artist downloads: every track still to get is searched on Soulseek
# with sockseek; only lossless or 320 kbps MP3 is taken, and it lands in "From Soulseek" inside the music folder.
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
prep() { python3 "$DIR/soulseek.py" prepare "$DIR" "$SLSK" >>"$LOG" 2>&1 || { say "Soulseek FAILED: could not read the to-get list"; exit 1; }; }
# Highest quality only. Pass 1: lossless only. Pass 2, for what pass 1 didn't find: MP3 at a confirmed 320 kbps
# (--strict-conditions drops files whose bitrate the peer doesn't report). Nothing lower is ever taken.
# --no-config: only these settings count. --no-skip-existing: soulseek.py's list alone decides what to search,
# so a Soulseek file that was moved or deleted is fetched again (sockseek's own index would skip it forever).
get() {
  "$SOCKSEEK" "$DIR/soulseek.csv" --input-type csv --no-config --user "$SUSER" --pass "$SPASS" \
    -o "$SLSK" --index-path "$SLSK/.index.sldl" --name-format '{sartist( - )stitle|slsk-filename}' \
    --strict-title --no-skip-existing --no-progress "$@" >"$DIR/soulseek-pass.log" 2>&1
  cat "$DIR/soulseek-pass.log" >>"$DIR/soulseek-run.log"
  python3 "$DIR/soulseek.py" record "$DIR" "$SLSK" >>"$LOG" 2>&1
  local c="$(grep -E 'Completed:' "$DIR/soulseek-pass.log" | tail -1 | sed 's/^\[cli\] Completed: //')"
  echo "${c:-FAILED, see soulseek-run.log}"
}
rows() { echo $(( $(wc -l < "$DIR/soulseek.csv") - 1 )); }
: >"$DIR/soulseek-run.log"
prep
if [ "$(rows)" -gt 0 ]; then
  RESULT="lossless pass: $(get --format flac,wav,aiff,aif,alac --pref-format flac,wav,aiff,aif)"
  prep
  if [ "$(rows)" -gt 0 ]; then
    RESULT="$RESULT; 320 MP3 pass: $(get --format mp3 --min-bitrate 320 --strict-conditions)"
  fi
  say "Soulseek: ${RESULT}"
  grep -q -i -E 'login failed|invalid pass|exception' "$DIR/soulseek-run.log" && say "Soulseek PROBLEM, see soulseek-run.log: $(grep -i -E 'login failed|invalid pass|exception' "$DIR/soulseek-run.log" | tail -1)"
else
  say "Soulseek: nothing new to look for"
fi
