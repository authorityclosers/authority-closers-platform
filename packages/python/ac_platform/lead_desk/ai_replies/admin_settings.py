"""AI replies' Admin settings for one environment: the switch, the model and the cap.

Owner rules (19 Oct 2026, through the orchestrator):

- Every AI provider and its key is chosen in Admin; the key itself stays in Infisical
  and only the AI replies runner (inside ``infisical run``, like the call data engine)
  ever sees it. The API never holds a model key.
- Lead messages go to the provider only while this environment's switch is on (Admin,
  audited, with the provider and model shown).
- The cap is a one-click dial: presets (₹100, ₹300, ₹400) or a custom amount, per day,
  per month, or for good. At the cap automatic replies wait ("waiting for budget"),
  suggestions stop, the owner gets one alert, and "Raise and resume" in Admin restarts
  them.

Settings are saved as revisions (``lead_desk_ai_settings``, newest wins), like
``call_data_settings``. Spend is the list-price estimate of each reply
(``lead_desk_ai_replies.cost_inr``), never a charge.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.call_data import settings as model_menu
from ac_platform.lead_desk.models import LeadAiReply, LeadAiSettings

PROVIDERS: Final[tuple[str, ...]] = ("gemini",)  # the providers this key path can run
PRESETS: Final[tuple[int, ...]] = (100, 300, 400)
PERIODS: Final[tuple[str, ...]] = ("daily", "monthly", "lifetime")
MAX_CAP: Final[int] = 50_000


class SettingsError(ValueError):
    """Settings that can't be saved; ``code`` says which part."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _models(provider: str) -> list[str]:
    return [name for name, item in model_menu.MODELS.items() if item.provider == provider]


DEFAULTS: Final[dict[str, Any]] = {
    "enabled": False,
    "provider": "gemini",
    "model": _models("gemini")[0],
    "cap_inr": 100,
    "period": "daily",
}


def validate(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The settings to save, complete and checked."""
    merged = {**DEFAULTS, **{key: raw[key] for key in DEFAULTS if key in raw}}
    if not isinstance(merged["enabled"], bool):
        raise SettingsError("enabled")
    if merged["provider"] not in PROVIDERS:
        raise SettingsError("provider")
    if merged["model"] not in _models(merged["provider"]):
        raise SettingsError("model")
    cap = merged["cap_inr"]
    if not isinstance(cap, int) or isinstance(cap, bool) or not 0 <= cap <= MAX_CAP:
        raise SettingsError("cap_inr")
    if merged["period"] not in PERIODS:
        raise SettingsError("period")
    return merged


def raise_to(cap: int) -> int:
    """The next one-click cap above ``cap``: the next preset, else ₹100 more."""
    for preset in PRESETS:
        if preset > cap:
            return preset
    return min(MAX_CAP, cap + 100)


def period_start(period: str, now: datetime) -> datetime | None:
    """Where this period's spend is counted from (None: for good)."""
    day = now.astimezone(UTC).date()
    if period == "daily":
        return datetime.combine(day, time.min, tzinfo=UTC)
    if period == "monthly":
        return datetime.combine(day.replace(day=1), time.min, tzinfo=UTC)
    return None


def period_key(period: str, now: datetime) -> str:
    """One owner alert per period: the day, the month, or once."""
    day = now.astimezone(UTC).date()
    return (
        day.isoformat()
        if period == "daily"
        else day.isoformat()[:7]
        if period == "monthly"
        else "lifetime"
    )


async def read(db: AsyncSession) -> tuple[dict[str, Any], int | None]:
    """This environment's settings and their revision (None: never saved, defaults)."""
    row = await db.scalar(select(LeadAiSettings).order_by(LeadAiSettings.revision.desc()).limit(1))
    if row is None:
        return dict(DEFAULTS), None
    try:
        return validate(row.config or {}), row.revision
    except SettingsError:
        return dict(DEFAULTS), row.revision


async def save(
    db: AsyncSession, config: Mapping[str, Any], *, person_id: UUID | None, now: datetime
) -> int:
    current = await db.scalar(select(func.max(LeadAiSettings.revision)))
    revision = int(current or 0) + 1
    db.add(
        LeadAiSettings(
            id=uuid4(),
            revision=revision,
            config=validate(config),
            created_by_person_id=person_id,
            created_at=now,
        )
    )
    await db.flush()
    return revision


async def spent(db: AsyncSession, config: Mapping[str, Any], now: datetime) -> Decimal:
    """This period's AI reply spend across organisations (list-price estimates)."""
    start = period_start(str(config.get("period") or "daily"), now)
    query = select(func.coalesce(func.sum(LeadAiReply.cost_inr), 0))
    if start is not None:
        query = query.where(LeadAiReply.created_at >= start)
    return Decimal(await db.scalar(query) or 0)


async def capped(db: AsyncSession, config: Mapping[str, Any], now: datetime) -> bool:
    return await spent(db, config, now) >= Decimal(int(config.get("cap_inr") or 0))


async def queue(db: AsyncSession) -> dict[str, int]:
    """Replies still to answer: queued for the runner, or waiting for budget."""
    counts = {"queued": 0, "waiting": 0}
    rows = await db.execute(
        select(LeadAiReply.outcome, func.count())
        .where(LeadAiReply.outcome.in_(tuple(counts)))
        .group_by(LeadAiReply.outcome)
    )
    for outcome, count in rows.all():
        counts[str(outcome)] = int(count)
    return counts
