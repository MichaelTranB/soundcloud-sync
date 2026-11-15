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
chmod +x "$DIR"/*.sh
mkdir -p "$AGENTS" "$HOME/Music/SoundCloud Sync"

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

job com.michael.soundcloud-sync.app "<key>ProgramArguments</key><array><string>/opt/homebrew/bin/python3</string><string>$DIR/app.py</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
job com.michael.soundcloud-sync "<key>ProgramArguments</key><array><string>$DIR/sync.sh</string></array>
<key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>10</integer></dict>"
job com.michael.soundcloud-sync.usb "<key>ProgramArguments</key><array><string>$DIR/usb.sh</string></array>
<key>StartOnMount</key><true/>"
echo "Open http://localhost:4780"
