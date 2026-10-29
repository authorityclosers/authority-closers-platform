#!/usr/bin/env python3
"""Bounded public release smoke; standalone stdlib, content-free evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TOTAL_SECONDS = 110
REQUEST_MS = 8000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A login redirect must not masquerade as a healthy page.


def targets(environment):
    suffix = "-staging" if environment == "staging" else ""
    domain = ".authorityclosers.com"
    return [
        ("learner", "learner", "/", 200),
        ("learner_health", "learner", "/healthz", 200),
        ("coach_login", "coach", "/login", 200),
        ("salesxray", "salesxray", "/", 200),
        ("salesxray_health", "salesxray", "/health", 200),
        ("api_live", "api", "/health/live", 200),
        ("api_ready", "api", "/health/ready", 200),
        ("api_programs", "api", "/v1/programs", 200),
        ("api_docs_private", "api", "/docs", 404),
        ("api_schema_private", "api", "/openapi.json", 404),
    ], suffix, domain


def probe(opener, url, expected):
    started = time.monotonic()
    status = None
    try:
        with opener.open(url, timeout=REQUEST_MS / 1000) as response:
            status = response.status
            response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
    elapsed = round((time.monotonic() - started) * 1000)
    return {
        "status": status,
        "elapsed_ms": elapsed,
        "ok": status == expected and elapsed <= REQUEST_MS,
    }


def run_checks(environment):
    checks, suffix, domain = targets(environment)
    opener = urllib.request.build_opener(NoRedirect())
    results = []
    for name, host, path, expected in checks:
        try:
            result = probe(opener, "https://" + host + suffix + domain + path, expected)
        except TimeoutError:
            raise
        except (OSError, ValueError):
            result = {"ok": False, "reason": "request_failed"}
        results.append({"check": name, **result})
    return results


def write_record(state_dir, environment, core, web, result, checks):
    record = {
        "result": result, "environment": environment, "core_sha": core,
        "web_sha": web, "at": time.time(), "checks": checks,
    }
    record["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    directory = state_dir / environment
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".smoke-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(record, output, sort_keys=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, directory / f"{core}-{web}.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return record


def deadline(signum, frame):
    raise TimeoutError("smoke_timeout")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=("staging", "production"))
    parser.add_argument("--core", required=True)
    parser.add_argument("--web", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if not all(re.fullmatch(r"[0-9a-f]{7,64}", sha) for sha in (args.core, args.web)):
        parser.error("invalid source revision")
    previous = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(TOTAL_SECONDS)
    try:
        try:
            checks = run_checks(args.environment)
            result = "pass" if checks and all(item["ok"] for item in checks) else "fail"
        except TimeoutError:
            checks, result = [{"check": "deadline", "ok": False, "reason": "timeout"}], "fail"
        except Exception:
            checks, result = [{"check": "runner", "ok": False, "reason": "runner_failed"}], "fail"
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    try:
        write_record(args.state_dir, args.environment, args.core, args.web, result, checks)
    except OSError:
        print("smoke fail: record_write_failed")
        return 1
    print("smoke " + result)
    return 0 if result == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
