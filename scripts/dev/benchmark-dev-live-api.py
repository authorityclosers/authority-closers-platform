"""Measure authenticated dev-live calls-list reads without logging credentials or data."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

HOST = "salesxray-dev.authorityclosers.com"
BASE = "http://127.0.0.1:8101"
CALLS = "/v1/conversation/acquisition/submissions?include_owners=true"


async def measure(values: dict[str, str]) -> dict[str, object]:
    headers = {"Host": HOST, "Origin": f"https://{HOST}", "User-Agent": "AUT-2158-dev-timing/1"}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30) as client:
        login = await client.post(
            "/v1/auth/password/login",
            json={"email": values["QA_EMAIL"], "password": values["QA_PASSWORD"]},
        )
        if login.status_code != 200:
            raise SystemExit(f"Synthetic QA login refused: HTTP {login.status_code}")
        # The API sets Secure cookies for its public host. Send the returned
        # session explicitly for this loopback-only probe, as the dev smoke does.
        cookies = [header.split(";", 1)[0] for header in login.headers.get_list("set-cookie")]
        client.headers["Cookie"] = "; ".join(cookies)

        async def read() -> float:
            start = time.perf_counter()
            response = await client.get(CALLS)
            if response.status_code != 200:
                raise SystemExit(f"Calls-list read refused: HTTP {response.status_code}")
            return round((time.perf_counter() - start) * 1000, 2)

        await read()  # Same warm-up before each measurement.
        singles = [await read() for _ in range(3)]
        bursts = []
        for _ in range(3):
            start = time.perf_counter()
            durations = await asyncio.gather(*(read() for _ in range(8)))
            bursts.append(
                {
                    "complete_ms": round((time.perf_counter() - start) * 1000, 2),
                    "request_ms": durations,
                }
            )
    return {
        "at": datetime.now(UTC).isoformat(),
        "target": BASE,
        "path": CALLS,
        "identity": "existing synthetic dev QA tester",
        "method": "one warm-up, three single reads, three bursts of eight; all HTTP 200",
        "single_ms": singles,
        "single_median_ms": statistics.median(singles),
        "bursts": bursts,
        "burst_complete_median_ms": statistics.median(b["complete_ms"] for b in bursts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    args = parser.parse_args()
    values = dict(
        line.split("=", 1) for line in args.credentials.read_text().split() if "=" in line
    )
    print(json.dumps(asyncio.run(measure(values)), indent=2))


if __name__ == "__main__":
    main()
