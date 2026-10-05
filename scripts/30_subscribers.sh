#!/usr/bin/env bash
# Provisions subscribers in MongoDB (UDR). Each gets K/OPc and its permitted S-NSSAI + DNN.
set -euo pipefail
K=465B5CE8B199B49FAA5F0A2EE238A6BC
OPC=E8ED289DEBA952E4283B54E88E6183CA
DB=open5gs-dbctl
$DB reset >/dev/null || true
add() { $DB add_ue_with_slice "00101$1" $K $OPC "$2" "$3" "$4" >/dev/null; echo "  imsi-00101$1  dnn=$2 sst=$3 sd=$4"; }
add 0000000001 internet 1 000001   # eMBB UE 1
add 0000000002 internet 1 000001   # eMBB UE 2
add 0000000003 urllc    2 000002   # URLLC UE
add 0000000004 iot      3 000003   # mIoT gateway 1
add 0000000005 iot      3 000003   # mIoT gateway 2
add 0000000006 internet 1 000001   # multi-slice UE ...
$DB update_slice "001010000000006" urllc 2 000002 >/dev/null && echo "  imsi-001010000000006  + dnn=urllc sst=2 sd=000002"
add 0000000007 internet 1 000001   # negative test: only eMBB subscribed, UE asks for URLLC

# Per-slice QoS profile written into every session of that DNN (UDR -> PCF -> SMF):
#   eMBB : 5QI 9  (non-GBR, best-effort video/data), ARP 8,  Session-AMBR 200/50 Mbps
#   URLLC: 5QI 80 (non-GBR low-latency, 10 ms PDB),   ARP 1,  Session-AMBR 20/20 Mbps
#   mIoT : 5QI 9  (non-GBR),                          ARP 12, Session-AMBR 2/2 Mbps
mongosh --quiet open5gs --eval '
const prof = {
  internet: {q: 9,  arp: 8,  dl: 200, ul: 50},
  urllc:    {q: 80, arp: 1,  dl: 20,  ul: 20},
  iot:      {q: 9,  arp: 12, dl: 2,   ul: 2},
};
db.subscribers.find().forEach(sub => {
  sub.slice.forEach(sl => sl.session.forEach(se => {
    const p = prof[se.name];
    se.type = 3;
    se.qos = {index: p.q, arp: {priority_level: p.arp, pre_emption_capability: 1,
                                 pre_emption_vulnerability: 1}};
    se.ambr = {downlink: {value: p.dl, unit: 2}, uplink: {value: p.ul, unit: 2}};
    se.pcc_rule = se.pcc_rule || [];
  }));
  db.subscribers.replaceOne({_id: sub._id}, sub);
});
db.subscribers.find({}, {imsi: 1, "slice.sst": 1, "slice.sd": 1, "slice.session.name": 1,
  "slice.session.qos.index": 1, _id: 0}).forEach(d => print(JSON.stringify(d)));
'

