"""Hash-pinned, account-bound exemptions for AC's named internal testers.

The release approval names exact email identities and scopes.  Every caller
re-resolves the current Person and membership before applying one scope; no
browser claim, environment variable, or guest credential can grant the
exemption.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import Scope

from ac_platform.conversation_intelligence.activation_contract import (
    HostedApprovalBundle,
    InternalTesterApproval,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, MembershipStatus

InternalTesterScope = Literal[
    "account_minutes",
    "analysis_count",
    "ip_session_issuance",
    "provider_stage_request_count",
]
INTERNAL_TESTER_SCOPES: tuple[InternalTesterScope, ...] = (
    "account_minutes",
    "analysis_count",
    "ip_session_issuance",
    "provider_stage_request_count",
)
_SESSION_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43,512}$")


class _BundleLoader(Protocol):
    def __call__(self) -> HostedApprovalBundle: ...


@dataclass(frozen=True, slots=True)
class InternalTesterPolicy:
    """Re-resolving access wrapper around one pinned approval loader."""

    loader: _BundleLoader
    environment: str

    def current(self) -> HostedApprovalBundle:
        bundle = self.loader()
        bundle.current(int(datetime.now(UTC).timestamp()), self.environment)
        return bundle

    @staticmethod
    def _approval(
        bundle: HostedApprovalBundle, email: str, scope: InternalTesterScope
    ) -> InternalTesterApproval | None:
        normalized = email.strip().casefold()
        return next(
            (
                approval
                for approval in bundle.internal_tester_accounts
                if approval.email == normalized and scope in approval.scopes
            ),
            None,
        )

    async def for_learner_account(
        self,
        database: AsyncSession,
        *,
        tenant_id: UUID,
        person_id: UUID,
        bundle: HostedApprovalBundle | None = None,
    ) -> InternalTesterApproval | None:
        """Resolve the current account-minute scope for an exact learner."""

        if type(tenant_id) is not UUID or type(person_id) is not UUID:
            return None
        person = await database.scalar(
            select(Person).where(Person.id == person_id).execution_options(populate_existing=True)
        )
        membership = await database.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == person_id,
            )
            .execution_options(populate_existing=True)
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is None
            or membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.role != "learner"
            or membership.ended_at is not None
        ):
            return None
        try:
            return self._approval(bundle or self.current(), person.email or "", "account_minutes")
        except (TypeError, ValueError, OSError):
            # An unavailable or stale approval cannot confer unlimited access.
            return None

    async def for_actor(
        self,
        database: AsyncSession,
        actor: ActorContext | ProcessingActor,
        scope: InternalTesterScope,
        *,
        bundle: HostedApprovalBundle | None = None,
    ) -> InternalTesterApproval | None:
        """Return the current approval only for a live verified account."""

        if isinstance(actor, ProcessingActor) or actor.tenant_id is None:
            return None
        if scope == "provider_stage_request_count":
            return await self.for_human_owner(
                database,
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                scope=scope,
                bundle=bundle,
            )
        person = await database.scalar(
            select(Person)
            .where(Person.id == actor.person_id)
            .execution_options(populate_existing=True)
        )
        membership = await database.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == actor.tenant_id,
                Membership.person_id == actor.person_id,
            )
            .execution_options(populate_existing=True)
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is None
            or membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.role == "processing"
            or membership.ended_at is not None
        ):
            return None
        try:
            return self._approval(bundle or self.current(), person.email or "", scope)
        except (TypeError, ValueError, OSError):
            # A stale or unavailable release approval must fail closed.
            return None

    async def for_human_owner(
        self,
        database: AsyncSession,
        *,
        tenant_id: UUID,
        person_id: UUID,
        scope: InternalTesterScope,
        bundle: HostedApprovalBundle | None = None,
    ) -> InternalTesterApproval | None:
        """Resolve a tester scope for an already source-bound human owner.

        Processing callers must resolve ``person_id`` through the canonical
        submission usage and claim rows before calling this method. Only the
        provider-stage request-count scope is available to such processing
        callers; a shared processing identity never supplies tester authority.
        """

        if scope != "provider_stage_request_count":
            return None
        if type(tenant_id) is not UUID or type(person_id) is not UUID:
            return None
        person = await database.scalar(
            select(Person).where(Person.id == person_id).execution_options(populate_existing=True)
        )
        membership = await database.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == person_id,
            )
            .execution_options(populate_existing=True)
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is None
            or membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.role == "processing"
            or membership.ended_at is not None
        ):
            return None
        try:
            return self._approval(bundle or self.current(), person.email or "", scope)
        except (TypeError, ValueError, OSError):
            # A stale or unavailable release approval must fail closed.
            return None

    def view(self, bundle: HostedApprovalBundle | None = None) -> dict[str, Any]:
        """Return a safe Admin projection without authorization references."""
        return internal_tester_view(bundle or self.current())


def internal_tester_view(bundle: HostedApprovalBundle) -> dict[str, Any]:
    accounts = tuple(bundle.internal_tester_accounts)
    return {
        "enabled": bool(accounts),
        "accounts": [item.email for item in accounts],
        "scopes": sorted({scope for item in accounts for scope in item.scopes}),
        "source": "hash_pinned_hosted_approval",
        "bundle_digest": bundle.digest,
        "limits_remaining_bounded": [
            "provider_stage_approval",
            "provider_budget_and_usage",
            "source_size_and_retention_storage",
            "guest_session_ip_rate_limit_without_named_account_session",
        ],
    }


def _cookie_value(scope: Scope, name: str) -> str | None:
    values: list[str] = []
    for key, raw in scope.get("headers", []):
        if key.lower() != b"cookie":
            continue
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            return None
        for part in text.split(";"):
            item = part.strip()
            if "=" not in item:
                return None
            candidate, value = item.split("=", 1)
            if candidate != name or not value or not _SESSION_TOKEN.fullmatch(value):
                continue
            values.append(value)
    if len(values) != 1:
        return None
    return values[0]


async def account_rate_limit_exemption(
    scope: Scope,
    rule_name: str,
    *,
    settings: Any,
    sessions: async_sessionmaker[AsyncSession],
    policy: InternalTesterPolicy,
) -> bool:
    """Resolve the account cookie just for the guest-session IP shield.

    The middleware invokes this only after selecting a rate-limit rule.  A
    missing, malformed, expired, revoked, or wrong-tenant cookie returns
    ``False`` and therefore remains in the normal IP bucket.
    """

    if rule_name != "conversation-acquisition-session":
        return False
    token = _cookie_value(scope, settings.session_cookie_name)
    if token is None:
        return False
    try:
        pepper = settings.session_token_pepper.get_secret_value().encode("utf-8")
        token_hash = hmac.new(pepper, token.encode("ascii"), hashlib.sha256).digest()
        async with sessions() as database, database.begin():
            session = await database.scalar(
                select(IdentitySession)
                .where(IdentitySession.token_hash == token_hash)
                .execution_options(populate_existing=True)
            )
            now = datetime.now(UTC)
            if (
                session is None
                or session.audience != "account"
                or session.selected_tenant_id != settings.public_learner_tenant_id
                or not session.is_active_at(now)
            ):
                return False
            person = await database.scalar(
                select(Person)
                .where(Person.id == session.person_id)
                .execution_options(populate_existing=True)
            )
            membership = await database.scalar(
                select(Membership)
                .where(
                    Membership.tenant_id == session.selected_tenant_id,
                    Membership.person_id == session.person_id,
                )
                .execution_options(populate_existing=True)
            )
            if (
                person is None
                or person.status != PersonStatus.ACTIVE.value
                or person.email_verified_at is None
                or membership is None
                or membership.status != MembershipStatus.ACTIVE.value
                or membership.role == "processing"
                or membership.ended_at is not None
            ):
                return False
            approval = policy._approval(policy.current(), person.email or "", "ip_session_issuance")
            return approval is not None
    except (OSError, TypeError, ValueError, UnicodeError):
        return False


def tester_rate_limit_resolver(
    *,
    settings: Any,
    sessions: async_sessionmaker[AsyncSession],
    policy: InternalTesterPolicy,
) -> Callable[[Scope, str], Awaitable[bool]]:
    async def resolve(scope: Scope, rule_name: str) -> bool:
        return await account_rate_limit_exemption(
            scope,
            rule_name,
            settings=settings,
            sessions=sessions,
            policy=policy,
        )

    return resolve


__all__ = [
    "INTERNAL_TESTER_SCOPES",
    "InternalTesterPolicy",
    "InternalTesterScope",
    "account_rate_limit_exemption",
    "internal_tester_view",
    "tester_rate_limit_resolver",
]
