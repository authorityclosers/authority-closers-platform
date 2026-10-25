"""Self-service Sales Xray contact profile on the canonical AC Person."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.identity.google_profile import (
    GoogleProfileClaims,
    erase_google_profile,
    read_google_profile,
)
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.sales_xray_profile_models import (
    PersonPhoto,
    PersonProfileDetails,
    SalesXrayProfile,
)

_E164 = re.compile(r"\+[1-9][0-9]{1,14}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# The user id (migration 0135): lower-case letters, digits, dot, dash or underscore,
# 3 to 30, starting with a letter or digit; changeable once in 30 days.
_HANDLE = re.compile(r"[a-z0-9][a-z0-9._-]{2,29}\Z")
RESERVED_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "api",
        "authorityclosers",
        "everyone",
        "help",
        "me",
        "owner",
        "root",
        "sales-xray",
        "salesxray",
        "support",
        "system",
    }
)
HANDLE_CHANGE_EVERY = timedelta(days=30)
# What a complete profile has (the "Your profile: 3 of 6" card).
COMPLETION_ITEMS = ("photo", "name", "handle", "title", "team", "phone")


class SalesXrayProfileError(ValueError):
    """Base error translated at the HTTP boundary."""


class SalesXrayProfileUnavailable(SalesXrayProfileError):
    """The canonical person cannot use authenticated Sales Xray features."""


class SalesXrayProfileIncomplete(SalesXrayProfileError):
    """Required contact fields have not been recorded yet."""


class SalesXrayProfileRevisionConflict(SalesXrayProfileError):
    """The caller's profile revision is stale."""


class SalesXrayProfileHandleTaken(SalesXrayProfileError):
    """Another member has that user id, or it is too soon to change it again."""


@dataclass(frozen=True, slots=True)
class SalesXrayProfileSnapshot:
    name: str | None
    email: str
    phone_number_e164: str | None
    phone_verified: bool
    profile_complete: bool
    revision: int
    given_name: str | None = None
    family_name: str | None = None
    locale: str | None = None
    hosted_domain: str | None = None
    photo_url: str | None = None
    # The member's profile (migration 0135, its own revision) and their photo's
    # versioned URL.
    handle: str | None = None
    title: str | None = None
    team: str | None = None
    details_revision: int = 0
    avatar_url: str | None = None
    own_photo: bool = False
    missing: tuple[str, ...] = field(default=COMPLETION_ITEMS)

    @property
    def completion(self) -> dict[str, object]:
        return {
            "done": len(COMPLETION_ITEMS) - len(self.missing),
            "total": len(COMPLETION_ITEMS),
            "missing": list(self.missing),
        }


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


def normalize_handle(value: str) -> str:
    handle = value.strip().lstrip("@").lower() if isinstance(value, str) else ""
    if _HANDLE.fullmatch(handle) is None:
        raise ValueError("handle_invalid")
    if handle in RESERVED_HANDLES:
        raise ValueError("handle_reserved")
    return handle


def _detail(value: str | None) -> str | None:
    """A title or team: one line, up to 80 characters; empty clears it."""
    if value is None:
        return None
    if not isinstance(value, str) or _CONTROL.search(value):
        raise ValueError("detail_invalid")
    normalized = " ".join(value.split())
    if len(normalized) > 80:
        raise ValueError("detail_invalid")
    return normalized or None


def _resolved_name(person: Person) -> str | None:
    value = person.display_name or person.first_name
    normalized = " ".join(value.split()) if value else ""
    return normalized or None


def _snapshot(
    person: Person,
    profile: SalesXrayProfile | None,
    google_profile: GoogleProfileClaims,
    avatar_url: str | None = None,
    own_photo: bool = False,
    details: PersonProfileDetails | None = None,
) -> SalesXrayProfileSnapshot:
    name = _resolved_name(person)
    email = person.email
    if email is None or person.email_verified_at is None:
        raise SalesXrayProfileUnavailable("A verified AC account is required.")
    phone = None if profile is None else profile.phone_number_e164
    complete = bool(name and phone and _E164.fullmatch(phone))
    handle = None if details is None else details.handle
    title = None if details is None else details.title
    team = None if details is None else details.team
    have = {
        "photo": avatar_url is not None,
        "name": bool(name),
        "handle": bool(handle),
        "title": bool(title),
        "team": bool(team),
        "phone": bool(phone),
    }
    return SalesXrayProfileSnapshot(
        name=name,
        email=email,
        phone_number_e164=phone,
        phone_verified=bool(profile and profile.phone_verified_at is not None),
        profile_complete=complete,
        revision=0 if profile is None else profile.revision,
        given_name=google_profile.given_name,
        family_name=google_profile.family_name,
        locale=google_profile.locale,
        hosted_domain=google_profile.hosted_domain,
        # Own photo or Google's: the route serves whichever wins.
        photo_url=google_profile.photo_url
        or ("/v1/me/sales-xray-profile/photo" if avatar_url else None),
        handle=handle,
        title=title,
        team=team,
        details_revision=0 if details is None else details.revision,
        avatar_url=avatar_url,
        own_photo=own_photo,
        missing=tuple(item for item in COMPLETION_ITEMS if not have[item]),
    )


async def _extras(
    session: AsyncSession, person_id: UUID, *, lock: bool = False
) -> tuple[str | None, bool, PersonProfileDetails | None]:
    """The photo URL, whether it is the person's own upload (which wins), and their
    details row."""
    from ac_platform.identity.person_photos import photo_urls, url_for

    statement = select(PersonProfileDetails).where(PersonProfileDetails.person_id == person_id)
    details = await session.scalar(statement.with_for_update() if lock else statement)
    own = await session.scalar(select(PersonPhoto.sha256).where(PersonPhoto.person_id == person_id))
    if own is not None:
        return url_for(person_id, own), True, details
    return (await photo_urls(session, [person_id]))[person_id], False, details


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
    extras: bool = True,
) -> SalesXrayProfileSnapshot:
    """``extras`` False leaves out the photo and the details (the completeness check
    before every call upload needs only the name and phone)."""
    person, profile = await _read_rows(session, person_id)
    google_profile = await read_google_profile(session, person_id)
    if not extras:
        return _snapshot(person, profile, google_profile)
    return _snapshot(person, profile, google_profile, *await _extras(session, person_id))


async def require_sales_xray_profile_complete(
    session: AsyncSession,
    *,
    person_id: UUID,
) -> SalesXrayProfileSnapshot:
    snapshot = await get_sales_xray_profile(session, person_id=person_id, extras=False)
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
    from ac_platform.conversation_intelligence.submission_labels import (
        erase_submission_labels_for_person,
    )

    removed_labels = await erase_submission_labels_for_person(session, person_id=person_id)
    from ac_platform.conversation_intelligence.speaker_map_store import (
        erase_speaker_maps_for_person,
    )

    removed_speaker_maps = await erase_speaker_maps_for_person(session, person_id=person_id)
    from ac_platform.coaching.sharing_store import erase_coaching_context_for_person

    removed_context = await erase_coaching_context_for_person(session, person_id=person_id)
    removed_google_profile = await erase_google_profile(session, person_id)
    from ac_platform.identity.person_photos import erase_photo

    removed_photo = await erase_photo(session, person_id)
    details = await session.scalar(
        select(PersonProfileDetails)
        .where(PersonProfileDetails.person_id == person_id)
        .with_for_update()
    )
    if details is not None:
        await session.delete(details)
    if profile is None:
        return (
            removed_labels > 0
            or removed_speaker_maps > 0
            or removed_context > 0
            or removed_google_profile
            or removed_photo
            or details is not None
        )
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
    google_profile = await read_google_profile(session, person_id)
    return _snapshot(person, profile, google_profile, *await _extras(session, person_id))


async def update_profile_details(
    session: AsyncSession,
    *,
    person_id: UUID,
    session_id: UUID | None,
    tenant_id: UUID,
    handle: str | None,
    title: str | None,
    team: str | None,
    expected_revision: int,
    now: datetime | None = None,
) -> SalesXrayProfileSnapshot:
    """The member's user id, title and team (migration 0135), compared and set against the
    details' own revision. ``handle`` None keeps it; a user id can be chosen once and
    changed again after 30 days."""

    normalized_handle = None if handle is None else normalize_handle(handle)
    normalized_title, normalized_team = _detail(title), _detail(team)
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("expected_revision_invalid")
    now = now or datetime.now(UTC)
    person, profile = await _read_rows(session, person_id, lock=True)
    if person.email is None or person.email_verified_at is None:
        raise SalesXrayProfileUnavailable("A verified AC account is required.")
    avatar_url, own_photo, details = await _extras(session, person_id, lock=True)
    current_revision = 0 if details is None else details.revision
    if expected_revision != current_revision:
        raise SalesXrayProfileRevisionConflict("Reload your profile before saving changes.")
    current_handle = None if details is None else details.handle
    changed: list[str] = []
    if normalized_handle is not None and normalized_handle != current_handle:
        last = None if details is None else details.handle_changed_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last is not None and now - last < HANDLE_CHANGE_EVERY:
            again = (last + HANDLE_CHANGE_EVERY).strftime("%d %b %Y")
            raise SalesXrayProfileHandleTaken(f"You can change your user id again on {again}.")
        taken = await session.scalar(
            select(PersonProfileDetails.person_id).where(
                PersonProfileDetails.handle == normalized_handle,
                PersonProfileDetails.person_id != person_id,
            )
        )
        if taken is not None:
            raise SalesXrayProfileHandleTaken("That user id is taken. Try another.")
        changed.append("handle")
    if normalized_title != (None if details is None else details.title):
        changed.append("title")
    if normalized_team != (None if details is None else details.team):
        changed.append("team")
    if changed:
        if details is None:
            details = PersonProfileDetails(person_id=person_id, revision=0, updated_at=now)
            session.add(details)
        if "handle" in changed:
            details.handle, details.handle_changed_at = normalized_handle, now
        details.title, details.team = normalized_title, normalized_team
        details.revision, details.updated_at = current_revision + 1, now
        await session.flush()
        await AuditRepository(session).append(
            tenant_id=tenant_id,
            actor_person_id=person_id,
            session_id=session_id,
            action="sales_xray.profile.details_updated.v1",
            resource_type="sales_xray_profile",
            resource_id=person_id,
            payload={"revision": details.revision, "changed_fields": changed},
            reason="Self-service profile details.",
            now=now,
        )
    google_profile = await read_google_profile(session, person_id)
    return _snapshot(person, profile, google_profile, avatar_url, own_photo, details)
