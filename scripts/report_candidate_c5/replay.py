#!/usr/bin/env python3
"""Pinned Report candidate construction/parsing only. No provider-send capability."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ac_platform.conversation_intelligence import inference_tasks as tasks
from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.gemini_tasks import decode_gemini_object
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.speaker_roles import validate_speaker_roles

HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / "pins.json").read_text())
KEYS = frozenset("ABCDEFGHIJKLMNOX")
APPROVAL = "OWNER-20261010-ALL-CALLS"
AUTHORITATIVE_ORIGINS = {"user_confirmed_roles", "channel_mapped_roles"}


class RouteError(ValueError):
    """Content-free route refusal; never include input or provider text."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def verify_library() -> str:
    root = Path(tasks.__file__).resolve().parent
    files = sorted(p for p in root.rglob("*") if p.suffix in {".py", ".json"})
    if any(p.is_symlink() for p in files):
        raise RouteError("library_symlink_refused")
    rows = [str(p.relative_to(root)) + "\0" + digest(p.read_bytes()) for p in files]
    sha = digest("\n".join(rows).encode())
    if sha != PINS["library_tree_sha256"] or len(files) != PINS["library_file_count"]:
        raise RouteError("candidate_library_mismatch")
    return sha


def require_image(receipt: dict[str, Any]) -> None:
    """Read a delivery-owner attestation; caller also retains its immutable source."""
    expected = PINS.get("image_receipt")
    if not isinstance(expected, dict) or receipt != expected:
        raise RouteError("candidate_image_attestation_missing_or_mismatched")
    image = receipt.get("image_digest", "")
    if (
        not isinstance(image, str)
        or len(image) != 71
        or not image.startswith("sha256:")
        or any(c not in "0123456789abcdef" for c in image[7:])
        or receipt.get("build_source_sha") != PINS["candidate_merge_sha"]
        or receipt.get("library_tree_sha256") != PINS["library_tree_sha256"]
        or not receipt.get("attestation_ref")
    ):
        raise RouteError("candidate_image_attestation_missing_or_mismatched")


def roles_for(transcript: dict[str, Any], snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise RouteError("authoritative_roles_missing")
    try:
        roles = validate_speaker_roles(snapshot, transcript)
    except ValueError:
        raise RouteError("authoritative_roles_mismatched") from None
    if roles["origin"] not in AUTHORITATIVE_ORIGINS:
        raise RouteError("authoritative_roles_unverified")
    return roles


@dataclass(frozen=True)
class CandidateRequest:
    """Byte-frozen source and attribution shared by the builder and parser."""

    payload: bytes
    transcript: bytes
    roles: bytes
    provenance: bytes


def build_candidate(
    transcript: dict[str, Any], packets: list[reports.FactPacket], snapshot: Any, language: str
) -> CandidateRequest:
    verify_library()
    source = deepcopy(transcript)
    roles = roles_for(source, snapshot)
    aggregate = reports.merge_fact_packets(packets, source)
    pack = load_qualitative_pack_for_revision("coaching-v5")
    profile = reports.load_report_profile()
    # Candidate deliberately reuses the v5 qualitative pack, as its own builder does.
    prepared = tasks.prepare_coaching_input(
        source,
        packets,
        provider=PINS["provider"],
        model=PINS["model"],
        profile=profile,
        report_language=language,
        qualitative_pack_sha256=pack.sha256,
        speaker_roles=roles,
        **PINS["c5"],
    )
    body = json.loads(prepared.payload)
    schema = body["generationConfig"].get("responseJsonSchema", {})
    if "report_content" not in schema.get("properties", {}):
        raise RouteError("candidate_wire_schema_missing")
    provenance = {
        "route": PINS["route"],
        "revision": PINS["revision"],
        "schema": PINS["schema"],
        "candidate_sha": PINS["candidate_sha"],
        "library_tree_sha256": PINS["library_tree_sha256"],
        "source_sha256": prepared.source_sha256,
        "transcript_revision": prepared.transcript_revision,
        "timebase_id": source["timebase_id"],
        "transcript_sha256": digest(canonical(source)),
        "roles_sha256": digest(canonical(roles)),
        "c4_coverage_sha256": digest(canonical(aggregate.covered_segment_ids)),
        "c4_packets_sha256": digest(canonical([p.model_dump(mode="json") for p in packets])),
        "c4_chunk_count": len(packets),
        "input_sha256": prepared.input_sha256,
        "schema_sha256": digest(canonical(schema)),
        "profile_revision": prepared.profile_revision,
        "profile_sha256": digest(canonical(profile)),
        "prompt": asdict(prepared.prompt_provenance),
        "qualitative_pack_id": pack.id,
        "qualitative_pack_sha256": pack.sha256,
        "max_output_tokens": prepared.max_completion_tokens,
    }
    return CandidateRequest(
        prepared.payload, canonical(source), canonical(roles), canonical(provenance)
    )


def parse_candidate(request: CandidateRequest, response: dict[str, Any]) -> dict[str, Any]:
    verify_library()
    provenance = json.loads(request.provenance)
    if (
        provenance.get("revision") != PINS["revision"]
        or provenance.get("schema") != PINS["schema"]
        or provenance.get("candidate_sha") != PINS["candidate_sha"]
        or provenance.get("input_sha256") != digest(request.payload)
        or provenance.get("transcript_sha256") != digest(request.transcript)
        or provenance.get("roles_sha256") != digest(request.roles)
    ):
        raise RouteError("request_provenance_mismatch")
    transcript = json.loads(request.transcript)
    roles = roles_for(transcript, json.loads(request.roles))
    body = json.loads(request.payload)
    source = json.loads(body["contents"][0]["parts"][0]["text"].split("\n", 1)[1])
    schema = body["generationConfig"].get("responseJsonSchema")
    profile = reports.load_report_profile()
    if (
        source["source_context"] != reports.coaching_source_context(transcript, speaker_roles=roles)
        or provenance.get("schema_sha256") != digest(canonical(schema))
        or provenance.get("profile_sha256") != digest(canonical(profile))
        or body["generationConfig"].get("maxOutputTokens") != PINS["c5"]["max_completion_tokens"]
    ):
        raise RouteError("request_source_or_schema_mismatch")
    try:
        decoded = decode_gemini_object(response)
        if decoded.get("report_content", {}).get("version") != PINS["schema"]:
            raise RouteError("candidate_output_schema_mismatch")
        draft = reports.parse_groq_response(
            decoded,
            transcript,
            profile=profile,
            coaching_prompt_revision=PINS["revision"],
            speaker_roles=roles,
        )
        if draft.report_content is None:
            raise RouteError("candidate_report_content_missing")
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RouteError("candidate_output_incompatible") from None
    return {
        "provenance": provenance,
        "response_sha256": digest(canonical(response)),
        "draft": draft.model_dump(mode="json"),
    }


def estimate(payload: bytes, maximum: int) -> dict[str, Any]:
    if type(maximum) is not int or maximum <= 0:
        raise RouteError("output_estimate_missing")
    # Entire native JSON envelope, including schema/escapes, one UTF-8 byte/token + 128.
    tokens = len(payload) + 128
    price = PINS["pricing"]
    rates = [price.get("input_usd_per_million"), price.get("output_usd_per_million")]
    if any(type(r) not in {int, float} or not math.isfinite(r) or r <= 0 for r in rates):
        raise RouteError("pricing_unknown")
    usd = (tokens * rates[0] + maximum * rates[1]) / 1_000_000
    return {
        "input_tokens_upper_estimate": tokens,
        "configured_max_output_tokens": maximum,
        "configured_usd_upper_estimate": usd,
        "pricing_ref": price["ref"],
    }


def admit_cost(estimates: list[dict[str, Any] | None], cap: float | None) -> float:
    if cap is None or type(cap) not in {int, float} or not math.isfinite(cap) or cap <= 0:
        raise RouteError("explicit_finite_cap_missing")
    if not estimates or any(e is None for e in estimates):
        raise RouteError("cost_estimate_missing")
    values = [e.get("configured_usd_upper_estimate") for e in estimates if e is not None]
    if any(type(v) not in {int, float} or not math.isfinite(v) or v < 0 for v in values):
        raise RouteError("cost_estimate_invalid")
    total = math.fsum(values)
    if not math.isfinite(total) or total > cap:
        raise RouteError("cost_plan_over_cap")
    return total


def retained_roles(baseline: Path, transcript: dict[str, Any]) -> dict[str, Any] | None:
    plans = read(baseline / "plans.json") if (baseline / "plans.json").exists() else []
    snapshots = [p["speaker_roles"] for p in plans if p.get("speaker_roles") is not None]
    if any(not isinstance(s, dict) for s in snapshots):
        raise RouteError("retained_roles_invalid")
    valid = [
        roles_for(transcript, s)
        for s in snapshots
        if s.get("transcript_revision") == transcript["revision"]
    ]
    if len({digest(canonical(s)) for s in valid}) > 1:
        raise RouteError("retained_roles_ambiguous")
    return valid[0] if valid else None


def private_write(path: Path, data: bytes) -> None:
    # Never replace existing corpus/history or an earlier output.
    with path.open("xb") as f:
        os.chmod(path, 0o600)
        f.write(data)


def plan(
    corpus: Path, output: Path, run_id: str, approval: str, cap: float | None
) -> dict[str, Any]:
    verify_library()
    if approval != APPROVAL:
        raise RouteError("all_call_selection_approval_missing")
    if cap is not None and (not math.isfinite(cap) or cap <= 0):
        raise RouteError("explicit_finite_cap_missing")
    manifest_path = corpus / "manifest.json"
    if digest(manifest_path.read_bytes()) != PINS["corpus_sha256"]:
        raise RouteError("corpus_pin_mismatch")
    calls = read(manifest_path)["calls"]
    if len(calls) != 16 or {c["key"] for c in calls} != KEYS:
        raise RouteError("all_16_selection_required")
    if corpus.resolve() == output.resolve() or corpus.resolve() in output.resolve().parents:
        raise RouteError("output_inside_retained_corpus_refused")
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    ledger: dict[str, Any] = {
        "run_id": run_id,
        "route": PINS["route"],
        "pins": PINS,
        "selection_approval": approval,
        "mode": "offline",
        "actual_spend_usd": 0,
        "cap_usd": cap,
        "route_source_hashes": {
            name: digest((HERE / name).read_bytes()) for name in ("replay.py", "pins.json")
        },
        "calls": [],
    }
    for call in calls:
        baseline = (corpus / call["folder"] / "baseline").resolve()
        if corpus.resolve() not in baseline.parents:
            raise RouteError("baseline_outside_corpus")
        row: dict[str, Any] = {
            "key": call["key"],
            "selected": True,
            "pipeline_disposition_issue": "AUT-1676" if call["key"] in "CDO" else None,
            "baseline_completed": (baseline / "c5.json").exists(),
            "report": "unavailable",
            "prospect": "not_evaluated",
            "coaching": "not_evaluated",
            "artifacts": {},
            "gaps": [],
            "c5_estimate": None,
        }
        for name in ("c2.json", "c4-chunks.json", "c5.json", "plans.json", "speaker-map.json"):
            path = baseline / name
            if path.exists():
                row["artifacts"][name] = {"path": str(path), "sha256": digest(path.read_bytes())}
        if not (baseline / "c2.json").exists():
            row["gaps"].append("retained_c2_missing")
            row["c4_regeneration_estimates"] = None
        else:
            transcript = read(baseline / "c2.json")["payload"]
            row["source_sha256"] = transcript["source_sha256"]
            row["transcript_revision"] = transcript["revision"]
            row["timebase_id"] = transcript["timebase_id"]
            if transcript["source_sha256"] != call["audio_ref"]["sha256"]:
                raise RouteError("corpus_audio_source_mismatch")
            try:
                c4 = tasks.prepare_fact_inputs(
                    transcript, provider=PINS["provider"], model=PINS["model"], **PINS["c4"]
                )
                row["c4_regeneration_estimates"] = [
                    estimate(t.payload, t.max_completion_tokens) for t in c4
                ]
                row["c4_regeneration_chunk_count"] = len(c4)
                row["c4_regeneration_request_hashes"] = [t.input_sha256 for t in c4]
                snapshot = retained_roles(baseline, transcript)
                if snapshot is None:
                    row["gaps"].append("authoritative_roles_missing")
                if not (baseline / "c4-chunks.json").exists():
                    row["gaps"].append("retained_c4_missing")
                else:
                    packets = [
                        reports.FactPacket.model_validate(r["payload"])
                        for r in read(baseline / "c4-chunks.json")
                    ]
                    aggregate = reports.merge_fact_packets(packets, transcript)
                    row["retained_c4_complete_chunks"] = len(packets)
                    row["retained_c4_coverage_sha256"] = digest(
                        canonical(aggregate.covered_segment_ids)
                    )
                    if snapshot is not None:
                        lang = (
                            read(baseline / "c5.json")["manifest"]["config"].get("report_language")
                            if (baseline / "c5.json").exists()
                            else None
                        )
                        if lang not in {"en", "hi-Deva+en", "mr-Deva+en"}:
                            raise RouteError("retained_output_language_missing")
                        request = build_candidate(transcript, packets, snapshot, lang)
                        row["c5_estimate"] = estimate(
                            request.payload, PINS["c5"]["max_completion_tokens"]
                        )
                        row["candidate_request_sha256"] = digest(request.payload)
                        private_write(output / f"{call['key']}.request.json", request.payload)
                        private_write(output / f"{call['key']}.provenance.json", request.provenance)
                        row["report"] = "request_constructed_only"
            except RouteError as e:
                row["gaps"].append(str(e))
            except (ValueError, TypeError, KeyError):
                row["gaps"].append("retained_input_invalid")
        ledger["calls"].append(row)
    c4_estimates = [e for r in ledger["calls"] for e in r.get("c4_regeneration_estimates") or []]
    ledger["c4_regeneration_known_chunk_count"] = len(c4_estimates)
    ledger["c4_regeneration_known_subtotal_usd"] = math.fsum(
        e["configured_usd_upper_estimate"] for e in c4_estimates
    )
    ledger["c4_regeneration_total_usd"] = (
        ledger["c4_regeneration_known_subtotal_usd"]
        if all(r.get("c4_regeneration_estimates") is not None for r in ledger["calls"])
        else None
    )
    ledger["estimator"] = (
        "entire native JSON UTF-8 bytes + 128 input tokens; configured output maximum"
    )
    ledger["budget_authorization"] = "missing; diagnostic cap is separate and grants no spend"
    estimates = [r["c5_estimate"] for r in ledger["calls"]]
    try:
        ledger["configured_c5_total_usd"] = admit_cost(estimates, cap)
        ledger["cost_plan_state"] = "configured_estimate_within_diagnostic_cap"
    except RouteError as e:
        ledger["configured_c5_total_usd"] = None
        ledger["cost_plan_state"] = str(e)
    ledger["real_send_admission"] = (
        "refused: no send implementation; image/gates/current price/cap required"
    )
    private_write(output / "ledger.json", canonical(ledger))
    return ledger


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=["report-candidate-c5"], default="report-candidate-c5")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument(
        "--max-usd", type=float, help="diagnostic cap only; grants no spend authority"
    )
    args = parser.parse_args()
    ledger = plan(args.corpus, args.output, args.run_id, args.approval, args.max_usd)
    print(
        json.dumps(
            {
                "run_id": ledger["run_id"],
                "calls": len(ledger["calls"]),
                "candidate_requests": sum(r["c5_estimate"] is not None for r in ledger["calls"]),
                "cost_plan_state": ledger["cost_plan_state"],
                "actual_spend_usd": 0,
            }
        )
    )
    if ledger["cost_plan_state"] == "cost_plan_over_cap":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
