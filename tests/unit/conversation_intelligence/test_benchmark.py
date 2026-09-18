"""Offline runner boundaries and actual failure detection, with no network access."""

from __future__ import annotations

import hashlib
import json
import socket
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence import benchmark as module
from ac_platform.conversation_intelligence import benchmark_cli as cli
from ac_platform.conversation_intelligence.benchmark import (
    BenchmarkError,
    Suite,
    bounded_json,
    compare,
    selected_cases,
)
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash

FIXTURES = Path(__file__).parents[2] / "fixtures" / "sales_xray_offline_benchmark"
RUN = UUID("8762a002-8a2c-4f69-becf-00e02a64b5b1")


def data():
    suite = Suite.model_validate(json.loads((FIXTURES / "manifest.json").read_bytes()))
    return suite, {
        case.case_id: (FIXTURES / case.input.name).read_bytes()
        for case in selected_cases(suite)
        if case.input is not None
    }


def changed_case(suite, inputs, case_id, mutate):
    raw = suite.model_dump()
    payload = json.loads(inputs[case_id])
    mutate(payload)
    changed = canonical(payload)
    next_inputs = {**inputs, case_id: changed}
    for case in raw["cases"]:
        if case["case_id"] == case_id:
            case["input"]["sha256"] = hashlib.sha256(changed).hexdigest()
    return Suite.model_validate(raw), next_inputs


def execute(suite, inputs):
    return compare(suite, inputs, run_id=RUN, implementation_sha256="a" * 64)


def test_runs_real_kernel_once_per_case_and_reuses_context_for_both_profiles(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline comparison must not open a network socket")

    monkeypatch.setattr(socket, "socket", no_network)
    suite, inputs = data()
    before = deepcopy(inputs)
    result = execute(suite, inputs)
    assert result["state"] == "passed"
    assert result["comparison_count"] == 16
    assert result["context_executions"] == 8
    assert result["profile_case_executions"] == 14
    assert result["provider_calls"] == result["asr_calls"] == result["provider_cost_paise"] == 0
    assert result["model_quality_measured"] is False
    assert result["numeric_publication"] == "withheld"
    assert inputs == before
    for case in suite.selected_case_ids:
        rows = [r for r in result["rows"] if r["case_id"] == case]
        assert len({r["context_sha256"] for r in rows}) == 1
        assert len({r["transcript_sha256"] for r in rows}) == 1
        assert all(r["candidate_elapsed_ns"] > 0 for r in rows)
    assert result["receipt_sha256"] == content_hash(
        {k: v for k, v in result.items() if k != "receipt_sha256"}
    )


def test_incorrect_fixture_expectation_fails_both_candidates_instead_of_claiming_success():
    suite, inputs = data()
    suite, inputs = changed_case(
        suite,
        inputs,
        "price-without-context",
        lambda value: value["expected_slots"]["price_objection"].update(value=1),
    )
    result = execute(suite, inputs)
    assert result["state"] == "failed"
    failed = [row for row in result["rows"] if row["state"] == "failed"]
    assert len(failed) == 2
    assert all(row["failed_checks"] == ["context_slot_mismatch"] for row in failed)


def test_rejected_case_does_not_pass_for_a_different_failure_stage():
    suite, inputs = data()
    suite, inputs = changed_case(
        suite,
        inputs,
        "forged-evidence",
        lambda value: value.update(expected_rejection_stage="packet"),
    )
    failed = [r for r in execute(suite, inputs)["rows"] if r["state"] == "failed"]
    assert len(failed) == 2
    assert all(r["failed_checks"] == ["wrong_rejection_stage"] for r in failed)


def test_profile_mutation_is_detected_without_contaminating_other_candidate(monkeypatch):
    original = module.project_profile

    def defective(profile, context):
        result = original(profile, context)
        if profile["id"] == "dipak_draft" and "tenant_id" in context:
            context["fact_state_hash"] = "broken"
        return result

    monkeypatch.setattr(module, "project_profile", defective)
    suite, inputs = data()
    result = execute(suite, inputs)
    assert result["state"] == "failed"
    assert any("profile_mutated_context" in r["failed_checks"] for r in result["rows"])
    assert all(
        r["state"] == "passed"
        for r in result["rows"]
        if r["candidate_id"] == "wording-fixture-bounded"
    )


@pytest.mark.parametrize(
    "change",
    ["holdout-selection", "source-leak", "participant-leak", "holdout-file", "duplicate-candidate"],
)
def test_partition_and_identity_errors_are_rejected_before_inputs(change):
    suite, _ = data()
    raw = suite.model_dump()
    if change == "holdout-selection":
        raw["selected_case_ids"] = ["sealed-metadata-only"]
    elif change == "source-leak":
        raw["cases"][-1]["source_sha256"] = raw["cases"][0]["source_sha256"]
    elif change == "participant-leak":
        raw["cases"][-1]["participant_partition_sha256"] = raw["cases"][0][
            "participant_partition_sha256"
        ]
    elif change == "holdout-file":
        raw["cases"][-1]["input"] = raw["cases"][0]["input"]
    else:
        raw["candidates"].append(raw["candidates"][0])
    with pytest.raises(BenchmarkError):
        selected_cases(Suite.model_validate(raw))


@pytest.mark.parametrize(
    "name",
    [
        "../escape.json",
        "C:/secret.json",
        "/private/secret.json",
        "https://test/file.json",
        "x.py",
        "x.json?key=bad",
    ],
)
def test_fixture_paths_cannot_be_urls_or_escape_the_manifest_directory(name):
    suite, _ = data()
    raw = suite.model_dump()
    raw["cases"][0]["input"]["name"] = name
    with pytest.raises(ValidationError):
        Suite.model_validate(raw)


def test_digest_tampering_and_unselected_input_are_rejected():
    suite, inputs = data()
    with pytest.raises(BenchmarkError, match="digest"):
        execute(suite, {**inputs, "forged-evidence": b"{}"})
    with pytest.raises(BenchmarkError, match="exactly"):
        execute(suite, {**inputs, "sealed-metadata-only": b"DO NOT OPEN"})


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b"[]",
        b"{" + b"x" * 1_048_576,
        b'{"x":' + b"[" * 25 + b"0" + b"]" * 25 + b"}",
    ],
    ids=["duplicate-field", "nan", "infinity", "array", "byte-limit", "depth-limit"],
)
def test_json_limits_and_ambiguous_values_fail_closed(raw):
    with pytest.raises(BenchmarkError):
        bounded_json(raw)


def test_no_real_data_or_unimplemented_adapter_can_enter_the_offline_runner():
    suite, _ = data()
    for field, value in [("data_class", "real_recording"), ("schema_id", "paid")]:
        with pytest.raises(ValidationError):
            Suite.model_validate({**suite.model_dump(), field: value})
    raw = suite.model_dump()
    raw["candidates"][0]["adapter"] = "ollama"
    with pytest.raises(ValidationError):
        Suite.model_validate(raw)
    raw = suite.model_dump()
    raw["candidates"][0]["profile"].update(source_weights=[100], actual_source_total=100)
    with pytest.raises(BenchmarkError, match="profile"):
        selected_cases(Suite.model_validate(raw))


def test_cli_writes_immutable_hashed_receipts_and_returns_nonzero_for_a_failed_case(
    tmp_path, capsys
):
    # The run is external even if pytest has been given an in-repository temp dir.
    if any((p / ".git").exists() for p in tmp_path.parents):
        pytest.skip("Pass an external --basetemp for receipt path validation")
    destination = tmp_path / "receipts"
    args = [
        "--manifest",
        str(FIXTURES / "manifest.json"),
        "--receipt-root",
        str(destination),
        "--run-id",
        str(RUN),
    ]
    assert cli.main(args) == 0
    record = json.loads((destination / str(RUN) / "receipt.json").read_bytes())
    assert record["source_input_files_read"] == 8
    assert record["resource_measurements"]["peak_python_allocated_bytes"] > 0
    assert "model quality" in (destination / str(RUN) / "comparison.md").read_text(encoding="utf-8")
    assert record["receipt_sha256"] == content_hash(
        {k: v for k, v in record.items() if k != "receipt_sha256"}
    )
    original = (destination / str(RUN) / "receipt.json").read_bytes()
    assert cli.main(args) == 2
    assert (destination / str(RUN) / "receipt.json").read_bytes() == original
    assert "Please stop" not in capsys.readouterr().out
    suite, inputs = data()
    suite, inputs = changed_case(
        suite,
        inputs,
        "price-without-context",
        lambda value: value["expected_slots"]["price_objection"].update(value=False),
    )
    raw = suite.model_dump()
    raw["selected_case_ids"] = ["price-without-context"]
    (tmp_path / "manifest.json").write_bytes(canonical(raw))
    (tmp_path / "price-without-context.json").write_bytes(inputs["price-without-context"])
    failed_id = uuid4()
    assert (
        cli.main(
            [
                "--manifest",
                str(tmp_path / "manifest.json"),
                "--receipt-root",
                str(destination),
                "--run-id",
                str(failed_id),
            ]
        )
        == 1
    )
    failed = json.loads((destination / str(failed_id) / "receipt.json").read_bytes())
    assert failed["state"] == "failed"
    assert all(row["failed_checks"] == ["context_slot_mismatch"] for row in failed["rows"])


def test_cli_rejects_holdout_manifest_without_reading_any_case(tmp_path, monkeypatch):
    suite, _ = data()
    raw = suite.model_dump()
    raw["selected_case_ids"] = ["sealed-metadata-only"]
    opened = []

    def reader(path):
        opened.append(path)
        return canonical(raw)

    monkeypatch.setattr(cli, "_regular_read", reader)
    with pytest.raises(BenchmarkError):
        cli.run(tmp_path / "manifest.json", tmp_path / "output", uuid4())
    assert opened == [tmp_path / "manifest.json"]
    assert not (tmp_path / "output").exists()


def test_receipts_cannot_be_written_into_git(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(BenchmarkError, match="outside Git"):
        cli._output_parent(tmp_path / "output")


def test_file_links_are_not_read(tmp_path):
    original = tmp_path / "input.json"
    original.write_text('{"fixture":"test"}', encoding="utf-8")
    link = tmp_path / "indirect.json"
    link.hardlink_to(original)
    with pytest.raises(BenchmarkError):
        cli._regular_read(link)


def test_cli_preserves_an_incomplete_marker_without_exception_contents(tmp_path, monkeypatch):
    if any((p / ".git").exists() for p in tmp_path.parents):
        pytest.skip("Pass an external --basetemp for receipt path validation")

    def broken(*args, **kwargs):
        raise BenchmarkError("sensitive-fixture-marker-must-not-be-written")

    monkeypatch.setattr(cli, "compare", broken)
    assert (
        cli.main(
            [
                "--manifest",
                str(FIXTURES / "manifest.json"),
                "--receipt-root",
                str(tmp_path),
                "--run-id",
                str(RUN),
            ]
        )
        == 2
    )
    folder = tmp_path / str(RUN)
    assert [p.name for p in folder.iterdir()] == ["incomplete.json"]
    assert json.loads((folder / "incomplete.json").read_bytes())["state"] == "incomplete"
    assert b"sensitive" not in (folder / "incomplete.json").read_bytes()


def test_nonregular_input_is_rejected_before_open(tmp_path, monkeypatch):
    def not_opened(*args, **kwargs):
        raise AssertionError("A nonregular input must be rejected before opening")

    monkeypatch.setattr(Path, "open", not_opened)
    with pytest.raises(BenchmarkError):
        cli._regular_read(tmp_path)
