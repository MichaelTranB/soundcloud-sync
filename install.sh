#!/bin/zsh
# Sets up the three background jobs on this Mac: the page (always on), the nightly sync, and the
# copy-to-USB that fires whenever a drive is plugged in. Safe to run again.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DIR="${0:A:h}"
AGENTS="$HOME/Library/LaunchAgents"
# yt-dlp (the SoundCloud downloader): the copy already on this Mac, else the official Mac build, checksum checked.
# No Homebrew needed. sync.sh keeps it current every week.
YTDLP_VER=2026.10.26 YTDLP_SHA=0f922c15ccc0b83eefa1c8bc9104e434318c4bf16e408e1ee93b7745a6efe0aa
if ! command -v yt-dlp >/dev/null; then
  T="$(mktemp -d)"
  curl -fsSL -o "$T/yt-dlp" "https://github.com/yt-dlp/yt-dlp/releases/download/$YTDLP_VER/yt-dlp_macos" &&
    [ "$(shasum -a 256 "$T/yt-dlp" | cut -d' ' -f1)" = "$YTDLP_SHA" ] &&
    mkdir -p "$HOME/.local/bin" && chmod +x "$T/yt-dlp" && mv "$T/yt-dlp" "$HOME/.local/bin/yt-dlp" ||
    echo "yt-dlp install FAILED (download or checksum)"
  rm -rf "$T"
fi
# sockseek (Soulseek downloader, github.com/fiso64/sockseek): pinned release for this Mac's chip, checksum checked.
SOCKSEEK_VER=3.0.6
if [ "$(uname -m)" = arm64 ]; then SOCKSEEK_OS=osx-arm64 SOCKSEEK_SHA=b7b9602b3ea0d8724b2a4dd1370c97f2f1f7175f901e7088dad714352c4926d9
else SOCKSEEK_OS=osx-x64 SOCKSEEK_SHA=6211374e1fca1f0b0bb4bfc6395e493c5969416e116a976f87bac4bdb99320fd; fi
if [ "$("$HOME/.local/bin/sockseek" --version 2>/dev/null)" != "$SOCKSEEK_VER" ]; then
  T="$(mktemp -d)"; F="$T/sockseek.tar.gz"
  curl -fsSL -o "$F" "https://github.com/fiso64/sockseek/releases/download/v$SOCKSEEK_VER/sockseek_${SOCKSEEK_VER}_${SOCKSEEK_OS}.tar.gz" &&
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
  NEW_HELPER=1
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

# "The Crate" in Applications (and Launchpad): opens the page.
APP="$HOME/Applications/The Crate.app"
if [ ! -d "$APP" ] && mkdir -p "$HOME/Applications" && osacompile -o "$APP" -e 'open location "http://localhost:4780"'; then
  IS="$(mktemp -d)/crate.iconset"; mkdir -p "$IS"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$DIR/icon.png" --out "$IS/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$DIR/icon.png" --out "$IS/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$IS" -o "$APP/Contents/Resources/applet.icns" && touch "$APP"
  rm -rf "${IS:h}"
fi

echo "Done. The Crate is at http://localhost:4780 (or open The Crate from Applications)."
# Run from get.sh (a friend's first install): open the page, and the one macOS switch the helper needs.
if [ -n "$CRATE_OPEN" ]; then
  sleep 2; open "http://localhost:4780"
  if [ -n "$NEW_HELPER" ] && [ -x "$HELPER" ]; then
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"; open -R "$APPDIR"
    echo "Last step: drag \"Crate Helper\" from the Finder window into the Full Disk Access list, and switch it on."
  fi
fi
