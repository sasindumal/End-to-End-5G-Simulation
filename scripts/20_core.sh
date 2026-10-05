#!/usr/bin/env bash
# Starts the Open5GS 5GC with the repo configs.
#   MODE=dedicated (default): URLLC on its own UPF-B
#   MODE=shared             : all slices on UPF-A (experiment E5)
set -euo pipefail
MODE=${MODE:-dedicated}
CFG=/e2e5g/configs/open5gs
RUN=/run/e2e5g; mkdir -p $RUN /var/log/open5gs

start() { # name binary config
  nohup "$2" -c "$3" >/var/log/open5gs/$1.stdout 2>&1 &
  echo $! > $RUN/$1.pid
}

bash /e2e5g/scripts/stop_core.sh >/dev/null 2>&1 || true
systemctl is-active --quiet mongod || systemctl start mongod

start nrf  open5gs-nrfd  $CFG/nrf.yaml;  sleep 1
start scp  open5gs-scpd  $CFG/scp.yaml;  sleep 1
for nf in ausf udm udr pcf nssf bsf; do start $nf open5gs-${nf}d $CFG/$nf.yaml; done
if [ "$MODE" = shared ]; then
  start upf-a open5gs-upfd $CFG/upf-a-shared.yaml
  start smf   open5gs-smfd $CFG/smf-shared.yaml
else
  start upf-a open5gs-upfd $CFG/upf-a.yaml
  start upf-b open5gs-upfd $CFG/upf-b.yaml
  start smf   open5gs-smfd $CFG/smf.yaml
fi
sleep 1
start amf open5gs-amfd $CFG/amf.yaml
echo "$MODE" > $RUN/core.mode
sleep 2
for p in $RUN/*.pid; do
  n=$(basename "$p" .pid); kill -0 "$(cat "$p")" 2>/dev/null && echo "  [up]   $n" || echo "  [DOWN] $n"
done
