#!/bin/zsh
# Sets up the three background jobs on this Mac: the page (always on), the nightly sync, and the
# copy-to-USB that fires whenever a drive is plugged in. Safe to run again.
DIR="${0:A:h}"
AGENTS="$HOME/Library/LaunchAgents"
command -v yt-dlp >/dev/null || brew install yt-dlp
# sockseek (Soulseek downloader, github.com/fiso64/sockseek): pinned release, checksum checked.
SOCKSEEK_VER=3.0.6 SOCKSEEK_SHA=b7b9602b3ea0d8724b2a4dd1370c97f2f1f7175f901e7088dad714352c4926d9
if [ "$("$HOME/.local/bin/sockseek" --version 2>/dev/null)" != "$SOCKSEEK_VER" ]; then
  T="$(mktemp -d)"; F="$T/sockseek.tar.gz"
  curl -fsSL -o "$F" "https://github.com/fiso64/sockseek/releases/download/v$SOCKSEEK_VER/sockseek_${SOCKSEEK_VER}_osx-arm64.tar.gz" &&
    [ "$(shasum -a 256 "$F" | cut -d' ' -f1)" = "$SOCKSEEK_SHA" ] &&
    mkdir -p "$HOME/.local/share/sockseek" "$HOME/.local/bin" && tar xzf "$F" -C "$HOME/.local/share/sockseek" &&
    ln -sf "$HOME/.local/share/sockseek/sockseek" "$HOME/.local/bin/sockseek" || echo "sockseek install FAILED (download or checksum)"
  rm -rf "$T"
fi
# ClamAV, the free virus scanner the safety check (safety.py) uses, through Homebrew when this Mac has it.
# Without it the check still blocks anything that isn't real audio.
if command -v brew >/dev/null; then
  command -v clamscan >/dev/null || brew install clamav
  CONF="$(brew --prefix)/etc/clamav"
  if [ -f "$CONF/freshclam.conf.sample" ] && [ ! -f "$CONF/freshclam.conf" ]; then
    sed 's/^Example/#Example/' "$CONF/freshclam.conf.sample" > "$CONF/freshclam.conf"
    freshclam --quiet && touch "$DIR/.virusdb"
  fi
fi
chmod +x "$DIR"/*.sh
mkdir -p "$AGENTS" "$HOME/Music/SoundCloud Sync"

# Crate Helper (crate-helper.c): the three jobs start through it, so one Full Disk Access switch for it
# (System Settings > Privacy & Security > Full Disk Access) lets yt-dlp read the SoundCloud sign-in already in
# Chrome or Safari, which macOS otherwise blocks. Rebuilt only when its source changes: to macOS a rebuilt
# helper is a new program, and the switch would have to be turned on again.
APPDIR="$DIR/Crate Helper.app"
HELPER="$APPDIR/Contents/MacOS/crate-helper"
SRC_SHA="$(shasum -a 256 "$DIR/crate-helper.c" | cut -d' ' -f1)"
if [ ! -x "$HELPER" ] || [ "$(cat "$DIR/.crate-helper.sha" 2>/dev/null)" != "$SRC_SHA" ]; then
  mkdir -p "$APPDIR/Contents/MacOS"
  cat > "$APPDIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.thecrate.helper</string>
<key>CFBundleName</key><string>Crate Helper</string>
<key>CFBundleExecutable</key><string>crate-helper</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>LSBackgroundOnly</key><true/>
</dict></plist>
EOF
  if clang -O2 -Wall -o "$HELPER" "$DIR/crate-helper.c" &&
     codesign --force --sign - --identifier com.thecrate.helper "$APPDIR"; then
    echo "$SRC_SHA" > "$DIR/.crate-helper.sha"
    echo "Crate Helper built. Turn it on once: System Settings > Privacy & Security > Full Disk Access."
  else
    echo "Crate Helper build FAILED (needs the Xcode command line tools); the jobs start without it"
    rm -f "$HELPER"
  fi
fi
# The program a job runs: through the helper when it's there, else directly.
run() { if [ -x "$HELPER" ]; then echo "<string>$HELPER</string><string>$1</string>"; else echo "$2"; fi; }

# Jobs from before the rename: stop and remove them so nothing runs twice.
for old in com.michael.soundcloud-sync.app com.michael.soundcloud-sync com.michael.soundcloud-sync.usb; do
  launchctl bootout "gui/$(id -u)/$old" 2>/dev/null; rm -f "$AGENTS/$old.plist"
done
PY="$(for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do [ -x "$p" ] && echo "$p" && break; done)"

job() { # label, body
  local p="$AGENTS/$1.plist"
  cat > "$p" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$1</string>
$2
<key>StandardOutPath</key><string>$DIR/launchd.log</string>
<key>StandardErrorPath</key><string>$DIR/launchd.log</string>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$p"
}

job com.thecrate.app "<key>ProgramArguments</key><array>$(run app "<string>$PY</string><string>$DIR/app.py</string>")</array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
job com.thecrate.sync "<key>ProgramArguments</key><array>$(run sync "<string>$DIR/sync.sh</string>")</array>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>10</integer></dict>"
job com.thecrate.usb "<key>ProgramArguments</key><array>$(run usb "<string>$DIR/usb.sh</string>")</array>
<key>StartOnMount</key><true/>"
echo "Open http://localhost:4780"
