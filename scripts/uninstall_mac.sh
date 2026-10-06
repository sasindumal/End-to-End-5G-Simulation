#!/usr/bin/env bash
# Completely removes the testbed VM from a Mac and gives the disk space back.
# Run on the Mac (not inside the VM), from anywhere:
#   bash scripts/uninstall_mac.sh            # asks for confirmation
#   bash scripts/uninstall_mac.sh --dry-run  # only shows what would be removed
#   bash scripts/uninstall_mac.sh --yes      # no prompt
#   bash scripts/uninstall_mac.sh --keep-lima  # delete VM + cache but keep Lima installed
# Removes: the "e2e5g" Lima VM (Ubuntu, Open5GS, UERANSIM, MongoDB, all VM data), Lima's
# download cache (Ubuntu image, nerdctl) and the Lima program (Homebrew).
# Does NOT touch this project folder: code, results/ and report/ stay on the Mac.
set -euo pipefail
VM=${VM:-e2e5g}
DRY=0; YES=0; KEEP_LIMA=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --keep-lima) KEEP_LIMA=1 ;;
    *) sed -n '2,10p' "$0"; exit 1 ;;
  esac
done
[ "$(uname -s)" = Darwin ] || { echo "Run this on the Mac host, not inside the VM."; exit 1; }

size() { [ -e "$1" ] && du -sh "$1" 2>/dev/null | cut -f1 || echo "-"; }
run()  { if [ "$DRY" = 1 ]; then echo "  would run: $*"; else echo "  running: $*"; "$@"; fi; }
HAVE_LIMA=0; command -v limactl >/dev/null 2>&1 && HAVE_LIMA=1
VM_DIR="$HOME/.lima/$VM"
CACHE="$HOME/Library/Caches/lima"

echo "This will permanently remove:"
echo "  VM '$VM'            $VM_DIR  ($(size "$VM_DIR"))"
echo "  Lima download cache $CACHE  ($(size "$CACHE"))"
if [ "$KEEP_LIMA" = 0 ] && command -v brew >/dev/null 2>&1 && brew list --versions lima >/dev/null 2>&1; then
  echo "  Lima program        $(brew list --versions lima)  ($(size "$(brew --cellar)/lima"))"
fi
echo "Free disk before: $(df -h / | awk 'NR==2{print $4}')"
echo "Not touched: $(cd "$(dirname "$0")/.." && pwd)"
echo

if [ "$DRY" = 0 ] && [ "$YES" = 0 ]; then
  read -r -p "Type 'delete' to continue: " ans
  [ "$ans" = delete ] || { echo "Cancelled, nothing removed."; exit 0; }
fi

# 1. the VM (stop first so its disk is released)
if [ "$HAVE_LIMA" = 1 ] && limactl list -q 2>/dev/null | grep -qx "$VM"; then
  run limactl stop -f "$VM" || true
  run limactl delete -f "$VM"
elif [ -d "$VM_DIR" ]; then
  run rm -rf "$VM_DIR"     # leftover directory without a working limactl
else
  echo "  VM '$VM' not found (already removed)"
fi

# 2. Lima's download cache (Ubuntu cloud image, nerdctl archive)
if [ "$HAVE_LIMA" = 1 ]; then
  run limactl prune || true
fi
[ -d "$CACHE" ] && run rm -rf "$CACHE"

# 3. the Lima program and its now-empty config directory
if [ "$KEEP_LIMA" = 0 ]; then
  if command -v brew >/dev/null 2>&1; then
    for f in lima-additional-guestagents lima; do
      brew list --versions "$f" >/dev/null 2>&1 && run brew uninstall "$f"
    done
  fi
  if [ -d "$HOME/.lima" ]; then
    others=$(find "$HOME/.lima" -mindepth 1 -maxdepth 1 ! -name _config ! -name "$VM" 2>/dev/null)
    if [ -z "$others" ]; then
      run rm -rf "$HOME/.lima"
    else
      echo "  kept ~/.lima: it still holds other VMs:"; echo "$others" | sed 's/^/    /'
    fi
  fi
fi

echo
if [ "$DRY" = 1 ]; then
  echo "Dry run only, nothing was removed."
else
  echo "Done. Free disk now: $(df -h / | awk 'NR==2{print $4}')"
  echo "To rebuild later, follow 'Quick start: macOS' in README.md."
fi
