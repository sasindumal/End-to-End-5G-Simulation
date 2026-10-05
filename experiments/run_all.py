#!/usr/bin/env python3
"""Scripted experiments E1-E5 (run as root inside the VM):

    sudo /opt/e2e5g-venv/bin/python /e2e5g/experiments/run_all.py [E1 E3 E4 E5 E6]

Every experiment writes into /e2e5g/results/<exp>/ : kpi_*.csv, events.csv, logs, pcaps.
"""
import os
import shutil
import sys
import time

sys.path.insert(0, "/e2e5g/sandbox")
import testbed as tb  # noqa: E402

RES = "/e2e5g/results"
ALL_UES = "embb1 embb2 urllc1 miot1 miot2 multi"


def fresh_dir(name):
    d = f"{RES}/{name}"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def stop_all_traffic(d=None):
    for s in tb.SLICES:
        tb.stop_traffic(s, d)


def restart_testbed(mode="dedicated", ues=ALL_UES, capture=None):
    """Full clean restart: RAN down, core restarted, slices up, qdiscs at defaults."""
    stop_all_traffic()
    tb.sh("bash /e2e5g/scripts/stop_ran.sh")
    tb.sh("rm -f /run/e2e5g/state-* /run/e2e5g/qos-*")
    tb.sh("bash /e2e5g/scripts/10_netns.sh")
    tb.sh("bash /e2e5g/scripts/slice_ctl.sh clear; bash /e2e5g/scripts/slice_ctl.sh init")
    tb.sh(f"MODE={mode} bash /e2e5g/scripts/20_core.sh", check=True)
    time.sleep(2)
    if capture:
        tb.sh(f"bash /e2e5g/scripts/50_capture.sh start {capture}")
    out = tb.sh(f"UES='{ues}' bash /e2e5g/scripts/40_ran.sh", timeout=120)
    tb.sh("bash /e2e5g/traffic/dn_servers.sh")
    return out


def set_ambr(dnn, dl_mbps, ul_mbps):
    """Rewrite the Session-AMBR of every session with this DNN in the UDR (MongoDB)."""
    js = ("db.subscribers.find().forEach(s=>{s.slice.forEach(sl=>sl.session.forEach(se=>{"
          f"if(se.name=='{dnn}'){{se.ambr={{downlink:{{value:{dl_mbps},unit:2}},uplink:{{value:{ul_mbps},unit:2}}}}}}"
          "}));db.subscribers.replaceOne({_id:s._id},s)})")
    tb.sh(f"mongosh --quiet open5gs --eval \"{js}\"", check=True)


def at(t0, t):
    """Sleep until t seconds after t0."""
    time.sleep(max(0, t0 + t - time.time()))


# ------------------------------------------------------------------------------ E1/E2
def e1_connectivity():
    """Registration + PDU sessions with signalling capture, then per-slice reachability."""
    d = fresh_dir("e1")
    pcap = f"{d}/attach.pcapng"
    out = restart_testbed(ues=ALL_UES + " badslice", capture=pcap)
    open(f"{d}/ue_table.txt", "w").write(out)
    time.sleep(3)
    # user-plane evidence: pings from every PDU session while the capture still runs
    lines = []
    for _, r in tb.ue_sessions().iterrows():
        if not r.ip[0].isdigit():
            continue
        p = tb.sh(f"ip netns exec ran ping -c 10 -i 0.2 -I {r.iface} {tb.DN}")
        lines.append(f"### {r.ue} {r.dnn} SST{r.sst} {r.ip} via {r.iface}\n{p}")
    open(f"{d}/ping.txt", "w").write("\n".join(lines))
    tb.sh("bash /e2e5g/scripts/50_capture.sh stop")
    # HTTP + iperf3 from one UE per slice
    rep = []
    # the "ran" namespace has no resolver, so resolve once in the core namespace
    web = tb.sh("getent ahostsv4 example.com | head -1 | cut -d' ' -f1").strip()
    for s, ue in [("eMBB", "embb1"), ("URLLC", "urllc1"), ("mIoT", "miot1")]:
        ip = tb.ue_ip(ue, tb.SLICES[s]["dnn"])
        rep.append(f"### {s} {ue} {ip} iperf3 downlink 5 s\n" +
                   tb.sh(f"ip netns exec ran iperf3 -c {tb.DN} -B {ip} -R -t 5"))
        rep.append(f"### {s} {ue} {ip} internet via N6 NAT\n" +
                   tb.sh(f"ip netns exec ran curl -s -m 5 -o /dev/null -w '%{{http_code}} %{{time_total}}s\\n' "
                         f"--interface {ip} --resolve example.com:80:{web} http://example.com"))
    open(f"{d}/iperf_http.txt", "w").write("\n".join(rep))
    tb.sh("bash /e2e5g/scripts/ue_table.sh > " + f"{d}/ue_table.txt")
    # topology snapshot
    topo = tb.sh("echo '## ran'; ip -n ran -br addr; ip -n ran rule; echo '## core'; ip -br addr; "
                 "ip route; echo '## dn'; ip -n dn -br addr; ip -n dn route; "
                 "echo '## sctp'; ss -Sanp | head")
    open(f"{d}/topology.txt", "w").write(topo)
    # negative test UE off again; copy logs
    tb.sh("kill $(cat /run/e2e5g/ue-badslice.pid); rm -f /run/e2e5g/ue-badslice.pid")
    for f in ["amf", "smf", "upf-a", "upf-b", "nssf"]:
        shutil.copy(f"/var/log/open5gs/{f}.log", f"{d}/{f}.log")
    for f in ["gnb", "ue-multi", "ue-badslice", "ue-urllc1"]:
        shutil.copy(f"/var/log/ueransim/{f}.log", f"{d}/{f}.log")
    print("E1 done")


# ------------------------------------------------------------------------------ E3
def e3_isolation():
    """URLLC + mIoT alone, then eMBB saturating load joins (t=30..90), then leaves."""
    d = fresh_dir("e3")
    tb.log_event(d, "phase", "URLLC+mIoT only")
    t0 = time.time()
    tb.start_traffic("URLLC", d, {"rate": 100, "size": 64}, duration=120)
    tb.start_traffic("mIoT", d, {"devices": 500, "period": 5.0}, duration=120)
    at(t0, 30)
    tb.log_event(d, "phase", "eMBB saturating load on")
    tb.start_traffic("eMBB", d, {"on": 60, "off": 0, "streams": 4}, duration=60)
    at(t0, 90)
    tb.log_event(d, "phase", "eMBB off")
    at(t0, 122)
    stop_all_traffic(d)
    print("E3 done")


# ------------------------------------------------------------------------------ E4
def e4_live_change():
    """Live slice-parameter changes while all three slices carry traffic."""
    d = fresh_dir("e4")
    tb.set_qos("eMBB", 150, 0, 0, d)
    tb.set_qos("URLLC", 20, 0, 0, d)
    t0 = time.time()
    tb.start_traffic("eMBB", d, {"on": 120, "off": 0, "streams": 2}, duration=120)
    tb.start_traffic("URLLC", d, duration=120)
    tb.start_traffic("mIoT", d, duration=120)
    at(t0, 40)
    tb.set_qos("eMBB", 30, 0, 0, d)          # eMBB slice MBR 150 -> 30 Mbit/s
    at(t0, 80)
    tb.set_qos("URLLC", 20, 5, 0, d)         # URLLC +5 ms each way (transport budget test)
    at(t0, 122)
    stop_all_traffic(d)
    tb.set_qos("eMBB", 150, 0, 0)
    tb.set_qos("URLLC", 20, 0, 0)
    print("E4 done")


# ------------------------------------------------------------------------------ E5
E5_UDP = float(os.environ.get("E5_UDP_MBIT", "500"))   # per eMBB UE, downlink


def e5_upf_sharing(reps=int(os.environ.get("E5_REPS", "3"))):
    """URLLC latency under eMBB overload with dedicated UPF-B vs URLLC moved onto UPF-A.
    Modes alternate (d, s, d, s, ...) so slow drifts of the host affect both equally."""
    for rep, mode in [(r, m) for r in range(1, reps + 1) for m in ["dedicated", "shared"]]:
        d = fresh_dir(f"e5_{mode}_r{rep}")
        set_ambr("internet", 10000, 10000)   # lift eMBB Session-AMBR for the overload test
        restart_testbed(mode=mode, ues="embb1 embb2 urllc1")
        tb.set_qos("eMBB", 10000, 0, 0)      # and the tc cap -> UPF-A/gNB become CPU bound
        time.sleep(2)
        open(f"{d}/ue_table.txt", "w").write(tb.sh("bash /e2e5g/scripts/ue_table.sh"))
        t0 = time.time()
        tb.log_event(d, "phase", f"{mode}: URLLC only")
        tb.start_traffic("URLLC", d, {"rate": 200, "size": 64}, duration=90)
        at(t0, 20)
        tb.log_event(d, "phase", f"{mode}: eMBB overload on")
        # fixed offered load (UDP) so both modes see exactly the same eMBB pressure
        tb.start_traffic("eMBB", d, {"on": 60, "off": 0, "streams": 4, "udp_mbit": E5_UDP}, duration=60)
        at(t0, 50)
        tb.sh(f"top -bn2 -d 2 -w 160 -o %CPU | awk '/^top -/{{n++}} n==2' | head -22 > {d}/top_under_load.txt")
        at(t0, 92)
        stop_all_traffic(d)
    set_ambr("internet", 200, 50)
    restart_testbed()  # back to the reference (dedicated) configuration
    print("E5 done")


# ------------------------------------------------------------------------------ E6
def e6_baseline_profiles():
    """Scenario S1: all slices with their nominal temporal profiles (traffic-behaviour figure)."""
    d = fresh_dir("e6")
    tb.apply_scenario("S1 Baseline (each slice nominal)", d)
    time.sleep(90)
    stop_all_traffic(d)
    print("E6 done")


if __name__ == "__main__":
    todo = sys.argv[1:] or ["E1", "E3", "E4", "E6", "E5"]
    fns = {"E1": e1_connectivity, "E3": e3_isolation, "E4": e4_live_change,
           "E5": e5_upf_sharing, "E6": e6_baseline_profiles}
    tb.sh("bash /e2e5g/scripts/versions.sh")
    for e in todo:
        print(f"== {e}", flush=True)
        fns[e]()
