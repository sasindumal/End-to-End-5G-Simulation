#!/usr/bin/env python3
"""mIoT collector (data-network side): receives small JSON telemetry over UDP, returns a 16-byte ACK."""
import socket, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", port))
while True:
    data, addr = s.recvfrom(2048)
    s.sendto(data[:16], addr)  # first 16 bytes carry device id + seq -> used as ACK
