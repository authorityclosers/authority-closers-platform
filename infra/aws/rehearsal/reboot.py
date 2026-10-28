#!/usr/bin/env python3
"""Reboot only the fixed fictional host and reconnect its loopback SSH tunnel."""

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = "ubuntu@3.25.123.75"
FORWARD = "127.0.0.1:18780:127.0.0.1:8080"
KEY = str(Path.home() / ".ssh/ac-rehearsal.pem")
SSH = ["ssh", "-i", KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=3"]


def main():
    # Only this exact task's tunnel may be stopped; leave every other SSH alone.
    for item in Path("/proc").iterdir():
        if not item.name.isdigit() or int(item.name) == os.getpid():
            continue
        try:
            args = (item / "cmdline").read_bytes().split(b"\x00")
            if args and args[0] == b"ssh" and FORWARD.encode() in args and HOST.encode() in args:
                os.kill(int(item.name), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    start = time.time()
    command = [*SSH, HOST, "test -f ~/rehearsal/FICTIONAL-ONLY && sudo reboot"]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)  # noqa: S603 - fixed destination and command
    tunnel = None
    rows = []
    # Fail acceptance at 120s but keep measuring recovery up to 300s.
    while time.time() - start < 300:
        if tunnel is None or tunnel.poll() is not None:
            tunnel = subprocess.Popen(  # noqa: S603 - fixed loopback forward and host
                [
                    *SSH,
                    "-o",
                    "ExitOnForwardFailure=yes",
                    "-o",
                    "ServerAliveInterval=3",
                    "-o",
                    "ServerAliveCountMax=1",
                    "-N",
                    "-L",
                    FORWARD,
                    HOST,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            time.sleep(1)
        try:
            request = urllib.request.Request(  # noqa: S310 - literal SSH loopback URL
                "http://127.0.0.1:18780/health/ready", headers={"Host": "api.authorityclosers.com"}
            )
            with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310 - literal loopback
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            status = 0
        rows.append({"seconds": time.time() - start, "status": status})
        if status == 200:
            print(
                json.dumps(
                    {
                        "recovery_seconds": time.time() - start,
                        "pass_120s": time.time() - start < 120,
                        "probe": rows,
                        "tunnel_pid": tunnel.pid,
                    }
                ),
                flush=True,
            )
            return
        time.sleep(1)
    print(json.dumps({"recovery_seconds": None, "pass_120s": False, "probe": rows}), flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
