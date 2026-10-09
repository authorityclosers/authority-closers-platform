"""ADR 0055 credential transitions in a caller-owned transaction.

Never raise an HTTP error inside a transaction after a security revocation:
return the outcome so the caller commits reuse/membership revocations first.
Secrets are returned only to their native caller and persisted only as hashes.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.db.models import companion_credentials as credentials
from ac_platform.db.models import companion_devices as devices
from ac_platform.db.models import companion_pairings as pairings
from ac_platform.db.models import companion_refresh_families as families
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Tenant

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class NativeOutcome:
    body: dict[str, Any] = field(repr=False)
    status: int = 200


def failure(code: str, status: int) -> NativeOutcome:
    return NativeOutcome({"code": code}, status)


class NativeDevices:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        device_limit: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self.db = database
        self.clock = clock
        self.device_limit = device_limit

    async def start(self, name: str, platform: str) -> NativeOutcome:
        now = self.clock()
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        poll_secret = secrets.token_urlsafe(32)
        pairing_id = uuid4()
        expiry = now + timedelta(minutes=10)
        await self.db.execute(
            insert(pairings).values(
                id=pairing_id,
                code_sha256=digest(code),
                poll_secret_sha256=digest(poll_secret),
                name=name,
                platform=platform,
                state="pending",
                created_at=now,
                expires_at=expiry,
            )
        )
        return NativeOutcome(
            {
                "pairing_id": str(pairing_id),
                "code": code,
                "poll_secret": poll_secret,
                "expires_at": expiry.isoformat(),
                "poll_interval_seconds": 5,
            },
            201,
        )

    async def _membership(self, tenant_id: UUID, person_id: UUID) -> bool:
        # Current canonical person, tenant and membership state, held through
        # the transition. Shared locks fence removal without serializing reads.
        row = (
            await self.db.execute(
                select(Membership.status, Person.status, Tenant.status)
                .join(Person, Person.id == Membership.person_id)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
                .with_for_update(read=True)
            )
        ).first()
        return row is not None and all(value == "active" for value in row)

    async def _audit(
        self,
        device: Mapping[Any, Any],
        action: str,
        *,
        resource_id: UUID,
        actor: ActorContext | None = None,
    ) -> None:
        await AuditRepository(self.db).append(
            tenant_id=device["tenant_id"],
            actor_person_id=device["person_id"],
            session_id=actor.session_id if actor else None,
            actor_type="person" if actor else "device",
            action=action,
            resource_type="companion_device",
            resource_id=resource_id,
            payload={"device_id": str(device["id"])},
            now=self.clock(),
        )

    async def decide(self, code: str, approve: bool, actor: ActorContext) -> NativeOutcome:
        if actor.tenant_id is None or not await self._membership(actor.tenant_id, actor.person_id):
            return failure("workspace_membership_required", 403)
        row = (
            (
                await self.db.execute(
                    select(pairings).where(pairings.c.code_sha256 == digest(code)).with_for_update()
                )
            )
            .mappings()
            .first()
        )
        now = self.clock()
        if row is None:
            return failure("pairing_not_found", 404)
        if utc(row["expires_at"]) <= now:
            return failure("pairing_expired", 410)
        if row["state"] != "pending":
            return failure("pairing_already_decided", 409)
        device_id = uuid4() if approve else None
        if approve:
            await self.db.execute(
                insert(devices).values(
                    id=device_id,
                    tenant_id=actor.tenant_id,
                    person_id=actor.person_id,
                    name=row["name"],
                    platform=row["platform"],
                    created_at=now,
                )
            )
        await self.db.execute(
            update(pairings)
            .where(pairings.c.id == row["id"])
            .values(
                state="approved" if approve else "denied",
                device_id=device_id,
                decided_at=now,
            )
        )
        await AuditRepository(self.db).append_for_actor(
            actor,
            action="native.pair.approve" if approve else "native.pair.deny",
            resource_type="companion_pairing",
            resource_id=row["id"],
            payload={"device_id": str(device_id) if device_id else None},
            now=now,
        )
        return NativeOutcome({"state": "approved" if approve else "denied"})

    async def _device(self, device_id: UUID) -> Mapping[Any, Any] | None:
        reference = (
            (await self.db.execute(select(devices).where(devices.c.id == device_id)))
            .mappings()
            .first()
        )
        if reference is None:
            return None
        if not await self._membership(reference["tenant_id"], reference["person_id"]):
            # Lazy materialization in this card's service; admission is denied
            # immediately, regardless of unexpired credentials.
            await self._revoke_binding(reference)
            return None
        removed_at = await self._last_removal(reference["tenant_id"], reference["person_id"])
        if removed_at is not None and utc(reference["created_at"]) <= removed_at:
            await self._revoke_binding(reference, removed_at=removed_at)
            return None
        row = (
            (
                await self.db.execute(
                    select(devices).where(devices.c.id == device_id).with_for_update()
                )
            )
            .mappings()
            .one()
        )
        return row if row["revoked_at"] is None else None

    async def _last_removal(self, tenant_id: UUID, person_id: UUID) -> datetime | None:
        # OrganisationService.remove_member commits this security fact with
        # canonical membership removal. Rejoining cannot revive older devices,
        # even if they made no requests during the inactive interval.
        timestamp = await self.db.scalar(
            select(AuditEvent.occurred_at)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == "organisation.member_removed",
                AuditEvent.resource_type == "organisation_membership",
                AuditEvent.resource_id == str(person_id),
            )
            .order_by(AuditEvent.sequence_no.desc())
            .limit(1)
        )
        return utc(timestamp) if timestamp else None

    async def _revoke_binding(
        self,
        reference: Mapping[Any, Any],
        *,
        removed_at: datetime | None = None,
    ) -> None:
        predicate: ColumnElement[bool] = devices.c.revoked_at.is_(None)
        if removed_at is not None:
            predicate = predicate & (devices.c.created_at <= removed_at)
        ids = (
            (
                await self.db.execute(
                    update(devices)
                    .where(
                        devices.c.tenant_id == reference["tenant_id"],
                        devices.c.person_id == reference["person_id"],
                        predicate,
                    )
                    .values(revoked_at=removed_at or self.clock())
                    .returning(devices.c.id)
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            return
        await self.db.execute(
            update(families)
            .where(
                families.c.device_id.in_(ids),
                families.c.revoked_at.is_(None),
            )
            .values(revoked_at=self.clock())
        )
        await AuditRepository(self.db).append(
            tenant_id=reference["tenant_id"],
            actor_person_id=reference["person_id"],
            actor_type="system",
            action="native.membership.revoke",
            resource_type="membership",
            resource_id=reference["person_id"],
            payload={"device_ids": [str(i) for i in ids]},
            now=self.clock(),
        )

    async def _issue(self, family: Mapping[Any, Any], device: Mapping[Any, Any]) -> NativeOutcome:
        now = self.clock()
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        idle = min(now + timedelta(days=30), utc(family["absolute_expires_at"]))
        access_expiry = min(now + timedelta(minutes=15), idle)
        await self.db.execute(
            insert(credentials),
            [
                dict(
                    id=uuid4(),
                    family_id=family["id"],
                    kind=kind,
                    token_sha256=digest(token),
                    created_at=now,
                    expires_at=expiry,
                )
                for kind, token, expiry in [
                    ("access", access, access_expiry),
                    ("refresh", refresh, idle),
                ]
            ],
        )
        await self.db.execute(
            update(families)
            .where(families.c.id == family["id"])
            .values(
                idle_expires_at=idle,
            )
        )
        return NativeOutcome(
            {
                "device_id": str(device["id"]),
                "workspace_id": str(device["tenant_id"]),
                "token_type": "Bearer",
                "access_token": access,
                "refresh_token": refresh,
                "access_expires_at": access_expiry.isoformat(),
                "refresh_expires_at": idle.isoformat(),
            }
        )

    async def poll(self, pairing_id: UUID, poll_secret: str) -> NativeOutcome:
        row = (
            (
                await self.db.execute(
                    select(pairings)
                    .where(
                        pairings.c.id == pairing_id,
                        pairings.c.poll_secret_sha256 == digest(poll_secret),
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        now = self.clock()
        if row is None:
            return failure("pairing_not_found", 404)
        if utc(row["expires_at"]) <= now:
            return failure("pairing_expired", 410)
        if row["state"] in {"pending", "denied"}:
            return NativeOutcome({"state": row["state"]})
        if row["state"] == "collected":
            return failure("pairing_already_collected", 409)
        device = await self._device(row["device_id"])
        if device is None:
            return failure("device_authorization_denied", 401)
        now = self.clock()
        if utc(row["expires_at"]) <= now:
            return failure("pairing_expired", 410)
        family = dict(
            id=uuid4(),
            device_id=device["id"],
            created_at=now,
            idle_expires_at=now + timedelta(days=30),
            absolute_expires_at=now + timedelta(days=90),
        )
        await self.db.execute(insert(families).values(**family))
        await self.db.execute(
            update(pairings)
            .where(pairings.c.id == pairing_id)
            .values(
                state="collected",
                collected_at=now,
            )
        )
        return await self._issue(family, device)

    async def _credential(
        self,
        token: str,
        kind: str,
    ) -> tuple[Mapping[Any, Any], Mapping[Any, Any], Mapping[Any, Any]] | None:
        reference = (
            (
                await self.db.execute(
                    select(
                        credentials.c.id,
                        credentials.c.family_id,
                        families.c.device_id,
                    )
                    .join(families, families.c.id == credentials.c.family_id)
                    .where(
                        credentials.c.token_sha256 == digest(token),
                        credentials.c.kind == kind,
                    )
                )
            )
            .mappings()
            .first()
        )
        if reference is None:
            return None
        if self.device_limit:
            await self.device_limit(reference["device_id"])
        device = await self._device(reference["device_id"])
        if device is None:
            return None
        family = (
            (
                await self.db.execute(
                    select(families)
                    .where(
                        families.c.id == reference["family_id"],
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        credential = (
            (
                await self.db.execute(
                    select(credentials)
                    .where(
                        credentials.c.id == reference["id"],
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        now = self.clock()
        if (
            family["revoked_at"] is not None
            or utc(family["idle_expires_at"]) <= now
            or utc(family["absolute_expires_at"]) <= now
        ):
            return None
        return credential, family, device

    async def refresh(self, token: str) -> NativeOutcome:
        bound = await self._credential(token, "refresh")
        if bound is None:
            return failure("invalid_device_credential", 401)
        credential, family, device = bound
        now = self.clock()
        # Check spent evidence before token expiry: earlier rotations retain
        # evidence until the family expires, even if that token has expired.
        if credential["consumed_at"] is not None:
            await self.db.execute(
                update(families)
                .where(families.c.id == family["id"])
                .values(
                    revoked_at=now,
                )
            )
            await self._audit(device, "native.refresh.reuse_revoke", resource_id=family["id"])
            return failure("refresh_reuse", 401)
        if utc(credential["expires_at"]) <= now:
            return failure("invalid_device_credential", 401)
        await self.db.execute(
            update(credentials)
            .where(credentials.c.id == credential["id"])
            .values(
                consumed_at=now,
            )
        )
        return await self._issue(family, device)

    async def authenticate(self, token: str) -> Mapping[Any, Any] | None:
        bound = await self._credential(token, "access")
        if bound is None:
            return None
        credential, _family, device = bound
        return device if utc(credential["expires_at"]) > self.clock() else None

    async def list_devices(self, actor: ActorContext, after: UUID | None = None) -> NativeOutcome:
        if actor.tenant_id is None or not await self._membership(actor.tenant_id, actor.person_id):
            return failure("workspace_membership_required", 403)
        removed_at = await self._last_removal(actor.tenant_id, actor.person_id)
        stmt = (
            select(devices)
            .where(
                devices.c.tenant_id == actor.tenant_id,
                devices.c.person_id == actor.person_id,
            )
            .order_by(devices.c.id)
            .limit(101)
        )
        if after:
            stmt = stmt.where(devices.c.id > after)
        rows = (await self.db.execute(stmt)).mappings().all()
        return NativeOutcome(
            {
                "devices": [
                    {
                        "id": str(row["id"]),
                        "name": row["name"],
                        "platform": row["platform"],
                        "created_at": utc(row["created_at"]).isoformat(),
                        "revoked_at": utc(row["revoked_at"]).isoformat()
                        if row["revoked_at"]
                        else (
                            removed_at.isoformat()
                            if removed_at is not None and utc(row["created_at"]) <= removed_at
                            else None
                        ),
                    }
                    for row in rows[:100]
                ],
                "next_cursor": str(rows[99]["id"]) if len(rows) > 100 else None,
            }
        )

    async def revoke(self, device_id: UUID, actor: ActorContext) -> NativeOutcome:
        if actor.tenant_id is None or not await self._membership(actor.tenant_id, actor.person_id):
            return failure("workspace_membership_required", 403)
        device = (
            (
                await self.db.execute(
                    select(devices)
                    .where(
                        devices.c.id == device_id,
                        devices.c.tenant_id == actor.tenant_id,
                        devices.c.person_id == actor.person_id,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if device is None:
            return failure("device_not_found", 404)
        return await self.revoke_device(device, actor=actor)

    async def revoke_device(
        self,
        device: Mapping[Any, Any],
        *,
        actor: ActorContext | None = None,
    ) -> NativeOutcome:
        if device["revoked_at"] is None:
            now = self.clock()
            await self.db.execute(
                update(devices)
                .where(devices.c.id == device["id"])
                .values(
                    revoked_at=now,
                )
            )
            await self.db.execute(
                update(families)
                .where(
                    families.c.device_id == device["id"],
                    families.c.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await self._audit(device, "native.device.revoke", resource_id=device["id"], actor=actor)
        return NativeOutcome({"device_id": str(device["id"]), "state": "revoked"})
