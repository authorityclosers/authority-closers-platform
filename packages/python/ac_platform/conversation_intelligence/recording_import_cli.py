"""Manifest-first operator for ordinary member-owned recording imports; dry-run by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ac_platform.conversation_intelligence.acquisition_usage import (
    LONGEST_CALL_EXCEEDED_MESSAGE,
    TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE,
)
from ac_platform.conversation_intelligence.bulk_import_contracts import ImportConfirmation
from ac_platform.conversation_intelligence.bulk_import_preview import (
    MAX_BATCH_BYTES,
    MAX_BATCH_FILES,
    BatchManifest,
    BatchSource,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.processing_plan import PlanAcceptance

PREFIX = "/v1/conversation/acquisition"
SHA = re.compile(r"[0-9a-f]{64}\Z")
TERMINAL = {"done", "failed", "held", "already_imported", "expired", "needs_member"}
STATES = TERMINAL | {"awaiting_upload", "queued", "working", "retrying", "unavailable"}
CAPACITY_DETAIL = (
    "The previous batch recording is still processing. Other callers can continue uploading."
)
ITEM_REFUSALS = {
    (403, TRIAL_ALLOWANCE_INSUFFICIENT_MESSAGE),
    (403, LONGEST_CALL_EXCEEDED_MESSAGE),
    (403, "The complete plan exceeds the effective provider budget."),
    (409, "The provider budget cannot cover this complete plan."),
    (409, "The approved allowance cannot cover this bounded processing plan."),
}


class RequestRefused(ValueError):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(f"Recording import refused a request (HTTP {status}).")
        self.status, self.reason = status, reason


def origin(value: str) -> str:
    url = urlsplit(value)
    if url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
        raise ValueError("Choose one credential-free recording import origin.")
    if url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}:
        return value.rstrip("/")
    if (
        url.scheme == "https"
        and url.hostname == "salesxray-staging.authorityclosers.com"
        and url.port in {None, 443}
    ):
        return value.rstrip("/")
    raise ValueError("Use loopback or the exact staging recording import origin.")


def uuid(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
        raise ValueError("Use an exact current organisation/member identifier.")
    return value


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


@dataclass(frozen=True)
class Source:
    source: BatchSource
    path: Path
    person: str
    person_id: str | None


@dataclass(frozen=True)
class Inventory:
    sha256: str
    files: list[Source]
    held: list[dict[str, Any]]
    total: int

    def manifest(self, *, assigned: bool) -> BatchManifest:
        return BatchManifest(files=[f.source for f in self.files if not assigned or f.person_id])

    def receipt(self) -> dict[str, Any]:
        return {
            "source_manifest_sha256": self.sha256,
            "total_files": self.total,
            "within_upload_limit": len(self.files),
            "assigned_files": sum(f.person_id is not None for f in self.files),
            "held": self.held,
            "within_limit_by_person": dict(Counter(f.person for f in self.files)),
            "total_by_person": dict(
                Counter(f.person for f in self.files)
                + Counter(h["person"] for h in self.held if h["reason"] == "upload_limit")
            ),
        }


def inventory(manifest_path: Path, members_path: Path | None = None) -> Inventory:
    root = manifest_path.resolve().parent
    document = json.loads(manifest_path.read_text())
    rows = document.get("files") if isinstance(document, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BATCH_FILES:
        raise ValueError("Use the downloaded bounded recording manifest.")
    members = json.loads(members_path.read_text()) if members_path else {}
    if not isinstance(members, dict) or any(not isinstance(key, str) or not key for key in members):
        raise ValueError("Use explicit person-label to current member-ID assignments.")
    for member in members.values():
        if member is not None:
            uuid(member)
    files: list[Source] = []
    held: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_bytes = 0
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("person"), str)
            or not row["person"]
            or not isinstance(row.get("file"), str)
            or type(row.get("bytes")) is not int
            or row["bytes"] < 1
            or not isinstance(row.get("sha256"), str)
            or SHA.fullmatch(row["sha256"]) is None
            or type(row.get("duration_s")) not in {int, float}
            or not math.isfinite(row["duration_s"])
            or row["duration_s"] <= 0
        ):
            raise ValueError("A recording manifest row is unavailable.")
        relative = BatchSource.bounded_relative_path(row["file"])
        if relative in seen or row.get("folder") != relative.split("/", 1)[0]:
            raise ValueError("Recording paths/folders must be unique and exact.")
        seen.add(relative)
        path = (root / row["file"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("A recording manifest path leaves its approved folder.")
        if path.stat().st_size != row["bytes"] or file_digest(path) != row["sha256"]:
            raise ValueError("The downloaded recording changed from its manifest.")
        total_bytes += row["bytes"]
        reason = "upload_limit" if row["bytes"] > MAX_AUDIO_BYTES else "needs_member"
        person_id = members.get(row["person"])
        if row["bytes"] > MAX_AUDIO_BYTES or person_id is None:
            held.append({"index": index, "person": row["person"], "reason": reason})
        if row["bytes"] <= MAX_AUDIO_BYTES:
            files.append(
                Source(
                    BatchSource(
                        relative_path=relative,
                        source_bytes=row["bytes"],
                        source_sha256=row["sha256"],
                    ),
                    path,
                    row["person"],
                    person_id,
                )
            )
    if total_bytes > MAX_BATCH_BYTES:
        raise ValueError("Use recording manifests up to the ordinary 1 GiB batch cap.")
    # Include explicit assignments in the source pin; never adopt name suggestions.
    return Inventory(
        content_hash({"manifest": document, "members": members}), files, held, len(rows)
    )


def request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = client.request(method, PREFIX + path, **kwargs)
    return response_receipt(response)


def response_receipt(response: httpx.Response) -> dict[str, Any]:
    if response.status_code not in {200, 201, 202}:
        try:
            problem = response.json()
        except ValueError:
            problem = None
        detail = problem.get("detail") if isinstance(problem, dict) else None
        reason = (
            "local_capacity"
            if response.status_code == 409 and detail == CAPACITY_DETAIL
            else "temporarily_unavailable"
            if response.status_code in {429, 502, 503, 504}
            else "item_refused"
            if response.status_code in {402, 413, 415, 422}
            or isinstance(detail, str)
            and (response.status_code, detail) in ITEM_REFUSALS
            else "authority_or_conflict"
        )
        raise RequestRefused(response.status_code, reason)
    try:
        result = response.json()
    except ValueError:
        result = None
    if not isinstance(result, dict):
        raise ValueError("The recording import receipt is unavailable.")
    return result


def preview(
    client: httpx.Client, value: Inventory, tenant: str, *, assigned: bool
) -> dict[str, Any]:
    manifest = value.manifest(assigned=assigned)
    result = request(client, "POST", "/imports/preview", json=manifest.model_dump(mode="json"))
    expected_folders = {f.folder for f in manifest.files}
    folders, members = result.get("folders"), result.get("members")
    if (
        result.get("tenant_id") != tenant
        or result.get("manifest_sha256") != content_hash(manifest.model_dump(mode="json"))
        or result.get("requires_confirmation") is not True
        or type(result.get("total_files")) is not int
        or result.get("total_files") != len(manifest.files)
        or type(result.get("total_bytes")) is not int
        or result.get("total_bytes") != sum(f.source_bytes for f in manifest.files)
        or not isinstance(folders, list)
        or any(not isinstance(f, dict) or not isinstance(f.get("folder"), str) for f in folders)
        or {f["folder"] for f in folders} != expected_folders
        or len(folders) != len(expected_folders)
        or not isinstance(members, list)
        or any(not isinstance(m, dict) for m in members)
    ):
        raise ValueError("Preview did not bind the exact organisation and manifest.")
    member_ids = {uuid(m.get("person_id")) for m in members}
    if any(f.person_id not in member_ids for f in value.files if f.person_id is not None):
        raise ValueError("A confirmed member is unavailable in the selected organisation.")
    return result


def batch_receipt(
    result: dict[str, Any],
    *,
    tenant: str,
    manifest: BatchManifest | None = None,
    policy: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    uuid(result.get("batch_id"))
    rows = result.get("files")
    if (
        result.get("tenant_id") != tenant
        or (batch_id is not None and result["batch_id"] != batch_id)
        or (policy is not None and result.get("policy_sha256") != policy)
        or not isinstance(rows, list)
        or not rows
        or len(rows) > MAX_BATCH_FILES
        or type(result.get("total_files")) is not int
        or result["total_files"] != len(rows)
        or result.get("terminal_state") not in (None, "done", "failed")
        or any(
            not isinstance(result.get(field), str) or SHA.fullmatch(result[field]) is None
            for field in ("manifest_sha256", "policy_sha256")
        )
    ):
        raise ValueError("Batch progress does not bind the selected organisation.")
    if manifest is not None and (
        result.get("manifest_sha256") != content_hash(manifest.model_dump(mode="json"))
        or len(rows) != len(manifest.files)
    ):
        raise ValueError("Batch progress does not bind the exact source manifest.")
    items = []
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or row.get("item_index") != index
            or type(row.get("item_index")) is not int
            or not isinstance(row.get("state"), str)
            or row["state"] not in STATES
            or not isinstance(row.get("source_sha256"), str)
            or SHA.fullmatch(row["source_sha256"]) is None
            or type(row.get("source_bytes")) is not int
            or not 1 <= row["source_bytes"] <= MAX_AUDIO_BYTES
        ):
            raise ValueError("An import item is unavailable.")
        uuid(row.get("upload_submission_id"))
        if row.get("submission_id") is not None:
            uuid(row["submission_id"])
        if manifest is not None and (
            row["source_sha256"] != manifest.files[index].source_sha256
            or row["source_bytes"] != manifest.files[index].source_bytes
        ):
            raise ValueError("An import item changed its source binding.")
        for field in ("person_id", "confirmed_person_id"):
            if row.get(field) is not None:
                uuid(row[field])
        minute_state = row.get("minute_state")
        run_state = row.get("run_state")
        stage = row.get("current_stage")
        local_state, plan_state, terminal_state = (
            row.get("local_state"),
            row.get("plan_state"),
            row.get("terminal_state"),
        )
        if (
            minute_state not in (None, "reserved", "released", "delivered")
            or run_state not in (None, "queued", "working", "retrying", "failed", "done")
            or (
                stage is not None
                and (not isinstance(stage, str) or re.fullmatch(r"C[0-6]", stage) is None)
            )
            or type(row.get("retry_available", False)) is not bool
            or local_state not in (None, "queued", "running", "completed", "failed", "cancelled")
            or plan_state not in (None, "quoted", "active", "held", "completed", "cancelled")
            or terminal_state not in (None, "done", "failed")
        ):
            raise ValueError("The canonical call progress receipt is unavailable.")
        items.append(
            {
                **{
                    field: row[field]
                    for field in (
                        "item_index",
                        "state",
                        "source_sha256",
                        "source_bytes",
                        "upload_submission_id",
                    )
                },
                "submission_id": row.get("submission_id"),
                "person_id": row.get("person_id"),
                "confirmed_person_id": row.get("confirmed_person_id"),
                "run_state": run_state,
                "minute_state": minute_state,
                "current_stage": stage,
                "retry_available": row.get("retry_available", False),
                "local_state": local_state,
                "plan_state": plan_state,
                "terminal_state": terminal_state,
            }
        )
    if type(result.get("total_bytes")) is not int or result["total_bytes"] != sum(
        row["source_bytes"] for row in rows
    ):
        raise ValueError("The import byte receipt is unavailable.")
    if result.get("terminal_state") is not None and any(
        row["state"] not in TERMINAL for row in rows
    ):
        raise ValueError("In-flight calls cannot be reported as delivered.")
    if result.get("terminal_state") == "done" and any(
        row["state"] not in {"done", "already_imported"} for row in rows
    ):
        raise ValueError("Failed or unassigned calls cannot be reported as delivered.")
    # Operator receipts contain identifiers/status only, even if a later API adds fields.
    return {
        **{
            field: result[field]
            for field in (
                "batch_id",
                "tenant_id",
                "manifest_sha256",
                "policy_sha256",
                "total_files",
                "total_bytes",
                "terminal_state",
            )
        },
        "files": items,
    }


def advance_item(
    client: httpx.Client,
    batch: dict[str, Any],
    item: dict[str, Any],
    value: Inventory,
    manifest: BatchManifest,
) -> str:
    if item["state"] == "awaiting_upload":
        source = manifest.files[item["item_index"]]
        file = next(f for f in value.files if f.source.relative_path == source.relative_path)
        if (
            file.path.stat().st_size != source.source_bytes
            or file_digest(file.path) != source.source_sha256
        ):
            raise ValueError("A recording changed before upload; resume only the same source.")
        with file.path.open("rb") as stream:
            uploaded = request(
                client,
                "PUT",
                f"/submissions/{item['upload_submission_id']}/source",
                content=stream,
                headers={
                    "X-Recording-Import": batch["batch_id"],
                    "X-Recording-Import-Item": str(item["item_index"]),
                    "X-Source-SHA256": source.source_sha256,
                    "X-Upload-Policy": batch["policy_sha256"],
                    "X-Upload-Consent": "accepted",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(source.source_bytes),
                },
                timeout=180,
            )
        uuid(uploaded.get("submission_id"))
        if uploaded.get("source_sha256") != source.source_sha256:
            raise ValueError("Upload did not return its exact source receipt.")
        return "advanced"
    submission = uuid(item.get("submission_id"))
    headers = {
        "X-Recording-Import": batch["batch_id"],
        "X-Recording-Import-Item": str(item["item_index"]),
    }
    progress = request(client, "GET", f"/submissions/{submission}", headers=headers)
    if progress.get("source_sha256") != item["source_sha256"]:
        raise ValueError("Call progress changed its source binding.")
    if (
        progress.get("run_state") == "failed"
        or progress.get("terminal_state") == "failed"
        or progress.get("local_state") in {"failed", "cancelled"}
        or progress.get("plan_state") in {"held", "cancelled"}
        and progress.get("local_state") == "completed"
    ):
        return "needs_attention"
    if (
        progress.get("local_state") != "completed"
        or progress.get("automatic_progression") is not False
        or progress.get("has_report") is not False
    ):
        return "waiting"
    recording = uuid(progress.get("recording_id"))
    response = client.get(PREFIX + f"/submissions/{submission}/plan", headers=headers)
    if response.status_code == 404:
        plan = request(
            client,
            "POST",
            f"/submissions/{submission}/plan/quote",
            headers={
                **headers,
                "Idempotency-Key": f"import-plan:{batch['batch_id']}:{item['item_index']}",
            },
            json={"report_language": "en"},
        )
    else:
        plan = response_receipt(response)
    if not isinstance(plan, dict) or plan.get("recording_id") != recording:
        raise ValueError("The plan does not bind this call.")
    uuid(plan.get("id"))
    if plan.get("state") in {"held", "cancelled"}:
        return "needs_attention"
    if plan.get("accepted") is True:
        return "waiting"
    if (
        plan.get("accepted") is not False
        or plan.get("state") != "quoted"
        or type(plan.get("expires_at_epoch")) is not int
        or plan["expires_at_epoch"] <= time.time()
    ):
        return "needs_attention"
    acceptance = PlanAcceptance.model_validate(
        {
            "plan_id": plan["id"],
            "plan_fingerprint": plan.get("plan_fingerprint"),
            "privacy_revision": plan.get("privacy_revision"),
            "accepted": True,
        }
    )
    accepted = request(
        client,
        "POST",
        f"/submissions/{submission}/plan",
        headers={**headers, "Idempotency-Key": f"accept-plan:{plan['id']}"},
        json=acceptance.model_dump(mode="json"),
    )
    if (
        accepted.get("id") != plan["id"]
        or accepted.get("recording_id") != recording
        or accepted.get("plan_fingerprint") != plan["plan_fingerprint"]
        or accepted.get("accepted") is not True
    ):
        raise ValueError("The exact analysis acceptance receipt is unavailable. Resume safely.")
    return "advanced"


def advance(
    client: httpx.Client,
    batch: dict[str, Any],
    value: Inventory,
    manifest: BatchManifest,
    attention: dict[int, dict[str, Any]],
) -> bool:
    # Provider processing may continue while the next source passes local C0/C1.
    # Attention is an operator-window skip, never a mutation of canonical state.
    for item in batch["files"]:
        index = item["item_index"]
        if index in attention or item["state"] in TERMINAL:
            continue
        if item["local_state"] == "completed" and item["plan_state"] == "active":
            continue
        try:
            outcome = advance_item(client, batch, item, value, manifest)
        except RequestRefused as error:
            if error.reason != "item_refused":
                raise
            attention[index] = {"item_index": index, "reason": error.reason, "status": error.status}
            continue
        if outcome == "needs_attention":
            attention[index] = {"item_index": index, "reason": "needs_attention"}
        elif outcome == "advanced":
            return True
    return False


def apply(client: httpx.Client, value: Inventory, tenant: str, *, max_wait: int) -> dict[str, Any]:
    manifest = value.manifest(assigned=True)
    viewed = preview(client, value, tenant, assigned=True)
    policy = request(client, "GET", "/upload-policy").get("policy_sha256")
    if not isinstance(policy, str) or SHA.fullmatch(policy) is None:
        raise ValueError("The current upload terms are unavailable.")
    folders: dict[str, str] = {}
    for file in value.files:
        if (
            file.person_id is not None
            and folders.setdefault(file.source.folder, file.person_id) != file.person_id
        ):
            raise ValueError("Each folder requires one exact confirmed current member.")
    confirmation = ImportConfirmation.model_validate(
        {
            "manifest": manifest.model_dump(mode="json"),
            "manifest_sha256": viewed["manifest_sha256"],
            "policy_sha256": policy,
            "rights_confirmed": True,
            "folders": [
                {"folder": folder, "person_id": member} for folder, member in folders.items()
            ],
        }
    )
    body = confirmation.model_dump(mode="json")
    batch = batch_receipt(
        request(
            client,
            "POST",
            "/imports",
            json=body,
            headers={"Idempotency-Key": "drive-import:" + content_hash(body)},
        ),
        tenant=tenant,
        manifest=manifest,
        policy=policy,
    )
    batch_id, deadline = batch["batch_id"], time.monotonic() + max_wait
    attention: dict[int, dict[str, Any]] = {}
    backoff, waiting_reason, read_back_pending = 60, None, False
    while time.monotonic() < deadline and any(
        r["state"] not in TERMINAL and r["item_index"] not in attention for r in batch["files"]
    ):
        try:
            advanced = False
            if not read_back_pending:
                advanced = advance(client, batch, value, manifest, attention)
                backoff, waiting_reason = 60, None
        except RequestRefused as error:
            if error.reason not in {"local_capacity", "temporarily_unavailable"}:
                raise
            advanced, waiting_reason = False, error.reason
        except httpx.TransportError:
            # An upload/acceptance may have committed. Read back before another
            # attempt, using the same item/hash/idempotency keys.
            advanced, waiting_reason = False, "ambiguous_request"
        remaining = deadline - time.monotonic()
        if remaining < backoff:
            # Preserve the result of the last write even when no poll fits in
            # the remaining window. A future invocation resumes this receipt.
            if advanced or waiting_reason == "ambiguous_request":
                try:
                    batch = batch_receipt(
                        request(client, "GET", f"/imports/{batch_id}"),
                        tenant=tenant,
                        manifest=manifest,
                        policy=policy,
                        batch_id=batch_id,
                    )
                except RequestRefused as error:
                    if error.reason != "temporarily_unavailable":
                        raise
                    waiting_reason = error.reason
                except httpx.TransportError:
                    waiting_reason = "read_back_unavailable"
            break
        time.sleep(backoff)
        try:
            batch = batch_receipt(
                request(client, "GET", f"/imports/{batch_id}"),
                tenant=tenant,
                manifest=manifest,
                policy=policy,
                batch_id=batch_id,
            )
            read_back_pending = False
        except RequestRefused as error:
            if error.reason != "temporarily_unavailable":
                raise
            read_back_pending, waiting_reason = True, error.reason
        except httpx.TransportError:
            read_back_pending, waiting_reason = True, "read_back_unavailable"
        if waiting_reason:
            backoff = min(300, backoff * 2)
        elif advanced:
            backoff = 60
    states = [
        row["run_state"] or "already_imported"
        if row["state"] == "already_imported"
        else row["state"]
        for row in batch["files"]
    ]
    outcome = (
        "failed"
        if attention or any(s in {"failed", "held", "expired"} for s in states)
        else "done"
        if all(s == "done" for s in states)
        else "already_imported"
        if all(s in {"done", "already_imported"} for s in states)
        else "waiting"
    )
    for row in batch["files"]:
        if row["state"] in {"failed", "held", "expired", "needs_member"}:
            attention.setdefault(
                row["item_index"],
                {
                    "item_index": row["item_index"],
                    "reason": row["state"],
                },
            )
    return {
        **value.receipt(),
        "batch": batch,
        "state": outcome,
        "attention": list(attention.values()),
        "waiting_reason": waiting_reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--members-file", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--tenant-id", type=UUID)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--read-back", type=UUID, metavar="BATCH_ID")
    parser.add_argument("--confirm-recording-rights", action="store_true")
    parser.add_argument("--accept-analysis-plans", action="store_true")
    parser.add_argument("--max-wait-seconds", type=int, default=3600)
    args = parser.parse_args()
    try:
        if not 0 <= args.max_wait_seconds <= 86400:
            raise ValueError("Choose a bounded operator window up to one day.")
        value = inventory(args.manifest, args.members_file)
        result = value.receipt()
        if args.preview or args.apply or args.read_back:
            if not args.base_url or args.tenant_id is None:
                raise ValueError("Select the exact current organisation and origin.")
            target = origin(args.base_url)
            tenant = uuid(str(args.tenant_id))
            cookie = os.environ.get("AC_RECORDING_IMPORT_COOKIE")
            if not cookie:
                raise ValueError("Inject the operator's current session at runtime.")
            if args.apply and not (args.confirm_recording_rights and args.accept_analysis_plans):
                raise ValueError("Confirm recording rights and ordinary analysis plans explicitly.")
            with httpx.Client(
                base_url=target,
                headers={"Cookie": cookie, "Origin": target, "X-Recording-Import-Tenant": tenant},
                timeout=30,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                if args.preview:
                    viewed = preview(client, value, tenant, assigned=False)
                    result = {
                        **result,
                        "tenant_id": tenant,
                        "members": [
                            {
                                "person_id": m["person_id"],
                                "display_name": m.get("display_name")
                                if isinstance(m.get("display_name"), str)
                                else "Member",
                            }
                            for m in viewed["members"]
                        ],
                    }
                elif args.read_back:
                    result = batch_receipt(
                        request(client, "GET", f"/imports/{args.read_back}"),
                        tenant=tenant,
                        batch_id=str(args.read_back),
                    )
                else:
                    result = apply(client, value, tenant, max_wait=args.max_wait_seconds)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, httpx.HTTPError):
        print(
            "Recording import unavailable. No call content or credentials are displayed; "
            "resume with the same manifest after correction.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
