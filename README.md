# End-to-End 5G Simulation: network slicing on a software-only testbed

This is a software-only 5G SA system with **three differentiated slices** (eMBB, URLLC and mIoT),
built for a smart-factory scenario. Everything runs inside one Ubuntu 24.04 Linux environment:
a Lima VM on macOS (where the report's results were produced), or WSL2 on Windows.

| Layer | Software |
|---|---|
| VM (macOS) | Lima 2.2.1 (vz), Ubuntu 24.04 arm64, 4 vCPU / 6 GiB |
| VM (Windows) | WSL2, Ubuntu 24.04 (amd64, or arm64 on Windows on ARM), 4 vCPU / 6 GiB |
| 5G core | Open5GS 2.8.0 (AMF, SMF, NRF, SCP, AUSF, UDM, UDR, PCF, NSSF, BSF, 2× UPF), MongoDB 8.0 |
| RAN / UE | UERANSIM v3.2.7 (gNB + 6 UEs, plus a negative-test UE) |
| Traffic | iperf3 (eMBB), Python UDP probe (URLLC), Poisson sensor client (mIoT) |
| Slice QoS | Session-AMBR in the UDR; per-slice `tc` HTB+netem (live MBR/delay/loss) |
| Sandbox | Streamlit on http://localhost:8501 |
| Analysis | tshark + pandas/matplotlib → `report/figures`, `report/generated` |
| Report | LaTeX (`report/main.tex`, built with Tectonic) → `report/main.pdf` |

## Slices

| Slice | S-NSSAI | DNN / pool | User plane | 5QI | AMBR DL/UL | tc MBR |
|---|---|---|---|---|---|---|
| eMBB | 1 / 000001 | internet / 10.45.0.0/16 | UPF-A (shared) | 9 | 200/50 Mbit/s | 150 Mbit/s |
| URLLC | 2 / 000002 | urllc / 10.46.0.0/16 | **UPF-B (dedicated)** | 80 | 20/20 Mbit/s | 20 Mbit/s |
| mIoT | 3 / 000003 | iot / 10.47.0.0/16 | UPF-A (shared) | 9 | 2/2 Mbit/s | 5 Mbit/s |

## Quick start: macOS (Lima)

```bash
brew install lima
```
This needs the Xcode licence to be accepted first: `sudo xcodebuild -license accept`.

```bash
limactl create --name=e2e5g vm/lima-5g.yaml && limactl start e2e5g
```
```bash
limactl shell e2e5g -- bash /e2e5g/scripts/00_provision.sh
```
Bring up the whole testbed and the sandbox:
```bash
limactl shell e2e5g -- sudo bash -c 'cd /e2e5g/scripts && ./10_netns.sh && ./20_core.sh && ./30_subscribers.sh && ./40_ran.sh && ./slice_ctl.sh init && ../traffic/dn_servers.sh && ./60_sandbox.sh'
```
Then open http://localhost:8501.

Run every experiment (E1–E6), the CPU control (E7) and the analysis:
```bash
limactl shell e2e5g -- sudo /opt/e2e5g-venv/bin/python /e2e5g/experiments/run_all.py
```
```bash
limactl shell e2e5g -- sudo /opt/e2e5g-venv/bin/python /e2e5g/experiments/cpu_control.py
```
```bash
limactl shell e2e5g -- /opt/e2e5g-venv/bin/python /e2e5g/analysis/analyze.py
```

## Quick start: Windows (WSL2)

The 5G software is the same; WSL2 replaces Lima. Run the PowerShell steps in **PowerShell**
and everything else in the **Ubuntu** shell. This path has not been tested yet: the setup
script below checks the kernel features the testbed needs before you install anything.

1. Install WSL with Ubuntu 24.04 (PowerShell, as Administrator; reboot if asked):
   ```powershell
   wsl --install -d Ubuntu-24.04
   ```
2. Give WSL the same resources as the Mac VM: copy `vm/wslconfig.example` to
   `C:\Users\<you>\.wslconfig` (4 vCPU, 6 GB), then restart WSL:
   ```powershell
   wsl --shutdown
   ```
3. In Ubuntu, clone the repo **inside the Linux filesystem** (not under `/mnt/c`, which is slow
   and breaks permissions):
   ```bash
   cd ~ && git clone <repo-url> End-to-End-5G-Simulation && cd End-to-End-5G-Simulation
   ```
4. Run the WSL setup check. It turns on systemd (needed for MongoDB), links the repo to
   `/e2e5g` (the path every script uses), checks for CRLF line endings, and live-tests SCTP,
   network namespaces, veth, TUN and `tc` HTB/netem:
   ```bash
   bash scripts/wsl_setup.sh
   ```
   If it says systemd is not active, run `wsl --shutdown` in PowerShell, reopen Ubuntu and
   run the script again. Continue only once it prints *All checks passed*.
5. Provision, then start the testbed and the sandbox (the same scripts as on macOS):
   ```bash
   bash /e2e5g/scripts/00_provision.sh
   ```
   ```bash
   sudo bash -c 'cd /e2e5g/scripts && ./10_netns.sh && ./20_core.sh && ./30_subscribers.sh && ./40_ran.sh && ./slice_ctl.sh init && ../traffic/dn_servers.sh && ./60_sandbox.sh'
   ```
   Then open http://localhost:8501 in a Windows browser (WSL forwards localhost).
6. Experiments and analysis:
   ```bash
   sudo /opt/e2e5g-venv/bin/python /e2e5g/experiments/run_all.py
   ```
   ```bash
   sudo /opt/e2e5g-venv/bin/python /e2e5g/experiments/cpu_control.py
   ```
   ```bash
   /opt/e2e5g-venv/bin/python /e2e5g/analysis/analyze.py
   ```

**If the kernel check fails** (SCTP or `tc` netem/HTB missing in the WSL kernel), first try
`wsl --update` in PowerShell. If it still fails, run Ubuntu 24.04 in a normal Hyper-V or
VirtualBox VM instead: its stock kernel has everything, and steps 3–6 are the same there.

**Notes**
- `scripts/00_provision.sh` detects the CPU architecture, so it works on amd64 and arm64.
- `.gitattributes` keeps every script and config in LF, even in a Windows checkout.
- Absolute latency and throughput will differ from the report (different CPU and hypervisor);
  the procedures and slice behaviour are the same.

## Useful commands

Inside the VM / WSL (as root):
- `bash /e2e5g/scripts/ue_table.sh`: UEs, PDU sessions, IPs and interfaces
- `bash /e2e5g/scripts/slice_ctl.sh set eMBB 30 0 0`: live slice MBR / delay / loss
- `bash /e2e5g/scripts/slice_ctl.sh down URLLC` and `bash /e2e5g/scripts/slice_ctl.sh up URLLC`
- `ip netns exec ran ping -I uesimtun0 192.168.100.2`: UE → data network
- `MODE=shared bash /e2e5g/scripts/20_core.sh`: put URLLC on the shared UPF-A

## Restarting / Troubleshooting

If the network namespaces become corrupted or the start scripts fail with `Cannot find device`, you must completely shut down the environment to get a clean slate.

**macOS (Lima)**:
```bash
limactl stop e2e5g && limactl start e2e5g
```

**Windows (WSL2)**:
1. Open a **Windows PowerShell** window (NOT Ubuntu) and kill the VM:
   ```powershell
   wsl --shutdown
   ```
2. Reopen your Ubuntu terminal and run the start sequence normally:
   ```bash
   sudo bash -c 'cd /e2e5g/scripts && ./10_netns.sh && ./20_core.sh && ./30_subscribers.sh && ./40_ran.sh && ./slice_ctl.sh init && ../traffic/dn_servers.sh && ./60_sandbox.sh'
   ```

## Removing the VM and getting the disk space back

Removing the VM does **not** delete this project folder: code, `results/` and `report/` stay.
Everything inside the VM can be rebuilt later with the quick-start steps.

### macOS

The script stops and deletes the `e2e5g` VM (~5.4 GB), clears Lima's download cache with the
Ubuntu image (~2.6 GB) and uninstalls Lima. See what it would remove first:
```bash
bash scripts/uninstall_mac.sh --dry-run
```
Then remove everything (it asks you to type `delete` to confirm):
```bash
bash scripts/uninstall_mac.sh
```
To keep Lima installed for a later rebuild, add `--keep-lima`; to skip the prompt, add `--yes`.

### Windows (WSL2)

This deletes the whole Ubuntu-24.04 distribution, including anything else you stored in it.
In PowerShell:
```powershell
wsl --shutdown
```
```powershell
wsl --unregister Ubuntu-24.04
```
Then delete `C:\Users\<you>\.wslconfig` if you created it for this project. If you no longer
need WSL at all, `wsl --uninstall` removes it too.

## Layout

```
vm/            Lima VM definition (macOS), wslconfig.example (Windows)
scripts/       provisioning, topology, core/RAN start-stop, subscribers, capture, slice control,
               wsl_setup.sh (Windows/WSL2 preparation and kernel checks),
               uninstall_mac.sh (delete the VM and Lima, free the disk space)
configs/       Open5GS NF configs, UERANSIM gNB/UE configs, slices.yaml
traffic/       per-slice traffic generators + data-network servers
sandbox/       Streamlit app (app.py) + control library (testbed.py)
experiments/   run_all.py (E1–E6), cpu_control.py (E7)
analysis/      analyze.py → figures and LaTeX tables
results/       raw data of the runs used in the report (KPI CSVs, events, pcap, logs, versions)
               e5_pilot_tcp/ = first E5 attempt with TCP load (confounded, see report §10)
tools/         screenshot_sandbox.py (report screenshots via Chrome DevTools)
report/        LaTeX report source and main.pdf
```

Group members and the shared-folder link go in `report/members.tex`.
