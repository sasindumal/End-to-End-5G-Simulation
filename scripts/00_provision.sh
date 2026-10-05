#!/usr/bin/env bash
# One-time provisioning of the Ubuntu 24.04 VM (Lima on macOS: arm64; WSL2 on Windows: amd64):
# MongoDB, Open5GS, UERANSIM, traffic/analysis tools and the Python venv.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

UERANSIM_TAG=${UERANSIM_TAG:-v3.2.7}
VENV=/opt/e2e5g-venv
ARCH=$(dpkg --print-architecture)   # arm64 (Apple silicon / Windows on ARM) or amd64 (most PCs)

sudo apt-get update
sudo apt-get install -y software-properties-common gnupg curl git make gcc g++ cmake \
  libsctp-dev lksctp-tools iproute2 iptables iperf3 jq net-tools tcpdump \
  python3-venv python3-pip

# tshark without the interactive "non-root capture" question
echo "wireshark-common wireshark-common/install-setuid boolean true" | sudo debconf-set-selections
sudo apt-get install -y tshark

# MongoDB 8.0 (subscriber database used by Open5GS UDR/PCF)
if ! command -v mongod >/dev/null; then
  curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
    sudo gpg --dearmor -o /usr/share/keyrings/mongodb-server-8.0.gpg
  echo "deb [ arch=$ARCH signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | \
    sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
  sudo apt-get update
  sudo apt-get install -y mongodb-org
fi
sudo systemctl enable --now mongod

# Open5GS from the official PPA
if ! command -v open5gs-amfd >/dev/null; then
  sudo add-apt-repository -y ppa:open5gs/latest
  sudo apt-get update
  sudo apt-get install -y open5gs
fi
# open5gs-dbctl (subscriber CLI) is not shipped in the .deb — take it from the matching tag
if ! command -v open5gs-dbctl >/dev/null; then
  sudo curl -fsSL -o /usr/local/bin/open5gs-dbctl \
    https://raw.githubusercontent.com/open5gs/open5gs/v2.8.0/misc/db/open5gs-dbctl
  sudo chmod +x /usr/local/bin/open5gs-dbctl
fi
# We run the NFs ourselves with our own configs, so stop the packaged units.
for s in $(systemctl list-unit-files 'open5gs-*' --no-legend | awk '{print $1}'); do
  sudo systemctl disable --now "$s" || true
done

# UERANSIM from source
if [ ! -x /opt/UERANSIM/build/nr-gnb ]; then
  sudo git clone --depth 1 --branch "$UERANSIM_TAG" https://github.com/aligungr/UERANSIM /opt/UERANSIM
  sudo chown -R "$USER" /opt/UERANSIM
  make -C /opt/UERANSIM -j"$(nproc)"
fi
sudo ln -sf /opt/UERANSIM/build/nr-gnb /opt/UERANSIM/build/nr-ue /opt/UERANSIM/build/nr-cli /usr/local/bin/

# Python environment for traffic generators, sandbox and analysis
if [ ! -d "$VENV" ]; then
  sudo python3 -m venv "$VENV"
  sudo chown -R "$USER" "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r /e2e5g/requirements.txt

sudo sysctl -w net.ipv4.ip_forward=1
echo "Provisioning complete."
