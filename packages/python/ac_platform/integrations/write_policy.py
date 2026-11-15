"""What an AI app, an API key or the CLI may change in Sales X-Ray, decided in one place
(owner order, 25 Oct 2026; design: docs/product/ai-writes.md, "Guardrails").

``decide`` is pure: the action, the caller's scopes, the workspace's switch and how many
changes this connection, this lead and this workspace made in the last 24 hours go in; a
decision comes out. The MCP server, the public API and the CLI all ask it before a write,
so the rules are the same whatever door a change comes through, and whatever a model was
told. Who may change which lead stays with the lead desk's own checks.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from ac_platform.lead_desk.contracts import APP_CHANGE_UNDO_DAYS

Action = Literal["note", "task", "update", "stage", "assign"]
ACTIONS: Final[tuple[Action, ...]] = ("note", "task", "update", "stage", "assign")
SCOPES: Final[dict[str, str]] = {
    "note": "leads:notes",
    "task": "leads:tasks",
    "update": "leads:update",
    "stage": "leads:stage",
    # Only an organisation's key held by an owner or admin (ai-writes.md, "Amended 15 Nov").
    "assign": "leads:assign",
}
# What a refusal calls each action.
WORDS: Final[dict[str, str]] = {
    "note": "notes",
    "task": "tasks",
    "update": "updates",
    "stage": "stage moves",
    "assign": "assigns",
}
# An organisation's key held by an owner or admin (ai-writes.md, "Amended 15 Nov",
# orchestrator for the owner, 15 Nov 2026) also assigns, changes up to 1,000 leads at once
# (previewed above 5, instead of the caps) and closes leads (Won, Lost, Junk) with a
# reason; the owner's pause and switches still decide.
BULK_MAX: Final = 1_000
PREVIEW_ABOVE: Final = 5
# The workspace's switch (Organisation -> AI apps). Defaults agreed 25 Oct 2026: notes,
# tasks and outcomes on; everything else (lead updates and stage moves too) off until an
# owner turns it on.
SWITCH_DEFAULTS: Final[dict[str, bool]] = {
    "paused": False,
    "note": True,
    "task": True,
    "outcome": True,
    "update": False,
    "stage": False,
}
# A stage move from an app (ai-writes.md, section 8): never to Won, Lost or Junk, which
# wait for a person's review.
REVIEW_STAGES: Final[tuple[str, ...]] = ("won", "lost", "junk")
REASON_LIMIT: Final = 500
# A lead update (ai-writes.md, section 2): only these fields. Phone and email decide
# duplicates and who a call matches, so they wait for the review queue (slice 2).
UPDATE_FIELDS: Final[tuple[str, ...]] = ("name", "company", "city", "interest", "language")
REVIEW_FIELDS: Final[tuple[str, ...]] = ("phone", "email")
# Caps, in the last 24 hours unless said otherwise (ai-writes.md, section 5).
PER_CONNECTION: Final[dict[str, int]] = {
    "note": 200,
    "task": 200,
    "update": 200,
    "stage": 50,
    "assign": 50,
}
PER_LEAD: Final[dict[str, int]] = {"note": 20, "task": 20, "update": 20, "stage": 5, "assign": 5}
PER_WORKSPACE: Final = 2_000
PER_MINUTE: Final = 30  # one connection, any action
UNDO_WINDOW: Final = timedelta(days=APP_CHANGE_UNDO_DAYS)
NOTE_LIMIT: Final = 1_000
# Control characters and the invisible ones that can hide text from a person (zero-width
# spaces and joiners, direction overrides); new lines and tabs stay.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿]")
_REQUEST = re.compile(r"^[\x21-\x7e]{8,80}$")


@dataclass(frozen=True, slots=True)
class Counts:
    """Changes in the last 24 hours (the minute for ``minute``)."""

    connection: Mapping[str, int]  # this connection's or key's, by action
    lead: int  # this lead's, of this action, from every door
    workspace: int  # every door and action
    minute: int  # this connection's or key's, any action


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    status: int = 200
    code: str = "ok"
    message: str = ""


ALLOW: Final = Decision(True)


def switch(config: Mapping[str, Any] | None) -> dict[str, bool]:
    """The workspace's switch as stored (lead desk settings, ``ai_writes``), with defaults."""
    raw = config if isinstance(config, Mapping) else {}
    return {
        key: raw[key] if isinstance(raw.get(key), bool) else default
        for key, default in SWITCH_DEFAULTS.items()
    }


def decide(
    action: str,
    *,
    scopes: frozenset[str],
    settings: Mapping[str, bool],
    counts: Counts | None,
    manager_key: bool = False,
) -> Decision:
    """Whether this change may go ahead now, and if not, why, in words a person can act on.

    ``manager_key``: an organisation's key held by an owner or admin ("Amended 15 Nov"),
    the only caller that assigns (no switch of its own; the owner's pause still stops it).
    ``counts`` None: one lead of such a key's bulk change, which previews instead of
    counting against the caps; the switches still decide."""
    if action not in ACTIONS:
        return Decision(False, 422, "action", "Sales X-Ray doesn't take that change from apps.")
    scope = SCOPES[action]
    if scope not in scopes:
        return Decision(
            False,
            403,
            "scope_missing",
            f"This connection doesn't have {scope}. Reconnect it and allow that.",
        )
    if settings.get("paused", False):
        return Decision(
            False,
            403,
            "writes_paused",
            "An owner has paused changes from apps in this workspace. Reading still works.",
        )
    if action == "assign":
        if not manager_key:
            return Decision(
                False,
                403,
                "managers_only",
                "Only an organisation's API key held by an owner or admin gives leads to people.",
            )
    elif not settings.get(action, False):
        return Decision(
            False,
            403,
            "action_off",
            f"An owner has turned off {WORDS[action]} from apps in this workspace.",
        )
    if counts is None:
        if not manager_key:
            raise ValueError("only a manager's bulk change goes without counts")
        return ALLOW
    if counts.minute >= PER_MINUTE:
        return Decision(False, 429, "cap_reached", "Too many changes this minute. Wait a minute.")
    if counts.workspace >= PER_WORKSPACE:
        return Decision(
            False,
            429,
            "cap_reached",
            f"This workspace took {PER_WORKSPACE} changes from apps in the last 24 hours.",
        )
    if counts.connection.get(action, 0) >= PER_CONNECTION[action]:
        return Decision(
            False,
            429,
            "cap_reached",
            f"This connection sent {PER_CONNECTION[action]} {WORDS[action]} in the last 24 hours.",
        )
    if counts.lead >= PER_LEAD[action]:
        return Decision(
            False,
            429,
            "cap_reached",
            f"This lead got {PER_LEAD[action]} {WORDS[action]} from apps in the last 24 hours.",
        )
    return ALLOW


def may_undo(
    *,
    person_id: UUID,
    manages: bool,
    made_by: UUID,
    lead_owner: UUID | None,
    made_at: datetime,
    now: datetime,
) -> Decision:
    """The person who made the change, the lead's owner or a manager, within 7 days."""
    if not (manages or person_id in {made_by, lead_owner}):
        return Decision(
            False,
            403,
            "not_yours",
            "Only the person who made it, the lead's owner or a manager can undo this.",
        )
    if made_at < now - UNDO_WINDOW:
        return Decision(
            False,
            409,
            "too_late",
            f"Changes from apps can be undone for {APP_CHANGE_UNDO_DAYS} days.",
        )
    return ALLOW


def clean_text(value: str) -> str:
    """Stored text stays inert: no control or invisible characters; trimmed."""
    kept = "".join(
        char
        for char in unicodedata.normalize("NFC", value)
        if char in "\n\t" or unicodedata.category(char) != "Cc"
    )
    return _INVISIBLE.sub("", kept).strip()


def request_ok(value: object) -> bool:
    """A caller's request id: 8 to 80 visible ASCII characters."""
    return isinstance(value, str) and _REQUEST.fullmatch(value) is not None


__all__ = [
    "ACTIONS",
    "ALLOW",
    "NOTE_LIMIT",
    "PER_CONNECTION",
    "PER_LEAD",
    "PER_MINUTE",
    "PER_WORKSPACE",
    "BULK_MAX",
    "PREVIEW_ABOVE",
    "REASON_LIMIT",
    "REVIEW_FIELDS",
    "REVIEW_STAGES",
    "SCOPES",
    "SWITCH_DEFAULTS",
    "UNDO_WINDOW",
    "UPDATE_FIELDS",
    "WORDS",
    "Counts",
    "Decision",
    "clean_text",
    "decide",
    "may_undo",
    "request_ok",
    "switch",
]
