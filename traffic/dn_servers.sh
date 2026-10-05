#!/usr/bin/env bash
# Starts the external data-network services inside netns "dn".
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
PY=/opt/e2e5g-venv/bin/python
pkill -f "iperf3 -s" 2>/dev/null || true
pkill -f udp_echo.py 2>/dev/null || true
pkill -f iot_collector.py 2>/dev/null || true
for p in 5201 5202 5203 5204; do
  ip netns exec dn iperf3 -s -p $p -D
done
ip netns exec dn nohup $PY "$D/udp_echo.py" 9000 >/dev/null 2>&1 &
ip netns exec dn nohup $PY "$D/iot_collector.py" 9100 >/dev/null 2>&1 &
echo "DN services: iperf3 5201-5204, UDP echo 9000, IoT collector 9100 on 192.168.100.2"
