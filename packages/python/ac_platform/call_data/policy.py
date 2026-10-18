"""What the fast pipeline does with each new object: fill, ask or just keep.

Pure. The owner's rule (19 Oct): high-confidence, repeated facts fill the lead
automatically; complex or uncertain ones are asked one at a time. A value a
person typed into the lead is never overwritten without asking.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ac_platform.call_data import taxonomy
from ac_platform.call_data.extraction import Draft

MAX_QUESTIONS = 7


@dataclass(frozen=True, slots=True)
class Plan:
    index: int  # position in the drafts list
    action: str  # auto_fill | ask | keep
    question: str | None = None  # fill | replace | confirm (for ask)
    lead_field: str | None = None  # the lead column this writes, when it does
    lead_value: str | None = None  # the text written to that column


def _same(a: str | None, b: str | None) -> bool:
    return " ".join((a or "").casefold().split()) == " ".join((b or "").casefold().split())


def auto_fill_allowed(draft: Draft) -> bool:
    kind_type = taxonomy.TYPES[draft.type_key]
    rule = kind_type.auto_fill
    if rule is None or draft.basis != "observed" or not draft.evidence:
        return False
    if draft.confidence < rule.min_confidence:
        return False
    return draft.mentions >= (1 if rule.simple else rule.min_mentions)


def lead_text(draft: Draft) -> str:
    """The plain text a lead column receives."""
    return draft.display


def plan(
    drafts: Sequence[Draft],
    *,
    lead: Mapping[str, str | None] | None,
    auto_filled: Mapping[str, str],
    rejected: frozenset[tuple[str, str]] = frozenset(),
) -> list[Plan]:
    """One plan per draft.

    ``lead`` is the linked lead's current columns (None when the call has no
    lead); ``auto_filled`` maps a column to the value the engine itself last
    wrote there (so a later call may correct its own guess, never a person's);
    ``rejected`` holds (type, display) pairs a person already rejected on this
    lead, which are never asked again.
    """
    plans: list[Plan] = []
    used_fields: set[str] = set()
    for index, draft in enumerate(drafts):
        kind_type = taxonomy.TYPES[draft.type_key]
        if (draft.type_key, " ".join(draft.display.casefold().split())) in rejected:
            plans.append(Plan(index, "keep"))
            continue
        column = kind_type.lead_field if lead is not None else None
        if column is not None and column not in used_fields:
            used_fields.add(column)
            current = lead.get(column) if lead is not None else None
            value = lead_text(draft)
            if current and _same(current, value):
                plans.append(Plan(index, "keep"))
            elif not current or (column in auto_filled and _same(current, auto_filled[column])):
                if auto_fill_allowed(draft):
                    plans.append(Plan(index, "auto_fill", lead_field=column, lead_value=value))
                else:
                    plans.append(Plan(index, "ask", "fill", column, value))
            else:
                plans.append(Plan(index, "ask", "replace", column, value))
            continue
        if auto_fill_allowed(draft):
            plans.append(Plan(index, "auto_fill"))
        elif kind_type.ask and not kind_type.ai_read:
            plans.append(Plan(index, "ask", "confirm"))
        else:
            plans.append(Plan(index, "keep"))
    return _cap_questions(plans, drafts)


def _cap_questions(plans: list[Plan], drafts: Sequence[Draft]) -> list[Plan]:
    asks = sorted(
        (p for p in plans if p.action == "ask"),
        key=lambda p: (
            taxonomy.TYPES[drafts[p.index].type_key].priority,
            -drafts[p.index].confidence,
        ),
    )
    keep = {p.index for p in asks[:MAX_QUESTIONS]}
    return [p if p.action != "ask" or p.index in keep else Plan(p.index, "keep") for p in plans]
