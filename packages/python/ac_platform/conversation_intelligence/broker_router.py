"""Fail-closed routing from an admitted reservation to one provider broker.

The application and durable worker own quote issuance, reservation state and
settlement.  This module is the small boundary between that state and the
provider-specific subprocess brokers.  It deliberately receives only opaque
credential references; a child broker remains responsible for launching its
provider process and for handling any injected secret.

Every call reparses the current release approval through ``ConversationAuthority``.
There is no fallback route: a reservation is dispatched only when its exact
source, provider, model, recipe, references, expiry and hosted authorization
match one current stage approval and the mapped child credential reference.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol, cast
from uuid import UUID

from ac_platform.conversation_intelligence.activation_contract import (
    HostedApprovalBundle,
    StageApproval,
)
from ac_platform.conversation_intelligence.entitlements import Reservation
from ac_platform.conversation_intelligence.gemini_tasks import gemini_prompt_view
from ac_platform.conversation_intelligence.inference_broker import InferenceBrokerError
from ac_platform.conversation_intelligence.providers import ProviderResult

_SUPPORTED_PROVIDERS = frozenset({"elevenlabs", "groq", "gemini"})
_REFERENCE = re.compile(r"^ref:[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_SENSITIVE = re.compile(
    r"(?:api[_-]?key|bearer|basic|password|secret|token|sk[-_]|gsk_|aq\.)",
    re.IGNORECASE,
)


class InferenceBroker(Protocol):
    """Structural protocol implemented by ``ProcessInferenceBroker`` and tests."""

    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult: ...


class ProviderRouterError(InferenceBrokerError):
    """Stable router failure code without reservation or credential details."""

    _CODES = frozenset(
        {
            "broker_router_authority_unavailable",
            "broker_router_authorization_mismatch",
            "broker_router_credential_mismatch",
            "broker_router_expired",
            "broker_router_payload_mismatch",
            "broker_router_provider_unconfigured",
            "broker_router_provider_unsupported",
            "broker_router_reservation_invalid",
            "broker_router_route_ambiguous",
            "broker_router_route_mismatch",
            "broker_router_result_mismatch",
        }
    )

    def __init__(self, code: str) -> None:
        # InferenceBrokerError intentionally accepts only its transport error
        # vocabulary.  Router errors need their own stable namespace while
        # remaining catchable by callers that already handle broker failures.
        self.code = code if code in self._CODES else "broker_failed"
        ValueError.__init__(self, self.code)


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """One immutable provider mapping, containing a reference but no secret."""

    provider_id: str
    credential_ref: str
    broker: InferenceBroker

    def __post_init__(self) -> None:
        if self.provider_id not in _SUPPORTED_PROVIDERS:
            raise ValueError("unsupported provider route")
        if (
            not isinstance(self.credential_ref, str)
            or _REFERENCE.fullmatch(self.credential_ref) is None
            or _SENSITIVE.search(self.credential_ref) is not None
        ):
            raise ValueError("invalid provider credential reference")
        if not callable(getattr(self.broker, "execute", None)):
            raise TypeError("provider route requires an executable broker")


CurrentAuthority = Callable[[datetime], HostedApprovalBundle]
Clock = Callable[[], datetime | int | float]


class FixedProviderRouter:
    """Route approved C2/C4/C5 reservations to their fixed child broker.

    ``routes`` is normally ``{"elevenlabs": ProviderRoute(...), "groq":
    ProviderRoute(...)}``.  A partial mapping is accepted so deployments can
    bring up one route at a time; a missing route fails before its child is
    touched.  ``current_authority`` is useful for composition tests and must
    return the freshly loaded approval bundle for the supplied instant.
    """

    def __init__(
        self,
        routes: Mapping[str, ProviderRoute],
        *,
        authority: Any | None = None,
        current_authority: CurrentAuthority | None = None,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        if authority is not None and current_authority is not None:
            raise ValueError("choose one current authority source")
        if authority is None and current_authority is None:
            raise ValueError("current authority is required")
        if not isinstance(routes, Mapping):
            raise TypeError("provider routes must be a mapping")
        fixed: dict[str, ProviderRoute] = {}
        for provider_id, route in routes.items():
            if provider_id not in _SUPPORTED_PROVIDERS:
                raise ValueError("unsupported provider route")
            if not isinstance(route, ProviderRoute) or route.provider_id != provider_id:
                raise ValueError("provider route key mismatch")
            fixed[provider_id] = route
        if not callable(clock):
            raise TypeError("router clock must be callable")
        self._routes: Mapping[str, ProviderRoute] = MappingProxyType(fixed)
        self._current_authority: CurrentAuthority = (
            current_authority
            if current_authority is not None
            else self._authority_method(authority)
        )
        self._clock = clock

    @staticmethod
    def _authority_method(authority: Any) -> CurrentAuthority:
        current = getattr(authority, "current", None)
        if not callable(current):
            raise TypeError("authority must provide current(now)")
        return cast(CurrentAuthority, current)

    def _now(self) -> tuple[datetime, int]:
        try:
            value = self._clock()
            if isinstance(value, datetime):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError
                now = value.astimezone(UTC)
            elif type(value) in {int, float} and value > 0:
                now = datetime.fromtimestamp(float(value), UTC)
            else:
                raise ValueError
            epoch = int(now.timestamp())
            if epoch <= 0:
                raise ValueError
            return now, epoch
        except (OverflowError, OSError, TypeError, ValueError):
            raise ProviderRouterError("broker_router_authority_unavailable") from None

    def _current_bundle(self, now: datetime) -> HostedApprovalBundle:
        try:
            bundle = self._current_authority(now)
            # A callback may return a mutable/forged object.  Reparse its
            # canonical bytes before using any field for authorization.
            canonical_bundle = HostedApprovalBundle.model_validate_json(bundle.to_json())
            # ConversationAuthority checks its configured environment.  The
            # router also checks the signed window itself so a direct test or
            # hosted composition callback cannot return a future bundle.
            return canonical_bundle.current(int(now.timestamp()), canonical_bundle.environment)
        except Exception:
            # The authority implementation already emits a content-free
            # denial.  The router must preserve that property at this boundary.
            raise ProviderRouterError("broker_router_authority_unavailable") from None

    @staticmethod
    def _stage(reservation: Reservation, bundle: HostedApprovalBundle) -> StageApproval:
        quote = reservation.quote
        # A public source has no pre-issued source row in the release bundle.
        # Derive the candidate from the immutable policy and source binding,
        # then require the permission reference to name that derived approval.
        # This keeps a reservation payload from selecting a wildcard provider
        # route or borrowing a different source's stage.
        policy = bundle.acquisition_policy
        if policy is not None:
            try:
                tenant_id = UUID(quote.source.tenant_id)
                person_id = UUID(quote.account_id)
                if tenant_id == policy.tenant_id and person_id == policy.processing_person_id:
                    derived = tuple(
                        policy.derive_stage(
                            tenant_id=tenant_id,
                            person_id=person_id,
                            source_sha256=quote.source.source_sha256,
                            stage=stage,
                        )
                        for stage in ("C2", "C4", "C5")
                    )
                    by_route = tuple(
                        item
                        for item in derived
                        if (
                            item.provider_id,
                            item.model_id,
                            item.recipe_revision,
                        )
                        == (
                            quote.provider_id,
                            quote.provider_model,
                            quote.recipe_revision,
                        )
                    )
                    if len(by_route) == 1:
                        return by_route[0]
                for stage in ("C2", "C4", "C5"):
                    candidate = policy.derive_stage(
                        tenant_id=tenant_id,
                        person_id=person_id,
                        source_sha256=quote.source.source_sha256,
                        stage=stage,
                    )
                    if reservation.permission.authorization_ref == (
                        f"hosted-stage-v1:{candidate.id}:{bundle.digest}"
                    ):
                        return candidate
                if tenant_id == policy.tenant_id and person_id == policy.processing_person_id:
                    raise ProviderRouterError("broker_router_route_mismatch")
            except (TypeError, ValueError):
                # The static exact-source path below will fail closed if this
                # is not a valid hosted reservation.
                pass
        candidates = tuple(
            item
            for item in bundle.stages
            if (
                item.stage in {"C2", "C4", "C5"}
                and str(item.tenant_id) == quote.source.tenant_id
                and str(item.person_id) == quote.account_id
                and item.source_sha256 == quote.source.source_sha256
                and item.provider_id == quote.provider_id
                and item.model_id == quote.provider_model
                and item.recipe_revision == quote.recipe_revision
            )
        )
        if len(candidates) != 1:
            code = (
                "broker_router_route_ambiguous"
                if len(candidates) > 1
                else "broker_router_route_mismatch"
            )
            raise ProviderRouterError(code)
        return candidates[0]

    @staticmethod
    def _validate(
        reservation: Reservation,
        payload: bytes,
        bundle: HostedApprovalBundle,
        approval: StageApproval,
        route: ProviderRoute,
        epoch: int,
    ) -> None:
        quote = reservation.quote
        permission = reservation.permission
        if type(payload) is not bytes:
            raise ProviderRouterError("broker_router_payload_mismatch")
        if reservation.state != "in_flight" or not reservation.attempt_id:
            raise ProviderRouterError("broker_router_reservation_invalid")
        if quote.max_cost_paise != approval.max_cost_paise or (
            quote.max_cost_paise > 0
            and (
                approval.zero_cost_basis != "paid_pricing_evidence"
                or not bundle.paid_approval_ref
                or quote.max_cost_paise > bundle.budget_cap_paise
            )
        ):
            raise ProviderRouterError("broker_router_authorization_mismatch")
        if hashlib.sha256(payload).hexdigest() != quote.input_sha256:
            raise ProviderRouterError("broker_router_payload_mismatch")
        # C2 is the only stage that receives source bytes.  Keep the source
        # binding explicit here so a caller cannot authorize another payload
        # merely by changing the quote's input digest.
        if approval.stage == "C2" and quote.input_sha256 != quote.source.source_sha256:
            raise ProviderRouterError("broker_router_payload_mismatch")
        if len(payload) > approval.max_input_bytes:
            raise ProviderRouterError("broker_router_payload_mismatch")
        if approval.provider_id == "gemini" and approval.stage in {"C4", "C5"}:
            try:
                body = json.loads(payload)
                maximum = body["generationConfig"]["maxOutputTokens"]
                if type(maximum) is not int or maximum > approval.max_completion_tokens:
                    raise ValueError
                gemini_prompt_view(body, model=approval.model_id, maximum=maximum)
            except (KeyError, TypeError, ValueError):
                raise ProviderRouterError("broker_router_payload_mismatch") from None
        if not (
            quote.created_at_epoch <= epoch < quote.expires_at_epoch
            and epoch < permission.expires_at_epoch
            and epoch < approval.expires_at_epoch
            and epoch < bundle.expires_at_epoch
        ):
            raise ProviderRouterError("broker_router_expired")
        if (
            quote.expires_at_epoch > approval.expires_at_epoch
            or quote.expires_at_epoch > bundle.expires_at_epoch
            or permission.expires_at_epoch > quote.expires_at_epoch
        ):
            raise ProviderRouterError("broker_router_expired")
        if quote.budget_scope_id != str(bundle.budget_scope_id):
            raise ProviderRouterError("broker_router_authorization_mismatch")
        if permission.authorization_ref != f"hosted-stage-v1:{approval.id}:{bundle.digest}":
            raise ProviderRouterError("broker_router_authorization_mismatch")
        if permission.approved_by != quote.account_id:
            raise ProviderRouterError("broker_router_authorization_mismatch")
        if permission.quote_fingerprint != quote.fingerprint:
            raise ProviderRouterError("broker_router_authorization_mismatch")
        if quote.privacy_revision != approval.privacy_revision:
            raise ProviderRouterError("broker_router_authorization_mismatch")
        for quote_field, approval_field in (
            ("permission_ref", "permission_ref"),
            ("provider_terms_ref", "provider_terms_ref"),
            ("retention_ref", "retention_ref"),
            ("professional_gate_ref", "professional_gate_ref"),
            ("pricing_ref", "pricing_ref"),
        ):
            if getattr(quote, quote_field) != getattr(approval, approval_field):
                raise ProviderRouterError("broker_router_authorization_mismatch")
        expected_operation = (
            "transcribe_scribe_v2" if approval.stage == "C2" else "extract_context_evidence"
        )
        if quote.operation != expected_operation:
            raise ProviderRouterError("broker_router_route_mismatch")
        if approval.stage == "C2" and approval.provider_id != "elevenlabs":
            raise ProviderRouterError("broker_router_route_mismatch")
        if approval.stage in {"C4", "C5"} and approval.provider_id not in {"groq", "gemini"}:
            raise ProviderRouterError("broker_router_route_mismatch")
        if route.credential_ref != approval.credential_ref:
            raise ProviderRouterError("broker_router_credential_mismatch")

    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        """Authorize and dispatch exactly once to the matching child broker."""

        if not isinstance(reservation, Reservation):
            raise ProviderRouterError("broker_router_reservation_invalid")
        now, epoch = self._now()
        bundle = self._current_bundle(now)
        try:
            approval = self._stage(reservation, bundle)
            route = self._routes.get(reservation.quote.provider_id)
            if route is None:
                raise ProviderRouterError("broker_router_provider_unconfigured")
            self._validate(reservation, payload, bundle, approval, route, epoch)
        except ProviderRouterError:
            raise
        except (AttributeError, TypeError, ValueError):
            raise ProviderRouterError("broker_router_authorization_mismatch") from None
        try:
            result = await route.broker.execute(reservation, payload)
        except asyncio.CancelledError:
            raise
        except InferenceBrokerError:
            raise
        except Exception:
            # Provider failures can contain source, response or credential
            # text.  Preserve only the stable router boundary code.
            raise ProviderRouterError("broker_failed") from None
        if not isinstance(result, ProviderResult):
            raise ProviderRouterError("broker_router_result_mismatch")
        if (
            result.provider != reservation.quote.provider_id
            or result.model != reservation.quote.provider_model
            or result.input_sha256 != reservation.quote.input_sha256
            or type(result.raw_json) is not bytes
            or hashlib.sha256(result.raw_json).hexdigest() != result.response_sha256
        ):
            raise ProviderRouterError("broker_router_result_mismatch")
        return result


# These aliases keep the composition seam discoverable without creating
# multiple implementations or alternate authorization paths.
ProviderBrokerRouter = FixedProviderRouter
BrokerRouter = FixedProviderRouter


__all__ = [
    "BrokerRouter",
    "CurrentAuthority",
    "FixedProviderRouter",
    "InferenceBroker",
    "ProviderBrokerRouter",
    "ProviderRoute",
    "ProviderRouterError",
]
