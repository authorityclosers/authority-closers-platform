"""A workspace's earlier import choices, and the Facebook lead form preset (owner's picks,
17 Nov 2026: lead import I2, "We'll remember this for your next import"; study 01 §6).

Three kinds of memory (table ``lead_desk_import_memory``, migration 0160):
- "column": a file header (as key()) and the field it filled, or KEEP (kept on the lead as
  a detail) or SKIP (not imported);
- "stage": a stage word in a file and the stage key it was said to mean;
- "owner": a name in a file's owner column and the teammate it was said to be.

Only owners and admins teach it (their imports); every import starts from it. A choice made
again replaces the old one. Words and choices only, never a lead's data.

The Facebook lead form preset: Meta's lead export (``id, created_time, ad_id, ad_name,
adset_id, adset_name, campaign_id, campaign_name, form_id, form_name, is_organic, platform``,
then one column per question) is recognised by its headers. Its ids are not imported, and the
``p:`` / ``l:`` / ``f:`` prefixes Meta puts on cells are taken off.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk.capture import key as header_key
from ac_platform.lead_desk.models import LeadImportMemory

KEEP: Final[str] = "_keep"
SKIP: Final[str] = "_skip"
# The fields a remembered column may fill (the import's own: FIELDS and stage, owner, source,
# and an old lead's enquiry date and campaign).
COLUMN_VALUES: Final[frozenset[str]] = frozenset(
    {
        "name",
        "phone",
        "email",
        "company",
        "city",
        "language",
        "interest",
        "stage",
        "owner",
        "source",
        "received",
        "campaign",
        KEEP,
        SKIP,
    }
)
# Words remembered per kind, at most: older ones are still used, new ones beyond are not kept.
MAX_WORDS: Final[int] = 400

META_FORM: Final[str] = "Facebook lead form"
# Meta's lead export, by its own columns (after key()): any one set names the file.
META_SIGNATURES: Final[tuple[frozenset[str], ...]] = (
    frozenset({"ad_id", "form_id"}),
    frozenset({"form_name", "is_organic"}),
    frozenset({"adset_id", "campaign_id", "created_time"}),
)
# Meta's ids: kept out of the leads (they say nothing to a seller).
META_SKIP: Final[frozenset[str]] = frozenset(
    {"ad_id", "adset_id", "campaign_id", "form_id", "is_organic"}
)
# "p:+919876543210", "l:1234", "f:5678", "ag:…", "as:…", "c:…": Meta's cell prefixes.
_META_PREFIX = re.compile(r"\A(?:p|l|f|ag|as|c):(?=\S)")


def is_meta_form(headers: Iterable[str]) -> bool:
    keys = {header_key(header) for header in headers}
    return any(signature <= keys for signature in META_SIGNATURES)


def meta_cell(value: str) -> str:
    """A Meta export cell without its prefix ("p:+9198…" → "+9198…")."""
    return _META_PREFIX.sub("", value, count=1)


def meta_rows(rows: Iterable[Mapping[str, str]]) -> tuple[dict[str, str], ...]:
    return tuple({name: meta_cell(value) for name, value in row.items()} for row in rows)


@dataclass(slots=True)
class Memory:
    """A workspace's import memory, keyed by key() of the word."""

    columns: dict[str, str] = field(default_factory=dict)
    stages: dict[str, str] = field(default_factory=dict)
    owners: dict[str, UUID] = field(default_factory=dict)

    def column(self, header: str) -> str | None:
        return self.columns.get(header_key(header))

    def stage(self, word: str) -> str | None:
        return self.stages.get(header_key(word))

    def owner(self, name: str) -> UUID | None:
        return self.owners.get(header_key(name))


async def read(db: AsyncSession, tenant_id: UUID) -> Memory:
    memory = Memory()
    rows = await db.execute(
        select(LeadImportMemory.kind, LeadImportMemory.word, LeadImportMemory.value).where(
            LeadImportMemory.tenant_id == tenant_id
        )
    )
    for kind, word, value in rows.tuples():
        if kind == "column" and value in COLUMN_VALUES:
            memory.columns[word] = value
        elif kind == "stage":
            memory.stages[word] = value
        elif kind == "owner":
            try:
                memory.owners[word] = UUID(value)
            except ValueError:
                continue
    return memory


def remembered_mapping(
    headers: Iterable[str], mapping: Mapping[str, str], memory: Memory
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    """The preview's mapping with the workspace's earlier choices laid over it: each header
    remembered for a field takes that field (from whatever had it), and the headers
    remembered as not imported. Returns (mapping, remembered headers, headers to skip)."""
    chosen = dict(mapping)
    remembered: list[str] = []
    skip: list[str] = []
    for header in headers:
        value = memory.column(header)
        if value is None:
            continue
        remembered.append(header)
        # The header no longer fills what the suggestion gave it.
        for name, current in list(chosen.items()):
            if current == header:
                del chosen[name]
        if value == SKIP:
            skip.append(header)
        elif value != KEEP:
            chosen[value] = header
    return chosen, tuple(remembered), tuple(skip)


async def remember(
    db: AsyncSession,
    tenant_id: UUID,
    person_id: UUID | None,
    now: datetime,
    *,
    columns: Mapping[str, str],
    stages: Mapping[str, str],
    owners: Mapping[str, UUID],
) -> int:
    """Keep these choices for the workspace's next import (a newer choice replaces the old).
    ``columns``: header → field, KEEP or SKIP. Returns how many words were written."""
    wanted: dict[tuple[str, str], str] = {}
    for header, value in columns.items():
        if value in COLUMN_VALUES and (word := header_key(header)[:120]):
            wanted[("column", word)] = value
    for word, stage in stages.items():
        if stage and (keyed := header_key(word)[:120]):
            wanted[("stage", keyed)] = stage[:80]
    for name, person in owners.items():
        if keyed := header_key(name)[:120]:
            wanted[("owner", keyed)] = str(person)
    if not wanted:
        return 0
    existing = {
        (row.kind, row.word): row
        for row in (
            await db.scalars(
                select(LeadImportMemory).where(
                    LeadImportMemory.tenant_id == tenant_id,
                    LeadImportMemory.kind.in_({kind for kind, _ in wanted}),
                    LeadImportMemory.word.in_({word for _, word in wanted}),
                )
            )
        ).all()
    }
    counts: dict[str, int] = {
        kind: int(count)
        for kind, count in (
            await db.execute(
                select(LeadImportMemory.kind, func.count())
                .where(LeadImportMemory.tenant_id == tenant_id)
                .group_by(LeadImportMemory.kind)
            )
        ).tuples()
    }
    written = 0
    for (kind, word), value in wanted.items():
        row = existing.get((kind, word))
        if row is not None:
            if row.value != value:
                row.value = value
                row.updated_by_person_id = person_id
                row.updated_at = now
                written += 1
            continue
        if counts.get(kind, 0) >= MAX_WORDS:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        db.add(
            LeadImportMemory(
                id=uuid4(),
                tenant_id=tenant_id,
                kind=kind,
                word=word,
                value=value,
                updated_by_person_id=person_id,
                updated_at=now,
            )
        )
        written += 1
    await db.flush()
    return written
