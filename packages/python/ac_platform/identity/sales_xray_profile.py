"""Self-service Sales Xray contact profile on the canonical AC Person."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile

_E164 = re.compile(r"\+[1-9][0-9]{1,14}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class SalesXrayProfileError(ValueError):
    """Base error translated at the HTTP boundary."""


class SalesXrayProfileUnavailable(SalesXrayProfileError):
    """The canonical person cannot use authenticated Sales Xray features."""


class SalesXrayProfileIncomplete(SalesXrayProfileError):
    """Required contact fields have not been recorded yet."""


class SalesXrayProfileRevisionConflict(SalesXrayProfileError):
    """The caller's profile revision is stale."""


@dataclass(frozen=True, slots=True)
class SalesXrayProfileSnapshot:
    name: str | None
    email: str
    phone_number_e164: str | None
    phone_verified: bool
    profile_complete: bool
    revision: int


def normalize_profile_name(value: str) -> str:
    if not isinstance(value, str) or _CONTROL.search(value):
        raise ValueError("full_name_invalid")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > 200:
        raise ValueError("full_name_invalid")
    return normalized


def validate_e164(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _E164.fullmatch(value) is None:
        raise ValueError("phone_number_e164_invalid")
    return value


def _resolved_name(person: Person) -> str | None:
    value = person.display_name or person.first_name
    normalized = " ".join(value.split()) if value else ""
    return normalized or None


def _snapshot(person: Person, profile: SalesXrayProfile | None) -> SalesXrayProfileSnapshot:
    name = _resolved_name(person)
    email = person.email
    if email is None or person.email_verified_at is None:
        raise SalesXrayProfileUnavailable("A verified AC account is required.")
    phone = None if profile is None else profile.phone_number_e164
    complete = bool(name and phone and _E164.fullmatch(phone))
    return SalesXrayProfileSnapshot(
        name=name,
        email=email,
        phone_number_e164=phone,
        phone_verified=bool(profile and profile.phone_verified_at is not None),
        profile_complete=complete,
        revision=0 if profile is None else profile.revision,
    )


async def _lock_phone_collision_key(session: AsyncSession, phone_number_e164: str) -> None:
    """Serialize same-number submissions so the later duplicate is review-flagged."""

    get_bind = getattr(session, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return
    lock_key = int.from_bytes(
        hashlib.sha256(
            b"ac-sales-xray-profile-phone-v1:" + phone_number_e164.encode("ascii")
        ).digest()[:8],
        byteorder="big",
        signed=True,
    )
    await session.execute(select(func.pg_advisory_xact_lock(lock_key)))


async def _read_rows(
    session: AsyncSession,
    person_id: UUID,
    *,
    lock: bool = False,
) -> tuple[Person, SalesXrayProfile | None]:
    person_statement = select(Person).where(Person.id == person_id)
    if lock:
        person_statement = person_statement.with_for_update()
    person = await session.scalar(person_statement)
    if person is None or person.status != PersonStatus.ACTIVE.value:
        raise SalesXrayProfileUnavailable("The AC account is unavailable.")
    profile_statement = select(SalesXrayProfile).where(SalesXrayProfile.person_id == person_id)
    if lock:
        profile_statement = profile_statement.with_for_update()
    profile = await session.scalar(profile_statement)
    return person, profile


async def get_sales_xray_profile(
    session: AsyncSession,
    *,
    person_id: UUID,
) -> SalesXrayProfileSnapshot:
    person, profile = await _read_rows(session, person_id)
    return _snapshot(person, profile)


async def require_sales_xray_profile_complete(
    session: AsyncSession,
    *,
    person_id: UUID,
) -> SalesXrayProfileSnapshot:
    snapshot = await get_sales_xray_profile(session, person_id=person_id)
    if not snapshot.profile_complete:
        raise SalesXrayProfileIncomplete("Complete your Sales Xray contact profile to continue.")
    return snapshot


async def erase_sales_xray_profile(
    session: AsyncSession,
    *,
    person_id: UUID,
) -> bool:
    """Erase separately stored phone data when canonical account deletion completes."""

    profile = await session.scalar(
        select(SalesXrayProfile).where(SalesXrayProfile.person_id == person_id).with_for_update()
    )
    if profile is None:
        return False
    await session.delete(profile)
    await session.flush()
    return True


async def update_sales_xray_profile(
    session: AsyncSession,
    *,
    person_id: UUID,
    session_id: UUID | None,
    tenant_id: UUID,
    full_name: str,
    phone_number_e164: str | None,
    expected_revision: int,
) -> SalesXrayProfileSnapshot:
    """Version one self-service update; never accepts a person or email selector."""

    normalized_name = normalize_profile_name(full_name)
    normalized_phone = validate_e164(phone_number_e164)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("expected_revision_invalid")

    person, profile = await _read_rows(session, person_id, lock=True)
    if person.email is None or person.email_verified_at is None:
        raise SalesXrayProfileUnavailable("A verified AC account is required.")
    current_revision = 0 if profile is None else profile.revision
    if expected_revision != current_revision:
        raise SalesXrayProfileRevisionConflict("Reload your profile before saving changes.")

    has_phone_collision = False
    if normalized_phone is not None:
        await _lock_phone_collision_key(session, normalized_phone)
        has_phone_collision = bool(
            await session.scalar(
                select(SalesXrayProfile.person_id)
                .where(
                    SalesXrayProfile.phone_number_e164 == normalized_phone,
                    SalesXrayProfile.person_id != person_id,
                )
                .limit(1)
            )
        )

    next_verified_at = None if profile is None else profile.phone_verified_at
    current_phone = None if profile is None else profile.phone_number_e164
    if current_phone != normalized_phone:
        # A changed number loses any earlier SMS proof. This release has no
        # operation that creates that proof; only the future adapter may do so.
        next_verified_at = None
    collision_flag = has_phone_collision
    changed_fields: list[str] = []
    if person.display_name != normalized_name:
        person.display_name = normalized_name
        person.revision += 1
        changed_fields.append("name")
    if (
        profile is None
        or profile.phone_number_e164 != normalized_phone
        or profile.phone_verified_at != next_verified_at
        or profile.admin_collision_review_required != collision_flag
    ):
        changed_fields.append("phone_number_e164")
    if profile is None:
        profile = SalesXrayProfile(
            person_id=person_id,
            phone_number_e164=normalized_phone,
            phone_verified_at=next_verified_at,
            admin_collision_review_required=collision_flag,
            revision=1,
        )
        session.add(profile)
        next_revision = 1
        changed_fields.append("profile_created")
    else:
        next_revision = profile.revision
        if changed_fields:
            profile.phone_number_e164 = normalized_phone
            profile.phone_verified_at = next_verified_at
            profile.admin_collision_review_required = collision_flag
            profile.revision += 1
            next_revision = profile.revision

    if changed_fields:
        await session.flush()
        await AuditRepository(session).append(
            tenant_id=tenant_id,
            actor_person_id=person_id,
            session_id=session_id,
            action="sales_xray.profile.self_updated.v1",
            resource_type="sales_xray_profile",
            resource_id=person_id,
            payload={
                "revision": next_revision,
                "changed_fields": sorted(set(changed_fields)),
                "admin_collision_review_required": collision_flag,
            },
            reason="Self-service Sales Xray contact profile update.",
            now=datetime.now(UTC),
        )
    return _snapshot(person, profile)
