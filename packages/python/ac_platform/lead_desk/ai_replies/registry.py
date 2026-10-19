"""The model behind AI replies, and when it may run at all.

AI replies send a lead's last messages and the organisation's own profile to a text
model. That is new data for an AI provider: the privacy guide today says Lead Desk
details stay on our servers, and AGENTS.md puts provider activation behind the
AC-GOV-AUD-001 gate (consent, retention, provenance, provider, professional). So the
model is off until every one of these holds, and the feature stays hidden until then:

1. Root's gate file records the gate as cleared for lead messages, never in git:
   ``/etc/authority-closers/lead-desk-ai-gate.json`` with ``{"cleared": ["gemini"]}``
   (the same pattern as live transcription's gate).
2. The process has the provider key (``GEMINI_API_KEY``; today only the call data
   runner's ``infisical run`` child has it, so the API needs it placed the same way).
3. Today's AI reply spend across all organisations is under the daily cap
   (``AC_LEAD_DESK_AI_DAILY_CAP_INR``, default ₹100), counted from
   ``lead_desk_ai_replies.cost_inr`` (list-price estimates, never a charge).

The model is the call data engine's client and price list (``call_data.provider``,
``call_data.settings``): Gemini with JSON output; ``AC_LEAD_DESK_AI_MODEL`` picks one
from that menu (default its fast model). Nothing here logs prompts or answers.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.call_data import provider as text_models
from ac_platform.call_data import settings as model_menu
from ac_platform.lead_desk.ai_replies.service import Completion, ModelUnavailable
from ac_platform.lead_desk.models import LeadAiReply

GATE_FILE: Final[Path] = Path("/etc/authority-closers/lead-desk-ai-gate.json")
PROVIDER: Final[str] = "gemini"
DEFAULT_CAP_INR: Final[Decimal] = Decimal("100")
SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "handoff": {"type": "boolean"},
        "reason": {
            "type": "string",
            "enum": ["ok", "human", "complaint", "price", "discount", "unsure", "off_topic"],
        },
    },
    "required": ["reply", "handoff", "reason"],
}


def gate_cleared(path: Path = GATE_FILE) -> bool:
    """True only when Root recorded the provider gate as cleared for lead messages."""
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    cleared = record.get("cleared") if isinstance(record, dict) else None
    return isinstance(cleared, list) and PROVIDER in cleared


def model_name(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    wanted = (env.get("AC_LEAD_DESK_AI_MODEL") or "").strip()
    if wanted in model_menu.MODELS and model_menu.MODELS[wanted].provider == PROVIDER:
        return wanted
    return next(name for name, item in model_menu.MODELS.items() if item.provider == PROVIDER)


def daily_cap(env: Mapping[str, str] | None = None) -> Decimal:
    env = os.environ if env is None else env
    try:
        value = Decimal((env.get("AC_LEAD_DESK_AI_DAILY_CAP_INR") or "").strip() or DEFAULT_CAP_INR)
    except InvalidOperation:
        return DEFAULT_CAP_INR
    return max(Decimal(0), value)


def available(
    *, path: Path = GATE_FILE, env: Mapping[str, str] | None = None
) -> tuple[bool, str | None]:
    """Whether AI replies can run here, and if not, why (for logs and Admin, not users)."""
    env = os.environ if env is None else env
    if not gate_cleared(path):
        return False, "gate"
    if not (env.get("GEMINI_API_KEY") or "").strip():
        return False, "key"
    return True, None


async def spent_today(db: AsyncSession, now: datetime) -> Decimal:
    start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    total = await db.scalar(
        select(func.coalesce(func.sum(LeadAiReply.cost_inr), 0)).where(
            LeadAiReply.created_at >= start
        )
    )
    return Decimal(total or 0)


class GatedModel:
    """Gemini behind the gate, the key and the daily cap."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        client: Callable[[], text_models.TextModel] = text_models.Gemini,
        path: Path = GATE_FILE,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions = sessions
        self.client = client
        self.path = path
        self.env = env
        self.clock = clock

    async def complete(self, *, tenant_id: UUID, system: str, user: str) -> Completion:
        ok, why = available(path=self.path, env=self.env)
        if not ok:
            raise ModelUnavailable("off", f"AI replies are off here ({why}).")
        async with self.sessions() as db:
            if await spent_today(db, self.clock()) >= daily_cap(self.env):
                raise ModelUnavailable("budget", "Today's AI reply budget is used up.")
        model = model_name(self.env)
        try:
            answer = await asyncio.to_thread(
                self.client().generate_json, model=model, system=system, user=user, schema=SCHEMA
            )
        except text_models.ProviderFailure as error:
            raise ModelUnavailable("failed", error.outcome) from None
        usage = answer.usage
        tokens_in = int(usage.get("promptTokenCount") or 0)
        # Thinking tokens are billed as output (as Admin's cost metrics count them).
        tokens_out = int(usage.get("candidatesTokenCount") or 0) + int(
            usage.get("thoughtsTokenCount") or 0
        )
        return Completion(
            text=json.dumps(answer.value, ensure_ascii=False),
            provider=PROVIDER,
            model=model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_inr=model_menu.cost_inr(model, tokens_in, tokens_out),
        )


def model_for(sessions: async_sessionmaker[AsyncSession]) -> GatedModel:
    return GatedModel(sessions)
