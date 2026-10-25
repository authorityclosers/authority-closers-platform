"""Staff keys: the Admin command line and MCP sign in with a key (orchestrator's go, 19 Oct 2026).

- A verified AC control account makes a key for themself in Admin, within 10 minutes of
  signing in, at most two active at a time. The key is shown once; only its SHA-256 is
  kept. A key lasts 30 days and can be revoked at once (by its owner or any other
  control account).
- Behind each key is its own session in the operations workspace, so on every request
  the person's live account, membership and role are checked exactly as for a browser,
  and audit rows name that session.
- A key reaches only the settings registry's routes, on the Admin host: reads with
  settings:read, the registry's change routes with settings:write. Billing, payment, plan
  prices, credit balances and secrets stay browser-only. At most 60 requests a minute.
  Every change made with a key is also audited as admin.staff_key_used with its prefix.
- With admin:read (Phase 6, orchestrator 20 Oct: AI agents operate Admin), a key also
  makes content-free reads: organisations, the calls list, one call's stage map, the
  review queue, analysis health and product telemetry (its overview and daily export).
  Ids, states, times, counts, costs and model names only; transcripts, quotes, facts'
  values and report text stay in the browser, behind their own audited reads.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.admin_settings.models import AdminStaffKey
from ac_platform.admin_settings.registry import SETTINGS
from ac_platform.admin_settings.staff_key_email import enqueue_staff_key_email
from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticationRequired, require_admin_surface
from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule
from ac_platform.identity.application import AsyncIdentityApplication, ResolvedActorContext
from ac_platform.identity.models import Session
from ac_platform.kernel.authz import ActorContext

SCOPES = ("settings:read", "settings:write", "admin:read")
READ_SCOPE = "admin:read"
_ID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# The one-click raises Admin offers beside the settings: each saves through its own
# area, audited there as a cap raise; a key needs settings:write, as for any change.
ONE_CLICK: tuple[tuple[str, str], ...] = (
    ("POST", "/v1/admin/call-data/raise"),
    ("POST", "/v1/admin/lead-desk-ai/raise"),
)
# GET only, and content-free by design (see the module note).
READS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"^/v1/platform/workspaces$",
        r"^/v1/admin/conversation/calls$",
        rf"^/v1/admin/call-data/calls/{_ID}/map$",
        r"^/v1/admin/conversation/review/queue$",
        r"^/v1/admin/conversation/health$",
        # Product telemetry: counts, timings and pseudonyms (owner, 24 Oct 2026; the cost
        # optimiser reads the daily export with a key).
        r"^/v1/admin/telemetry/overview$",
        r"^/v1/admin/telemetry/daily$",
        # The improvement loop: devices, release comparison, the release gate (Align 3's
        # train reads it with a key) and what to fix next.
        r"^/v1/admin/telemetry/devices$",
        r"^/v1/admin/telemetry/compare$",
        r"^/v1/admin/telemetry/gate$",
        r"^/v1/admin/telemetry/fix-next$",
        # Where people get stuck, by week (owner, 25 Oct 2026; builders read it with a key).
        r"^/v1/admin/telemetry/friction$",
    )
)
MAX_ACTIVE = 2
LIFETIME = timedelta(days=30)
FRESH_SIGN_IN = timedelta(minutes=10)
USE_EVERY = timedelta(seconds=60)
ENVIRONMENT_TAG = {"production": "live", "staging": "stg"}
RULE = RateLimitRule(
    name="admin-staff-key",
    method="ANY",
    path=re.compile(r"^/v1/admin/"),
    capacity=60,
    refill_seconds=60.0,
)
# Never with a key, whatever the registry says: these stay in the browser.
BLOCKED = re.compile(r"billing|payment|price|plan|credit|secret|password|staff-keys", re.I)

CREATED, REVOKED, USED = (
    "admin.staff_key_created",
    "admin.staff_key_revoked",
    "admin.staff_key_used",
)


def route_scope(routes: dict[tuple[str, str], str], method: str, path: str) -> str | None:
    """The scope a key needs for this request, or None when no key may make it."""
    if BLOCKED.search(path):
        return None
    scope = routes.get((method, path))
    if scope is None and method == "GET" and any(read.match(path) for read in READS):
        return READ_SCOPE
    return scope


def digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_routes() -> dict[tuple[str, str], str]:
    """(method, path) a key may reach, with the scope each needs."""
    routes: dict[tuple[str, str], str] = {("GET", "/v1/admin/settings"): "settings:read"}
    for item in SETTINGS:
        routes[("GET", item.read.path)] = "settings:read"
        if item.write is not None and not BLOCKED.search(item.write.path):
            routes[(item.write.method, item.write.path)] = "settings:write"
    for route in ONE_CLICK:
        routes[route] = "settings:write"
    return {route: scope for route, scope in routes.items() if not BLOCKED.search(route[1])}


class StaffKeys:
    """Make, list and revoke keys: browser only, verified control accounts."""

    def __init__(self, database: AsyncSession, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def _admit(self, actor: ActorContext) -> None:
        if (
            self.settings.operations_tenant_id is None
            or actor.tenant_id != self.settings.operations_tenant_id
        ):
            raise ConversationDenied("Staff keys need the AC operations workspace.")
        await ConversationProviderAdmin(ConversationApplication(self.database)).admit(actor)

    async def mine(self, actor: ActorContext, *, now: datetime) -> dict[str, Any]:
        await self._admit(actor)
        rows = (
            await self.database.scalars(
                select(AdminStaffKey)
                .where(AdminStaffKey.person_id == actor.person_id)
                .order_by(AdminStaffKey.created_at.desc())
            )
        ).all()
        return {
            "keys": [row.view(now) for row in rows],
            "limits": {
                "active": MAX_ACTIVE,
                "days": LIFETIME.days,
                "fresh_minutes": int(FRESH_SIGN_IN.total_seconds() // 60),
                "scopes": list(SCOPES),
            },
        }

    async def create(
        self,
        actor: ActorContext,
        identity: AsyncIdentityApplication,
        *,
        name: str,
        scopes: list[str],
        now: datetime,
    ) -> dict[str, Any]:
        await self._admit(actor)
        signed_in = await self.database.scalar(
            select(Session.created_at).where(Session.id == actor.session_id)
        )
        if signed_in is None or now - signed_in > FRESH_SIGN_IN:
            raise ConversationDenied(
                "Sign in again to make a key: it needs a sign-in within the last 10 minutes."
            )
        label = name.strip()
        if not 1 <= len(label) <= 80:
            raise ConversationError("Name the key (1 to 80 characters).")
        chosen = sorted(set(scopes))
        if not chosen or not set(chosen) <= set(SCOPES) or "settings:read" not in chosen:
            raise ConversationError(
                "Choose settings:read, with settings:write if it may change settings and"
                " admin:read if it may read calls, organisations, the review queue and health."
            )
        active = await self.database.scalar(
            select(func.count())
            .select_from(AdminStaffKey)
            .where(
                AdminStaffKey.person_id == actor.person_id,
                AdminStaffKey.revoked_at.is_(None),
                AdminStaffKey.expires_at > now,
            )
        )
        if int(active or 0) >= MAX_ACTIVE:
            raise ConversationError(f"You hold {MAX_ACTIVE} active keys: revoke one first.")
        assert self.settings.operations_tenant_id is not None
        issued = await identity.issue_authenticated_session(
            actor.person_id, user_agent="Admin staff key", now=now
        )
        await identity.select_tenant(issued.token, self.settings.operations_tenant_id, now=now)
        tag = ENVIRONMENT_TAG.get(self.settings.environment, "dev")
        key = f"ac_{tag}_{issued.token}"
        row = AdminStaffKey(
            id=uuid4(),
            tenant_id=self.settings.operations_tenant_id,
            person_id=actor.person_id,
            session_id=issued.metadata.id,
            name=label,
            prefix=key[: len(tag) + 12],
            secret_sha256=digest(key),
            scopes=chosen,
            created_at=now,
            expires_at=min(now + LIFETIME, issued.metadata.expires_at),
            last_used_at=None,
            revoked_at=None,
            revoked_by_person_id=None,
        )
        self.database.add(row)
        await self.database.flush()
        await AuditRepository(self.database).append_for_actor(
            actor,
            action=CREATED,
            resource_type="admin_staff_key",
            resource_id=row.id,
            payload={
                "prefix": row.prefix,
                "name": row.name,
                "scopes": chosen,
                "expires_at": row.expires_at.isoformat(),
                "environment": self.settings.environment,
            },
        )
        if self.settings.environment == "production":
            # The control account hears of every production key (orchestrator, 19 Oct).
            await enqueue_staff_key_email(self.database, row)
        # The key itself, once; it is never stored or shown again.
        return {**row.view(now), "key": key}

    async def revoke(self, actor: ActorContext, key_id: UUID, *, now: datetime) -> dict[str, Any]:
        await self._admit(actor)
        row = await self.database.get(AdminStaffKey, key_id, with_for_update=True)
        if row is None:
            raise ConversationNotFound("That key is not here.")
        if row.revoked_at is None:
            row.revoked_at = now
            row.revoked_by_person_id = actor.person_id
            await self.database.execute(
                update(Session)
                .where(Session.id == row.session_id, Session.revoked_at.is_(None))
                .values(revoked_at=now, revocation_reason="staff key revoked")
            )
            await self.database.flush()
            await AuditRepository(self.database).append_for_actor(
                actor,
                action=REVOKED,
                resource_type="admin_staff_key",
                resource_id=row.id,
                payload={"prefix": row.prefix, "owner_person_id": str(row.person_id)},
            )
        return row.view(now)


class StaffKeyGuard:
    """Installed as app.state.staff_keys: auth hands it every request signed with a key."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.limiter = InMemoryTokenBucketLimiter()
        self.routes = key_routes()

    async def resolve(
        self,
        request: Request,
        database: AsyncSession,
        identity: AsyncIdentityApplication,
        key: str,
    ) -> tuple[ResolvedActorContext, str]:
        now = datetime.now(UTC)
        row = await database.scalar(
            select(AdminStaffKey).where(AdminStaffKey.secret_sha256 == digest(key))
        )
        if row is None:
            raise AuthenticationRequired("This staff key is not valid.")
        if row.revoked_at is not None:
            raise AuthenticationRequired("This staff key was revoked.")
        if row.expires_at <= now:
            raise AuthenticationRequired("This staff key has expired.")
        token = key.split("_", 2)[2]
        resolved = await identity.resolve_actor(token)
        if (
            resolved.actor.session_id != row.session_id
            or resolved.actor.tenant_id != row.tenant_id
            or resolved.actor.person_id != row.person_id
        ):
            raise AuthenticationRequired("This staff key is not valid.")
        request.state.staff_key_row = row
        return resolved, token

    async def admit(
        self, request: Request, database: AsyncSession, resolved: ResolvedActorContext
    ) -> None:
        row: AdminStaffKey = request.state.staff_key_row
        require_admin_surface(request, self.settings)
        allowed, retry, _ = await self.limiter.consume(str(row.id), RULE)
        if not allowed:
            raise HTTPException(
                429, "Too many requests with this key.", headers={"Retry-After": str(retry)}
            )
        method, path = request.method.upper(), request.url.path
        scope = route_scope(self.routes, method, path)
        if scope is None:
            raise HTTPException(
                403,
                "A staff key reaches only Admin settings and content-free reads;"
                " this stays in the browser.",
            )
        if scope not in row.scopes:
            raise HTTPException(403, f"This key does not hold {scope}.")
        try:
            await ConversationProviderAdmin(ConversationApplication(database)).admit(resolved.actor)
        except ConversationError as error:
            raise HTTPException(403, str(error)) from None
        now = datetime.now(UTC)
        if row.last_used_at is None or now - row.last_used_at >= USE_EVERY:
            row.last_used_at = now
            await database.flush()
        if method != "GET":
            await AuditRepository(database).append_for_actor(
                resolved.actor,
                action=USED,
                resource_type="admin_staff_key",
                resource_id=row.id,
                payload={"prefix": row.prefix, "method": method, "path": path},
            )
