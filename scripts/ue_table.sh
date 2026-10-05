#!/usr/bin/env bash
# Prints UE -> RM state / PDU sessions (DNN, S-NSSAI, IP, tun interface) via nr-cli in netns "ran".
# FORMAT=csv prints machine-readable rows (used by the sandbox).
FMT=${FORMAT:-table}
[ "$FMT" = csv ] && echo "ue,supi,rm_state,psi,dnn,sst,sd,ip,iface" || \
  printf "%-9s %-21s %-14s %-4s %-9s %-4s %-7s %-12s %-10s\n" UE SUPI RM-STATE PSI DNN SST SD ADDRESS IFACE
for f in /run/e2e5g/ue-*.pid; do
  [ -f "$f" ] || continue
  u=$(basename "$f" .pid); u=${u#ue-}
  kill -0 "$(cat "$f")" 2>/dev/null || continue
  supi=$(awk -F"'" '/^supi/{print $2}' /e2e5g/configs/ueransim/ue-$u.yaml)
  st=$(ip netns exec ran nr-cli "$supi" -e status 2>/dev/null | awk '/rm-state/{print $2}')
  rows=$(ip netns exec ran nr-cli "$supi" -e ps-list 2>/dev/null | awk '
    /^PDU Session/{if(psi!="")print psi,apn,sst,sd,ip; psi=substr($2,8); sub(":","",psi); apn=sst=sd=ip="-"}
    /apn:/{apn=$2} /sst:/{sst=$2; sub("0x","",sst); sst=sst+0} /sd:/{sd=$2; sub("0x","",sd)} /address:/{ip=$2}
    END{if(psi!="")print psi,apn,sst,sd,ip}')
  [ -z "$rows" ] && rows="- - - - -"
  while read -r psi apn sst sd ip; do
    ifc=$(ip -n ran -o -4 addr show 2>/dev/null | awk -v a="$ip" '{split($4,x,"/")} x[1]==a {print $2}')
    if [ "$FMT" = csv ]; then echo "$u,$supi,${st:-?},$psi,$apn,$sst,$sd,$ip,${ifc:--}"
    else printf "%-9s %-21s %-14s %-4s %-9s %-4s %-7s %-12s %-10s\n" "$u" "$supi" "${st:-?}" "$psi" "$apn" "$sst" "$sd" "$ip" "${ifc:--}"; fi
  done <<< "$rows"
done
