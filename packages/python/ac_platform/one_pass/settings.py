"""Which analysis pipeline this environment runs, set in Admin (Providers hub).

- ``classic``: today's pipeline only (Scribe, C4 facts, C5 report, pointer review, call
  data). The default everywhere.
- ``both``: today's pipeline as now, and the one-pass pipeline on the same call beside
  it. Both results are stored; the person sees classic. One-pass is an evaluated
  candidate, never the official score (AC-SVAL gates).
- ``one_pass``: the person sees one-pass results. Not offered yet: publishing them into
  the Report is the next step after the comparison, and the production switch is the
  owner's decision.

Development only for now (owner, 21 Oct 2026): staging and production stay classic, so
no production approval or sealing changes. The one-pass spend cap lives in Admin → AI
spend (feature ``one_pass``), where raising it is the recorded approval.
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
    "one_pass": "One pass (people see it)",
}
TIERS: Final[dict[str, str]] = {
    "standard": "Standard (answer in seconds)",
    "flex": "Flex (half price, may wait minutes)",
}
TRANSCRIPTION_MODEL: Final = "gemini-3.1-flash-lite"
ANALYSIS_MODEL: Final = "gemini-3.8-flash"
# Publishing one-pass results to people (mode one_pass) is not built yet.
PUBLISHING_READY: Final = False
# Environments where a mode other than classic may be saved.
TRIAL_ENVIRONMENTS: Final = frozenset({"development"})
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
    if mode == "classic":
        return None
    if mode == "one_pass" and not PUBLISHING_READY:
        return "Showing one-pass results to people comes after the side-by-side comparison."
    if environment_name(environment) not in TRIAL_ENVIRONMENTS:
        return "Staging and production stay on today's pipeline until the owner decides."
    return None


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
            {"value": key, "label": label, "why_not": why_not(environment, key)}
            for key, label in MODES.items()
        ],
        "tiers": [{"value": key, "label": label} for key, label in TIERS.items()],
    }
