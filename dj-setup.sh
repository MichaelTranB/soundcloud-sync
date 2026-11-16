#!/bin/zsh
# The DJ library's own Python (dj.py uses it for tempo and key, and for rekordbox's library): the official standalone
# Python 3.12 build, unpacked into ~/.local/share/crate-dj (no password, nothing outside your home folder, no
# Homebrew), with the packages in dj-requirements.txt. Checked before anything runs: the download's fingerprint must
# match the one pinned here, and every package must match its fingerprint in dj-requirements.txt.
# Safe to run again (does nothing when it's all there); install.sh and every sync run it. About 400 MB on disk.
# Without it The Crate still works: songs reach the decks unanalysed and the decks analyse them on load.
PYVER=3.12.16 PYTAG=20261110
case "$(uname -m)" in
  arm64) ARCH=aarch64 SHA=2f11b8aa3726bdbd87dd9eb76568412faddf4f47e26913fa45d6a2e424972acd ;;
  x86_64) ARCH=x86_64 SHA=b78a4c479f1964ec484880bee567568266f68da102269fb93a05fe8716b45f91 ;;
  *) echo "DJ SETUP PROBLEM: this Mac's chip isn't one the analyser knows."; exit 1 ;;
esac
DIR="${0:A:h}"
H="${CRATE_DJ_HOME:-$HOME/.local/share/crate-dj}"   # overridable for tests
WANT="$PYVER-$PYTAG $(shasum -a 256 "$DIR/dj-requirements.txt" | cut -d' ' -f1)"
[ -x "$H/python/bin/python3" ] && [ "$(cat "$H/.version" 2>/dev/null)" = "$WANT" ] && exit 0
# One setup at a time (a sync and the installer can both start one).
mkdir -p "$H"
if ! mkdir "$H/.setting-up" 2>/dev/null; then
  [ -n "$(find "$H/.setting-up" -maxdepth 0 -mmin -60 2>/dev/null)" ] && exit 0
fi
T="$(mktemp -d)"; trap 'rm -rf "$T"; rmdir "$H/.setting-up" 2>/dev/null' EXIT
fail() { echo "DJ SETUP PROBLEM: $1 Tempo, key and rekordbox wait; the next sync tries again."; exit 1; }
echo "Setting up the DJ library's analyser (a one-time download, a few minutes)..."
curl -fsSL -o "$T/python.tar.gz" "https://github.com/astral-sh/python-build-standalone/releases/download/$PYTAG/cpython-$PYVER+$PYTAG-$ARCH-apple-darwin-install_only_stripped.tar.gz" ||
  fail "the download didn't come through (check the internet)."
[ "$(shasum -a 256 "$T/python.tar.gz" | cut -d' ' -f1)" = "$SHA" ] || fail "the download failed its fingerprint check; nothing was installed."
tar -xzf "$T/python.tar.gz" -C "$T" || fail "the download couldn't be unpacked."
"$T/python/bin/python3" -m pip install -q --disable-pip-version-check --no-warn-script-location --no-deps \
  --only-binary :all: --require-hashes -r "$DIR/dj-requirements.txt" >"$T/pip.log" 2>&1 ||
  fail "a package didn't install ($(grep -i 'error' "$T/pip.log" | tail -1 | cut -c1-200))."
"$T/python/bin/python3" -c 'import essentia.standard, mutagen, pyrekordbox' >/dev/null 2>"$T/try.log" ||
  fail "the analyser was installed but won't start ($(tail -1 "$T/try.log" | cut -c1-200))."
# In place only once it's whole; what was there before (an older version, or the first build's folder) goes to the Trash.
for old in python venv; do
  [ -e "$H/$old" ] && mv "$H/$old" "$HOME/.Trash/crate-dj $old $(date +%s)"
done
mv "$T/python" "$H/python" && echo "$WANT" >"$H/.version" || fail "couldn't put it in place."
echo "The DJ library's analyser is ready."
