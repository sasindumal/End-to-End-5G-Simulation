"""E2E 5G Slicing Sandbox — single control surface for the testbed.

Run inside the VM (as root, needs netns/tc access):
    sudo /opt/e2e5g-venv/bin/streamlit run /e2e5g/sandbox/app.py --server.port 8501
then open http://localhost:8501 on the Mac (Lima forwards the port).
"""
import time

import pandas as pd
import streamlit as st

import testbed as tb

st.set_page_config(page_title="E2E 5G Slicing Sandbox", layout="wide")
# the KPI fragment re-runs every 2 s; don't fade it while it refreshes
st.markdown("<style>[data-stale='true']{opacity:1 !important;transition:none !important}</style>",
            unsafe_allow_html=True)
COLORS = {"eMBB": "#2a78d6", "URLLC": "#eb6834", "mIoT": "#1baf7a"}  # same slots as report figures

if "run_dir" not in st.session_state:
    st.session_state.run_dir = tb.current_run()
run_dir = st.session_state.run_dir

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Scenario")
    sc = st.selectbox("Service scenario", list(tb.SCENARIOS))
    if st.button("Apply scenario", type="primary", use_container_width=True):
        for m in tb.apply_scenario(sc, run_dir):
            st.toast(m)
    if st.button("Stop all traffic", use_container_width=True):
        for s in tb.SLICES:
            tb.stop_traffic(s, run_dir)
    st.divider()
    st.header("Run data")
    st.caption(f"Current run: `{run_dir.split('/')[-1]}`")
    if st.button("Start new run", use_container_width=True):
        for s in tb.SLICES:
            tb.stop_traffic(s, run_dir)
        st.session_state.run_dir = tb.new_run("sandbox")
        st.rerun()
    st.download_button("Export run (ZIP)", data=tb.export_zip(run_dir),
                       file_name=f"{run_dir.split('/')[-1]}.zip", mime="application/zip",
                       use_container_width=True)
    st.divider()
    st.header("5G core")
    status = tb.core_status()
    st.write(" ".join(f"{'🟢' if up else '🔴'} {nf}" for nf, up in status.items()))

st.title("End-to-End 5G Slicing Sandbox")
st.caption("Open5GS 5GC · UERANSIM gNB/UEs · per-slice UPF selection · tc-based slice QoS")

# ----------------------------------------------------------------------------- slice cards
cols = st.columns(len(tb.SLICES))
for col, (name, cfg) in zip(cols, tb.SLICES.items()):
    with col, st.container(border=True):
        state = tb.slice_state(name)
        running = tb.traffic_running(name)
        st.subheader(f"{name}")
        st.caption(f"S-NSSAI SST {cfg['sst']} / SD {cfg['sd']} · DNN `{cfg['dnn']}` · {cfg['upf']}")
        st.markdown(f"Slice: **{'UP' if state == 'up' else 'DOWN'}** · "
                    f"Traffic: **{'running' if running else 'stopped'}**")
        c1, c2 = st.columns(2)
        if c1.button("Slice up", key=f"up-{name}", disabled=state == "up", use_container_width=True):
            with st.spinner("re-attaching UEs…"):
                tb.slice_updown(name, True, run_dir)
            st.rerun()
        if c2.button("Slice down", key=f"down-{name}", disabled=state != "up", use_container_width=True):
            with st.spinner("deregistering…"):
                tb.slice_updown(name, False, run_dir)
            st.rerun()
        c3, c4 = st.columns(2)
        if c3.button("Start traffic", key=f"ts-{name}", disabled=running or state != "up",
                     use_container_width=True):
            st.toast(tb.start_traffic(name, run_dir))
            st.rerun()
        if c4.button("Stop traffic", key=f"tp-{name}", disabled=not running, use_container_width=True):
            tb.stop_traffic(name, run_dir)
            st.rerun()
        rate, delay, loss = tb.get_qos(name)
        with st.form(f"qos-{name}"):
            st.markdown("**Live slice parameters**")
            r = st.slider("Max bit rate [Mbit/s]", 1, 500, int(rate), key=f"r-{name}")
            d = st.slider("Added one-way delay [ms]", 0, 100, int(delay), key=f"d-{name}")
            l = st.slider("Packet loss [%]", 0.0, 10.0, float(loss), 0.5, key=f"l-{name}")
            if st.form_submit_button("Apply live", use_container_width=True):
                tb.set_qos(name, r, d, l, run_dir)
                st.toast(f"{name}: {r} Mbit/s, {d} ms, {l} %")


# ----------------------------------------------------------------------------- live KPIs
@st.fragment(run_every=2)
def live_kpis():
    window = st.session_state.get("window", 120)
    df = tb.per_slice_series(tb.load_kpis(run_dir, window))
    st.subheader("Live per-slice KPIs")
    if df.empty:
        st.info("No KPI samples yet — start traffic on a slice.")
        return
    df["time"] = pd.to_datetime(df.t, unit="s")
    last = df[df.t >= df.t.max() - 5].groupby("slice").mean(numeric_only=True)
    mcols = st.columns(len(tb.SLICES))
    for c, name in zip(mcols, tb.SLICES):
        if name in last.index:
            row = last.loc[name]
            c.metric(f"{name} throughput", f"{row.throughput_mbps:.2f} Mbit/s")
            if name != "eMBB":
                c.metric(f"{name} RTT p50 / p99", f"{row.rtt_p50_ms:.2f} / {row.rtt_p99_ms:.2f} ms")
                c.metric(f"{name} loss", f"{row.loss_pct:.2f} %")
        else:
            c.metric(f"{name}", "idle")
    g1, g2 = st.columns(2)
    thr = df.pivot_table(index="time", columns="slice", values="throughput_mbps")
    g1.markdown("Throughput [Mbit/s]")
    g1.line_chart(thr, color=[COLORS[c] for c in thr.columns])
    lat = df[df.slice != "eMBB"].pivot_table(index="time", columns="slice", values="rtt_p99_ms")
    g2.markdown("RTT p99 [ms] (URLLC, mIoT)")
    if not lat.empty:
        g2.line_chart(lat, color=[COLORS[c] for c in lat.columns])


st.select_slider("KPI window [s]", options=[30, 60, 120, 300, 600], value=120, key="window")
live_kpis()

# ----------------------------------------------------------------------------- tables
t1, t2 = st.columns([3, 2])
with t1:
    st.subheader("UEs and PDU sessions")
    st.dataframe(tb.ue_sessions(), hide_index=True, use_container_width=True)
with t2:
    st.subheader("Event log")
    try:
        ev = pd.read_csv(f"{run_dir}/events.csv")
        ev["time"] = pd.to_datetime(ev.ts, unit="s").dt.strftime("%H:%M:%S")
        st.dataframe(ev[["time", "action", "detail"]].iloc[::-1], hide_index=True,
                     use_container_width=True, height=260)
    except FileNotFoundError:
        st.caption("No events yet.")
