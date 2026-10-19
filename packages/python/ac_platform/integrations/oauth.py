"""Connect: OAuth 2.0 authorisation code with PKCE (RFC 6749, 7636; OAuth 2.1 rules).

An app (a "client") sends an organisation's owner or admin to Sales X-Ray's consent
screen. On approval Sales X-Ray returns a one-time code to the app's registered
address; the app swaps it, with its PKCE verifier, for an access token (1 hour) and a
refresh token (30 days, replaced on every use). Tokens act for that one organisation,
within the scopes approved, until the connection is removed.

Rules:
- PKCE S256 for every client; the plain method is refused.
- Redirect addresses match exactly what was registered: https, or http on
  127.0.0.1/localhost for apps on the person's own computer (RFC 8252).
- A code works once, for 10 minutes, for its own client, address and verifier.
- Codes and tokens are stored only as SHA-256. A refresh token used twice ends the
  whole connection (it was stolen or replayed).
- Confidential clients (with a secret) authenticate at the token endpoint; public
  clients (CLIs, MCP hosts) rely on PKCE alone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import Table, insert, or_, select, update

from ac_platform.integrations import scopes as scope_rules
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.models import (
    IntegrationOAuthClient,
    IntegrationOAuthCode,
    IntegrationOAuthGrant,
    IntegrationOAuthToken,
)

_ALPHABET = string.ascii_letters + string.digits
CODE_LIFETIME = timedelta(minutes=10)
ACCESS_LIFETIME = timedelta(hours=1)
REFRESH_LIFETIME = timedelta(days=30)
MAX_REDIRECTS = 5
TOUCH_EVERY = timedelta(seconds=60)
ACCESS_PATTERN = re.compile(r"^sxa_[A-Za-z0-9]{40}$")
REFRESH_PATTERN = re.compile(r"^sxr_[A-Za-z0-9]{48}$")
VERIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")

CLIENTS = cast(Table, IntegrationOAuthClient.__table__)
GRANTS = cast(Table, IntegrationOAuthGrant.__table__)
CODES = cast(Table, IntegrationOAuthCode.__table__)
TOKENS = cast(Table, IntegrationOAuthToken.__table__)


@dataclass(frozen=True, slots=True)
class TokenContext:
    grant_id: UUID
    tenant_id: UUID
    client_id: str
    scopes: frozenset[str]


def _random(prefix: str, size: int) -> str:
    return prefix + "".join(secrets.choice(_ALPHABET) for _ in range(size))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def challenge_for(verifier: str) -> str:
    raw = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def redirect_allowed(uri: str) -> bool:
    try:
        parts = urlsplit(uri)
        parts.port  # noqa: B018 - raises on a bad port
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not parts.hostname:
        return False
    if len(uri) > 512:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}


def _clean_name(name: object) -> str:
    if not isinstance(name, str):
        raise IntegrationError("name")
    cleaned = " ".join(name.split())
    if not 1 <= len(cleaned) <= 80 or any(ord(ch) < 32 for ch in cleaned):
        raise IntegrationError("name")
    return cleaned


def client_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "client_id": row.client_id,
        "name": row.name,
        "redirect_uris": list(row.redirect_uris),
        "confidential": row.client_secret_sha256 is not None,
        "created_at": row.created_at.isoformat(),
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


def register_client(
    connection: Any,
    *,
    tenant_id: UUID | None,
    person_id: UUID | None,
    name: object,
    redirect_uris: list[object],
    confidential: bool,
    now: datetime,
) -> tuple[dict[str, Any], str | None]:
    """A new app. ``tenant_id`` is the organisation that registered it (None: registered
    by the app itself, RFC 7591). Returns its view and, for a confidential client, its
    secret (shown once)."""
    cleaned = _clean_name(name)
    uris = [uri for uri in redirect_uris if isinstance(uri, str)]
    if (
        not uris
        or len(uris) != len(redirect_uris)
        or len(uris) > MAX_REDIRECTS
        or len(set(uris)) != len(uris)
        or not all(redirect_allowed(uri) for uri in uris)
    ):
        raise IntegrationError("redirect_uris")
    secret = _random("sxcs_", 40) if confidential else None
    row = {
        "id": uuid4(),
        "client_id": _random("sxc_", 24),
        "tenant_id": tenant_id,
        "name": cleaned,
        "redirect_uris": uris,
        "client_secret_sha256": digest(secret) if secret else None,
        "created_by_person_id": person_id,
        "created_at": now,
        "revoked_at": None,
    }
    connection.execute(insert(CLIENTS).values(**row))
    return client_view(SimpleNamespace(**row)), secret


def find_client(connection: Any, client_id: str) -> Any:
    row = connection.execute(
        select(CLIENTS).where(CLIENTS.c.client_id == client_id, CLIENTS.c.revoked_at.is_(None))
    ).first()
    if row is None:
        raise IntegrationError("client_unknown", 400)
    return row


def check_request(
    connection: Any,
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    code_challenge: str,
    code_challenge_method: str,
    response_type: str,
) -> tuple[Any, list[str]]:
    """Everything the consent screen must check before it shows anything."""
    client = find_client(connection, client_id)
    if redirect_uri not in client.redirect_uris:
        raise IntegrationError("redirect_uri", 400)
    if response_type != "code":
        raise IntegrationError("unsupported_response_type")
    if code_challenge_method != "S256" or not CHALLENGE_PATTERN.fullmatch(code_challenge):
        raise IntegrationError("pkce")
    try:
        chosen = scope_rules.validate(scope.split())
    except scope_rules.ScopeError:
        raise IntegrationError("invalid_scope") from None
    return client, chosen


def issue_code(
    connection: Any,
    *,
    client: Any,
    tenant_id: UUID,
    person_id: UUID,
    scopes: list[str],
    redirect_uri: str,
    code_challenge: str,
    now: datetime,
) -> str:
    code = _random("sxo_", 40)
    connection.execute(
        insert(CODES).values(
            id=uuid4(),
            code_sha256=digest(code),
            client_id=client.client_id,
            tenant_id=tenant_id,
            person_id=person_id,
            scopes=scopes,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            created_at=now,
            expires_at=now + CODE_LIFETIME,
            used_at=None,
        )
    )
    return code


def _client_auth(client: Any, client_secret: str | None) -> None:
    if client.client_secret_sha256 is None:
        if client_secret:
            raise IntegrationError("invalid_client", 401)
        return
    if not client_secret or not hmac.compare_digest(
        digest(client_secret), client.client_secret_sha256
    ):
        raise IntegrationError("invalid_client", 401)


def _tokens(
    connection: Any, *, grant_id: UUID, now: datetime, replaces: UUID | None = None
) -> dict[str, Any]:
    access, refresh = _random("sxa_", 40), _random("sxr_", 48)
    refresh_id = uuid4()
    connection.execute(
        insert(TOKENS),
        [
            {
                "id": uuid4(),
                "grant_id": grant_id,
                "kind": "access",
                "token_sha256": digest(access),
                "created_at": now,
                "expires_at": now + ACCESS_LIFETIME,
                "revoked_at": None,
                "replaced_by": None,
            },
            {
                "id": refresh_id,
                "grant_id": grant_id,
                "kind": "refresh",
                "token_sha256": digest(refresh),
                "created_at": now,
                "expires_at": now + REFRESH_LIFETIME,
                "revoked_at": None,
                "replaced_by": None,
            },
        ],
    )
    if replaces is not None:
        connection.execute(
            update(TOKENS)
            .where(TOKENS.c.id == replaces)
            .values(revoked_at=now, replaced_by=refresh_id)
        )
    grant = connection.execute(select(GRANTS.c.scopes).where(GRANTS.c.id == grant_id)).one()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_LIFETIME.total_seconds()),
        "refresh_token": refresh,
        "scope": " ".join(grant.scopes),
    }


def exchange_code(
    connection: Any,
    *,
    code: str,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    code_verifier: str,
    now: datetime,
) -> dict[str, Any]:
    client = find_client(connection, client_id)
    _client_auth(client, client_secret)
    row = connection.execute(
        select(CODES).where(CODES.c.code_sha256 == digest(code)).with_for_update()
    ).first()
    if (
        row is None
        or row.client_id != client_id
        or row.used_at is not None
        or row.expires_at <= now
        or row.redirect_uri != redirect_uri
        or not VERIFIER_PATTERN.fullmatch(code_verifier)
        or not hmac.compare_digest(challenge_for(code_verifier), row.code_challenge)
    ):
        if row is not None and row.used_at is not None:
            # A code used twice: end what the first use made (RFC 6749 §4.1.2).
            _end_grants(connection, client_id, row.tenant_id, now)
        raise IntegrationError("invalid_grant", 400)
    connection.execute(update(CODES).where(CODES.c.id == row.id).values(used_at=now))
    grant_id = uuid4()
    connection.execute(
        insert(GRANTS).values(
            id=grant_id,
            client_id=client_id,
            tenant_id=row.tenant_id,
            person_id=row.person_id,
            scopes=list(row.scopes),
            created_at=now,
            last_used_at=None,
            revoked_at=None,
            revoked_by=None,
        )
    )
    return _tokens(connection, grant_id=grant_id, now=now)


def _end_grants(connection: Any, client_id: str, tenant_id: UUID, now: datetime) -> None:
    ids = [
        row.id
        for row in connection.execute(
            select(GRANTS.c.id).where(
                GRANTS.c.client_id == client_id,
                GRANTS.c.tenant_id == tenant_id,
                GRANTS.c.revoked_at.is_(None),
            )
        )
    ]
    for grant_id in ids:
        revoke_grant(connection, grant_id=grant_id, by="security:replay", now=now)


def refresh(
    connection: Any,
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str | None,
    now: datetime,
) -> dict[str, Any]:
    client = find_client(connection, client_id)
    _client_auth(client, client_secret)
    if not REFRESH_PATTERN.fullmatch(refresh_token):
        raise IntegrationError("invalid_grant", 400)
    row = connection.execute(
        select(TOKENS, GRANTS.c.client_id, GRANTS.c.revoked_at.label("grant_revoked"))
        .join(GRANTS, GRANTS.c.id == TOKENS.c.grant_id)
        .where(TOKENS.c.token_sha256 == digest(refresh_token), TOKENS.c.kind == "refresh")
        .with_for_update(of=TOKENS)
    ).first()
    if row is None or row.client_id != client_id:
        raise IntegrationError("invalid_grant", 400)
    if row.revoked_at is not None:
        # A replaced refresh token came back: someone else has a copy. End the connection.
        revoke_grant(connection, grant_id=row.grant_id, by="security:refresh_reuse", now=now)
        raise IntegrationError("invalid_grant", 400)
    if row.grant_revoked is not None or row.expires_at <= now:
        raise IntegrationError("invalid_grant", 400)
    return _tokens(connection, grant_id=row.grant_id, now=now, replaces=row.id)


def authenticate(connection: Any, presented: str, *, now: datetime) -> TokenContext | None:
    if not ACCESS_PATTERN.fullmatch(presented):
        return None
    row = connection.execute(
        select(
            TOKENS.c.expires_at,
            TOKENS.c.revoked_at,
            GRANTS.c.id.label("grant_id"),
            GRANTS.c.tenant_id,
            GRANTS.c.client_id,
            GRANTS.c.scopes,
            GRANTS.c.revoked_at.label("grant_revoked"),
            GRANTS.c.last_used_at,
        )
        .join(GRANTS, GRANTS.c.id == TOKENS.c.grant_id)
        .where(TOKENS.c.token_sha256 == digest(presented), TOKENS.c.kind == "access")
    ).first()
    if (
        row is None
        or row.revoked_at is not None
        or row.grant_revoked is not None
        or row.expires_at <= now
    ):
        return None
    connection.execute(
        update(GRANTS)
        .where(
            GRANTS.c.id == row.grant_id,
            or_(GRANTS.c.last_used_at.is_(None), GRANTS.c.last_used_at < now - TOUCH_EVERY),
        )
        .values(last_used_at=now)
    )
    return TokenContext(row.grant_id, row.tenant_id, row.client_id, frozenset(row.scopes))


def revoke_grant(connection: Any, *, grant_id: UUID, by: str, now: datetime) -> bool:
    changed = connection.execute(
        update(GRANTS)
        .where(GRANTS.c.id == grant_id, GRANTS.c.revoked_at.is_(None))
        .values(revoked_at=now, revoked_by=by[:160])
    ).rowcount
    connection.execute(
        update(TOKENS)
        .where(TOKENS.c.grant_id == grant_id, TOKENS.c.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return bool(changed)


def revoke_token(connection: Any, *, token: str, client_id: str, now: datetime) -> None:
    """RFC 7009: revoking a refresh token ends its connection; an access token, itself.
    Unknown tokens are not an error."""
    row = connection.execute(
        select(TOKENS.c.id, TOKENS.c.kind, TOKENS.c.grant_id, GRANTS.c.client_id)
        .join(GRANTS, GRANTS.c.id == TOKENS.c.grant_id)
        .where(TOKENS.c.token_sha256 == digest(token))
    ).first()
    if row is None or row.client_id != client_id:
        return
    if row.kind == "refresh":
        revoke_grant(connection, grant_id=row.grant_id, by=f"client:{client_id}", now=now)
    else:
        connection.execute(
            update(TOKENS)
            .where(TOKENS.c.id == row.id, TOKENS.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )


def _connection_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "app": row.name,
        "client_id": row.client_id,
        "scopes": list(row.scopes),
        "granted_by_person_id": str(row.person_id),
        "created_at": row.created_at.isoformat(),
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


def connections(connection: Any, tenant_id: UUID) -> list[dict[str, Any]]:
    """The organisation's connected apps, newest first, with the app's name."""
    rows = connection.execute(
        select(GRANTS, CLIENTS.c.name)
        .join(CLIENTS, CLIENTS.c.client_id == GRANTS.c.client_id)
        .where(GRANTS.c.tenant_id == tenant_id)
        .order_by(GRANTS.c.created_at.desc())
    ).all()
    return [_connection_view(row) for row in rows]


def all_connections(connection: Any, limit: int = 2000) -> list[dict[str, Any]]:
    """Every organisation's connected apps, for platform admins."""
    rows = connection.execute(
        select(GRANTS, CLIENTS.c.name)
        .join(CLIENTS, CLIENTS.c.client_id == GRANTS.c.client_id)
        .order_by(GRANTS.c.created_at.desc())
        .limit(limit)
    ).all()
    return [{**_connection_view(row), "tenant_id": str(row.tenant_id)} for row in rows]


def connection_row(connection: Any, grant_id: UUID) -> dict[str, Any] | None:
    """One connection with its organisation, for platform admins."""
    row = connection.execute(
        select(GRANTS, CLIENTS.c.name)
        .join(CLIENTS, CLIENTS.c.client_id == GRANTS.c.client_id)
        .where(GRANTS.c.id == grant_id)
    ).first()
    return None if row is None else {**_connection_view(row), "tenant_id": str(row.tenant_id)}


def tenant_clients(connection: Any, tenant_id: UUID) -> list[dict[str, Any]]:
    rows = connection.execute(
        select(CLIENTS)
        .where(CLIENTS.c.tenant_id == tenant_id)
        .order_by(CLIENTS.c.created_at.desc())
    ).all()
    return [client_view(row) for row in rows]


def revoke_client(connection: Any, *, tenant_id: UUID, client_row_id: UUID, now: datetime) -> bool:
    row = connection.execute(
        select(CLIENTS).where(CLIENTS.c.id == client_row_id, CLIENTS.c.tenant_id == tenant_id)
    ).first()
    if row is None:
        raise IntegrationError("not_found", 404)
    if row.revoked_at is not None:
        return False
    connection.execute(update(CLIENTS).where(CLIENTS.c.id == row.id).values(revoked_at=now))
    for grant in connection.execute(
        select(GRANTS.c.id).where(
            GRANTS.c.client_id == row.client_id, GRANTS.c.revoked_at.is_(None)
        )
    ).all():
        revoke_grant(connection, grant_id=grant.id, by="client_removed", now=now)
    return True
