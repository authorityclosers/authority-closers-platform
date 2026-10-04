"""Owner-only DNS TXT verification for the selected customer organisation."""

import shlex
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.http.organisation import OrganisationResponse
from ac_platform.identity.services import TenantScopeDeniedError
from ac_platform.kernel.errors import AuthorizationDenied, DomainError, ResourceNotFound
from ac_platform.organisations.service import OrganisationService, _normalize_domain
from ac_platform.tenancy.models import Membership, Organisation, Tenant


class DomainsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    verified_domains: list[str]
    auto_join: bool


class DomainVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    record_name: str
    record_value: str


class ResolverUnavailable(DomainError):
    status = 503
    code = "dns_resolver_unavailable"


async def verify_dns_txt(domain: str, token: str, resolver_url: str) -> None:
    name = f"_ac-verify.{domain}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                resolver_url,
                params={"name": name, "type": "TXT"},
                headers={"accept": "application/dns-json"},
            )
            response.raise_for_status()
            answer = response.json()
        if answer["Status"] not in {0, 3} or answer.get("TC", False):
            raise ValueError("DNS resolution failed")
        records = answer.get("Answer", []) if answer["Status"] == 0 else []
        for record in records:
            if (
                record["type"] == 16
                and record["name"].rstrip(".").lower() == name
                and "".join(shlex.split(record["data"])) == f"ac-verify={token}"
            ):
                return
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ResolverUnavailable("The DNS resolver is unavailable. Try again later.") from error
    raise DomainError(f"Missing DNS TXT verification record for {domain}.")


def install_organisation_domains_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    router = APIRouter(prefix="/v1/organisation/domains", tags=["organisation"])

    async def owner(
        request: Request, response: Response
    ) -> AsyncIterator[AuthenticatedTransaction]:
        if request.method != "GET":
            require_safe_origin(request, settings)
        try:
            resolver = require_actor.read_only if request.method == "GET" else require_actor  # type: ignore[attr-defined]
            async for auth in resolver(request):
                tenant_id = auth.resolved.actor.tenant_id
                if (
                    tenant_id
                    in {None, settings.operations_tenant_id, settings.public_learner_tenant_id}
                    or await auth.database.get(Organisation, tenant_id) is None
                ):
                    raise ResourceNotFound("No organisation selected.")
                if auth.resolved.membership_role != "owner":
                    raise AuthorizationDenied("Only the organisation owner can set domains.")
                response.headers["cache-control"] = "private, no-store"
                response.headers["vary"] = "Cookie"
                yield auth
        except TenantScopeDeniedError as error:
            raise ResourceNotFound("No organisation selected.") from error

    owner_dependency = Depends(owner, scope="function")

    @router.get("/verification", response_model=DomainVerificationResponse)
    async def verification(
        domain: Annotated[str, Query(min_length=1, max_length=254)],
        auth: AuthenticatedTransaction = owner_dependency,
    ) -> DomainVerificationResponse:
        domain = _normalize_domain(domain)
        organisation = await auth.database.get(Organisation, auth.resolved.actor.tenant_id)
        assert organisation is not None
        return DomainVerificationResponse(
            record_name=f"_ac-verify.{domain}",
            record_value=f"ac-verify={organisation.domain_verification_token}",
        )

    @router.put("", response_model=OrganisationResponse)
    async def domains(
        body: DomainsRequest,
        key: Annotated[str, Header(alias="Idempotency-Key")],
        auth: AuthenticatedTransaction = owner_dependency,
    ) -> OrganisationResponse:
        try:
            command_id = UUID(key.strip())
            if command_id.version != 4 or str(command_id) != key.strip().lower():
                raise ValueError("invalid command ID")
        except ValueError as error:
            raise DomainError("Idempotency-Key must be a canonical UUIDv4.") from error
        actor = auth.resolved.actor
        assert actor.tenant_id is not None
        if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
            raise DomainError("Organisation tenant boundaries are not configured.")

        async def verify(domain: str, token: str) -> None:
            await verify_dns_txt(domain, token, str(settings.organisation_dns_resolver_url))

        result = await OrganisationService(
            auth.database,
            operations_tenant_id=settings.operations_tenant_id,
            public_learner_tenant_id=settings.public_learner_tenant_id,
        ).set_domains_attested(
            actor.tenant_id,
            body.verified_domains,
            body.auto_join,
            f"dns_txt:{actor.person_id}",
            command_id,
            actor_person_id=actor.person_id,
            reason="dns_txt",
            verify_domain=verify,
        )
        tenant = await auth.database.get(Tenant, actor.tenant_id)
        assert tenant is not None
        count = await auth.database.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == actor.tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        return OrganisationResponse(
            tenant_id=actor.tenant_id,
            name=tenant.name,
            role="owner",
            verified_domains=list(result.verified_domains),
            auto_join=result.auto_join,
            member_count=count or 0,
        )

    application.include_router(router)
