"""Admin plan prices (owner, 29 Oct 2026: "Admin price editor").

- GET /v1/admin/plan-prices          each plan's current price and revision, and the latest
                                      price changes (any verified Admin, operations workspace)
- PUT /v1/admin/plan-prices/{key}    the owner only (the AI budget ceiling's allowlist): new
                                      monthly and yearly paise for one plan, checked against
                                      the revision read, with a reason

A change supersedes, never overwrites: the plans row takes the new price under a new revision
(checkout, /v1/plans and /v1/me/plan read it; orders keep the price they copied, and a provider
plan is keyed by revision and amount), while an append-only plan_price_changes row (migration
20261029_0143) and an audit event keep the old and new prices, who and why. Admin only; no
price reaches an analysis screen or the Play app from here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.budget_admin import CEILING_OWNER_EMAILS
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.plans.models import Plan, PlanPriceChange

PRIVATE = {"Cache-Control": "private, no-store"}
PRICE_ACTION = "plans.price_changed"
# Plans that take a new price: on sale, or coming soon (Enterprise's hidden price).
EDITABLE = ("coming_soon", "active")
# ₹10,00,000: far above any price set so far (the highest was ₹1,08,000 a seat a year).
MAX_PRICE_PAISE = 100_000_000
HISTORY_LIMIT = 20


class PriceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1)
    monthly_price_paise: int = Field(gt=0, le=MAX_PRICE_PAISE)
    yearly_price_paise: int = Field(gt=0, le=MAX_PRICE_PAISE)
    reason: str = Field(min_length=1, max_length=300)


class PriceRefused(ValueError):
    """A content-free reason the price was not changed, with its HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


async def is_price_owner(db: AsyncSession, person_id: UUID) -> bool:
    """The owner's own verified account, on the AI budget ceiling's allowlist."""

    person = await db.get(Person, person_id)
    return (
        person is not None
        and person.email_verified_at is not None
        and (person.email or "").casefold() in CEILING_OWNER_EMAILS
    )


async def price_view(db: AsyncSession, *, environment: str, can_change: bool) -> dict[str, Any]:
    """This environment's plans and their latest price changes (each environment has its own)."""

    plans = (await db.scalars(select(Plan).order_by(Plan.sort_order, Plan.key))).all()
    changes = (
        await db.scalars(
            select(PlanPriceChange)
            .order_by(PlanPriceChange.created_at.desc(), PlanPriceChange.plan_revision.desc())
            .limit(HISTORY_LIMIT)
        )
    ).all()
    who = {change.changed_by_person_id for change in changes}
    people = (
        {
            person.id: person.email
            for person in (await db.scalars(select(Person).where(Person.id.in_(who)))).all()
        }
        if who
        else {}
    )
    return {
        "environment": environment,
        "can_change": can_change,
        "plans": [
            {
                "key": plan.key,
                "name": plan.name,
                "status": plan.status,
                "revision": plan.revision,
                "per_seat": plan.per_seat,
                "prices_include_gst": plan.prices_include_gst,
                "monthly_price_paise": plan.monthly_price_paise,
                "yearly_price_paise": plan.yearly_price_paise,
                "editable": plan.status in EDITABLE,
            }
            for plan in plans
        ],
        "history": [
            {
                "plan_key": change.plan_key,
                "plan_revision": change.plan_revision,
                "monthly_price_paise": change.monthly_price_paise,
                "yearly_price_paise": change.yearly_price_paise,
                "previous_monthly_price_paise": change.previous_monthly_price_paise,
                "previous_yearly_price_paise": change.previous_yearly_price_paise,
                "reason": change.reason,
                "changed_by": people.get(change.changed_by_person_id),
                "changed_at": change.created_at.astimezone(UTC).isoformat(),
            }
            for change in changes
        ],
    }


async def change_price(
    db: AsyncSession,
    *,
    key: str,
    command: PriceCommand,
    person_id: UUID,
    now: datetime,
) -> tuple[Plan, dict[str, int | None], dict[str, int | None]]:
    """Set one plan's prices under a new revision and keep the change (caller audits)."""

    plan = await db.scalar(select(Plan).where(Plan.key == key).with_for_update())
    if plan is None:
        raise PriceRefused(404, "There is no plan with that key.")
    if plan.status not in EDITABLE:
        raise PriceRefused(409, "Only a plan on sale or coming soon takes a new price.")
    if plan.revision != command.expected_revision:
        raise PriceRefused(409, "This plan changed. Refresh and try again.")
    before = {
        "monthly_price_paise": plan.monthly_price_paise,
        "yearly_price_paise": plan.yearly_price_paise,
    }
    after: dict[str, int | None] = {
        "monthly_price_paise": command.monthly_price_paise,
        "yearly_price_paise": command.yearly_price_paise,
    }
    if before == after:
        raise PriceRefused(422, "These are the current prices; nothing changed.")
    plan.monthly_price_paise = command.monthly_price_paise
    plan.yearly_price_paise = command.yearly_price_paise
    plan.revision += 1
    plan.updated_at = now
    db.add(
        PlanPriceChange(
            id=uuid4(),
            plan_id=plan.id,
            plan_key=plan.key,
            plan_revision=plan.revision,
            monthly_price_paise=command.monthly_price_paise,
            yearly_price_paise=command.yearly_price_paise,
            previous_monthly_price_paise=before["monthly_price_paise"],
            previous_yearly_price_paise=before["yearly_price_paise"],
            reason=command.reason.strip(),
            changed_by_person_id=person_id,
            created_at=now,
        )
    )
    await db.flush()
    return plan, before, after


def install_plan_prices_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["plan-prices-admin"])

    async def admit(request: Request, response: Response, auth: AuthenticatedTransaction) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if request.query_params:
            raise HTTPException(422, "Plan prices take no query parameters.")
        actor = auth.resolved.actor
        if (
            settings.operations_tenant_id is None
            or actor.tenant_id != settings.operations_tenant_id
        ):
            raise HTTPException(403, "Use the AC operations workspace.")
        try:
            await ConversationProviderAdmin(ConversationApplication(auth.database)).admit(actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return actor

    @router.get("/v1/admin/plan-prices")
    async def overview(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        actor = await admit(request, response, auth)
        owner = await is_price_owner(auth.database, actor.person_id)
        return await price_view(auth.database, environment=settings.environment, can_change=owner)

    @router.put("/v1/admin/plan-prices/{key}")
    async def change(
        key: str,
        command: PriceCommand,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use this Admin page to continue.") from None
        actor = await admit(request, response, auth)
        db = auth.database
        if not await is_price_owner(db, actor.person_id):
            raise HTTPException(403, "Only the owner (Suyash) can change plan prices.")
        reason = command.reason.strip()
        if not reason:
            raise HTTPException(422, "Add a short reason; it goes in the audit trail.")
        try:
            plan, before, after = await change_price(
                db, key=key, command=command, person_id=actor.person_id, now=datetime.now(UTC)
            )
        except PriceRefused as error:
            raise HTTPException(error.status, str(error)) from None
        await AuditRepository(db).append_for_actor(
            actor,
            action=PRICE_ACTION,
            resource_type="plan",
            resource_id=plan.key,
            payload={
                "plan_key": plan.key,
                "from_revision": plan.revision - 1,
                "to_revision": plan.revision,
                "old": before,
                "new": after,
            },
            reason=reason,
        )
        return await price_view(db, environment=settings.environment, can_change=True)

    application.include_router(router)


__all__ = [
    "MAX_PRICE_PAISE",
    "PRICE_ACTION",
    "PriceCommand",
    "PriceRefused",
    "change_price",
    "install_plan_prices_admin_http",
    "is_price_owner",
    "price_view",
]
