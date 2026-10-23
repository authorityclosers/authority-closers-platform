"""Where a lead may go from its stage, and what a seller is asked on the way in.

Lead OS (owner order, 24 Oct 2026; the sales team's nine-stage spec is the bar). A
lead has one current stage and moves straight to the stage that says where it stands
now, never through every stage. A business's stage list says, per stage:

- ``moves``: the stages a lead may go to from it. For Won, Lost and Junk these are the
  stages it can be reopened to. A stage without ``moves`` lets a lead go to any live
  stage, as before Lead OS, so a list saved before it behaves exactly as it did;
- ``needs``: what the seller must give on the way in: when to follow up
  (``next_action``), the meeting (``meeting``), why it was lost or is junk (``reason``),
  or why a call didn't connect (``nc_reason``). Without ``needs``, Junk needs a reason
  and Couldn't reach a not-connected reason; nothing else is required;
- ``reasons``: the reasons offered for Lost and Junk; "Other" always needs a note.

Everything here is pure: the store's one stage writer (``LeadDesk._move``) checks every
move through :func:`check` before it changes a lead. Who may do what:

- a closed lead (Won, Lost, Junk) goes back to work by a reopen; only an owner or admin
  reopens a Won lead in a list with moves;
- a Won or Lost lead turned Junk (it was never a real lead) is for an owner or admin;
- anyone working the lead marks it Junk from an open stage, with a reason.

Nothing here moves a lead by itself: unanswered calls never make a lead Junk or Lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from ac_platform.lead_desk.journey.model import CLOSED_KINDS, Journey, Stage
from ac_platform.lead_desk.vocabulary import JUNK_REASONS, LOST_REASONS, OTHER_REASON

Group = Literal["active", "won", "lost", "junk"]
Action = Literal["move", "close", "reopen", "reclassify"]

NEXT_ACTION: Final[str] = "next_action"
MEETING: Final[str] = "meeting"
REASON: Final[str] = "reason"
NC_REASON: Final[str] = "nc_reason"
# Asked by the sheet when the reason is "Other"; the server refuses Other without it.
REASON_NOTE: Final[str] = "reason_note"
# Offered by the sheet; never required.
NOTE: Final[str] = "note"
CONFIRM: Final[str] = "confirm"

NEED_WORDS: Final[dict[str, str]] = {
    NEXT_ACTION: "Pick when to follow up.",
    MEETING: "Add the meeting's date, time and type.",
    REASON: "Pick a reason.",
    NC_REASON: "Pick why the call didn't connect.",
    REASON_NOTE: "Add a short note for Other.",
}
# Where a move may come from (the stage event's ``source``).
SOURCES: Final[frozenset[str]] = frozenset(
    {"seller", "ai_suggestion", "rule", "import", "merge", "capture", "template"}
)


class MoveRefused(Exception):
    """A move the stage list or the person's role doesn't allow, or that lacks input.

    ``status`` is 403 (not this person), 409 (not from this stage: ``allowed`` lists
    where it can go) or 422 (``needs`` lists what to ask for)."""

    def __init__(
        self,
        status: int,
        words: str,
        *,
        allowed: tuple[str, ...] = (),
        needs: tuple[str, ...] = (),
    ) -> None:
        super().__init__(words)
        self.status = status
        self.allowed = allowed
        self.needs = needs


@dataclass(frozen=True, slots=True)
class Move:
    """One stage a lead may go to, as the stage sheet shows it."""

    stage: Stage
    action: Action
    needs: tuple[str, ...]
    asks: tuple[str, ...]
    reasons: tuple[tuple[str, str], ...]
    managers_only: bool = False

    @property
    def group(self) -> Group:
        return group(self.stage.kind)


@dataclass(frozen=True, slots=True)
class Given:
    """What the seller gave with a move."""

    reason: str | None = None
    reason_note: str | None = None
    nc_reason: str | None = None
    next_action: bool = False
    meeting: bool = False


def group(kind: str) -> Group:
    if kind in ("won", "lost", "junk"):
        return kind  # type: ignore[return-value]
    return "active"


def action_of(current: Stage | None, target: Stage) -> Action:
    closed_now = current is not None and current.kind in CLOSED_KINDS
    if target.kind in CLOSED_KINDS:
        return "reclassify" if closed_now else "close"
    return "reopen" if closed_now else "move"


def reasons_of(stage: Stage) -> tuple[tuple[str, str], ...]:
    if stage.kind not in ("lost", "junk"):
        return ()
    if stage.reasons:
        return stage.reasons
    return LOST_REASONS if stage.kind == "lost" else JUNK_REASONS


def needs_of(stage: Stage) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What a lead entering ``stage`` must have (needs), and what the sheet offers (asks)."""
    if stage.needs is not None:
        needs = tuple(n for n in stage.needs if n != REASON or stage.kind in ("lost", "junk"))
    elif stage.kind == "junk":
        needs = (REASON,)
    elif stage.kind == "not_connected":
        needs = (NC_REASON,)
    else:
        needs = ()
    asks: list[str] = []
    if stage.kind == "lost" and REASON not in needs:
        asks.append(REASON)
    if stage.kind == "not_connected" and NEXT_ACTION not in needs:
        asks.append(NEXT_ACTION)
    if stage.kind in CLOSED_KINDS:
        asks.append(CONFIRM)
    asks.append(NOTE)
    return needs, tuple(asks)


def _move(current: Stage | None, target: Stage, *, ruled: bool) -> Move:
    needs, asks = needs_of(target)
    action = action_of(current, target)
    # Reopening Won is for a manager where the list has moves; making a closed lead Junk
    # always is.
    managers_only = (action == "reclassify" and target.kind == "junk") or (
        ruled and action == "reopen" and current is not None and current.kind == "won"
    )
    return Move(target, action, needs, asks, reasons_of(target), managers_only)


def moves(journey: Journey, current: Stage | None, *, can_manage: bool) -> tuple[Move, ...]:
    """Every stage a lead in ``current`` may go to, for this person, in board order."""
    return tuple(
        move for move in _all_moves(journey, current) if can_manage or not move.managers_only
    )


def _all_moves(journey: Journey, current: Stage | None) -> tuple[Move, ...]:
    board = journey.board()
    if current is not None and current.moves is not None:
        wanted = set(current.moves)
        targets = [stage for stage in board if stage.key in wanted]
        ruled = True
    else:
        targets = list(board)
        ruled = False
    return tuple(
        _move(current, target, ruled=ruled)
        for target in targets
        if current is None or target.key != current.key
    )


def _words(stages: list[str]) -> str:
    if len(stages) <= 1:
        return "".join(stages)
    return ", ".join(stages[:-1]) + " or " + stages[-1]


def check(
    journey: Journey,
    current: Stage | None,
    step: str,
    given: Given,
    *,
    can_manage: bool,
    source: str = "seller",
) -> Move:
    """The move to ``step`` if this person may make it with what they gave; else refused.

    Imports skip the stage list's moves (the file says where each lead stands) but never
    a required reason."""
    target = journey.stage_for(step)
    if target is None or target.archived:
        raise MoveRefused(422, "Pick one of your current stages.")
    if current is not None and current.key == target.key:
        raise MoveRefused(409, f"This lead is already in “{target.label}”.")
    allowed = _all_moves(journey, current)
    move = next((item for item in allowed if item.stage.key == target.key), None)
    if move is None:
        if source != "import":
            mine = [m for m in allowed if can_manage or not m.managers_only]
            where = _words([f"“{m.stage.label}”" for m in mine])
            raise MoveRefused(
                409,
                f"From “{current.label if current else 'here'}”, a lead goes to {where}."
                if mine
                else "This lead can't move from here.",
                allowed=tuple(m.stage.key for m in mine),
            )
        move = _move(current, target, ruled=False)
    if move.managers_only and not can_manage:
        raise MoveRefused(
            403,
            "Only an owner or admin can reopen a won lead."
            if move.action == "reopen"
            else "Only an owner or admin can mark a closed lead as Junk.",
        )
    missing = [need for need in move.needs if not _has(need, given)]
    if given.reason is not None:
        keys = {key for key, _ in move.reasons}
        if move.reasons and given.reason not in keys:
            raise MoveRefused(422, "Pick one of the listed reasons.", needs=(REASON,))
        if given.reason == OTHER_REASON and not (given.reason_note or "").strip():
            missing.append(REASON_NOTE)
    if missing:
        raise MoveRefused(422, " ".join(NEED_WORDS[need] for need in missing), needs=tuple(missing))
    return move


def _has(need: str, given: Given) -> bool:
    if need == NEXT_ACTION:
        return given.next_action
    if need == MEETING:
        return given.meeting
    if need == REASON:
        return bool(given.reason)
    if need == NC_REASON:
        return bool(given.nc_reason)
    return True


def reason_label(move: Move, reason: str | None) -> str | None:
    if reason is None:
        return None
    return dict(move.reasons).get(reason)


def as_json(move: Move) -> dict[str, Any]:
    """A move as the lead's page reads it."""
    return {
        "step": move.stage.key,
        "label": move.stage.label,
        "kind": move.stage.kind,
        "group": move.group,
        "action": move.action,
        "needs": list(move.needs),
        "asks": list(move.asks),
        "reasons": [{"key": key, "label": label} for key, label in move.reasons],
    }
