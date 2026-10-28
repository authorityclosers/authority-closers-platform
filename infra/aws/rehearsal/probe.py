#!/usr/bin/env python3
"""Probe the SSH loopback only and export status/time, never response bodies."""

import argparse
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--url", default="http://127.0.0.1:18780/health/ready")
    args = parser.parse_args()
    target = urlsplit(args.url)
    if target.scheme != "http" or target.hostname != "127.0.0.1":
        raise SystemExit("SSH loopback required")
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        start = time.time()
        request = urllib.request.Request(  # noqa: S310 - scheme and loopback validated above
            args.url, headers={"Host": "api.authorityclosers.com"}
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310 - validated loopback
                code = response.status
        except urllib.error.HTTPError as error:
            code = error.code
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            code = 0
        print(
            json.dumps({"epoch": start, "status": code, "seconds": time.time() - start}), flush=True
        )
        time.sleep(0.5)


if __name__ == "__main__":
    main()
