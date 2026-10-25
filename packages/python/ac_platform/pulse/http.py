"""Pulse routes on Sales X-Ray (contract docs/architecture/pulse-identity-contract.md).

Organisation -> Connections -> Pulse (an active owner or admin of the selected
organisation, checked against the live membership on every request):

- GET  /v1/sales-xray/pulse                       the link, the directory, Pulse's access
- POST /v1/sales-xray/pulse/connect               the Pulse address to approve the link
- POST /v1/sales-xray/pulse/sync                  read the directory again now
- POST /v1/sales-xray/pulse/invite                invite Pulse members who aren't here
- PUT  /v1/sales-xray/pulse/sharing               photos on/off, work signals on/off
- POST /v1/sales-xray/pulse/disconnect            end the link here and at Pulse
- GET  /v1/sales-xray/pulse/members/{id}/photo    a directory photo
- GET  /v1/sales-xray/pulse/people                Pulse titles, teams and photos of
                                                  this organisation's people (any member)

Pulse itself:

- GET  /v1/integrations/pulse/callback            where Pulse returns the approving admin
- POST /v1/integrations/pulse/webhook             signed change notices (pull-on-push);
       /v1/api/pulse/webhook                     the same, the address registered with Pulse

Everything here is off (404) until this environment has a Pulse client (issuer, id and
secret) and a sealing key.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.identity_provider import IdentityProviderUnavailable
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import oauth
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.seats import seat_exempt
from ac_platform.organisations.service import OrganisationService
from ac_platform.pulse import org_link
from ac_platform.pulse.models import PersonPulseProfile, PulseOrgLink
from ac_platform.pulse.oidc import PulseClient
from ac_platform.pulse.org_link import PulseLinkError
from ac_platform.pulse.profile import fetch_pulse_photo, save_photo
from ac_platform.tenancy.models import Membership, Organisation

_LOGGER = logging.getLogger(__name__)
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
MANAGER_ROLES = frozenset({"owner", "admin"})
HUB_RETURN = "/organisation?tab=connections&part=pulse"


class InviteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: list[UUID] = Field(min_length=1, max_length=100)


class SharingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photos: Literal["read", "off"]
    signals: Literal["off", "write"]


def pulse_client(ctx: RouteContext) -> PulseClient | None:
    settings = ctx.settings
    secret = settings.pulse_client_secret
    if not settings.pulse_configured or secret is None:
        return None
    try:
        return PulseClient(
            issuer=settings.pulse_issuer or "",
            client_id=settings.pulse_client_id or "",
            client_secret=secret.get_secret_value(),
        )
    except ValueError:
        _LOGGER.warning("pulse_org_link_settings_invalid")
        return None


def install_pulse_http(
    application: FastAPI, ctx: RouteContext, *, client: PulseClient | None = None
) -> None:
    """``client``: a Pulse client to use instead of the one the settings make (tests)."""
    settings = ctx.settings
    sessions = ctx.sessions
    client = client or pulse_client(ctx)
    seal_value = settings.pulse_seal_key.get_secret_value() if settings.pulse_seal_key else None
    key = org_link.seal_key_from(seal_value)
    app_url = str(settings.sales_xray_app_url).rstrip("/") if settings.sales_xray_app_url else None
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    router = APIRouter(tags=["pulse"])

    def ready() -> tuple[PulseClient, Any, str]:
        if client is None or key is None or app_url is None:
            raise HTTPException(404, "Pulse isn't set up here.", headers=PRIVATE)
        return client, key, app_url

    def on_host(request: Request) -> None:
        if settings.sales_xray_app_url is None or (
            request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Pulse isn't available here.", headers=PRIVATE)

    def refuse(error: PulseLinkError) -> HTTPException:
        return HTTPException(
            error.status, {"code": error.code, "message": error.message}, headers=PRIVATE
        )

    async def role_of(auth: Any) -> str | None:
        actor = auth.resolved.actor
        if actor.tenant_id is None:
            return None
        role: str | None = await auth.database.scalar(
            select(Membership.role)
            .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
            .where(
                Membership.tenant_id == actor.tenant_id,
                Membership.person_id == actor.person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        return role

    @asynccontextmanager
    async def manager(
        request: Request, response: Response | None, *, write: bool = False
    ) -> AsyncIterator[Any]:
        """The signed-in owner or admin of the selected registered organisation."""
        on_host(request)
        if response is not None:
            response.headers.update(PRIVATE)
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
                if await role_of(auth) not in MANAGER_ROLES:
                    raise HTTPException(
                        403,
                        "Only an owner or admin of an organisation can manage Pulse.",
                        headers=PRIVATE,
                    )
                yield auth
        except PulseLinkError as error:
            raise refuse(error) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    # ----- the directory sync (network outside transactions) ----------------------

    async def sync(
        link_id: UUID, *, full: bool, subject: str | None = None
    ) -> dict[str, Any] | None:
        live_client, live_key, _ = ready()
        now = datetime.now(UTC)
        async with sessions() as database, database.begin():
            link = await database.get(PulseOrgLink, link_id)
            if link is None or link.status != "active":
                return None
            since = (
                None
                if full or link.last_sync_at is None
                else (link.last_sync_at - timedelta(minutes=5))
            )
            remote = org_link.LinkSession(live_client, live_key, link)
        try:
            if subject is not None:
                one = await remote.member(subject)
                records = [one] if one is not None else []
                complete = False
            else:
                records, complete = await remote.members(updated_since=since)
        except PulseLinkError as error:
            if remote.revoked:
                async with sessions() as database, database.begin():
                    await org_link.end_link(
                        database,
                        link_id,
                        by="pulse",
                        person_id=None,
                        now=now,
                        reason="Pulse no longer accepts this organisation's link.",
                    )
            async with sessions() as database, database.begin():
                failed = await database.get(PulseOrgLink, link_id, with_for_update=True)
                if failed is not None and failed.status == "active":
                    failed.last_sync = {**(failed.last_sync or {}), "problem": error.message}
            raise
        counts = org_link.SyncCounts()
        photos: list[tuple[UUID, str]] = []
        async with sessions() as database, database.begin():
            link = await database.get(PulseOrgLink, link_id, with_for_update=True)
            if link is None or link.status != "active":
                return None
            remote.save_tokens(link)
            for record in records:
                photo = await org_link.apply_member(database, link, record, now=now, counts=counts)
                if photo is not None:
                    photos.append(photo)
            if subject is not None and not records:
                # Pulse no longer lists the person in the org: they left.
                still_here = await _subjects(database, link_id) - {subject}
                counts.removed += await org_link.mark_gone(database, link, still_here, now=now)
            if full and complete:
                counts.removed += await org_link.mark_gone(
                    database, link, {record.subject for record in records}, now=now
                )
            if subject is None:
                link.last_sync_at = now
            link.last_sync = {
                **counts.as_dict(),
                "complete": complete or subject is not None,
                "at": now.isoformat(),
            }
            await AuditRepository(database).append(
                tenant_id=link.tenant_id,
                actor_person_id=None,
                actor_type="system",
                action="pulse.directory_synced",
                resource_type="pulse_org_link",
                resource_id=link.id,
                payload={**counts.as_dict(), "full": full, "one": subject is not None},
                now=now,
            )
            issuer = link.issuer
        for member_id, picture in photos[: org_link._PHOTO_FETCHES]:
            jpeg = await fetch_pulse_photo(picture, issuer=issuer)
            if jpeg is None:
                continue
            async with sessions() as database, database.begin():
                person_id = await org_link.save_member_photo(
                    database, member_id, picture, jpeg, now=now
                )
                if person_id is not None:
                    await save_photo(
                        database, person_id=person_id, picture_url=picture, jpeg=jpeg, now=now
                    )
        return counts.as_dict()

    async def sync_quietly(link_id: UUID, full: bool, subject: str | None = None) -> None:
        try:
            await sync(link_id, full=full, subject=subject)
        except (PulseLinkError, IdentityProviderUnavailable, HTTPException):
            _LOGGER.warning("pulse_sync_failed")
        except Exception:
            _LOGGER.exception("pulse_sync_crashed")

    # ----- the page ---------------------------------------------------------------

    async def view(auth: Any) -> dict[str, Any]:
        tenant_id = auth.resolved.actor.tenant_id
        link = await org_link.open_link(auth.database, tenant_id)
        pulse_access = [
            item
            for item in await auth.database.run_sync(
                lambda session: oauth.connections(session.connection(), tenant_id)
            )
            if str(item.get("app") or item.get("name") or "").casefold() == "pulse"
        ]
        answer: dict[str, Any] = {
            "schema": "sx-pulse/1",
            "configured": client is not None and key is not None,
            "issuer": client.issuer if client is not None else None,
            "link": None,
            "members": [],
            "sharing_choices": {name: list(v) for name, v in org_link.SHARING_CHOICES.items()},
            "pulse_access": pulse_access,
        }
        if link is None or link.status != "active":
            return answer
        linked_by = None
        if link.linked_by_person_id is not None:
            from ac_platform.identity.models import Person

            person = await auth.database.get(Person, link.linked_by_person_id)
            linked_by = getattr(person, "display_name", None) or getattr(person, "email", None)
        answer["link"] = {
            "status": link.status,
            "pulse_org_id": link.pulse_org_id,
            "pulse_org_name": link.pulse_org_name,
            "linked_at": link.linked_at.isoformat() if link.linked_at else None,
            "linked_by": linked_by,
            "scopes": link.scopes,
            "sharing": org_link.sharing_of(link.sharing),
            "webhooks": link.webhook_id is not None,
            "last_sync_at": link.last_sync_at.isoformat() if link.last_sync_at else None,
            "last_sync": link.last_sync or {},
        }
        answer["members"] = await org_link.directory(auth.database, link)
        return answer

    @router.get("/v1/sales-xray/pulse")
    async def overview(
        request: Request, response: Response, background: BackgroundTasks
    ) -> dict[str, Any]:
        async with manager(request, response) as auth:
            answer = await view(auth)
            link = await org_link.open_link(auth.database, auth.resolved.actor.tenant_id)
            if (
                link is not None
                and link.status == "active"
                and (
                    link.last_sync_at is None
                    or link.last_sync_at < datetime.now(UTC) - org_link.STALE_AFTER
                )
            ):
                background.add_task(sync_quietly, link.id, False)
            return answer

    @router.post("/v1/sales-xray/pulse/connect")
    async def connect(request: Request, response: Response) -> dict[str, Any]:
        live_client, live_key, base = ready()
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            try:
                address = await org_link.begin(
                    auth.database,
                    live_client,
                    live_key,
                    tenant_id=actor.tenant_id,
                    person_id=actor.person_id,
                    redirect_uri=f"{base}{org_link.CALLBACK_PATH}",
                    now=datetime.now(UTC),
                )
            except IdentityProviderUnavailable:
                raise HTTPException(
                    503,
                    {"code": "unavailable", "message": "Pulse isn't reachable. Try again."},
                    headers=PRIVATE,
                ) from None
            return {"redirect_url": address}

    def back(outcome: str) -> RedirectResponse:
        base = app_url or ""
        response = RedirectResponse(
            f"{base}{HUB_RETURN}&{urlencode({'pulse': outcome})}", status_code=303
        )
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        return response

    @router.get("/v1/integrations/pulse/callback")
    async def callback(request: Request) -> Response:
        on_host(request)
        live_client, live_key, base = ready()
        params = request.query_params
        states = params.getlist("state")
        codes = params.getlist("code")
        errors = params.getlist("error")
        if len(states) != 1 or len(codes) > 1 or len(errors) > 1 or len(states[0]) > 200:
            return back("failed")
        now = datetime.now(UTC)
        try:
            async with asynccontextmanager(ctx.require_actor)(request) as auth:
                if await role_of(auth) not in MANAGER_ROLES:
                    return back("not_manager")
                attempt = await org_link.take_attempt(
                    auth.database,
                    live_key,
                    state=states[0],
                    person_id=auth.resolved.actor.person_id,
                    now=now,
                )
                person_id = auth.resolved.actor.person_id
                if attempt.tenant_id != auth.resolved.actor.tenant_id:
                    return back("other_workspace")
        except PulseLinkError as error:
            return back(error.code)
        except DomainError:
            return back("sign_in")
        if errors or not codes:
            return back("cancelled")
        try:
            grant = await org_link.exchange(
                live_client,
                attempt,
                code=codes[0],
                redirect_uri=f"{base}{org_link.CALLBACK_PATH}",
            )
            async with sessions() as database, database.begin():
                link = await org_link.activate(
                    database, live_key, attempt=attempt, grant=grant, person_id=person_id, now=now
                )
                remote = org_link.LinkSession(live_client, live_key, link)
                link_id = link.id
        except PulseLinkError as error:
            return back(error.code)
        try:
            hook = await remote.add_webhook(f"{base}{org_link.WEBHOOK_APP_PATH}")
            if hook is not None:
                async with sessions() as database, database.begin():
                    await org_link.save_webhook(database, live_key, link_id, hook)
        except PulseLinkError:
            _LOGGER.warning("pulse_webhook_not_registered")
        try:
            await sync(link_id, full=True)
        except (PulseLinkError, HTTPException):
            return back("linked_sync_failed")
        return back("connected")

    @router.post("/v1/sales-xray/pulse/sync")
    async def sync_now(request: Request, response: Response) -> dict[str, Any]:
        ready()
        async with manager(request, response, write=True) as auth:
            link = await org_link.open_link(auth.database, auth.resolved.actor.tenant_id)
            if link is None or link.status != "active":
                raise refuse(PulseLinkError(409, "not_linked", "Connect Pulse first."))
            link_id = link.id
        try:
            counts = await sync(link_id, full=True)
        except PulseLinkError as error:
            raise refuse(error) from None
        async with manager(request, None) as auth:
            return {**await view(auth), "synced": counts}

    @router.post("/v1/sales-xray/pulse/invite")
    async def invite(
        command: InviteCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        ready()
        if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
            raise HTTPException(503, "Invites aren't set up here.", headers=PRIVATE)
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            link = await org_link.open_link(auth.database, actor.tenant_id)
            if link is None or link.status != "active":
                raise refuse(PulseLinkError(409, "not_linked", "Connect Pulse first."))
            service = OrganisationService(
                auth.database,
                operations_tenant_id=settings.operations_tenant_id,
                public_learner_tenant_id=settings.public_learner_tenant_id,
                seat_exempt=lambda tenant_id: seat_exempt(
                    tenant_id,
                    policy=getattr(application.state, "internal_tester_policy", None),
                    environment=settings.environment,
                ),
            )
            invited: list[str] = []
            refused: list[dict[str, str]] = []
            now = datetime.now(UTC)
            for row in await org_link.invitable(auth.database, link, command.members):
                try:
                    async with auth.database.begin_nested():
                        await service.request_member(
                            actor.tenant_id,
                            str(row.email),
                            "member",
                            org_link.invite_command(link.id, row.subject),
                            actor_person_id=actor.person_id,
                            require_acceptance=True,
                        )
                        row.invited_at = now
                        invited.append(str(row.id))
                except DomainError as error:
                    refused.append({"id": str(row.id), "message": str(error)[:200]})
            await AuditRepository(auth.database).append(
                tenant_id=actor.tenant_id,
                actor_person_id=actor.person_id,
                action="pulse.members_invited",
                resource_type="pulse_org_link",
                resource_id=link.id,
                payload={"invited": len(invited), "refused": len(refused)},
                now=now,
            )
            return {"invited": invited, "refused": refused, **await view(auth)}

    @router.put("/v1/sales-xray/pulse/sharing")
    async def sharing(
        command: SharingCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        ready()
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            link = await org_link.open_link(auth.database, actor.tenant_id)
            if link is None or link.status != "active":
                raise refuse(PulseLinkError(409, "not_linked", "Connect Pulse first."))
            chosen = org_link.sharing_of(
                {**(link.sharing or {}), "photos": command.photos, "signals": command.signals}
            )
            link.sharing = chosen
            if chosen["photos"] == "off":
                from ac_platform.pulse.models import PulseOrgMember

                for row in (
                    await auth.database.scalars(
                        select(PulseOrgMember).where(PulseOrgMember.link_id == link.id)
                    )
                ).all():
                    row.photo_jpeg, row.photo_sha256, row.photo_source_sha256 = None, None, None
                    row.picture_url = None
                    if row.person_id is not None:
                        profile = await auth.database.scalar(
                            select(PersonPulseProfile).where(
                                PersonPulseProfile.person_id == row.person_id,
                                PersonPulseProfile.source == "org_link",
                            )
                        )
                        if profile is not None:
                            profile.photo_jpeg, profile.photo_sha256 = None, None
                            profile.photo_source_sha256, profile.picture_url = None, None
            await auth.database.flush()
            await AuditRepository(auth.database).append(
                tenant_id=actor.tenant_id,
                actor_person_id=actor.person_id,
                action="pulse.sharing_changed",
                resource_type="pulse_org_link",
                resource_id=link.id,
                payload=chosen,
                now=datetime.now(UTC),
            )
            return await view(auth)

    @router.post("/v1/sales-xray/pulse/disconnect")
    async def disconnect(request: Request, response: Response) -> dict[str, Any]:
        live_client, live_key, _ = ready()
        async with manager(request, response, write=True) as auth:
            link = await org_link.open_link(auth.database, auth.resolved.actor.tenant_id)
            if link is None:
                raise refuse(PulseLinkError(409, "not_linked", "Pulse isn't connected."))
            remote = (
                org_link.LinkSession(live_client, live_key, link)
                if link.status == "active"
                else None
            )
            link_id, person_id = link.id, auth.resolved.actor.person_id
        told_pulse = False
        if remote is not None:
            await remote.end()
            told_pulse = True
        async with sessions() as database, database.begin():
            await org_link.end_link(
                database,
                link_id,
                by="sales_xray",
                person_id=person_id,
                now=datetime.now(UTC),
                reason="An owner or admin unlinked the organisation from Pulse.",
            )
        async with manager(request, None) as auth:
            return {**await view(auth), "told_pulse": told_pulse}

    def photo_response(request: Request, photo: tuple[bytes, str] | None) -> Response:
        headers = {
            "Cache-Control": "private, no-cache",
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        }
        if photo is None:
            return Response(status_code=404, headers=headers)
        jpeg, digest = photo
        etag = f'"{digest}"'
        headers["ETag"] = etag
        if request.headers.get("if-none-match", "").replace("W/", "").strip() == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=jpeg, media_type="image/jpeg", headers=headers)

    @asynccontextmanager
    async def member_of_org(request: Request) -> AsyncIterator[Any]:
        on_host(request)
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                if await role_of(auth) is None:
                    raise HTTPException(403, "Open an organisation first.", headers=PRIVATE)
                yield auth
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    @router.get("/v1/sales-xray/pulse/members/{member_id}/photo")
    async def member_photo(member_id: UUID, request: Request) -> Response:
        async with member_of_org(request) as auth:
            return photo_response(
                request,
                await org_link.member_photo(
                    auth.database, auth.resolved.actor.tenant_id, member_id
                ),
            )

    @router.get("/v1/sales-xray/pulse/people")
    async def people(request: Request, response: Response) -> dict[str, Any]:
        """Pulse titles, teams and photos of this organisation's people, for member lists."""
        response.headers.update(PRIVATE)
        async with member_of_org(request) as auth:
            tenant_id = auth.resolved.actor.tenant_id
            from ac_platform.pulse.models import PulseOrgMember

            rows = (
                await auth.database.execute(
                    select(
                        PulseOrgMember.id,
                        PulseOrgMember.person_id,
                        PulseOrgMember.title,
                        PulseOrgMember.team,
                        PulseOrgMember.photo_sha256,
                    )
                    .join(PulseOrgLink, PulseOrgLink.id == PulseOrgMember.link_id)
                    .where(
                        PulseOrgMember.tenant_id == tenant_id,
                        PulseOrgMember.person_id.is_not(None),
                        PulseOrgMember.removed_at.is_(None),
                        PulseOrgLink.status == "active",
                    )
                )
            ).all()
            return {
                "people": {
                    str(row.person_id): {
                        "title": row.title,
                        "team": row.team,
                        "photo_url": (
                            f"/v1/sales-xray/pulse/members/{row.id}/photo"
                            if row.photo_sha256
                            else None
                        ),
                    }
                    for row in rows
                }
            }

    @router.post(org_link.WEBHOOK_PATH)
    @router.post(org_link.WEBHOOK_APP_PATH)
    async def webhook(request: Request, background: BackgroundTasks) -> Response:
        """Signed notices from Pulse. The body only says who changed; the change itself is
        read from Pulse's API (pull-on-push), so a forged or stale body changes nothing."""
        on_host(request)
        if client is None or key is None:
            return JSONResponse({"error": "not_set_up"}, status_code=404)
        body = await request.body()
        if len(body) > 16_384:
            return JSONResponse({"error": "too_large"}, status_code=413)
        try:
            event = json.loads(body)
        except ValueError:
            return JSONResponse({"error": "body"}, status_code=400)
        org_id = event.get("org_id") if isinstance(event, dict) else None
        kind = request.headers.get("x-pulse-event") or (
            event.get("type") if isinstance(event, dict) else None
        )
        if not isinstance(org_id, str) or kind not in org_link.EVENTS:
            return JSONResponse({"error": "event"}, status_code=400)
        async with sessions() as database, database.begin():
            link = await database.scalar(
                select(PulseOrgLink).where(
                    PulseOrgLink.issuer == client.issuer,
                    PulseOrgLink.pulse_org_id == org_id,
                    PulseOrgLink.status == "active",
                )
            )
            secret = None if link is None else org_link.webhook_secret(key, link)
            if (
                link is None
                or secret is None
                or not org_link.verify_signature(
                    request.headers.get("x-pulse-signature"), body, secret
                )
            ):
                return JSONResponse({"error": "signature"}, status_code=401)
            link_id = link.id
        subject = event.get("sub") if isinstance(event.get("sub"), str) else None
        if kind == "link.revoked":
            # Confirmed only when Pulse also refuses the link's token (sync ends it then).
            background.add_task(sync_quietly, link_id, False)
        elif subject:
            background.add_task(sync_quietly, link_id, False, subject[:255])
        return JSONResponse({"ok": True}, status_code=202)

    application.include_router(router)


async def _subjects(database: Any, link_id: UUID) -> set[str]:
    from ac_platform.pulse.models import PulseOrgMember

    return set(
        (
            await database.scalars(
                select(PulseOrgMember.subject).where(
                    PulseOrgMember.link_id == link_id, PulseOrgMember.removed_at.is_(None)
                )
            )
        ).all()
    )


__all__ = ["install_pulse_http", "pulse_client"]
