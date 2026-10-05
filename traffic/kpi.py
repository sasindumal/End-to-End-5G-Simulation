"""Shared helper: append one per-second KPI row to a CSV that the sandbox and analysis read."""
import csv, os, time

FIELDS = ["ts", "slice", "ue_ip", "throughput_mbps", "rtt_p50_ms", "rtt_p99_ms",
          "jitter_ms", "loss_pct", "msgs"]


class KpiWriter:
    def __init__(self, path, slice_name, ue_ip):
        self.slice, self.ue_ip = slice_name, ue_ip
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        new = not os.path.exists(path)
        self.f = open(path, "a", newline="")
        self.w = csv.DictWriter(self.f, fieldnames=FIELDS)
        if new:
            self.w.writeheader()

    def write(self, **kv):
        row = {k: "" for k in FIELDS}
        row.update(ts=f"{time.time():.3f}", slice=self.slice, ue_ip=self.ue_ip)
        row.update({k: (f"{v:.3f}" if isinstance(v, float) else v) for k, v in kv.items()})
        self.w.writerow(row)
        self.f.flush()


def percentile(vals, p):
    if not vals:
        return float("nan")
    v = sorted(vals)
    k = (len(v) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)
