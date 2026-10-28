#!/usr/bin/env python3
# ruff: noqa: S603, S607 -- reviewed argv, fixed utilities, no shell interpolation
"""Public read canary from ac. Receipts contain status/timing, never body or cookies."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--config", required=True, help="JSON list of url/status/contains/header expectations"
    )
    args = p.parse_args()
    checks = json.loads(Path(args.config).read_text())
    if not checks:
        raise ValueError("canary checks required")
    for check in checks:
        url = check["url"]
        if not url.startswith("https://"):
            raise ValueError("public TLS URLs required")
        start = time.monotonic()
        r = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "20",
                "--proto",
                "=https",
                "--dump-header",
                "-",
                "--write-out",
                "\n%{http_code}",
                url,
            ],
            capture_output=True,
            check=False,
        )
        if r.returncode:
            raise ValueError("public request failed")
        headers_body, code = r.stdout.rsplit(b"\n", 1)
        expected = check.get("contains", "").encode()
        if int(code) != check.get("status", 200) or expected not in headers_body:
            raise ValueError("public response mismatch")
        if (
            check.get("header", "").lower().encode()
            not in headers_body.split(b"\r\n\r\n", 1)[0].lower()
        ):
            raise ValueError("release/route header mismatch")
        print(
            json.dumps(
                {
                    "check": check["name"],
                    "status": int(code),
                    "seconds": round(time.monotonic() - start, 3),
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("public canary failed; body suppressed", file=sys.stderr)
        sys.exit(1)
