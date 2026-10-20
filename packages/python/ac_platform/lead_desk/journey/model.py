"""A business's own lead stages: one list per organisation, saved as versions.

Every save adds a version (``lead_desk_journey_versions``); nothing is overwritten,
and a stage that was ever used stays in the list, archived, so old leads and old
history keep their words. An organisation that never saved one works with the
"Any business" profile, whose stage keys are the desk's own six stages, so nothing
changes for it until it picks its own.

A lead keeps the desk's stage (``Lead.stage``, the stage's kind) and, when a seller
picked one of the business's own stages, that stage's key (``Lead.step``). A lead
with no step is in the business's stage for its kind (see ``Journey.resolve``).
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
    Kind,
    Milestone,
    guess_milestone,
    slug,
    template,
)
from ac_platform.lead_desk.models import Lead, LeadJourneyVersion

MAX_LIVE: Final[int] = 16
MAX_ALL: Final[int] = 80
MAX_LABEL: Final[int] = 40
KEY: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
ORIGINS: Final[frozenset[str]] = frozenset({"template", "custom", "pulse", "suggested"})
OPEN_KINDS: Final[frozenset[str]] = frozenset({"follow_up", "interested"})
# The desk stages a seller picks after a call that connected.
CONNECTED_KINDS: Final[frozenset[str]] = frozenset({"follow_up", "interested", "won", "lost"})


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
        return out


@dataclass(frozen=True, slots=True)
class Journey:
    version: int  # 0: never saved, the default profile
    industry: str | None
    stages: tuple[Stage, ...]
    saved_at: datetime | None = None
    saved_by: UUID | None = None
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
        return live or next((s for s in self.stages if s.kind == kind), None)

    def label(self, kind: str, step: str | None) -> str | None:
        stage = self.resolve(kind, step)
        return stage.label if stage else None

    def funnel(self) -> tuple[Stage, ...]:
        """The live stages a lead moves through towards a sale, in the business's order.
        Couldn't reach and Lost sit beside it."""
        return tuple(s for s in self.live if s.kind not in ("not_connected", "lost"))

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
            Stage(key, label, kind, milestone, item.get("archived") is True, str(origin), ref)
        )
    return tuple(out)


async def read(db: AsyncSession, tenant_id: UUID) -> Journey:
    """The organisation's newest version, or the default profile."""
    row = await db.scalar(
        select(LeadJourneyVersion)
        .where(LeadJourneyVersion.tenant_id == tenant_id)
        .order_by(LeadJourneyVersion.version.desc())
        .limit(1)
    )
    if row is None:
        return default_journey()
    stages = from_rows(row.stages if isinstance(row.stages, list) else [])
    if not stages:
        return replace(default_journey(), version=row.version)
    return Journey(
        version=row.version,
        industry=row.industry,
        stages=stages,
        saved_at=row.created_at,
        saved_by=row.created_by_person_id,
    )


async def lead_counts(db: AsyncSession, tenant_id: UUID, journey: Journey) -> dict[str, int]:
    """How many leads sit in each of the business's stages now."""
    counts: dict[str, int] = {}
    rows = await db.execute(
        select(Lead.stage, Lead.step, func.count())
        .where(Lead.tenant_id == tenant_id)
        .group_by(Lead.stage, Lead.step)
    )
    for kind, step, count in rows.tuples():
        stage = journey.resolve(kind, step)
        if stage is not None:
            counts[stage.key] = counts.get(stage.key, 0) + int(count)
    return counts


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
            origin = item.get("origin") if item.get("origin") in ORIGINS else "custom"
            ref = item.get("ref") if isinstance(item.get("ref"), str) else None
            stage = Stage(key, label, kind, milestone, item.get("archived") is True, origin, ref)
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
    if live and live[0].kind != "new":
        raise JourneyError("The New stage comes first.")
    if not any(stage.kind == "won" for stage in live):
        raise JourneyError("Keep at least one Won stage, so you can see your sales.")
    if not any(stage.kind == "lost" for stage in live):
        raise JourneyError("Keep at least one Lost stage.")
    return stages


def from_template(
    template_id: str, before: Journey, counts: Mapping[str, int]
) -> tuple[Stage, ...]:
    """A profile's stages; this business's earlier stages stay, archived."""
    profile = template(template_id)
    if profile is None:
        raise JourneyError("Pick one of the listed kinds of business.")
    wanted = [
        {"key": item.key, "label": item.label, "milestone": item.milestone, "kind": item.kind}
        for item in profile.stages
    ]
    out: list[Stage] = []
    taken: set[str] = set()
    for item in wanted:
        prior = before.by_key.get(item["key"])
        if prior is not None and prior.kind != item["kind"] and counts.get(prior.key, 0) > 0:
            # Same key, another meaning, and leads in it: keep the old one, give this one
            # a fresh key.
            item = {**item, "key": _unique_key(item["key"], set(before.by_key) | taken)}
        stage = Stage(item["key"], item["label"], item["kind"], item["milestone"])
        taken.add(stage.key)
        out.append(stage)
    for prior in before.stages:
        if prior.key not in taken and (before.version > 0 or counts.get(prior.key, 0) > 0):
            out.append(replace(prior, archived=True))
            taken.add(prior.key)
    return check(tuple(out))


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
) -> Journey:
    """A new version, if nobody saved one since the page read it."""
    current = await read(db, tenant_id)
    if current.version != expected_version:
        raise JourneyError("Someone changed the stages just now. Check them and try again.")
    version = current.version + 1
    db.add(
        LeadJourneyVersion(
            tenant_id=tenant_id,
            version=version,
            industry=industry,
            stages=[stage.as_json() for stage in stages],
            note=note[:200],
            created_by_person_id=by,
            created_at=now,
        )
    )
    await db.flush()
    return Journey(version, industry, stages, now, by)


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
