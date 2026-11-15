#!/bin/zsh
# Sets up the three background jobs on this Mac: the page (always on), the nightly sync, and the
# copy-to-USB that fires whenever a drive is plugged in. Safe to run again.
DIR="${0:A:h}"
AGENTS="$HOME/Library/LaunchAgents"
command -v yt-dlp >/dev/null || brew install yt-dlp
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
