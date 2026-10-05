#!/usr/bin/env bash
# Starts the UERANSIM gNB and UEs inside netns "ran".
#   UES="embb1 embb2 urllc1 miot1 miot2 multi"  (default) — pass a subset to start fewer.
# Each UE is started from a runtime config that only lists sessions of slices that are up.
set -euo pipefail
CFG=/e2e5g/configs/ueransim
PY=/opt/e2e5g-venv/bin/python
RUN=/run/e2e5g; LOG=/var/log/ueransim; mkdir -p $RUN $LOG
UES=${UES:-"embb1 embb2 urllc1 miot1 miot2 multi"}

if ! [ -f $RUN/gnb.pid ] || ! kill -0 "$(cat $RUN/gnb.pid)" 2>/dev/null; then
  ip netns exec ran nohup nr-gnb -c $CFG/gnb.yaml >$LOG/gnb.log 2>&1 &
  echo $! > $RUN/gnb.pid
  sleep 2
fi
for u in $UES; do
  [ -f $RUN/ue-$u.pid ] && kill -0 "$(cat $RUN/ue-$u.pid)" 2>/dev/null && continue
  cfg=$($PY /e2e5g/scripts/ue_cfg.py "$u") || { echo "  $u: no active slice, left off"; continue; }
  ip netns exec ran nohup nr-ue -c "$cfg" >>$LOG/ue-$u.log 2>&1 &
  echo $! > $RUN/ue-$u.pid
  sleep 1.5
done
sleep ${SETTLE:-3}
[ "${QUIET:-0}" = 1 ] || bash /e2e5g/scripts/ue_table.sh
