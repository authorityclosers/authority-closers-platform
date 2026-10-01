"""The job failure detail names the stage, code, rule and field paths, never the content."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, RootModel, TypeAdapter, ValidationError

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
    draft = reports.ReportDraft
    assert module._loc(("strengths", 0, "evidence", 3, "quote"), "string_type", draft) == (
        "strengths.0.evidence.3.quote"
    )
    assert module._loc(("bad key!", True, "x" * 41), "string_type", draft) == "<key>.<key>.<key>"
    assert module._loc("not-a-tuple", "string_type", draft) == "<key>"


def test_unknown_schema_fails_closed_including_indices() -> None:
    # Without a supported schema an integer may be a mapping key as easily as an index.
    assert module._loc(("strengths", 0, "quote"), "string_type", None) == "<key>.<key>.<key>"
    assert module._loc((1, "a"), "int_type", None) == "<key>.<key>"


def test_the_report_models_are_the_supported_roots() -> None:
    roots = module._supported_roots()
    assert set(roots) == {
        "FactPacket",
        "AggregateFactPacket",
        "ReportDraft",
        "ReportCitation",
        "DetailedOverview",
    }


# Fictional fixtures. They are not supported roots, so the stored detail for
# their errors is fully redacted; the walker itself is checked with _loc.


class _ReviewValue(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    quote: int


class _ProviderExtras(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider_extras: dict[str, int]
    findings: list[dict[str, int]] = []


class _IntegerKeys(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    counts: dict[int, int]


class _UnrelatedFixture(BaseModel):
    sentinel_9f3c_private_words: str = ""


class _ReviewIntUnion(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    findings: dict[int, _ReviewValue] | list[int]


class _ReviewStrUnion(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    findings: dict[str, _ReviewValue] | list[int]


class _ReviewTuple(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    findings: tuple[int, dict[int, _ReviewValue]]


class _ReviewModelTuple(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    findings: tuple[_ReviewValue, dict[str, _ReviewValue]]


class _ReviewMapBranch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: Literal["_ReviewListBranch"]
    findings: dict[int, _ReviewValue]


class _ReviewListBranch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: Literal["_ReviewMapBranch"]
    findings: list[int]


class _ReviewTaggedUnion(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    result: Annotated[_ReviewMapBranch | _ReviewListBranch, Field(discriminator="kind")]


class _ReviewAliasCollision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    findings: list[int] = Field(alias="sequence", default=[])
    provider_extras: dict[int, int] = Field(alias="findings")


class _ReviewNestedMap(RootModel[dict[str, int]]):
    model_config = ConfigDict(strict=True)


class _ReviewNestedRoot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    findings: _ReviewNestedMap


class _AdapterTitleCollision(BaseModel):
    model_config = ConfigDict(title="dict[str,dict[int,int]]", strict=True)
    findings: list[int] = []


class _ShadowReportDraft:
    """A stand-in class answering to ReportDraft's title. Not a pydantic model, so it is
    never in the real loaded-model scan; one test injects it."""

    model_config = {"title": "ReportDraft"}


def _stored_and_walked(
    error: ValidationError, model: type[BaseModel]
) -> tuple[list[str], list[str]]:
    detail = build_failure_detail(error, stage="C5", failure_code=CATCH_ALL)
    text = canonical_failure_detail(detail)
    assert "123456789" not in text
    assert SENTINEL not in text
    stored = [entry["loc"] for entry in detail["errors"]]
    walked = [
        module._loc(entry["loc"], entry["type"], model)
        for entry in error.errors(include_url=False, include_context=False, include_input=False)
    ]
    for loc in walked:
        assert "123456789" not in loc
        assert SENTINEL not in loc
    return stored, walked


def _locs(model: type[BaseModel], value: Any) -> list[str]:
    """Walked locations for a fixture; its stored detail must be fully redacted."""

    with pytest.raises(ValidationError) as caught:
        model.model_validate(value)
    stored, walked = _stored_and_walked(caught.value, model)
    assert stored and all(set(loc.split(".")) == {"<key>"} for loc in stored)
    return walked


@pytest.mark.parametrize("key", ["summary", "quote", SENTINEL, "provider_extras"])
def test_mapping_keys_are_redacted_even_when_another_model_declares_the_word(key: str) -> None:
    assert _UnrelatedFixture.model_fields  # the sentinel is a declared field name somewhere
    locs = _locs(_ProviderExtras, {"provider_extras": {key: "fictional noninteger"}})
    assert locs == ["provider_extras.<key>"]


def test_integer_mapping_keys_are_redacted_in_str_keyed_mappings() -> None:
    locs = _locs(_ProviderExtras, {"provider_extras": {123456789: "fictional noninteger"}})
    assert set(locs) <= {"provider_extras.<key>", "provider_extras.<key>.<key>"}


def test_integer_mapping_keys_are_redacted_in_int_keyed_mappings() -> None:
    assert _locs(_IntegerKeys, {"counts": {123456789: "fictional noninteger"}}) == ["counts.<key>"]


def test_nested_mapping_keys_under_a_list_are_redacted_and_indices_kept() -> None:
    locs = _locs(
        _ProviderExtras, {"provider_extras": {}, "findings": [{"summary": 1}, {SENTINEL: "x"}]}
    )
    assert locs == ["findings.1.<key>"]


def test_union_branch_label_does_not_consume_a_mapping_key() -> None:
    value = {"findings": {123456789: {"quote": "fictional noninteger"}}}
    assert "findings.<key>.<key>.quote" in _locs(_ReviewIntUnion, value)
    value = {"findings": {"quote": {"quote": "fictional noninteger"}}}
    assert "findings.<key>.<key>.quote" in _locs(_ReviewStrUnion, value)
    value = {"findings": {SENTINEL: {"quote": "x"}}}
    assert "findings.<key>.<key>.quote" in _locs(_ReviewStrUnion, value)


def test_an_unresolved_union_branch_hides_everything_below_it() -> None:
    assert module._step(dict[str, int] | list[int], "custom-label")[1] is module._OPAQUE


def test_fixed_tuple_items_use_the_schema_at_their_own_index() -> None:
    value = {"findings": (1, {123456789: {"quote": "fictional noninteger"}})}
    assert "findings.1.<key>.quote" in _locs(_ReviewTuple, value)
    value = {"findings": ({"quote": 1}, {"quote": {"quote": "fictional noninteger"}})}
    assert "findings.1.<key>.quote" in _locs(_ReviewModelTuple, value)


def test_variadic_tuples_and_out_of_range_indices() -> None:
    assert module._step(tuple[_ReviewValue, ...], 5) == ("5", _ReviewValue)
    assert module._step(tuple[int, str], 2) == ("<key>", module._OPAQUE)
    assert module._step(list[int], "word") == ("<key>", module._OPAQUE)
    assert module._step(int, 0) == ("<key>", module._OPAQUE)


def test_a_tagged_union_label_never_selects_a_member_by_class_name() -> None:
    value = {
        "kind": "_ReviewListBranch",
        "findings": {123456789: {"quote": "fictional noninteger"}},
    }
    locs = _locs(_ReviewTaggedUnion, {"result": value})
    assert locs and all(loc.startswith("result.<key>") and "quote" not in loc for loc in locs)


def test_a_field_name_that_is_another_fields_alias_is_ambiguous() -> None:
    # CTO review of 8b48f8e0: ("findings", 123456789) matched the list field's name.
    locs = _locs(
        _ReviewAliasCollision, {"sequence": [1], "findings": {123456789: "fictional noninteger"}}
    )
    assert locs == ["<key>.<key>"]


def test_a_nested_root_model_is_opaque() -> None:
    locs = _locs(_ReviewNestedRoot, {"findings": {"root": "fictional noninteger"}})
    assert locs and all("root" not in loc for loc in locs)


def test_type_adapters_root_models_and_title_collisions_keep_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _AdapterTitleCollision.model_fields
    with pytest.raises(ValidationError) as caught:
        TypeAdapter(dict[str, dict[int, int]]).validate_python(
            {"findings": {123456789: "fictional noninteger"}}, strict=True
        )
    # A loaded model shares the adapter's title; the adapter root still keeps nothing.
    detail = build_failure_detail(caught.value, stage="C5", failure_code=CATCH_ALL)
    assert "123456789" not in canonical_failure_detail(detail)
    assert detail["errors"] and all(
        set(entry["loc"].split(".")) == {"<key>"} for entry in detail["errors"]
    )

    # A second class answering to a supported root's title makes that title ambiguous.
    loaded = module._models()
    monkeypatch.setattr(module, "_models", lambda: [*loaded, _ShadowReportDraft])
    error = _task_error(lambda: _raise_report_draft_error())
    detail = build_failure_detail(error, stage="C5", failure_code=CATCH_ALL)
    assert detail["errors"] and all(
        set(entry["loc"].split(".")) == {"<key>"} for entry in detail["errors"]
    )


def _raise_report_draft_error() -> None:
    payload: dict[str, Any] = {field: [] for field in reports._CONTENT_FIELDS}
    payload["summary"] = [SENTINEL]
    reports.parse_report_draft(payload, _transcript())


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
    loc = module._loc(("strengths", 0, key), "extra_forbidden", reports.ReportDraft)
    assert loc == "strengths.0.<key>"


@pytest.mark.parametrize("key", [SENTINEL, "Ravi_Kumar", "cust_000123"])
def test_unknown_keys_are_redacted_and_the_rest_of_the_path_fails_closed(key: str) -> None:
    # An undeclared part inside a known schema hides everything after it.
    loc = module._loc(("strengths", key, 2, "quote"), "string_type", reports.ReportDraft)
    assert loc == "strengths.<key>.<key>.<key>"
