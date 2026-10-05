#!/usr/bin/env python3
"""eMBB traffic: iperf3 TCP downlink (DN -> UE, i.e. video/file download) with an on/off
temporal profile (default 20 s on / 5 s off, like segment-based adaptive video).
Parses iperf3 per-second output and writes throughput KPIs."""
import argparse, re, subprocess, time, signal, sys
from kpi import KpiWriter

ap = argparse.ArgumentParser()
ap.add_argument("--bind", required=True)
ap.add_argument("--dst", default="192.168.100.2")
ap.add_argument("--port", type=int, default=5201)
ap.add_argument("--on", type=int, default=20)
ap.add_argument("--off", type=int, default=5)
ap.add_argument("--streams", type=int, default=1)
ap.add_argument("--uplink", action="store_true", help="UE -> DN instead of downlink")
ap.add_argument("--udp-mbit", type=float, default=0,
                help="fixed-rate UDP flood instead of TCP (controlled offered load, E5)")
ap.add_argument("--duration", type=float, default=0)
ap.add_argument("--slice", default="eMBB")
ap.add_argument("--out", required=True)
a = ap.parse_args()

kw = KpiWriter(a.out, a.slice, a.bind)
line_re = re.compile(r"\[(SUM|\s*\d+)\]\s+([\d.]+)-([\d.]+)\s+sec\s+[\d.]+\s+\w?Bytes\s+([\d.]+)\s+(\w?)bits/sec")
scale = {"K": 1e-3, "M": 1.0, "G": 1e3, "": 1e-6}
proc = None


def stop(*_):
    if proc and proc.poll() is None:
        proc.terminate()
    sys.exit(0)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
t0 = time.monotonic()
while a.duration == 0 or time.monotonic() - t0 < a.duration:
    on = a.on if a.duration == 0 else min(a.on, max(1, int(a.duration - (time.monotonic() - t0))))
    cmd = ["iperf3", "-c", a.dst, "-p", str(a.port), "-B", a.bind, "-t", str(on), "-i", "1",
           "-P", str(a.streams), "--forceflush"] + ([] if a.uplink else ["-R"])
    if a.udp_mbit:
        cmd += ["-u", "-b", f"{a.udp_mbit / a.streams:.1f}M", "-l", "1200"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        m = line_re.search(line)
        if not m or "sender" in line or "receiver" in line:
            continue
        if a.streams > 1 and m.group(1) != "SUM":
            continue
        if float(m.group(3)) - float(m.group(2)) < 0.5:   # drop iperf3's short trailing interval
            continue
        kw.write(throughput_mbps=float(m.group(4)) * scale.get(m.group(5), 1e-6))
    proc.wait()
    if a.duration and time.monotonic() - t0 >= a.duration:
        break
    for _ in range(a.off):  # idle period: explicit zero samples
        kw.write(throughput_mbps=0.0)
        time.sleep(1)
