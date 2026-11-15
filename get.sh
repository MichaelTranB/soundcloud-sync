#!/bin/zsh
# The Crate, installed with one line pasted into Terminal:
#   curl -fsSL https://raw.githubusercontent.com/MichaelTranB/soundcloud-sync/main/get.sh | zsh
# Run the same line again any time to update. Nothing here needs a password.
D="${CRATE_DIR:-$HOME/TheCrate}"
if ! xcode-select -p >/dev/null 2>&1; then
  echo "First, your Mac needs Apple's free command line tools (about 5 minutes)."
  echo "A window is opening: click Install, wait until it says it's done, then paste the same line again."
  xcode-select --install
  exit 0
fi
if [ -d "$D/.git" ]; then
  echo "Updating The Crate in $D ..."
  git -C "$D" pull -q --ff-only || { echo "Couldn't update. Check the internet and try again."; exit 1; }
else
  echo "Downloading The Crate into $D ..."
  git clone -q https://github.com/MichaelTranB/soundcloud-sync.git "$D" || {
    echo "Couldn't download it. Check the internet and try again."; exit 1; }
fi
CRATE_OPEN=1 zsh "$D/install.sh"
