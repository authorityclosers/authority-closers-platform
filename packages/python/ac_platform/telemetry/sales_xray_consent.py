"""Who Sales X-Ray records usage analytics for (owner, 24 Oct 2026: "Telemetry consent: option
B. Workspace switch on by default with a per-person opt-out, and a privacy-policy line").

- A workspace records usage analytics unless an owner or admin turns it off for the workspace.
- A person is recorded unless they turn it off for themselves (Settings, Privacy). Their choice
  holds in every workspace they belong to.
- Sandbox workspaces never record it.
- Each choice is an append-only audit event (resource ``sales_xray_product_analytics``): the
  workspace's under resource id ``workspace``, a person's under their person id, each with the
  notice version they were shown. The newest event is the choice; nothing is overwritten.

``sales_xray_consent`` is the intake's consent resolver. It answers granted (with the notice
version and when recording last began), denied (switched off), or nothing for a sandbox (the
intake then refuses and lists no events).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.telemetry.ingest import TelemetryConsent, TelemetryConsentStatus
from ac_platform.telemetry.sales_xray import NOTICE_EFFECTIVE_AT, NOTICE_VERSION
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.roles import roles_with

RESOURCE_TYPE = "sales_xray_product_analytics"
WORKSPACE_RESOURCE = "workspace"
WORKSPACE_ACTION = "telemetry.sales_xray_analytics_workspace.v1"
PERSON_ACTION = "telemetry.sales_xray_analytics_person.v1"
MANAGER_ROLES = frozenset(roles_with("org.manage"))

Scope = Literal["workspace", "person"]


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


@dataclass(frozen=True)
class Choice:
    """A switch's state: on unless the newest choice turned it off (``at`` None: never set)."""

    enabled: bool
    at: datetime | None = None


@dataclass(frozen=True)
class Standing:
    sandbox: bool
    workspace: Choice
    person: Choice

    @property
    def collecting(self) -> bool:
        return not self.sandbox and self.workspace.enabled and self.person.enabled

    @property
    def since(self) -> datetime:
        """When recording last began: the notice, or a later switch back on."""
        moments = [NOTICE_EFFECTIVE_AT]
        moments += [item.at for item in (self.workspace, self.person) if item.at is not None]
        return max(moments)


def _newest(connection: Any, tenants: list[UUID], resource_id: str) -> Choice:
    row = connection.execute(
        select(AuditEvent.payload, AuditEvent.occurred_at)
        .where(
            AuditEvent.tenant_id.in_(tenants),
            AuditEvent.resource_type == RESOURCE_TYPE,
            AuditEvent.resource_id == resource_id,
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.sequence_no.desc())
        .limit(1)
    ).first()
    if row is None:
        return Choice(enabled=True)
    payload = row[0] if isinstance(row[0], dict) else {}
    return Choice(enabled=payload.get("enabled") is not False, at=_utc(row[1]))


def read_standing(connection: Any, *, tenant_id: UUID, person_id: UUID) -> Standing:
    """This person's standing in this workspace (a sync session or connection)."""
    sandbox = (
        connection.execute(
            select(ConversationSandboxOrganisation.tenant_id).where(
                ConversationSandboxOrganisation.tenant_id == tenant_id
            )
        ).first()
        is not None
    )
    # A person's choice holds in every workspace: read it from each one they belong to.
    tenants = {
        row[0]
        for row in connection.execute(
            select(Membership.tenant_id).where(Membership.person_id == person_id)
        )
    }
    tenants.add(tenant_id)
    return Standing(
        sandbox=sandbox,
        workspace=_newest(connection, [tenant_id], WORKSPACE_RESOURCE),
        person=_newest(connection, sorted(tenants), str(person_id)),
    )


async def standing_for(database: Any, actor: ActorContext) -> Standing | None:
    tenant_id = actor.tenant_id
    if tenant_id is None:
        return None

    def read(connection: Any) -> Standing:
        return read_standing(connection, tenant_id=tenant_id, person_id=actor.person_id)

    result: Standing = await database.run_sync(read)
    return result


async def sales_xray_consent(database: Any, actor: ActorContext) -> TelemetryConsent | None:
    """The intake's consent resolver for Sales X-Ray (option B)."""
    standing = await standing_for(database, actor)
    if standing is None or standing.sandbox or actor.tenant_id is None:
        return None
    return TelemetryConsent(
        status=(
            TelemetryConsentStatus.GRANTED if standing.collecting else TelemetryConsentStatus.DENIED
        ),
        policy_version=NOTICE_VERSION,
        captured_at=standing.since,
        tenant_id=actor.tenant_id,
        person_id=actor.person_id,
        session_id=actor.session_id,
    )


async def record_choice(
    database: Any,
    actor: ActorContext,
    *,
    scope: Scope,
    enabled: bool,
    now: datetime,
) -> None:
    """Append a person's or a workspace's choice to the workspace's audit chain."""
    if actor.tenant_id is None:
        raise ValueError("a workspace is required")
    whose = "the whole workspace" if scope == "workspace" else "themselves"
    await AuditRepository(database).append(
        tenant_id=actor.tenant_id,
        actor_person_id=actor.person_id,
        session_id=actor.session_id,
        action=WORKSPACE_ACTION if scope == "workspace" else PERSON_ACTION,
        resource_type=RESOURCE_TYPE,
        resource_id=WORKSPACE_RESOURCE if scope == "workspace" else str(actor.person_id),
        payload={"enabled": enabled, "notice_version": NOTICE_VERSION},
        reason=f"Turned Sales X-Ray usage analytics {'on' if enabled else 'off'} for {whose}.",
        now=now,
    )


__all__ = [
    "MANAGER_ROLES",
    "PERSON_ACTION",
    "RESOURCE_TYPE",
    "WORKSPACE_ACTION",
    "WORKSPACE_RESOURCE",
    "Choice",
    "Standing",
    "read_standing",
    "record_choice",
    "sales_xray_consent",
    "standing_for",
]
