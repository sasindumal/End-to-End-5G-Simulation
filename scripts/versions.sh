#!/usr/bin/env bash
# Records the exact version of every component used (report appendix).
{
echo "host_macos: $(cat /e2e5g/results/host_versions.txt 2>/dev/null | tr '\n' ' ')"
echo "guest_os: $(. /etc/os-release; echo "$PRETTY_NAME") kernel $(uname -r) $(uname -m)"
echo "open5gs: $(dpkg-query -W -f='${Version}' open5gs-amf)"
echo "open5gs-dbctl: v2.8.0 (misc/db/open5gs-dbctl)"
echo "mongodb: $(mongod --version | awk '/db version/{print $3}')"
echo "ueransim: $(cd /opt/UERANSIM && git describe --tags 2>/dev/null) ($(cd /opt/UERANSIM && git rev-parse --short HEAD))"
echo "iperf3: $(iperf3 --version | head -1 | awk '{print $2}')"
echo "tshark: $(tshark --version 2>/dev/null | head -1 | awk '{print $3}')"
echo "iproute2/tc: $(tc -V | awk '{print $3}')"
echo "python: $(/opt/e2e5g-venv/bin/python --version | awk '{print $2}')"
/opt/e2e5g-venv/bin/python - <<'P'
import streamlit, pandas, matplotlib, numpy, yaml
for m in (streamlit, pandas, matplotlib, numpy, yaml):
    print(f"{m.__name__}: {m.__version__}")
P
echo "gcc: $(gcc -dumpfullversion)  cmake: $(cmake --version | head -1 | awk '{print $3}')"
} | tee /e2e5g/results/versions.txt
