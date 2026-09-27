#!/usr/bin/env python3
"""Run the required Sales Xray acquisition browser proof against a production build.

The proof is deliberately opt-in from the test's point of view, but this wrapper
sets every opt-in value and fails closed when the named case is missing, skipped,
or unable to produce its bounded receipt. The browser talks to the real local
ASGI application and disposable loopback PostgreSQL database; only the challenge,
native media runtime, and provider broker are synthetic test adapters.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/sales-xray-web"
TEST_FILE = ROOT / "tests/e2e/test_sales_xray_acquisition_browser.py"
TEST_NAME = "test_compiled_account_required_upload_profile_otp_report_relogin_and_deletion"
TEST_NODE = f"tests/e2e/test_sales_xray_acquisition_browser.py::{TEST_NAME}"
API_ORIGIN = "http://127.0.0.1:18116"

REQUIRED_ASSERTIONS = {
    "selected audio remains browser-local before authentication",
    "pre-auth requests contain no source upload or processing plan",
    "email OTP delivered through local outbox and verified",
    "new canonical account exists before profile completion",
    "required account name and mobile profile completed",
    "no source transfer until authenticated profile is complete",
    "originally selected audio bytes upload only after profile completion",
    "selected filename stays visible through email OTP and profile",
    "uploaded source hash matches originally selected audio bytes",
    "inline upload consent",
    "native C1",
    "explicit provider plan after profile and upload consent",
    "C6 overview",
    "acquisition allowance settled exactly once",
    "private range playback",
    "reload without retranscription",
    "390px reflow",
    "print",
    "new browser context signs in again with email OTP",
    "new browser context discovers call in canonical account library",
    "library row opens retained report and actual audio plays",
    "rendered Sign out button returns204 and private endpoints401",
    "stranger denied",
    "deletion accepted",
}


class GateError(RuntimeError):
    """A bounded diagnostic safe to expose in CI logs."""


def _require_test_source() -> None:
    if not TEST_FILE.is_file():
        raise GateError("The required Sales Xray acquisition browser test file is missing")
    try:
        tree = ast.parse(TEST_FILE.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise GateError("The required Sales Xray acquisition browser test is unreadable") from error
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == TEST_NAME
        for node in ast.walk(tree)
    ):
        raise GateError("The required Sales Xray acquisition browser test case is missing")


def _require_compiled_build() -> str:
    build_id_path = WEB / ".next/BUILD_ID"
    standalone_server = WEB / ".next/standalone/apps/sales-xray-web/server.js"
    if not build_id_path.is_file() or not standalone_server.is_file():
        raise GateError(
            "A production Sales Xray standalone build is required; static preview is invalid"
        )
    build_id = build_id_path.read_text(encoding="utf-8").strip()
    if not build_id or any(character.isspace() for character in build_id):
        raise GateError("The compiled Sales Xray build id is missing or malformed")
    return build_id


def _require_node() -> tuple[str, str]:
    node = os.environ.get("AC_SALES_XRAY_TEST_NODE") or ""
    node_path = node or _which_node()
    if not node_path:
        raise GateError("The pinned Node runtime is missing")
    try:
        result = subprocess.run(  # noqa: S603 - fixed Node executable and version argument
            [node_path, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GateError("The pinned Node runtime could not be queried") from error
    version = result.stdout.strip()
    if version != "v24.19.0":
        raise GateError("The Sales Xray browser gate requires Node 24.19.0")
    return node_path, version


def _which_node() -> str:
    path = os.environ.get("PATH", "")
    for directory in path.split(os.pathsep):
        candidate = Path(directory) / ("node.exe" if os.name == "nt" else "node")
        if candidate.is_file():
            return str(candidate)
    return ""


def _parse_junit(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise GateError("The required browser JUnit receipt is missing")
    try:
        raw = path.read_bytes()
        if len(raw) > 1_000_000:
            raise GateError("The browser JUnit receipt exceeds its bound")
        text = raw.decode("utf-8")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise GateError("The browser JUnit receipt must not declare entities")
        root = ET.fromstring(text)  # noqa: S314 - bounded local pytest XML, DTD refused above
    except GateError:
        raise
    except (OSError, UnicodeError, ET.ParseError) as error:
        raise GateError("The browser JUnit receipt is malformed") from error
    cases = list(root.iter("testcase"))
    names = [case.attrib.get("name") for case in cases]
    problems = any(list(root.iter(tag)) for tag in ("failure", "error", "skipped"))
    bad_counts = any(
        int(suite.attrib.get(key, "0")) != 0
        for suite in root.iter("testsuite")
        for key in ("failures", "errors", "skipped")
    )
    if names != [TEST_NAME] or problems or bad_counts:
        raise GateError("Exactly the required Sales Xray browser case must pass without skips")


def _load_browser_receipt(path: Path, build_id: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise GateError("The required browser-network receipt is missing")
    try:
        raw = path.read_bytes()
        if len(raw) > 1_000_000:
            raise GateError("The browser-network receipt exceeds its bound")
        value = json.loads(raw.decode("utf-8"))
    except GateError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GateError("The browser-network receipt is malformed") from error
    if not isinstance(value, dict):
        raise GateError("The browser-network receipt must be a JSON object")
    if value.get("compiled_build_id") != build_id:
        raise GateError("The browser receipt does not identify the compiled build")
    if value.get("route") != "/":
        raise GateError("The browser receipt has an unexpected route")
    if value.get("api_interceptions") != 0 or value.get("provider_network_calls") != 0:
        raise GateError("The browser proof must use the real local API and synthetic provider only")
    if (
        value.get("native_socket_simulated") is not True
        or value.get("challenge_simulated") is not True
    ):
        raise GateError("The browser proof must declare its bounded synthetic adapters")
    if value.get("page_errors") != []:
        raise GateError("The browser proof reported a page error")
    journey = value.get("journey_checks")
    required_journey = {
        "pre_auth_source_or_plan_writes": 0,
        "pre_auth_provider_calls": 0,
        "pre_auth_external_mutations": 0,
        "email_otp_verified": True,
        "account_created_before_profile": True,
        "pre_profile_source_or_plan_writes": 0,
        "profile_complete_before_upload": True,
        "selected_filename_in_auth_modal": True,
        "selected_filename_through_profile": True,
        "selected_filename_visible_before_upload": True,
        "uploaded_source_request_hash_matches_selected_bytes": True,
        "acquisition_usage_count": 1,
        "settlement_count": 1,
        "charged_seconds": 1,
        "relogin_existing_account": True,
        "external_mutations": 0,
    }
    if not isinstance(journey, dict) or any(
        journey.get(key) != expected for key, expected in required_journey.items()
    ):
        raise GateError("The browser proof did not establish account-first and one-charge evidence")
    passed = value.get("passed")
    if not isinstance(passed, list) or not REQUIRED_ASSERTIONS.issubset(passed):
        raise GateError("The browser receipt is missing one or more required journey assertions")
    receipts = value.get("http_receipts")
    if not isinstance(receipts, list) or not receipts:
        raise GateError("The browser proof did not record local HTTP receipts")
    return value


def _write_sanitized_receipt(path: Path, source: dict[str, Any], build_id: str) -> None:
    statuses = sorted(
        int(item["status"])
        for item in source["http_receipts"]
        if isinstance(item, dict) and isinstance(item.get("status"), int)
    )
    sanitized = {
        "schema": "ac.sales_xray.acquisition-browser-gate.v1",
        "status": "passed",
        "compiled_build_id": build_id,
        "route": "/",
        "http_receipt_count": len(source["http_receipts"]),
        "http_statuses": statuses,
        "api_interceptions": 0,
        "provider_network_calls": 0,
        "native_socket_simulated": True,
        "challenge_simulated": True,
        "page_errors": [],
        "account_first_checks": {
            key: source["journey_checks"][key]
            for key in (
                "pre_auth_source_or_plan_writes",
                "pre_auth_external_mutations",
                "email_otp_verified",
                "account_created_before_profile",
                "pre_profile_source_or_plan_writes",
                "profile_complete_before_upload",
                "selected_filename_visible_before_upload",
                "uploaded_source_request_hash_matches_selected_bytes",
                "acquisition_usage_count",
                "settlement_count",
                "charged_seconds",
                "relogin_existing_account",
            )
        },
        "passed": sorted(REQUIRED_ASSERTIONS),
        "synthetic_only": True,
    }
    path.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")


def _write_failure_receipt(path: Path, proof: dict[str, Any]) -> None:
    """Leave a bounded artifact even when setup fails before browser execution."""
    path.write_text(
        json.dumps(
            {
                "schema": "ac.sales_xray.acquisition-browser-gate.v1",
                "status": "failed",
                "reason": proof.get("reason", "The browser gate did not complete"),
                "provider_acceptance": False,
                "synthetic_only": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    proof: dict[str, Any] = {
        "schema": "ac.sales_xray.acquisition-browser-gate-proof.v1",
        "status": "failed",
        "test": TEST_NODE,
        "provider_acceptance": False,
    }
    try:
        _require_test_source()
        build_id = _require_compiled_build()
        node, node_version = _require_node()
        proof["node_version"] = node_version
        environment = os.environ.copy()
        environment.update(
            {
                "AC_CONVERSATION_API_ORIGIN": API_ORIGIN,
                "AC_SALES_XRAY_ACQUISITION_BROWSER_EVIDENCE_DIR": str(evidence),
                "AC_SALES_XRAY_TEST_NODE": node,
                "NEXT_TELEMETRY_DISABLED": "1",
                "NODE_ENV": "production",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        junit = evidence / "acquisition-browser.junit.xml"
        log = evidence / "pytest.log"
        command = [
            sys.executable,
            "-m",
            "pytest",
            TEST_NODE,
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(evidence / "pytest-basetemp"),
            "--junitxml",
            str(junit),
        ]
        with log.open("xb") as output:
            result = subprocess.run(  # noqa: S603 - fixed pytest module and repository-local test node
                command,
                cwd=ROOT,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=900,
                check=False,
            )
        if result.returncode:
            raise GateError("The required Sales Xray browser case failed")
        _parse_junit(junit)
        source = _load_browser_receipt(evidence / "browser-network.json", build_id)
        _write_sanitized_receipt(
            evidence / "sales-xray-acquisition-browser-receipt.json", source, build_id
        )
        proof.update(
            status="passed", provider_acceptance=False, assertions=len(REQUIRED_ASSERTIONS)
        )
        return 0
    except subprocess.TimeoutExpired:
        proof["reason"] = "The required Sales Xray browser case timed out"
        return 1
    except GateError as error:
        proof["reason"] = str(error)
        return 1
    except Exception:
        proof["reason"] = "The required Sales Xray browser gate failed unexpectedly"
        return 1
    finally:
        receipt = evidence / "sales-xray-acquisition-browser-receipt.json"
        if not receipt.exists():
            _write_failure_receipt(receipt, proof)
        (evidence / "proof.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(proof))


if __name__ == "__main__":
    raise SystemExit(main())
