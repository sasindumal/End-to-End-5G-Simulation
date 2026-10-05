#!/usr/bin/env bash
for p in /run/e2e5g/ue-*.pid /run/e2e5g/gnb.pid; do
  [ -f "$p" ] && kill "$(cat "$p")" 2>/dev/null; rm -f "$p"
done
pkill -f "nr-ue -c" 2>/dev/null; pkill -f "nr-gnb -c" 2>/dev/null; sleep 1; true
# UERANSIM leaves its per-session policy-routing rules behind; flush them so stale
# "from <old-ip> lookup rt_uesimtunN" entries never shadow a new session.
ip netns exec ran ip rule show 2>/dev/null | awk -F: '$1>0 && $1<32766 {print $1}' | \
  while read -r p; do ip netns exec ran ip rule del priority "$p" 2>/dev/null; done
true
