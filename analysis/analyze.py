#!/usr/bin/env python3
"""Turns the raw experiment outputs in results/ into report figures and LaTeX tables.

Run inside the VM (needs tshark):
    /opt/e2e5g-venv/bin/python /e2e5g/analysis/analyze.py
Outputs: report/figures/*.pdf, report/generated/*.tex, results/summary.json
"""
import json
import os
import re
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.environ.get("E2E_ROOT", "/e2e5g")
RES = f"{ROOT}/results"
FIG = f"{ROOT}/report/figures"
GEN = f"{ROOT}/report/generated"
os.makedirs(FIG, exist_ok=True)
os.makedirs(GEN, exist_ok=True)

# Validated categorical slots 1-3 (fixed order: eMBB, URLLC, mIoT)
C = {"eMBB": "#2a78d6", "URLLC": "#eb6834", "mIoT": "#1baf7a"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": INK2,
    "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "lines.linewidth": 1.6,
    "legend.frameon": False, "figure.dpi": 150, "savefig.bbox": "tight",
})
SUMMARY = {}


def save(fig, name):
    fig.savefig(f"{FIG}/{name}.pdf")
    fig.savefig(f"{FIG}/{name}.png", dpi=160)
    plt.close(fig)


def load(exp):
    frames = [pd.read_csv(f"{RES}/{exp}/{f}") for f in os.listdir(f"{RES}/{exp}") if f.startswith("kpi_")]
    df = pd.concat(frames, ignore_index=True)
    ev = pd.read_csv(f"{RES}/{exp}/events.csv") if os.path.exists(f"{RES}/{exp}/events.csv") else pd.DataFrame()
    t0 = min(df.ts.min(), ev.ts.min() if not ev.empty else np.inf)
    df["t"] = (df.ts - t0).round(0)
    if not ev.empty:
        ev["t"] = ev.ts - t0
    # one value per UE per second first (a UE can emit two rows in one rounded second)
    df = df.groupby(["slice", "ue_ip", "t"]).agg(
        throughput_mbps=("throughput_mbps", "mean"), rtt_p50_ms=("rtt_p50_ms", "mean"),
        rtt_p99_ms=("rtt_p99_ms", "max"), loss_pct=("loss_pct", "mean"), msgs=("msgs", "sum"),
        jitter_ms=("jitter_ms", "mean")).reset_index()
    agg = df.groupby(["slice", "t"]).agg(
        thr=("throughput_mbps", "sum"), p50=("rtt_p50_ms", "mean"), p99=("rtt_p99_ms", "max"),
        loss=("loss_pct", "mean"), msgs=("msgs", "sum"), jit=("jitter_ms", "mean")).reset_index()
    return agg, ev


def tex_table(name, df, colfmt, caption=None):
    body = df.to_latex(index=False, column_format=colfmt, escape=True)
    open(f"{GEN}/{name}.tex", "w").write(body)


def label_last(ax, x, y, text, color):
    ax.annotate(text, (x, y), xytext=(4, 0), textcoords="offset points", color=INK2,
                va="center", fontsize=7.5)


# ============================================================================ E1/E2 signalling
def tshark(pcap, fields, filt):
    cmd = ["tshark", "-r", pcap, "-o", "nas-5gs.null_decipher:TRUE", "-d", "tcp.port==7777,http2",
           "-Y", filt, "-T", "fields", "-E", "separator=|", "-E", "occurrence=a", "-E", "aggregator=;"]
    for f in fields:
        cmd += ["-e", f]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return [l.split("|") for l in out.strip().splitlines() if l]


def signalling():
    pcap = f"{RES}/e1/attach.pcapng"
    rows = tshark(pcap, ["frame.time_relative", "ip.src", "ip.dst", "ngap.RAN_UE_NGAP_ID",
                         "_ws.col.Info", "nas-5gs.mm.suci.msin", "nas-5gs.pdu_session_id"],
                  "ngap || pfcp.msg_type in {50,51,52,53}")
    # --- procedure timing per UE (keyed on RAN-UE-NGAP-ID)
    ues, msin_of = {}, {}
    for t, src, dst, ranid, info, msin, psi in rows:
        t = float(t)
        if not ranid:
            continue
        rid = ranid.split(";")[0]
        u = ues.setdefault(rid, {})
        if msin:
            msin_of[rid] = msin.split(";")[0]
        if "Registration request" in info and "InitialUEMessage" in info:
            u.setdefault("reg_start", t)
        if "Registration accept" in info:
            u.setdefault("reg_accept", t)
        if "PDU session establishment request" in info:
            u.setdefault("pdu_req", []).append(t)
        if "PDUSessionResourceSetupResponse" in info:
            u.setdefault("pdu_done", []).append(t)
        if "Registration reject" in info or "5GMM status" in info:
            u["reject"] = info
    upf_by_dnn = {}
    for t, src, dst, ranid, info, msin, psi in rows:
        if "PFCP Session Establishment Request" in info:
            upf_by_dnn.setdefault(dst, 0)
            upf_by_dnn[dst] += 1
    names = {"0000000001": "embb1", "0000000002": "embb2", "0000000003": "urllc1",
             "0000000004": "miot1", "0000000005": "miot2", "0000000006": "multi",
             "0000000007": "badslice"}
    out = []
    for rid, u in ues.items():
        if "reg_start" not in u:
            continue
        msin = msin_of.get(rid, "")
        reg = (u.get("reg_accept", np.nan) - u["reg_start"]) * 1000
        req, done = u.get("pdu_req", []), u.get("pdu_done", [])
        # two requests can share one NGAP message -> pair each completion with its request (or the last one)
        pdu = [(d - req[min(i, len(req) - 1)]) * 1000 for i, d in enumerate(done)] if req else []
        out.append({"UE": names.get(msin, msin), "SUPI": f"imsi-00101{msin}",
                    "Registration [ms]": f"{reg:.1f}",
                    "PDU sessions": len(u.get("pdu_done", [])),
                    "PDU setup [ms]": ", ".join(f"{p:.1f}" for p in pdu) or "rejected"})
    tdf = pd.DataFrame(out)
    tex_table("tab_signalling_timing", tdf, "llrcl")
    SUMMARY["signalling"] = out
    SUMMARY["pfcp_session_est_by_upf"] = upf_by_dnn

    # --- SBI service usage (HTTP/2 :path)
    sbi = tshark(pcap, ["http2.headers.method", "http2.headers.path"], "http2.headers.path")
    svc = {}
    for m, p in sbi:
        for mm, pp in zip(m.split(";"), p.split(";")):
            if not pp.startswith("/n"):
                continue
            parts = [re.sub(r"imsi-\d+", "{supi}", x) for x in pp.split("?")[0].split("/")[1:]]
            parts = [re.sub(r"^[0-9a-f-]{20,}$|^\d+$", "{id}", x) for x in parts]
            api, res = parts[0], "/".join(parts[2:4])
            if not mm:
                continue
            key = (api, f"{mm} /{res}")
            svc[key] = svc.get(key, 0) + 1
    sdf = pd.DataFrame([{"SBI API": k[0], "Operation": k[1], "Count": v} for k, v in svc.items()])
    sdf = sdf[~sdf["SBI API"].str.startswith("nnrf")].sort_values("Count", ascending=False).head(12)
    tex_table("tab_sbi", sdf, "llr")

    # --- ladder diagram for the multi-slice UE (msin ...06)
    rid = next((r for r, m in msin_of.items() if m == "0000000006"), None)
    lanes = {"UE/gNB": 0, "AMF": 1, "SMF": 2, "UPF-A": 3, "UPF-B": 4}
    addr = {"10.10.0.2": "UE/gNB", "10.10.0.1": "AMF", "127.0.0.4": "SMF",
            "127.0.0.7": "UPF-A", "127.0.0.17": "UPF-B"}
    seq = []
    ts = [float(r[0]) for r in rows if r[3].split(";")[0] == rid]
    t_lo, t_hi = min(ts) - 0.001, max(ts) + 0.001
    for t, src, dst, ranid, info, msin, psi in rows:
        t = float(t)
        is_ue = ranid.split(";")[0] == rid
        is_pfcp = "PFCP" in info and t_lo <= t <= t_hi
        if not (is_ue or is_pfcp) or "SACK" == info.strip():
            continue
        info = re.sub(r"SACK \(Ack=\d+, Arwnd=\d+\)\s*,?", "", info)
        lab = info.split(", ")
        lab = [x.strip(" ,") for x in lab if x.strip(" ,") and not x.strip().startswith("(Ack")
               and x.strip() not in ("UplinkNASTransport", "DownlinkNASTransport", "UL NAS transport",
                                     "DL NAS transport")]
        if not lab:
            continue
        lab = " + ".join(lab).replace("PDU session establishment", "PDU est.").replace("Registration complete", "Reg. complete")
        seq.append((t, addr.get(src, src), addr.get(dst, dst), lab))
    seq.sort()
    fig, ax = plt.subplots(figsize=(7.2, 0.32 * len(seq) + 0.8))
    for name, x in lanes.items():
        ax.plot([x, x], [-0.5, len(seq)], color=INK2, lw=0.8)
        ax.text(x, -0.9, name, ha="center", va="bottom", fontsize=8.5, weight="bold", color=INK)
    t0 = seq[0][0]
    for i, (t, s, d, lab) in enumerate(seq):
        if s not in lanes or d not in lanes:
            continue
        xs, xd = lanes[s], lanes[d]
        col = C["URLLC"] if "UPF-B" in (s, d) else (C["eMBB"] if "UPF" in s + d else INK)
        ax.annotate("", xy=(xd, i + 0.5), xytext=(xs, i + 0.5),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=1.0, shrinkA=0, shrinkB=0))
        ax.text((xs + xd) / 2, i + 0.38, lab[:70], ha="center", va="bottom", fontsize=6.0, color=INK,
                bbox=dict(boxstyle="square,pad=0.05", fc="white", ec="none"))
        ax.text(-1.25, i + 0.5, f"{(t - t0) * 1000:6.1f} ms", ha="right", va="center", fontsize=6.3,
                color=INK2, family="DejaVu Sans Mono")
    ax.set_ylim(len(seq) + 0.2, -1.2)
    ax.set_xlim(-2.0, 4.5)
    ax.axis("off")
    save(fig, "fig_ladder_multi")


# ============================================================================ E3 isolation
def phase_spans(ax, ev, labels):
    ph = ev[ev.action == "phase"].reset_index(drop=True)
    for i, r in ph.iterrows():
        if r.detail.endswith(" on"):
            end = ph.t[i + 1] if i + 1 < len(ph) else None
            if end is not None:
                ax.axvspan(r.t, end, color="#f0efec", zorder=0)


def e3():
    agg, ev = load("e3")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 4.2), sharex=True)
    for ax in (a1, a2):
        phase_spans(ax, ev, None)
    e = agg[agg.slice == "eMBB"]
    a1.plot(e.t, e.thr, color=C["eMBB"], label="eMBB")
    a1.set_ylabel("eMBB DL throughput\n[Mbit/s]")
    a1.set_title("eMBB load phase (shaded): 2 UEs × 4 TCP streams, slice MBR 150 Mbit/s",
                 fontsize=7.5, color=INK2, loc="left")
    for s in ["URLLC", "mIoT"]:
        d = agg[agg.slice == s]
        a2.plot(d.t, d.p99, color=C[s], label=f"{s} p99")
        a2.plot(d.t, d.p50, color=C[s], lw=1.0, ls="--", label=f"{s} p50")
    a2.set_ylabel("RTT UE↔DN [ms]")
    a2.set_xlabel("time [s]")
    a2.legend(ncol=4, loc="upper left", fontsize=7.5)
    save(fig, "fig_e3_isolation")
    rows = []
    for s in ["URLLC", "mIoT"]:
        d = agg[agg.slice == s]
        for name, m in [("idle (0–30 s)", d.t < 30), ("eMBB load (30–90 s)", (d.t >= 32) & (d.t < 90)),
                        ("after (90–120 s)", d.t >= 92)]:
            x = d[m]
            rows.append({"Slice": s, "Phase": name, "RTT p50 [ms]": f"{x.p50.median():.2f}",
                         "RTT p99 [ms]": f"{x.p99.median():.2f}", "worst p99 [ms]": f"{x.p99.max():.2f}",
                         "Loss [%]": f"{x.loss.mean():.2f}"})
    tdf = pd.DataFrame(rows)
    tex_table("tab_e3", tdf, "llrrrr")
    SUMMARY["e3"] = rows
    SUMMARY["e3_embb_mean_thr"] = float(e[(e.t >= 32) & (e.t < 90)].thr.mean())


# ============================================================================ E4 live change
def e4():
    agg, ev = load("e4")
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7, 4.2), sharex=True)
    q = ev[ev.action == "qos"]
    marks = q[q.t > 5]
    for ax in (a1, a2):
        for _, r in marks.iterrows():
            ax.axvline(r.t, color=INK2, lw=0.8, ls=":")
    e = agg[agg.slice == "eMBB"]
    a1.plot(e.t, e.thr, color=C["eMBB"])
    a1.set_ylabel("eMBB DL throughput\n[Mbit/s]")
    for s in ["URLLC", "mIoT"]:
        d = agg[agg.slice == s]
        a2.plot(d.t, d.p50, color=C[s], label=f"{s} p50")
    a2.set_ylabel("RTT p50 [ms]")
    a2.set_xlabel("time [s]")
    a2.legend(loc="center left", fontsize=7.5)
    for _, r in marks.iterrows():
        kv = dict(x.split("=") for x in r.detail.split()[1:])
        sl = r.detail.split()[0]
        ax = a1 if sl == "eMBB" else a2
        txt = (f"eMBB MBR → {kv['rate']} Mbit/s" if sl == "eMBB"
               else f"{sl}: +{kv['delay']} ms each direction")
        ax.text(r.t + 1.5, ax.get_ylim()[1] * 0.82, txt, fontsize=7.5, color=INK2)
    save(fig, "fig_e4_live")
    ch = marks.t.tolist()
    t1, t2 = (ch + [40, 80])[:2] if len(ch) >= 2 else (40, 80)
    u = agg[agg.slice == "URLLC"]
    SUMMARY["e4"] = {
        "embb_before": float(e[(e.t > 5) & (e.t < t1)].thr.mean()),
        "embb_after": float(e[(e.t > t1 + 3) & (e.t < t2)].thr.mean()),
        "urllc_p50_before": float(u[(u.t > t1) & (u.t < t2)].p50.median()),
        "urllc_p50_after": float(u[u.t > t2 + 2].p50.median()),
        "change_times": ch,
        "mIoT_p50_after": float(agg[(agg.slice == "mIoT") & (agg.t > t2 + 2)].p50.median()),
    }


# ============================================================================ E5 UPF sharing
def e5():
    import glob
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 2.8), gridspec_kw={"width_ratios": [1.6, 1]})
    styles = {"dedicated": ("-", "dedicated UPF-B"), "shared": ("--", "shared UPF-A")}
    per_rep, pooled = [], {}
    for mode, (ls, lab) in styles.items():
        dirs = sorted(glob.glob(f"{RES}/e5_{mode}_r*"))
        pooled[mode] = []
        for i, dpath in enumerate(dirs):
            agg, ev = load(os.path.relpath(dpath, RES))
            u = agg[agg.slice == "URLLC"]
            e = agg[agg.slice == "eMBB"]
            ld = u[(u.t >= 25) & (u.t < 80)]
            idle = u[u.t < 18]
            per_rep.append({"mode": mode, "rep": i + 1, "idle_p50": idle.p50.median(),
                            "load_p50": ld.p50.median(), "load_p99": ld.p99.median(),
                            "load_p99_95": ld.p99.quantile(0.95), "worst": ld.p99.max(),
                            "loss": ld.loss.mean(), "embb": e[(e.t >= 25) & (e.t < 80)].thr.mean()})
            pooled[mode].append(ld.p99.dropna().values)
            if i == 0:
                a1.plot(u.t, u.p99, color=C["URLLC"], ls=ls, label=f"URLLC on {lab} (run 1)")
        v = np.sort(np.concatenate(pooled[mode])) if pooled[mode] else np.array([])
        if len(v):
            a2.plot(v, np.arange(1, len(v) + 1) / len(v), color=C["URLLC"], ls=ls, label=lab)
    a1.axvspan(20, 80, color="#f0efec", zorder=0)
    a1.set_xlabel("time [s] (shaded: eMBB overload)")
    a1.set_ylabel("URLLC RTT p99 per second [ms]")
    a1.legend(fontsize=7, loc="upper left")
    a2.set_xscale("log")
    a2.set_xlabel("URLLC per-second p99 under load [ms]")
    a2.set_ylabel("CDF (all runs)")
    a2.legend(fontsize=7, loc="lower right")
    save(fig, "fig_e5_upf")
    df = pd.DataFrame(per_rep)
    df.to_csv(f"{RES}/e5_per_rep.csv", index=False)
    rows = []
    for mode in styles:
        x = df[df["mode"] == mode]
        f = lambda c: f"{x[c].mean():.2f} ± {x[c].std(ddof=1):.2f}" if len(x) > 1 else f"{x[c].mean():.2f}"
        rows.append({"URLLC user plane": mode, "runs": len(x), "load p50 [ms]": f("load_p50"),
                     "load p99 [ms]": f("load_p99"), "p95 of p99 [ms]": f("load_p99_95"),
                     "worst p99 [ms]": f"{x.worst.max():.1f}", "loss [%]": f"{x.loss.mean():.3f}",
                     "eMBB [Mbit/s]": f"{x.embb.mean():.0f}"})
    tex_table("tab_e5", pd.DataFrame(rows), "lrrrrrrr")
    SUMMARY["e5"] = {"per_rep": per_rep, "table": rows}
    # CPU usage under load (first run of each mode)
    for mode in styles:
        f = f"{RES}/e5_{mode}_r1/top_under_load.txt"
        if os.path.exists(f):
            SUMMARY.setdefault("e5_top", {})[mode] = open(f).read().splitlines()[6:16]


# ============================================================================ E7 CPU control
def e7():
    agg, ev = load("e7")
    u = agg[agg.slice == "URLLC"]
    rows = []
    for name, m in [("idle (0–30 s)", u.t < 30), ("CPU busy-loops, no traffic (30–60 s)", (u.t >= 31) & (u.t < 60)),
                    ("idle again (60–90 s)", u.t >= 61)]:
        x = u[m]
        rows.append({"Condition": name, "RTT p50 [ms]": f"{x.p50.median():.3f}", "RTT p99 [ms]": f"{x.p99.median():.2f}"})
    tex_table("tab_e7", pd.DataFrame(rows), "lrr")
    SUMMARY["e7"] = rows


# ============================================================================ E6 temporal profiles
def e6():
    agg, ev = load("e6")
    fig, axs = plt.subplots(3, 1, figsize=(7, 4.6), sharex=True)
    e = agg[agg.slice == "eMBB"]
    axs[0].plot(e.t, e.thr, color=C["eMBB"])
    axs[0].set_ylabel("eMBB\n[Mbit/s]")
    u = agg[agg.slice == "URLLC"]
    axs[1].plot(u.t, u.msgs, color=C["URLLC"])
    axs[1].set_ylabel("URLLC\n[echoes/s]")
    m = agg[agg.slice == "mIoT"]
    axs[2].bar(m.t, m.msgs, color=C["mIoT"], width=0.8)
    axs[2].set_ylabel("mIoT\n[reports/s]")
    axs[2].set_xlabel("time [s]")
    save(fig, "fig_e6_profiles")
    SUMMARY["e6"] = {s: {"thr_mean": float(agg[agg.slice == s].thr.mean()),
                         "msgs_mean": float(agg[agg.slice == s].msgs.mean()),
                         "p50": float(agg[agg.slice == s].p50.median()) if s != "eMBB" else None}
                     for s in ["eMBB", "URLLC", "mIoT"]}


if __name__ == "__main__":
    for fn in (signalling, e3, e4, e5, e6, e7):
        try:
            fn()
            print("ok", fn.__name__)
        except Exception as ex:  # keep going so partial results still render
            print("FAILED", fn.__name__, repr(ex))
    json.dump(SUMMARY, open(f"{RES}/summary.json", "w"), indent=2, default=str)
