"""C2 read-only Admin customer list using existing platform authority."""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from pydantic import ValidationError
from starlette.middleware.base import RequestResponseEndpoint

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.billing.ledger import BillingError
from ac_platform.billing.trial import TrialPolicy
from ac_platform.customers.read_models import (
    CustomerPage,
    CustomerQuery,
    customer_page,
    decode_cursor,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_admin_surface
from ac_platform.kernel.errors import DomainError


class CustomerValidationFailed(DomainError):
    code = "validation_failed"
    title = "Customer query is invalid"


class CustomerReadUnavailable(DomainError):
    code = "customer_read_unavailable"
    title = "Customer directory is unavailable"
    status = 503


def install_admin_customers_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    @application.middleware("http")
    async def no_store(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.url.path == "/v1/admin/customers":
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_surface(request: Request) -> None:
        require_admin_surface(request, settings)

    router = APIRouter(dependencies=[Depends(require_surface)], tags=["admin-customers"])
    actor_dependency = Depends(getattr(require_actor, "read_only", require_actor), scope="function")

    @router.get("/v1/admin/customers", response_model=CustomerPage)
    async def customers(
        request: Request, auth: AuthenticatedTransaction = actor_dependency
    ) -> CustomerPage:
        permissions = await platform_projection(
            auth.database, auth.resolved.actor, operations_tenant_id=settings.operations_tenant_id
        )
        if "platform_tenants_read" not in permissions:
            raise CapabilityDenied("A current platform tenant-read assignment is required.")
        try:
            pairs = request.query_params.multi_items()
            if len({key for key, _ in pairs}) != len(pairs):
                raise ValueError
            values: dict[str, object] = dict(pairs)
            if "limit" in values:
                if re.fullmatch(r"[0-9]{1,2}", str(values["limit"])) is None:
                    raise ValueError
                values["limit"] = int(str(values["limit"]))
            query = CustomerQuery.model_validate(values)
            if query.cursor is not None:
                decode_cursor(query.cursor)
        except (ValueError, ValidationError) as error:
            raise CustomerValidationFailed("Use only valid C2 customer list parameters.") from error
        public, operations = settings.public_learner_tenant_id, settings.operations_tenant_id
        if public is None or operations is None or public == operations:
            raise CustomerReadUnavailable("Customer tenant boundaries are not configured.")
        try:
            return await customer_page(
                auth.database,
                public_tenant_id=public,
                operations_tenant_id=operations,
                query=query,
                now=datetime.now(UTC),
                trial_policy=TrialPolicy(
                    settings.sales_xray_trial_policy, settings.sales_xray_trial_policy_switch_at
                ),
            )
        except (ValueError, BillingError) as error:
            raise CustomerReadUnavailable("Canonical customer data could not be read.") from error

    application.include_router(router)
