#!/usr/bin/env python3
"""URLLC traffic: periodic small UDP packets (default 100 Hz x 64 B, i.e. a motion-control
loop) sent from the UE address to the DN echo server. Reports RTT p50/p99, jitter and loss
every second."""
import argparse, select, socket, struct, time
from kpi import KpiWriter, percentile

ap = argparse.ArgumentParser()
ap.add_argument("--bind", required=True, help="UE IP (uesimtun address)")
ap.add_argument("--dst", default="192.168.100.2")
ap.add_argument("--port", type=int, default=9000)
ap.add_argument("--rate", type=float, default=100.0, help="packets per second")
ap.add_argument("--size", type=int, default=64)
ap.add_argument("--duration", type=float, default=0, help="0 = run until killed")
ap.add_argument("--slice", default="URLLC")
ap.add_argument("--out", required=True)
a = ap.parse_args()

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind((a.bind, 0))
s.setblocking(False)
kw = KpiWriter(a.out, a.slice, a.bind)
pad = b"\0" * max(0, a.size - 12)
period = 1.0 / a.rate
seq, sent_in_win, rtts, outstanding = 0, 0, [], {}
t0 = time.monotonic()
next_tx, next_report = t0, t0 + 1.0
while a.duration == 0 or time.monotonic() - t0 < a.duration:
    now = time.monotonic()
    if now >= next_tx:
        s.sendto(struct.pack("!Id", seq, now) + pad, (a.dst, a.port))
        outstanding[seq] = now
        seq += 1
        sent_in_win += 1
        next_tx += period
    try:
        while True:
            data = s.recv(2048)
            t_rx = time.monotonic()
            sq, ts = struct.unpack("!Id", data[:12])
            if outstanding.pop(sq, None) is not None:
                rtts.append((t_rx - ts) * 1000.0)
    except BlockingIOError:
        pass
    if now >= next_report:
        # packets older than 1 s without echo are counted as lost
        lost = [k for k, v in outstanding.items() if now - v > 1.0]
        for k in lost:
            outstanding.pop(k)
        jitter = sum(abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))) / max(1, len(rtts) - 1)
        kw.write(rtt_p50_ms=percentile(rtts, 50), rtt_p99_ms=percentile(rtts, 99),
                 jitter_ms=float(jitter), loss_pct=100.0 * len(lost) / max(1, sent_in_win),
                 throughput_mbps=sent_in_win * a.size * 8 / 1e6, msgs=len(rtts))
        rtts, sent_in_win = [], 0
        next_report += 1.0
    # block until the next TX/report deadline *or* an echo arrives, so RTT is not quantised
    select.select([s], [], [], max(0.0, min(next_tx, next_report) - time.monotonic()))
