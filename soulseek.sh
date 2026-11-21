#!/bin/zsh
# Last fallback, run by sync.sh after the artist downloads: every track still to get is searched on Soulseek
# with sockseek; only lossless or 320 kbps MP3 is taken, and it lands in the music folder with everything else.
# sockseek only downloads; it shares nothing. When the artist's own file arrives later, the Soulseek copy on
# the Mac is removed (usb.sh never deletes, so the USB keeps what it already has).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
# A background job on a Mac may only have 256 files open at once (launchctl limit maxfiles): sockseek's searches
# and downloads go past that, and it stopped with "Too many open files" before every song was looked for.
ulimit -n 8192 2>/dev/null || ulimit -n 4096 2>/dev/null
DIR="${0:A:h}"
SLSK="${SLSK:-$HOME/Music/SoundCloud Sync}"   # the music folder itself; overridable for tests
SOCKSEEK="${SOCKSEEK:-$HOME/.local/bin/sockseek}"
SERVICE=soundcloud-sync-soulseek   # Keychain item made by soulseek-login.sh
LOG="$DIR/soulseek.log"
say() { echo "$(date '+%F %R')  $1" | tee -a "$LOG"; }
# The page's note that a file was thrown back and its track wants looking for (soulseek-now.sh): this run does that.
# One thrown back while this run is going leaves the note again, and the page starts another run after this one.
rm -f "$DIR/.soulseek-again"

[ -x "$SOCKSEEK" ] || { say "Soulseek skipped: sockseek isn't installed (run install.sh)"; exit 0; }
SUSER="$(security find-generic-password -s "$SERVICE" 2>/dev/null | sed -n 's/^ *"acct"<blob>="\(.*\)"$/\1/p')"
SPASS="$(security find-generic-password -s "$SERVICE" -w 2>/dev/null)"
[ -z "$SUSER" ] || [ -z "$SPASS" ] && { say "Soulseek skipped: not set up yet (run soulseek-login.sh)"; exit 0; }

mkdir -p "$SLSK"
# The safety check first: a file a stopped run left behind is checked before soulseek.py counts it as got.
prep() { python3 "$DIR/safety.py" check "$DIR" "$SLSK" 2>>"$DIR/safety.log"; python3 "$DIR/soulseek.py" prepare "$DIR" "$SLSK" >>"$LOG" 2>&1 || { say "Soulseek FAILED: could not read the to-get list"; exit 1; }; }
# Each track is also searched in looser ways (--desperate: the artist or the title alone, then filtered;
# --artist-maybe-wrong: once without the artist, as a SoundCloud uploader isn't always the artist). The quality, title and length checks
# below still decide what is taken, so a looser search only finds more, never a worse or wrong file. sockseek's own
# limit on searches per minute still holds (more searches per track just take longer).
# Highest quality only. Pass 1: lossless only. Pass 2, for what pass 1 didn't find: MP3 at a confirmed 320 kbps
# (--strict-conditions drops files whose bitrate the peer doesn't report). Nothing lower is ever taken.
# Same version only: the file must be within 5 seconds of the SoundCloud track's length (an extended mix is not
# the radio edit), unless the SoundCloud upload is itself a clip or edit (soulseek.py leaves its length out).
# That is asked of sockseek here and checked on the file itself afterwards (soulseek.py record).
# Only these settings count: a private one-run config file holds the sign-in (a password on the command line
# would show in the list of running programs). --no-skip-existing: soulseek.py's list (soulseek.tsv: got once,
# never again) alone decides what to search.
CONF="$(mktemp "$DIR/.sockseek-XXXXXX")" || { say "Soulseek FAILED: could not write its settings"; exit 1; }
trap 'rm -f "$CONF"' EXIT
printf 'username = %s\npassword = %s\n' "$SUSER" "$SPASS" >"$CONF"
# A sync's Soulseek turn ends after SLSK_HOURS (3 to start): a long list (a Liked Songs batch) otherwise held the
# rekordbox update, the USB copy and the next sync back for a day. What it didn't reach waits for the next sync;
# playlist songs are first on the list, so only Liked Songs ever wait. The lossless pass has the first two thirds
# of it and the 320 MP3 pass always gets the rest, so a song only out there as MP3 is never stuck behind a long
# lossless search. A track both passes searched and found nothing for waits its days (soulseek.py missed), so the
# next sync goes on further down the list instead of searching the same first songs again.
START=$(date +%s); HOURS=${SLSK_HOURS:-3}
END=$(( START + HOURS * 3600 ))
TIMEUP="$DIR/.soulseek-timeup"
get() {
  rm -f "$TIMEUP"
  # Never the same wrong file twice: the people whose file you threw back aren't asked again, and the ones whose
  # file the check threw back come last (soulseek-wrong.tsv, kept by soulseek.py).
  local BAN=(${(f)"$(python3 "$DIR/soulseek.py" banned "$DIR" "$SLSK" 2>>"$LOG")"})
  "$SOCKSEEK" "$DIR/soulseek.csv" --input-type csv --config "$CONF" \
    -o "$SLSK" --index-path "$SLSK/.index.sldl" --name-format '{sartist( - )stitle|slsk-filename}' \
    --strict-title --length-tol 5 "${LOOSE[@]}" --no-skip-existing --no-progress "${BAN[@]}" "$@" >"$DIR/soulseek-pass.log" 2>&1 &
  local pid=$!
  ( while kill -0 $pid 2>/dev/null; do
      (( $(date +%s) >= UNTIL )) && { touch "$TIMEUP"; kill -TERM $pid; break; }
      sleep 15
    done ) >/dev/null 2>&1 &
  local watch=$!
  wait $pid
  kill $watch 2>/dev/null
  cat "$DIR/soulseek-pass.log" >>"$DIR/soulseek-run.log"
  # Before anything counts as got: a file that isn't real audio (or that the virus scan flags) goes to Quarantine.
  python3 "$DIR/safety.py" check "$DIR" "$SLSK" 2>>"$DIR/safety.log"
  # Then each file is looked at itself (its real length, the song named inside it): sockseek's own title and
  # length checks only see what the other person's computer says about a file. One that isn't the playlist's song
  # is thrown back (to the Trash) and its track stays on the list.
  local said="$(python3 "$DIR/soulseek.py" record "$DIR" "$SLSK" 2>&1)"
  [ -n "$said" ] && print -r -- "$said" >>"$LOG"
  local back=$(print -r -- "$said" | grep -c '^thrown back')
  # sockseek writes one "SongJob: succeeded" line per track it got (a failed try on one peer is only a [warn]).
  local n=$(( $(wc -l < "$DIR/soulseek.csv") - 1 ))
  local got=$(( $(grep -c '\] SongJob: succeeded:' "$DIR/soulseek-pass.log") - back ))
  if [ -e "$TIMEUP" ]; then
    echo "stopped at its time limit after getting $(( got > 0 ? got : 0 )) of $n; the rest are looked for next sync"
  elif grep -q -i 'unhandled exception' "$DIR/soulseek-pass.log"; then
    echo "FAILED (sockseek crashed after getting $(( got > 0 ? got : 0 )) of $n), see soulseek-run.log"
  elif grep -q 'Job List: ' "$DIR/soulseek-pass.log"; then
    echo "got $(( got > 0 ? got : 0 )) of $n$( [ "$back" -gt 0 ] && echo " ($back thrown back: not the playlist's song)")"
  else
    echo "FAILED, see soulseek-run.log"
  fi
}
rows() { echo $(( $(wc -l < "$DIR/soulseek.csv") - 1 )); }
LOOSE=(--desperate --artist-maybe-wrong)
pass() {
  # A pass that crashed is run once more with only the exact searches: a one-word title searched alone ("Sugar")
  # can bring back more results than sockseek can hold, and it then stops with nothing after that track searched.
  local r="$(get "$@")"
  case "$r" in "FAILED (sockseek crashed"*)
    prep
    [ "$(rows)" -gt 0 ] || { echo "$r"; return; }
    LOOSE=()
    local again="$(get "$@")"
    case "$again" in FAILED*) echo "$r; again with exact searches only: $again" ;; *) echo "$again (exact searches only: the looser ones crashed sockseek)" ;; esac ;;
  *) echo "$r" ;;
  esac
}
: >"$DIR/soulseek-run.log"
prep
if [ "$(rows)" -gt 0 ]; then
  UNTIL=$(( START + HOURS * 2400 ))
  RESULT="lossless pass: $(pass --format flac,wav,aiff,aif,alac --pref-format flac,wav,aiff,aif)"
  cp "$DIR/soulseek-run.log" "$DIR/soulseek-lossless.log"
  prep
  if [ "$(rows)" -gt 0 ]; then
    UNTIL=$END
    RESULT="$RESULT; 320 MP3 pass: $(pass --format mp3 --min-bitrate 320 --strict-conditions)"
  fi
  # Tracks no pass found at all are searched again after a wait (soulseek.py: 1, 2, 4, then 7 days). Only tracks
  # both passes searched count (a pass stopped by the time limit didn't reach them all), and none after a crash.
  case "$RESULT" in *FAILED*) ;; *) python3 "$DIR/soulseek.py" missed "$DIR" "$SLSK" "soulseek-lossless.log" "soulseek-pass.log" >>"$LOG" 2>&1 ;; esac
  say "Soulseek: ${RESULT}"
  # Only a sign-in or a crash that the second try didn't get past is a problem; a peer that doesn't answer is
  # normal (the next one is tried).
  BAD='login.*(fail|reject|denied)|invalid ?pass|wrong password'
  case "$RESULT" in *FAILED*) BAD="$BAD|unhandled exception" ;; esac
  grep -q -i -E "$BAD" "$DIR/soulseek-run.log" && say "Soulseek PROBLEM, see soulseek-run.log: $(grep -i -E "$BAD" "$DIR/soulseek-run.log" | tail -1)"
else
  say "Soulseek: nothing new to look for"
fi
