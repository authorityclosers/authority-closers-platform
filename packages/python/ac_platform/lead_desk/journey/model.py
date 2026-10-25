"""A business's own lead stages: one list per pipeline, saved as versions.

Every save adds a version (``lead_desk_journey_versions``); nothing is overwritten,
and a stage that was ever used stays in the list, archived, so old leads and old
history keep their words. An organisation that never saved one works with the
"Any business" profile, whose stage keys are the desk's own six stages, so nothing
changes for it until it picks its own.

A lead keeps the desk's stage (``Lead.stage``, the stage's kind) and, when a seller
picked one of the business's own stages, that stage's key (``Lead.step``). A lead
with no step is in the business's stage for its kind (see ``Journey.resolve``).

An organisation can run several pipelines, each with its own list (``pipelines.py``); a
lead's step is read in its own pipeline's list. Version numbers stay unique per
organisation across its pipelines.

A stage may carry its moves (Lead OS, 24 Oct 2026): ``moves`` (where a lead may go from
it), ``needs`` (what a seller is asked on the way in), ``reasons`` (for Lost and Junk)
and ``rot_hours`` (how long a lead may sit in it). They are written only when set, so a
list saved before them reads back unchanged and lets a lead go anywhere
(``journey/transitions.py``).

Every list can mark a lead Junk, even one with no Junk stage of its own: such a lead
sits in ``JUNK``, the desk's own Junk stage.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.journey.templates import (
    DEFAULT_TEMPLATE,
    FUNNEL_ORDER,
    KINDS,
    MILESTONE_KIND,
    MILESTONES,
    NEEDS,
    Kind,
    Milestone,
    Template,
    guess_milestone,
    slug,
    template,
)
from ac_platform.lead_desk.models import Lead, LeadJourneyVersion
from ac_platform.lead_desk.vocabulary import NOT_A_LEAD

MAIN_PIPELINE: Final[str] = "main"
MAX_LIVE: Final[int] = 16
MAX_ALL: Final[int] = 80
MAX_LABEL: Final[int] = 40
KEY: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
ORIGINS: Final[frozenset[str]] = frozenset({"template", "custom", "pulse", "suggested"})
OPEN_KINDS: Final[frozenset[str]] = frozenset({"follow_up", "interested"})
# The desk stages a seller picks after a call that connected.
CONNECTED_KINDS: Final[frozenset[str]] = frozenset({"follow_up", "interested", "won", "lost"})
CLOSED_KINDS: Final[frozenset[str]] = frozenset({"won", "lost", "junk"})
MAX_REASONS: Final[int] = 20
MAX_REASON_LABEL: Final[int] = 60
MAX_ROT_HOURS: Final[int] = 24 * 90


class JourneyError(ValueError):
    """A change the manager must fix; the message is shown as is."""


@dataclass(frozen=True, slots=True)
class Stage:
    key: str
    label: str
    kind: Kind
    milestone: Milestone
    archived: bool = False
    origin: str = "template"
    ref: str | None = None  # where it came from, e.g. a Pulse workflow step's id
    # Lead OS rules; None: anywhere, nothing asked beyond the desk's own defaults.
    moves: tuple[str, ...] | None = None
    needs: tuple[str, ...] | None = None
    reasons: tuple[tuple[str, str], ...] | None = None
    rot_hours: int | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "milestone": self.milestone,
            "archived": self.archived,
            "origin": self.origin,
        }
        if self.ref:
            out["ref"] = self.ref
        if self.moves is not None:
            out["moves"] = list(self.moves)
        if self.needs is not None:
            out["needs"] = list(self.needs)
        if self.reasons is not None:
            out["reasons"] = [{"key": key, "label": label} for key, label in self.reasons]
        if self.rot_hours is not None:
            out["rot_hours"] = self.rot_hours
        return out


# The desk's own Junk stage, for a list without one (every organisation can mark a lead
# Junk from the day Junk arrived).
JUNK: Final[Stage] = Stage("junk", "Junk", "junk", "disqualified")


@dataclass(frozen=True, slots=True)
class Journey:
    version: int  # 0: never saved, the default profile
    industry: str | None
    stages: tuple[Stage, ...]
    saved_at: datetime | None = None
    saved_by: UUID | None = None
    pipeline: str = MAIN_PIPELINE
    by_key: dict[str, Stage] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_key", {stage.key: stage for stage in self.stages})

    @property
    def live(self) -> tuple[Stage, ...]:
        return tuple(stage for stage in self.stages if not stage.archived)

    def resolve(self, kind: str, step: str | None) -> Stage | None:
        """The business's stage for a lead: its own step, else the stage for its kind."""
        if step and step in self.by_key:
            return self.by_key[step]
        if kind in self.by_key and self.by_key[kind].kind == kind:
            return self.by_key[kind]
        live = next((s for s in self.live if s.kind == kind), None)
        found = live or next((s for s in self.stages if s.kind == kind), None)
        if found is None and kind == "junk":
            # A list that keeps Junk in Lost shows a Junk lead in Lost.
            if self.junk_in_lost:
                return next(s for s in self.live if s.kind == "lost")
            return JUNK
        return found

    def stage_for(self, step: str) -> Stage | None:
        """A stage by its key; ``junk`` is the desk's Junk stage in a list without a live
        Junk stage of its own."""
        found = self.by_key.get(step)
        if step == JUNK.key and not self.has_junk and (found is None or found.archived):
            return None if self.junk_in_lost else JUNK
        return found

    @property
    def has_junk(self) -> bool:
        """Whether the list has a live Junk stage of its own."""
        return any(stage.kind == "junk" and not stage.archived for stage in self.stages)

    @property
    def junk_in_lost(self) -> bool:
        """Whether a lead that was never real is Lost here, "Junk / not a real lead": a list
        with no Junk stage whose Lost takes that reason (the sales team's eight stages, owner,
        25 Oct 2026). It has no Junk column, not even the desk's own."""
        return not self.has_junk and any(
            stage.kind == "lost" and any(key == NOT_A_LEAD for key, _ in stage.reasons or ())
            for stage in self.live
        )

    @property
    def ruled(self) -> bool:
        """Whether any stage carries its own moves (the stage list's graph is in force)."""
        return any(stage.moves is not None for stage in self.live)

    def board(self) -> tuple[Stage, ...]:
        """The live stages as the pipeline board shows them: the open ones in the list's
        order, then Won, Lost and Junk (the desk's own Junk when the list has none, unless
        it keeps Junk in Lost)."""
        live = self.live
        groups = (
            [s for s in live if s.kind not in CLOSED_KINDS],
            [s for s in live if s.kind == "won"],
            [s for s in live if s.kind == "lost"],
            [s for s in live if s.kind == "junk"]
            or ([] if self.has_junk or self.junk_in_lost else [JUNK]),
        )
        return tuple(stage for group in groups for stage in group)

    def column(self, kind: str, step: str | None) -> Stage:
        """The board column a lead sits in: its stage, or, when that stage is archived,
        the live stage of its kind (each lead is in exactly one column)."""
        board = self.board()
        found = self.resolve(kind, step)
        if found is not None and any(stage.key == found.key for stage in board):
            return found
        same = next((stage for stage in board if stage.kind == kind), None)
        if same is not None:
            return same
        closed = kind in CLOSED_KINDS
        return next((s for s in board if (s.kind in CLOSED_KINDS) == closed), board[0])

    def label(self, kind: str, step: str | None) -> str | None:
        stage = self.resolve(kind, step)
        return stage.label if stage else None

    def funnel(self) -> tuple[Stage, ...]:
        """The live stages a lead moves through towards a sale, in the business's order.
        Couldn't reach and Lost sit beside it."""
        return tuple(s for s in self.live if s.kind not in ("not_connected", "lost", "junk"))

    def with_earlier(self, key: str) -> list[str]:
        """A funnel stage and every funnel stage before it; any other stage alone."""
        keys = [stage.key for stage in self.funnel()]
        if key in keys:
            return keys[: keys.index(key) + 1]
        return [key]

    def pickable(self) -> tuple[Stage, ...]:
        """What a seller can choose after a call that connected."""
        return tuple(s for s in self.live if s.kind in CONNECTED_KINDS)

    def as_json(self) -> list[dict[str, Any]]:
        return [stage.as_json() for stage in self.stages]


def default_journey() -> Journey:
    profile = template(DEFAULT_TEMPLATE)
    assert profile is not None
    return Journey(
        version=0,
        industry=None,
        stages=tuple(
            Stage(item.key, item.label, item.kind, item.milestone) for item in profile.stages
        ),
    )


def _moves(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    return tuple(dict.fromkeys(k for k in value if isinstance(k, str) and KEY.fullmatch(k)))


def _needs(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    return tuple(dict.fromkeys(need for need in value if need in NEEDS))


def _reasons(value: Any) -> tuple[tuple[str, str], ...] | None:
    if not isinstance(value, list):
        return None
    out: dict[str, str] = {}
    for item in value[:MAX_REASONS]:
        if not isinstance(item, Mapping):
            continue
        key, label = item.get("key"), item.get("label")
        if isinstance(key, str) and KEY.fullmatch(key) and isinstance(label, str):
            text = " ".join(label.split())[:MAX_REASON_LABEL]
            if text:
                out.setdefault(key, text)
    return tuple(out.items())


def _rot(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= MAX_ROT_HOURS else None


def from_rows(stages: Iterable[Mapping[str, Any]]) -> tuple[Stage, ...]:
    """Stored stages back into objects; anything unreadable is skipped, never guessed."""
    out: list[Stage] = []
    for item in stages:
        key, label = item.get("key"), item.get("label")
        kind, milestone = item.get("kind"), item.get("milestone")
        if not isinstance(key, str) or not isinstance(label, str):
            continue
        if kind not in KINDS or milestone not in MILESTONES:
            continue
        origin = item.get("origin") if item.get("origin") in ORIGINS else "custom"
        ref = item.get("ref") if isinstance(item.get("ref"), str) else None
        out.append(
            Stage(
                key,
                label,
                kind,
                milestone,
                item.get("archived") is True,
                str(origin),
                ref,
                _moves(item.get("moves")),
                _needs(item.get("needs")),
                _reasons(item.get("reasons")),
                _rot(item.get("rot_hours")),
            )
        )
    return tuple(out)


def lead_in(pipeline: str) -> Any:
    """Leads in this pipeline; a lead from before pipelines (null) is in main."""
    return func.coalesce(Lead.pipeline_key, MAIN_PIPELINE) == pipeline


def version_in(pipeline: str) -> Any:
    return func.coalesce(LeadJourneyVersion.pipeline_key, MAIN_PIPELINE) == pipeline


def pipeline_of(lead: Lead) -> str:
    return lead.pipeline_key or MAIN_PIPELINE


async def read(db: AsyncSession, tenant_id: UUID, pipeline: str = MAIN_PIPELINE) -> Journey:
    """The pipeline's newest version, or the default profile."""
    row = await db.scalar(
        select(LeadJourneyVersion)
        .where(LeadJourneyVersion.tenant_id == tenant_id, version_in(pipeline))
        .order_by(LeadJourneyVersion.version.desc())
        .limit(1)
    )
    if row is None:
        return replace(default_journey(), pipeline=pipeline)
    stages = from_rows(row.stages if isinstance(row.stages, list) else [])
    if not stages:
        return replace(default_journey(), version=row.version, pipeline=pipeline)
    return Journey(
        version=row.version,
        industry=row.industry,
        stages=stages,
        saved_at=row.created_at,
        saved_by=row.created_by_person_id,
        pipeline=pipeline,
    )


async def lead_counts(db: AsyncSession, tenant_id: UUID, journey: Journey) -> dict[str, int]:
    """How many of the pipeline's leads sit in each of its stages now."""
    counts: dict[str, int] = {}
    rows = await db.execute(
        select(Lead.stage, Lead.step, func.count())
        .where(Lead.tenant_id == tenant_id, lead_in(journey.pipeline))
        .group_by(Lead.stage, Lead.step)
    )
    for kind, step, count in rows.tuples():
        stage = journey.resolve(kind, step)
        if stage is not None:
            counts[stage.key] = counts.get(stage.key, 0) + int(count)
    return counts


async def lead_pairs(
    db: AsyncSession, tenant_id: UUID, journey: Journey
) -> dict[tuple[str, str | None], int]:
    """How many of the pipeline's leads hold each (desk stage, step) pair now."""
    rows = await db.execute(
        select(Lead.stage, Lead.step, func.count())
        .where(Lead.tenant_id == tenant_id, lead_in(journey.pipeline))
        .group_by(Lead.stage, Lead.step)
    )
    return {(str(kind), step): int(count) for kind, step, count in rows.tuples()}


# ----- checking a change ----------------------------------------------------------------


def clean_label(value: Any) -> str:
    if not isinstance(value, str):
        raise JourneyError("Give each stage a name.")
    label = " ".join(value.split())
    if not label:
        raise JourneyError("Give each stage a name.")
    if len(label) > MAX_LABEL:
        raise JourneyError(f"Keep stage names to {MAX_LABEL} letters or fewer.")
    return label


def _unique_key(base: str, taken: set[str]) -> str:
    key, n = base, 2
    while key in taken:
        suffix = f"_{n}"
        key = f"{base[: 40 - len(suffix)]}{suffix}"
        n += 1
    return key


def build(
    wanted: Sequence[Mapping[str, Any]],
    before: Journey,
    counts: Mapping[str, int],
) -> tuple[Stage, ...]:
    """The new list from what the page sent, checked against the one before.

    - A stage without a key is new: its key comes from its name, its meaning is guessed
      from its words when not given, and its desk kind follows from its meaning.
    - A stage from before that the page left out stays, archived: history keeps it.
    - A stage that has leads keeps its desk kind, so those leads stay where they are.
    - A stage keeps its moves, needs, reasons and age limit unless the page sent new ones.
    """
    taken: set[str] = set()
    out: list[Stage] = []
    for item in wanted:
        label = clean_label(item.get("label"))
        key = item.get("key")
        prior = before.by_key.get(key) if isinstance(key, str) else None
        milestone = item.get("milestone")
        if milestone is not None and milestone not in MILESTONES:
            raise JourneyError("Pick what each stage means from the list.")
        kind = item.get("kind")
        if kind is not None and kind not in KINDS:
            raise JourneyError("Pick each stage's type from the list.")
        if prior is None:
            if isinstance(key, str) and key and not KEY.fullmatch(key):
                raise JourneyError("A stage's key can't be read. Reload the page and try again.")
            base = key if isinstance(key, str) and key else slug(label)
            key = _unique_key(base, taken | set(before.by_key))
            milestone = milestone or guess_milestone(label)
            kind = kind or MILESTONE_KIND[milestone]
            origin = str(item["origin"]) if item.get("origin") in ORIGINS else "custom"
            ref = item.get("ref") if isinstance(item.get("ref"), str) else None
            stage = Stage(
                key,
                label,
                kind,
                milestone,
                item.get("archived") is True,
                origin,
                ref,
                _moves(item.get("moves")),
                _needs(item.get("needs")),
                _reasons(item.get("reasons")),
                _rot(item.get("rot_hours")),
            )
        else:
            if key in taken:
                raise JourneyError("Each stage can be in the list only once.")
            kind = kind or prior.kind
            if kind != prior.kind and counts.get(prior.key, 0) > 0:
                raise JourneyError(
                    f"“{prior.label}” has leads in it, so its type stays "
                    "the same. Add a new stage instead."
                )
            stage = Stage(
                prior.key,
                label,
                kind,
                milestone or prior.milestone,
                item.get("archived") is True,
                prior.origin,
                prior.ref,
                _moves(item["moves"]) if "moves" in item else prior.moves,
                _needs(item["needs"]) if "needs" in item else prior.needs,
                _reasons(item["reasons"]) if "reasons" in item else prior.reasons,
                _rot(item["rot_hours"]) if "rot_hours" in item else prior.rot_hours,
            )
        taken.add(stage.key)
        out.append(stage)
    for prior in before.stages:
        if prior.key not in taken and (before.version > 0 or counts.get(prior.key, 0) > 0):
            out.append(replace(prior, archived=True))
            taken.add(prior.key)
    return check(tuple(out))


def check(stages: tuple[Stage, ...]) -> tuple[Stage, ...]:
    """The rules every saved list keeps, in words a manager can act on."""
    live = [stage for stage in stages if not stage.archived]
    if len(stages) > MAX_ALL:
        raise JourneyError("That's too many stages. Remove some archived ones first.")
    if len(live) > MAX_LIVE:
        raise JourneyError(f"Keep it to {MAX_LIVE} stages or fewer. Fewer is easier for sellers.")
    names = [stage.label.casefold() for stage in live]
    if len(set(names)) != len(names):
        raise JourneyError("Two stages have the same name. Give each its own.")
    for kind, words in (("new", "a New stage"), ("not_connected", "a Couldn't reach stage")):
        found = [stage for stage in live if stage.kind == kind]
        if len(found) != 1:
            raise JourneyError(f"Keep exactly one stage as {words}.")
    if sum(1 for stage in live if stage.kind == "junk") > 1:
        raise JourneyError("Keep one Junk stage at most.")
    if live and live[0].kind != "new":
        raise JourneyError("The New stage comes first.")
    if not any(stage.kind == "won" for stage in live):
        raise JourneyError("Keep at least one Won stage, so you can see your sales.")
    if not any(stage.kind == "lost" for stage in live):
        raise JourneyError("Keep at least one Lost stage.")
    return stages


def journey_of(profile: Template, version: int = 1) -> Journey:
    """A profile's stages as a saved list, nothing archived (the legacy nine in tests)."""
    stages = tuple(
        Stage(
            item.key,
            item.label,
            item.kind,
            item.milestone,
            needs=item.needs,
            reasons=item.reasons,
            rot_hours=item.rot_hours,
            moves=item.moves,
        )
        for item in profile.stages
    )
    return Journey(version, profile.id, check(stages))


def from_template(
    template_id: str, before: Journey, counts: Mapping[str, int]
) -> tuple[Stage, ...]:
    """A profile's stages; this business's earlier stages stay, archived."""
    profile = template(template_id)
    if profile is None:
        raise JourneyError("Pick one of the listed kinds of business.")
    out: list[Stage] = []
    taken: set[str] = set()
    renamed: dict[str, str] = {}
    for item in profile.stages:
        key = item.key
        prior = before.by_key.get(key)
        if prior is not None and prior.kind != item.kind and counts.get(prior.key, 0) > 0:
            # Same key, another meaning, and leads in it: keep the old one, give this one
            # a fresh key.
            key = _unique_key(key, set(before.by_key) | taken)
            renamed[item.key] = key
        stage = Stage(
            key,
            item.label,
            item.kind,
            item.milestone,
            needs=item.needs,
            reasons=item.reasons,
            rot_hours=item.rot_hours,
        )
        taken.add(stage.key)
        out.append(stage)
    # The profile's moves name its own keys: follow any stage given a fresh key.
    out = [
        replace(stage, moves=tuple(renamed.get(k, k) for k in item.moves))
        if item.moves is not None
        else stage
        for stage, item in zip(out, profile.stages, strict=True)
    ]
    for prior in before.stages:
        if prior.key not in taken and (before.version > 0 or counts.get(prior.key, 0) > 0):
            out.append(replace(prior, archived=True))
            taken.add(prior.key)
    return check(tuple(out))


def place_choices(before: Journey, after: Journey) -> dict[str, tuple[str, ...]]:
    """Where a manager may put the leads of each of today's columns when a new list
    replaces it: from an open stage to any open stage; Won and Lost only to a stage of
    their own kind (closing needs a person's reason, reopening is a person's call). Junk
    stays Junk; where the new list has no Junk, it goes to Lost ("Junk / not a real lead",
    the sales team's eight stages, owner, 25 Oct 2026)."""
    board = after.board()
    choices: dict[str, tuple[str, ...]] = {}
    no_junk = not any(s.kind == "junk" for s in after.live)
    for stage in before.board():
        if stage.kind == "junk":
            if no_junk:
                choices[stage.key] = tuple(s.key for s in board if s.kind == "lost")
            continue
        if stage.kind in CLOSED_KINDS:
            choices[stage.key] = tuple(s.key for s in board if s.kind == stage.kind)
        else:
            choices[stage.key] = tuple(s.key for s in board if s.kind not in CLOSED_KINDS)
    return choices


def check_places(before: Journey, after: Journey, wanted: Mapping[str, str]) -> dict[str, str]:
    """The template's map (today's column -> the new list's stage), checked."""
    choices = place_choices(before, after)
    places: dict[str, str] = {}
    for old, new in wanted.items():
        allowed = choices.get(old)
        if allowed is None:
            raise JourneyError("Pick where leads go for one of today's stages.")
        if new not in allowed:
            raise JourneyError(
                "Leads in an open stage go to an open stage; Won and Lost keep their kind."
            )
        places[old] = new
    return places


def landing(
    before: Journey, after: Journey, places: Mapping[str, str], kind: str, step: str | None
) -> Stage:
    """The column a lead holds under a new list: the stage picked for its column today,
    else its own stage or the live stage of its kind."""
    picked = places.get(before.column(kind, step).key)
    found = after.stage_for(picked) if picked else None
    return found if found is not None else after.column(kind, step)


async def save(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    stages: tuple[Stage, ...],
    industry: str | None,
    expected_version: int,
    note: str,
    by: UUID,
    now: datetime,
    pipeline: str = MAIN_PIPELINE,
) -> Journey:
    """A new version of the pipeline's list, if nobody saved one since the page read it."""
    current = await read(db, tenant_id, pipeline)
    if current.version != expected_version:
        raise JourneyError("Someone changed the stages just now. Check them and try again.")
    newest = await db.scalar(
        select(func.max(LeadJourneyVersion.version)).where(
            LeadJourneyVersion.tenant_id == tenant_id
        )
    )
    version = int(newest or 0) + 1
    db.add(
        LeadJourneyVersion(
            tenant_id=tenant_id,
            version=version,
            industry=industry,
            stages=[stage.as_json() for stage in stages],
            note=note[:200],
            created_by_person_id=by,
            created_at=now,
            pipeline_key=pipeline,
        )
    )
    await db.flush()
    return Journey(version, industry, stages, now, by, pipeline)


def change_note(before: Journey, after: tuple[Stage, ...]) -> str:
    """One line for the history: what this save changed."""
    old = {stage.key: stage for stage in before.stages}
    added = [s.label for s in after if s.key not in old and not s.archived]
    renamed = [
        f"{old[s.key].label} → {s.label}"
        for s in after
        if s.key in old and old[s.key].label != s.label
    ]
    archived = [s.label for s in after if s.archived and s.key in old and not old[s.key].archived]
    back = [s.label for s in after if not s.archived and s.key in old and old[s.key].archived]
    parts = []
    if added:
        parts.append("Added " + ", ".join(added))
    if renamed:
        parts.append("Renamed " + ", ".join(renamed))
    if archived:
        parts.append("Archived " + ", ".join(archived))
    if back:
        parts.append("Brought back " + ", ".join(back))
    old_live = [s.key for s in before.live]
    new_live = [s.key for s in after if not s.archived]
    if not parts and old_live != new_live:
        parts.append("New order")
    return "; ".join(parts) or "Saved"


def funnel_rank(stage: Stage) -> int:
    return FUNNEL_ORDER.get(stage.milestone, 99)


# A new organisation's first stage list: the sales team's eight stages (owner, 25 Oct 2026:
# "make it the default for new organisations").
NEW_ORGANISATION_TEMPLATE: Final[str] = "inside_sales_demos"


async def start_organisation(db: AsyncSession, tenant_id: UUID, by: UUID, now: datetime) -> bool:
    """Give a new organisation the sales team's stages, once: one that has saved a list of
    its own keeps it. True when installed."""
    before = await read(db, tenant_id, MAIN_PIPELINE)
    if before.version > 0:
        return False
    await save(
        db,
        tenant_id,
        stages=from_template(NEW_ORGANISATION_TEMPLATE, before, {}),
        industry=NEW_ORGANISATION_TEMPLATE,
        expected_version=before.version,
        note="The sales team's stages, for a new organisation",
        by=by,
        now=now,
        pipeline=MAIN_PIPELINE,
    )
    return True
