"""AI on calls API on the Sales Xray account session (/v1/sales-xray/call-ai).

- GET /                      the organisation's default, each person's own level, and
                             the caller's own (any member may read; sellers see why a
                             call has no report)
- PUT /default               the organisation's default (owners and admins)
- PUT /people/{person_id}    one person's own level, or back to the default with
                             ``level: null`` (owners and admins)

Each save is a new settings revision (``expected_revision`` guards against two people
saving at once) and an audit event with old and new. Only the organisation's owners and
admins may change levels; the processing plan enforces them on the server before any
paid stage, whatever the app shows. "Get full report" on one call lives with the call's
other actions (``http/conversation_submissions.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
from ac_platform.call_ai import policy, store
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.store import MANAGERS, person_name
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
LevelName = Literal["off", "data_only", "auto", "full"]
# What each level does, in the app's words (no prices: never on a user screen).
HINTS: dict[str, str] = {
    "off": "Calls are saved and logged on the lead. No AI reads them.",
    "data_only": (
        "Transcript and lead facts for the CRM, WhatsApp and automations. No report or coaching."
    ),
    "auto": "Sales X-Ray picks per call. Until call types arrive, every call gets the full report.",
    "full": "The full report and coaching on every call.",
}


class DefaultCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    level: LevelName


class PersonCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None
    # None: back to the organisation's default.
    level: LevelName | None


def levels() -> list[dict[str, str]]:
    return [
        {"id": level, "name": policy.NAMES[level], "hint": HINTS[level]} for level in policy.LEVELS
    ]


def install_call_ai_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/sales-xray/call-ai", tags=["call-ai"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    settings = ctx.settings

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "AI on calls is unavailable here.", headers=PRIVATE)

    @asynccontextmanager
    async def workspace(
        request: Request, response: Response, *, write: bool = False
    ) -> AsyncIterator[tuple[Any, UUID, UUID, str]]:
        """(auth, tenant, person, role) for a member of the current organisation."""
        response.headers.update(PRIVATE)
        same_host(request)
        if request.query_params:
            raise HTTPException(422, "Remove the extra address options.", headers=PRIVATE)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Use this Sales Xray page to continue.", headers=PRIVATE
                ) from None
        try:
            async with asynccontextmanager(ctx.require_actor if write else read_actor)(
                request
            ) as auth:
                actor = auth.resolved.actor
                tenant_id = actor.tenant_id
                if tenant_id is None or tenant_id in (
                    settings.operations_tenant_id,
                    settings.public_learner_tenant_id,
                ):
                    raise HTTPException(
                        403, "AI on calls is set inside an organisation.", headers=PRIVATE
                    )
                role = await auth.database.scalar(
                    select(Membership.role)
                    .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
                    .where(
                        Membership.tenant_id == tenant_id,
                        Membership.person_id == actor.person_id,
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                        Membership.role.in_(SALES_XRAY_MEMBER_ROLES),
                    )
                )
                if role is None:
                    raise HTTPException(
                        403, "AI on calls is set inside an organisation.", headers=PRIVATE
                    )
                if write and role not in MANAGERS:
                    raise HTTPException(
                        403,
                        "Only the organisation's owners and admins can change AI on calls.",
                        headers=PRIVATE,
                    )
                yield auth, tenant_id, actor.person_id, str(role)
        except store.SettingsConflict:
            raise HTTPException(
                409, "Someone changed these settings. Open them again.", headers=PRIVATE
            ) from None
        except policy.SettingsError as error:
            raise HTTPException(422, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    async def view(
        auth: Any, tenant_id: UUID, person_id: UUID, role: str, current: store.Settings
    ) -> dict[str, Any]:
        people = current.config["people"]
        names: dict[str, str] = {}
        if people:
            rows = (
                await auth.database.execute(
                    select(Person)
                    .join(Membership, Membership.person_id == Person.id)
                    .where(
                        Membership.tenant_id == tenant_id,
                        Person.id.in_([UUID(key) for key in people]),
                    )
                )
            ).scalars()
            names = {str(row.id): person_name(row) for row in rows}
        own, source = policy.resolve(current.config, person_id)
        return {
            "revision": current.revision,
            "default": current.config["default"],
            "people": [
                {"person_id": key, "name": names.get(key, "Former member"), "level": level}
                for key, level in sorted(people.items(), key=lambda kv: names.get(kv[0], "~"))
            ],
            "you": {"level": own, "source": source},
            "levels": levels(),
            "can_edit": role in MANAGERS,
        }

    async def saved(
        auth: Any,
        tenant_id: UUID,
        person_id: UUID,
        role: str,
        expected: int | None,
        config: dict[str, Any],
        *,
        action: str,
        changed: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        before, after = await store.save(
            auth.database,
            tenant_id,
            config,
            expected_revision=expected,
            actor_person_id=person_id,
            now=now,
        )
        await AuditRepository(auth.database).append(
            tenant_id=tenant_id,
            actor_person_id=person_id,
            session_id=auth.resolved.actor.session_id,
            action=action,
            resource_type="call_ai_settings",
            resource_id=f"{tenant_id}:{after.revision}",
            payload={
                **changed,
                "revision": after.revision,
                "before": before.config,
                "after": after.config,
            },
            now=now,
        )
        return await view(auth, tenant_id, person_id, role, after)

    @router.get("")
    async def read(request: Request, response: Response) -> dict[str, Any]:
        async with workspace(request, response) as (auth, tenant_id, person_id, role):
            return await view(
                auth, tenant_id, person_id, role, await store.read(auth.database, tenant_id)
            )

    @router.put("/default")
    async def set_default(
        command: DefaultCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        async with workspace(request, response, write=True) as (
            auth,
            tenant_id,
            person_id,
            role,
        ):
            current = await store.read(auth.database, tenant_id)
            return await saved(
                auth,
                tenant_id,
                person_id,
                role,
                command.expected_revision,
                {**current.config, "default": command.level},
                action="sales_xray.call_ai.default_changed",
                changed={"default": command.level},
            )

    @router.put("/people/{member_id}")
    async def set_person(
        member_id: UUID, command: PersonCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        async with workspace(request, response, write=True) as (
            auth,
            tenant_id,
            person_id,
            role,
        ):
            member = await auth.database.scalar(
                select(Membership.person_id).where(
                    Membership.tenant_id == tenant_id,
                    Membership.person_id == member_id,
                    Membership.status == "active",
                    Membership.ended_at.is_(None),
                )
            )
            current = await store.read(auth.database, tenant_id)
            # A former member's level can still be cleared, never set.
            if member is None and command.level is not None:
                raise HTTPException(
                    404, "That person is not in this organisation.", headers=PRIVATE
                )
            return await saved(
                auth,
                tenant_id,
                person_id,
                role,
                command.expected_revision,
                policy.with_person(current.config, member_id, command.level),
                action="sales_xray.call_ai.person_changed",
                changed={"person_id": str(member_id), "level": command.level},
            )

    application.include_router(router)
