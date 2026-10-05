#!/usr/bin/env bash
# Slice control plane for the testbed.
#   slice_ctl.sh init                         install default per-slice qdiscs
#   slice_ctl.sh set  <slice> <rate_mbit> <delay_ms> <loss_pct>   live change (DL + UL)
#   slice_ctl.sh show [slice]                 print qdisc/class stats
#   slice_ctl.sh up|down <slice>              establish / release that slice's PDU sessions
# Downlink is shaped on the slice's UPF tun device (kernel -> UPF), uplink on the N6 veth
# (n6-core egress) with one HTB class per UE pool.
set -euo pipefail
Y=/e2e5g/configs/slices.yaml
PY=/opt/e2e5g-venv/bin/python
get() { $PY -c "import yaml,sys;s=yaml.safe_load(open('$Y'))['slices']['$1'];print(eval(sys.argv[1]))" "$2"; }
ALL="eMBB URLLC mIoT"

apply() { # slice rate delay loss
  local s=$1 rate=$2 delay=$3 loss=$4 tun cls subnet
  tun=$(get "$s" "s['tun']"); cls=$(get "$s" "s['classid']"); subnet=$(get "$s" "s['subnet']")
  local nargs="delay ${delay}ms"; [ "$(echo "$loss > 0" | bc)" = 1 ] && nargs="$nargs loss ${loss}%"
  # --- downlink: root HTB on the tun device
  if ! tc qdisc show dev "$tun" | grep -q "htb 1:"; then
    tc qdisc replace dev "$tun" root handle 1: htb default 10
    tc class add dev "$tun" parent 1: classid 1:10 htb rate "${rate}mbit" ceil "${rate}mbit" burst 64k
    tc qdisc add dev "$tun" parent 1:10 handle 10: netem $nargs limit 10000
  else
    tc class change dev "$tun" parent 1: classid 1:10 htb rate "${rate}mbit" ceil "${rate}mbit" burst 64k
    tc qdisc change dev "$tun" parent 1:10 handle 10: netem $nargs limit 10000
  fi
  # --- uplink: per-slice class on n6-core
  if ! tc qdisc show dev n6-core | grep -q "htb 1:"; then
    tc qdisc replace dev n6-core root handle 1: htb default 99
    tc class add dev n6-core parent 1: classid 1:99 htb rate 10gbit
  fi
  if tc class show dev n6-core | grep -q "1:$cls "; then
    tc class change dev n6-core parent 1: classid 1:$cls htb rate "${rate}mbit" ceil "${rate}mbit" burst 64k
    tc qdisc change dev n6-core parent 1:$cls handle $cls: netem $nargs limit 10000
  else
    tc class add dev n6-core parent 1: classid 1:$cls htb rate "${rate}mbit" ceil "${rate}mbit" burst 64k
    tc qdisc add dev n6-core parent 1:$cls handle $cls: netem $nargs limit 10000
    tc filter add dev n6-core parent 1: protocol ip prio 1 u32 match ip src "$subnet" flowid 1:$cls
  fi
  mkdir -p /run/e2e5g
  echo "$rate $delay $loss" > /run/e2e5g/qos-$s
  echo "$s: rate=${rate}Mbit/s delay=${delay}ms loss=${loss}% (DL on $tun, UL on n6-core 1:$cls)"
}

ue_stop() { # ue — graceful switch-off deregistration, then stop the process
  local u=$1 supi
  [ -f /run/e2e5g/ue-$u.pid ] || return 0
  supi=$(awk -F"'" '/^supi/{print $2}' /e2e5g/configs/ueransim/ue-$u.yaml)
  ip netns exec ran nr-cli "$supi" -e "deregister switch-off" >/dev/null 2>&1 || true
  sleep 0.5
  kill "$(cat /run/e2e5g/ue-$u.pid)" 2>/dev/null || true
  rm -f /run/e2e5g/ue-$u.pid
}

ps_ctl() { # slice up|down — UERANSIM re-creates released sessions automatically, so a slice is
  # taken down by re-attaching its UEs with a config that no longer contains that slice.
  local s=$1 dir=$2 u
  mkdir -p /run/e2e5g; echo "$dir" > /run/e2e5g/state-$s
  for u in $(get "$s" "' '.join(s['ues'])"); do
    if [ "$dir" = down ] && [ ! -f /run/e2e5g/ue-$u.pid ]; then continue; fi
    ue_stop "$u"
  done
  sleep 1
  UES="$(get "$s" "' '.join(s['ues'])")" QUIET=1 SETTLE=2 bash /e2e5g/scripts/40_ran.sh
  echo "$s is $dir"
}

case "${1:-}" in
  init)  for s in $ALL; do apply "$s" $(get "$s" "s['defaults']['rate_mbit']") \
           $(get "$s" "s['defaults']['delay_ms']") $(get "$s" "s['defaults']['loss_pct']"); done ;;
  set)   apply "$2" "$3" "$4" "$5" ;;
  up|down) ps_ctl "$2" "$1" ;;
  show)  for s in ${2:-$ALL}; do t=$(get "$s" "s['tun']"); echo "== $s ($t)"; tc -s qdisc show dev "$t"; done
         echo "== n6-core"; tc -s class show dev n6-core ;;
  clear) for s in $ALL; do tc qdisc del dev "$(get "$s" "s['tun']")" root 2>/dev/null || true; rm -f /run/e2e5g/qos-$s; done
         tc qdisc del dev n6-core root 2>/dev/null || true ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
