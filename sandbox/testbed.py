"""Control library for the E2E 5G testbed (runs as root inside the VM).

Used by both the Streamlit sandbox (sandbox/app.py) and the scripted experiments
(experiments/run_all.py), so the demo and the measured results go through one code path.
"""
import csv
import glob
import io
import os
import signal
import subprocess
import time
import zipfile

import pandas as pd
import yaml

ROOT = "/e2e5g"
RUN = "/run/e2e5g"
PY = "/opt/e2e5g-venv/bin/python"
SLICES = yaml.safe_load(open(f"{ROOT}/configs/slices.yaml"))["slices"]
DN = "192.168.100.2"

# Traffic plan: which UE carries which generator, and the DN port it uses
TRAFFIC = {
    "eMBB": [("embb1", 5201), ("embb2", 5202)],
    "URLLC": [("urllc1", 9000)],
    "mIoT": [("miot1", 9100), ("miot2", 9100)],
}
DEFAULT_PARAMS = {
    "eMBB": {"on": 20, "off": 5, "streams": 2},
    "URLLC": {"rate": 100, "size": 64},
    "mIoT": {"devices": 200, "period": 10.0},
}

# Scenario presets for the sandbox: QoS per slice + which slices carry traffic
SCENARIOS = {
    "S1 Baseline (each slice nominal)": {
        "qos": {"eMBB": (150, 0, 0), "URLLC": (20, 0, 0), "mIoT": (5, 0, 0)},
        "traffic": {"eMBB": {"on": 20, "off": 5, "streams": 2}, "URLLC": {"rate": 100, "size": 64},
                    "mIoT": {"devices": 200, "period": 10.0}},
    },
    "S2 Smart-factory peak (eMBB saturating)": {
        "qos": {"eMBB": (300, 0, 0), "URLLC": (20, 0, 0), "mIoT": (5, 0, 0)},
        "traffic": {"eMBB": {"on": 3600, "off": 0, "streams": 4}, "URLLC": {"rate": 200, "size": 64},
                    "mIoT": {"devices": 500, "period": 5.0}},
    },
    "S3 Degraded transport (eMBB 10 ms / 1 % loss)": {
        "qos": {"eMBB": (50, 10, 1.0), "URLLC": (20, 0, 0), "mIoT": (5, 0, 0)},
        "traffic": {"eMBB": {"on": 20, "off": 5, "streams": 2}, "URLLC": {"rate": 100, "size": 64},
                    "mIoT": {"devices": 200, "period": 10.0}},
    },
    "S4 Massive IoT burst": {
        "qos": {"eMBB": (150, 0, 0), "URLLC": (20, 0, 0), "mIoT": (2, 0, 0)},
        "traffic": {"URLLC": {"rate": 100, "size": 64}, "mIoT": {"devices": 3000, "period": 2.0}},
    },
}


def sh(cmd, check=False, timeout=60):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd}\n{r.stdout}\n{r.stderr}")
    return r.stdout + r.stderr


# --------------------------------------------------------------------------- status
def core_status():
    out = {}
    for nf in ["nrf", "scp", "ausf", "udm", "udr", "pcf", "nssf", "bsf", "smf", "amf", "upf-a", "upf-b", "gnb"]:
        p = f"{RUN}/{nf}.pid"
        out[nf] = os.path.exists(p) and _alive(int(open(p).read()))
    return out


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ue_sessions():
    txt = sh("FORMAT=csv bash /e2e5g/scripts/ue_table.sh")
    rows = list(csv.DictReader(io.StringIO(txt[txt.find("ue,"):])))
    return pd.DataFrame(rows)


def ue_ip(ue, dnn):
    df = ue_sessions()
    if df.empty:
        return None
    m = df[(df.ue == ue) & (df.dnn == dnn) & (df.ip.str.match(r"\d+\.\d+\.\d+\.\d+"))]
    return None if m.empty else m.iloc[0].ip


def slice_state(name):
    p = f"{RUN}/state-{name}"
    return open(p).read().strip() if os.path.exists(p) else "up"


def get_qos(name):
    p = f"{RUN}/qos-{name}"
    if os.path.exists(p):
        r, d, l = open(p).read().split()
        return float(r), float(d), float(l)
    d = SLICES[name]["defaults"]
    return d["rate_mbit"], d["delay_ms"], d["loss_pct"]


# --------------------------------------------------------------------------- events
def new_run(tag="run"):
    rid = time.strftime("%Y%m%d-%H%M%S") + f"-{tag}"
    d = f"{ROOT}/results/runs/{rid}"
    os.makedirs(d, exist_ok=True)
    with open(f"{RUN}/current_run", "w") as f:
        f.write(d)
    return d


def current_run():
    p = f"{RUN}/current_run"
    if os.path.exists(p) and os.path.isdir(open(p).read().strip()):
        return open(p).read().strip()
    return new_run("sandbox")


def log_event(run_dir, action, detail=""):
    p = f"{run_dir}/events.csv"
    new = not os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "action", "detail"])
        w.writerow([f"{time.time():.3f}", action, detail])


# --------------------------------------------------------------------------- control
def set_qos(name, rate, delay, loss, run_dir=None):
    out = sh(f"bash /e2e5g/scripts/slice_ctl.sh set {name} {rate} {delay} {loss}", check=True)
    if run_dir:
        log_event(run_dir, "qos", f"{name} rate={rate} delay={delay} loss={loss}")
    return out


def slice_updown(name, up, run_dir=None):
    if not up:
        stop_traffic(name, run_dir)
    out = sh(f"bash /e2e5g/scripts/slice_ctl.sh {'up' if up else 'down'} {name}", timeout=120)
    if run_dir:
        log_event(run_dir, "slice_up" if up else "slice_down", name)
    return out


def _tpid(name):
    return f"{RUN}/traffic-{name}.pids"


def traffic_running(name):
    p = _tpid(name)
    if not os.path.exists(p):
        return False
    return any(_alive(int(x)) for x in open(p).read().split())


def start_traffic(name, run_dir, params=None, duration=0):
    if traffic_running(name):
        return "already running"
    params = {**DEFAULT_PARAMS[name], **(params or {})}
    dnn = SLICES[name]["dnn"]
    pids, msgs = [], []
    for ue, port in TRAFFIC[name]:
        ip = ue_ip(ue, dnn)
        if not ip:
            msgs.append(f"{ue}: no {dnn} session")
            continue
        out = f"{run_dir}/kpi_{name}.csv"
        if name == "eMBB":
            args = (f"traffic/embb.py --bind {ip} --port {port} --on {params['on']} "
                    f"--off {params['off']} --streams {params['streams']}")
            if params.get("udp_mbit"):
                args += f" --udp-mbit {params['udp_mbit']}"
        elif name == "URLLC":
            args = f"traffic/urllc_probe.py --bind {ip} --rate {params['rate']} --size {params['size']}"
        else:
            args = f"traffic/miot_client.py --bind {ip} --devices {params['devices']} --period {params['period']}"
        cmd = (f"ip netns exec ran {PY} {ROOT}/{args} --slice {name} --out {out} "
               f"--duration {duration}")
        p = subprocess.Popen(cmd.split(), cwd=f"{ROOT}/traffic", start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=open(f"{run_dir}/traffic_{name}.err", "a"))
        pids.append(p.pid)
        msgs.append(f"{ue} ({ip})")
    with open(_tpid(name), "w") as f:
        f.write(" ".join(map(str, pids)))
    log_event(run_dir, "traffic_start", f"{name} {params}")
    return "started: " + ", ".join(msgs)


def stop_traffic(name, run_dir=None):
    p = _tpid(name)
    if os.path.exists(p):
        for x in open(p).read().split():
            try:
                os.killpg(int(x), signal.SIGTERM)
            except OSError:
                pass
        os.remove(p)
        if run_dir:
            log_event(run_dir, "traffic_stop", name)


def apply_scenario(key, run_dir):
    sc = SCENARIOS[key]
    log_event(run_dir, "scenario", key)
    for name in SLICES:
        stop_traffic(name, run_dir)
    for name, (r, d, l) in sc["qos"].items():
        set_qos(name, r, d, l, run_dir)
    msgs = []
    for name, params in sc["traffic"].items():
        if slice_state(name) == "up":
            msgs.append(f"{name}: " + start_traffic(name, run_dir, params))
    return msgs


# --------------------------------------------------------------------------- data
def load_kpis(run_dir, window_s=None):
    frames = []
    for f in glob.glob(f"{run_dir}/kpi_*.csv"):
        try:
            frames.append(pd.read_csv(f))
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if window_s:
        df = df[df.ts >= time.time() - window_s]
    return df


def per_slice_series(df):
    """1-s bins per slice: sum throughput over UEs, mean of latency metrics."""
    if df.empty:
        return df
    df = df.copy()
    df["t"] = df.ts.astype(float).round(0)
    # one value per UE per second first (a UE can emit two rows in one rounded second)
    df = df.groupby(["slice", "ue_ip", "t"]).agg(
        throughput_mbps=("throughput_mbps", "mean"), rtt_p50_ms=("rtt_p50_ms", "mean"),
        rtt_p99_ms=("rtt_p99_ms", "max"), loss_pct=("loss_pct", "mean"), msgs=("msgs", "sum"),
        jitter_ms=("jitter_ms", "mean")).reset_index()
    agg = df.groupby(["slice", "t"]).agg(
        throughput_mbps=("throughput_mbps", "sum"), rtt_p50_ms=("rtt_p50_ms", "mean"),
        rtt_p99_ms=("rtt_p99_ms", "max"), loss_pct=("loss_pct", "mean"), msgs=("msgs", "sum"),
        jitter_ms=("jitter_ms", "mean")).reset_index()
    return agg


def export_zip(run_dir):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in glob.glob(f"{run_dir}/*"):
            z.write(f, os.path.basename(f))
        z.writestr("ue_sessions.csv", ue_sessions().to_csv(index=False))
        z.writestr("qos.txt", "\n".join(f"{n} rate/delay/loss = {get_qos(n)}" for n in SLICES))
    return buf.getvalue()
