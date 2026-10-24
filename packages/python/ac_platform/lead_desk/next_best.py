"""What a seller should do now (work-memory engine, section 6;
docs/product/lead-desk/work-memory-engine.md).

Candidates are tasks due or overdue, promised call-backs, callers not reached, new leads
waiting past the first-response target and hot leads gone quiet. Each gets a score, a sum
of weighted factors from 0 to 1, and the words of its two biggest factors ("because:
promised a call back · 20 min overdue"), so the order can always be explained. A business
can tune the weights (0 to 5 each). Ties go to the earlier due, then the lead, so the same
facts always give the same order.

Pure: candidates, a clock and weights in; a ranked list out.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

DEFAULT_WEIGHTS: Final[dict[str, float]] = {
    "overdue": 3.0,
    "promise": 3.0,
    "missed_caller": 2.5,
    "due_soon": 2.0,
    "sla": 2.0,
    "hot_quiet": 1.5,
    "stage": 1.0,
    "just_talked": 2.0,
}
WEIGHT_LIMIT: Final = 5.0
# How far ahead "due soon" looks, and when overdue counts in full.
SOON_MINUTES: Final = 120.0
FULLY_OVERDUE_MINUTES: Final = 120.0
JUST_TALKED_MINUTES: Final = 30.0


@dataclass(frozen=True, slots=True)
class Candidate:
    lead_id: str
    lead_name: str
    task_id: str | None = None
    due_at: datetime | None = None
    promised: bool = False
    missed_caller: bool = False
    # A new lead: how long it has waited and the first-response target.
    waiting_minutes: float | None = None
    target_minutes: float | None = None
    # A lead past "qualified": time since the last contact and its stage's limit.
    quiet_hours: float | None = None
    rot_hours: float | None = None
    stage_rank: int = 0
    max_rank: int = 1
    talked_minutes_ago: float | None = None


@dataclass(frozen=True, slots=True)
class Ranked:
    candidate: Candidate
    score: float
    because: tuple[str, ...]


def weights_from(config: Mapping[str, object] | None) -> dict[str, float]:
    """A business's weights over the defaults, each held between 0 and 5."""
    out = dict(DEFAULT_WEIGHTS)
    for key, value in (config or {}).items():
        if key in out and isinstance(value, int | float) and not isinstance(value, bool):
            out[key] = min(WEIGHT_LIMIT, max(0.0, float(value)))
    return out


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


def _minutes(minutes: float) -> str:
    whole = int(minutes)
    if whole < 60:
        return f"{whole} min"
    hours, rest = divmod(whole, 60)
    if hours < 24:
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return f"{hours // 24} d"


def factors(candidate: Candidate, now: datetime) -> list[tuple[str, float, str]]:
    """(factor, value 0..1, words) for every factor that applies; "just talked" is a
    negative value."""
    out: list[tuple[str, float, str]] = []
    if candidate.due_at is not None:
        late = (now - candidate.due_at).total_seconds() / 60
        if late >= 1:
            # Past its due a task keeps all of "due soon" and adds "overdue" on top: more
            # overdue never ranks lower than due, or than due soon.
            out.append(("due_soon", 1.0, ""))
            out.append(
                ("overdue", _clip(late / FULLY_OVERDUE_MINUTES), f"{_minutes(late)} overdue")
            )
        elif -late <= SOON_MINUTES:
            ahead = max(0.0, -late)
            out.append(("due_soon", _clip(1 - ahead / SOON_MINUTES), f"due in {_minutes(ahead)}"))
    if candidate.promised:
        out.append(("promise", 1.0, "promised a call back"))
    if candidate.missed_caller:
        out.append(("missed_caller", 1.0, "called you, not reached"))
    if candidate.waiting_minutes is not None and candidate.target_minutes:
        share = candidate.waiting_minutes / candidate.target_minutes
        out.append(
            ("sla", _clip(share), f"new lead, {_minutes(candidate.waiting_minutes)} waiting")
        )
    if candidate.quiet_hours is not None and candidate.rot_hours:
        over = candidate.quiet_hours / candidate.rot_hours - 1
        if over > 0:
            days = int(candidate.quiet_hours // 24)
            words = f"quiet {days} d" if days else f"quiet {int(candidate.quiet_hours)} h"
            out.append(("hot_quiet", _clip(over), words))
    if candidate.max_rank > 0 and candidate.stage_rank > 0:
        out.append(("stage", _clip(candidate.stage_rank / candidate.max_rank), "far along"))
    if (
        candidate.talked_minutes_ago is not None
        and candidate.talked_minutes_ago < JUST_TALKED_MINUTES
    ):
        out.append(("just_talked", -1.0, "talked just now"))
    return out


def score(
    candidate: Candidate, now: datetime, weights: Mapping[str, float] = DEFAULT_WEIGHTS
) -> Ranked:
    parts = factors(candidate, now)
    total = sum(weights.get(name, 0.0) * value for name, value, _ in parts)
    reasons = sorted(
        (
            (weights.get(name, 0.0) * value, words)
            for name, value, words in parts
            if value > 0 and words
        ),
        key=lambda item: -item[0],
    )
    return Ranked(candidate, round(total, 6), tuple(words for _, words in reasons[:2]))


def rank(
    candidates: Iterable[Candidate],
    now: datetime,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    limit: int = 20,
) -> list[Ranked]:
    """The top ``limit``, best first; one entry per lead (its best reason to act)."""
    best: dict[str, Ranked] = {}
    for candidate in candidates:
        ranked = score(candidate, now, weights)
        kept = best.get(candidate.lead_id)
        if kept is None or ranked.score > kept.score:
            best[candidate.lead_id] = ranked
    far = datetime.max.replace(tzinfo=now.tzinfo)
    ordered = sorted(
        best.values(),
        key=lambda item: (
            -item.score,
            item.candidate.due_at or far,
            item.candidate.lead_id,
        ),
    )
    return ordered[: max(0, limit)]
