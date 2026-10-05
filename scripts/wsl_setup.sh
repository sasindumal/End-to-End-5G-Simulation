#!/usr/bin/env bash
# Windows / WSL2 preparation — run once inside the WSL Ubuntu 24.04 shell, from the repo root:
#   bash scripts/wsl_setup.sh
# 1. enables systemd (needed for mongod), 2. links the repo to /e2e5g (the path every script uses),
# 3. checks for CRLF line endings, 4. tests that the WSL kernel has every feature the testbed needs.
# Safe to re-run; it changes nothing that is already correct.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
ok()   { printf '  \033[32m[ok]\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m[FAIL]\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0

echo "== Environment"
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  ok "WSL2 kernel $(uname -r)"
else
  warn "not running under WSL ($(uname -r)) — continuing with the checks anyway"
fi
. /etc/os-release
[ "${VERSION_ID:-}" = "24.04" ] && ok "$PRETTY_NAME ($(dpkg --print-architecture))" \
  || warn "$PRETTY_NAME — the testbed was validated on Ubuntu 24.04"
[ "$(nproc)" -ge 4 ] && ok "$(nproc) vCPUs" || warn "$(nproc) vCPUs — 4 recommended (see vm/wslconfig.example)"
mem=$(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo)
[ "$mem" -ge 5 ] && ok "${mem} GiB RAM" || warn "${mem} GiB RAM — 6 GiB recommended (see vm/wslconfig.example)"

echo "== systemd (MongoDB runs as a systemd service)"
if [ "$(ps -p 1 -o comm=)" = "systemd" ]; then
  ok "systemd is PID 1"
else
  if ! grep -q '^systemd=true' /etc/wsl.conf 2>/dev/null; then
    printf '[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf >/dev/null
    echo "         wrote [boot] systemd=true to /etc/wsl.conf"
  fi
  fail "systemd not active yet — in PowerShell run:  wsl --shutdown   then reopen Ubuntu and re-run this script"
fi

echo "== Repository location"
case "$REPO" in
  /mnt/*) warn "repo is on the Windows drive ($REPO): slow and permission-prone; clone it inside WSL (e.g. ~/) instead" ;;
  *)      ok "repo at $REPO" ;;
esac
if [ "$REPO" = /e2e5g ]; then
  ok "repo is mounted at /e2e5g"
elif [ -L /e2e5g ] && [ "$(readlink -f /e2e5g)" = "$REPO" ]; then
  ok "/e2e5g -> $REPO"
elif [ -e /e2e5g ]; then
  fail "/e2e5g exists and is not a link to this repo — move it away and re-run"
else
  sudo ln -s "$REPO" /e2e5g && ok "created /e2e5g -> $REPO"
fi

echo "== Line endings"
crlf=$(grep -rlI $'\r' "$REPO"/scripts "$REPO"/traffic "$REPO"/configs "$REPO"/sandbox "$REPO"/experiments "$REPO"/analysis 2>/dev/null)
if [ -z "$crlf" ]; then
  ok "no CRLF in scripts/configs"
else
  fail "CRLF line endings found (bash will break):"; echo "$crlf" | sed 's/^/           /'
  echo "         fix: git config core.autocrlf false && git rm -rq --cached . && git reset --hard"
fi

echo "== Kernel features (live tests, everything is cleaned up afterwards)"
sudo modprobe -q sctp 2>/dev/null; sudo modprobe -q sch_htb 2>/dev/null; sudo modprobe -q sch_netem 2>/dev/null
python3 - <<'P' && ok "SCTP sockets (N2 / NGAP)" || fail "SCTP not available — the gNB cannot reach the AMF"
import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_SCTP).close()
P
if sudo ip netns add e2e5g-test 2>/dev/null; then sudo ip netns del e2e5g-test; ok "network namespaces"
else fail "network namespaces"; fi
if sudo ip link add e2e5g-t0 type veth peer name e2e5g-t1 2>/dev/null; then
  ok "veth pairs"
  sudo tc qdisc add dev e2e5g-t0 root handle 1: htb default 10 2>/dev/null \
    && ok "tc HTB (per-slice rate)" || fail "tc HTB (sch_htb) — live slice MBR will not work"
  sudo tc class add dev e2e5g-t0 parent 1: classid 1:10 htb rate 10mbit 2>/dev/null
  sudo tc qdisc add dev e2e5g-t0 parent 1:10 handle 10: netem delay 1ms 2>/dev/null \
    && ok "tc netem (per-slice delay/loss)" || fail "tc netem (sch_netem) — live delay/loss will not work"
  sudo ip link del e2e5g-t0 2>/dev/null
else
  fail "veth pairs"
fi
if sudo ip tuntap add name e2e5g-tun mode tun 2>/dev/null; then sudo ip tuntap del name e2e5g-tun mode tun; ok "TUN devices (UPF / UE)"
else fail "TUN devices"; fi

echo
if [ "$FAILED" = 0 ]; then
  echo "All checks passed. Next:  bash /e2e5g/scripts/00_provision.sh   (see README, Windows section)"
else
  cat <<'EOF'
Some checks failed. systemd / CRLF / path issues are fixed by the hints above.
If SCTP or tc netem/HTB are missing, this WSL kernel lacks them. Options:
  * update WSL:  wsl --update   (in PowerShell), then re-run this script
  * run Ubuntu 24.04 in a normal VM (Hyper-V or VirtualBox) instead — its stock kernel has everything
  * build a custom WSL kernel with CONFIG_IP_SCTP, CONFIG_NET_SCH_HTB, CONFIG_NET_SCH_NETEM
EOF
  exit 1
fi
