#!/usr/bin/env bash
# start|stop a signalling + user-plane capture.
#   N2/N3 on n3-core (NGAP/SCTP 38412, GTP-U 2152), SBI (HTTP/2 :7777) and N4 (PFCP 8805) on lo.
#   Set SNAPLEN (e.g. 128) to truncate payloads on long traffic captures.
set -euo pipefail
OUT=${2:-/e2e5g/results/capture.pcapng}
case "${1:-start}" in
  start)
    mkdir -p "$(dirname "$OUT")"
    pkill -f "tshark -i n3-core" 2>/dev/null || true
    nohup tshark -i n3-core -i lo -s ${SNAPLEN:-0} \
      -f "sctp or udp port 2152 or udp port 8805 or tcp port 7777" \
      -w "$OUT" >/var/log/e2e5g-tshark.log 2>&1 &
    echo $! > /run/e2e5g/tshark.pid; sleep 2; echo "capturing -> $OUT" ;;
  stop)
    [ -f /run/e2e5g/tshark.pid ] && kill -INT "$(cat /run/e2e5g/tshark.pid)" 2>/dev/null || true
    sleep 2; rm -f /run/e2e5g/tshark.pid; echo "capture stopped" ;;
esac
