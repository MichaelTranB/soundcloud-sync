#!/bin/zsh
# One-time Soulseek sign-in for The Crate. Soulseek makes the account the first time a new name signs in,
# so pick a name nobody has and a NEW password you use nowhere else. Both go into the Keychain only.
SERVICE=soundcloud-sync-soulseek
SOCKSEEK="$HOME/.local/bin/sockseek"
read "SUSER?Soulseek username (new or existing): "
[ -z "$SUSER" ] && { echo "No name given; nothing changed."; exit 1; }
while security delete-generic-password -s "$SERVICE" >/dev/null 2>&1; do :; done
echo "Now type the password (it won't show), then type it again:"
security add-generic-password -U -s "$SERVICE" -a "$SUSER" -T /usr/bin/security -w || { echo "Not saved."; exit 1; }
echo "Saved in the Keychain. Checking the sign-in with one test search..."
OUT="$("$SOCKSEEK" "Daft Punk - Around the World" -s --print results --no-config --no-progress \
  --user "$SUSER" --pass "$(security find-generic-password -s "$SERVICE" -w)" 2>&1)"
if echo "$OUT" | grep -q -i -E "invalid ?pass|login failed|logged out|unauthor"; then
  echo "Soulseek said no: that name is taken with a different password. Run this again with another name."; exit 1
elif echo "$OUT" | grep -q -i -E "error|exception"; then
  echo "Couldn't check it right now:"; echo "$OUT" | grep -i -E "error|exception" | tail -2; exit 1
fi
echo "Signed in. The Crate will look on Soulseek for anything still to get on the next sync."
