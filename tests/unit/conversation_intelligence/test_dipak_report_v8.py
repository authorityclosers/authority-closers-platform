"""Compact six-pillar C5 candidate, fictional dialogue only, no provider sends."""

import json
from copy import deepcopy

import pytest

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_response_json_schema,
)
from ac_platform.conversation_intelligence.coaching_validation_gate import (
    coaching_revision_runtime_block,
)
from ac_platform.conversation_intelligence.dipak_report import (
    COACHING_PROMPT_V8_INSTRUCTION,
    REPORT_SECTION_FIELDS,
    project_pillars,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_coaching_input,
    validate_coaching_result,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reports import (
    ReportError,
    build_report_groq_prompt,
    parse_fact_packet,
    parse_report_draft,
    plan_transcript_chunks,
)
from tests.unit.conversation_intelligence.test_call_map import _FIXTURE, _segments
from tests.unit.conversation_intelligence.test_coaching_schema import _valid_response
from tests.unit.conversation_intelligence.test_coaching_v7_prompt import validate_schema
from tests.unit.conversation_intelligence.test_gemini_tasks import envelope, result
from tests.unit.conversation_intelligence.test_long_coaching_budget import largest_v7_value
from tests.unit.conversation_intelligence.test_sensitive_segments_store import state as state
from tests.unit.http.test_platform_sensitive_segments import marks_state as marks_state
from tests.unit.http.test_workspaces import workspace_state as workspace_state


def refs(*ids):
    return [{"segment_id": s} for s in ids]


def note(text, *ids):
    return {"text": text, "evidence": refs(*ids)}


@pytest.fixture
def case():
    transcript = {
        "source_sha256": "a" * 64,
        "revision": "fictional-dipak-v8-c2",
        "timebase_id": "1ms",
        "duration_ms": _FIXTURE["duration_ms"],
        "segments": _segments(),
    }
    packets = [
        parse_fact_packet(
            {"overview": "A fictional sales discussion.", "observations": [], "uncertainties": []},
            transcript,
            chunk=chunk,
        )
        for chunk in plan_transcript_chunks(transcript)
    ]
    roles = {
        "origin": "user_confirmed_roles",
        "transcript_revision": transcript["revision"],
        "map_revision": "b" * 64,
        "speakers": [
            {"speaker_id": "speaker_0", "role": "seller", "is_account_holder": True},
            {"speaker_id": "speaker_1", "role": "prospect", "is_account_holder": False},
        ],
    }
    next_step = {**note("Review the sample mapping next Tuesday.", "s8"), "when": "next Tuesday"}
    pillars = {
        "version": "report-pillars/1",
        "outcome": {
            "status": "Follow-up Set",
            "line": "A sample review was agreed for next Tuesday.",
            "evidence": refs("s8"),
        },
        "summary": (
            "The prospect needs clearer owners and next steps. "
            "The price is above the stated budget. "
            "A sample review was agreed for next Tuesday."
        ),
        "biggest_influence": note(
            "The prospect agreed to review a sample despite the budget gap.", "s6", "s8"
        ),
        "strongest_part": {
            **note("You ended with a specific next conversation.", "s8", "s9"),
            "short": "Specific next conversation",
        },
        "biggest_concern": {
            **note("You offered a sample before clarifying the budget concern.", "s6", "s7"),
            "short": "Budget concern left unclear",
        },
        "next_step": deepcopy(next_step),
        "timeline": [
            {
                "label": label,
                "start_ms": transcript["segments"][i]["start_ms"],
                "evidence": refs(transcript["segments"][i]["id"]),
            }
            for i, label in [
                (0, "Opening"),
                (1, "Work context"),
                (4, "Offer discussion"),
                (5, "Price & decision"),
                (7, "Next step"),
            ]
        ],
        "key_change": {
            **note("The conversation moved from the problem to the offer.", "s5"),
            "before": {
                **note("You were understanding what gets missed.", "s3"),
                "label": "Discovery",
            },
            "after": {
                **note("You discussed a sample to address the concern.", "s7"),
                "label": "Sample discussion",
            },
        },
        "worked": [
            {
                "title": "You checked the timing",
                "what": "You checked whether the prospect could talk.",
                "evidence": refs("s1"),
                "why_it_helped": "The prospect could choose whether to continue.",
            }
        ],
        "didnt": [
            {
                "title": "Budget concern left unclear",
                "what": "You offered a sample instead of exploring the budget gap.",
                "evidence": refs("s6", "s7"),
                "what_it_affected": "It left the investment decision unclear.",
                "possible_areas": ["What budget flexibility does the prospect have?"],
            }
        ],
        "moments": [
            {
                "kind": "Important Miss",
                "title": "The budget gap needed more discussion",
                "evidence": refs("s6", "s7"),
                "why": "The sample did not clarify how the investment would be decided.",
                "moved_toward": "You offered to map the columns in a sample.",
                "what_was_missed": "The reason for the budget limit remained unclear.",
                "price_stated": None,
                "prospect_response": None,
            },
            {
                "kind": "Commitment",
                "title": "A review was agreed",
                "evidence": refs("s8"),
                "why": "The call ended with a specific next conversation.",
                "moved_toward": None,
                "what_was_missed": None,
                "price_stated": None,
                "prospect_response": None,
            },
        ],
        "deeper": {
            "became_clear": [note("Owners and next steps are often missed.", "s2")],
            "still_unclear": ["Can the budget change?"],
            "opening_missed": note("The prospect stated a budget gap.", "s6"),
            "relevant": [note("Mapping columns was discussed.", "s7")],
            "less_relevant": None,
            "value_connection": None,
            "price": None,
            "prospect_response": note("The stated price is above the budget.", "s6"),
            "likely_status": [],
            "listening": None,
            "communication_note": None,
        },
        "deal": {
            "position": note("The prospect agreed to review a sample.", "s8"),
            "blocker": {
                **note("The stated price is above the prospect's budget.", "s6"),
                "basis": "said",
            },
            "prospect_commitments": [note("Review the mapping with a colleague.", "s8")],
            "seller_commitments": [note("Send the sample layout.", "s7")],
            "next_event": deepcopy(next_step),
            "commitment_quality": "Clear",
            "still_unclear": ["Does the colleague need to approve the purchase?"],
            "deal_action": "Send the sample before the agreed review.",
            "coaching_mission": "Explore the concern before offering another solution.",
        },
        "most_important_moment": 0,
    }
    dimensions = _valid_response()["dimensions"]
    for d in dimensions:
        d.update(status="observed", call_state="observed", evidence=refs("s1", "s2"))
    payload = {
        "pillars": pillars,
        "dimensions": dimensions,
        "summary_evidence": refs("s2", "s6", "s8"),
        "sensitive_segments": [],
        "review_status": "draft_not_dipak_adjudicated",
    }
    return transcript, packets, roles, payload


def parse(case, payload=None, **options):
    transcript, _, roles, saved = case
    return parse_report_draft(
        saved if payload is None else payload,
        transcript,
        coaching_prompt_revision="coaching-v8",
        speaker_roles=roles,
        **options,
    )


def test_every_spec_section_maps_to_a_field():
    assert {k.split(".")[0] for k in REPORT_SECTION_FIELDS} == {"1", "2", "3", "4", "5", "6"}
    assert {f"6.{n}" for n in range(1, 10)} <= REPORT_SECTION_FIELDS.keys()
    assert "calculation" in REPORT_SECTION_FIELDS["2.1"]


def test_wire_to_canonical_to_public_preserves_all_pillars_and_legacy_content(case):
    transcript, _, _, payload = case
    validate_schema(payload, coaching_response_json_schema("coaching-v8"))
    draft = parse(case)
    assert parse(case, draft.model_dump(mode="json"), canonical_read=True) == draft
    assert draft.summary == payload["pillars"]["summary"]
    assert draft.improvements[0].explanation == payload["pillars"]["didnt"][0]["what"]
    public = project_pillars(draft.pillars)
    assert (
        public["deal"]["prospect_commitments"][0]["evidence"][0]["quote"]
        == transcript["segments"][7]["text"]
    )
    assert public["deeper"]["became_clear"] == ["Owners and next steps are often missed."]
    assert set(public["timeline"][0]) == {"label", "start_ms"}
    assert set(public["key_change"]["before"]) == {"label", "text"}
    assert "pillars" not in draft.provider_extras


def test_account_projection_keeps_native_quotes_and_guest_boundary(case):
    from ac_platform.conversation_intelligence.report_access import ReportAccess, project_report

    draft = parse(case)
    account = project_report(draft, access=ReportAccess.ACCOUNT)
    guest = project_report(draft, access=ReportAccess.GUEST)
    ref = account["content"]["pillars"]["next_step"]["evidence"][0]
    assert set(ref) == {"segment_id", "quote", "start_ms", "end_ms"}
    assert ref["start_ms"] == case[0]["segments"][7]["start_ms"]
    assert "pillars" not in guest["content"]
    assert draft.pillars is not None


def test_privacy_marks_withhold_new_evidence_without_mutating_saved_report(case):
    from ac_platform.conversation_intelligence.report_access import ReportAccess, project_report
    from ac_platform.conversation_intelligence.sensitive_segments import (
        WITHHELD_MARKER,
        WithheldPlan,
        withhold,
    )

    draft = parse(case)
    view = project_report(draft, access=ReportAccess.ACCOUNT)
    private = withhold(view, WithheldPlan(frozenset({"s8"}), frozenset()))
    assert private["content"]["pillars"]["next_step"]["evidence"][0]["quote"] == WITHHELD_MARKER
    assert view["content"]["pillars"]["next_step"]["evidence"][0]["quote"] != WITHHELD_MARKER
    assert draft.pillars.next_step.evidence[0].quote != WITHHELD_MARKER


@pytest.mark.parametrize(
    "provider,model", [("gemini", "gemini-3.8-flash"), ("openai", "gpt-6-luna")]
)
def test_prepared_adapter_selects_compact_schema_and_bound_roles(case, provider, model):
    transcript, packets, roles, _ = case
    before = deepcopy(transcript)
    task = prepare_coaching_input(
        transcript,
        packets,
        provider=provider,
        model=model,
        max_completion_tokens=8000,
        coaching_prompt_revision="coaching-v8",
        speaker_roles=roles,
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v8").sha256,
    )
    assert task.prompt_provenance.prompt_revision == "coaching-v8"
    assert transcript == before
    assert "report-pillars/1" in json.dumps(task.as_provider_body())


def test_actual_c5_response_uses_v8_parser(case):
    transcript, packets, roles, payload = case
    task = prepare_coaching_input(
        transcript,
        packets,
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
        coaching_prompt_revision="coaching-v8",
        speaker_roles=roles,
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v8").sha256,
    )
    output = validate_coaching_result(
        result(task, envelope(payload)),
        task,
        transcript,
        coaching_prompt_revision="coaching-v8",
        speaker_roles=roles,
    ).data()
    assert output["pillars"]["deal"]["commitment_quality"] == "Clear"
    assert output["dimensions"][0]["call_state"] == "observed"


@pytest.mark.parametrize(
    "invalid",
    [
        "seller_as_prospect",
        "prospect_as_seller",
        "missing_pillars",
        "missing_call_state",
        "unsupported_state",
        "duplicate_opening",
        "no_agreement",
        "no_timing",
        "invented_date",
        "foreign_segment",
        "invented_quote",
        "unsupported_miss",
        "invented_phase_time",
        "duplicate_phase",
        "moment_index",
        "won",
    ],
)
def test_unsupported_claims_fail_closed(case, invalid):
    payload = deepcopy(case[3])
    p = payload["pillars"]
    if invalid == "seller_as_prospect":
        p["deal"]["prospect_commitments"][0]["evidence"] = refs("s7")
    elif invalid == "prospect_as_seller":
        p["deal"]["seller_commitments"][0]["evidence"] = refs("s8")
    elif invalid == "missing_pillars":
        payload.pop("pillars")
    elif invalid == "missing_call_state":
        payload["dimensions"][0].pop("call_state")
    elif invalid == "unsupported_state":
        payload["dimensions"][0]["evidence"] = []
    elif invalid == "duplicate_opening":
        p["summary"] = p["outcome"]["line"].upper() + " You explored the problem."
    elif invalid == "no_agreement":
        p["deal"]["next_event"] = None
    elif invalid == "no_timing":
        p["deal"]["next_event"]["when"] = None
    elif invalid == "invented_date":
        p["deal"]["next_event"]["when"] = "Friday at 4 PM"
    elif invalid == "foreign_segment":
        p["next_step"]["evidence"] = refs("foreign")
    elif invalid == "invented_quote":
        p["next_step"]["evidence"] = [{"segment_id": "s8", "quote": "I bought it."}]
    elif invalid == "unsupported_miss":
        p["moments"][0]["evidence"] = refs("s6")
    elif invalid == "invented_phase_time":
        p["timeline"][1]["start_ms"] += 1
    elif invalid == "duplicate_phase":
        p["timeline"][1]["start_ms"] = p["timeline"][0]["start_ms"]
    elif invalid == "moment_index":
        p["most_important_moment"] = 4
    else:
        p["outcome"]["status"] = "Won"
    with pytest.raises(ReportError):
        parse(case, payload)


def test_output_inferred_roles_cannot_establish_commitments(case):
    transcript, _, _, payload = case
    with pytest.raises(ReportError):
        parse_report_draft(payload, transcript, coaching_prompt_revision="coaching-v8")


def test_saved_compatibility_receipt_survives_canonical_read(case):
    payload = deepcopy(case[3])
    payload["sensitive_segments"] = [{"segment_id": "foreign", "category": "SENSITIVE_LEGAL"}]
    draft = parse(case, payload)
    assert draft.provider_extras["compatibility"]["sensitive_segments_dropped"] == 1
    assert parse(case, draft.model_dump(mode="json"), canonical_read=True) == draft


def test_largest_wire_output_fits_existing_completion_envelope():
    schema = coaching_response_json_schema("coaching-v8")
    largest = largest_v7_value(schema)
    validate_schema(largest, schema)
    assert len(canonical(largest)) <= 24000
    assert set(schema["properties"]) == {
        "pillars",
        "dimensions",
        "summary_evidence",
        "sensitive_segments",
        "review_status",
    }
    assert "pillars" not in coaching_response_json_schema("coaching-v7")["properties"]


def test_prompt_is_one_sales_story_not_a_second_copy_of_old_sections(case):
    transcript, packets, roles, _ = case
    prompt = build_report_groq_prompt(
        transcript,
        packets,
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
        coaching_prompt_revision="coaching-v8",
        speaker_roles=roles,
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v8").sha256,
    )
    system = prompt["messages"][0]["content"]
    assert "3-5 short everyday sentences" in system
    assert "Assigned tasks and suggestions are not commitments" in system
    assert "Outcome line and summary have different openings" in system
    assert "V8 WIRE LIMITS" in system and "V7 WIRE LIMITS" not in system
    assert "Required overview shape" not in system


def test_candidate_keeps_existing_sval_gate():
    assert "AC-SVAL-01 Gate 2" in coaching_revision_runtime_block("coaching-v8")


def test_plain_sales_voice_does_not_use_analyst_words_as_advice():
    instruction = COACHING_PROMPT_V8_INSTRUCTION
    assert "VOICE (Dipak's plain sales language)" in instruction
    before, rest = instruction.split("Never use: ", 1)
    banned, after = rest.split(". No praise adjectives", 1)
    for word in banned.split(", "):
        assert word not in before
        assert word not in after
    assert "no confirmed first name is supplied" in instruction
    assert "preserve uncertainty the speaker expressed" in instruction


@pytest.mark.asyncio
async def test_v8_sensitive_marks_append_the_actual_prompt_revision(state):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from ac_platform.audit.models import AuditEvent
    from ac_platform.conversation_intelligence.sensitive_segments_store import (
        SensitiveSegmentsStore,
    )
    from tests.unit.conversation_intelligence.test_sensitive_segments_store import add_c2, principal
    from tests.unit.http.test_workspaces import HttpDatabase

    revision = "fictional-v8-sensitive-r1"
    principal(state)
    add_c2(state, state.recording, revision, {"s4": "A fictional private legal matter."})
    with Session(state.engine) as db, db.begin():
        rows = await SensitiveSegmentsStore(HttpDatabase(db)).mark_generation(
            recording_id=state.recording,
            transcript_revision=revision,
            model_segments=[("s4", "SENSITIVE_LEGAL")],
            model_revision="coaching-v8",
        )
        assert len(rows) == 1
        assert rows[0].reason_ref == "coaching-v8:sensitive_segments"
        assert (
            db.scalars(
                select(AuditEvent).where(AuditEvent.action == "conversation.sensitive_segment.mark")
            ).first()
            is not None
        )


@pytest.mark.asyncio
async def test_finish_persists_native_pillars_and_v8_sensitive_revision(case):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch
    from uuid import uuid4

    from ac_platform.conversation_intelligence.checkpoints import (
        STAGE_PARENTS,
        build_checkpoint,
        content_hash,
    )
    from ac_platform.conversation_intelligence.inference import binding_for
    from ac_platform.conversation_intelligence.models import ConversationReportDraft
    from ac_platform.conversation_intelligence.report_store import ConversationReports
    from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline
    from ac_platform.conversation_intelligence.reports import load_report_profile
    from ac_platform.conversation_intelligence.sensitive_segments_store import (
        SensitiveSegmentsStore,
    )
    from ac_platform.kernel.authz import ActorContext

    # Runtime C2 revisions bind the native provider-response SHA256.
    case[0]["revision"] = "c" * 64
    case[2]["transcript_revision"] = case[0]["revision"]
    case[3]["sensitive_segments"] = [{"segment_id": "s2", "category": "SENSITIVE_LEGAL"}]
    payload = parse(case).model_dump(mode="json")
    recording = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        person_id=uuid4(),
        source_revision=1,
        source_sha256=case[0]["source_sha256"],
    )
    task = SimpleNamespace(quote_id=uuid4())
    run = SimpleNamespace(id=uuid4())
    database = AsyncMock()
    database.add = MagicMock()
    database.scalar.return_value = None
    application = SimpleNamespace(clock=lambda: datetime.now(UTC), _receipt=AsyncMock())
    pipeline = ReportingPipeline(SimpleNamespace(database=database, application=application))
    c2 = SimpleNamespace(id=uuid4(), payload=case[0])
    pipeline.checkpoint = AsyncMock(return_value=(c2, None))
    transcription = SimpleNamespace(run_id=uuid4())
    pipeline.provider_task = AsyncMock(
        return_value=(transcription, {"response_sha256": case[0]["revision"]})
    )
    pipeline.save = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    plan = SimpleNamespace(
        transcript=case[0],
        native_transcript=case[0],
        profile=load_report_profile(),
        request=SimpleNamespace(
            transcript_checkpoint_id=c2.id, coaching_prompt_revision="coaching-v8"
        ),
    )
    nodes = {}
    for stage, parents in STAGE_PARENTS.items():
        nodes[stage] = build_checkpoint(
            binding_for(recording),
            stage,
            "fictional-v8",
            {},
            [nodes[parent] for parent in parents],
            content_hash(payload),
        )
    c5 = nodes["C5"]
    with (
        patch(
            "ac_platform.conversation_intelligence.inference.verified_checkpoint", return_value=c5
        ),
        patch(
            "ac_platform.conversation_intelligence.reporting_pipeline.actor_from_row",
            return_value=ActorContext(uuid4(), uuid4(), recording.tenant_id),
        ),
        patch.object(SensitiveSegmentsStore, "mark_generation", new_callable=AsyncMock) as marks,
    ):
        await pipeline.finish(
            recording,
            task,
            run,
            plan,
            SimpleNamespace(id=uuid4()),
            payload,
            SimpleNamespace(response_sha256="b" * 64),
        )
    marks.assert_awaited_once_with(
        recording_id=recording.id,
        transcript_revision=case[0]["revision"],
        model_segments=(("s2", "SENSITIVE_LEGAL"),),
        model_revision="coaching-v8",
    )
    draft = database.add.call_args.args[0]
    assert isinstance(draft, ConversationReportDraft)
    report, _ = ConversationReports._validated(draft, recording)
    assert report.model_dump(mode="json") == payload
    application._receipt.assert_awaited_once()
