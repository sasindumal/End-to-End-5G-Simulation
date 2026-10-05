#!/usr/bin/env python3
"""Control experiment E7: is the 'lower RTT under load' effect a CPU idle-state artefact?
URLLC probe for 90 s; t=30..60 s four pure CPU busy-loops run in the core namespace
(no network traffic at all)."""
import multiprocessing as mp, os, sys, time
sys.path.insert(0, "/e2e5g/sandbox")
import testbed as tb

def burn(stop):
    while time.time() < stop:
        pass

d = "/e2e5g/results/e7"
os.system(f"rm -rf {d}; mkdir -p {d}")
tb.log_event(d, "phase", "idle")
t0 = time.time()
tb.start_traffic("URLLC", d, {"rate": 100, "size": 64}, duration=90)
time.sleep(max(0, t0 + 30 - time.time()))
tb.log_event(d, "phase", "cpu busy-loop on")
ps = [mp.Process(target=burn, args=(time.time() + 30,)) for _ in range(4)]
[p.start() for p in ps]; [p.join() for p in ps]
tb.log_event(d, "phase", "cpu busy-loop off")
time.sleep(max(0, t0 + 92 - time.time()))
tb.stop_traffic("URLLC", d)
print("E7 done")
