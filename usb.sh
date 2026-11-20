#!/bin/zsh
# Copies the music folder to the chosen USB when it is plugged in. Runs after every sync and whenever
# any drive is mounted, so tracks downloaded while the USB was away land on it the next time it appears.
# Only ever ADDS tracks: no track on the USB is deleted or overwritten. Only music goes on it: the to-buy list stays
# on the Mac (the page shows it), and the list older versions put on the USB is taken off. A USB that already has things
# on it is asked about on the page first (usb_ask.py). The one exception is a song
# you threw back on the page ("Wrong or bad file"): its copy here goes to the USB's own Trash, and on a USB that
# already held songs, another download of a library song is swapped for the library's file and a double of one is
# taken off, both to that Trash as well (usb_tidy.py). Songs that aren't from this library are left alone.
# Before any of that, what the decks saved on the USB is backed up to this Mac (backup.py: it only reads the USB).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="${0:A:h}"
SRC="${SRC:-$HOME/Music/SoundCloud Sync}"   # both overridable for tests
NAME="$(cat "$DIR/usb.txt" 2>/dev/null)"
[ -z "$NAME" ] && exit 0
DEST="${VOLUMES:-/Volumes}/$NAME"
[ -d "$DEST" ] || { echo "$(date '+%F %R')  USB \"$NAME\" not plugged in; will copy when it is" >> "$DIR/usb.log"; exit 0; }
# First, before anything on it is changed: what your decks saved on it since last time (hot cues, playlists, history)
# is copied to this Mac (backup.py: it only reads the USB), so a USB that goes wrong can be put back as it was.
python3 "$DIR/backup.py" run "$DIR" "$DEST" "$SRC" 2>>"$DIR/dj.log"
# A USB that already has things on it is changed only after your OK on the page (usb_ask.py): until then nothing on
# it is touched. An empty one needs no asking, and neither does one The Crate was already copying to before it asked.
python3 "$DIR/usb_ask.py" check "$DIR" "$DEST" || {
  tail -1 "$DIR/usb.log" 2>/dev/null | grep -q "waiting for your OK" || \
    echo "$(date '+%F %R')  USB \"$NAME\" already has things on it: waiting for your OK on the page" >> "$DIR/usb.log"
  exit 0
}
# One copy at a time (a sync, a plugged-in drive and the Copy Now button can all start one). While it runs,
# .usb-copy says how far it is ("pid stage new-tracks") and .usb-progress lists each file copied: the page shows both.
STATE="$DIR/.usb-copy"
kill -0 "$(cut -d' ' -f1 "$STATE" 2>/dev/null)" 2>/dev/null && exit 0
echo "$$ checking 0" >"$STATE"; : >"$DIR/.usb-progress"
trap 'rm -f "$STATE" "$DIR/.usb-err"' EXIT
# A copy while a sync is still getting tracks (not the sync's own last one) never ejects: more tracks are coming, and
# the page copies them over as they arrive. The sync's last copy ejects once, at the end.
MID=""; [ -z "$CRATE_FINAL" ] && kill -0 "$(cat "$DIR/.running" 2>/dev/null)" 2>/dev/null && MID=1
fail() {
  echo "$(date '+%F %R')  COPY FAILED to \"$NAME\": $1" >> "$DIR/usb.log"
  [ -z "$VOLUMES" ] && osascript -e "display notification \"Copy to $NAME failed: $1\" with title \"The Crate\"" 2>/dev/null
  exit 1
}
[ -w "$DEST" ] || fail "the drive is read-only (locked, or formatted so a Mac can only read it, like NTFS). Use a drive formatted exFAT, FAT32 or Mac."
# The Crate's own folder on the USB: "SoundCloud Sync" at its top, or where you chose on the Library Manager page
# (place.py). A new choice moves that one folder first; the decks' lists follow in dj.py below.
SAID="$(python3 "$DIR/place.py" move "$DEST" 2>&1)"; [ -n "$SAID" ] && echo "$(date '+%F %R')  USB \"$NAME\": $SAID" >> "$DIR/usb.log"
CRATE="$(python3 "$DIR/place.py" where "$DEST" 2>/dev/null)"; [ -n "$CRATE" ] || CRATE="$DEST/SoundCloud Sync"
mkdir -p "$CRATE" 2>"$DIR/.usb-err" || fail "couldn't make The Crate's folder on it ($(tail -1 "$DIR/.usb-err"))."
# FLACs that arrived since the last time become AIFFs first (aiff.py: the same sound, in a file every deck plays), so
# the USB gets the AIFF and never both. Not while a sync is still getting songs: that sync does it at its end.
PY="$HOME/.local/share/crate-dj/python/bin/python3"; [ -x "$PY" ] || PY="$HOME/.local/share/crate-dj/venv/bin/python"
[ -z "$MID" ] && [ -x "$PY" ] && "$PY" "$DIR/aiff.py" auto "$DIR" "$SRC" 2>>"$DIR/dj.log"
# Then a new song's missing cover and details are filled in (details.py: only empty fields, each one undoable), so
# the USB gets the finished file.
[ -z "$MID" ] && [ -x "$PY" ] && "$PY" "$DIR/details.py" auto "$DIR" "$SRC" 2>>"$DIR/dj.log"
# First, inside that folder only: a song you threw back on the page goes to the USB's Trash, and Soulseek songs that
# sat in a folder of their own move in with the rest (so the copy below doesn't put them on it a second time).
python3 "$DIR/usb_tidy.py" "$DIR" "$SRC" "$CRATE" >>"$DIR/usb.log" 2>&1
# Only files that passed the safety check (safety.py) are copied. During a sync the check runs at its end.
kill -0 "$(cat "$DIR/.running" 2>/dev/null)" 2>/dev/null || python3 "$DIR/safety.py" check "$DIR" "$SRC" 2>>"$DIR/safety.log"
LIST="$DIR/.usb-list"
# "./" first: rsync would read a name starting with # or ; as a comment
cut -f1 "$DIR/safety-ok.tsv" 2>/dev/null | while IFS= read -r p; do [ -f "$SRC/$p" ] && echo "./$p"; done >"$LIST"
TOTAL=$(wc -l <"$LIST" | tr -d ' ')
# Only the tracks not on the USB yet are copied, and counted for the notice below. On a USB laid out in folders
# (layout.py: by genre, picked on the Library Manager page) a song already in its folder counts as on it; a new one
# lands in the main folder and dj.py files it right after.
python3 "$DIR/layout.py" missing "$CRATE" <"$LIST" >"$LIST.new" && mv "$LIST.new" "$LIST"
NEW=$(wc -l <"$LIST" | tr -d ' ')
echo "$$ copying $NEW" >"$STATE"
rm -f "$CRATE/To Buy.txt"  # The Crate's own list, put there by older versions: not music
if rsync -a --ignore-existing --out-format='%n' --files-from="$LIST" "$SRC/" "$CRATE/" \
     >"$DIR/.usb-progress" 2>"$DIR/.usb-err"; then
  echo "$(date '+%F %R')  copied to \"$NAME\" ($NEW new, $TOTAL on it${MID:+, sync still running})" >> "$DIR/usb.log"
  touch "$DIR/.usb-done"
  [ -n "$MID" ] && [ "$NEW" -gt 0 ] && touch "$DIR/.usb-mid"  # tracks went on mid-sync: the last copy ejects
  # The decks' libraries (dj.py): the tracks now on the USB join its Engine DJ library, and rekordbox on this Mac
  # catches up. Before any eject, and not back until it's written. A sync does the listening itself, at its end.
  [ -z "$MID" ] && VOLUMES="${VOLUMES:-/Volumes}" python3 "$DIR/dj.py" "$DIR" "$SRC" --wait 2>>"$DIR/dj.log"
else
  cat "$DIR/.usb-err" >> "$DIR/usb.log"
  [ -d "$DEST" ] || fail "it was unplugged before the copy finished. Plug it back in; it carries on."
  grep -q -i 'no space' "$DIR/.usb-err" && fail "the USB is full. Free up space on it, then Copy Now."
  grep -q -i 'read-only' "$DIR/.usb-err" && fail "the drive is read-only. Use a drive formatted exFAT, FAT32 or Mac."
  fail "$(grep -v '^rsync error' "$DIR/.usb-err" | tail -1 | sed 's/^rsync: //')"
fi
# New tracks landed: say so, and eject the USB only if "Eject" is ticked on the page (off unless chosen).
if [ -n "$MID" ]; then
  [ "$NEW" -gt 0 ] && [ -z "$VOLUMES" ] && osascript -e "display notification \"$NEW new on $NAME so far. Still syncing: keep it plugged in.\" with title \"The Crate\"" 2>/dev/null
elif { [ "$NEW" -gt 0 ] || [ -e "$DIR/.usb-mid" ]; } && [ -z "$VOLUMES" ]; then
  rm -f "$DIR/.usb-mid"
  [ "$NEW" = 0 ] && MSG="All $TOTAL tracks on $NAME." || { [ "$NEW" = 1 ] && MSG="1 new track on $NAME." || MSG="$NEW new tracks on $NAME."; }
  if [ -e "$DIR/usb-eject.txt" ]; then
    sync; diskutil eject "$DEST" >/dev/null 2>&1 && { MSG="$MSG Safe to unplug."; echo "$(date '+%F %R')  ejected \"$NAME\"" >> "$DIR/usb.log"; }
  fi
  osascript -e "display notification \"$MSG\" with title \"The Crate\" sound name \"Glass\"" 2>/dev/null
fi
exit 0
