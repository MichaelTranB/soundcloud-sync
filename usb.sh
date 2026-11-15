#!/bin/zsh
# Copies the music folder to the chosen USB when it is plugged in. Runs after every sync and whenever
# any drive is mounted, so tracks downloaded while the USB was away land on it the next time it appears.
# Only ever ADDS files: nothing on the USB is deleted or overwritten.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="${0:A:h}"
SRC="${SRC:-$HOME/Music/SoundCloud Sync}"   # both overridable for tests
NAME="$(cat "$DIR/usb.txt" 2>/dev/null)"
[ -z "$NAME" ] && exit 0
DEST="${VOLUMES:-/Volumes}/$NAME"
[ -d "$DEST" ] || { echo "$(date '+%F %R')  USB \"$NAME\" not plugged in; will copy when it is" >> "$DIR/usb.log"; exit 0; }
mkdir -p "$DEST/SoundCloud Sync"
# Only files that passed the safety check (safety.py) are copied. During a sync the check runs at its end.
[ -e "$DIR/.running" ] || python3 "$DIR/safety.py" check "$DIR" "$SRC" 2>>"$DIR/safety.log"
LIST="$DIR/.usb-list"
{ cut -f1 "$DIR/safety-ok.tsv" 2>/dev/null; echo "To Buy.txt"; } | while IFS= read -r p; do [ -f "$SRC/$p" ] && echo "$p"; done >"$LIST"
if rsync -a --ignore-existing --files-from="$LIST" "$SRC/" "$DEST/SoundCloud Sync/" 2>>"$DIR/usb.log"; then
  echo "$(date '+%F %R')  copied to \"$NAME\"" >> "$DIR/usb.log"
else
  echo "$(date '+%F %R')  COPY FAILED to \"$NAME\"" >> "$DIR/usb.log"; exit 1
fi
