#!/usr/bin/env python3
"""UDP echo server (runs in the data-network namespace) — reflects URLLC probe packets."""
import socket, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", port))
while True:
    data, addr = s.recvfrom(2048)
    s.sendto(data, addr)
