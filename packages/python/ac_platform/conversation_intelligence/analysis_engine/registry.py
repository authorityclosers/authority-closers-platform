"""The analysis engine's registry, version 0 (adaptive analysis, phase 1; owner, 22 Oct 2026:
"design an algorithm that is most optimized ... very cheap ... make it simple for our
algorithm to plug in").

What every analysis module costs, measured, and the plans built from them:

- A **module** is one paid read the pipeline runs, or could run: the metrics store's stage
  code, the model ids the store records for it (Flex is its own id, ``model:flex``), the
  calls it applies to (by the call's fact prompt revision), and a cost **fit** for a call of
  ``m`` audio minutes, with where that fit was measured.
- A **plan** is the modules a short call gets (under one minute: transcript and lead details
  only), the modules an analysed call gets, and the modules that run only when someone asks
  (the full report on demand).

Pure data and arithmetic. Nothing here routes a call, changes a route or reads a database:
Admin uses it to project a plan's rupees per audio minute on a call mix, and to price each
recorded step's expected cost on read (``view``). Plan ``today`` recomputes the ₹0.709 the
design used on production's measured 14-day mix (the reference mix below).

Rupees are list prices at the planning rate (₹100 to the US dollar). Changing a number or a
plan is a new ``VERSION``; ``digest()`` changes with any edit, and Admin shows both.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Final, Literal

from ac_platform.one_pass import markers

VERSION: Final = "analysis-engine-registry/1"
# The rate every fit below is in: the price sheet's planning rate (admin_pricing.FX_USD_TO_INR).
PLANNING_FX: Final = 100.0
# The short-call rule: under a minute (or no conversation) gets the transcript and lead details.
SHORT_CALL_MINUTES: Final = 1.0
# The Brain 4.0 part inside the one-pass read (v2), measured on 8 AC dev calls (22 Oct): about
# 4.5k more input tokens and 1.5-2.0k more output tokens than v1 (the midpoint is used).
BRAIN4_PART_INPUT: Final = 4_500
BRAIN4_PART_OUTPUT: Final = 1_750
# A call's fact prompt revision as the metrics store records it (None: before revisions).
CLASSIC_FACTS: Final = frozenset({None, "facts-v1", "facts-v2"})
# One-pass calls carry the one-pass prompt revision (one_pass.markers is its only source).
REVISION_V1: Final = markers.PROMPT_REVISION
REVISION_V2: Final = markers.PROMPT_REVISION_V2

Status = Literal["live", "sealed", "trial", "beta", "planned"]


@dataclass(frozen=True)
class Fit:
    """One run of a module on a call of ``m`` audio minutes, in tokens and rupees.

    ``tokens_in`` and ``tokens_out`` are (fixed, per minute) and are priced at ``usd`` (input
    and output US dollars per million tokens). ``rupees`` is (fixed, per minute), for reads
    billed by audio or measured only in rupees. ``by_length`` is rupees a call by length,
    (up to minutes, ₹), for a read whose receipts were only measured that way.
    """

    tokens_in: tuple[float, float] | None = None
    tokens_out: tuple[float, float] | None = None
    usd: tuple[float, float] | None = None
    rupees: tuple[float, float] = (0.0, 0.0)
    by_length: tuple[tuple[float, float], ...] = ()

    def tokens(self, minutes: float) -> tuple[int, int] | None:
        if self.tokens_in is None or self.tokens_out is None:
            return None
        return (
            round(self.tokens_in[0] + self.tokens_in[1] * minutes),
            round(self.tokens_out[0] + self.tokens_out[1] * minutes),
        )

    def cost(self, minutes: float) -> float:
        """Rupees for one run at the planning rate."""
        minutes = max(0.0, minutes)
        total = self.rupees[0] + self.rupees[1] * minutes
        tokens = self.tokens(minutes)
        if tokens is not None and self.usd is not None:
            total += (tokens[0] * self.usd[0] + tokens[1] * self.usd[1]) / 1e6 * PLANNING_FX
        if self.by_length:
            total += next(
                (amount for upto, amount in self.by_length if minutes <= upto),
                self.by_length[-1][1],
            )
        return total

    def scaled(self, factor: float) -> Fit:
        """The same read at ``factor`` times the price (Flex is half)."""
        return Fit(
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            usd=None if self.usd is None else (self.usd[0] * factor, self.usd[1] * factor),
            rupees=(self.rupees[0] * factor, self.rupees[1] * factor),
            by_length=tuple((upto, amount * factor) for upto, amount in self.by_length),
        )


@dataclass(frozen=True)
class Module:
    id: str
    label: str
    # The metrics store's stage code (C1, C2, C4, C5, PR, CDF, CDD); B4 is not in the store yet.
    stage: str
    # Model ids as the store records them; empty means any model at this stage.
    models: tuple[str, ...]
    fit: Fit
    status: Status
    evidence: str
    # The calls' fact prompt revisions it applies to; empty means every call.
    facts: frozenset[str | None] = field(default_factory=frozenset)
    note: str = ""
    # False for a module with no route yet: it never matches a recorded step.
    recorded: bool = True

    def applies(self, stage: str, model: str | None, facts: str | None) -> bool:
        return (
            self.recorded
            and stage == self.stage
            and (not self.models or model in self.models)
            and (not self.facts or facts in self.facts)
        )


@dataclass(frozen=True)
class Plan:
    id: str
    label: str
    status: Status
    short: tuple[str, ...]
    analysed: tuple[str, ...]
    # Run only when someone asks (the full report on demand); projected at an uptake rate.
    on_demand: tuple[str, ...] = ()


# ---------- measured fits ----------

_GEMINI_FLASH = (0.75, 3.75)  # gemini-3.8-flash list, US dollars per million tokens in, out
_ONE_PASS_V1 = Fit(tokens_in=(3_579, 649), tokens_out=(3_379, 101), usd=_GEMINI_FLASH)
_ONE_PASS_V2 = Fit(
    tokens_in=(3_579 + BRAIN4_PART_INPUT, 649),
    tokens_out=(3_379 + BRAIN4_PART_OUTPUT, 101),
    usd=_GEMINI_FLASH,
)
# Production receipts by call length, less the one-pass C4 fit at each length's mean minutes.
_C5_AFTER_ONE_PASS = Fit(
    by_length=((3.0, 1.2296), (6.0, 1.4130), (10.0, 1.8873), (20.0, 2.0615), (999.0, 2.4777))
)
# Luna's C4 on Flex, production's exact request (₹ a call); the Brain 4.0 part at Luna Flex rates.
_LUNA_FLEX_USD = (0.05, 0.25)
_LUNA_V1_FLEX = Fit(rupees=(0.19, 0.0042))
_LUNA_V2_FLEX = Fit(
    rupees=(
        0.19
        + (BRAIN4_PART_INPUT * _LUNA_FLEX_USD[0] + BRAIN4_PART_OUTPUT * _LUNA_FLEX_USD[1])
        / 1e6
        * PLANNING_FX,
        0.0042,
    )
)

_V1_EVIDENCE = "production's exact request on 10 real dev calls (one-pass session, 21-22 Oct)"
_STORE_EVIDENCE = "dev and staging receipts in the metrics store, 22 Oct"

MODULES: Final[tuple[Module, ...]] = (
    Module(
        id="c1.audio-check",
        label="Audio check",
        stage="C1",
        models=(),
        fit=Fit(),
        status="live",
        evidence="Runs on the server; no provider charge.",
    ),
    Module(
        id="c2.flash-lite",
        label="Transcript · Gemini 3.1 Flash-Lite",
        stage="C2",
        models=("gemini-3.1-flash-lite",),
        fit=Fit(rupees=(0.0, 0.233)),
        status="live",
        evidence="16 real calls' receipts, audio and output tokens (one-pass session, 21 Oct)",
        note="The metrics store prices this step at the price sheet's ₹0.30/min ceiling, so its"
        " actual reads about 29% above this fit.",
    ),
    Module(
        id="c2.flash-lite.flex",
        label="Transcript · Flash-Lite on Flex",
        stage="C2",
        models=("gemini-3.1-flash-lite:flex",),
        fit=Fit(rupees=(0.0, 0.1175)),
        status="sealed",
        evidence="the same 16 calls on Flex, fallbacks to standard included",
        note="The metrics store prices this step at ₹0.15/min.",
    ),
    Module(
        id="c2.flash-lite-compact.flex",
        label="Transcript · Flash-Lite, compact lines, Flex",
        stage="C2",
        models=(),
        fit=Fit(rupees=(0.0, 0.1175 * 0.65)),
        status="planned",
        evidence="−48% output tokens on 6 fictional and −53% on 11 real calls; speaker accuracy"
        " −2.3 points",
        recorded=False,
    ),
    Module(
        id="c2.scribe",
        label="Transcript · ElevenLabs Scribe",
        stage="C2",
        models=("scribe_v2",),
        fit=Fit(rupees=(0.0, 0.22 / 60 * PLANNING_FX)),
        status="live",
        evidence="ElevenLabs list price, USD 0.22 an hour (the price sheet); billed by audio",
    ),
    Module(
        id="c4.one-pass-v1",
        label="One pass · facts, notes and 27-pointer review",
        stage="C4",
        models=("gemini-3.8-flash",),
        facts=frozenset({REVISION_V1}),
        fit=_ONE_PASS_V1,
        status="live",
        evidence=_V1_EVIDENCE,
    ),
    Module(
        id="c4.one-pass-v1.flex",
        label="One pass on Flex",
        stage="C4",
        models=("gemini-3.8-flash:flex",),
        facts=frozenset({REVISION_V1}),
        fit=_ONE_PASS_V1.scaled(0.5),
        status="sealed",
        evidence=_V1_EVIDENCE + "; Flex is half the list price",
    ),
    Module(
        id="c4.one-pass-v1.luna-flex",
        label="One pass · GPT-6 Luna on Flex",
        stage="C4",
        models=("gpt-6-luna:flex",),
        facts=frozenset({REVISION_V1}),
        fit=_LUNA_V1_FLEX,
        status="trial",
        evidence="13 real calls, production's exact request (one-pass session, 21 Oct)",
        note="The metrics store has no Luna price yet, so its actual shows as unpriced.",
    ),
    Module(
        id="c4.one-pass-v2",
        label="One pass with Brain 4.0 inside",
        stage="C4",
        models=("gemini-3.8-flash",),
        facts=frozenset({REVISION_V2}),
        fit=_ONE_PASS_V2,
        status="planned",
        evidence="the v1 fit plus the Brain 4.0 part as measured on 8 AC dev calls (22 Oct):"
        " +4.5k input, +1.5-2.0k output tokens (midpoint used); every contract passed",
    ),
    Module(
        id="c4.one-pass-v2.flex",
        label="One pass with Brain 4.0, Flex",
        stage="C4",
        models=("gemini-3.8-flash:flex",),
        facts=frozenset({REVISION_V2}),
        fit=_ONE_PASS_V2.scaled(0.5),
        status="planned",
        evidence="as above; Flex is half the list price",
    ),
    Module(
        id="c4.one-pass-v2.luna-flex",
        label="One pass with Brain 4.0 · Luna on Flex",
        stage="C4",
        models=("gpt-6-luna:flex",),
        facts=frozenset({REVISION_V2}),
        fit=_LUNA_V2_FLEX,
        status="planned",
        evidence="Luna's measured C4 plus the Brain 4.0 part (Gemini's measured tokens) at Luna"
        " Flex list rates",
    ),
    Module(
        id="c4.classic",
        label="Facts · classic C4",
        stage="C4",
        models=("gemini-3.8-flash",),
        facts=CLASSIC_FACTS,
        fit=Fit(tokens_in=(67, 725.8), tokens_out=(146, 56.7), usd=_GEMINI_FLASH),
        status="live",
        evidence="78 calls' " + _STORE_EVIDENCE + "; every C4 step of a call (2.4-2.6 a call:"
        " classic facts read a long call in parts); median error 10% in, 14% out",
    ),
    Module(
        id="pr.classic",
        label="Pointer review · classic",
        stage="PR",
        models=("gemini-3.8-flash",),
        facts=CLASSIC_FACTS,
        fit=Fit(tokens_in=(947, 408.3), tokens_out=(4_074, 10.6), usd=_GEMINI_FLASH),
        status="live",
        evidence="61 reviews' " + _STORE_EVIDENCE,
    ),
    Module(
        id="pr.in-one-pass",
        label="Pointer review · inside the one-pass read",
        stage="PR",
        models=(),
        facts=frozenset({REVISION_V1, REVISION_V2}),
        fit=Fit(),
        status="live",
        evidence="The review comes in the one-pass answer; no read of its own.",
    ),
    Module(
        id="c5.after-one-pass",
        label="Full report · coaching-v5",
        stage="C5",
        models=("gemini-3.8-flash",),
        facts=frozenset({REVISION_V1, REVISION_V2}),
        fit=_C5_AFTER_ONE_PASS,
        status="live",
        evidence="production receipts by call length on the 14-day mix, less the one-pass C4 fit",
    ),
    Module(
        id="c5.after-one-pass.flex",
        label="Full report on Flex",
        stage="C5",
        models=("gemini-3.8-flash:flex",),
        facts=frozenset({REVISION_V1, REVISION_V2}),
        fit=_C5_AFTER_ONE_PASS.scaled(0.5),
        status="sealed",
        evidence="as above; Flex is half the list price",
    ),
    Module(
        id="c5.classic",
        label="Full report · after classic facts",
        stage="C5",
        models=("gemini-3.8-flash",),
        facts=CLASSIC_FACTS,
        fit=Fit(tokens_in=(4_374, 602.4), tokens_out=(3_540, 24.0), usd=_GEMINI_FLASH),
        status="live",
        evidence="72 calls' " + _STORE_EVIDENCE,
    ),
    Module(
        id="cdf.fast",
        label="Lead details · fast call data",
        stage="CDF",
        models=(),
        fit=Fit(rupees=(0.0, 0.087 * PLANNING_FX / 95)),
        status="live",
        evidence="38 real dev calls, 537 min (call data engine, 19 Oct; measured at ₹95/USD)",
    ),
    Module(
        id="cdd.deep",
        label="Call data · deep read",
        stage="CDD",
        models=(),
        fit=Fit(rupees=(0.0, 0.303 * PLANNING_FX / 95)),
        status="live",
        evidence="40 real dev calls, 493 min (call data engine, 19 Oct; measured at ₹95/USD)",
        note="Production's deep call data comes from the one-pass answer; this read runs on dev.",
    ),
    Module(
        id="b4.shadow",
        label="Brain 4.0 · separate read",
        stage="B4",
        models=(),
        fit=Fit(tokens_in=(4_472, 383), tokens_out=(1_376, 24), usd=_GEMINI_FLASH),
        status="beta",
        evidence="61 saved production reads on Gemini 3.8 Flash (one-pass session, 22 Oct)",
        note="Brain 4.0 beta organisations only; the metrics store does not record this read.",
        recorded=False,
    ),
)

_BY_ID: Final = {module.id: module for module in MODULES}


# ---------- quality ----------


@dataclass(frozen=True)
class Quality:
    """Agreement with the coaching lead's gold labels, for one artifact of one setup.

    ``module`` is set when the setup is that registry module exactly as built; a research arm
    or a near relative leaves it empty and names the module it informs in ``nearest``.
    ``agreement`` and its 95% interval are shares of the labels; all three are None while the
    setup is not scored. Beta and research only: nothing here is an official score (AC-SVAL).
    """

    artifact: Literal["review", "brain4"]
    setup: str
    agreement: float | None
    low: float | None
    high: float | None
    evidence: str
    module: str | None = None
    nearest: str | None = None


_GOLD_V1 = "gold v1: the coaching lead's 43 labels on 6 real calls, Flash-Lite transcripts"
_NOT_SCORED = "not scored yet: production's exact requests on the 7 gold calls"

QUALITY: Final[tuple[Quality, ...]] = (
    Quality(
        artifact="review",
        setup="Classic pointer review",
        module="pr.classic",
        agreement=0.64,
        low=0.49,
        high=0.77,
        evidence=_GOLD_V1,
    ),
    Quality(
        artifact="review",
        setup="One pass v1 review, production's request",
        module="c4.one-pass-v1",
        agreement=None,
        low=None,
        high=None,
        evidence=_NOT_SCORED,
    ),
    Quality(
        artifact="review",
        setup="Research one pass (onepass2: facts and 27 pointers, Gemini)",
        nearest="c4.one-pass-v1",
        agreement=0.72,
        low=0.57,
        high=0.83,
        evidence=_GOLD_V1 + "; a research prompt, not production's request",
    ),
    Quality(
        artifact="review",
        setup="Luna C review, production's request",
        module="c4.one-pass-v1.luna-flex",
        agreement=None,
        low=None,
        high=None,
        evidence=_NOT_SCORED,
    ),
    Quality(
        artifact="brain4",
        setup="Brain 4.0, product prompt, Gemini 3.8 Flash (separate read)",
        module="b4.shadow",
        agreement=0.55,
        low=0.38,
        high=0.70,
        evidence=_GOLD_V1,
    ),
    Quality(
        artifact="brain4",
        setup="Brain 4.0 inside the one-pass read (v2)",
        module="c4.one-pass-v2",
        agreement=None,
        low=None,
        high=None,
        evidence=_NOT_SCORED + "; the same Brain 4.0 instructions as the separate read",
    ),
    Quality(
        artifact="brain4",
        setup="Brain 4.0, product prompt, GPT-6 Luna (separate read)",
        nearest="c4.one-pass-v2.luna-flex",
        agreement=0.39,
        low=0.28,
        high=0.50,
        evidence=_GOLD_V1,
    ),
    Quality(
        artifact="brain4",
        setup="Research Brain 4.0 prompt, Gemini",
        nearest="b4.shadow",
        agreement=0.60,
        low=0.44,
        high=0.73,
        evidence=_GOLD_V1 + "; a research prompt",
    ),
)


def quality_of(module_id: str) -> tuple[Quality, ...]:
    """The gold rows for a module as built (not its research relatives)."""
    return tuple(row for row in QUALITY if row.module == module_id)


PLANS: Final[tuple[Plan, ...]] = (
    Plan(
        id="today",
        label="Today: one pass v1 and the full report, Gemini standard",
        status="live",
        short=("c2.flash-lite", "cdf.fast"),
        analysed=("c2.flash-lite", "c4.one-pass-v1", "c5.after-one-pass"),
    ),
    Plan(
        id="today-brain4-read",
        label="Today plus a separate Brain 4.0 read on every analysed call",
        status="beta",
        short=("c2.flash-lite", "cdf.fast"),
        analysed=("c2.flash-lite", "c4.one-pass-v1", "c5.after-one-pass", "b4.shadow"),
    ),
    Plan(
        id="v2",
        label="Brain 4.0 inside the one-pass read, full report kept",
        status="planned",
        short=("c2.flash-lite", "cdf.fast"),
        analysed=("c2.flash-lite", "c4.one-pass-v2", "c5.after-one-pass"),
    ),
    Plan(
        id="v2-report-on-demand",
        label="v2, full report on demand",
        status="planned",
        short=("c2.flash-lite", "cdf.fast"),
        analysed=("c2.flash-lite", "c4.one-pass-v2"),
        on_demand=("c5.after-one-pass",),
    ),
    Plan(
        id="v2-flex-report-on-demand",
        label="v2 on Flex, full report on demand",
        status="planned",
        short=("c2.flash-lite.flex", "cdf.fast"),
        analysed=("c2.flash-lite.flex", "c4.one-pass-v2.flex"),
        on_demand=("c5.after-one-pass.flex",),
    ),
    Plan(
        id="v2-luna-flex-report-on-demand",
        label="v2 on Luna, Flex, full report on demand",
        status="planned",
        short=("c2.flash-lite.flex", "cdf.fast"),
        analysed=("c2.flash-lite.flex", "c4.one-pass-v2.luna-flex"),
        on_demand=("c5.after-one-pass.flex",),
    ),
    Plan(
        id="v2-luna-flex-compact",
        label="As above, with the compact transcript",
        status="planned",
        short=("c2.flash-lite-compact.flex", "cdf.fast"),
        analysed=("c2.flash-lite-compact.flex", "c4.one-pass-v2.luna-flex"),
        on_demand=("c5.after-one-pass.flex",),
    ),
)

# Production's measured 14 days (canaries out): (calls, mean audio minutes) by length, the
# minutes read back from C2 at ₹0.233/min. 62 calls, 284.4 min; 27 under a minute.
REFERENCE_MIX: Final[tuple[tuple[int, float], ...]] = (
    (27, 0.12 / 0.233),
    (11, 0.39 / 0.233),
    (7, 1.00 / 0.233),
    (8, 1.85 / 0.233),
    (6, 3.40 / 0.233),
    (3, 5.51 / 0.233),
)


def module(module_id: str) -> Module:
    return _BY_ID[module_id]


def plan(plan_id: str) -> Plan:
    return next(item for item in PLANS if item.id == plan_id)


def match(stage: str, model: str | None, facts: str | None) -> Module | None:
    """The module a recorded step belongs to (the first that applies), or None."""
    return next((item for item in MODULES if item.applies(stage, model, facts)), None)


def project(
    chosen: Plan,
    mix: Iterable[tuple[int, float]],
    *,
    uptake: float = 0.0,
    without: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """A plan's rupees per audio minute on a mix of (calls, minutes each).

    ``uptake`` is the share of analysed calls that ask for the on-demand modules; ``without``
    leaves modules out (what a module adds is the plan with it less the plan without it).
    """
    if not 0.0 <= uptake <= 1.0:
        raise ValueError("uptake is a share between 0 and 1")
    minutes = calls = 0.0
    by_module: dict[str, float] = {}

    def add(module_id: str, count: float, length: float) -> None:
        if module_id in without:
            return
        amount = count * _BY_ID[module_id].fit.cost(length)
        by_module[module_id] = by_module.get(module_id, 0.0) + amount

    for count, length in mix:
        calls += count
        minutes += count * length
        if length < SHORT_CALL_MINUTES:
            for module_id in chosen.short:
                add(module_id, count, length)
            continue
        for module_id in chosen.analysed:
            add(module_id, count, length)
        for module_id in chosen.on_demand:
            add(module_id, count * uptake, length)
    rupees = sum(by_module.values())
    return {
        "plan": chosen.id,
        "calls": int(calls),
        "audio_minutes": round(minutes, 1),
        "rupees": round(rupees, 2),
        "per_minute": None if minutes <= 0 else round(rupees / minutes, 4),
        "modules": {
            key: None if minutes <= 0 else round(value / minutes, 4)
            for key, value in by_module.items()
        },
    }


def _plain(value: Any) -> Any:
    if isinstance(value, frozenset):
        return sorted(value, key=lambda item: "" if item is None else item)
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_plain(item) for item in value]
    return value


def digest() -> str:
    """Ten hex characters over every module and plan: any edit changes it."""
    body = json.dumps(
        {
            "version": VERSION,
            "fx": PLANNING_FX,
            "short_minutes": SHORT_CALL_MINUTES,
            "modules": [_plain(asdict(item)) for item in MODULES],
            "plans": [_plain(asdict(item)) for item in PLANS],
            "quality": [_plain(asdict(item)) for item in QUALITY],
            "mix": _plain(REFERENCE_MIX),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()[:10]


EXAMPLE_MINUTES: Final = (2.0, 5.0, 15.0)


def describe(*, uptake: float = 0.1) -> dict[str, Any]:
    """The registry for Admin: modules with example costs, plans on the reference mix."""
    return {
        "version": VERSION,
        "digest": digest(),
        "planning_fx": PLANNING_FX,
        "short_call_minutes": SHORT_CALL_MINUTES,
        "modules": [
            {
                "id": item.id,
                "label": item.label,
                "stage": item.stage,
                "models": list(item.models),
                "facts": _plain(item.facts),
                "status": item.status,
                "evidence": item.evidence,
                "note": item.note,
                "examples": [
                    {"minutes": minutes, "rupees": round(item.fit.cost(minutes), 3)}
                    for minutes in EXAMPLE_MINUTES
                ],
            }
            for item in MODULES
        ],
        "plans": [
            {
                "id": item.id,
                "label": item.label,
                "status": item.status,
                "short": list(item.short),
                "analysed": list(item.analysed),
                "on_demand": list(item.on_demand),
                "reference": project(item, REFERENCE_MIX),
                "reference_with_uptake": project(item, REFERENCE_MIX, uptake=uptake)
                if item.on_demand
                else None,
            }
            for item in PLANS
        ],
        "quality": [asdict(item) for item in QUALITY],
        "uptake": uptake,
    }
