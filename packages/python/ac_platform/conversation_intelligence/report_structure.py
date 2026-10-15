"""Read-only mapping of saved qualitative analysis to the owner's 27-pointer Report.

No new assessment, numeric score, provider extraction or official deal inference.
Callers authorize and privacy-project all inputs before publishing the result.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from ac_platform.conversation_intelligence.call_metrics import (
    CALL_METRICS_RULES,
    TranscriptSegment,
    compute_call_metrics,
)
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER

# Owner's final list, 16 October 04:00 IST. Related dimensions are context only.
POINTERS = (
    ("call_opening_first_impression", "Call Opening & First Impression", "human_connection_trust"),
    ("purpose_agenda_setting", "Purpose & Agenda Setting", ""),
    ("tone_energy", "Tone and Energy", "communication_tonality"),
    ("active_listening", "Active Listening", "discovery_deep_understanding"),
    ("open_ended_questions", "Asking Open-Ended Questions", "discovery_deep_understanding"),
    ("enough_questions", "Asking Enough Questions", "discovery_deep_understanding"),
    ("prospect_role", "Understanding the Prospect's Role", "qualification"),
    ("needs_challenges", "Identifying Needs and Challenges", "discovery_deep_understanding"),
    ("current_solution", "Exploring Current Solution", "discovery_deep_understanding"),
    ("business_impact", "Quantifying Business Impact", "problem_impact_desire"),
    ("decision_process", "Understanding Decision Process", "qualification"),
    ("stakeholders", "Identifying Stakeholders", "qualification"),
    ("handling_objections", "Handling Objections", "certainty_objection_intelligence"),
    ("solution_value", "Positioning Solution Value", "solution_relevance_presentation"),
    ("discussing_pricing", "Discussing Pricing", ""),
    ("handling_competition", "Handling Competition", "certainty_objection_intelligence"),
    ("checking_concerns", "Checking for Concerns", "certainty_objection_intelligence"),
    ("next_steps", "Next Steps", "closing_decision_management"),
    ("call_control", "Call Control", "communication_tonality"),
    ("question_talk_ratio", "Question to Talk Ratio", ""),
    ("handling_silence", "Handling Silence", ""),
    ("professionalism", "Professionalism", "communication_tonality"),
    ("closing_attitude", "Closing Attitude", "closing_decision_management"),
    ("building_rapport", "Building Rapport", "human_connection_trust"),
    ("presenting_solution", "Presenting the Solution", "solution_relevance_presentation"),
    ("creating_value", "Creating Value", "problem_impact_desire"),
    ("overall_communication", "Overall Communication", "communication_tonality"),
)


def _note(value: Any, source: str) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value.get("evidence"):
        return None
    text = value.get("text", value.get("explanation", value.get("what")))
    if not isinstance(text, str) or not text.strip():
        return None
    return {"text": text, "evidence": deepcopy(value["evidence"]), "source": source}


def unavailable_statistics() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "duration_ms": None,
        "talk_share_percent": {"rep": None, "prospect": None},
        "questions_asked": {"rep": None, "prospect": None},
        "longest_turn": None,
        "longest_rep_turn": None,
        "speakers": [],
        "rules": CALL_METRICS_RULES,
        "question_count_method": "transcript_question_marks",
        "role_status": "unavailable",
    }


def project_report_structure(report: ReportDraft) -> dict[str, Any]:
    """Use canonical evidence before the legacy pillars projection drops some refs."""
    raw = report.model_dump(mode="json")
    pillars = raw.get("pillars") or {}
    content = raw.get("report_content") or {}
    deeper = pillars.get("deeper") or {}
    overview = raw.get("overview") or {}
    dimensions = {item["dimension_id"]: item for item in raw["dimensions"]}
    direct = {
        "purpose_agenda_setting": (content.get("purpose"), "report_content.purpose"),
        "active_listening": (deeper.get("listening"), "pillars.deeper.listening"),
        "discussing_pricing": (deeper.get("price"), "pillars.deeper.price"),
        "next_steps": (
            pillars.get("next_step") or content.get("next_step"),
            "pillars.next_step" if pillars.get("next_step") else "report_content.next_step",
        ),
        "overall_communication": (
            deeper.get("communication_note"),
            "pillars.deeper.communication_note",
        ),
    }
    connection = deeper.get("value_connection")
    if connection:
        direct["solution_value"] = (
            {"text": connection["state"], "evidence": connection["evidence"]},
            "pillars.deeper.value_connection",
        )
    pointers = []
    for number, (pointer_id, label, dimension_id) in enumerate(POINTERS, 1):
        value, source = direct.get(pointer_id, (None, ""))
        observation = _note(value, source)
        observations = [observation] if observation else []
        why = None
        improve = None
        for collection in ("strengths", "improvements", "objection_analysis", "closing_analysis"):
            for index, finding in enumerate(raw[collection]):
                # No fuzzy/keyword classification of a model's free-form titles.
                exact = finding["title"].strip().casefold() == label.casefold()
                if exact:
                    item = _note(finding, f"{collection}[{index}]")
                    if item:
                        observations.append(item)
                    if exact:
                        detail_key = (
                            "strength_details"
                            if collection == "strengths"
                            else "improvement_details"
                        )
                        detail = (
                            next(
                                (
                                    d
                                    for d in overview.get(detail_key, [])
                                    if d["finding_index"] == index
                                ),
                                None,
                            )
                            if collection in {"strengths", "improvements"}
                            else None
                        )
                        if detail:
                            why = detail["why_it_matters"]
                            if collection == "improvements":
                                improve = detail["replacement_behavior"]
        related = [deepcopy(dimensions[dimension_id])] if dimension_id in dimensions else []
        if pointer_id == "creating_value" and "solution_relevance_presentation" in dimensions:
            related.append(deepcopy(dimensions["solution_relevance_presentation"]))
        related_findings = [
            note
            for collection in (
                ["objection_analysis"]
                if pointer_id == "handling_objections"
                else ["closing_analysis"]
                if pointer_id == "closing_attitude"
                else []
            )
            for index, finding in enumerate(raw[collection])
            if (note := _note(finding, f"{collection}[{index}]")) is not None
        ]
        pointers.append(
            {
                "id": pointer_id,
                "number": number,
                "label": label,
                "status": "insufficient_evidence",
                "status_reason": "No separate assessment for this pointer is saved.",
                "score": None,
                "score_status": "not_scored",
                "rating": None,
                "coverage": "existing_observation"
                if observations
                else "related_analysis"
                if related
                else "unavailable",
                "what_happened": observations[0]["text"] if observations else None,
                "why_it_matters": why,
                "evidence": deepcopy(observations[0]["evidence"]) if observations else [],
                "how_to_improve": improve,
                "training_video": None,
                "observations": observations,
                "related_dimensions": related,
                "related_findings": related_findings,
            }
        )

    def highlight(pillar: str, canonical: str, fallback: str) -> dict[str, Any] | None:
        return (
            _note(pillars.get(pillar), f"pillars.{pillar}")
            or _note(content.get(canonical), f"report_content.{canonical}")
            or next(
                (_note(value, f"{fallback}[{i}]") for i, value in enumerate(raw[fallback])), None
            )
        )

    return {
        "version": "report-structure/1",
        "overview": {
            "summary": report.summary,
            "evidence": deepcopy(raw.get("summary_evidence") or []),
            "score": None,
            "score_status": "not_scored",
            "biggest_strength": highlight("strongest_part", "strongest", "strengths"),
            "biggest_improvement": highlight("biggest_concern", "concern", "improvements"),
            "call_statistics": unavailable_statistics(),
        },
        "pointers": pointers,
        "final_call_outcome": project_final_outcome(None),
    }


def project_final_outcome(record: dict[str, Any] | None) -> dict[str, Any]:
    """Only a current authorized person-entered record can set an official outcome."""
    labels = {
        "won": "Won",
        "lost": "Lost",
        "follow_up": "Follow-up Set",
        "no_decision": "Decision Pending",
    }
    value: dict[str, Any] = (record.get("value") or {}) if record else {}
    recorded = bool(
        record and record.get("basis") == "person" and value and value.get("outcome") in labels
    )
    return {
        "status": "recorded" if recorded else "unrecorded" if record is not None else "unavailable",
        "outcome": labels[value["outcome"]] if recorded else None,
        "basis": "person" if recorded else None,
        "deal_value": deepcopy(value.get("deal_value")) if recorded else None,
        "revision": record.get("revision", 0) if record else 0,
        "follow_up_on": value.get("follow_up_on") if recorded else None,
        "lost_reason": value.get("lost_reason") if recorded else None,
    }


def report_statistics(
    transcript: dict[str, Any], speaker_map: dict[str, Any] | None
) -> dict[str, Any]:
    """Existing transcript measurements; roles and judgments are never guessed here."""
    segments = cast(list[TranscriptSegment], transcript["segments"])
    metrics = compute_call_metrics(segments, transcript["duration_ms"])
    roles = (
        {row["speaker_id"]: row for row in (speaker_map or {}).get("speakers", [])}
        if speaker_map and speaker_map.get("transcript_revision") == transcript["revision"]
        else {}
    )
    redacted = {row["speaker_id"] for row in segments if WITHHELD_MARKER in row["text"]}
    speakers = []
    for speaker_id, measured in metrics["speakers"].items():
        role = roles.get(speaker_id, {}).get("role")
        speakers.append(
            {
                "speaker_id": speaker_id,
                "role": "rep" if role in {"you", "salesperson"} else role,
                "role_source": roles.get(speaker_id, {}).get("role_source"),
                "talk_ms": measured["talk_ms"],
                "talk_share_percent": None
                if measured["talk_share"] is None
                else round(measured["talk_share"] * 100, 2),
                "questions": None if speaker_id in redacted else measured["questions"],
                "longest_turn_ms": measured["longest_monologue_ms"],
            }
        )
    grouped = {
        role: [row for row in speakers if row["role"] == role] for role in ("rep", "prospect")
    }
    complete = bool(
        grouped["rep"]
        and grouped["prospect"]
        and all(row["role"] in {"rep", "prospect", "other"} for row in speakers)
    )
    # Unattributed speech means role totals would claim more certainty than C2.
    complete = complete and all(row["speaker_id"] is not None for row in segments)

    def longest(rep_only: bool = False) -> dict[str, Any] | None:
        runs = [
            run
            for run in metrics["monologues"]
            if not rep_only or any(row["speaker_id"] == run["speaker_id"] for row in grouped["rep"])
        ]
        run = max(runs, key=lambda r: r["end_ms"] - r["start_ms"], default=None)
        if rep_only:
            # The existing detector publishes only the top three call-wide runs.
            # Its per-speaker maximum remains complete even if all three are
            # prospect turns. Keep that duration without inventing seek bounds.
            speaker = max(grouped["rep"], key=lambda row: row["longest_turn_ms"], default=None)
            if speaker and (
                run is None or speaker["longest_turn_ms"] > run["end_ms"] - run["start_ms"]
            ):
                return {
                    "speaker_id": speaker["speaker_id"],
                    "duration_ms": speaker["longest_turn_ms"],
                    "start_ms": None,
                    "end_ms": None,
                }
        return {**run, "duration_ms": run["end_ms"] - run["start_ms"]} if run else None

    return {
        **unavailable_statistics(),
        "status": "available",
        "duration_ms": transcript["duration_ms"],
        "talk_share_percent": {
            role: round(sum(row["talk_share_percent"] for row in rows), 2)
            if complete and all(row["talk_share_percent"] is not None for row in rows)
            else None
            for role, rows in grouped.items()
        },
        "questions_asked": {
            role: sum(row["questions"] for row in rows)
            if complete and all(row["questions"] is not None for row in rows)
            else None
            for role, rows in grouped.items()
        },
        "longest_turn": longest(),
        "longest_rep_turn": longest(True) if complete else None,
        "speakers": speakers,
        "role_status": speaker_map.get("status", "unavailable")
        if roles and speaker_map
        else "unavailable",
    }
