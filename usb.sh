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
# One copy at a time (a sync, a plugged-in drive and the Copy Now button can all start one). While it runs,
# .usb-copy says how far it is ("pid stage new-tracks") and .usb-progress lists each file copied: the page shows both.
STATE="$DIR/.usb-copy"
kill -0 "$(cut -d' ' -f1 "$STATE" 2>/dev/null)" 2>/dev/null && exit 0
echo "$$ checking 0" >"$STATE"; : >"$DIR/.usb-progress"
trap 'rm -f "$STATE" "$DIR/.usb-err"' EXIT
fail() {
  echo "$(date '+%F %R')  COPY FAILED to \"$NAME\": $1" >> "$DIR/usb.log"
  [ -z "$VOLUMES" ] && osascript -e "display notification \"Copy to $NAME failed: $1\" with title \"The Crate\"" 2>/dev/null
  exit 1
}
[ -w "$DEST" ] || fail "the drive is read-only (locked, or formatted so a Mac can only read it, like NTFS). Use a drive formatted exFAT, FAT32 or Mac."
mkdir -p "$DEST/SoundCloud Sync" 2>"$DIR/.usb-err" || fail "couldn't make the SoundCloud Sync folder on it ($(tail -1 "$DIR/.usb-err"))."
# Only files that passed the safety check (safety.py) are copied. During a sync the check runs at its end.
kill -0 "$(cat "$DIR/.running" 2>/dev/null)" 2>/dev/null || python3 "$DIR/safety.py" check "$DIR" "$SRC" 2>>"$DIR/safety.log"
LIST="$DIR/.usb-list"
# "./" first: rsync would read a name starting with # or ; as a comment
cut -f1 "$DIR/safety-ok.tsv" 2>/dev/null | while IFS= read -r p; do [ -f "$SRC/$p" ] && echo "./$p"; done >"$LIST"
# Tracks not on the USB yet (counted before the copy, for the notice below)
NEW=$(while IFS= read -r p; do [ -e "$DEST/SoundCloud Sync/$p" ] || echo x; done <"$LIST" | wc -l | tr -d ' ')
echo "$$ copying $NEW" >"$STATE"
# To Buy.txt is The Crate's own list, so the USB always gets the latest one.
if rsync -a --ignore-existing --out-format='%n' --files-from="$LIST" "$SRC/" "$DEST/SoundCloud Sync/" \
     >"$DIR/.usb-progress" 2>"$DIR/.usb-err" &&
   { [ ! -f "$SRC/To Buy.txt" ] || cp "$SRC/To Buy.txt" "$DEST/SoundCloud Sync/To Buy.txt" 2>"$DIR/.usb-err"; }; then
  echo "$(date '+%F %R')  copied to \"$NAME\" ($NEW new)" >> "$DIR/usb.log"
else
  cat "$DIR/.usb-err" >> "$DIR/usb.log"
  [ -d "$DEST" ] || fail "it was unplugged before the copy finished. Plug it back in; it carries on."
  grep -q -i 'no space' "$DIR/.usb-err" && fail "the USB is full. Free up space on it, then Copy Now."
  grep -q -i 'read-only' "$DIR/.usb-err" && fail "the drive is read-only. Use a drive formatted exFAT, FAT32 or Mac."
  fail "$(grep -v '^rsync error' "$DIR/.usb-err" | tail -1 | sed 's/^rsync: //')"
fi
# New tracks landed: eject the USB (unless "Eject when done" is off on the page) and say it's safe to unplug.
if [ "$NEW" -gt 0 ] && [ -z "$VOLUMES" ]; then
  [ "$NEW" = 1 ] && MSG="1 new track on $NAME." || MSG="$NEW new tracks on $NAME."
  if [ ! -e "$DIR/usb-keep.txt" ]; then
    sync; diskutil eject "$DEST" >/dev/null 2>&1 && { MSG="$MSG Safe to unplug."; echo "$(date '+%F %R')  ejected \"$NAME\"" >> "$DIR/usb.log"; }
  fi
  osascript -e "display notification \"$MSG\" with title \"The Crate\" sound name \"Glass\"" 2>/dev/null
fi
