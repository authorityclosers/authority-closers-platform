"""Race-safe username claims and an opt-in canonical practice-XP leaderboard."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.service import AuditRepository
from ac_platform.community.models import (
    AcademyLeaderboardPreference,
    CohorvaPublicProfile,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.practice.models import PracticeRewardClaim
from ac_platform.tenancy.models import Membership

USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
RESERVED_USERNAMES = frozenset(
    {
        "admin",
        "administrator",
        "authority_closers",
        "authorityclosers",
        "coach",
        "dipak",
        "dipak_vishwakarma",
        "dipakvishwakarma",
        "moderator",
        "official",
        "root",
        "staff",
        "support",
        "system",
    }
)
LEADERBOARD_POLICY_VERSION = "all_time_practice_xp_v1"


class CommunityError(DomainError):
    status = 400
    code = "community_error"
    title = "Community request could not be completed"


class UsernameInvalid(CommunityError):
    status = 422
    code = "username_invalid"


class UsernameReserved(CommunityError):
    status = 422
    code = "username_reserved"


class UsernameUnavailable(CommunityError):
    status = 409
    code = "username_unavailable"


class UsernameAlreadyClaimed(CommunityError):
    status = 409
    code = "username_already_claimed"


class CommunityRevisionConflict(CommunityError):
    status = 409
    code = "community_revision_conflict"


class UsernameRequired(CommunityError):
    status = 409
    code = "username_required"


class InvalidLeaderboardCursor(CommunityError):
    status = 422
    code = "leaderboard_cursor_invalid"


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not 3 <= len(username) <= 30 or USERNAME_PATTERN.fullmatch(username) is None:
        raise UsernameInvalid(
            "Use 3–30 lowercase letters, numbers, or single underscores; start with a letter."
        )
    reserved_parts = RESERVED_USERNAMES.intersection(username.split("_"))
    if (
        username in RESERVED_USERNAMES
        or reserved_parts
        or username.startswith(("authorityclosers", "authority_closers", "dipak"))
        or username.startswith("official_")
        or username.endswith("_official")
    ):
        raise UsernameReserved("That username is reserved for account safety.")
    return username


@dataclass(frozen=True, slots=True)
class LeaderboardCursor:
    xp: int
    username: str


def encode_cursor(cursor: LeaderboardCursor) -> str:
    payload = json.dumps(
        {"v": 1, "xp": cursor.xp, "u": cursor.username},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _validate_cursor_username(value: str) -> str:
    """Validate the persisted sort key without applying claim-only policy."""
    if not 3 <= len(value) <= 30 or value != value.lower():
        raise ValueError
    return value


def decode_cursor(value: str) -> LeaderboardCursor:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.b64decode(value + padding, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {"v", "xp", "u"}:
            raise ValueError
        xp = payload["xp"]
        raw_username = payload["u"]
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError
        if type(xp) is not int or not 0 <= xp <= 2**63 - 1 or not isinstance(raw_username, str):
            raise ValueError
        return LeaderboardCursor(xp=xp, username=_validate_cursor_username(raw_username))
    except (
        TypeError,
        ValueError,
        KeyError,
        binascii.Error,
        json.JSONDecodeError,
        UsernameInvalid,
        UsernameReserved,
    ) as error:
        raise InvalidLeaderboardCursor("The leaderboard cursor is not valid.") from error


class CommunityApplication:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    def _require_transaction(self) -> None:
        transaction = self.database.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise CommunityError("Community mutations require a caller-owned transaction.")

    @staticmethod
    def _tenant(actor: ActorContext) -> UUID:
        if actor.tenant_id is None:
            raise CommunityError("Select your academy before opening community identity.")
        return actor.tenant_id

    @staticmethod
    def _profile_payload(
        identity: CohorvaPublicProfile | None,
        preference: AcademyLeaderboardPreference | None,
    ) -> dict[str, Any]:
        return {
            "username": None if identity is None else identity.username,
            "leaderboard_opted_in": (
                False if preference is None else preference.leaderboard_opted_in
            ),
            "revision": 0 if preference is None else preference.revision,
            "leaderboard_policy": {
                "version": LEADERBOARD_POLICY_VERSION,
                "period": "all_time",
                "measure": "confirmed_practice_xp",
                "ranking": "competition",
                "privacy": "academy_opt_in",
            },
        }

    async def _preference(self, actor: ActorContext) -> AcademyLeaderboardPreference | None:
        if actor.tenant_id is None:
            return None
        return cast(
            AcademyLeaderboardPreference | None,
            await self.database.scalar(
                select(AcademyLeaderboardPreference).where(
                    AcademyLeaderboardPreference.tenant_id == actor.tenant_id,
                    AcademyLeaderboardPreference.person_id == actor.person_id,
                )
            ),
        )

    async def profile(self, actor: ActorContext) -> dict[str, Any]:
        identity = await self.database.scalar(
            select(CohorvaPublicProfile).where(
                CohorvaPublicProfile.person_id == actor.person_id,
            )
        )
        return self._profile_payload(identity, await self._preference(actor))

    async def claim_username(self, actor: ActorContext, value: str) -> dict[str, Any]:
        self._require_transaction()
        username = normalize_username(value)
        identity = await self.database.scalar(
            select(CohorvaPublicProfile)
            .where(
                CohorvaPublicProfile.person_id == actor.person_id,
            )
            .with_for_update()
        )
        if identity is not None:
            if identity.username == username:
                return self._profile_payload(identity, await self._preference(actor))
            raise UsernameAlreadyClaimed(
                "This Cohorva account already has a username. Usernames are fixed in this release."
            )

        try:
            async with self.database.begin_nested():
                identity = CohorvaPublicProfile(
                    person_id=actor.person_id,
                    username=username,
                    claimed_session_id=actor.session_id,
                    claim_source="account_claim",
                    legacy_profile_count=0,
                )
                self.database.add(identity)
                await self.database.flush()
        except IntegrityError as error:
            existing = await self.database.scalar(
                select(CohorvaPublicProfile).where(
                    CohorvaPublicProfile.person_id == actor.person_id,
                )
            )
            if existing is not None and existing.username == username:
                return self._profile_payload(existing, await self._preference(actor))
            raise UsernameUnavailable("That username is unavailable. Choose another.") from error
        if actor.tenant_id is not None:
            await AuditRepository(self.database).append_for_actor(
                actor,
                action="community.username_claimed",
                resource_type="community_public_profile",
                resource_id=actor.person_id,
                payload={"username": username, "scope": "global"},
            )
        return self._profile_payload(identity, await self._preference(actor))

    async def set_leaderboard_opt_in(
        self,
        actor: ActorContext,
        *,
        opted_in: bool,
        expected_revision: int,
    ) -> dict[str, Any]:
        self._require_transaction()
        tenant_id = self._tenant(actor)
        identity = await self.database.scalar(
            select(CohorvaPublicProfile).where(
                CohorvaPublicProfile.person_id == actor.person_id,
            )
        )
        if identity is None:
            raise UsernameRequired("Claim a username before joining the leaderboard.")
        preference = await self.database.scalar(
            select(AcademyLeaderboardPreference).where(
                AcademyLeaderboardPreference.tenant_id == tenant_id,
                AcademyLeaderboardPreference.person_id == actor.person_id,
            )
        )
        if preference is None:
            if not opted_in and expected_revision == 0:
                return self._profile_payload(identity, None)
            if expected_revision != 0:
                raise CommunityRevisionConflict(
                    "Community preferences changed. Refresh and try again."
                )
            try:
                async with self.database.begin_nested():
                    preference = AcademyLeaderboardPreference(
                        tenant_id=tenant_id,
                        person_id=actor.person_id,
                        leaderboard_opted_in=True,
                        revision=1,
                    )
                    self.database.add(preference)
                    await self.database.flush()
            except IntegrityError as error:
                existing = await self.database.scalar(
                    select(AcademyLeaderboardPreference).where(
                        AcademyLeaderboardPreference.tenant_id == tenant_id,
                        AcademyLeaderboardPreference.person_id == actor.person_id,
                    )
                )
                if existing is not None and existing.leaderboard_opted_in is opted_in:
                    return self._profile_payload(identity, existing)
                raise CommunityRevisionConflict(
                    "Community preferences changed. Refresh and try again."
                ) from error
        elif preference.revision != expected_revision:
            if preference.leaderboard_opted_in is opted_in:
                return self._profile_payload(identity, preference)
            raise CommunityRevisionConflict("Community preferences changed. Refresh and try again.")
        elif preference.leaderboard_opted_in is opted_in:
            return self._profile_payload(identity, preference)
        else:
            result = cast(
                CursorResult[Any],
                await self.database.execute(
                    update(AcademyLeaderboardPreference)
                    .where(
                        AcademyLeaderboardPreference.tenant_id == tenant_id,
                        AcademyLeaderboardPreference.person_id == actor.person_id,
                        AcademyLeaderboardPreference.revision == expected_revision,
                    )
                    .values(
                        leaderboard_opted_in=opted_in,
                        revision=expected_revision + 1,
                        updated_at=func.now(),
                    )
                ),
            )
            if result.rowcount != 1:
                raise CommunityRevisionConflict(
                    "Community preferences changed. Refresh and try again."
                )
            preference.leaderboard_opted_in = opted_in
            preference.revision = expected_revision + 1
        await AuditRepository(self.database).append_for_actor(
            actor,
            action=(
                "community.leaderboard_joined" if opted_in else "community.leaderboard_withdrawn"
            ),
            resource_type="academy_leaderboard_preference",
            resource_id=actor.person_id,
            payload={
                "policy_version": LEADERBOARD_POLICY_VERSION,
                "profile_revision": preference.revision,
            },
        )
        return self._profile_payload(identity, preference)

    async def leaderboard(
        self,
        actor: ActorContext,
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        # Rank only the immutable, server-confirmed reward journal, never telemetry.
        totals = (
            select(
                CohorvaPublicProfile.person_id.label("person_id"),
                CohorvaPublicProfile.username.label("username"),
                func.sum(PracticeRewardClaim.xp).label("xp_total"),
            )
            .join(
                AcademyLeaderboardPreference,
                AcademyLeaderboardPreference.person_id == CohorvaPublicProfile.person_id,
            )
            .join(
                PracticeRewardClaim,
                and_(
                    PracticeRewardClaim.tenant_id == AcademyLeaderboardPreference.tenant_id,
                    PracticeRewardClaim.person_id == AcademyLeaderboardPreference.person_id,
                ),
            )
            .join(
                Membership,
                and_(
                    Membership.tenant_id == AcademyLeaderboardPreference.tenant_id,
                    Membership.person_id == AcademyLeaderboardPreference.person_id,
                ),
            )
            .join(Person, Person.id == CohorvaPublicProfile.person_id)
            .where(
                AcademyLeaderboardPreference.tenant_id == tenant_id,
                AcademyLeaderboardPreference.leaderboard_opted_in.is_(True),
                PracticeRewardClaim.xp > 0,
                Membership.role == "learner",
                Membership.status == "active",
                Person.status == "active",
                Person.email_verified_at.is_not(None),
            )
            .group_by(
                CohorvaPublicProfile.person_id,
                CohorvaPublicProfile.username,
            )
            .subquery()
        )
        ranked = select(
            totals.c.person_id,
            totals.c.username,
            totals.c.xp_total,
            func.rank().over(order_by=desc(totals.c.xp_total)).label("rank"),
        ).subquery()
        statement = select(ranked)
        if cursor is not None:
            decoded = decode_cursor(cursor)
            statement = statement.where(
                or_(
                    ranked.c.xp_total < decoded.xp,
                    and_(
                        ranked.c.xp_total == decoded.xp,
                        ranked.c.username > decoded.username,
                    ),
                )
            )
        rows = tuple(
            (
                await self.database.execute(
                    statement.order_by(
                        desc(ranked.c.xp_total),
                        ranked.c.username,
                        ranked.c.person_id,
                    ).limit(limit + 1)
                )
            ).mappings()
        )
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1]
            next_cursor = encode_cursor(
                LeaderboardCursor(
                    xp=int(last["xp_total"]),
                    username=str(last["username"]),
                )
            )
        return {
            "policy": {
                "version": LEADERBOARD_POLICY_VERSION,
                "label": "All-time practice XP",
                "period": "all_time",
                "ranking": "competition",
                "scope": "academy",
            },
            "items": [
                {
                    "rank": int(row["rank"]),
                    "username": str(row["username"]),
                    "xp_total": int(row["xp_total"]),
                    "is_current_learner": row["person_id"] == actor.person_id,
                }
                for row in page
            ],
            "next_cursor": next_cursor,
        }


__all__ = [
    "CommunityApplication",
    "CommunityError",
    "CommunityRevisionConflict",
    "InvalidLeaderboardCursor",
    "LEADERBOARD_POLICY_VERSION",
    "LeaderboardCursor",
    "RESERVED_USERNAMES",
    "UsernameAlreadyClaimed",
    "UsernameInvalid",
    "UsernameRequired",
    "UsernameReserved",
    "UsernameUnavailable",
    "decode_cursor",
    "encode_cursor",
    "normalize_username",
]
