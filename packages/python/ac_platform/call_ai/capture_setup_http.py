"""Call capture setup API on the Sales Xray account session (/v1/sales-xray/call-ai/capture-setup).

- GET  /capture-setup        the caller's own setup in the current workspace: whether it is
                             required, the profile and consent as the steps need them, the
                             last no and when to ask again, and the phones that finished.
                             A personal workspace answers ``required: false``.
- POST /capture-setup        the caller's own finished phone, or their no at the disclosure
                             (any member, for themselves, with an Idempotency-Key).
- GET  /capture-setup/team   each member's state, for owners, admins and managers (Team),
                             with today's calls that have no recording, each and in all.
- GET  /capture-setup/missing  the caller's own connected lead calls today with no recording
                             two minutes after they ended (``missing_recordings``).

Agreeing is the standing consent (``auto_consent``, POST /auto-analysis): this API never
records consent, and a finished phone is refused until the consent is on and the profile
complete, so the record can't claim more than the seller did.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.call_ai import auto_consent, capture_setup, missing_recordings
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileError,
    get_sales_xray_profile,
)
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.models import LeadDeskSettings
from ac_platform.lead_desk.store import MANAGERS, PHONES_KEY, person_name
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
OUTSIDE = "Call capture is set up inside an organisation."
SCHEMA = "sales-xray-capture-setup/1"
TEAM_SCHEMA = "sales-xray-capture-setup-team/1"
MISSING_SCHEMA = "sales-xray-missing-recordings/1"
RECORDING_SCHEMA = "sales-xray-recording-health/1"


class PhoneFinished(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # This install's own id (the one call logging uses), never a phone number.
    device: str = Field(min_length=1, max_length=80)
    model: str = Field(default="", max_length=80)
    family: str = Field(default="", max_length=20)
    app_version: str = Field(default="", max_length=40)
    recordings: bool = False
    background: bool = False
    uploads: bool = False


class RecordingHealth(BaseModel):
    """The seller's own phone: its install id and its newest call recording."""

    model_config = ConfigDict(extra="forbid")
    device: str = Field(min_length=1, max_length=80)
    newest_recording_at: datetime | None = None


class SetupCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["completed", "declined"]
    phone: PhoneFinished | None = None


def install_capture_setup_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/sales-xray/call-ai/capture-setup", tags=["call-ai"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    settings = ctx.settings

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Call capture setup is unavailable here.", headers=PRIVATE)

    @asynccontextmanager
    async def member(
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
                    raise HTTPException(403, OUTSIDE, headers=PRIVATE)
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
                    raise HTTPException(403, OUTSIDE, headers=PRIVATE)
                yield auth, tenant_id, actor.person_id, str(role)
        except capture_setup.SetupError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    def terms_in_force(request: Request) -> str | None:
        """The upload terms' hash in force, from the upload routes (as auto-analysis reads it)."""
        terms = getattr(request.app.state, auto_consent.UPLOAD_TERMS_STATE, None)
        return terms() if callable(terms) else None

    async def consent_of(
        request: Request, auth: Any, tenant_id: UUID, person_id: UUID
    ) -> auto_consent.Standing:
        found = await auto_consent.standing(auth.database, tenant_id, person_id)
        current = terms_in_force(request)
        # Upload terms changed since: the consent asks again, as GET /auto-analysis says.
        if found.state == "on" and current is not None and found.terms_sha256 != current:
            return auto_consent.Standing("ask", found.event_id, found.at, found.terms_sha256)
        return found

    async def profile_complete(auth: Any, person_id: UUID) -> bool:
        """The same check as the upload's (``write-eligibility``): name and phone."""
        try:
            profile = await get_sales_xray_profile(auth.database, person_id=person_id, extras=False)
        except SalesXrayProfileError:
            return False
        return bool(profile.profile_complete)

    async def own_view(
        request: Request, auth: Any, tenant_id: UUID, person_id: UUID, role: str
    ) -> dict[str, Any]:
        consent = await consent_of(request, auth, tenant_id, person_id)
        found = await capture_setup.setup(auth.database, tenant_id, person_id)
        no = capture_setup.last_no(found, consent.state, consent.at)
        again = capture_setup.ask_again_at(no)
        return {
            "schema": SCHEMA,
            "workspace": "organisation",
            "required": role in capture_setup.REQUIRED_ROLES,
            "profile_complete": await profile_complete(auth, person_id),
            "consent": consent.state,
            "consent_since": consent.at.isoformat() if consent.at else None,
            "declined_at": no.isoformat() if no else None,
            "ask_again_at": again.isoformat() if again else None,
            "phones": [phone.view() for phone in found.phones],
            # This person's installs finished in any workspace: their phone steps are done.
            "finished_devices": await capture_setup.finished_devices(auth.database, person_id),
        }

    @router.get("")
    async def read_setup(request: Request, response: Response) -> dict[str, Any]:
        try:
            async with member(request, response) as (auth, tenant_id, person_id, role):
                return await own_view(request, auth, tenant_id, person_id, role)
        except HTTPException as error:
            # A personal workspace: the steps may still be offered, never required.
            if error.status_code == 403 and error.detail == OUTSIDE:
                return {
                    "schema": SCHEMA,
                    "workspace": "personal",
                    "required": False,
                    "consent": "unavailable",
                    "declined_at": None,
                    "ask_again_at": None,
                    "phones": [],
                }
            raise

    @router.post("")
    async def record_setup(
        command: SetupCommand,
        request: Request,
        response: Response,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
    ) -> dict[str, Any]:
        async with member(request, response, write=True) as (auth, tenant_id, person_id, role):
            consent = await consent_of(request, auth, tenant_id, person_id)
            if command.outcome == "completed":
                if command.phone is None:
                    raise capture_setup.SetupError(
                        422, "Open Sales X-Ray on your phone to finish setting it up."
                    )
                if not await profile_complete(auth, person_id):
                    raise capture_setup.SetupError(403, "Add your name and phone number first.")
                if consent.state != "on":
                    raise capture_setup.SetupError(
                        409, "Agree to call capture first, then finish on your phone."
                    )
            elif consent.state == "on":
                raise capture_setup.SetupError(
                    409, "Call capture is on. Turn it off in Settings, Privacy."
                )
            await capture_setup.record(
                auth.database,
                tenant_id=tenant_id,
                person_id=person_id,
                session_id=auth.resolved.actor.session_id,
                outcome=command.outcome,
                phone=command.phone.model_dump() if command.phone else None,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
            return await own_view(request, auth, tenant_id, person_id, role)

    @router.get("/team")
    async def read_team(request: Request, response: Response) -> dict[str, Any]:
        async with member(request, response) as (auth, tenant_id, _, role):
            if role not in MANAGERS:
                raise HTTPException(
                    403,
                    "Only the organisation's owners, admins and managers see this.",
                    headers=PRIVATE,
                )
            rows = (
                await auth.database.execute(
                    select(Person, Membership.role)
                    .join(Membership, Membership.person_id == Person.id)
                    .where(
                        Membership.tenant_id == tenant_id,
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                        Membership.role.in_(capture_setup.REQUIRED_ROLES),
                    )
                )
            ).all()
            found = await capture_setup.team(auth.database, tenant_id, [row[0].id for row in rows])
            # The same calls Home counts (its Tried), never more.
            missing = (
                await missing_recordings.calls_today(
                    auth.database,
                    tenant_id=tenant_id,
                    person_id=auth.resolved.actor.person_id,
                    role=role,
                    now=datetime.now(UTC),
                    team=True,
                )
            ).missing
            # Phones with work-call logging off, by Connections' own rule (ph1-23).
            desk = await auth.database.get(LeadDeskSettings, tenant_id)
            stored = (desk.config if desk else None) or {}
            reports = stored.get(PHONES_KEY)
            phones: dict[str, Any] = reports if isinstance(reports, dict) else {}
            # Each phone's newest recording (competitor teardown #7).
            kept = stored.get(capture_setup.RECORDING_KEY)
            recordings: dict[str, Any] = kept if isinstance(kept, dict) else {}
            now = datetime.now(UTC)
            people: list[dict[str, Any]] = []
            for person, member_role in rows:
                consent = await consent_of(request, auth, tenant_id, person.id)
                setup = found.get(person.id, capture_setup.Setup())
                state = capture_setup.team_state(setup, consent.state)
                # When the line's state began: the phone finished, the no, or the consent.
                at: datetime | None = None
                if state == "set_up":
                    at = setup.phones[0].at
                elif state == "declined":
                    at = setup.declined_at
                elif state in ("phone_pending", "turned_off"):
                    at = consent.at
                newest = setup.phones[0] if setup.phones else None
                report: dict[str, Any] = phones.get(str(person.id)) or {}
                log_off = (
                    capture_setup.phone_label(report.get("device_id"), report.get("family"), setup)
                    if capture_setup.call_log_off(report)
                    else None
                )
                people.append(
                    {
                        "person_id": str(person.id),
                        "name": person_name(person),
                        "role": str(member_role),
                        "state": state,
                        "at": at.isoformat() if at else None,
                        "phone": (
                            capture_setup.phone_name(newest.model, newest.family)
                            if newest
                            else None
                        ),
                        "missing_today": missing.by_person.get(person.id, 0),
                        # The phone with work-call logging off, by name, or None.
                        "call_log_off": log_off,
                        # Recording on this seller's phone: ok, late or off, and the fix.
                        "recording": capture_setup.recording_state(
                            phones.get(str(person.id)), recordings.get(str(person.id)), now
                        ),
                    }
                )
            # Who still needs to set it up first, then by name.
            people.sort(key=lambda row: (row["state"] == "set_up", row["name"].casefold()))
            # Calls without a recording today, everyone's (owner, 30 Oct 2026, fix 5).
            return {
                "schema": TEAM_SCHEMA,
                "people": people,
                "missing_today": missing.total,
                "call_log_off": sum(row["call_log_off"] is not None for row in people),
            }

    @router.post("/recording-health")
    async def report_recording(
        command: RecordingHealth, request: Request, response: Response
    ) -> dict[str, Any]:
        """The seller's phone says when it last found a call recording, for Team's line
        (competitor teardown #7, 1 Nov 2026). Never a number, a name or the file."""
        async with member(request, response, write=True) as (auth, tenant_id, person_id, _):
            now = datetime.now(UTC)
            desk = await auth.database.get(LeadDeskSettings, tenant_id, with_for_update=True)
            if desk is None:
                desk = LeadDeskSettings(
                    tenant_id=tenant_id,
                    revision=1,
                    config={},
                    updated_by_person_id=None,
                    updated_at=now,
                )
                auth.database.add(desk)
            kept = (desk.config or {}).get(capture_setup.RECORDING_KEY)
            health: dict[str, Any] = dict(kept) if isinstance(kept, dict) else {}
            newest = command.newest_recording_at
            if newest is not None:
                newest = min(newest.astimezone(UTC), now)
            health[str(person_id)] = {
                "device": command.device,
                "newest_at": newest.isoformat() if newest else None,
                "reported_at": now.isoformat(),
            }
            # A new dict, so the change is saved; the revision stays (not a manager's edit).
            desk.config = {**(desk.config or {}), capture_setup.RECORDING_KEY: health}
            await auth.database.flush()
            return {"schema": RECORDING_SCHEMA, "recorded": True}

    async def missing_view(
        request: Request, response: Response, day: date | None
    ) -> dict[str, Any]:
        try:
            async with member(request, response) as (auth, tenant_id, person_id, role):
                found = await missing_recordings.calls_today(
                    auth.database,
                    tenant_id=tenant_id,
                    person_id=person_id,
                    role=role,
                    now=datetime.now(UTC),
                    day=day,
                )
                latest = found.missing.latest.get(person_id)
                mine = [item for item in found.items if item.person_id == person_id][:50]
                names = await missing_recordings.lead_names(
                    auth.database, tenant_id, [item.lead_id for item in mine]
                )
                return {
                    "schema": MISSING_SCHEMA,
                    "calls": found.missing.by_person.get(person_id, 0),
                    "tried": found.tried.get(person_id, 0),
                    "latest_at": latest.isoformat() if latest else None,
                    # The calls themselves: the lead, when and how long, never a number.
                    "items": [
                        {
                            "event_id": str(item.event_id),
                            "lead_id": str(item.lead_id),
                            "lead_name": names.get(item.lead_id),
                            "at": item.at.isoformat(),
                            "seconds": item.seconds,
                        }
                        for item in mine
                    ],
                }
        except HTTPException as error:
            # A personal workspace: its calls are checked on the phone, not here.
            if error.status_code == 403 and error.detail == OUTSIDE:
                return {
                    "schema": MISSING_SCHEMA,
                    "calls": 0,
                    "tried": 0,
                    "latest_at": None,
                    "items": [],
                }
            raise

    @router.get("/missing")
    async def read_missing(request: Request, response: Response) -> dict[str, Any]:
        """The caller's own connected lead calls today with no recording after two minutes,
        from the calls Home counts, and how many they tried (Home's Tried): the line at the
        top of Calls and Reports, and its list of those calls (teardown 13)."""
        return await missing_view(request, response, None)

    @router.get("/missing/{day}")
    async def read_missing_day(day: str, request: Request, response: Response) -> dict[str, Any]:
        """One India day's (the bell's reminder opens it, ph1-27): the last 31 days."""
        try:
            asked = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(422, "That isn't a day.", headers=PRIVATE) from None
        today = datetime.now(missing_recordings.INDIA).date()
        if not timedelta(0) <= today - asked <= timedelta(days=31):
            raise HTTPException(422, "Only the last 31 days.", headers=PRIVATE)
        return await missing_view(request, response, asked)

    application.include_router(router)
