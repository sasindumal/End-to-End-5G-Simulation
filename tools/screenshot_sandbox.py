#!/usr/bin/env python3
"""Captures report screenshots of the running sandbox via Chrome DevTools Protocol.
Runs on the host (macOS or Windows); set CHROME to override the browser path.
Usage: python3 tools/screenshot_sandbox.py report/screenshots"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request
import websocket

out = sys.argv[1] if len(sys.argv) > 1 else "."
CHROME = os.environ.get("CHROME") or (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe" if sys.platform == "win32"
    else "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
chrome = subprocess.Popen([
    CHROME, "--headless=new",
    "--remote-debugging-port=9333", "--remote-allow-origins=http://127.0.0.1:9333", "--hide-scrollbars", "--window-size=1440,1000",
    f"--user-data-dir={os.path.join(tempfile.gettempdir(), 'e2e5g-chrome-cdp')}", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
            break
        except OSError:
            time.sleep(0.2)
    ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"],
                                     origin="http://127.0.0.1:9333")
    n = 0

    def call(method, **params):
        global n
        n += 1
        ws.send(json.dumps({"id": n, "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == n:
                return m.get("result", {})

    call("Emulation.setDeviceMetricsOverride", width=1440, height=1900, deviceScaleFactor=1.5, mobile=False)
    call("Page.navigate", url="http://localhost:8501")
    time.sleep(12)  # real time: websocket session + first KPI refreshes
    shots = {"sandbox_top": (0, 1000), "sandbox_kpis": (1000, 900)}
    for name, (y, h) in shots.items():
        r = call("Page.captureScreenshot", format="png",
                 clip={"x": 0, "y": y, "width": 1440, "height": h, "scale": 1}, captureBeyondViewport=True)
        open(f"{out}/{name}.png", "wb").write(base64.b64decode(r["data"]))
        print("saved", name)
finally:
    chrome.terminate()
