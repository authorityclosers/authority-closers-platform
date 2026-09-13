"""Race-safe username claims and an opt-in canonical practice-XP leaderboard."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, desc, exists, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.service import AuditRepository
from ac_platform.community.models import (
    AcademyLeaderboardPreference,
    CohorvaPublicProfile,
    CommunityBlock,
    CommunityConnection,
    CommunityConnectionEvent,
    CommunityDiscoveryPreference,
    CommunityReport,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.media.models import MediaAsset
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


class DiscoveryRevisionConflict(CommunityError):
    status = 409
    code = "community_discovery_revision_conflict"


class DiscoveryUsernameRequired(CommunityError):
    status = 409
    code = "community_discovery_username_required"


class CommunityTargetUnavailable(CommunityError):
    status = 404
    code = "community_target_unavailable"


class ConnectionActionInvalid(CommunityError):
    status = 409
    code = "community_connection_action_invalid"


class ReportReasonInvalid(CommunityError):
    status = 422
    code = "community_report_reason_invalid"


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

    @staticmethod
    def _lookup(value: str) -> str:
        candidate = value.strip().lower()
        if not 3 <= len(candidate) <= 30 or USERNAME_PATTERN.fullmatch(candidate) is None:
            raise UsernameInvalid("Enter a username using letters, numbers, or underscores.")
        return candidate

    @staticmethod
    def _public_payload(row: Any, *, connection_state: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "username": str(row["username"]),
            "display_name": row["public_display_name"],
            "avatar_asset_id": row["avatar_asset_id"],
            "practice_xp_total": (
                int(row["practice_xp_total"]) if row["practice_xp_total"] is not None else None
            ),
        }
        if connection_state is not None:
            result["connection_state"] = connection_state
        return result

    async def _discovery_preference(
        self, actor: ActorContext
    ) -> CommunityDiscoveryPreference | None:
        tenant_id = self._tenant(actor)
        return cast(
            CommunityDiscoveryPreference | None,
            await self.database.scalar(
                select(CommunityDiscoveryPreference).where(
                    CommunityDiscoveryPreference.tenant_id == tenant_id,
                    CommunityDiscoveryPreference.person_id == actor.person_id,
                )
            ),
        )

    async def discovery_profile(self, actor: ActorContext) -> dict[str, Any]:
        identity = await self.database.scalar(
            select(CohorvaPublicProfile).where(
                CohorvaPublicProfile.person_id == actor.person_id,
            )
        )
        preference = await self._discovery_preference(actor)
        return {
            "username": None if identity is None else identity.username,
            "discoverable": False if preference is None else preference.discoverable,
            "public_display_name": None if preference is None else preference.public_display_name,
            "avatar_asset_id": None if preference is None else preference.avatar_asset_id,
            "revision": 0 if preference is None else preference.revision,
        }

    async def set_discovery(
        self,
        actor: ActorContext,
        *,
        discoverable: bool,
        public_display_name: str | None,
        avatar_asset_id: UUID | None,
        expected_revision: int,
    ) -> dict[str, Any]:
        self._require_transaction()
        tenant_id = self._tenant(actor)
        identity = await self.database.scalar(
            select(CohorvaPublicProfile).where(
                CohorvaPublicProfile.person_id == actor.person_id,
            )
        )
        if discoverable and identity is None:
            raise DiscoveryUsernameRequired("Claim a username before enabling discovery.")
        name = public_display_name.strip() if public_display_name is not None else None
        if name == "":
            name = None
        if name is not None and len(name) > 120:
            raise CommunityError("Your public display name is too long.")
        if avatar_asset_id is not None:
            valid_avatar = await self.database.scalar(
                select(MediaAsset).where(
                    MediaAsset.tenant_id == tenant_id,
                    MediaAsset.id == avatar_asset_id,
                    MediaAsset.owner_person_id == actor.person_id,
                    MediaAsset.purpose == "avatar",
                    MediaAsset.state.in_(("ready", "processing", "uploading")),
                )
            )
            if valid_avatar is None:
                raise CommunityError("Choose an avatar owned by this academy profile.")
        preference = await self._discovery_preference(actor)
        if preference is None:
            if expected_revision != 0:
                raise DiscoveryRevisionConflict(
                    "Community discovery changed. Refresh and try again."
                )
            preference = CommunityDiscoveryPreference(
                tenant_id=tenant_id,
                person_id=actor.person_id,
                discoverable=discoverable,
                public_display_name=name,
                avatar_asset_id=avatar_asset_id,
                revision=1,
            )
            self.database.add(preference)
            await self.database.flush()
        elif preference.revision != expected_revision:
            raise DiscoveryRevisionConflict("Community discovery changed. Refresh and try again.")
        else:
            preference.discoverable = discoverable
            preference.public_display_name = name
            preference.avatar_asset_id = avatar_asset_id
            preference.revision += 1
            await self.database.flush()
        await AuditRepository(self.database).append_for_actor(
            actor,
            action=(
                "community.discovery_enabled"
                if discoverable
                else "community.discovery_disabled"
            ),
            resource_type="community_discovery_preference",
            resource_id=actor.person_id,
            payload={"revision": preference.revision},
        )
        return await self.discovery_profile(actor)

    async def _public_candidate(
        self, actor: ActorContext, username: str
    ) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        target = self._lookup(username)
        blocked = exists(
            select(CommunityBlock.id).where(
                CommunityBlock.tenant_id == tenant_id,
                or_(
                    and_(
                        CommunityBlock.blocker_person_id == actor.person_id,
                        CommunityBlock.blocked_person_id == CohorvaPublicProfile.person_id,
                    ),
                    and_(
                        CommunityBlock.blocker_person_id == CohorvaPublicProfile.person_id,
                        CommunityBlock.blocked_person_id == actor.person_id,
                    ),
                ),
            )
        )
        row = (
            await self.database.execute(
                select(
                    CohorvaPublicProfile.person_id.label("person_id"),
                    CohorvaPublicProfile.username.label("username"),
                    CommunityDiscoveryPreference.public_display_name,
                    CommunityDiscoveryPreference.avatar_asset_id,
                    AcademyLeaderboardPreference.leaderboard_opted_in,
                )
                .join(
                    CommunityDiscoveryPreference,
                    and_(
                        CommunityDiscoveryPreference.person_id == CohorvaPublicProfile.person_id,
                        CommunityDiscoveryPreference.tenant_id == tenant_id,
                    ),
                )
                .join(Person, Person.id == CohorvaPublicProfile.person_id)
                .join(
                    Membership,
                    and_(
                        Membership.person_id == CohorvaPublicProfile.person_id,
                        Membership.tenant_id == tenant_id,
                    ),
                )
                .outerjoin(
                    AcademyLeaderboardPreference,
                    and_(
                        AcademyLeaderboardPreference.person_id == CohorvaPublicProfile.person_id,
                        AcademyLeaderboardPreference.tenant_id == tenant_id,
                    ),
                )
                .where(
                    CohorvaPublicProfile.username == target,
                    CohorvaPublicProfile.person_id != actor.person_id,
                    CommunityDiscoveryPreference.discoverable.is_(True),
                    Membership.role == "learner",
                    Membership.status == "active",
                    Person.status == "active",
                    Person.email_verified_at.is_not(None),
                    ~blocked,
                )
            )
        ).mappings().first()
        if row is None:
            raise CommunityTargetUnavailable("That learner is unavailable.")
        metric = None
        if row["leaderboard_opted_in"]:
            metric = await self.database.scalar(
                select(func.sum(PracticeRewardClaim.xp)).where(
                    PracticeRewardClaim.tenant_id == tenant_id,
                    PracticeRewardClaim.person_id == row["person_id"],
                    PracticeRewardClaim.xp > 0,
                )
            )
        result = self._public_payload(
            {**dict(row), "practice_xp_total": metric},
        ) | {"person_id": row["person_id"]}
        connection = await self._connection(actor, row["person_id"])
        if connection is not None:
            result["connection_state"] = connection.state
            result["connection_incoming"] = connection.requested_by_person_id != actor.person_id
        return result

    async def search_public_profiles(
        self, actor: ActorContext, *, query: str, limit: int
    ) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        search = self._lookup(query)
        blocked = exists(
            select(CommunityBlock.id).where(
                CommunityBlock.tenant_id == tenant_id,
                or_(
                    and_(
                        CommunityBlock.blocker_person_id == actor.person_id,
                        CommunityBlock.blocked_person_id == CohorvaPublicProfile.person_id,
                    ),
                    and_(
                        CommunityBlock.blocker_person_id == CohorvaPublicProfile.person_id,
                        CommunityBlock.blocked_person_id == actor.person_id,
                    ),
                ),
            )
        )
        rows = tuple(
            (
                await self.database.execute(
                    select(
                        CohorvaPublicProfile.person_id.label("person_id"),
                        CohorvaPublicProfile.username.label("username"),
                        CommunityDiscoveryPreference.public_display_name,
                        CommunityDiscoveryPreference.avatar_asset_id,
                        AcademyLeaderboardPreference.leaderboard_opted_in,
                    )
                    .join(
                        CommunityDiscoveryPreference,
                        and_(
                            CommunityDiscoveryPreference.person_id
                            == CohorvaPublicProfile.person_id,
                            CommunityDiscoveryPreference.tenant_id == tenant_id,
                        ),
                    )
                    .join(Person, Person.id == CohorvaPublicProfile.person_id)
                    .join(
                        Membership,
                        and_(
                            Membership.person_id == CohorvaPublicProfile.person_id,
                            Membership.tenant_id == tenant_id,
                        ),
                    )
                    .outerjoin(
                        AcademyLeaderboardPreference,
                        and_(
                            AcademyLeaderboardPreference.person_id
                            == CohorvaPublicProfile.person_id,
                            AcademyLeaderboardPreference.tenant_id == tenant_id,
                        ),
                    )
                    .where(
                        CohorvaPublicProfile.username.startswith(search),
                        CommunityDiscoveryPreference.discoverable.is_(True),
                        Membership.role == "learner",
                        Membership.status == "active",
                        Person.status == "active",
                        Person.email_verified_at.is_not(None),
                        ~blocked,
                    )
                    .order_by(CohorvaPublicProfile.username)
                    .limit(limit)
                )
            ).mappings()
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            metric = None
            if row["leaderboard_opted_in"]:
                metric = await self.database.scalar(
                    select(func.sum(PracticeRewardClaim.xp)).where(
                        PracticeRewardClaim.tenant_id == tenant_id,
                        PracticeRewardClaim.person_id == row["person_id"],
                        PracticeRewardClaim.xp > 0,
                    )
                )
            result = self._public_payload({**dict(row), "practice_xp_total": metric})
            connection = await self._connection(actor, row["person_id"])
            if connection is not None:
                result["connection_state"] = connection.state
                result["connection_incoming"] = connection.requested_by_person_id != actor.person_id
            items.append(result)
        return {"items": items}

    async def _connection(self, actor: ActorContext, target_id: UUID) -> CommunityConnection | None:
        tenant_id = self._tenant(actor)
        first, second = sorted((actor.person_id, target_id), key=lambda value: value.int)
        return cast(
            CommunityConnection | None,
            await self.database.scalar(
                select(CommunityConnection).where(
                    CommunityConnection.tenant_id == tenant_id,
                    CommunityConnection.person_a_id == first,
                    CommunityConnection.person_b_id == second,
                )
            ),
        )

    async def _record_connection_action(
        self, actor: ActorContext, connection: CommunityConnection, action: str
    ) -> None:
        self.database.add(
            CommunityConnectionEvent(
                connection_id=connection.id,
                tenant_id=connection.tenant_id,
                actor_person_id=actor.person_id,
                action=action,
                revision=connection.revision,
            )
        )
        await self.database.flush()

    async def request_connection(self, actor: ActorContext, username: str) -> dict[str, Any]:
        self._require_transaction()
        target = await self._public_candidate(actor, username)
        target_id = target.pop("person_id")
        connection = await self._connection(actor, target_id)
        if connection is None:
            first, second = sorted((actor.person_id, target_id), key=lambda value: value.int)
            connection = CommunityConnection(
                tenant_id=self._tenant(actor),
                person_a_id=first,
                person_b_id=second,
                requested_by_person_id=actor.person_id,
                state="pending",
                revision=1,
            )
            self.database.add(connection)
            await self.database.flush()
            await self._record_connection_action(actor, connection, "requested")
        elif connection.state in ("declined", "removed"):
            connection.requested_by_person_id = actor.person_id
            connection.state = "pending"
            connection.revision += 1
            await self._record_connection_action(actor, connection, "requested")
        elif connection.state == "pending" and connection.requested_by_person_id != actor.person_id:
            raise ConnectionActionInvalid("Respond to the incoming connection request first.")
        return {"username": target["username"], "state": connection.state, "incoming": False}

    async def respond_connection(
        self, actor: ActorContext, username: str, *, accept: bool
    ) -> dict[str, Any]:
        self._require_transaction()
        target = await self._public_candidate(actor, username)
        target_id = target.pop("person_id")
        connection = await self._connection(actor, target_id)
        if (
            connection is None
            or connection.state != "pending"
            or connection.requested_by_person_id == actor.person_id
        ):
            raise ConnectionActionInvalid("There is no incoming connection to respond to.")
        connection.state = "accepted" if accept else "declined"
        connection.revision += 1
        await self._record_connection_action(actor, connection, connection.state)
        return {"username": target["username"], "state": connection.state, "incoming": True}

    async def remove_connection(self, actor: ActorContext, username: str) -> dict[str, Any]:
        self._require_transaction()
        target = await self._public_candidate(actor, username)
        target_id = target.pop("person_id")
        connection = await self._connection(actor, target_id)
        if connection is None or connection.state == "removed":
            return {"username": target["username"], "state": "removed", "incoming": False}
        connection.state = "removed"
        connection.revision += 1
        await self._record_connection_action(actor, connection, "removed")
        return {"username": target["username"], "state": "removed", "incoming": False}

    async def connections(self, actor: ActorContext, *, limit: int = 50) -> dict[str, Any]:
        """List only the actor's own pending/accepted connections."""

        tenant_id = self._tenant(actor)
        blocked = exists(
            select(CommunityBlock.id).where(
                CommunityBlock.tenant_id == tenant_id,
                or_(
                    and_(
                        CommunityBlock.blocker_person_id == actor.person_id,
                        CommunityBlock.blocked_person_id.in_(
                            (
                                CommunityConnection.person_a_id,
                                CommunityConnection.person_b_id,
                            )
                        ),
                    ),
                    and_(
                        CommunityBlock.blocked_person_id == actor.person_id,
                        CommunityBlock.blocker_person_id.in_(
                            (
                                CommunityConnection.person_a_id,
                                CommunityConnection.person_b_id,
                            )
                        ),
                    ),
                ),
            )
        )
        rows = (
            await self.database.execute(
                select(CommunityConnection)
                .where(
                    CommunityConnection.tenant_id == tenant_id,
                    or_(
                        CommunityConnection.person_a_id == actor.person_id,
                        CommunityConnection.person_b_id == actor.person_id,
                    ),
                    CommunityConnection.state.in_(("pending", "accepted")),
                    ~blocked,
                )
                .order_by(CommunityConnection.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        items: list[dict[str, Any]] = []
        for connection in rows:
            target_id = (
                connection.person_b_id
                if connection.person_a_id == actor.person_id
                else connection.person_a_id
            )
            identity = await self.database.scalar(
                select(CohorvaPublicProfile).where(CohorvaPublicProfile.person_id == target_id)
            )
            if identity is None:
                continue
            items.append(
                {
                    "username": identity.username,
                    "state": connection.state,
                    "incoming": connection.requested_by_person_id != actor.person_id,
                }
            )
        return {"items": items}

    async def block(self, actor: ActorContext, username: str) -> dict[str, Any]:
        self._require_transaction()
        target = await self._public_candidate(actor, username)
        target_id = target.pop("person_id")
        existing = await self.database.scalar(
            select(CommunityBlock).where(
                CommunityBlock.tenant_id == self._tenant(actor),
                CommunityBlock.blocker_person_id == actor.person_id,
                CommunityBlock.blocked_person_id == target_id,
            )
        )
        if existing is None:
            self.database.add(
                CommunityBlock(
                    tenant_id=self._tenant(actor),
                    blocker_person_id=actor.person_id,
                    blocked_person_id=target_id,
                )
            )
            await self.database.flush()
        connection = await self._connection(actor, target_id)
        if connection is not None and connection.state != "removed":
            connection.state = "removed"
            connection.revision += 1
            await self._record_connection_action(actor, connection, "blocked")
        return {"username": target["username"], "blocked": True}

    async def report(self, actor: ActorContext, username: str, *, reason: str) -> dict[str, Any]:
        self._require_transaction()
        if reason not in {"spam", "harassment", "impersonation", "other"}:
            raise ReportReasonInvalid("Choose a supported report reason.")
        target = await self._public_candidate(actor, username)
        target_id = target.pop("person_id")
        self.database.add(
            CommunityReport(
                tenant_id=self._tenant(actor),
                reporter_person_id=actor.person_id,
                reported_person_id=target_id,
                reason=reason,
            )
        )
        await self.database.flush()
        return {"username": target["username"], "reported": True}

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
    "CommunityTargetUnavailable",
    "CommunityError",
    "ConnectionActionInvalid",
    "CommunityRevisionConflict",
    "DiscoveryRevisionConflict",
    "DiscoveryUsernameRequired",
    "InvalidLeaderboardCursor",
    "LEADERBOARD_POLICY_VERSION",
    "LeaderboardCursor",
    "RESERVED_USERNAMES",
    "UsernameAlreadyClaimed",
    "UsernameInvalid",
    "UsernameRequired",
    "UsernameReserved",
    "UsernameUnavailable",
    "ReportReasonInvalid",
    "decode_cursor",
    "encode_cursor",
    "normalize_username",
]
