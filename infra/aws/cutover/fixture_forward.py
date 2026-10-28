#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- fixed rehearsal Docker metadata command
"""Private rehearsal-only TCP relay, for proving the ops SSH tunnel without publishing PG."""

import json
import select
import socket
import socketserver
import subprocess
from pathlib import Path


def main():
    if not (Path.home() / "rehearsal/FICTIONAL-ONLY").is_file():
        raise ValueError("fictional host only")
    result = subprocess.run(  # noqa: S603, S607 -- fixed rehearsal container, metadata only
        [
            "docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Networks}}",
            "ac-rehearsal-postgres-1",
        ],
        capture_output=True,
        check=True,
    )
    networks = json.loads(result.stdout)
    address = next(v["IPAddress"] for v in networks.values() if v["IPAddress"])

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection((address, 5432), timeout=10) as upstream:
                pair = [self.request, upstream]
                while True:
                    ready, _, _ = select.select(pair, [], [], 30)
                    if not ready:
                        return
                    for incoming in ready:
                        data = incoming.recv(65536)
                        if not data:
                            return
                        (upstream if incoming is self.request else self.request).sendall(data)

    socketserver.ThreadingTCPServer(("127.0.0.1", 15432), Relay).serve_forever()


if __name__ == "__main__":
    main()
