"""Dry-run first; the named operator uses the ordinary sandbox cookie API for apply."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from itertools import chain
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.synthetic_import_dataset import (
    attachments,
    bundles,
    master_records,
    record_batches,
    summaries,
)

AC_SANDBOX = UUID("90ec1979-0d85-4829-ba8d-cabde2a9a9d3")
PREFIX = "/v1/conversation/acquisition/imports/sandbox"


def allowed_origin(value: str, tenant: UUID) -> str:
    url = urlsplit(value)
    if url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
        raise ValueError("Choose one exact credential-free sandbox origin.")
    if url.hostname in {"localhost", "127.0.0.1", "::1"} and url.scheme == "http":
        return value.rstrip("/")
    if (
        url.scheme == "https"
        and url.hostname == "salesxray-staging.authorityclosers.com"
        and url.port in {None, 443}
        and tenant == AC_SANDBOX
    ):
        return value.rstrip("/")
    raise ValueError("This operator supports loopback or the exact staging AC Sandbox only.")


def validate_dataset(root: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    fingerprint = hashlib.sha256()
    identities: set[tuple[str, str, int]] = set()
    for batch in record_batches(chain(master_records(root), summaries(root))):
        for row in batch.records:
            identity = (row.kind, row.key, row.revision)
            if identity in identities:
                raise ValueError("The dataset contains a repeated synthetic record revision.")
            identities.add(identity)
            counts[row.kind] += 1
            fingerprint.update(content_hash(row.model_dump(mode="json")).encode())
    for call in bundles(root):
        counts["call"] += 1
        fingerprint.update(content_hash(call.model_dump(by_alias=True)).encode())
    for attachment in attachments(root):
        counts["audio_manifest"] += 1
        counts["audio"] += 1
        fingerprint.update(content_hash(attachment.manifest.model_dump(by_alias=True)).encode())
    return {"synthetic": True, "counts": dict(counts), "dataset_sha256": fingerprint.hexdigest()}


def apply_dataset(
    root: Path, *, origin: str, tenant: UUID, cookie: str, receipt: dict[str, Any]
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    fingerprint = hashlib.sha256()
    with httpx.Client(
        base_url=origin,
        headers={"Cookie": cookie, "Origin": origin},
        timeout=30,
        follow_redirects=False,
        trust_env=False,
    ) as client:

        def send(path: str, body: dict[str, Any]) -> None:
            digest = content_hash(body)
            response = client.post(
                PREFIX + path, json=body, headers={"Idempotency-Key": "sandbox:" + digest}
            )
            if response.status_code != 201:
                # Do not print provider/application bodies, cookies or request objects.
                raise ValueError(
                    f"Sandbox import refused a request (HTTP {response.status_code}). "
                    "Rerun safely after correction."
                )
            result = response.json()
            if result.get("synthetic") is not True or result.get("state") != "done":
                raise ValueError(
                    "The sandbox API did not return an explicit synthetic delivery receipt."
                )
            counts["created"] += result.get("created", 0)
            counts["skipped"] += result.get("skipped", int(result.get("created") is False))

        response = client.get(PREFIX)
        if response.status_code != 200 or response.json().get("tenant_id") != str(tenant):
            raise ValueError(
                "The signed-in selected organisation is not the exact flagged sandbox target."
            )
        before = response.json()
        for batch in record_batches(chain(master_records(root), summaries(root))):
            for row in batch.records:
                fingerprint.update(content_hash(row.model_dump(mode="json")).encode())
            send("/records", batch.model_dump(mode="json", by_alias=True))
        for call in bundles(root):
            fingerprint.update(content_hash(call.model_dump(by_alias=True)).encode())
            send("/calls", call.model_dump(by_alias=True))
        for attachment in attachments(root):
            manifest = attachment.manifest.model_dump(by_alias=True)
            fingerprint.update(content_hash(manifest).encode())
            send(f"/calls/{attachment.manifest.call_id}/audio", manifest)
            with attachment.path.open("rb") as source:
                response = client.put(
                    PREFIX + f"/calls/{attachment.manifest.call_id}/source",
                    content=source,
                    headers={
                        "Content-Type": "audio/mpeg",
                        "Content-Length": str(attachment.manifest.audio_bytes),
                        "Idempotency-Key": "sandbox-audio:" + content_hash(manifest),
                    },
                )
            if (
                response.status_code != 201
                or response.json().get("synthetic") is not True
                or response.json().get("state") != "done"
                or type(response.json().get("created")) is not bool
            ):
                raise ValueError("The verified sandbox audio was not retained. Rerun safely.")
            counts["audio_created"] += int(response.json()["created"])
            counts["audio_skipped"] += int(not response.json()["created"])
        if fingerprint.hexdigest() != receipt["dataset_sha256"]:
            raise ValueError("The authored dataset changed after its dry-run source pin.")
        response = client.get(PREFIX)
        if response.status_code != 200:
            raise ValueError(
                "The sandbox read-back is unavailable; retain the receipts and rerun safely."
            )
        after = response.json()
        actual = {row["kind"]: row["count"] for row in after.get("records", [])}
        if actual != receipt["counts"]:
            raise ValueError("Sandbox read-back counts differ from the exact dry-run dataset.")
        return {
            **receipt,
            "applied": True,
            "tenant_id": str(tenant),
            "before": before,
            "after": after,
            "receipts": dict(counts),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--tenant-id", type=UUID, default=AC_SANDBOX)
    parser.add_argument("--base-url")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        receipt = validate_dataset(args.dataset.resolve())
        if args.apply:
            if not args.base_url:
                raise ValueError("Apply requires the exact sandbox origin.")
            origin = allowed_origin(args.base_url, args.tenant_id)
            cookie = os.environ.get("AC_SANDBOX_IMPORT_COOKIE")
            if not cookie:
                raise ValueError(
                    "The operator must inject its current sandbox session cookie at runtime."
                )
            receipt = apply_dataset(
                args.dataset.resolve(),
                origin=origin,
                tenant=args.tenant_id,
                cookie=cookie,
                receipt=receipt,
            )
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, httpx.HTTPError):
        print(
            "Synthetic dataset validation/import failed. "
            "No request content or credentials are displayed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
