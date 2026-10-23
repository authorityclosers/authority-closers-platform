"""Which new calls go to gold reviewers, and how (orchestrator, 21 Oct 2026).

After the 21 Oct checkpoint reset the gold reader stops assigning every real call. A
checkpoint (``profiles/gold_checkpoint.json``) names the calls worth a reviewer's time:
our own company's workspaces, 10-30 minutes, recorded after the checkpoint began; at
least so many that reach price or closing, raise an objection, or talk decisions and
next steps; a mix of first calls and follow-ups and of outcomes; and several
salespeople. At most ``daily`` calls a day, stopping at ``total``. Each chosen call goes
to every standing reviewer, so a second reviewer rates the same calls (AC-SVAL-01 Gate 0).

``mode`` says how the calls are reviewed: ``brain4_blind`` asks for the 18 Brain 4.0
ratings before Brain 4.0's own are shown (AC-SVAL-01 section 8.1).

The facts are the saved analysis' (stages, objections, next steps, buyer qualification)
and the salesperson's own records (prospect links, call outcome); nothing is inferred
here. ``choose`` is a sampling rule, not a judgement of the calls: it fills the
``at_least`` counts first (keeping enough room for each), then the ``mix``, then new
salespeople, oldest call first on a tie.

Pure: no I/O but reading the config file.
"""

from __future__ import annotations

import functools
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONFIG_FILE: Final = Path(__file__).with_name("profiles") / "gold_checkpoint.json"
MODES: Final = ("lines", "brain4_blind", "report")
FEATURES: Final = (
    "price",
    "objection",
    "decision",
    "first_call",
    "follow_up",
    "won",
    "lost",
    "pending",
)
# The analysis' stages that mean the call reached price or closing.
PRICE_STAGES: Final = frozenset({"Negotiation", "Closing"})
# The salesperson's recorded outcome, in the checkpoint's three words.
OUTCOMES: Final = {
    "won": "won",
    "lost": "lost",
    "follow_up": "pending",
    "no_decision": "pending",
}
# Sampling weights: a needed at_least count outranks a needed mix count, which outranks a
# new salesperson. Ordering only; they never reach a review or a score.
_AT_LEAST: Final = 2.0
_MIX: Final = 1.0
_NEW_SALESPERSON: Final = 0.5


class Salespeople(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    at_least: int = Field(ge=1, le=50)
    at_most_each: int = Field(ge=1, le=500)


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9./-]*$")
    about: str = Field(default="", max_length=600)
    since: datetime
    mode: Literal["lines", "brain4_blind", "report"]
    daily: int = Field(ge=1, le=50)
    total: int = Field(ge=1, le=500)
    # Reviewers work in India: a day's calls are assigned from this hour, Asia/Kolkata.
    assign_from_hour: int = Field(ge=0, le=23)
    # Call length in minutes, from the saved transcript; null takes any length.
    minutes: tuple[int, int] | None
    # "company": our own company's workspaces (Admin's kind); "any": every real workspace.
    workspaces: Literal["company", "any"]
    at_least: dict[str, int]
    mix: dict[str, int]
    salespeople: Salespeople

    @model_validator(mode="after")
    def coherent(self) -> Checkpoint:
        if self.minutes is not None and not 0 <= self.minutes[0] < self.minutes[1] <= 240:
            raise ValueError("minutes must be a range within 0-240")
        if self.since.tzinfo is None:
            raise ValueError("since needs a time zone")
        for name, count in (*self.at_least.items(), *self.mix.items()):
            if name not in FEATURES or not 0 <= count <= self.total:
                raise ValueError(f"unknown or impossible count: {name}")
        if self.daily > self.total:
            raise ValueError("daily cannot exceed total")
        return self


# The reader's rule before checkpoints (16-21 Oct 2026): every real call, the 29 lines.
EVERY_CALL: Final = Checkpoint(
    name="every-call",
    since=datetime(2000, 1, 1, tzinfo=UTC),
    mode="lines",
    daily=50,
    total=500,
    assign_from_hour=0,
    minutes=None,
    workspaces="any",
    at_least={},
    mix={},
    salespeople=Salespeople(at_least=1, at_most_each=500),
)


@functools.cache
def current() -> Checkpoint:
    """The checkpoint in force (one at a time; a new one replaces the file)."""
    return Checkpoint.model_validate_json(CONFIG_FILE.read_text(encoding="utf-8"))


def _listed(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _state(qualification: Any, key: str) -> str | None:
    if not isinstance(qualification, Mapping):
        return None
    entry = qualification.get(key)
    state = entry.get("state") if isinstance(entry, Mapping) else None
    return state if isinstance(state, str) else None


def features(
    outcome: Any,
    qualification: Any,
    *,
    sequence: str | None = None,
    recorded_outcome: str | None = None,
) -> frozenset[str]:
    """What one call offers the checkpoint.

    ``outcome`` and ``qualification`` are the saved analysis' ``outcome`` and
    ``buyer_qualification`` blocks; ``sequence`` is ``first_call`` or ``follow_up`` from
    the salesperson's prospect links (None when the call has no prospect); and
    ``recorded_outcome`` is the outcome the salesperson recorded (None when none).
    """
    found: set[str] = set()
    block = outcome if isinstance(outcome, Mapping) else {}
    if PRICE_STAGES & {s for s in _listed(block.get("stages")) if isinstance(s, str)}:
        found.add("price")
    if _listed(block.get("objections")):
        found.add("objection")
    if _listed(block.get("next_steps")) or _state(qualification, "authority") in (
        "confirmed",
        "concern",
    ):
        found.add("decision")
    if sequence in ("first_call", "follow_up"):
        found.add(sequence)
    if recorded_outcome in OUTCOMES:
        found.add(OUTCOMES[recorded_outcome])
    return frozenset(found)


@dataclass(frozen=True)
class Candidate:
    recording_id: str
    salesperson: str
    recorded_at: datetime
    features: frozenset[str]


def choose(
    checkpoint: Checkpoint,
    picked: Sequence[Candidate],
    candidates: Sequence[Candidate],
    room: int,
) -> list[Candidate]:
    """Up to ``room`` new calls for the checkpoint, given the calls it already chose.

    Hard rules: never past ``total``; never more than ``at_most_each`` calls from one
    salesperson; when an ``at_least`` count needs every remaining place, only calls that
    meet it; when the remaining places are all needed for new salespeople, only new ones.
    A call those rules exclude waits for a later day. Soft: the call that helps the most
    needed counts goes first; among equals, the oldest.
    """
    chosen: list[Candidate] = []
    taken = list(picked)
    seen = {c.recording_id for c in taken}
    pool = sorted(
        (c for c in candidates if c.recording_id not in seen),
        key=lambda c: (c.recorded_at, c.recording_id),
    )
    people = checkpoint.salespeople
    while len(chosen) < room and len(taken) < checkpoint.total and pool:
        left = checkpoint.total - len(taken)
        counts = Counter(f for c in taken for f in c.features)
        per_person = Counter(c.salesperson for c in taken)
        need = {f: max(0, n - counts[f]) for f, n in checkpoint.at_least.items()}
        mix = {f: max(0, n - counts[f]) for f, n in checkpoint.mix.items()}
        must = frozenset(f for f, n in need.items() if n and n >= left)
        short = people.at_least - len(per_person)
        only_new = short > 0 and left <= short
        best: Candidate | None = None
        best_score = -1.0
        for candidate in pool:
            if per_person[candidate.salesperson] >= people.at_most_each:
                continue
            if not must <= candidate.features:
                continue
            new = candidate.salesperson not in per_person
            if only_new and not new:
                continue
            score = sum(_AT_LEAST * n / left for f, n in need.items() if f in candidate.features)
            score += sum(_MIX * n / left for f, n in mix.items() if f in candidate.features)
            if new and short > 0:
                score += _NEW_SALESPERSON
            if score > best_score:
                best, best_score = candidate, score
        if best is None:
            break
        chosen.append(best)
        taken.append(best)
        pool.remove(best)
    return chosen


def progress(checkpoint: Checkpoint, picked: Sequence[Candidate]) -> dict[str, Any]:
    """Counts only, for Admin: how far the checkpoint's sample is."""
    counts = Counter(f for c in picked for f in c.features)
    return {
        "name": checkpoint.name,
        "mode": checkpoint.mode,
        "since": checkpoint.since.isoformat(),
        "minutes": list(checkpoint.minutes) if checkpoint.minutes else None,
        "workspaces": checkpoint.workspaces,
        "daily": checkpoint.daily,
        "total": checkpoint.total,
        "chosen": len(picked),
        "salespeople": len({c.salesperson for c in picked}),
        "at_least": {f: {"want": n, "have": counts[f]} for f, n in checkpoint.at_least.items()},
        "mix": {f: {"want": n, "have": counts[f]} for f, n in checkpoint.mix.items()},
    }


__all__ = [
    "EVERY_CALL",
    "FEATURES",
    "MODES",
    "Candidate",
    "Checkpoint",
    "choose",
    "current",
    "features",
    "progress",
]
