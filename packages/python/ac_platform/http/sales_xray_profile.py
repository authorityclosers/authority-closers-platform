"""Self-service Sales Xray profile and pre-body write eligibility boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    WORKSPACE_UNAVAILABLE_MESSAGE,
    sales_xray_workspace_served,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.identity import characters, person_photos
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileError,
    SalesXrayProfileHandleTaken,
    SalesXrayProfileIncomplete,
    SalesXrayProfileRevisionConflict,
    SalesXrayProfileSnapshot,
    get_sales_xray_profile,
    require_sales_xray_profile_complete,
    update_profile_details,
    update_sales_xray_profile,
)
from ac_platform.kernel.authz import ActorContext

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime


class ProfileCompletion(BaseModel):
    """What a complete profile still needs (the "Your profile: 3 of 6" card)."""

    model_config = ConfigDict(extra="forbid")

    done: int
    total: int
    missing: list[str]


class SalesXrayProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    email: str
    phone_number_e164: str | None
    phone_verified: bool
    profile_complete: bool
    revision: int
    given_name: str | None
    family_name: str | None
    locale: str | None
    company_domain: str | None
    photo_url: str | None
    # The member's profile (migration 0135, 25 Oct 2026), saved against its own revision.
    handle: str | None = None
    title: str | None = None
    team: str | None = None
    details_revision: int = 0
    # The character the photo is (owner #32, 26 Oct 2026), else null; the one shown without a
    # photo.
    character: str | None = None
    default_character: str | None = None
    avatar_url: str | None = None
    own_photo: bool = False
    completion: ProfileCompletion | None = None


class ProfileDetailsUpdate(BaseModel):
    """User id, title and team. A missing or null handle keeps the current one;
    ``expected_revision`` is the response's ``details_revision``."""

    model_config = ConfigDict(extra="forbid")

    handle: str | None = Field(default=None, max_length=31)
    title: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=200)
    expected_revision: int = Field(ge=0, strict=True)


class SalesXrayProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    phone_number_e164: str | None = Field(max_length=16)
    expected_revision: int = Field(ge=0, strict=True)


class CharacterChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character: str = Field(min_length=2, max_length=24)


async def require_sales_xray_write_profile(
    database: AsyncSession,
    actor: ActorContext | None,
) -> SalesXrayProfileSnapshot:
    """Fail closed for new bytes/provider work unless a human account is ready."""

    if actor is None:
        raise HTTPException(
            401,
            "Sign in and complete your AC contact profile before continuing.",
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )
    try:
        return await require_sales_xray_profile_complete(database, person_id=actor.person_id)
    except SalesXrayProfileError:
        raise HTTPException(
            403,
            "Complete your AC contact profile before continuing.",
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        ) from None


def install_sales_xray_profile_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None = None,
) -> None:
    router = APIRouter(prefix="/v1/me/sales-xray-profile", tags=["sales-xray-profile"])
    # Personal or an approved organisation; the operations tenant never qualifies.
    actor_dependency = Depends(require_actor, scope="function")
    read_require_actor = getattr(require_actor, "read_only", require_actor)
    read_actor_dependency = Depends(read_require_actor, scope="function")

    async def require_profile_surface(request: Request, auth: AuthenticatedTransaction) -> None:
        allowed_hosts = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            allowed_hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in allowed_hosts or request.query_params:
            raise HTTPException(404, "Profile route not found.")
        if not await sales_xray_workspace_served(
            auth.database, settings, auth.resolved.actor.tenant_id
        ):
            raise HTTPException(403, WORKSPACE_UNAVAILABLE_MESSAGE)

    async def require_eligibility_surface(request: Request, auth: AuthenticatedTransaction) -> None:
        allowed_hosts = {
            settings.public_app_url.host,
            settings.api_url.host,
            settings.admin_app_url.host,
            settings.coach_app_url.host,
        }
        if settings.sales_xray_app_url is not None:
            allowed_hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in allowed_hosts or request.query_params:
            raise HTTPException(404, "Profile eligibility route not found.")
        if not await sales_xray_workspace_served(
            auth.database, settings, auth.resolved.actor.tenant_id
        ):
            raise HTTPException(403, WORKSPACE_UNAVAILABLE_MESSAGE)

    def headers(response: Response) -> None:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"

    def fail_profile(error: SalesXrayProfileError) -> HTTPException:
        if isinstance(error, SalesXrayProfileHandleTaken):
            return HTTPException(409, str(error), headers={"Cache-Control": "private, no-store"})
        if isinstance(error, SalesXrayProfileRevisionConflict):
            return HTTPException(409, str(error), headers={"Cache-Control": "private, no-store"})
        if isinstance(error, SalesXrayProfileIncomplete):
            return HTTPException(403, str(error), headers={"Cache-Control": "private, no-store"})
        return HTTPException(403, str(error), headers={"Cache-Control": "private, no-store"})

    def response_value(value: SalesXrayProfileSnapshot) -> dict[str, object]:
        return SalesXrayProfileResponse(
            name=value.name,
            email=value.email,
            phone_number_e164=value.phone_number_e164,
            phone_verified=value.phone_verified,
            profile_complete=value.profile_complete,
            revision=value.revision,
            given_name=value.given_name,
            family_name=value.family_name,
            locale=value.locale,
            company_domain=value.hosted_domain,
            photo_url=value.photo_url,
            handle=value.handle,
            title=value.title,
            team=value.team,
            details_revision=value.details_revision,
            character=value.character,
            default_character=value.default_character,
            avatar_url=value.avatar_url,
            own_photo=value.own_photo,
            completion=ProfileCompletion.model_validate(value.completion),
        ).model_dump()

    def photo_headers(etag: str | None = None) -> dict[str, str]:
        result = {
            "Cache-Control": "private, no-cache",
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        }
        if etag is not None:
            result["ETag"] = etag
        return result

    def if_none_match_matches(header: str | None, etag: str) -> bool:
        if header is None:
            return False
        return any(
            value.strip() == "*" or value.strip().removeprefix("W/") == etag
            for value in header.split(",")
        )

    @router.get("", response_model=SalesXrayProfileResponse)
    async def read_profile(
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> dict[str, object]:
        headers(response)
        await require_profile_surface(request, auth)
        try:
            value = await get_sales_xray_profile(
                auth.database,
                person_id=auth.resolved.actor.person_id,
            )
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        return response_value(value)

    @router.get("/photo", response_class=Response)
    async def read_profile_photo(
        request: Request,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> Response:
        actor = auth.resolved.actor
        await require_profile_surface(request, auth)
        # The person's own upload wins over Google's (25 Oct 2026).
        photo = await person_photos.read_photo(auth.database, actor.person_id)
        if photo is None:
            raise HTTPException(
                404,
                "Profile photo not found.",
                headers=photo_headers(),
            )
        etag = f'"{photo.sha256}"'
        headers = photo_headers(etag)
        if if_none_match_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return Response(content=photo.data, media_type=photo.content_type, headers=headers)

    def audit_tenant(auth: AuthenticatedTransaction) -> UUID:
        tenant_id = auth.resolved.actor.tenant_id or settings.public_learner_tenant_id
        if tenant_id is None:
            raise HTTPException(503, "A tenant audit boundary is unavailable.")
        return tenant_id

    @router.put("/photo", response_model=SalesXrayProfileResponse)
    async def upload_photo(
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, actor_dependency] = actor_dependency,
    ) -> dict[str, object]:
        """The person's photo: the image itself as the body (the app crops it square)."""
        headers(response)
        actor = auth.resolved.actor
        await require_profile_surface(request, auth)
        require_safe_origin(request, settings)
        data = b""
        async for chunk in request.stream():
            data += chunk
            if len(data) > person_photos.MAX_BYTES:
                raise HTTPException(413, "Choose a photo up to 2 MB.")
        try:
            await person_photos.save_upload(
                auth.database,
                person_id=actor.person_id,
                session_id=actor.session_id,
                tenant_id=audit_tenant(auth),
                content_type=request.headers.get("content-type", ""),
                data=data,
            )
            value = await get_sales_xray_profile(auth.database, person_id=actor.person_id)
        except person_photos.PhotoRejected as error:
            raise HTTPException(422, str(error)) from None
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        return response_value(value)

    @router.delete("/photo", response_model=SalesXrayProfileResponse)
    async def remove_photo(
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, actor_dependency] = actor_dependency,
    ) -> dict[str, object]:
        """Back to Google's photo, or initials."""
        headers(response)
        actor = auth.resolved.actor
        await require_profile_surface(request, auth)
        require_safe_origin(request, settings)
        await person_photos.remove_upload(
            auth.database,
            person_id=actor.person_id,
            session_id=actor.session_id,
            tenant_id=audit_tenant(auth),
        )
        try:
            value = await get_sales_xray_profile(auth.database, person_id=actor.person_id)
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        return response_value(value)

    @router.put("/details", response_model=SalesXrayProfileResponse)
    async def update_details(
        payload: ProfileDetailsUpdate,
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, actor_dependency] = actor_dependency,
    ) -> dict[str, object]:
        """User id, title and team (25 Oct 2026: who did what work)."""
        headers(response)
        actor = auth.resolved.actor
        await require_profile_surface(request, auth)
        require_safe_origin(request, settings)
        try:
            value = await update_profile_details(
                auth.database,
                person_id=actor.person_id,
                session_id=actor.session_id,
                tenant_id=audit_tenant(auth),
                handle=payload.handle,
                title=payload.title,
                team=payload.team,
                expected_revision=payload.expected_revision,
            )
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        except ValueError as error:
            words = {
                "handle_invalid": (
                    "A user id is 3 to 30 letters, digits, dots, dashes or underscores, "
                    "starting with a letter or digit."
                ),
                "handle_reserved": "That user id is kept for Sales X-Ray. Try another.",
            }
            raise HTTPException(
                422, words.get(str(error), "A title or team is one line, up to 80 characters.")
            ) from None
        return response_value(value)

    @router.put("", response_model=SalesXrayProfileResponse)
    async def update_profile(
        payload: SalesXrayProfileUpdate,
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, actor_dependency] = actor_dependency,
    ) -> dict[str, object]:
        headers(response)
        actor = auth.resolved.actor
        await require_profile_surface(request, auth)
        require_safe_origin(request, settings)
        tenant_id = actor.tenant_id or settings.public_learner_tenant_id
        if tenant_id is None:
            raise HTTPException(503, "A tenant audit boundary is unavailable.")
        try:
            value = await update_sales_xray_profile(
                auth.database,
                person_id=actor.person_id,
                session_id=actor.session_id,
                tenant_id=tenant_id,
                full_name=payload.full_name,
                phone_number_e164=payload.phone_number_e164,
                expected_revision=payload.expected_revision,
            )
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        except ValueError:
            raise HTTPException(
                422, "Choose a valid name and explicit E.164 phone number."
            ) from None
        return response_value(value)

    @router.get("/write-eligibility", status_code=204)
    async def write_eligibility(
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> Response:
        headers(response)
        await require_eligibility_surface(request, auth)
        try:
            await require_sales_xray_profile_complete(
                auth.database,
                person_id=auth.resolved.actor.person_id,
            )
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        return Response(
            status_code=204,
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )

    @router.put("/character", response_model=SalesXrayProfileResponse)
    async def choose_character(
        choice: CharacterChoice,
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, actor_dependency] = actor_dependency,
    ) -> dict[str, object]:
        """One of the characters as the person's photo (owner #32, 26 Oct 2026). It replaces
        an uploaded photo, as the app's confirm says; removing the photo goes back to the
        default character."""
        headers(response)
        actor = auth.resolved.actor
        await require_profile_surface(request, auth)
        require_safe_origin(request, settings)
        if not characters.load():
            raise HTTPException(409, "Characters are not available yet.")
        try:
            await person_photos.save_character(
                auth.database,
                person_id=actor.person_id,
                session_id=actor.session_id,
                tenant_id=audit_tenant(auth),
                key=choice.character,
            )
        except characters.CharacterRejected as error:
            raise HTTPException(422, str(error)) from None
        # The profile as GET answers it: the same call with or without the Pulse link.
        return await read_profile(request, response, auth)

    application.include_router(router)

    # Anyone's photo, for the people who share an organisation with them (avatars on
    # leads, notes, tasks and Members; 25 Oct 2026). The ?v= changes with the photo.
    people = APIRouter(prefix="/v1/people", tags=["sales-xray-profile"])

    def on_app_host(request: Request) -> bool:
        allowed_hosts = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            allowed_hosts.add(settings.sales_xray_app_url.host)
        return request.url.hostname in allowed_hosts

    # The characters (owner #32, 26 Oct 2026): the list for the picker and each picture,
    # which never changes for its ?v=.
    @people.get("/characters")
    async def character_list(
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> dict[str, object]:
        if not on_app_host(request) or request.query_params:
            raise HTTPException(404, "Characters not found.")
        response.headers.update({"Cache-Control": "private, no-cache", "Vary": "Cookie"})
        return {
            "characters": [
                {"key": item.key, "label": item.label, "url": item.url}
                for item in characters.load()
            ]
        }

    @people.get("/characters/{key}", response_class=Response)
    async def character_picture(
        key: str,
        request: Request,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> Response:
        chosen = characters.by_key(key)
        if not on_app_host(request) or chosen is None or set(request.query_params) - {"v"}:
            raise HTTPException(404, "Character not found.", headers=photo_headers())
        etag = f'"{chosen.sha256}"'
        exact = request.query_params.get("v") == chosen.sha256[:8]
        cache = {
            **photo_headers(etag),
            "Cache-Control": "private, max-age=31536000, immutable"
            if exact
            else "private, no-cache",
        }
        if if_none_match_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=cache)
        return Response(content=chosen.data, media_type="image/webp", headers=cache)

    @people.get("/{person_id}/photo", response_class=Response)
    async def person_photo(
        person_id: UUID,
        request: Request,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> Response:
        if not on_app_host(request) or set(request.query_params) - {"v"}:
            raise HTTPException(404, "Photo not found.")
        viewer = auth.resolved.actor.person_id
        photo = (
            await person_photos.read_photo(auth.database, person_id)
            if await person_photos.may_see(auth.database, viewer, person_id)
            else None
        )
        if photo is None:
            raise HTTPException(404, "Photo not found.", headers=photo_headers())
        etag = f'"{photo.sha256}"'
        cache = {**photo_headers(etag), "Cache-Control": "private, max-age=86400"}
        if if_none_match_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=cache)
        return Response(content=photo.data, media_type=photo.content_type, headers=cache)

    application.include_router(people)
