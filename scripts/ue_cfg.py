#!/usr/bin/env python3
"""Writes the runtime UERANSIM config for one UE, keeping only sessions whose slice is
administratively up (/run/e2e5g/state-<slice> != 'down'). Prints the path, or exits 1 when
the UE has no active slice left (it then stays powered off)."""
import os, sys, yaml

ue = sys.argv[1]
base = yaml.safe_load(open(f"/e2e5g/configs/ueransim/ue-{ue}.yaml"))
slices = yaml.safe_load(open("/e2e5g/configs/slices.yaml"))["slices"]


def slice_up(sst):
    for name, s in slices.items():
        if s["sst"] == sst:
            p = f"/run/e2e5g/state-{name}"
            return not (os.path.exists(p) and open(p).read().strip() == "down")
    return True  # unknown slice (negative-test UE) -> leave as configured


sessions = [s for s in base["sessions"] if slice_up(s["slice"]["sst"])]
if not sessions:
    sys.exit(1)
base["sessions"] = sessions
base["configured-nssai"] = [s["slice"] for s in sessions]
base["default-nssai"] = [sessions[0]["slice"]]
os.makedirs("/run/e2e5g/ue", exist_ok=True)
out = f"/run/e2e5g/ue/ue-{ue}.yaml"
yaml.safe_dump(base, open(out, "w"), sort_keys=False)
print(out)
