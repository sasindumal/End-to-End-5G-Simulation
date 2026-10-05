#!/usr/bin/env bash
RUN=/run/e2e5g
for p in $RUN/{amf,smf,upf-a,upf-b,nssf,bsf,pcf,udr,udm,ausf,scp,nrf}.pid; do
  [ -f "$p" ] && kill "$(cat "$p")" 2>/dev/null; rm -f "$p"
done
pkill -f 'open5gs-.*d -c /e2e5g' 2>/dev/null || true
sleep 1
