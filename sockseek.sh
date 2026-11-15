#!/bin/zsh
# sockseek (the Soulseek downloader, github.com/fiso64/sockseek): pinned release for this Mac's chip, checksum
# checked, into ~/.local/share (nothing outside your home folder, no password). Safe to run again: install.sh runs it,
# and sync.sh runs it every time, so a Mac where it's missing or out of date gets it on its next sync.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
SOCKSEEK_VER=3.0.6
if [ "$(uname -m)" = arm64 ]; then SOCKSEEK_OS=osx-arm64 SOCKSEEK_SHA=b7b9602b3ea0d8724b2a4dd1370c97f2f1f7175f901e7088dad714352c4926d9
else SOCKSEEK_OS=osx-x64 SOCKSEEK_SHA=6211374e1fca1f0b0bb4bfc6395e493c5969416e116a976f87bac4bdb99320fd; fi
[ "$("$HOME/.local/bin/sockseek" --version 2>/dev/null)" = "$SOCKSEEK_VER" ] && exit 0
# Each version gets its own folder and the short name is switched over at the end, so a sync searching Soulseek
# right now carries on with the copy it started with. (~/.local/share is made here: a new Mac doesn't have it.)
echo "Getting the Soulseek downloader (sockseek $SOCKSEEK_VER)..."
T="$(mktemp -d)"; F="$T/sockseek.tar.gz"; V="$HOME/.local/share/sockseek-$SOCKSEEK_VER"; trap 'rm -rf "$T"' EXIT
curl -fsSL -o "$F" "https://github.com/fiso64/sockseek/releases/download/v$SOCKSEEK_VER/sockseek_${SOCKSEEK_VER}_${SOCKSEEK_OS}.tar.gz" ||
  { echo "Soulseek downloader download FAILED. Check the internet; the next sync tries again."; exit 1; }
[ "$(shasum -a 256 "$F" | cut -d' ' -f1)" = "$SOCKSEEK_SHA" ] || { echo "Soulseek downloader FAILED its fingerprint check; not installed."; exit 1; }
mkdir -p "$T/x" "$HOME/.local/bin" "$HOME/.local/share" && tar xzf "$F" -C "$T/x" && rm -rf "$V" && mv "$T/x" "$V" &&
  ln -sfn "$V/sockseek" "$HOME/.local/bin/sockseek" || { echo "Soulseek downloader couldn't be put in place; the next sync tries again."; exit 1; }
"$HOME/.local/bin/sockseek" --version >/dev/null 2>&1 || { echo "Soulseek downloader installed but won't start."; exit 1; }
