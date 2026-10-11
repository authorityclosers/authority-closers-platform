"""Bounded adapter for Strike F's exact published files; no name-based identity merge."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ac_platform.conversation_intelligence.application import utc
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.synthetic_import_audio import SyntheticAudioManifest
from ac_platform.conversation_intelligence.synthetic_import_contracts import (
    MAX_BUNDLE_BYTES,
    SYNTHETIC_KEY,
    SyntheticCallBundle,
    SyntheticRecordBatch,
    SyntheticRecordInput,
)

OPERATIONS = (
    ("people", "people", "person_id", "fields.joined_on"),
    ("companies", "companies", "company_id", "founded_on"),
    ("contacts", "contacts", "person_id", None),
    ("leads", "leads", "lead_id", "created_at"),
    ("deals", "deals", "deal_id", "created_at"),
    ("invoices", "invoices", "invoice_id", "issued_at"),
    ("payments", "payments", "payment_id", "at"),
    ("calendar", "calendar", "event_id", "at"),
    ("people_events", "people_events", "event_id", "at"),
    ("rep_weeks", "rep_weeks", "rep_id", "week"),
    ("sales_events", "sales_events", "event_id", "at"),
    ("skill_trajectory", "skills", "rep_id", "at"),
    ("coaching_missions", "missions", "mission_id", "started_at"),
)


def record_batches(records: Iterable[SyntheticRecordInput]) -> Iterator[SyntheticRecordBatch]:
    """Bound ordinary JSON requests below the existing 1 MiB HTTP middleware cap."""
    pending: list[SyntheticRecordInput] = []
    size = 256
    for row in records:
        row_bytes = len(row.model_dump_json().encode()) + 1
        if pending and (len(pending) == 128 or size + row_bytes > 850 * 1024):
            yield SyntheticRecordBatch.model_validate(
                {
                    "schema": "synthetic-record-batch/1",
                    "synthetic": True,
                    "records": pending,
                }
            )
            pending, size = [], 256
        pending.append(row)
        size += row_bytes
    if pending:
        yield SyntheticRecordBatch.model_validate(
            {
                "schema": "synthetic-record-batch/1",
                "synthetic": True,
                "records": pending,
            }
        )


def exact_file(root: Path, relative: str) -> Path:
    """The dataset may select only a regular file under its own root."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("The synthetic dataset contains an unavailable or out-of-root file.")
    return path


def read_json(root: Path, relative: str, *, maximum: int = 2 * 1024 * 1024) -> Any:
    path = exact_file(root, relative)
    if path.stat().st_size > maximum:
        raise ValueError("A synthetic JSON file exceeds its input budget.")
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        while line := stream.readline(800 * 1024 + 1):
            if len(line.encode()) > 800 * 1024 or not line.endswith("\n"):
                raise ValueError("A synthetic JSONL record exceeds its input budget.")
            yield json.loads(line)


def date(row: dict[str, Any], path: str | None, *, baseline: str | None = None) -> datetime:
    value: Any = row
    if path is None:
        if baseline is None:
            raise ValueError("Undated master records require the published simulation baseline.")
        value = baseline + "T00:00:00+05:30"
    else:
        for part in path.split("."):
            value = value[part]
        # F publishes local calendar dates explicitly; the dataset timezone is IST.
        if isinstance(value, str) and len(value) == 10:
            value += "T00:00:00+05:30"
    if not isinstance(value, str):
        raise ValueError("A synthetic record is missing its authored date.")
    return datetime.fromisoformat(value)


def record(
    row: dict[str, Any],
    *,
    kind: str,
    identifier: str,
    at: str | None,
    businesses: tuple[str, ...],
    baseline: str | None = None,
) -> SyntheticRecordInput:
    key = row[identifier]
    if not isinstance(key, str) or not SYNTHETIC_KEY.fullmatch(key):
        raise ValueError("A synthetic entity is missing its immutable key.")
    business = row.get("business_id")
    if business is None:
        matches = [item for item in businesses if key == item or key.startswith(item + "-")]
        if len(matches) != 1:
            raise ValueError("A synthetic entity needs one exact published selling business.")
        business = matches[0]
    if kind in {"rep_weeks", "skills"}:
        key += ":" + utc(date(row, at)).strftime("%Y%m%dT%H%M%SZ")
    return SyntheticRecordInput.model_validate(
        {
            "kind": kind,
            "key": key,
            "business_id": business,
            "revision": row.get("revision", 1),
            "occurred_at": date(row, at, baseline=baseline),
            "payload": row,
        }
    )


def master_records(root: Path) -> Iterator[SyntheticRecordInput]:
    config = read_json(root, "simulation/config.json")
    baseline = config.get("start")
    if config.get("synthetic") is not True or not isinstance(baseline, str):
        raise ValueError("The dataset needs its explicit synthetic date baseline.")
    histories = list(lines(exact_file(root, "simulation/operations/business_history.jsonl.gz")))
    businesses = tuple(sorted({row["business_id"] for row in histories}))
    if not businesses:
        raise ValueError("The synthetic business index needs published identities.")
    for business in businesses:
        # Preserve products/prices, seller companies, initial reps, initial prospect
        # companies and contacts from the published world as one authored envelope.
        world = read_json(root, "world/" + business + ".json", maximum=8 * 1024 * 1024)
        yield record(
            world,
            kind="world",
            identifier="business_id",
            at=None,
            businesses=businesses,
            baseline=baseline,
        )
    for history in histories:
        # F publishes a business/price timeline without event IDs. Retain each
        # exact authored snapshot under an explicitly content-addressed key.
        yield SyntheticRecordInput.model_validate(
            {
                "kind": "business_history",
                "key": history["business_id"] + "-history:" + content_hash(history),
                "business_id": history["business_id"],
                "revision": 1,
                "occurred_at": date(history, "at"),
                "payload": history,
            }
        )
    for filename, kind, identifier, at in OPERATIONS:
        for row in lines(exact_file(root, f"simulation/operations/{filename}.jsonl.gz")):
            yield record(
                row,
                kind=kind,
                identifier=identifier,
                at=at,
                businesses=businesses,
                baseline=baseline,
            )


def summaries(root: Path) -> Iterator[SyntheticRecordInput]:
    histories = list(lines(exact_file(root, "simulation/operations/business_history.jsonl.gz")))
    businesses = tuple(sorted({row["business_id"] for row in histories}))
    files = sorted((root / "simulation/calls").glob("????-??.jsonl.gz"))
    if not files:
        raise ValueError("The published multi-year call stream is missing.")
    for path in files:
        for row in lines(exact_file(root, str(path.relative_to(root)))):
            yield record(
                row, kind="call_summary", identifier="call_id", at="at", businesses=businesses
            )


def bundles(root: Path) -> Iterator[SyntheticCallBundle]:
    index = read_json(root, "import_ready/index.json", maximum=8 * 1024 * 1024)
    if not isinstance(index, dict) or index.get("synthetic") is not True:
        raise ValueError("The full-call index must be explicitly synthetic.")
    entries = index.get("bundles")
    if not isinstance(entries, list) or len(entries) != index.get("calls"):
        raise ValueError("The full-call index must enumerate its exact count.")
    seen = set()
    for entry in entries:
        call_id = entry.get("call_id")
        if (
            not isinstance(call_id, str)
            or not SYNTHETIC_KEY.fullmatch(call_id)
            or call_id in seen
            or entry.get("folder") != "import_ready/" + call_id
        ):
            raise ValueError("The full-call index contains an invalid or repeated folder identity.")
        seen.add(call_id)
        data = {
            name: read_json(root, f"import_ready/{call_id}/{name}.json")
            for name in ("metadata", "transcript", "answer_key", "report", "coaching")
        }
        parsed = SyntheticCallBundle.model_validate(
            {"schema": "synthetic-call-bundle/1", "synthetic": True, **data}
        )
        if parsed.metadata["call_id"] != call_id:
            raise ValueError("The indexed call differs from its authored bundle identity.")
        yield parsed


@dataclass(frozen=True)
class SyntheticAudioAttachment:
    manifest: SyntheticAudioManifest
    path: Path


def verify_decode(path: Path, *, duration_ms: int) -> None:
    """Reproduce complete local MP3 decode; the operator runs this through ac-heavy."""
    try:
        probe_program, decode_program = shutil.which("ffprobe"), shutil.which("ffmpeg")
        if probe_program is None or decode_program is None:
            raise ValueError("The local media tools are unavailable.")
        probe = subprocess.run(  # noqa: S603 -- fixed argv, exact in-root file, no shell
            [
                probe_program,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_name",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        data = json.loads(probe.stdout)
        if (
            not data.get("streams")
            or any(row.get("codec_name") != "mp3" for row in data["streams"])
            or abs(float(data["format"]["duration"]) * 1000 - duration_ms) > 150
        ):
            raise ValueError("The verified media decode/duration differs from its receipt.")
        subprocess.run(  # noqa: S603 -- fixed offline decoder, bounded complete local read
            [
                decode_program,
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        raise ValueError("The synthetic MP3 could not be independently decoded.") from None


def attachments(root: Path) -> Iterator[SyntheticAudioAttachment]:
    verification = None
    for bundle in bundles(root):
        if bundle.metadata.get("audio_file") is None:
            continue
        if verification is None:
            verification = read_json(
                root, "validation/audio_verification.json", maximum=8 * 1024 * 1024
            )
            if not isinstance(verification, dict) or verification.get("synthetic") is not True:
                raise ValueError("Media verification must be explicitly synthetic.")
            receipts = verification.get("calls")
            if (
                not isinstance(receipts, list)
                or not 1 <= len(receipts) <= 4096
                or any(not isinstance(row, dict) for row in receipts)
            ):
                raise ValueError("Media verification needs a bounded canonical call index.")
        call_id = str(bundle.metadata["call_id"])
        matches = [row for row in verification.get("calls", []) if row.get("call_id") == call_id]
        if len(matches) != 1:
            raise ValueError("The indexed audio needs one exact canonical verification receipt.")
        path = exact_file(root, f"import_ready/{call_id}/audio.mp3")
        if not 0 < path.stat().st_size <= MAX_AUDIO_BYTES:
            raise ValueError("An audio attachment exceeds its byte budget.")
        sha = hashlib.sha256()
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                sha.update(block)
        timing_path = exact_file(root, f"import_ready/{call_id}/audio.timing.json")
        if timing_path.stat().st_size > MAX_BUNDLE_BYTES:
            raise ValueError("A timing attachment exceeds its byte budget.")
        timing_bytes = timing_path.read_bytes()
        manifest = SyntheticAudioManifest.model_validate(
            {
                "schema": "synthetic-call-audio/1",
                "synthetic": True,
                "call_id": call_id,
                "call_bundle_sha256": content_hash(bundle.model_dump(by_alias=True)),
                "audio_sha256": sha.hexdigest(),
                "audio_bytes": path.stat().st_size,
                "content_type": "audio/mpeg",
                "duration_ms": bundle.metadata["duration_ms"],
                "timing_file_sha256": hashlib.sha256(timing_bytes).hexdigest(),
                "timing": json.loads(timing_bytes),
                "verification": matches[0],
            }
        )
        manifest.require_bundle(bundle)
        verify_decode(path, duration_ms=manifest.duration_ms)
        yield SyntheticAudioAttachment(manifest=manifest, path=path)
