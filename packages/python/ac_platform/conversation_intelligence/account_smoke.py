"""Bounded QA-account HTTP smoke; credentials and report contents stay in memory."""

from __future__ import annotations

import asyncio
import hashlib
import time
from importlib import resources
from typing import Any
from uuid import UUID, uuid4

import httpx

from ac_platform.conversation_intelligence.canary_cli import (
    FIXTURE_SHA256,
    MAX_QUOTE_PAISE,
    check_report_coaching,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash

ORIGINS = {
    "production": "https://salesxray.authorityclosers.com",
    "staging": "https://salesxray-staging.authorityclosers.com",
}
PREFIX = "/v1/conversation/acquisition"


class SmokeFailure(ValueError):
    """Only fixed content-free error codes may cross the QA output boundary."""


async def account_smoke(
    client: httpx.AsyncClient,
    *,
    environment: str,
    email: str,
    password: str,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    origin = ORIGINS.get(environment)
    if (
        origin is None
        or str(client.base_url).rstrip("/") != origin
        or not email.endswith(f"+ac-qa-{environment}@authorityclosers.com")
        or not password
        or not 1 <= timeout_seconds <= 1800
    ):
        raise SmokeFailure("qa_runtime_refused")
    started = time.monotonic()

    async def request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await client.request(
            method, path, headers={"Origin": origin, **kwargs.pop("headers", {})}, **kwargs
        )
        if response.is_redirect or response.status_code >= 400:
            raise SmokeFailure("qa_endpoint_unavailable")
        try:
            body = response.json() if response.content else {}
        except ValueError:
            raise SmokeFailure("qa_response_invalid") from None
        if not isinstance(body, dict):
            raise SmokeFailure("qa_response_invalid")
        return body

    async with asyncio.timeout(timeout_seconds):
        await request(
            "POST", "/v1/auth/password/login", json={"email": email, "password": password}
        )
        identity = await request("GET", "/v1/me/workspaces")
        if identity.get("selected_tenant_id") is None:
            raise SmokeFailure("qa_workspace_required")
        person_id, tenant_id = (
            str(UUID(identity["person_id"])),
            str(UUID(identity["selected_tenant_id"])),
        )
        await request("GET", "/v1/me/sales-xray-profile/write-eligibility")
        policy = await request("GET", PREFIX + "/upload-policy")
        if environment == "production" and not 1 <= policy["retention_days"] <= 7:
            raise SmokeFailure("qa_retention_refused")
        fixture = (
            resources.files("ac_platform.conversation_intelligence")
            .joinpath("canary_fixture/sales_call_v1.wav")
            .read_bytes()
        )
        if hashlib.sha256(fixture).hexdigest() != FIXTURE_SHA256:
            raise SmokeFailure("qa_fixture_changed")
        submission_id = uuid4()
        path = f"{PREFIX}/submissions/{submission_id}"
        await request(
            "PUT",
            path + "/source",
            content=fixture,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Source-SHA256": FIXTURE_SHA256,
                "X-Upload-Policy": policy["policy_sha256"],
                "X-Upload-Consent": "accepted",
            },
        )
        accepted = False
        while True:
            progress = await request("GET", path)
            if progress.get("has_report"):
                break
            if (
                progress.get("local_state") in {"failed", "cancelled"}
                or progress.get("state") in {"held", "failed", "cancelled"}
                or progress.get("execution_hold")
                or any(
                    stage.get("state") in {"failed", "uncertain"}
                    for stage in progress.get("stages", [])
                )
            ):
                raise SmokeFailure("qa_analysis_failed_or_held")
            if progress.get("local_state") == "completed" and not accepted:
                quote = await request(
                    "POST",
                    path + "/plan/quote",
                    headers={"Idempotency-Key": f"qa-quote:{submission_id}"},
                )
                if (
                    type(quote.get("max_cost_paise")) is not int
                    or not 0 <= quote["max_cost_paise"] <= MAX_QUOTE_PAISE
                ):
                    raise SmokeFailure("qa_quote_over_cap")
                await request(
                    "POST",
                    path + "/plan",
                    headers={"Idempotency-Key": f"qa-accept:{submission_id}"},
                    json={
                        "plan_id": quote["id"],
                        "plan_fingerprint": quote["plan_fingerprint"],
                        "privacy_revision": quote["privacy_revision"],
                        "accepted": True,
                    },
                )
                accepted = True
            await asyncio.sleep(1)
        report = await request("GET", path + "/report")
        if (
            report.get("source_sha256") != FIXTURE_SHA256
            or report.get("report", {}).get("access") != "claimed_account"
        ):
            raise SmokeFailure("qa_report_binding_invalid")
        check_report_coaching(report["report"]["content"])
        coaching = await request("GET", f"/v1/me/coaching/calls/{submission_id}")
        if (
            coaching.get("schema") != "ac.sales-xray.call-coaching/1"
            or coaching.get("state") != "ready"
            or coaching.get("submission_id") != str(submission_id)
            or coaching.get("recording_id") != report.get("recording_id")
            or coaching.get("source_sha256") != FIXTURE_SHA256
            or coaching.get("transcript_revision") != report.get("transcript_revision")
            or coaching.get("report_revision") != content_hash(report["report"])
            or coaching.get("person_id") != person_id
            or coaching.get("tenant_id") != tenant_id
            or coaching.get("authority") != "provisional"
        ):
            raise SmokeFailure("qa_call_coaching_binding_invalid")
        return {
            "schema": "ac.sales-xray.qa-account-smoke/1",
            "environment": environment,
            "ok": True,
            "submission_id": str(submission_id),
            "recording_id": report["recording_id"],
            "report_run_id": report["run_id"],
            "fixture_sha256": FIXTURE_SHA256,
            "report_present": True,
            "per_call_coaching_present": True,
            "total_seconds": time.monotonic() - started,
        }
