"""Operations-admin cost and usage across environments (owner order, 19 Oct 2026).

One Admin shows what Sales X-Ray really costs and earns in production, staging
and dev. Each environment's usage numbers are exported read-only by the host
collector (``infra/metrics/ac-metrics-collect``) into a separate metrics store,
``<store root>/<environment>/usage.json``; this module only reads that store.
It never opens another environment's database, never writes anything, and
never reads call content: the export holds opaque ids, dates, labels and
counters only. People appear only as per-environment pseudonyms
(``usage_people.pseudonyms``), and exports from 21 Oct carry no names: for this
Admin's own environment, organisation and person names are read live from its
own database for the signed-in control account, and never stored.

Money here is a list-price estimate: provider counters (tokens, audio length)
priced with the repo price sheet (``admin_pricing``). It is not an invoice and
it never becomes payment, budget or progress state (AGENTS.md).

Copies: dev's database started as a copy of staging, and production may later
be copied down. A call, step or review present in an upstream environment
(production, then staging, then dev) is counted there only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ac_platform.conversation_intelligence.admin_pricing import (
    FX_SET_ON,
    FX_USD_TO_INR,
    PRICING_SNAPSHOTS,
    estimate_provider_usage,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.fx.reference import rate_on
from ac_platform.fx.store import REFRESHER
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Tenant
from ac_platform.usage_people import pseudonyms

SCHEMA = "ac.sales-xray.usage-metrics/1"
# Upstream first: a row that also exists upstream is a copy and counts there.
ENVIRONMENTS = ("production", "staging", "development")
ENVIRONMENT_FILTERS = ("all", *ENVIRONMENTS)
MAX_DAYS = 120
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CALLS = 300
# Calls that cost nothing are listed apart, newest first (owner's review, 19 Oct 2026).
MAX_ZERO_CALLS = 100
# Organisations offered by the filter, and the shape of their ids (tenant uuids).
MAX_COMPANIES = 60
COMPANY_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# How the Per call tab can order the calls with a cost.
CALL_SORTS = ("newest", "cost", "per_minute", "audio", "tokens")
STALE_AFTER = timedelta(minutes=45)
INDIA = ZoneInfo("Asia/Kolkata")
TEST_KINDS = frozenset({"canary", "qa"})
PROVIDER_STAGES = ("C2", "C4", "C5")
STAGE_LABELS = {
    "C1": "Audio check",
    "C2": "Transcription",
    "C4": "Facts",
    "C5": "Report",
    "PR": "Pointer review",
    "CDF": "Call data · fast",
    "CDD": "Call data · deep",
    "AR": "AI replies",
    "QF": "Quote facts",
}
# Paid AI beyond call analysis (the export's ai_work rows).
AI_WORK_STAGES = ("CDF", "CDD", "AR", "QF")
# An unknown Gemini model is priced as Flash, never read as free (as the AI spend ledger).
FALLBACK_MODEL = "gemini-3.8-flash"
FX = {
    "currency": "USD",
    "mode": "planning",
    "usd_to_inr": float(FX_USD_TO_INR),
    "set_on": FX_SET_ON.isoformat(),
    "planning_usd_to_inr": float(FX_USD_TO_INR),
    "latest": None,
    "unrated_steps": 0,
    "problem": None,
    "source": "The planning rate, set with the price sheet; providers bill in US dollars.",
}
FX_MODES = ("daily", "planning")
HOLD_REFS = {
    "provider-cost-reconciliation": "Waiting for settlement or an invoice check",
    "provider-outcome-reconciliation": "Provider outcome unknown: invoice check",
    "list-price-estimate": "Settled at list price",
    "checkpoint": "Local step, no charge",
}
# Why holds are open, and what settles them (owner approval 19 Oct 2026).
HOLD_FINDING = (
    "From v0.64 the worker settles each AI budget hold at list price the moment its "
    "validated provider receipt lands (owner's approval, 19 Oct), once and audited. "
    "Holds still open are ones these rules can't price (older steps with no audio "
    "length or an old receipt) and ones whose provider outcome is unknown; they wait for "
    "an invoice check. Holds opened between 17 Oct and that release can be settled with "
    "the approved one-time script."
)

# (coaching prompt, facts prompt, report model, transcription model, settings revision)
Version = tuple[str | None, str | None, str | None, str | None, str | None]


@dataclass(frozen=True)
class Call:
    environment: str
    id: str
    company: str | None
    at: datetime
    kind: str
    audio_ms: int
    billed_s: int
    plan: str | None
    accepted_at: datetime | None
    delivered_at: datetime | None
    # A report exists: its minutes were charged, or (before minute billing) its C5 step finished.
    report_at: datetime | None
    version: Version
    gold: tuple[int, int, int]
    # Pseudonymous person id (usage_people.pseudonyms): never a person id or name.
    person: str | None = None


@dataclass(frozen=True)
class Step:
    environment: str
    call: str | None
    company: str | None
    stage: str
    provider: str | None
    model: str | None
    status: str
    attempts: int
    input_tokens: int
    output_tokens: int
    audio_ms: int
    elapsed_ms: int | None
    paise: int | None
    at: datetime
    person: str | None = None


@dataclass
class Export:
    environment: str
    generated_at: datetime | None
    migration: str | None
    window_days: int
    calls: list[Call] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    holds: list[dict[str, Any]] = field(default_factory=list)
    budgets: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    subscriptions: list[dict[str, Any]] = field(default_factory=list)
    companies: dict[str, dict[str, str | None]] = field(default_factory=dict)
    # Names for this Admin's own environment only, read live (never from the store).
    people: dict[str, str] = field(default_factory=dict)
    synthetic: dict[str, int] = field(default_factory=dict)
    # Calls waiting for AI budget at export time (they resume by themselves).
    waiting_calls: int = 0
    copies_dropped: int = 0


# ---------- reading the store ----------


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _rows(document: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _person(value: Any) -> str | None:
    text = _text(value)
    return text if text is not None and pseudonyms.PATTERN.fullmatch(text) else None


def _usage_tokens(provider: str | None, usage: Mapping[str, Any] | None) -> tuple[int, int]:
    if not usage:
        return 0, 0
    if provider == "openai":
        return _int(usage.get("input_tokens")), _int(usage.get("output_tokens"))
    return (
        _int(usage.get("promptTokenCount")),
        _int(usage.get("candidatesTokenCount")) + _int(usage.get("thoughtsTokenCount")),
    )


def price(
    provider: str | None, model: str | None, usage: Mapping[str, Any] | None, audio_ms: int
) -> int | None:
    """List-price paise for one provider step, or None when it can't be priced."""

    estimate = estimate_provider_usage(
        provider, model, usage, duration_ms=audio_ms if audio_ms > 0 else None
    )
    paise = estimate.get("paise")
    return paise if estimate.get("state") == "available" and type(paise) is int else None


def parse_export(environment: str, document: Mapping[str, Any]) -> Export:
    """One environment's export as typed rows, every step priced."""

    if document.get("schema") != SCHEMA:
        raise ValueError("unknown_schema")
    export = Export(
        environment=environment,
        generated_at=_when(document.get("generated_at")),
        migration=_text(document.get("migration")),
        window_days=_int(document.get("window_days")),
    )
    for row in _rows(document, "companies"):
        if (company := _text(row.get("id"))) is not None:
            # Exports from 21 Oct carry no names; Admin reads its own environment's live.
            export.companies[company] = {
                "name": _text(row.get("name")),
                "kind": _text(row.get("kind")) or "other",
            }
    calls: dict[str, Call] = {}
    for row in _rows(document, "calls"):
        call_id, at = _text(row.get("id")), _when(row.get("at"))
        if call_id is None or at is None:
            continue
        gold_value = row.get("gold")
        gold: dict[str, Any] = gold_value if isinstance(gold_value, dict) else {}
        calls[call_id] = Call(
            environment=environment,
            id=call_id,
            company=_text(row.get("company")),
            at=at,
            kind=_text(row.get("kind")) or "real",
            audio_ms=_int(row.get("audio_ms")),
            billed_s=_int(row.get("billed_s")),
            plan=_text(row.get("plan")),
            accepted_at=_when(row.get("accepted_at")),
            delivered_at=_when(row.get("delivered_at")),
            report_at=None,
            version=(
                _text(row.get("prompt")),
                _text(row.get("facts")),
                _text(row.get("report_model")),
                _text(row.get("transcription_model")),
                _text(row.get("settings")),
            ),
            gold=(_int(gold.get("agree")), _int(gold.get("partly")), _int(gold.get("disagree"))),
            person=_person(row.get("person")),
        )
    for row in _rows(document, "steps"):
        at = _when(row.get("at"))
        stage = _text(row.get("stage"))
        if at is None or stage not in PROVIDER_STAGES:
            continue
        provider, model = _text(row.get("provider")), _text(row.get("model"))
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else None
        call = calls.get(_text(row.get("call")) or "")
        audio = _int(row.get("audio_ms")) or (call.audio_ms if call and stage == "C2" else 0)
        status = _text(row.get("status")) or "unknown"
        tokens = _usage_tokens(provider, usage)
        export.steps.append(
            Step(
                environment=environment,
                call=_text(row.get("call")),
                company=_text(row.get("company")),
                stage=stage,
                provider=provider,
                model=model,
                status=status,
                attempts=_int(row.get("attempts")),
                input_tokens=tokens[0],
                output_tokens=tokens[1],
                audio_ms=audio if stage == "C2" else 0,
                elapsed_ms=_int(row.get("provider_ms"))
                if row.get("provider_ms") is not None
                else None,
                # Only a finished step with a receipt is priced; the rest is counted, not guessed.
                paise=price(provider, model, usage, audio) if status == "succeeded" else None,
                at=at,
            )
        )
    finished: dict[str, datetime] = {}
    for step in export.steps:
        if step.stage == "C5" and step.status == "succeeded" and step.call:
            done = step.at + timedelta(milliseconds=step.elapsed_ms or 0)
            finished[step.call] = min(done, finished.get(step.call, done))
    export.calls = [
        replace(call, report_at=call.delivered_at or finished.get(call.id))
        for call in calls.values()
    ]
    for row in _rows(document, "local_steps"):
        at = _when(row.get("at"))
        if at is None:
            continue
        export.steps.append(
            Step(
                environment=environment,
                call=_text(row.get("call")),
                company=_text(row.get("company")),
                stage="C1",
                provider="local",
                model=None,
                status=_text(row.get("status")) or "unknown",
                attempts=_int(row.get("attempts")),
                input_tokens=0,
                output_tokens=0,
                audio_ms=0,
                elapsed_ms=_int(row.get("run_ms")) if row.get("run_ms") is not None else None,
                paise=0,
                at=at,
            )
        )
    for row in _rows(document, "pointer_reviews"):
        at = _when(row.get("at"))
        if at is None:
            continue
        model = _text(row.get("model"))
        usage = {
            "promptTokenCount": _int(row.get("input_tokens")),
            "candidatesTokenCount": _int(row.get("output_tokens")),
        }
        export.steps.append(
            Step(
                environment=environment,
                call=_text(row.get("call")),
                company=_text(row.get("company")),
                stage="PR",
                provider="gemini",
                model=model,
                status="succeeded",
                attempts=1,
                input_tokens=usage["promptTokenCount"],
                output_tokens=usage["candidatesTokenCount"],
                audio_ms=0,
                elapsed_ms=None,
                paise=price("gemini", model, usage, 0),
                at=at,
            )
        )
    for row in _rows(document, "ai_work"):
        at = _when(row.get("at"))
        stage = _text(row.get("stage"))
        if at is None or stage not in AI_WORK_STAGES:
            continue
        provider, model = _text(row.get("provider")) or "gemini", _text(row.get("model"))
        raw = _text(row.get("status")) or "unknown"
        status = raw if raw in ("failed", "skipped", "running") else "succeeded"
        usage = {
            "promptTokenCount": _int(row.get("input_tokens")),
            "candidatesTokenCount": _int(row.get("output_tokens")),
        }
        if status == "running":
            paise: int | None = 200  # the engine counts a start with no outcome as Rs 2
        else:
            # The price sheet first, so every figure uses one rate; then the feature's own.
            paise = price(provider, model, usage, 0)
            if paise is None and provider == "gemini":
                paise = price("gemini", FALLBACK_MODEL, usage, 0)
            cost = row.get("cost_inr")
            if paise is None and isinstance(cost, (int, float)) and not isinstance(cost, bool):
                paise = round(cost * 100)
        export.steps.append(
            Step(
                environment=environment,
                call=_text(row.get("call")),
                company=_text(row.get("company")),
                stage=stage,
                provider=provider,
                model=model,
                status=status,
                attempts=1,
                input_tokens=usage["promptTokenCount"],
                output_tokens=usage["candidatesTokenCount"],
                audio_ms=0,
                elapsed_ms=None,
                paise=paise,
                at=at,
                person=_person(row.get("person")),
            )
        )
    # A call's steps belong to the person whose call it is.
    owner = {call.id: call.person for call in export.calls if call.person}
    export.steps = [
        step if step.person or not step.call else replace(step, person=owner.get(step.call))
        for step in export.steps
    ]
    export.holds = list(_rows(document, "holds"))
    export.budgets = list(_rows(document, "budgets"))
    export.payments = list(_rows(document, "payments"))
    export.subscriptions = list(_rows(document, "subscriptions"))
    export.waiting_calls = _int(document.get("waiting_calls"))
    for row in _rows(document, "synthetic_calls"):
        if (day := _text(row.get("day"))) is not None:
            export.synthetic[day] = _int(row.get("n"))
    return export


def read_store(root: str | None) -> tuple[list[Export], list[dict[str, str]]]:
    """Every environment export under ``root``; a missing or broken file is reported, not raised."""

    exports: list[Export] = []
    problems: list[dict[str, str]] = []
    if not root:
        return exports, [{"environment": "all", "problem": "not_configured"}]
    for environment in ENVIRONMENTS:
        path = os.path.join(root, environment, "usage.json")
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                problems.append({"environment": environment, "problem": "too_large"})
                continue
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except FileNotFoundError:
            continue  # this Admin is not given that environment
        except (OSError, ValueError):
            problems.append({"environment": environment, "problem": "unreadable"})
            continue
        if not isinstance(document, dict):
            problems.append({"environment": environment, "problem": "unreadable"})
            continue
        try:
            exports.append(parse_export(environment, document))
        except ValueError as error:
            problems.append({"environment": environment, "problem": str(error)})
    return dedupe(exports), problems


def dedupe(exports: Sequence[Export]) -> list[Export]:
    """Count copied rows once, in the most upstream environment that has them."""

    ordered = sorted(exports, key=lambda item: ENVIRONMENTS.index(item.environment))
    seen_steps: set[tuple[str | None, str, str]] = set()
    seen_calls: set[str] = set()
    seen_scopes: set[str] = set()
    seen_payments: set[tuple[Any, ...]] = set()
    seen_synthetic: Counter[str] = Counter()
    for export in ordered:
        before = len(export.steps) + len(export.calls)
        steps = [
            step
            for step in export.steps
            if (step.call, step.stage, step.at.isoformat()) not in seen_steps
        ]
        own_calls = {step.call for step in steps}
        calls = [call for call in export.calls if call.id not in seen_calls or call.id in own_calls]
        export.copies_dropped = before - len(steps) - len(calls)
        seen_steps.update((step.call, step.stage, step.at.isoformat()) for step in export.steps)
        seen_calls.update(call.id for call in export.calls)
        export.steps, export.calls = steps, calls
        scopes = {_text(row.get("scope")) for row in export.budgets}
        export.holds = [row for row in export.holds if _text(row.get("scope")) not in seen_scopes]
        export.budgets = [
            row for row in export.budgets if _text(row.get("scope")) not in seen_scopes
        ]
        seen_scopes.update(scope for scope in scopes if scope)
        payments = []
        for row in export.payments:
            key = tuple(row.get(name) for name in ("company", "day", "kind", "amount_minor", "n"))
            if key not in seen_payments:
                payments.append(row)
            seen_payments.add(key)
        export.payments = payments
        for day, count in list(export.synthetic.items()):
            export.synthetic[day] = max(0, count - seen_synthetic[day])
            seen_synthetic[day] = max(seen_synthetic[day], count)
    return list(ordered)


# ---------- building the views ----------


def india_day(moment: datetime) -> date:
    return moment.astimezone(INDIA).date()


def _rupees(paise: int | float | None) -> float | None:
    return None if paise is None else round(paise / 100, 2)


def _minutes(ms: int | float) -> float:
    return round(ms / 60_000, 2)


def _per_minute(paise: int, audio_ms: int) -> float | None:
    return None if audio_ms <= 0 else round(paise / 100 / (audio_ms / 60_000), 3)


def _median(values: Iterable[float]) -> int | None:
    items = list(values)
    return round(median(items)) if items else None


def _p90(values: Iterable[float]) -> int | None:
    items = sorted(values)
    if not items:
        return None
    return round(items[min(len(items) - 1, round(0.9 * (len(items) - 1)))])


def version_label(version: Sequence[str | None]) -> str:
    prompt, facts, report_model, transcription_model, _settings = version
    if not any(version):
        return "Not recorded (older calls)"
    parts = [prompt or "coaching ?", facts or "facts ?", report_model or "model ?"]
    if transcription_model:
        parts.append(transcription_model)
    return " · ".join(parts)


def version_id(version: Sequence[str | None]) -> str:
    return hashlib.sha256("|".join(item or "" for item in version).encode()).hexdigest()[:10]


@dataclass(frozen=True)
class Scope:
    now: datetime
    days: int
    environment: str
    tests: bool
    # The Per call tab: its order, and whether each call carries its steps.
    call_sort: str = "newest"
    call_steps: bool = False
    # Usage filters (owner, 20 Oct 2026): one organisation, one feature (stage).
    company: str | None = None
    stage: str | None = None
    # One person (a pseudonym from the people filter).
    person: str | None = None

    @property
    def since(self) -> datetime:
        return self.now - timedelta(days=self.days)


def _step_view(step: Step) -> dict[str, Any]:
    """One provider step of a call: what ran, how, and what it cost (numbers only)."""

    return {
        "stage": step.stage,
        "provider": step.provider,
        "model": step.model,
        "status": step.status,
        "attempts": step.attempts,
        "input_tokens": step.input_tokens,
        "output_tokens": step.output_tokens,
        "audio_minutes": _minutes(step.audio_ms) if step.audio_ms else None,
        "elapsed_ms": step.elapsed_ms,
        "rupees": None if step.paise is None else _rupees(step.paise),
        "at": step.at.isoformat(),
    }


def _company(
    exports: Mapping[str, Export], environment: str, company: str | None
) -> dict[str, str]:
    known = exports[environment].companies.get(company or "") if environment in exports else None
    if known and known["kind"] == "personal":
        return {"id": company or "", "name": "Personal accounts", "kind": "personal"}
    name = known.get("name") if known else None
    return {
        "id": company or "",
        # Names never sit in the shared store: other environments show the id's start.
        "name": name or (f"Organisation {company[:8]}" if company else "Unknown"),
        "kind": (known.get("kind") if known else None) or "other",
    }


def _narrow(
    export: Export, company: str | None, stage: str | None, person: str | None = None
) -> Export:
    """One organisation's, one feature's and/or one person's rows only (the Usage filters)."""

    steps = [
        step
        for step in export.steps
        if (company is None or step.company == company)
        and (stage is None or step.stage == stage)
        and (person is None or step.person == person)
    ]
    kept = {step.call for step in steps}
    return replace(
        export,
        steps=steps,
        calls=[
            call
            for call in export.calls
            if (company is None or call.company == company)
            and (stage is None or call.id in kept)
            and (person is None or call.person == person)
        ],
        payments=[
            row
            for row in export.payments
            if company is None or _text(row.get("company")) == company
        ],
        subscriptions=[
            row
            for row in export.subscriptions
            if company is None or _text(row.get("company")) == company
        ],
    )


def _choices(
    exports: Sequence[Export], by_env: Mapping[str, Export], scope: Scope
) -> dict[str, Any]:
    """What the filters offer: organisations with spend in the window (most first) and the
    features that ran, so a choice never shows an empty page."""

    spend: Counter[tuple[str, str]] = Counter()
    people: Counter[tuple[str, str]] = Counter()
    stages: set[str] = set()
    for export in exports:
        for step in export.steps:
            if step.at < scope.since:
                continue
            stages.add(step.stage)
            if step.company:
                spend[(export.environment, step.company)] += step.paise or 0
            if step.person:
                people[(export.environment, step.person)] += step.paise or 0
    companies: dict[str, dict[str, Any]] = {}
    for (environment, company), paise in spend.most_common():
        row = companies.setdefault(
            company, {**_company(by_env, environment, company), "rupees": 0.0}
        )
        row["rupees"] = round(row["rupees"] + paise / 100, 2)
        row.setdefault("environment", environment)
    return {
        "companies": list(companies.values())[:MAX_COMPANIES],
        # Who spent most: pseudonyms, named only for this Admin's own environment.
        "people": [
            {
                "id": person,
                "environment": environment,
                "name": by_env[environment].people.get(person) if environment in by_env else None,
                "rupees": round(paise / 100, 2),
            }
            for (environment, person), paise in people.most_common(MAX_COMPANIES)
        ],
        "people_available": sorted(
            {export.environment for export in exports if any(c.person for c in export.calls)}
        ),
        "stages": [
            {"stage": stage, "label": STAGE_LABELS.get(stage, stage)}
            for stage in sorted(
                stages,
                key=lambda item: list(STAGE_LABELS).index(item) if item in STAGE_LABELS else 99,
            )
            if stage != "C1"
        ],
    }


def _rate(value: Any) -> float | None:
    return None if value is None else float(value)


def _routes(steps: Iterable[Step]) -> list[dict[str, Any]]:
    """What each feature ran on in each environment (its newest run), how many runs used that
    provider and model in the window, and the price sheet's unit price in dollars. What ran,
    not what is set: a change shows here once it has run."""

    newest: dict[tuple[str, str], Step] = {}
    runs: Counter[tuple[str, str, str | None, str | None]] = Counter()
    for step in steps:
        if step.provider in (None, "local"):
            continue
        key = (step.environment, step.stage)
        if key not in newest or step.at > newest[key].at:
            newest[key] = step
        runs[(step.environment, step.stage, step.provider, step.model)] += 1
    order = list(STAGE_LABELS)

    def place(key: tuple[str, str]) -> tuple[int, int]:
        environment, stage = key
        return (
            ENVIRONMENTS.index(environment) if environment in ENVIRONMENTS else 9,
            order.index(stage) if stage in order else 99,
        )

    rows: list[dict[str, Any]] = []
    for key in sorted(newest, key=place):
        step = newest[key]
        snapshot = PRICING_SNAPSHOTS.get((step.provider or "", step.model or ""))
        rows.append(
            {
                "environment": key[0],
                "stage": key[1],
                "label": STAGE_LABELS.get(key[1], key[1]),
                "provider": step.provider,
                "model": step.model,
                "runs": runs[(key[0], key[1], step.provider, step.model)],
                "last_at": step.at.isoformat(),
                "unit": None
                if snapshot is None
                else {
                    "basis": snapshot.rate_basis,
                    "usd_per_hour": _rate(snapshot.usd_per_hour),
                    "usd_per_minute": _rate(snapshot.usd_per_minute),
                    "input_usd_per_million": _rate(snapshot.input_usd_per_million_tokens),
                    "output_usd_per_million": _rate(snapshot.output_usd_per_million_tokens),
                },
            }
        )
    return rows


def at_daily_rates(
    exports: Sequence[Export], rates: Mapping[date, Decimal], since: datetime | None = None
) -> tuple[list[Export], dict[str, Any]]:
    """Provider costs at each day's reference rate instead of the planning rate.

    Only provider steps move: they are dollars converted at the planning rate, so each is
    rescaled by its India day's rate (that day's, else the latest earlier one). Revenue,
    payments and budget caps are rupees already and stay as they are. Dollars stay exact
    through the window's average rate, which the page divides by."""
    if not rates:
        return list(exports), dict(FX)
    planning = Decimal(FX_USD_TO_INR)
    before = after = Decimal(0)
    unrated = 0
    moved: list[Export] = []
    for export in exports:
        steps = []
        for step in export.steps:
            if step.paise is None:
                steps.append(step)
                continue
            found = rate_on(rates, india_day(step.at))
            if found is None:
                unrated += 1
                steps.append(step)
                continue
            exact = Decimal(step.paise) * found[1] / planning
            if since is None or step.at >= since:
                # The average comes from unrounded rupees, so dollars stay exact.
                before += step.paise
                after += exact
            steps.append(replace(step, paise=round(exact)))
        moved.append(replace(export, steps=steps))
    latest_day = max(rates)
    latest = rates[latest_day]
    average = (after / before * planning) if before else latest
    return moved, {
        "currency": "USD",
        "mode": "daily",
        "usd_to_inr": float(average.quantize(Decimal("0.01"))),
        "set_on": latest_day.isoformat(),
        "planning_usd_to_inr": float(planning),
        "latest": {"day": latest_day.isoformat(), "usd_to_inr": float(latest)},
        "unrated_steps": unrated,
        "problem": None,
        "source": "ECB euro reference rates: each day's costs at that day's rate, dollars at"
        " this window's average.",
    }


def build_metrics(exports: Sequence[Export], scope: Scope) -> dict[str, Any]:
    by_env = {export.environment: export for export in exports}
    chosen = [
        export
        for export in exports
        if scope.environment == "all" or export.environment == scope.environment
    ]
    choices = _choices(chosen, by_env, scope)
    if scope.company is not None or scope.stage is not None or scope.person is not None:
        chosen = [_narrow(export, scope.company, scope.stage, scope.person) for export in chosen]
    calls = {(call.environment, call.id): call for export in chosen for call in export.calls}

    def kind_of(step: Step) -> str:
        call = calls.get((step.environment, step.call or ""))
        return call.kind if call else "real"

    def counted(kind: str) -> bool:
        return scope.tests or kind not in TEST_KINDS

    all_steps = [step for export in chosen for step in export.steps]
    window_steps = [step for step in all_steps if step.at >= scope.since]
    steps = [step for step in window_steps if counted(kind_of(step))]
    test_steps = [step for step in window_steps if kind_of(step) in TEST_KINDS]
    today = india_day(scope.now)
    month = (today.year, today.month)

    def spend(items: Iterable[Step]) -> int:
        return sum(step.paise or 0 for step in items)

    def audio(items: Iterable[Step]) -> int:
        return sum(
            step.audio_ms for step in items if step.stage == "C2" and step.status == "succeeded"
        )

    # ---- overview ----
    month_steps = [
        step
        for step in all_steps
        if counted(kind_of(step)) and (india_day(step.at).year, india_day(step.at).month) == month
    ]
    today_steps = [step for step in month_steps if india_day(step.at) == today]
    step_calls = {(step.environment, step.call) for step in steps}
    window_calls = [
        call
        for call in calls.values()
        if counted(call.kind) and (call.environment, call.id) in step_calls
    ]
    delivered = [
        call
        for call in window_calls
        if call.report_at is not None and call.report_at >= scope.since
    ]
    turnaround = [
        (call.report_at - call.at).total_seconds() * 1000
        for call in delivered
        if call.report_at and call.report_at >= call.at
    ]
    environments: list[dict[str, Any]] = []
    for export in chosen:
        mine = [step for step in steps if step.environment == export.environment]
        mine_month = [step for step in month_steps if step.environment == export.environment]
        mine_tests = [step for step in test_steps if step.environment == export.environment]
        env_calls = [call for call in window_calls if call.environment == export.environment]
        env_delivered = [call for call in delivered if call.environment == export.environment]
        env_turn = [
            (call.report_at - call.at).total_seconds() * 1000
            for call in env_delivered
            if call.report_at and call.report_at >= call.at
        ]
        environments.append(
            {
                "environment": export.environment,
                "today": _rupees(spend(s for s in mine_month if india_day(s.at) == today)),
                "month": _rupees(spend(mine_month)),
                "window": _rupees(spend(mine)),
                "tests": _rupees(spend(mine_tests)),
                "test_runs": len({s.call for s in mine_tests if s.stage == "C2"}),
                "calls": len(env_calls),
                "reports": len(env_delivered),
                "audio_minutes": _minutes(audio(mine)),
                "per_minute": _per_minute(spend(mine), audio(mine)),
                "billed_minutes": _minutes(sum(call.billed_s for call in env_delivered) * 1000),
                "report_p50_ms": _median(env_turn),
            }
        )
    # Cost per audio minute by the day each call was first transcribed: every step of
    # that call counts there (a later pointer-review backfill doesn't spike another
    # day), and a repeat transcription raises that call's cost, not its minutes.
    call_cost: Counter[tuple[str, str | None]] = Counter()
    first_c2: dict[tuple[str, str | None], Step] = {}
    for step in all_steps:
        if not counted(kind_of(step)):
            continue
        key = (step.environment, step.call)
        call_cost[key] += step.paise or 0
        if (
            step.stage == "C2"
            and step.status == "succeeded"
            and (key not in first_c2 or step.at < first_c2[key].at)
        ):
            first_c2[key] = step
    cohort_paise: dict[str, Counter[date]] = defaultdict(Counter)
    cohort_audio: dict[str, Counter[date]] = defaultdict(Counter)
    for key, first in first_c2.items():
        cohort_paise[key[0]][india_day(first.at)] += call_cost[key]
        cohort_audio[key[0]][india_day(first.at)] += first.audio_ms

    def cohort(environments: Iterable[str], span: Iterable[date]) -> float | None:
        wanted = list(span)
        paise = sum(cohort_paise[env][day] for env in environments for day in wanted)
        audio_ms = sum(cohort_audio[env][day] for env in environments for day in wanted)
        return _per_minute(paise, audio_ms)

    # Daily trend in India time, every day of the window so the bars add up.
    first_day = india_day(scope.since)
    days = [first_day + timedelta(days=offset) for offset in range((today - first_day).days + 1)]
    daily_spend: dict[date, Counter[str]] = defaultdict(Counter)
    daily_audio: Counter[date] = Counter()
    daily_calls: dict[date, set[tuple[str, str | None]]] = defaultdict(set)
    for step in steps:
        day = india_day(step.at)
        daily_spend[day][step.environment] += step.paise or 0
        if step.stage == "C2" and step.status == "succeeded":
            daily_audio[day] += step.audio_ms
            daily_calls[day].add((step.environment, step.call))
    daily = [
        {
            "day": day.isoformat(),
            "by_environment": {env: _rupees(paise) for env, paise in daily_spend[day].items()},
            "spend": _rupees(sum(daily_spend[day].values())),
            "audio_minutes": _minutes(daily_audio[day]),
            "per_minute": cohort([export.environment for export in chosen], [day]),
            "calls": len(daily_calls[day]),
        }
        for day in days
    ]
    stage_spend: Counter[str] = Counter()
    stage_tokens: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for step in steps:
        stage_spend[step.stage] += step.paise or 0
        tally = stage_tokens[step.stage]
        tally[0] += step.input_tokens
        tally[1] += step.output_tokens
        tally[2] += step.audio_ms if step.status == "succeeded" else 0
    total = spend(steps)
    for env_row in environments:
        env_row["per_minute"] = cohort([env_row["environment"]], days)
    overview = {
        "spend_today": _rupees(spend(today_steps)),
        "spend_month": _rupees(spend(month_steps)),
        "spend_window": _rupees(total),
        "tests_window": _rupees(spend(test_steps)),
        "test_runs": len({(s.environment, s.call) for s in test_steps if s.stage == "C2"}),
        "calls": len(window_calls),
        "reports": len(delivered),
        "audio_minutes": _minutes(audio(steps)),
        "per_minute": cohort([export.environment for export in chosen], days),
        "billed_minutes": _minutes(sum(call.billed_s for call in delivered) * 1000),
        "report_p50_ms": _median(turnaround),
        "report_p90_ms": _p90(turnaround),
        "unpriced_steps": sum(
            1 for step in steps if step.paise is None and step.status == "succeeded"
        ),
        "environments": environments,
        "daily": daily,
        "by_stage": [
            {
                "stage": stage,
                "label": STAGE_LABELS.get(stage, stage),
                "rupees": _rupees(paise),
                "share": round(paise / total, 3) if total else 0,
                "per_minute": _per_minute(paise, audio(steps)),
                # Transcription is audio minutes; model steps are input and output tokens.
                "input_tokens": stage_tokens[stage][0],
                "output_tokens": stage_tokens[stage][1],
                "audio_minutes": _minutes(stage_tokens[stage][2]),
            }
            for stage, paise in sorted(stage_spend.items(), key=lambda item: -item[1])
            if stage != "C1"
        ],
    }

    # ---- providers ----
    provider_rows: dict[tuple[str, str], dict[str, Any]] = {}
    provider_daily: dict[tuple[str, str, str], dict[str, Any]] = {}
    for step in steps:
        if step.provider in (None, "local"):
            continue
        key = (step.provider or "?", step.model or "?")
        row = provider_rows.setdefault(
            key,
            {
                "provider": key[0],
                "model": key[1],
                "stages": set(),
                "steps": 0,
                "failed": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "audio_ms": 0,
                "paise": 0,
                "calls": set(),
            },
        )
        row["stages"].add(step.stage)
        row["steps"] += 1
        row["failed"] += step.status == "dead_letter"
        row["input_tokens"] += step.input_tokens
        row["output_tokens"] += step.output_tokens
        row["audio_ms"] += step.audio_ms
        row["paise"] += step.paise or 0
        row["calls"].add((step.environment, step.call))
        day_key = (india_day(step.at).isoformat(), *key)
        day_row = provider_daily.setdefault(
            day_key,
            {
                "day": day_key[0],
                "provider": key[0],
                "model": key[1],
                "input_tokens": 0,
                "output_tokens": 0,
                "audio_ms": 0,
                "paise": 0,
            },
        )
        for name in ("input_tokens", "output_tokens", "audio_ms"):
            day_row[name] += getattr(step, name)
        day_row["paise"] += step.paise or 0
    providers = {
        "models": [
            {
                "provider": row["provider"],
                "model": row["model"],
                "stages": sorted(row["stages"]),
                "calls": len(row["calls"]),
                "steps": row["steps"],
                "failed": row["failed"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "audio_minutes": _minutes(row["audio_ms"]),
                "rupees": _rupees(row["paise"]),
                "share": round(row["paise"] / total, 3) if total else 0,
            }
            for row in sorted(provider_rows.values(), key=lambda item: -item["paise"])
        ],
        "daily": [
            {
                **row,
                "audio_minutes": _minutes(row.pop("audio_ms")),
                "rupees": _rupees(row.pop("paise")),
            }
            for _key, row in sorted(provider_daily.items(), reverse=True)
        ],
    }

    # ---- per call ----
    revenue_per_minute = _revenue_per_minute(chosen)
    per_call: dict[tuple[str, str | None], list[Step]] = defaultdict(list)
    for step in window_steps:
        per_call[(step.environment, step.call)].append(step)
    call_rows: list[dict[str, Any]] = []
    for call in sorted(
        (
            call
            for call in calls.values()
            if counted(call.kind) and (call.environment, call.id) in per_call
        ),
        key=lambda item: item.at,
        reverse=True,
    ):
        mine = per_call[(call.environment, call.id)]
        by_stage: dict[str, dict[str, Any]] = {}
        for step in mine:
            row = by_stage.setdefault(
                step.stage,
                {"input_tokens": 0, "output_tokens": 0, "paise": 0, "runs": 0, "failed": 0},
            )
            row["input_tokens"] += step.input_tokens
            row["output_tokens"] += step.output_tokens
            row["paise"] += step.paise or 0
            row["runs"] += 1
            row["failed"] += step.status == "dead_letter"
        cost = spend(mine)
        statuses = Counter(step.status for step in mine)
        models = sorted({step.model for step in mine if step.model})
        rate = revenue_per_minute.get((call.environment, call.company or ""))
        revenue = None if rate is None else round(rate * call.billed_s / 60, 2)
        company = _company(by_env, call.environment, call.company)
        call_rows.append(
            {
                "environment": call.environment,
                "id": call.id,
                "company": company["name"],
                "company_kind": company["kind"],
                "kind": call.kind,
                "at": call.at.isoformat(),
                "audio_minutes": _minutes(call.audio_ms),
                "stages": {
                    stage: {
                        "input_tokens": row["input_tokens"],
                        "output_tokens": row["output_tokens"],
                        "rupees": _rupees(row["paise"]),
                        "runs": row["runs"],
                        "failed": row["failed"],
                    }
                    for stage, row in by_stage.items()
                },
                "rupees": _rupees(cost),
                "per_minute": _per_minute(cost, call.audio_ms),
                "billed_minutes": _minutes(call.billed_s * 1000),
                "report": call.report_at is not None,
                "report_ms": None
                if not (call.report_at and call.report_at >= call.at)
                else round((call.report_at - call.at).total_seconds() * 1000),
                "version": version_label(call.version),
                "revenue": revenue,
                "margin": None if revenue is None else round(revenue - cost / 100, 2),
                "tokens": sum(step.input_tokens + step.output_tokens for step in mine),
                "models": models,
                "statuses": dict(statuses),
                **({"steps": [_step_view(step) for step in mine]} if scope.call_steps else {}),
            }
        )
    paid_calls = [row for row in call_rows if row["rupees"] > 0]
    zero_calls = [row for row in call_rows if row["rupees"] <= 0]
    if scope.call_sort != "newest":
        field = {"cost": "rupees", "per_minute": "per_minute", "audio": "audio_minutes"}.get(
            scope.call_sort, "tokens"
        )
        paid_calls.sort(key=lambda row: row[field] or 0, reverse=True)

    # ---- revenue against cost, per company ----
    revenue_rows = _revenue_rows(chosen, by_env, steps, calls, scope)

    # ---- pipelines ----
    pipelines = _pipelines(chosen, window_steps, calls, scope)

    # ---- money health ----
    money = _money(chosen, scope)

    # ---- ideas: what makes cost obvious ----
    ideas = _ideas(steps, window_steps, calls, by_env, delivered, total, test_steps, kind_of)

    return {
        "schema": "ac.sales-xray.admin-metrics/1",
        "window": {
            "days": scope.days,
            "since": scope.since.isoformat(),
            "timezone": "Asia/Kolkata",
        },
        "environment": scope.environment,
        "tests": scope.tests,
        "fx": FX,
        "filters": {"company": scope.company, "stage": scope.stage, "person": scope.person},
        "routes": _routes(window_steps),
        "choices": choices,
        "sources": [
            {
                "environment": export.environment,
                "generated_at": None
                if export.generated_at is None
                else export.generated_at.isoformat(),
                "stale": export.generated_at is None
                or scope.now - export.generated_at > STALE_AFTER,
                "migration": export.migration,
                "window_days": export.window_days,
                "calls": len(export.calls),
                "steps": len(export.steps),
                "copies_counted_upstream": export.copies_dropped,
                "synthetic_calls": sum(
                    count
                    for day, count in export.synthetic.items()
                    if day >= scope.since.date().isoformat()
                ),
            }
            for export in exports
        ],
        "overview": overview,
        "providers": providers,
        "calls": {
            "rows": paid_calls[:MAX_CALLS],
            "total": len(paid_calls),
            "sort": scope.call_sort,
            "zero_rows": zero_calls[:MAX_ZERO_CALLS],
            "zero_total": len(zero_calls),
        },
        "revenue": revenue_rows,
        "pipelines": pipelines,
        "money": money,
        "ideas": ideas,
    }


def _revenue_per_minute(exports: Sequence[Export]) -> dict[tuple[str, str], float]:
    """Rupees per included minute of each company's newest live plan, if it has one."""

    rates: dict[tuple[str, str], float] = {}
    for export in exports:
        for row in sorted(export.subscriptions, key=lambda item: str(item.get("at"))):
            company = _text(row.get("company"))
            minutes = _int(row.get("included_minutes"))
            amount = _int(row.get("amount_minor"))
            if company and minutes and amount and row.get("mode") != "test":
                rates[(export.environment, company)] = amount / 100 / minutes
    return rates


def _revenue_rows(
    exports: Sequence[Export],
    by_env: Mapping[str, Export],
    steps: Sequence[Step],
    calls: Mapping[tuple[str, str], Call],
    scope: Scope,
) -> dict[str, Any]:
    since_day = india_day(scope.since).isoformat()
    rows: dict[tuple[str, str], dict[str, Any]] = {}

    def row_for(environment: str, company: str | None) -> dict[str, Any]:
        key = (environment, company or "")
        if key not in rows:
            info = _company(by_env, environment, company)
            rows[key] = {
                "environment": environment,
                "company": info["name"],
                "company_kind": info["kind"],
                "revenue_minor": 0,
                "test_revenue_minor": 0,
                "refunds_minor": 0,
                "cost_paise": 0,
                "calls": set(),
                "billed_s": 0,
                "plan": None,
            }
        return rows[key]

    for export in exports:
        for payment in export.payments:
            if str(payment.get("day") or "") < since_day:
                continue
            row = row_for(export.environment, _text(payment.get("company")))
            amount = _int(payment.get("amount_minor"))
            if payment.get("kind") == "refund.processed":
                row["refunds_minor"] += amount
            elif payment.get("mode") == "test":
                row["test_revenue_minor"] += amount
            else:
                row["revenue_minor"] += amount
        for subscription in export.subscriptions:
            row = row_for(export.environment, _text(subscription.get("company")))
            row["plan"] = {
                "name": _text(subscription.get("plan")),
                "interval": _text(subscription.get("interval")),
                "rupees": _rupees(_int(subscription.get("amount_minor"))),
                "seats": _int(subscription.get("seats")),
                "included_minutes": _int(subscription.get("included_minutes")),
                "mode": _text(subscription.get("mode")),
            }
    for step in steps:
        row = row_for(step.environment, step.company)
        row["cost_paise"] += step.paise or 0
        row["calls"].add(step.call)
    for call in calls.values():
        if (
            call.report_at is not None
            and call.report_at >= scope.since
            and (scope.tests or call.kind not in TEST_KINDS)
            and (call.environment, call.company or "") in rows
        ):
            rows[(call.environment, call.company or "")]["billed_s"] += call.billed_s
    out = []
    for row in rows.values():
        revenue = (row["revenue_minor"] - row["refunds_minor"]) / 100
        cost = row["cost_paise"] / 100
        out.append(
            {
                **{
                    k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "calls",
                        "cost_paise",
                        "revenue_minor",
                        "test_revenue_minor",
                        "refunds_minor",
                        "billed_s",
                    }
                },
                "revenue": round(revenue, 2),
                "test_revenue": round(row["test_revenue_minor"] / 100, 2),
                "cost": round(cost, 2),
                "margin": round(revenue - cost, 2),
                "calls": len(row["calls"] - {None}),
                "billed_minutes": _minutes(row["billed_s"] * 1000),
                "cost_per_billed_minute": None
                if not row["billed_s"]
                else round(cost / (row["billed_s"] / 60), 2),
            }
        )
    out.sort(
        key=lambda item: (ENVIRONMENTS.index(item["environment"]), -item["revenue"], -item["cost"])
    )
    totals = {
        environment: {
            "revenue": round(sum(r["revenue"] for r in out if r["environment"] == environment), 2),
            "cost": round(sum(r["cost"] for r in out if r["environment"] == environment), 2),
        }
        for environment in {row["environment"] for row in out}
    }
    for value in totals.values():
        value["margin"] = round(value["revenue"] - value["cost"], 2)
    return {
        "rows": out,
        "totals": totals,
        "payments_recorded": sum(len(export.payments) for export in exports),
        "plans_recorded": sum(len(export.subscriptions) for export in exports),
    }


def _pipelines(
    exports: Sequence[Export],
    steps: Sequence[Step],
    calls: Mapping[tuple[str, str], Call],
    scope: Scope,
) -> list[dict[str, Any]]:
    """Per pipeline version: cost, time per stage, failure rate, gold agreement, test runs."""

    groups: dict[Version, dict[str, Any]] = {}
    for step in steps:
        call = calls.get((step.environment, step.call or ""))
        version: Version = call.version if call else (None, None, None, None, None)
        group = groups.setdefault(
            version,
            {
                "calls": set(),
                "tests": set(),
                "steps": 0,
                "failed": 0,
                "retried": 0,
                "paise": 0,
                "audio_ms": 0,
                "elapsed": defaultdict(list),
                "environments": set(),
                "first": step.at,
                "last": step.at,
                "report_ms": [],
                "gold": [0, 0, 0],
                "gold_calls": set(),
            },
        )
        key = (step.environment, step.call)
        group["environments"].add(step.environment)
        group["first"] = min(group["first"], step.at)
        group["last"] = max(group["last"], step.at)
        if call is not None and call.kind in TEST_KINDS:
            group["tests"].add(key)
            if not scope.tests:
                continue
        group["calls"].add(key)
        group["steps"] += 1
        group["failed"] += step.status == "dead_letter"
        group["retried"] += step.attempts > 1
        group["paise"] += step.paise or 0
        if step.stage == "C2" and step.status == "succeeded":
            group["audio_ms"] += step.audio_ms
        if step.elapsed_ms is not None:
            group["elapsed"][step.stage].append(step.elapsed_ms)
        if call is not None and key not in group["gold_calls"]:
            group["gold_calls"].add(key)
            for index in range(3):
                group["gold"][index] += call.gold[index]
            if call.report_at and call.report_at >= call.at:
                group["report_ms"].append((call.report_at - call.at).total_seconds() * 1000)
    rows = []
    for version, group in groups.items():
        agree, partly, disagree = group["gold"]
        reviewed = agree + partly + disagree
        rows.append(
            {
                "id": version_id(version),
                "label": version_label(version),
                "prompt": version[0],
                "facts": version[1],
                "report_model": version[2],
                "transcription_model": version[3],
                "settings": version[4],
                "environments": sorted(group["environments"], key=ENVIRONMENTS.index),
                "first_seen": group["first"].isoformat(),
                "last_seen": group["last"].isoformat(),
                "calls": len(group["calls"]),
                "test_runs": len(group["tests"]),
                "steps": group["steps"],
                "failure_rate": round(group["failed"] / group["steps"], 3)
                if group["steps"]
                else None,
                "retry_rate": round(group["retried"] / group["steps"], 3)
                if group["steps"]
                else None,
                "rupees": _rupees(group["paise"]),
                "per_minute": _per_minute(group["paise"], group["audio_ms"]),
                "audio_minutes": _minutes(group["audio_ms"]),
                "stage_ms": {
                    stage: _median(values) for stage, values in sorted(group["elapsed"].items())
                },
                "report_p50_ms": _median(group["report_ms"]),
                "gold": {
                    "reviewed": reviewed,
                    "agree": agree,
                    "partly": partly,
                    "disagree": disagree,
                    "agreement": None
                    if not reviewed
                    else round((agree + partly / 2) / reviewed, 3),
                },
            }
        )
    rows.sort(key=lambda row: row["last_seen"], reverse=True)
    return rows


def _money(exports: Sequence[Export], scope: Scope) -> dict[str, Any]:
    """Budget holds per environment: open, settled, and the last two weeks of open ones."""

    recent_day = (india_day(scope.now) - timedelta(days=14)).isoformat()
    environments = []
    for export in exports:
        cap = sum(_int(row.get("cap_paise")) for row in export.budgets)
        used = sum(_int(row.get("committed_paise")) for row in export.budgets)
        periods = {_text(row.get("period")) or "lifetime" for row in export.budgets}
        open_rows = [row for row in export.holds if row.get("state") == "uncertain"]
        by_ref: Counter[str] = Counter()
        by_ref_paise: Counter[str] = Counter()
        by_kind: Counter[str] = Counter()
        for row in open_rows:
            ref = _text(row.get("ref")) or "unknown"
            by_ref[ref] += _int(row.get("n"))
            by_ref_paise[ref] += _int(row.get("held_paise"))
            by_kind[_text(row.get("kind")) or "real"] += _int(row.get("n"))
        recent: dict[str, dict[str, int]] = defaultdict(
            lambda: {"n": 0, "held_paise": 0, "canary": 0}
        )
        for row in open_rows:
            day = str(row.get("day") or "")
            if day >= recent_day:
                recent[day]["n"] += _int(row.get("n"))
                recent[day]["held_paise"] += _int(row.get("held_paise"))
                if row.get("kind") in TEST_KINDS:
                    recent[day]["canary"] += _int(row.get("n"))
        settled = [row for row in export.holds if row.get("state") == "settled"]
        open_paise = sum(_int(row.get("held_paise")) for row in open_rows)
        environments.append(
            {
                "environment": export.environment,
                "cap": _rupees(cap) if cap else None,
                "open": sum(_int(row.get("n")) for row in open_rows),
                "open_rupees": _rupees(open_paise),
                "cap_share": round(open_paise / cap, 3) if cap else None,
                "used_rupees": _rupees(used),
                "used_share": round(used / cap, 3) if cap else None,
                "waiting_calls": export.waiting_calls,
                "period": periods.pop() if len(periods) == 1 else "lifetime",
                "settled": sum(_int(row.get("n")) for row in settled),
                "settled_rupees": _rupees(sum(_int(row.get("settled_paise")) for row in settled)),
                "by_reason": [
                    {
                        "ref": ref,
                        "label": HOLD_REFS.get(ref, ref),
                        "n": n,
                        "rupees": _rupees(by_ref_paise[ref]),
                    }
                    for ref, n in by_ref.most_common()
                ],
                "by_kind": dict(by_kind),
                "recent": [
                    {
                        "day": day,
                        **{k: (_rupees(v) if k == "held_paise" else v) for k, v in value.items()},
                    }
                    for day, value in sorted(recent.items(), reverse=True)
                ],
            }
        )
    return {"environments": environments, "finding": HOLD_FINDING}


def _ideas(
    steps: Sequence[Step],
    window_steps: Sequence[Step],
    calls: Mapping[tuple[str, str], Call],
    by_env: Mapping[str, Export],
    delivered: Sequence[Call],
    total: int,
    test_steps: Sequence[Step],
    kind_of: Any,
) -> dict[str, Any]:
    company_spend: Counter[tuple[str, str | None]] = Counter()
    company_calls: dict[tuple[str, str | None], set[str | None]] = defaultdict(set)
    call_spend: Counter[tuple[str, str | None]] = Counter()
    # Each call's successful transcriptions in order; every one after the first is a repeat.
    transcriptions: dict[tuple[str, str | None], list[int]] = defaultdict(list)
    failed_paise = 0
    for step in sorted(steps, key=lambda item: item.at):
        company_spend[(step.environment, step.company)] += step.paise or 0
        company_calls[(step.environment, step.company)].add(step.call)
        call_spend[(step.environment, step.call)] += step.paise or 0
        if step.status == "dead_letter":
            failed_paise += step.paise or 0
        if step.stage == "C2" and step.status == "succeeded":
            transcriptions[(step.environment, step.call)].append(step.paise or 0)
    repeats = [paise[1:] for paise in transcriptions.values() if len(paise) > 1]
    repeat_paise = sum(sum(extra) for extra in repeats)
    no_report = [
        key
        for key in call_spend
        if (call := calls.get((key[0], key[1] or ""))) is not None and call.report_at is None
    ]
    no_report_paise = sum(call_spend[key] for key in no_report)

    def company_row(key: tuple[str, str | None]) -> dict[str, Any]:
        info = _company(by_env, key[0], key[1])
        paise = company_spend[key]
        return {
            "environment": key[0],
            "company": info["name"],
            "company_kind": info["kind"],
            "rupees": _rupees(paise),
            "calls": len(company_calls[key] - {None}),
            "per_call": _rupees(paise / max(1, len(company_calls[key] - {None}))),
        }

    def call_row(key: tuple[str, str | None]) -> dict[str, Any]:
        call = calls.get((key[0], key[1] or ""))
        info = _company(by_env, key[0], call.company if call else None)
        return {
            "environment": key[0],
            "id": key[1],
            "company": info["name"],
            "kind": call.kind if call else "real",
            "audio_minutes": _minutes(call.audio_ms) if call else None,
            "rupees": _rupees(call_spend[key]),
        }

    reports = len(delivered)
    return {
        "top_companies": [company_row(key) for key, _ in company_spend.most_common(8)],
        "top_calls": [call_row(key) for key, _ in call_spend.most_common(8)],
        "per_report": _rupees(total / reports) if reports else None,
        "failed_rupees": _rupees(failed_paise),
        "repeat_transcriptions": sum(len(extra) for extra in repeats),
        "repeat_rupees": _rupees(repeat_paise),
        "no_report_calls": len(no_report),
        "no_report_rupees": _rupees(no_report_paise),
        "tests_share": round(
            sum(s.paise or 0 for s in test_steps) / max(1, sum(s.paise or 0 for s in window_steps)),
            3,
        ),
        "missing": [
            "Cost per lead: the Lead Desk links only a lead's last call; it waits for "
            "call-to-lead links.",
            "Cost per reviewer hour: gold reviews don't record time spent yet.",
            "Invoices: amounts are list prices from the price sheet until provider "
            "invoices are reconciled.",
        ],
    }


class AdminCostMetrics:
    """The Admin's read of the metrics store, admitted like the other Sales X-Ray admin reads."""

    def __init__(
        self,
        application: ConversationApplication,
        operations_tenant_id: UUID,
        *,
        store_root: str | None,
        here: str | None = None,
    ) -> None:
        self.application = application
        self.operations_tenant_id = operations_tenant_id
        self.store_root = store_root
        # The environment this Admin runs in: its own calls can open in Calls.
        self.here = here if here in ENVIRONMENTS else None

    async def summary(
        self,
        actor: ActorContext,
        *,
        days: int = 30,
        environment: str = "all",
        tests: bool = False,
        call_sort: str = "newest",
        call_steps: bool = False,
        company: str | None = None,
        stage: str | None = None,
        person: str | None = None,
        fx: str = "daily",
    ) -> dict[str, Any]:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Cost and usage requires the AC operations workspace.")
        await ConversationProviderAdmin(self.application).admit(actor)
        if type(days) is not int or not 1 <= days <= MAX_DAYS:
            raise ConversationError("Choose a window between 1 and 120 days.")
        if environment not in ENVIRONMENT_FILTERS:
            raise ConversationError("Choose all, production, staging or development.")
        if call_sort not in CALL_SORTS:
            raise ConversationError("Sort calls by newest, cost, per_minute, audio or tokens.")
        if company is not None and not COMPANY_ID.fullmatch(company):
            raise ConversationError("Choose an organisation from the list.")
        if stage is not None and stage not in STAGE_LABELS:
            raise ConversationError("Choose a feature from the list.")
        if person is not None and not pseudonyms.PATTERN.fullmatch(person):
            raise ConversationError("Choose a person from the list.")
        if fx not in FX_MODES:
            raise ConversationError("Choose daily or planning rates.")
        exports, problems = read_store(self.store_root)
        now = utc(self.application.clock())
        await self._name_here(exports, now)
        fx_view = dict(FX)
        if fx == "daily":
            rates = await REFRESHER.rates(self.application.database, now)
            exports, fx_view = at_daily_rates(exports, rates, now - timedelta(days=days))
            fx_view["problem"] = REFRESHER.problem
        result = build_metrics(
            exports,
            Scope(
                now=now,
                days=days,
                environment=environment,
                tests=tests,
                call_sort=call_sort,
                call_steps=call_steps,
                company=company,
                stage=stage,
                person=person,
            ),
        )
        result["fx"] = fx_view
        result["problems"] = problems
        result["available"] = [export.environment for export in exports]
        result["here"] = self.here
        return result

    async def _name_here(self, exports: Sequence[Export], now: datetime) -> None:
        """This environment's organisation and person names, read live from its own database
        for this signed-in control account; never written to the store."""
        if self.here is None:
            return
        database = self.application.database
        # This environment's pseudonym key, made here once, so its next export carries people.
        await database.run_sync(lambda sync: pseudonyms.ensure_key(sync.connection(), now))
        mine = next((export for export in exports if export.environment == self.here), None)
        if mine is None:
            return
        ids = [UUID(key) for key in mine.companies if COMPANY_ID.fullmatch(key)]
        if ids:
            rows = await database.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(ids)))
            for tenant_id, name in rows:
                known = mine.companies.get(str(tenant_id))
                if known is not None and name:
                    known["name"] = str(name)
        wanted = {call.person for call in mine.calls if call.person} | {
            step.person for step in mine.steps if step.person
        }
        if wanted:
            mine.people = await database.run_sync(
                lambda sync: pseudonyms.names_for(sync.connection(), wanted, now)
            )


__all__ = [
    "AdminCostMetrics",
    "at_daily_rates",
    "ENVIRONMENTS",
    "Scope",
    "build_metrics",
    "dedupe",
    "parse_export",
    "price",
    "read_store",
    "version_id",
    "version_label",
]
