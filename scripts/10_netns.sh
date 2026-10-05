#!/usr/bin/env bash
# Builds the three-domain topology inside the VM:
#   netns "ran"  : gNB + UEs (uesimtun* live here)          10.10.0.2
#   root ns      : 5G core (AMF N2 / UPF N3 on veth n3-core)  10.10.0.1 (UPF-A), 10.10.0.3 (UPF-B)
#   netns "dn"   : external data network (servers)          192.168.100.2
# plus the UPF tun devices (one per DNN) and routes for the UE pools.
set -euo pipefail

ip netns add ran 2>/dev/null || true
ip netns add dn  2>/dev/null || true

# --- N2/N3 link: core <-> RAN ---------------------------------------------
if ! ip link show n3-core >/dev/null 2>&1; then
  ip link add n3-core type veth peer name n3-ran
  ip link set n3-ran netns ran
fi
ip addr replace 10.10.0.1/24 dev n3-core          # AMF NGAP + UPF-A GTP-U
ip addr replace 10.10.0.3/24 dev n3-core          # UPF-B GTP-U (dedicated URLLC UPF)
ip link set n3-core up
ip -n ran addr replace 10.10.0.2/24 dev n3-ran    # gNB N2/N3 address
ip -n ran link set n3-ran up
ip -n ran link set lo up

# --- N6 link: core <-> data network ----------------------------------------
if ! ip link show n6-core >/dev/null 2>&1; then
  ip link add n6-core type veth peer name n6-dn
  ip link set n6-dn netns dn
fi
ip addr replace 192.168.100.1/24 dev n6-core
ip link set n6-core up
ip -n dn addr replace 192.168.100.2/24 dev n6-dn
ip -n dn link set n6-dn up
ip -n dn link set lo up
# the DN only knows how to reach UE pools through the core
ip -n dn route replace 10.45.0.0/16 via 192.168.100.1
ip -n dn route replace 10.46.0.0/16 via 192.168.100.1
ip -n dn route replace 10.47.0.0/16 via 192.168.100.1
ip -n dn route replace default via 192.168.100.1

# --- UPF tun devices: one per DNN -----------------------------------------
mk_tun() { # name gateway/prefix
  ip tuntap add name "$1" mode tun 2>/dev/null || true
  ip addr replace "$2" dev "$1"
  ip link set "$1" up
}
mk_tun ogstun  10.45.0.1/16   # DNN internet (eMBB) on UPF-A
mk_tun ogstun2 10.46.0.1/16   # DNN urllc   (URLLC) on UPF-B
mk_tun ogstun3 10.47.0.1/16   # DNN iot     (mIoT)  on UPF-A

sysctl -qw net.ipv4.ip_forward=1
# UE pools may also reach the Internet through the VM uplink (NAT)
for p in 10.45.0.0/16 10.46.0.0/16 10.47.0.0/16; do
  iptables -t nat -C POSTROUTING -s "$p" ! -d 192.168.100.0/24 ! -o ogstun+ -j MASQUERADE 2>/dev/null || \
  iptables -t nat -A POSTROUTING -s "$p" ! -d 192.168.100.0/24 ! -o ogstun+ -j MASQUERADE
done
iptables -P FORWARD ACCEPT
echo "netns topology ready"
