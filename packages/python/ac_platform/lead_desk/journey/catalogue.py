"""Stages a business already uses elsewhere, offered as lead stages.

An app the organisation connected (Pulse first) sends the steps of its workflows
(``PUT /v1/api/lead-journey/catalogue``). They are kept as a list to choose from,
never applied by themselves: the Lead stages page shows "From your Pulse workflows:
Site visit, Quotation…" and a manager adds one with a tap. A stage added this way
remembers the step it came from, so a rename there can be offered here.

Names only: no people, customers or amounts. Kept in the organisation's Lead Desk
settings under ``journey_catalogue``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from ac_platform.lead_desk.journey.model import Journey
from ac_platform.lead_desk.journey.templates import (
    KIND_WORDS,
    MILESTONE_KIND,
    MILESTONE_WORDS,
    guess_milestone,
)

KEY: Final[str] = "journey_catalogue"
SOURCES: Final[dict[str, str]] = {"pulse": "Pulse"}
MAX_WORKFLOWS: Final[int] = 20
MAX_STEPS: Final[int] = 50
MAX_NAME: Final[int] = 60
REF: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")
# Pulse's block kinds that are steps of a sale (others are tasks inside the business).
SALES_BLOCKS: Final[dict[str, str]] = {
    "lead_capture": "lead",
    "follow_up": "contacted",
    "site_visit": "appointment_booked",
    "meeting": "appointment_booked",
    "quotation": "proposal",
    "proposal": "proposal",
    "documents": "application",
    "data_capture": "application",
    "negotiation": "negotiation",
    "booking": "won",
    "payment": "won",
    "tax_invoice": "won",
}


class CatalogueError(ValueError):
    """The sent catalogue can't be kept; the message names what to fix."""


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogueError("Every workflow and step needs a name.")
    return " ".join(value.split())[:MAX_NAME]


def _ref(value: Any) -> str:
    text = str(value) if value is not None else ""
    if not REF.fullmatch(text):
        raise CatalogueError("Every workflow and step needs an id of letters, digits, - _ . :")
    return text


def clean(source: str, body: Mapping[str, Any], *, now: int) -> dict[str, Any]:
    """The catalogue as kept: bounded, names only, steps in their workflow's order."""
    if source not in SOURCES:
        raise CatalogueError("Only connected apps can send workflow steps.")
    workflows = body.get("workflows")
    if not isinstance(workflows, list) or len(workflows) > MAX_WORKFLOWS:
        raise CatalogueError(f"Send up to {MAX_WORKFLOWS} workflows.")
    out = []
    for flow in workflows:
        if not isinstance(flow, Mapping):
            raise CatalogueError("Each workflow is an object.")
        steps = flow.get("steps")
        if not isinstance(steps, list) or len(steps) > MAX_STEPS:
            raise CatalogueError(f"Send up to {MAX_STEPS} steps per workflow.")
        rows: list[tuple[int, dict[str, Any]]] = []
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                raise CatalogueError("Each step is an object.")
            block = step.get("block")
            position = step.get("position")
            at = position if isinstance(position, int) else index
            rows.append(
                (
                    at,
                    {
                        "id": _ref(step.get("id")),
                        "name": _name(step.get("name")),
                        "block": str(block)[:40] if isinstance(block, str) else None,
                        "position": at,
                    },
                )
            )
        rows.sort(key=lambda row: row[0])
        kept = [row[1] for row in rows]
        out.append({"id": _ref(flow.get("id")), "name": _name(flow.get("name")), "steps": kept})
    revision = body.get("revision")
    return {
        "source": source,
        "revision": str(revision)[:80] if revision is not None else None,
        "received_at": now,
        "workflows": out,
    }


def suggestions(config: Mapping[str, Any], journey: Journey) -> list[dict[str, Any]]:
    """The connected app's sales steps that aren't stages yet, with what each means."""
    box = config.get(KEY)
    if not isinstance(box, Mapping):
        return []
    source = str(box.get("source") or "")
    taken_refs = {stage.ref for stage in journey.stages if stage.ref}
    taken_names = {stage.label.casefold() for stage in journey.live}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for flow in box.get("workflows") or []:
        if not isinstance(flow, Mapping):
            continue
        for step in flow.get("steps") or []:
            if not isinstance(step, Mapping):
                continue
            name = str(step.get("name") or "")
            ref = f"{source}:{step.get('id')}"
            block = step.get("block")
            milestone = SALES_BLOCKS.get(str(block)) if block else None
            if milestone is None:
                milestone = guess_milestone(name)
                if milestone == "other":
                    continue  # an inside task, not a step of a sale
            if milestone in ("lead", "unreachable"):
                continue  # the first stage and Couldn't reach are there already
            if ref in taken_refs or name.casefold() in taken_names or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            kind = MILESTONE_KIND[milestone]
            out.append(
                {
                    "ref": ref,
                    "label": name,
                    "source": SOURCES.get(source, source),
                    "workflow": str(flow.get("name") or ""),
                    "milestone": milestone,
                    "meaning": MILESTONE_WORDS[milestone],
                    "kind": kind,
                    "kindWords": KIND_WORDS[kind],
                }
            )
    return out[:12]
