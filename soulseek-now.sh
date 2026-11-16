#!/bin/zsh
# Started by the page when a Soulseek file is thrown back ("Wrong or bad file"): Soulseek is asked for another copy
# right away instead of at the next sync. Only the Soulseek step and what follows it in sync.sh; SoundCloud isn't
# read again. One at a time with a sync (.running): the page starts this once a running sync or search is done.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="${0:A:h}"
OUT="$HOME/Music/SoundCloud Sync"
kill -0 "$(cat "$DIR/.running" 2>/dev/null)" 2>/dev/null && exit 0
echo $$ >"$DIR/.running"; trap 'rm -f "$DIR/.running"' EXIT
: >"$DIR/soulseek-pass.log"  # from here the page shows it as looking on Soulseek
"$DIR/soulseek.sh"
awk -F'\t' '{ print $1 "  " ($3 != "" ? "FREE: " $3 : $2) }' "$DIR/to-buy.tsv" > "$OUT/To Buy.txt"
python3 "$DIR/safety.py" check "$DIR" "$OUT" 2>>"$DIR/safety.log"
python3 "$DIR/dj.py" "$DIR" "$OUT" --wait 2>>"$DIR/dj.log"
"$DIR/usb.sh"  # onto the USB if it's plugged in; never ejects (that is the sync's own last copy)
