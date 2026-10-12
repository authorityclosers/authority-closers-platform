"""Fictional candidate route, native transport, source failures and blocked-send proof."""

import json
import socket
import subprocess
import urllib.request
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest

from ac_platform.conversation_intelligence import providers, reports
from ac_platform.conversation_intelligence.coaching_validation_gate import (
    coaching_revision_runtime_block,
)
from scripts.report_candidate_c5 import replay as route
from tests.unit.conversation_intelligence.test_report_content import case


def inputs():
    transcript, roles, payload = case()
    packet = reports.parse_fact_packet(
        {"overview": "A fictional meeting discussion.", "observations": [], "uncertainties": []},
        transcript,
        chunk=reports.plan_transcript_chunks(transcript, max_input_chars=16_000)[0],
    )
    return transcript, roles, payload, [packet]


def envelope(payload):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"role": "model", "parts": [{"text": json.dumps(payload)}]},
            }
        ]
    }


def test_route_constructs_native_candidate_and_parses_with_the_same_roles(monkeypatch):
    transcript, roles, payload, packets = inputs()
    seen = []
    original_builder = route.tasks.prepare_coaching_input
    original_parser = route.reports.parse_groq_response

    def builder(*args, **kwargs):
        seen.append(("builder", deepcopy(kwargs)))
        return original_builder(*args, **kwargs)

    def parser(*args, **kwargs):
        seen.append(("parser", deepcopy(kwargs)))
        return original_parser(*args, **kwargs)

    monkeypatch.setattr(route.tasks, "prepare_coaching_input", builder)
    monkeypatch.setattr(route.reports, "parse_groq_response", parser)
    request = route.build_candidate(transcript, packets, roles, "en")
    body = json.loads(request.payload)
    config = body["generationConfig"]
    assert config["maxOutputTokens"] == 8000
    assert "report_content" in config["responseJsonSchema"]["properties"]
    assert "REPORT_CONTENT: report-content/1" in body["systemInstruction"]["parts"][0]["text"]
    source = json.loads(body["contents"][0]["parts"][0]["text"].split("\n", 1)[1])
    assert source["source_context"]["speaker_roles"] == roles
    result = route.parse_candidate(request, envelope(payload))
    assert result["draft"]["report_content"]["version"] == "report-content/1"
    assert result["draft"]["report_content"]["outcome"]["status"] == "Meeting Booked"
    assert [s[0] for s in seen] == ["builder", "parser"]
    assert all(s[1]["coaching_prompt_revision"] == "report-c5-v1" for s in seen)
    assert seen[0][1]["speaker_roles"] == seen[1][1]["speaker_roles"] == roles
    provenance = result["provenance"]
    assert provenance["source_sha256"] == transcript["source_sha256"]
    assert provenance["timebase_id"] == transcript["timebase_id"]
    assert provenance["transcript_revision"] == transcript["revision"]
    assert provenance["qualitative_pack_sha256"]
    assert coaching_revision_runtime_block("report-c5-v1") is not None


@pytest.mark.parametrize(
    "change", ["legacy", "wrong_schema", "wrong_actor", "malformed", "truncated"]
)
def test_candidate_parser_refuses_incompatible_outputs(change):
    transcript, roles, payload, packets = inputs()
    request = route.build_candidate(transcript, packets, roles, "en")
    if change == "legacy":
        del payload["report_content"]
    elif change == "wrong_schema":
        payload["report_content"]["version"] = "report-content/0"
    elif change == "wrong_actor":
        payload["report_content"]["outcome"]["actor_id"] = "seller"
    response = envelope(payload)
    if change == "malformed":
        response["candidates"][0]["content"]["parts"][0]["text"] = "{broken"
    elif change == "truncated":
        response["candidates"][0]["finishReason"] = "MAX_TOKENS"
    with pytest.raises(route.RouteError, match="candidate_output_incompatible"):
        route.parse_candidate(request, response)


@pytest.mark.parametrize("change", ["missing", "revision", "speaker", "unverified", "partial"])
def test_candidate_builder_refuses_missing_or_mismatched_roles(change):
    transcript, roles, _, packets = inputs()
    if change == "missing":
        roles = None
    elif change == "revision":
        roles["transcript_revision"] = "foreign-transcript"
    elif change == "speaker":
        roles["speakers"][0]["speaker_id"] = "foreign-speaker"
    elif change == "unverified":
        roles["origin"] = "text_predicted_roles"
    elif change == "partial":
        roles["speakers"].pop()
    with pytest.raises(route.RouteError, match="authoritative_roles"):
        route.build_candidate(transcript, packets, roles, "en")


def test_candidate_refuses_incomplete_coverage_and_source_mutation():
    transcript, roles, payload, packets = inputs()
    with pytest.raises(reports.ReportError, match="fact_packets_empty"):
        route.build_candidate(transcript, [], roles, "en")
    request = route.build_candidate(transcript, packets, roles, "en")
    with pytest.raises(route.RouteError, match="request_provenance_mismatch"):
        route.parse_candidate(replace(request, roles=route.canonical({})), envelope(payload))
    foreign_roles = deepcopy(roles)
    foreign_roles["speakers"][0]["is_account_holder"] = False
    provenance = json.loads(request.provenance)
    provenance["roles_sha256"] = route.digest(route.canonical(foreign_roles))
    with pytest.raises(route.RouteError, match="request_source_or_schema_mismatch"):
        route.parse_candidate(
            replace(
                request,
                roles=route.canonical(foreign_roles),
                provenance=route.canonical(provenance),
            ),
            envelope(payload),
        )


def test_unknown_pricing_is_refused(monkeypatch):
    monkeypatch.setitem(route.PINS["pricing"], "input_usd_per_million", None)
    with pytest.raises(route.RouteError, match="pricing_unknown"):
        route.estimate(b"fictional-request", 8000)


def test_wrong_image_and_library_are_refused(monkeypatch):
    receipt = {
        "image_digest": "sha256:" + "a" * 64,
        "build_source_sha": route.PINS["candidate_merge_sha"],
        "library_tree_sha256": route.PINS["library_tree_sha256"],
        "attestation_ref": "fictional-build-receipt",
    }
    with pytest.raises(route.RouteError, match="candidate_image"):
        route.require_image(receipt)
    monkeypatch.setitem(route.PINS, "image_receipt", receipt)
    route.require_image(receipt)
    with pytest.raises(route.RouteError, match="candidate_image"):
        route.require_image({**receipt, "build_source_sha": "wrong-image"})
    with pytest.raises(route.RouteError, match="candidate_image"):
        route.require_image({**receipt, "image_digest": "sha256:" + "b" * 64})
    monkeypatch.setitem(route.PINS, "library_tree_sha256", "0" * 64)
    with pytest.raises(route.RouteError, match="candidate_library_mismatch"):
        route.verify_library()


@pytest.mark.parametrize(
    "value,cap,error",
    [
        (None, 1, "cost_estimate_missing"),
        (float("nan"), 1, "cost_estimate_invalid"),
        (float("inf"), 1, "cost_estimate_invalid"),
        (-1, 1, "cost_estimate_invalid"),
        (2, 1, "cost_plan_over_cap"),
        (1, float("nan"), "explicit_finite_cap_missing"),
        (1, None, "explicit_finite_cap_missing"),
    ],
)
def test_cost_refusals(value, cap, error):
    estimate = None if value is None else {"configured_usd_upper_estimate": value}
    with pytest.raises(route.RouteError, match=error):
        route.admit_cost([estimate], cap)


def test_default_dry_run_with_blocked_network_provider_secret_and_subprocess(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("dry run attempted an external/secret/subprocess entrypoint")

    for obj, attr in [
        (socket, "socket"),
        (socket, "create_connection"),
        (urllib.request, "urlopen"),
        (httpx.Client, "send"),
        (httpx.AsyncClient, "send"),
        (subprocess, "run"),
        (subprocess, "Popen"),
    ]:
        monkeypatch.setattr(obj, attr, forbidden)
    monkeypatch.setattr(providers.BoundedProviders, "__init__", forbidden)
    monkeypatch.setattr(route.os, "getenv", forbidden)
    transcript, roles, _, packets = inputs()
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    manifest = {"calls": []}
    for key in sorted(route.KEYS):
        folder = f"calls/{key}"
        manifest["calls"].append(
            {"key": key, "folder": folder, "audio_ref": {"sha256": transcript["source_sha256"]}}
        )
        baseline = corpus / folder / "baseline"
        baseline.mkdir(parents=True)
        (baseline / "c2.json").write_bytes(route.canonical({"payload": transcript}))
        (baseline / "c4-chunks.json").write_bytes(
            route.canonical([{"payload": p.model_dump(mode="json")} for p in packets])
        )
        (baseline / "plans.json").write_bytes(route.canonical([{"speaker_roles": roles}]))
        (baseline / "c5.json").write_bytes(
            route.canonical({"manifest": {"config": {"report_language": "en"}}})
        )
    (corpus / "manifest.json").write_bytes(route.canonical(manifest))
    monkeypatch.setitem(route.PINS, "corpus_sha256", route.digest(route.canonical(manifest)))
    output = tmp_path / "output"
    ledger = route.plan(corpus, output, "fictional-offline-proof", route.APPROVAL, None)
    assert len(ledger["calls"]) == 16
    assert all(r["report"] == "request_constructed_only" for r in ledger["calls"])
    assert ledger["actual_spend_usd"] == 0
    assert ledger["configured_c5_total_usd"] is None
    assert ledger["cost_plan_state"] == "explicit_finite_cap_missing"
    assert (output / "ledger.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        route.plan(corpus, output, "fictional-offline-proof", route.APPROVAL, None)
