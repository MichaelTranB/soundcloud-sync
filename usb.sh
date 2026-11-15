#!/bin/zsh
# Copies the music folder to the chosen USB when it is plugged in. Runs after every sync and whenever
# any drive is mounted, so tracks downloaded while the USB was away land on it the next time it appears.
# Only ever ADDS files: nothing on the USB is deleted or overwritten.
DIR="${0:A:h}"
SRC="$HOME/Music/SoundCloud Sync"
NAME="$(cat "$DIR/usb.txt" 2>/dev/null)"
[ -z "$NAME" ] && exit 0
DEST="/Volumes/$NAME"
[ -d "$DEST" ] || { echo "$(date '+%F %R')  USB \"$NAME\" not plugged in; will copy when it is" >> "$DIR/usb.log"; exit 0; }
mkdir -p "$DEST/SoundCloud Sync"
if rsync -a --ignore-existing --exclude '.*' "$SRC/" "$DEST/SoundCloud Sync/" 2>>"$DIR/usb.log"; then
  echo "$(date '+%F %R')  copied to \"$NAME\"" >> "$DIR/usb.log"
else
  echo "$(date '+%F %R')  COPY FAILED to \"$NAME\"" >> "$DIR/usb.log"; exit 1
fi
