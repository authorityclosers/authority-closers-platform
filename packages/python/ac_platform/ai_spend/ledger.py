"""Every paid AI request this environment made, read from each feature's own rows.

No feature writes here: each already records its requests where it works, so this is
one read across them, grouped by day (India time), feature, who started it, provider
and model:

- call analysis: ``conversation_inference_tasks`` with the job's provider receipt
  (C2 transcription by audio length, C4 facts and C5 report by tokens). A fixture
  canary call is "Release checks", not call analysis.
- pointer review: ``conversation_pointer_reviews`` (tokens). Operator runs are bulk
  re-scores.
- call data engine: ``call_data_runs`` (its own rupee estimate; a start without an
  outcome counts ₹2, exactly as the engine's own cap counts it).
- AI replies: ``lead_desk_ai_replies`` (its own rupee estimate).
- partner quote facts: ``partner_quote_facts`` (tokens).
- the one-pass trial: ``one_pass_runs`` on real calls (its own rupee estimate), one line
  per stage (Flash-Lite transcription, the 3.8 Flash pass); a start without an outcome
  counts ₹2. Fictional benchmark runs are the research's money and are not here.

Rupees are list-price estimates from the Admin price sheet (``admin_pricing``), never a
charge. Nothing here reads a transcript, prompt, answer, message or name.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS

INDIA = ZoneInfo("Asia/Kolkata")
OPEN_ATTEMPT_INR = Decimal(2)  # the call data engine's own count for a start with no outcome


def _number(expression: str) -> str:
    """A JSON counter as a bigint, 0 when missing or not a plain number."""
    return f"(CASE WHEN ({expression}) ~ '^[0-9]{{1,12}}$' THEN ({expression})::bigint ELSE 0 END)"


_USAGE = "j.provider_receipt -> 'usage'"
_IN = " + ".join(
    _number(f"{_USAGE} ->> '{key}'")
    for key in ("promptTokenCount", "input_tokens", "prompt_tokens")
)
_OUT = " + ".join(
    _number(f"{_USAGE} ->> '{key}'")
    for key in ("candidatesTokenCount", "output_tokens", "completion_tokens", "thoughtsTokenCount")
)
_CANARY = """EXISTS (
      SELECT 1 FROM conversation_guest_submissions g
      JOIN conversation_canary_submissions c
        ON c.submission_id = g.submission_id AND c.tenant_id = g.tenant_id
      WHERE g.recording_id = {recording})"""

SPEND_SQL = text(
    f"""
    WITH line AS (
      SELECT CASE WHEN {_CANARY.format(recording="t.recording_id")} THEN 'canary'
                  WHEN t.stage = 'C2' THEN 'call_transcription'
                  WHEN t.stage = 'C4' THEN 'call_facts'
                  ELSE 'call_report' END AS feature,
             CASE WHEN {_CANARY.format(recording="t.recording_id")} THEN 'release'
                  ELSE 'person' END AS trigger,
             coalesce(j.created_at, t.created_at) AS at,
             coalesce(j.provider_receipt ->> 'provider', '') AS provider,
             coalesce(j.provider_receipt ->> 'model', '') AS model,
             CASE WHEN t.stage = 'C2' THEN 0 ELSE {_IN} END AS input_tokens,
             CASE WHEN t.stage = 'C2' THEN 0 ELSE {_OUT} END AS output_tokens,
             CASE WHEN t.stage = 'C2' THEN {_number("t.intent ->> 'duration_ms'")} ELSE 0 END
               AS audio_ms,
             NULL::numeric AS cost_inr
      FROM conversation_inference_tasks t
      JOIN jobs j ON j.id = t.job_id
      WHERE j.provider_receipt IS NOT NULL AND coalesce(j.created_at, t.created_at) >= :since
      UNION ALL
      SELECT CASE WHEN {_CANARY.format(recording="p.recording_id")} THEN 'canary'
                  ELSE 'pointer_review' END,
             CASE WHEN {_CANARY.format(recording="p.recording_id")} THEN 'release'
                  WHEN p.created_by LIKE 'operator:%' THEN 'backfill' ELSE 'auto' END,
             p.created_at, 'gemini', coalesce(p.model_id, ''),
             coalesce(p.input_tokens, 0), coalesce(p.output_tokens, 0), 0, NULL::numeric
      FROM conversation_pointer_reviews p
      WHERE p.created_at >= :since
      UNION ALL
      SELECT 'call_data_' || d.pipeline,
             CASE WHEN d.trigger = 'backfill' THEN 'backfill'
                  WHEN d.trigger = 'operator' THEN 'operator' ELSE 'auto' END,
             d.created_at, coalesce(d.provider, 'gemini'), coalesce(d.model_id, ''),
             coalesce(d.input_tokens, 0), coalesce(d.output_tokens, 0), 0,
             CASE WHEN d.state = 'running' THEN {OPEN_ATTEMPT_INR}
                  ELSE coalesce(d.cost_inr, 0) END
      FROM call_data_runs d
      WHERE d.created_at >= :since
        AND (d.state <> 'running'
             OR NOT EXISTS (SELECT 1 FROM call_data_runs o WHERE o.supersedes_id = d.id))
      UNION ALL
      SELECT 'lead_desk_ai', CASE WHEN a.mode = 'auto' THEN 'auto' ELSE 'person' END,
             a.created_at, coalesce(a.provider, 'gemini'), coalesce(a.model, ''),
             coalesce(a.input_tokens, 0), coalesce(a.output_tokens, 0), 0,
             coalesce(a.cost_inr, 0)
      FROM lead_desk_ai_replies a
      WHERE a.created_at >= :since AND a.input_tokens IS NOT NULL
      UNION ALL
      SELECT 'partner_quote_facts', 'auto', f.created_at, 'gemini', coalesce(f.model_id, ''),
             coalesce(f.input_tokens, 0), coalesce(f.output_tokens, 0), 0, NULL::numeric
      FROM partner_quote_facts f
      WHERE f.created_at >= :since AND f.input_tokens IS NOT NULL
      UNION ALL
      SELECT 'one_pass', CASE WHEN o.trigger = 'operator' THEN 'operator' ELSE 'auto' END,
             o.created_at, 'gemini', coalesce(o.transcription_model, ''),
             coalesce(o.transcription_input_tokens, 0), coalesce(o.transcription_output_tokens, 0),
             coalesce(o.audio_ms, 0), o.transcription_cost_inr
      FROM one_pass_runs o
      WHERE o.created_at >= :since AND o.source = 'call' AND o.state <> 'running'
        AND o.transcription_cost_inr IS NOT NULL
      UNION ALL
      SELECT 'one_pass', CASE WHEN o.trigger = 'operator' THEN 'operator' ELSE 'auto' END,
             o.created_at, 'gemini', coalesce(o.analysis_model, ''),
             coalesce(o.analysis_input_tokens, 0), coalesce(o.analysis_output_tokens, 0), 0,
             o.analysis_cost_inr
      FROM one_pass_runs o
      WHERE o.created_at >= :since AND o.source = 'call' AND o.state <> 'running'
        AND o.analysis_cost_inr IS NOT NULL
      UNION ALL
      SELECT 'one_pass', CASE WHEN o.trigger = 'operator' THEN 'operator' ELSE 'auto' END,
             o.created_at, 'gemini', coalesce(o.analysis_model, ''), 0, 0, 0,
             {OPEN_ATTEMPT_INR}
      FROM one_pass_runs o
      WHERE o.created_at >= :since AND o.source = 'call' AND o.state = 'running'
        AND NOT EXISTS (SELECT 1 FROM one_pass_runs d WHERE d.supersedes_id = o.id)
    )
    SELECT feature, trigger, (at AT TIME ZONE 'Asia/Kolkata')::date AS day, provider, model,
           count(*) AS requests, sum(input_tokens) AS input_tokens,
           sum(output_tokens) AS output_tokens, sum(audio_ms) AS audio_ms,
           sum(cost_inr) AS cost_inr, count(cost_inr) AS costed
    FROM line
    GROUP BY 1, 2, 3, 4, 5
    """  # noqa: S608 - built only from the fixed fragments above
)


@dataclass(frozen=True, slots=True)
class SpendRow:
    feature: str
    trigger: str
    day: date
    provider: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    audio_ms: int
    inr: Decimal
    priced: bool  # False: no list price for this model, counted as ₹0


def _fx(snapshot: Any) -> Decimal:
    return Decimal(snapshot.as_dict()["usd_to_inr"])


def price_inr(
    provider: str, model: str, input_tokens: int, output_tokens: int, audio_ms: int
) -> tuple[Decimal, bool]:
    """List-price rupees for summed usage, and whether the model has a price.

    A Gemini model missing from the sheet is priced as Gemini 3.8 Flash, so an
    unknown model never reads as free."""
    snapshot = PRICING_SNAPSHOTS.get((provider, model))
    if snapshot is None and provider == "gemini":
        snapshot = PRICING_SNAPSHOTS[("gemini", "gemini-3.8-flash")]
    if snapshot is None:
        return Decimal(0), input_tokens == 0 and output_tokens == 0 and audio_ms == 0
    fx = _fx(snapshot)
    if snapshot.rate_basis == "per_hour" and snapshot.usd_per_hour is not None:
        usd = Decimal(audio_ms) / Decimal(3_600_000) * snapshot.usd_per_hour
    elif snapshot.rate_basis == "per_minute" and snapshot.usd_per_minute is not None:
        usd = Decimal(audio_ms) / Decimal(60_000) * snapshot.usd_per_minute
    else:
        usd = (
            Decimal(input_tokens) * (snapshot.input_usd_per_million_tokens or 0)
            + Decimal(output_tokens) * (snapshot.output_usd_per_million_tokens or 0)
        ) / Decimal(1_000_000)
    return (usd * fx).quantize(Decimal("0.0001")), True


def rows_from(records: Iterable[Mapping[str, Any]]) -> list[SpendRow]:
    rows: list[SpendRow] = []
    for record in records:
        tokens_in = int(record["input_tokens"] or 0)
        tokens_out = int(record["output_tokens"] or 0)
        audio = int(record["audio_ms"] or 0)
        if int(record["costed"] or 0) == int(record["requests"]):
            inr, priced = Decimal(record["cost_inr"] or 0), True
        else:
            inr, priced = price_inr(
                str(record["provider"]), str(record["model"]), tokens_in, tokens_out, audio
            )
            inr += Decimal(record["cost_inr"] or 0)
        rows.append(
            SpendRow(
                feature=str(record["feature"]),
                trigger=str(record["trigger"]),
                day=record["day"],
                provider=str(record["provider"]),
                model=str(record["model"]),
                requests=int(record["requests"]),
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                audio_ms=audio,
                inr=inr,
                priced=priced,
            )
        )
    return rows


def read(connection: Any, since: datetime) -> list[SpendRow]:
    """Spend since ``since`` (a synchronous SQLAlchemy connection)."""
    return rows_from(connection.execute(SPEND_SQL, {"since": since}).mappings().all())


async def read_async(database: Any, since: datetime) -> list[SpendRow]:
    """The same for an ``AsyncSession``."""
    result = await database.execute(SPEND_SQL, {"since": since})
    return rows_from(result.mappings().all())


def month_start(now: datetime) -> datetime:
    """The first of this calendar month, midnight India time."""
    local = now.astimezone(INDIA)
    return datetime.combine(local.date().replace(day=1), time.min, tzinfo=INDIA)


def window_start(now: datetime, days: int) -> datetime:
    """Midnight India time, ``days`` days ago including today."""
    local = now.astimezone(INDIA).date() - timedelta(days=days - 1)
    return datetime.combine(local, time.min, tzinfo=INDIA)


@dataclass(frozen=True, slots=True)
class Totals:
    """Spend of a window: in all, per feature, and by backfills and bulk re-scores."""

    total: Decimal
    by_feature: dict[str, Decimal]
    backfill: Decimal


def totals(rows: Iterable[SpendRow]) -> Totals:
    by_feature: dict[str, Decimal] = defaultdict(Decimal)
    backfill = Decimal(0)
    for row in rows:
        by_feature[row.feature] += row.inr
        if row.trigger == "backfill":
            backfill += row.inr
    return Totals(sum(by_feature.values(), Decimal(0)), dict(by_feature), backfill)
