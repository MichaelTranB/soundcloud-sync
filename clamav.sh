#!/bin/zsh
# The free ClamAV virus scanner for the safety check (safety.py), on a Mac without Homebrew: Cisco's own signed
# Mac package, unpacked into ~/.local/share/clamav (no password, nothing outside your home folder).
# Checked twice before anything runs: the file's fingerprint must match the one pinned here, and macOS must confirm
# Cisco's Apple-issued signature. Safe to run again; install.sh runs it. Then the virus list is fetched (freshclam).
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
VER=1.5.4 SHA=df7fa753e2f9f67f3bc99b2a40a3be7ef559088c68ad6bdf66b4b5764e965bd6
SIGNER="Developer ID Installer: Cisco (DE8Y96K9QP)"
H="$HOME/.local/share/clamav"
DIR="${0:A:h}"

# Already here (Homebrew's, the official install, or ours): nothing to do but keep the virus list fresh.
for c in /opt/homebrew/bin/clamscan /usr/local/bin/clamscan /usr/local/clamav/bin/clamscan "$H/bin/clamscan"; do
  [ -x "$c" ] && [ "$c" != "$H/bin/clamscan" -o "$(cat "$H/.version" 2>/dev/null)" = "$VER" ] && FOUND=1 && break
done
if [ -z "$FOUND" ]; then
  echo "Getting the virus scanner (ClamAV $VER, about 170 MB)..."
  T="$(mktemp -d)"; P="$T/clamav.pkg"; trap 'rm -rf "$T"' EXIT  # cleaned up on failure too
  curl -fsSL -o "$P" "https://github.com/Cisco-Talos/clamav/releases/download/clamav-$VER/clamav-$VER.macos.universal.pkg" ||
    { echo "Virus scanner download FAILED. Check the internet; the next install or the app's button tries again."; exit 1; }
  [ "$(shasum -a 256 "$P" | cut -d' ' -f1)" = "$SHA" ] || { echo "Virus scanner FAILED its fingerprint check; not installed."; exit 1; }
  pkgutil --check-signature "$P" | grep -qF "$SIGNER" || { echo "Virus scanner FAILED its signature check; not installed."; exit 1; }
  pkgutil --expand-full "$P" "$T/x" >/dev/null || { echo "Virus scanner couldn't be unpacked."; exit 1; }
  mkdir -p "$H/bin" "$H/lib" "$H/db" "$H/certs"
  for part in programs libraries; do
    S="$T/x/clamav-$VER.macos.universal-$part.pkg/Payload/usr/local/clamav"
    [ -d "$S/bin" ] && ditto "$S/bin" "$H/bin"
    [ -d "$S/lib" ] && find "$S/lib" -maxdepth 1 -name '*.dylib' -exec cp -RP {} "$H/lib/" \;
    [ -d "$S/etc/certs" ] && ditto "$S/etc/certs" "$H/certs"
  done
  # The package expects /usr/local/clamav (which needs a password): point the programs at their own lib folder
  # instead. That edit changes the files, so they're re-signed for this Mac only (macOS requires a signature).
  for b in clamscan freshclam; do
    install_name_tool -add_rpath @executable_path/../lib "$H/bin/$b" 2>/dev/null
    codesign --force --sign - "$H/bin/$b" 2>/dev/null
  done
  for l in "$H"/lib/*.dylib(N); do [ -L "$l" ] || codesign --force --sign - "$l" 2>/dev/null; done
  "$H/bin/clamscan" --version >/dev/null 2>&1 || { echo "Virus scanner installed but won't start; the safety check runs without it."; exit 1; }
  echo "$VER" >"$H/.version"
fi

# Short names the rest of The Crate uses, set to this copy's own virus list and settings. The scanner's name is only
# made once a virus list is here: without one it can't scan, and the safety check would hold every file back.
scanner() {
  local db=("$H"/db/*.c[vl]d(N)); (( $#db )) || return 0  # (N): no match is quiet in zsh
  printf '#!/bin/sh\nexport CVD_CERTS_DIR="%s/certs"\nexec "%s/bin/clamscan" --database="%s/db" "$@"\n' "$H" "$H" "$H" >"$HOME/.local/bin/clamscan"
  chmod +x "$HOME/.local/bin/clamscan"
}
if [ -x "$H/bin/clamscan" ]; then
  printf 'DatabaseDirectory %s\nDatabaseMirror database.clamav.net\n' "$H/db" >"$H/freshclam.conf"
  mkdir -p "$HOME/.local/bin"
  printf '#!/bin/sh\nexport CVD_CERTS_DIR="%s/certs"\nexec "%s/bin/freshclam" --config-file="%s/freshclam.conf" --cvdcertsdir="%s/certs" "$@"\n' "$H" "$H" "$H" "$H" >"$HOME/.local/bin/freshclam"
  chmod +x "$HOME/.local/bin/freshclam"
  scanner
fi
# The virus list itself (about 250 MB the first time; sync.sh runs this file daily to refresh it). ClamAV's servers
# limit how often: at most once in 20 hours, and only marked done when the list really loads.
if command -v freshclam >/dev/null && [ -z "$(find "$DIR/.virusdb" -mmin -1200 2>/dev/null)" ]; then
  echo "Getting the list of known viruses..."
  freshclam --quiet
  [ -x "$H/bin/clamscan" ] && scanner
  # (freshclam can report success without a usable list: the scanner's version line names the list it loaded.)
  clamscan --version 2>/dev/null | grep -q / && touch "$DIR/.virusdb" ||
    { echo "Virus list download FAILED; the next sync tries again."; exit 1; }
fi
