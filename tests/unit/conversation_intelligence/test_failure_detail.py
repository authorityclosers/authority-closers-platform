"""The job failure detail names the stage, code, rule and field paths, never the content."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from ac_platform.conversation_intelligence import failure_detail as module
from ac_platform.conversation_intelligence import inference_tasks, reports
from ac_platform.conversation_intelligence.failure_detail import (
    FAILURE_DETAIL_MAX_BYTES,
    FAILURE_DETAIL_SCHEMA,
    REDACTED,
    build_failure_detail,
    canonical_failure_detail,
    minimal_failure_detail,
)
from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
from ac_platform.conversation_intelligence.inference_worker import provider_failure_code
from ac_platform.conversation_intelligence.reports import REPORT_VALIDATOR_REVISION, ReportError

SENTINEL = "sentinel_9f3c_private_words"
SITE = re.compile(r"^[A-Za-z0-9_.]+\.py:\d+:[A-Za-z0-9_<>]+$")
CATCH_ALL = "conversation_provider_result_validation_failed"


def _transcript(text: str = "The buyer asked about price.") -> dict[str, Any]:
    return {
        "source_sha256": "a" * 64,
        "revision": "scribe-r1",
        "timebase_id": "scribe-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {"id": "s1", "speaker_id": "speaker_1", "start_ms": 0, "end_ms": 900, "text": text}
        ],
    }


def _task_error(raise_report_error: Any) -> InferenceTaskError:
    """Re-raise the way the task layer does: ``from None`` on top of the report error."""

    try:
        try:
            raise_report_error()
        except ReportError as exc:
            raise InferenceTaskError(str(exc)) from None
    except InferenceTaskError as error:
        return error
    raise AssertionError("expected a task error")


def _c5_strict_failure(transcript: dict[str, Any]) -> InferenceTaskError:
    payload: dict[str, Any] = {field: [] for field in reports._CONTENT_FIELDS}
    payload["summary"] = [SENTINEL]
    return _task_error(lambda: reports.parse_report_draft(payload, transcript))


def test_c5_strict_model_failure_stores_stage_code_site_and_field_errors() -> None:
    error = _c5_strict_failure(_transcript())
    failure_code = provider_failure_code(error)
    assert failure_code == "conversation_report_payload_invalid"

    detail = build_failure_detail(error, stage="C5", failure_code=failure_code)

    assert detail["schema"] == FAILURE_DETAIL_SCHEMA
    assert detail["stage"] == "C5"
    assert detail["failure_code"] == failure_code
    assert detail["code"] == "report_payload_invalid"
    assert detail["validator_revision"] == REPORT_VALIDATOR_REVISION
    assert SITE.match(detail["site"]) and detail["site"].startswith("reports.py:")
    assert detail["site"].endswith(":parse_report_draft")
    assert {"loc": "summary", "type": "string_type"} in detail["errors"]
    assert all(set(item) == {"loc", "type"} for item in detail["errors"])


def test_catch_all_failure_code_keeps_the_inner_code() -> None:
    payload: dict[str, Any] = {field: [] for field in reports._CONTENT_FIELDS}
    payload["review_status"] = SENTINEL
    error = _task_error(lambda: reports.parse_report_draft(payload, _transcript()))
    failure_code = provider_failure_code(error)
    assert failure_code == CATCH_ALL

    detail = build_failure_detail(error, stage="C5", failure_code=failure_code)

    assert detail["failure_code"] == CATCH_ALL
    assert detail["code"] == "report_review_status_invalid"
    assert SENTINEL not in canonical_failure_detail(detail)
    assert detail["site"].endswith(":parse_report_draft")


def test_sentinel_in_response_transcript_and_message_never_appears() -> None:
    transcript = _transcript(f"Private {SENTINEL} words.")
    inner = _c5_strict_failure(transcript)
    try:
        raise RuntimeError(f"provider said {SENTINEL}") from inner
    except RuntimeError as wrapped:
        error: BaseException = wrapped

    detail = build_failure_detail(error, stage="C5", failure_code=CATCH_ALL)

    text = canonical_failure_detail(detail)
    assert SENTINEL not in text
    assert "Private" not in text and "provider said" not in text
    assert detail["code"] == "report_payload_invalid"
    assert detail["errors"]


@pytest.mark.parametrize(
    "code",
    ["report_evidence_invalid: private words", "x" * 61, "Mixed_Case", "", "sk-abc"],
)
def test_non_identifier_or_over_long_code_is_redacted(code: str) -> None:
    detail = build_failure_detail(InferenceTaskError(code), stage="C4", failure_code=CATCH_ALL)
    assert detail["code"] == REDACTED
    assert code not in canonical_failure_detail(detail) or code == ""


def test_two_kib_cap_holds_by_dropping_errors_then_site(monkeypatch: pytest.MonkeyPatch) -> None:
    original = module._describe
    long_loc = ".".join(f"k{index}" for index in range(120))

    def describe(*args: Any, **kwargs: Any) -> dict[str, Any]:
        detail = original(*args, **kwargs)
        detail["errors"] = [{"loc": long_loc, "type": "extra_forbidden"}] * 10
        return detail

    monkeypatch.setattr(module, "_describe", describe)
    detail = build_failure_detail(
        InferenceTaskError("report_payload_invalid"), stage="C5", failure_code=CATCH_ALL
    )

    assert len(canonical_failure_detail(detail).encode("ascii")) <= FAILURE_DETAIL_MAX_BYTES
    assert detail["schema"] == FAILURE_DETAIL_SCHEMA
    assert detail["failure_code"] == CATCH_ALL
    assert detail["code"] == "report_payload_invalid"
    assert 0 < len(detail["errors"]) < 10


def test_over_long_failure_code_alone_is_redacted_under_the_cap() -> None:
    detail = build_failure_detail(None, stage=None, failure_code="f" * 3_000)
    assert detail == minimal_failure_detail(REDACTED)
    assert len(canonical_failure_detail(detail)) <= FAILURE_DETAIL_MAX_BYTES


@pytest.mark.parametrize(
    ("stage", "revision"),
    [("C2", None), ("C4", REPORT_VALIDATOR_REVISION), ("C5", REPORT_VALIDATOR_REVISION)],
)
def test_each_stage_is_stored_with_its_validator_revision(stage: str, revision: str | None) -> None:
    error = _task_error(
        lambda: reports.parse_fact_packet(
            json.dumps(
                {"overview": "x", "observations": [], "uncertainties": [], "unexpected": SENTINEL}
            ),
            _transcript(),
        )
    )
    detail = build_failure_detail(error, stage=stage, failure_code=provider_failure_code(error))
    assert detail["stage"] == stage
    assert detail["validator_revision"] == revision
    assert detail["code"] == "fact_packet_invalid"
    assert detail["errors"] == [{"loc": "<key>", "type": "extra_forbidden"}]
    assert SENTINEL not in canonical_failure_detail(detail)


def test_unknown_stage_and_missing_error_store_nulls() -> None:
    detail = build_failure_detail(None, stage="C9", failure_code=CATCH_ALL)
    assert detail == {
        "schema": FAILURE_DETAIL_SCHEMA,
        "stage": None,
        "failure_code": CATCH_ALL,
        "code": None,
        "validator_revision": None,
        "site": None,
        "errors": [],
    }


def test_builder_failure_falls_back_to_the_minimal_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(SENTINEL)

    monkeypatch.setattr(module, "_describe", explode)
    detail = build_failure_detail(InferenceTaskError("x"), stage="C5", failure_code=CATCH_ALL)
    assert detail == {"schema": FAILURE_DETAIL_SCHEMA, "failure_code": CATCH_ALL}


def test_site_names_the_rule_not_the_raise_helper() -> None:
    try:
        inference_tasks._text(123, "field_name")
    except InferenceTaskError as error:
        detail = build_failure_detail(error, stage="C4", failure_code=CATCH_ALL)
    assert detail["code"] == "invalid_field_name"
    assert detail["site"].startswith("inference_tasks.py:")
    assert detail["site"].endswith(":_text")


def test_loc_keeps_schema_keys_and_indices_only() -> None:
    assert module._loc(("strengths", 0, "evidence", 3, "quote")) == "strengths.0.evidence.3.quote"
    assert module._loc(("bad key!", True, "x" * 41)) == "<key>.<key>.<key>"
    assert module._loc("not-a-tuple") == "<key>"


def test_an_unknown_provider_key_is_redacted_even_when_it_looks_like_an_identifier() -> None:
    # CTO repro on AUT-484: an identifier-shaped extra key must not be stored.
    error = _task_error(
        lambda: reports.parse_fact_packet(
            json.dumps(
                {
                    "overview": "fictional overview",
                    "observations": [],
                    "uncertainties": [],
                    SENTINEL: "fictional value",
                }
            ),
            _transcript(),
        )
    )
    detail = build_failure_detail(error, stage="C4", failure_code=provider_failure_code(error))
    assert detail["errors"] == [{"loc": "<key>", "type": "extra_forbidden"}]
    assert SENTINEL not in canonical_failure_detail(detail)


@pytest.mark.parametrize("key", [SENTINEL, "Ravi_Kumar", "cust_000123", "summary"])
def test_extra_forbidden_never_keeps_the_extra_key(key: str) -> None:
    # Even a key that is also a schema field elsewhere is the provider's own key here.
    assert module._loc(("strengths", 0, key), "extra_forbidden") == "strengths.0.<key>"


@pytest.mark.parametrize("key", [SENTINEL, "Ravi_Kumar", "cust_000123"])
def test_mapping_or_unknown_keys_are_redacted_and_schema_paths_kept(key: str) -> None:
    assert module._loc(("strengths", key, 2, "quote"), "string_type") == "strengths.<key>.2.quote"
