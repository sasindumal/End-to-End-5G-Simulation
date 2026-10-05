#!/usr/bin/env bash
# Starts the Streamlit sandbox on :8501 (forwarded to the Mac by Lima).
pkill -f "streamlit run /e2e5g/sandbox/app.py" 2>/dev/null || true
cd /e2e5g/sandbox
nohup /opt/e2e5g-venv/bin/streamlit run /e2e5g/sandbox/app.py --server.port 8501 \
  --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false \
  >/var/log/e2e5g-sandbox.log 2>&1 &
sleep 4; tail -3 /var/log/e2e5g-sandbox.log
echo "Sandbox: http://localhost:8501"
