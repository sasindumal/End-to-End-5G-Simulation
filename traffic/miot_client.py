#!/usr/bin/env python3
"""mIoT traffic: N virtual sensors behind one UE, each sending a ~100 B JSON report with a
Poisson (exponential inter-arrival) process, mean period P seconds. Reports msgs/s,
ACK latency and loss each second."""
import argparse, json, random, select, socket, struct, time, heapq
from kpi import KpiWriter, percentile

ap = argparse.ArgumentParser()
ap.add_argument("--bind", required=True)
ap.add_argument("--dst", default="192.168.100.2")
ap.add_argument("--port", type=int, default=9100)
ap.add_argument("--devices", type=int, default=200)
ap.add_argument("--period", type=float, default=10.0, help="mean report interval per device [s]")
ap.add_argument("--duration", type=float, default=0)
ap.add_argument("--slice", default="mIoT")
ap.add_argument("--out", required=True)
a = ap.parse_args()

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind((a.bind, 0))
s.setblocking(False)
kw = KpiWriter(a.out, a.slice, a.bind)
t0 = time.monotonic()
events = [(t0 + random.expovariate(1 / a.period), d) for d in range(a.devices)]
heapq.heapify(events)
seq, pending, lat, sent, nbytes = 0, {}, [], 0, 0
next_report = t0 + 1.0
while a.duration == 0 or time.monotonic() - t0 < a.duration:
    now = time.monotonic()
    while events and events[0][0] <= now:
        _, dev = heapq.heappop(events)
        body = json.dumps({"dev": dev, "temp": round(random.gauss(24, 2), 2),
                           "batt": random.randint(10, 100)}).encode()
        pkt = struct.pack("!IIq", dev, seq, int(now * 1e6)) + body
        s.sendto(pkt, (a.dst, a.port))
        pending[seq] = now
        seq += 1; sent += 1; nbytes += len(pkt)
        heapq.heappush(events, (now + random.expovariate(1 / a.period), dev))
    try:
        while True:
            ack = s.recv(64)
            t_rx = time.monotonic()
            _, sq, _ = struct.unpack("!IIq", ack[:16])
            ts = pending.pop(sq, None)
            if ts is not None:
                lat.append((t_rx - ts) * 1000.0)
    except BlockingIOError:
        pass
    if now >= next_report:
        lost = [k for k, v in pending.items() if now - v > 2.0]
        for k in lost:
            pending.pop(k)
        kw.write(msgs=sent, rtt_p50_ms=percentile(lat, 50), rtt_p99_ms=percentile(lat, 99),
                 loss_pct=100.0 * len(lost) / max(1, sent), throughput_mbps=nbytes * 8 / 1e6)
        lat, sent, nbytes = [], 0, 0
        next_report += 1.0
    deadline = min(events[0][0] if events else next_report, next_report)
    select.select([s], [], [], max(0.0, deadline - time.monotonic()))
