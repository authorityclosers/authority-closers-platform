"""Pseudonymous person ids for Admin's cross-environment usage store (orchestrator, 20 Oct
2026: the owner asked "which user is using how much", and no person id or name may sit in
the shared store).

- Each environment holds its own secret HMAC-SHA-256 key in its own database, as the two
  padded keys of the HMAC construction (``metrics_pseudonym_keys``, one row, made the first
  time Admin's usage pages are read there). It is never answered, logged or exported.
- The usage export (``infra/metrics/usage-metrics-export.sql``) writes each person as ``p_``
  and the first 16 hex characters of HMAC(key, person id), computed with PostgreSQL's
  built-in sha256 from the two pads, so the shared store holds only that.
- Admin turns a pseudonym back into a name only through that same environment's API, for a
  control account signed in there (``names_for``): it hashes this environment's person ids
  and reads names only for the ones asked about.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ac_platform.identity.models import Person
from ac_platform.usage_people.models import MetricsPseudonymKey

PREFIX = "p_"
LENGTH = 16
PATTERN = re.compile(r"^p_[0-9a-f]{16}$")
_BLOCK = 64


def pads(key: bytes) -> tuple[bytes, bytes]:
    """HMAC-SHA-256's inner and outer padded keys for a key of at most 64 bytes."""
    if not 16 <= len(key) <= _BLOCK:
        raise ValueError("key length")
    padded = key.ljust(_BLOCK, b"\0")
    return bytes(b ^ 0x36 for b in padded), bytes(b ^ 0x5C for b in padded)


def pseudonym(inner: bytes, outer: bytes, person_id: UUID | str) -> str:
    """``p_`` and 16 hex characters of HMAC(key, the person id's text), as the export makes it."""
    message = str(person_id).encode("utf-8")
    digest = hashlib.sha256(outer + hashlib.sha256(inner + message).digest()).hexdigest()
    return PREFIX + digest[:LENGTH]


def ensure_key(connection: Any, now: datetime) -> tuple[bytes, bytes]:
    """This environment's pads, made once (random) the first time they are needed."""
    row = connection.execute(
        select(MetricsPseudonymKey.inner_pad, MetricsPseudonymKey.outer_pad).where(
            MetricsPseudonymKey.id == 1
        )
    ).first()
    if row is None:
        inner, outer = pads(os.urandom(32))
        connection.execute(
            insert(MetricsPseudonymKey)
            .values(id=1, inner_pad=inner, outer_pad=outer, created_at=now)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        row = connection.execute(
            select(MetricsPseudonymKey.inner_pad, MetricsPseudonymKey.outer_pad).where(
                MetricsPseudonymKey.id == 1
            )
        ).one()
    return bytes(row[0]), bytes(row[1])


def names_for(connection: Any, wanted: Iterable[str], now: datetime) -> dict[str, str]:
    """Names for the pseudonyms asked about, among this environment's people; others absent."""
    asked = {item for item in wanted if PATTERN.fullmatch(item)}
    if not asked:
        return {}
    inner, outer = ensure_key(connection, now)
    matched: dict[UUID, str] = {}
    for (person_id,) in connection.execute(select(Person.id)):
        made = pseudonym(inner, outer, person_id)
        if made in asked:
            matched[person_id] = made
    if not matched:
        return {}
    names: dict[str, str] = {}
    rows = connection.execute(
        select(Person.id, Person.display_name, Person.first_name).where(
            Person.id.in_(list(matched))
        )
    )
    for person_id, display_name, first_name in rows:
        names[matched[person_id]] = str(display_name or first_name or "A person without a name")
    return names
