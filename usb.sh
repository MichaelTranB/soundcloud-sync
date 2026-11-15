#!/bin/zsh
# Copies the music folder to the chosen USB when it is plugged in. Runs after every sync and whenever
# any drive is mounted, so tracks downloaded while the USB was away land on it the next time it appears.
# Only ever ADDS tracks: no track on the USB is deleted or overwritten (only its To Buy.txt list is updated).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="${0:A:h}"
SRC="${SRC:-$HOME/Music/SoundCloud Sync}"   # both overridable for tests
NAME="$(cat "$DIR/usb.txt" 2>/dev/null)"
[ -z "$NAME" ] && exit 0
DEST="${VOLUMES:-/Volumes}/$NAME"
[ -d "$DEST" ] || { echo "$(date '+%F %R')  USB \"$NAME\" not plugged in; will copy when it is" >> "$DIR/usb.log"; exit 0; }
mkdir -p "$DEST/SoundCloud Sync"
# Only files that passed the safety check (safety.py) are copied. During a sync the check runs at its end.
kill -0 "$(cat "$DIR/.running" 2>/dev/null)" 2>/dev/null || python3 "$DIR/safety.py" check "$DIR" "$SRC" 2>>"$DIR/safety.log"
LIST="$DIR/.usb-list"
# "./" first: rsync would read a name starting with # or ; as a comment
cut -f1 "$DIR/safety-ok.tsv" 2>/dev/null | while IFS= read -r p; do [ -f "$SRC/$p" ] && echo "./$p"; done >"$LIST"
# Tracks not on the USB yet (counted before the copy, for the notice below)
NEW=$(while IFS= read -r p; do [ -e "$DEST/SoundCloud Sync/$p" ] || echo x; done <"$LIST" | wc -l | tr -d ' ')
# To Buy.txt is The Crate's own list, so the USB always gets the latest one.
if rsync -a --ignore-existing --files-from="$LIST" "$SRC/" "$DEST/SoundCloud Sync/" 2>>"$DIR/usb.log" &&
   { [ ! -f "$SRC/To Buy.txt" ] || cp "$SRC/To Buy.txt" "$DEST/SoundCloud Sync/To Buy.txt" 2>>"$DIR/usb.log"; }; then
  echo "$(date '+%F %R')  copied to \"$NAME\" ($NEW new)" >> "$DIR/usb.log"
else
  echo "$(date '+%F %R')  COPY FAILED to \"$NAME\"" >> "$DIR/usb.log"
  [ -z "$VOLUMES" ] && osascript -e "display notification \"Copy to $NAME failed. Open The Crate to see why.\" with title \"The Crate\"" 2>/dev/null
  exit 1
fi
# New tracks landed: eject the USB (unless "Eject when done" is off on the page) and say it's safe to unplug.
if [ "$NEW" -gt 0 ] && [ -z "$VOLUMES" ]; then
  [ "$NEW" = 1 ] && MSG="1 new track on $NAME." || MSG="$NEW new tracks on $NAME."
  if [ ! -e "$DIR/usb-keep.txt" ]; then
    sync; diskutil eject "$DEST" >/dev/null 2>&1 && { MSG="$MSG Safe to unplug."; echo "$(date '+%F %R')  ejected \"$NAME\"" >> "$DIR/usb.log"; }
  fi
  osascript -e "display notification \"$MSG\" with title \"The Crate\" sound name \"Glass\"" 2>/dev/null
fi
