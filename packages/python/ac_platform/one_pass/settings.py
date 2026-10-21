"""Which analysis pipeline this environment runs, set in Admin (Providers hub).

- ``classic``: today's pipeline only (Scribe, C4 facts, C5 report, pointer review, call
  data). The default everywhere.
- ``both``: today's pipeline as now, and the one-pass pipeline on the same call beside
  it. Both results are stored; the person sees classic. One-pass is an evaluated
  candidate, never the official score (AC-SVAL gates).
- ``one_pass``: people see one-pass results: each call's deep call data and pointer
  review come from one strict Gemini 3.8 Flash read of the saved transcript; today's
  C2, C4 and C5 stay (``publish.py``). Where the call data engine runs (development and
  staging), by the owner's action in Admin (owner, 21 Oct 2026: "So at least get this
  on prod now!!!"): a control account, signed in within ten minutes, types
  ``one_pass`` and gives the reason. ``classic`` is one click back, at once.

Production runs no call data engine, so this read would replace only the pointer
review there; production's one-pass saving is its transcription route (Gemini 3.1
Flash-Lite, sealed, chosen in Providers). ``both`` stays development only (two reads of
each call). Staging and production run the standard tier for now; Flex after a latency
check. The one-pass spend cap lives in Admin → AI spend (feature ``one_pass``), where
raising it is the recorded approval.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text

from ac_platform.ai_spend.policy import environment_name
from ac_platform.one_pass.models import AnalysisPipelineSettings

MODES: Final[dict[str, str]] = {
    "classic": "Today's pipeline",
    "both": "Both, side by side (people see today's)",
    "one_pass": "One pass: people see it (deep call data and pointer review in one read)",
}
TIERS: Final[dict[str, str]] = {
    "standard": "Standard (answer in seconds)",
    "flex": "Flex (half price, may wait minutes)",
}
TRANSCRIPTION_MODEL: Final = "gemini-3.1-flash-lite"
ANALYSIS_MODEL: Final = "gemini-3.8-flash"
# Environments where the side-by-side trial (mode both) may run.
TRIAL_ENVIRONMENTS: Final = frozenset({"development"})
# Environments whose call data engine runs, so one read can replace its deep read.
PUBLISH_ENVIRONMENTS: Final = frozenset({"development", "staging"})
# Environments where only the standard tier runs for now (owner, 21 Oct 2026).
STANDARD_ONLY: Final = frozenset({"staging", "production"})
# What the owner types to show people one-pass results.
CONFIRM: Final = "one_pass"
MAX_CALL_MINUTES: Final = 120

_DEFAULTS: Final[dict[str, Any]] = {
    "mode": "classic",
    "transcription_tier": "standard",
    "analysis_tier": "standard",
    "max_call_minutes": 60,
}


class SettingsError(ValueError):
    """Settings that can't be saved; ``code`` says which part."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def defaults() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULTS)


def why_not(environment: str, mode: str) -> str | None:
    """Why ``mode`` can't be chosen here, in plain words; None when it can."""
    name = environment_name(environment)
    if mode == "classic":
        return None
    if mode == "one_pass":
        if name in PUBLISH_ENVIRONMENTS:
            return None
        return (
            "Production runs no call data engine, so its one-pass saving is the "
            "transcription route: Gemini 3.1 Flash-Lite in Providers (sealed)."
        )
    if name not in TRIAL_ENVIRONMENTS:
        return "The side-by-side trial runs on development only."
    return None


def needs_owner(mode: str) -> bool:
    """Showing people one-pass results is the owner's action (typed confirm, reason)."""
    return mode == "one_pass"


def validate(environment: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """A complete, checked document: missing parts take the defaults, unknown parts and
    choices this environment may not make are refused."""
    result = defaults()
    if not isinstance(config, Mapping) or not set(config) <= set(result):
        raise SettingsError("settings_shape")
    mode = config.get("mode", result["mode"])
    if mode not in MODES:
        raise SettingsError("mode")
    if why_not(environment, str(mode)) is not None:
        raise SettingsError("mode_not_here")
    result["mode"] = mode
    for key in ("transcription_tier", "analysis_tier"):
        tier = config.get(key, result[key])
        if tier not in TIERS:
            raise SettingsError(key)
        if tier != "standard" and environment_name(environment) in STANDARD_ONLY:
            raise SettingsError(f"{key}_standard_only")
        result[key] = tier
    minutes = config.get("max_call_minutes", result["max_call_minutes"])
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        raise SettingsError("max_call_minutes")
    if not 1 <= minutes <= MAX_CALL_MINUTES:
        raise SettingsError("max_call_minutes")
    result["max_call_minutes"] = minutes
    return result


def read(connection: Any, environment: str) -> tuple[dict[str, Any], int | None]:
    """This environment's settings and revision (None: never saved, the defaults).

    Before the migration has run there is no table, and the defaults apply. A saved
    document that no longer validates (a newer release, or a mode this environment may
    no longer run) reads as classic, never as a trial."""
    if not connection.scalar(text("SELECT to_regclass('analysis_pipeline_settings') IS NOT NULL")):
        return defaults(), None
    row = connection.execute(
        select(AnalysisPipelineSettings.config, AnalysisPipelineSettings.revision)
        .order_by(AnalysisPipelineSettings.revision.desc())
        .limit(1)
    ).first()
    if row is None:
        return defaults(), None
    try:
        return validate(environment, row.config or {}), int(row.revision)
    except SettingsError:
        return defaults(), int(row.revision)


def save(
    connection: Any,
    environment: str,
    config: Mapping[str, Any],
    *,
    person_id: UUID | None,
    reason: str | None,
    now: datetime,
) -> int:
    checked = validate(environment, config)
    current = connection.scalar(
        select(AnalysisPipelineSettings.revision)
        .order_by(AnalysisPipelineSettings.revision.desc())
        .limit(1)
        .with_for_update()
    )
    revision = int(current or 0) + 1
    connection.execute(
        insert(AnalysisPipelineSettings).values(
            id=uuid4(),
            revision=revision,
            config=checked,
            reason=(reason or "").strip()[:200] or None,
            created_by_person_id=person_id,
            created_at=now,
        )
    )
    return revision


def history(connection: Any, limit: int = 10) -> list[dict[str, Any]]:
    rows = connection.execute(
        select(
            AnalysisPipelineSettings.revision,
            AnalysisPipelineSettings.config,
            AnalysisPipelineSettings.reason,
            AnalysisPipelineSettings.created_by_person_id,
            AnalysisPipelineSettings.created_at,
        )
        .order_by(AnalysisPipelineSettings.revision.desc())
        .limit(limit)
    ).all()
    return [
        {
            "revision": row.revision,
            "config": row.config,
            "reason": row.reason,
            "by": str(row.created_by_person_id) if row.created_by_person_id else None,
            "at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def public(environment: str, config: dict[str, Any], revision: int | None) -> dict[str, Any]:
    """The Admin read: the document, its revision and every choice with why it is off."""
    return {
        "environment": environment_name(environment),
        "revision": revision,
        "config": config,
        "defaults": defaults(),
        "models": {"transcription": TRANSCRIPTION_MODEL, "analysis": ANALYSIS_MODEL},
        "modes": [
            {
                "value": key,
                "label": label,
                "why_not": why_not(environment, key),
                "needs_owner": needs_owner(key),
            }
            for key, label in MODES.items()
        ],
        "confirm": CONFIRM,
        "tiers": [{"value": key, "label": label} for key, label in TIERS.items()],
    }
