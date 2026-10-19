"""API keys: made once, shown once, stored as a SHA-256, checked on every request.

A key reads ``sxk_live_`` (production) or ``sxk_test_`` (every other environment)
followed by 40 random letters and digits (about 238 bits). Only its SHA-256 and its
first 13 characters are kept. A key works only in the environment kind it was made
for, only for its own organisation, only within its scopes, until it expires or is
revoked.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, and_, func, insert, or_, select, update

from ac_platform.integrations import scopes as scope_rules
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.models import IntegrationApiKey

ALPHABET = string.ascii_letters + string.digits
SECRET_CHARS = 40
PREFIX_CHARS = 13  # "sxk_live_" and four characters
KEY_PATTERN = re.compile(r"^sxk_(live|test)_[A-Za-z0-9]{40}$")
EXPIRY_DAYS = (30, 90, 365)  # or never
MAX_ACTIVE_KEYS = 25
TOUCH_EVERY = timedelta(seconds=60)

_TABLE = cast(Table, IntegrationApiKey.__table__)


@dataclass(frozen=True, slots=True)
class KeyContext:
    """Who is calling with a key: the organisation and what the key may do."""

    key_id: UUID
    tenant_id: UUID
    scopes: frozenset[str]
    prefix: str
    acting_person_id: UUID  # who made the key, or who approved the app's connection


def mode(environment: str) -> str:
    return "live" if environment == "production" else "test"


def generate(environment: str) -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(SECRET_CHARS))
    return f"sxk_{mode(environment)}_{body}"


def digest(key: str) -> str:
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def state(row: Any, now: datetime) -> str:
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at is not None and row.expires_at <= now:
        return "expired"
    return "active"


def view(row: Any, now: datetime) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "prefix": row.prefix,
        "scopes": list(row.scopes),
        "state": state(row, now),
        "created_at": row.created_at.isoformat(),
        "created_by_person_id": str(row.created_by_person_id),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


def _clean_name(name: object) -> str:
    if not isinstance(name, str):
        raise IntegrationError("name")
    cleaned = " ".join(name.split())
    if not 1 <= len(cleaned) <= 80 or any(ord(ch) < 32 for ch in cleaned):
        raise IntegrationError("name")
    return cleaned


def _active(tenant_id: UUID, now: datetime) -> Any:
    return and_(
        _TABLE.c.tenant_id == tenant_id,
        _TABLE.c.revoked_at.is_(None),
        or_(_TABLE.c.expires_at.is_(None), _TABLE.c.expires_at > now),
    )


def create(
    connection: Any,
    *,
    tenant_id: UUID,
    person_id: UUID,
    name: object,
    scopes: list[object],
    expires_days: int | None,
    environment: str,
    now: datetime,
) -> tuple[str, dict[str, Any]]:
    """A new key: returns the key itself (shown once) and its stored view."""
    cleaned = _clean_name(name)
    try:
        chosen = scope_rules.validate(scopes)
    except scope_rules.ScopeError:
        raise IntegrationError("scopes") from None
    if expires_days is not None and expires_days not in EXPIRY_DAYS:
        raise IntegrationError("expiry")
    active = connection.scalar(
        select(func.count()).select_from(_TABLE).where(_active(tenant_id, now))
    )
    if active >= MAX_ACTIVE_KEYS:
        raise IntegrationError("too_many_keys", 409)
    key = generate(environment)
    row = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "name": cleaned,
        "prefix": key[:PREFIX_CHARS],
        "key_sha256": digest(key),
        "scopes": chosen,
        "created_by_person_id": person_id,
        "created_at": now,
        "expires_at": now + timedelta(days=expires_days) if expires_days else None,
        "last_used_at": None,
        "revoked_at": None,
        "revoked_by_person_id": None,
    }
    connection.execute(insert(_TABLE).values(**row))
    return key, view(SimpleNamespace(**row), now)


def listing(connection: Any, tenant_id: UUID, now: datetime) -> list[dict[str, Any]]:
    rows = connection.execute(
        select(_TABLE).where(_TABLE.c.tenant_id == tenant_id).order_by(_TABLE.c.created_at.desc())
    ).all()
    return [view(row, now) for row in rows]


def revoke(
    connection: Any, *, tenant_id: UUID | None, key_id: UUID, person_id: UUID, now: datetime
) -> tuple[dict[str, Any], bool]:
    """Revoke once. Returns the key's view and whether this call revoked it.

    ``tenant_id`` None is a platform admin acting on any organisation's key.
    """
    where = [_TABLE.c.id == key_id]
    if tenant_id is not None:
        where.append(_TABLE.c.tenant_id == tenant_id)
    row = connection.execute(select(_TABLE).where(*where).with_for_update()).first()
    if row is None:
        raise IntegrationError("not_found", 404)
    if row.revoked_at is not None:
        return view(row, now), False
    connection.execute(
        update(_TABLE)
        .where(_TABLE.c.id == key_id, _TABLE.c.revoked_at.is_(None))
        .values(revoked_at=now, revoked_by_person_id=person_id)
    )
    fresh = connection.execute(select(_TABLE).where(_TABLE.c.id == key_id)).one()
    return view(fresh, now), True


def authenticate(
    connection: Any, presented: str, *, environment: str, now: datetime
) -> KeyContext | None:
    """The key's context, or None for any wrong, unknown, expired or revoked key."""
    match = KEY_PATTERN.fullmatch(presented)
    if match is None or match.group(1) != mode(environment):
        return None
    row = connection.execute(select(_TABLE).where(_TABLE.c.key_sha256 == digest(presented))).first()
    if row is None or state(row, now) != "active":
        return None
    connection.execute(
        update(_TABLE)
        .where(
            _TABLE.c.id == row.id,
            or_(_TABLE.c.last_used_at.is_(None), _TABLE.c.last_used_at < now - TOUCH_EVERY),
        )
        .values(last_used_at=now)
    )
    return KeyContext(
        key_id=row.id,
        tenant_id=row.tenant_id,
        scopes=frozenset(row.scopes),
        prefix=row.prefix,
        acting_person_id=row.created_by_person_id,
    )
