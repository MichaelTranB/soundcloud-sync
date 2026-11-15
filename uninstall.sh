#!/bin/zsh
# Removes The Crate: stops its background jobs and moves the app folder to the Trash.
# Your music in ~/Music/SoundCloud Sync stays where it is.
DIR="${0:A:h}"
for job in com.thecrate.app com.thecrate.sync com.thecrate.usb; do
  launchctl bootout "gui/$(id -u)/$job" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/$job.plist"
done
while security delete-generic-password -s soundcloud-sync-soulseek >/dev/null 2>&1; do :; done
# The virus scanner clamav.sh put in the home folder (never one from Homebrew or elsewhere).
for w in clamscan freshclam; do grep -qF "/.local/share/clamav/" "$HOME/.local/bin/$w" 2>/dev/null && rm -f "$HOME/.local/bin/$w"; done
[ -d "$HOME/.local/share/clamav" ] && mv "$HOME/.local/share/clamav" "$HOME/.Trash/ClamAV $(date +%s)"
[ -d "$HOME/Applications/The Crate.app" ] && mv "$HOME/Applications/The Crate.app" "$HOME/.Trash/The Crate $(date +%s).app"
mv "$DIR" "$HOME/.Trash/TheCrate $(date +%s)"
echo "The Crate is removed (its folder is in the Trash). Your music is still in Music > SoundCloud Sync."
echo "You can also remove Crate Helper from System Settings > Privacy & Security > Full Disk Access."
