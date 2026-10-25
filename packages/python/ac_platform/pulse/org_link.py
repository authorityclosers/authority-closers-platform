"""An organisation's link to its Pulse org: connect, the member directory, sync and unlink.

Contract, section 2 and 3 (docs/architecture/pulse-identity-contract.md):

- An owner or admin starts the link here; a Pulse org admin approves it on Pulse
  (scopes ``openid pulse.org.read pulse.org.webhooks``, PKCE S256, 10 minutes). The
  token answer names the Pulse org (``pulse_org_id``). The refresh token belongs to the
  link, not to the person who approved it; it and the webhook secret are sealed
  (AES-256-GCM, bound to the link row and organisation), never stored in clear.
- The directory (``GET {api}/orgs/{org}/members``) is read on link, on "Sync now", when
  the page finds it older than six hours, and for one person on each Pulse webhook
  (pull-on-push: a webhook body never writes data by itself).
- Members are matched to this organisation's people by their Pulse sign-in (issuer and
  ``sub``) or by verified email. A match copies the Pulse name, title, team and photo to
  the person's profile; it never changes a role. People in Pulse but not here can be
  invited (as Sellers) by an owner or admin, one button, seats permitting.
- Either side ends the link at once: unlink here deletes the webhook and the link at
  Pulse and revokes the token; ``link.revoked`` from Pulse (confirmed by Pulse refusing
  the token) ends it here. Every link, sync, invite and unlink is an audit event.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from ac_platform.audit.service import AuditRepository
from ac_platform.http.identity_provider import (
    IdentityProviderRejected,
    IdentityProviderUnavailable,
)
from ac_platform.identity.models import Person, ProviderIdentity
from ac_platform.integrations import sealed
from ac_platform.pulse.models import PulseOrgLink, PulseOrgMember
from ac_platform.pulse.oidc import ORG_LINK_SCOPES, PulseClaims, PulseClient
from ac_platform.pulse.profile import picture_source_sha256, record_profile
from ac_platform.tenancy.models import Membership

CALLBACK_PATH = "/v1/integrations/pulse/callback"
WEBHOOK_PATH = "/v1/integrations/pulse/webhook"
# The address registered with Pulse: app traffic reaches /v1/api on every environment
# (dev sits behind an access gate that lets only /v1/api and OAuth through).
WEBHOOK_APP_PATH = "/v1/api/pulse/webhook"
ATTEMPT_MINUTES = 10
STALE_AFTER = timedelta(hours=6)
WEBHOOK_TOLERANCE_SECONDS = 300
EVENTS = (
    "person.updated",
    "person.photo_updated",
    "membership.added",
    "membership.removed",
    "membership.role_changed",
    "link.revoked",
)
# What flows each way (Organisation -> Integrations -> Pulse). The directory is what the
# link is for; photos can be turned off; work signals to Pulse stay off until an owner
# or admin turns them on (and Pulse's signals API is live).
SHARING_DEFAULTS: dict[str, str] = {"directory": "read", "photos": "read", "signals": "off"}
SHARING_CHOICES: dict[str, tuple[str, ...]] = {
    "directory": ("read",),
    "photos": ("read", "off"),
    "signals": ("off", "write"),
}
_MEMBER_PAGES = 50
_PHOTO_FETCHES = 50
_NAMESPACE = UUID("2c9b7f5e-6d0a-4c71-9f3e-1b8a5d2e7c40")


class PulseLinkError(Exception):
    """A refusal with a code the page explains."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def seal_key_from(value: str | None) -> sealed.SealKey | None:
    """``AC_PULSE_SEAL_KEY`` if set, else the platform's ``AC_INTEGRATIONS_SEAL_KEY``."""
    if value:
        return sealed.key_from(value)
    return sealed.load_key()


def sharing_of(raw: Mapping[str, Any] | None) -> dict[str, str]:
    raw = raw if isinstance(raw, Mapping) else {}
    return {
        name: raw[name] if raw.get(name) in SHARING_CHOICES[name] else default
        for name, default in SHARING_DEFAULTS.items()
    }


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seal(key: sealed.SealKey, link: PulseOrgLink, purpose: str, value: str) -> str:
    return sealed.seal(
        key, secret_id=link.id, tenant_id=link.tenant_id, purpose=purpose, value=value.encode()
    )


def _unseal(key: sealed.SealKey, link: PulseOrgLink, purpose: str, value: str | None) -> str:
    if value is None:
        raise PulseLinkError(409, "not_linked", "Connect Pulse first.")
    row = _SealedRow(
        id=link.id,
        tenant_id=link.tenant_id,
        purpose=purpose,
        sealed=value,
        seal_key_id=link.seal_key_id,
    )
    try:
        return sealed.unseal(key, row).decode()
    except Exception as exc:
        raise PulseLinkError(503, "seal", "Pulse's keys can't be opened here.") from exc


@dataclass(frozen=True, slots=True)
class _SealedRow:
    id: UUID
    tenant_id: UUID
    purpose: str
    sealed: str
    seal_key_id: str


@dataclass(frozen=True, slots=True)
class MemberRecord:
    """One member as Pulse's API states it (contract ``Member``)."""

    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    title: str | None
    team: str | None
    picture: str | None
    role: str | None
    status: str
    updated_at: datetime | None

    @classmethod
    def parse(cls, raw: object) -> MemberRecord | None:
        if not isinstance(raw, Mapping):
            return None
        subject = raw.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            return None
        claims = PulseClaims.from_claims("", raw)
        email = raw.get("email")
        updated: datetime | None = None
        if isinstance(raw.get("updated_at"), str):
            try:
                updated = datetime.fromisoformat(str(raw["updated_at"]).replace("Z", "+00:00"))
            except ValueError:
                updated = None
        status = raw.get("status")
        return cls(
            subject=subject,
            email=email.strip() if isinstance(email, str) and 3 <= len(email) <= 320 else None,
            email_verified=raw.get("email_verified") is True,
            name=claims.name,
            title=claims.title,
            team=claims.team,
            picture=claims.picture,
            role=(str(raw.get("role"))[:40] if isinstance(raw.get("role"), str) else None),
            status=str(status)[:16] if isinstance(status, str) and status else "active",
            updated_at=updated,
        )


# ----- connect --------------------------------------------------------------------


async def open_link(database: AsyncSession, tenant_id: UUID) -> PulseOrgLink | None:
    found: PulseOrgLink | None = await database.scalar(
        select(PulseOrgLink).where(
            PulseOrgLink.tenant_id == tenant_id, PulseOrgLink.status.in_(("pending", "active"))
        )
    )
    return found


async def begin(
    database: AsyncSession,
    client: PulseClient,
    key: sealed.SealKey,
    *,
    tenant_id: UUID,
    person_id: UUID,
    redirect_uri: str,
    now: datetime,
) -> str:
    """Start (or restart) a connect attempt; the Pulse address to send the admin to."""
    found = await client.discovery()
    current = await open_link(database, tenant_id)
    if current is not None and current.status == "active":
        raise PulseLinkError(409, "already_linked", "This organisation is already linked to Pulse.")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(24)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    link = current or PulseOrgLink(
        id=uuid4(),
        tenant_id=tenant_id,
        issuer=client.issuer,
        status="pending",
        scopes=ORG_LINK_SCOPES.split(),
        sharing=dict(SHARING_DEFAULTS),
        last_sync={},
    )
    link.issuer = client.issuer
    link.seal_key_id = key.key_id
    link.state_sha256 = _sha(state)
    link.sealed_verifier = _seal(key, link, "pulse_attempt", json.dumps([verifier, nonce]))
    link.expires_at = now + timedelta(minutes=ATTEMPT_MINUTES)
    link.started_by_person_id = person_id
    link.started_at = now
    if current is None:
        database.add(link)
    await database.flush()
    return client.authorize_url(
        found,
        {
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ORG_LINK_SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "consent",
        },
    )


@dataclass(frozen=True, slots=True)
class Attempt:
    link_id: UUID
    tenant_id: UUID
    verifier: str
    nonce: str


async def take_attempt(
    database: AsyncSession,
    key: sealed.SealKey,
    *,
    state: str,
    person_id: UUID,
    now: datetime,
) -> Attempt:
    """The pending attempt this state belongs to, started by this person, still in time."""
    link: PulseOrgLink | None = await database.scalar(
        select(PulseOrgLink)
        .where(PulseOrgLink.state_sha256 == _sha(state), PulseOrgLink.status == "pending")
        .with_for_update()
    )
    if link is None or link.expires_at is None or link.expires_at < now:
        raise PulseLinkError(410, "expired", "That Pulse approval took too long. Start again.")
    if link.started_by_person_id != person_id:
        raise PulseLinkError(403, "not_yours", "Finish the link with the account that started it.")
    verifier, nonce = json.loads(_unseal(key, link, "pulse_attempt", link.sealed_verifier))
    # One use: a replayed callback finds nothing.
    link.state_sha256 = _sha(secrets.token_urlsafe(32))
    await database.flush()
    return Attempt(link.id, link.tenant_id, verifier, nonce)


@dataclass(frozen=True, slots=True)
class Grant:
    pulse_org_id: str
    pulse_org_name: str | None
    refresh_token: str
    access_token: str
    expires_in: int
    scopes: tuple[str, ...]


async def exchange(client: PulseClient, attempt: Attempt, *, code: str, redirect_uri: str) -> Grant:
    """Swap the code for the link's tokens (network; no database transaction open)."""
    if not code or len(code) > 4096 or not code.isascii():
        raise PulseLinkError(400, "code", "Pulse returned an invalid answer.")
    try:
        payload = await client.token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": attempt.verifier,
            }
        )
        if payload.get("id_token"):
            await client.verify_id_token(str(payload["id_token"]), nonce=attempt.nonce)
    except IdentityProviderRejected as exc:
        raise PulseLinkError(400, "refused", "Pulse did not approve the link.") from exc
    except IdentityProviderUnavailable as exc:
        raise PulseLinkError(503, "unavailable", "Pulse is unavailable. Try again.") from exc
    org_id = payload.get("pulse_org_id")
    refresh = payload.get("refresh_token")
    access = payload.get("access_token")
    if not isinstance(org_id, str) or not org_id or len(org_id) > 128:
        raise PulseLinkError(400, "no_org", "Pulse did not say which org approved the link.")
    if not isinstance(refresh, str) or not refresh or not isinstance(access, str) or not access:
        raise PulseLinkError(400, "no_token", "Pulse did not give the link its keys.")
    granted = payload.get("scope")
    scopes = (
        tuple(str(granted).split()) if isinstance(granted, str) else tuple(ORG_LINK_SCOPES.split())
    )
    if "pulse.org.read" not in scopes:
        raise PulseLinkError(400, "scope", "Pulse did not allow reading the org's members.")
    expires = payload.get("expires_in")
    name = payload.get("pulse_org_name")
    return Grant(
        pulse_org_id=org_id,
        pulse_org_name=str(name)[:200] if isinstance(name, str) and name else None,
        refresh_token=refresh,
        access_token=access,
        expires_in=int(expires) if isinstance(expires, int) and 0 < expires <= 86400 else 300,
        scopes=scopes,
    )


async def activate(
    database: AsyncSession,
    key: sealed.SealKey,
    *,
    attempt: Attempt,
    grant: Grant,
    person_id: UUID,
    now: datetime,
) -> PulseOrgLink:
    link: PulseOrgLink | None = await database.get(
        PulseOrgLink, attempt.link_id, with_for_update=True
    )
    if link is None or link.status != "pending":
        raise PulseLinkError(409, "gone", "That link attempt ended. Start again.")
    taken = await database.scalar(
        select(PulseOrgLink.id).where(
            PulseOrgLink.issuer == link.issuer,
            PulseOrgLink.pulse_org_id == grant.pulse_org_id,
            PulseOrgLink.status == "active",
        )
    )
    if taken is not None:
        raise PulseLinkError(
            409, "org_taken", "That Pulse org is already linked to another organisation."
        )
    link.status = "active"
    link.pulse_org_id = grant.pulse_org_id
    link.pulse_org_name = grant.pulse_org_name
    link.scopes = list(grant.scopes)
    link.sealed_refresh_token = _seal(key, link, "pulse_refresh", grant.refresh_token)
    link.sealed_access_token = _seal(key, link, "pulse_access", grant.access_token)
    link.access_expires_at = now + timedelta(seconds=grant.expires_in)
    link.state_sha256 = None
    link.sealed_verifier = None
    link.expires_at = None
    link.linked_by_person_id = person_id
    link.linked_at = now
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=link.tenant_id,
        actor_person_id=person_id,
        action="pulse.org_linked",
        resource_type="pulse_org_link",
        resource_id=link.id,
        payload={"issuer": link.issuer, "pulse_org_id": grant.pulse_org_id, "scopes": link.scopes},
        reason="An owner or admin linked the organisation to its Pulse org.",
        now=now,
    )
    return link


# ----- talking to Pulse as the link -------------------------------------------------


class LinkSession:
    """The link's tokens, refreshed when they run out (network; keep transactions short)."""

    def __init__(self, client: PulseClient, key: sealed.SealKey, link: PulseOrgLink) -> None:
        self.client, self.key, self.link = client, key, link
        self._access: str | None = None
        self._until = 0.0
        if link.sealed_access_token and link.access_expires_at is not None:
            self._access = _unseal(key, link, "pulse_access", link.sealed_access_token)
            self._until = link.access_expires_at.timestamp() - 60
        self.rotated: tuple[str, str, datetime] | None = None
        self.revoked = False

    async def access_token(self) -> str:
        if self._access is not None and time.time() < self._until:
            return self._access
        refresh = (
            self.rotated[0]
            if self.rotated is not None
            else _unseal(self.key, self.link, "pulse_refresh", self.link.sealed_refresh_token)
        )
        try:
            payload = await self.client.token(
                {"grant_type": "refresh_token", "refresh_token": refresh}
            )
        except IdentityProviderRejected as exc:
            self.revoked = True
            raise PulseLinkError(401, "link_refused", "Pulse no longer accepts this link.") from exc
        except IdentityProviderUnavailable as exc:
            raise PulseLinkError(503, "unavailable", "Pulse is unavailable. Try again.") from exc
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise PulseLinkError(503, "unavailable", "Pulse gave no access token.")
        expires = payload.get("expires_in")
        seconds = int(expires) if isinstance(expires, int) and 0 < expires <= 86400 else 300
        new_refresh = payload.get("refresh_token")
        self._access, self._until = access, time.time() + seconds - 60
        self.rotated = (
            new_refresh if isinstance(new_refresh, str) and new_refresh else refresh,
            access,
            datetime.now(UTC) + timedelta(seconds=seconds),
        )
        return access

    def save_tokens(self, link: PulseOrgLink) -> None:
        """Write rotated tokens onto the (re-read, locked) link row."""
        if self.rotated is None or link.status != "active":
            return
        refresh, access, until = self.rotated
        link.sealed_refresh_token = _seal(self.key, link, "pulse_refresh", refresh)
        link.sealed_access_token = _seal(self.key, link, "pulse_access", access)
        link.access_expires_at = until

    def _org_url(self, path: str) -> str:
        found = self.client.cached_discovery
        base = found.api_base if found is not None else f"{self.client.issuer}/api/v1"
        org = quote(str(self.link.pulse_org_id), safe="")
        return f"{base}/orgs/{org}{path}"

    async def call(self, method: str, path: str, **kwargs: Any) -> Any:
        await self.client.discovery()
        for attempt in (1, 2):
            token = await self.access_token()
            response = await self.client.request(
                method,
                self._org_url(path),
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                **kwargs,
            )
            if response.status_code == 401 and attempt == 1:
                self._until = 0  # the access token ran out early; refresh once
                continue
            if response.status_code == 404:
                return None
            if response.status_code == 204:
                return {}
            if response.status_code in (401, 403):
                raise PulseLinkError(403, "pulse_refused", "Pulse refused the link's request.")
            if response.status_code >= 400:
                raise PulseLinkError(503, "unavailable", "Pulse could not answer. Try again.")
            return self.client.json_of(response)
        raise PulseLinkError(403, "pulse_refused", "Pulse refused the link's request.")

    async def members(self, *, updated_since: datetime | None) -> tuple[list[MemberRecord], bool]:
        """Every member (or those changed since); and whether the read was complete."""
        found: list[MemberRecord] = []
        cursor: str | None = None
        for _ in range(_MEMBER_PAGES):
            params: dict[str, str] = {}
            if updated_since is not None:
                params["updated_since"] = updated_since.isoformat()
            if cursor:
                params["cursor"] = cursor
            page = await self.call("GET", "/members", params=params)
            if page is None:
                raise PulseLinkError(404, "org_missing", "Pulse doesn't know this org any more.")
            for raw in page.get("members") or []:
                member = MemberRecord.parse(raw)
                if member is not None:
                    found.append(member)
            next_cursor = page.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                return found, True
            cursor = next_cursor
        return found, False

    async def member(self, subject: str) -> MemberRecord | None:
        raw = await self.call("GET", f"/members/{quote(subject, safe='')}")
        return None if raw is None else MemberRecord.parse(raw)

    async def add_webhook(self, url: str) -> tuple[str, str] | None:
        if "pulse.org.webhooks" not in (self.link.scopes or []):
            return None
        answer = await self.call("POST", "/webhooks", json={"url": url, "events": list(EVENTS)})
        hook_id, secret = (answer or {}).get("id"), (answer or {}).get("secret")
        if not isinstance(hook_id, str) or not isinstance(secret, str) or not secret:
            return None
        return hook_id[:128], secret

    async def end(self) -> None:
        """Best effort at Pulse: the webhook, the link, then the refresh token."""
        try:
            if self.link.webhook_id:
                await self.call("DELETE", f"/webhooks/{quote(self.link.webhook_id, safe='')}")
            await self.call("DELETE", "/link")
        except PulseLinkError:
            pass
        try:
            refresh = _unseal(self.key, self.link, "pulse_refresh", self.link.sealed_refresh_token)
            await self.client.revoke(refresh)
        except (PulseLinkError, IdentityProviderUnavailable):
            pass


async def save_webhook(
    database: AsyncSession, key: sealed.SealKey, link_id: UUID, hook: tuple[str, str]
) -> None:
    link = await database.get(PulseOrgLink, link_id, with_for_update=True)
    if link is None or link.status != "active":
        return
    link.webhook_id = hook[0]
    link.sealed_webhook_secret = _seal(key, link, "pulse_webhook", hook[1])
    await database.flush()


# ----- the directory --------------------------------------------------------------


async def _person_by_subject(
    database: AsyncSession, tenant_id: UUID, issuer: str, subject: str
) -> UUID | None:
    found: UUID | None = await database.scalar(
        select(ProviderIdentity.person_id)
        .join(Membership, Membership.person_id == ProviderIdentity.person_id)
        .where(
            ProviderIdentity.issuer == issuer,
            ProviderIdentity.subject == subject,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
        .limit(1)
    )
    return found


async def _person_by_email(database: AsyncSession, tenant_id: UUID, email: str) -> UUID | None:
    rows = (
        await database.scalars(
            select(Person.id)
            .join(Membership, Membership.person_id == Person.id)
            .where(
                func.lower(Person.email) == email.lower(),
                Person.email_verified_at.is_not(None),
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
            .limit(2)
        )
    ).all()
    return rows[0] if len(rows) == 1 else None


@dataclass
class SyncCounts:
    seen: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    matched: int = 0
    missing: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "seen": self.seen,
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "matched": self.matched,
            "missing": self.missing,
        }


async def apply_member(
    database: AsyncSession,
    link: PulseOrgLink,
    record: MemberRecord,
    *,
    now: datetime,
    counts: SyncCounts,
) -> tuple[UUID, str] | None:
    """Upsert one directory row, match it, copy the profile; a photo to fetch, if any."""
    sharing = sharing_of(link.sharing)
    row: PulseOrgMember | None = await database.scalar(
        select(PulseOrgMember)
        .where(PulseOrgMember.link_id == link.id, PulseOrgMember.subject == record.subject)
        .with_for_update()
    )
    if row is not None and (
        row.pulse_updated_at is not None
        and record.updated_at is not None
        and record.updated_at < row.pulse_updated_at
    ):
        row.seen_at = now  # an older copy arrived late: updated_at decides
        return None
    if row is None:
        row = PulseOrgMember(
            id=uuid4(),
            link_id=link.id,
            tenant_id=link.tenant_id,
            subject=record.subject,
            email_verified=False,
            status="active",
            seen_at=now,
        )
        database.add(row)
        counts.added += 1
    else:
        counts.updated += 1
    counts.seen += 1
    row.email = record.email
    row.email_verified = record.email_verified
    row.name, row.title, row.team = record.name, record.title, record.team
    row.role, row.status = record.role, record.status
    row.pulse_updated_at = record.updated_at
    row.seen_at = now
    row.removed_at = None if record.status == "active" else (row.removed_at or now)
    picture = record.picture if sharing["photos"] == "read" else None
    row.picture_url = picture
    if picture is None:
        row.photo_jpeg, row.photo_sha256, row.photo_source_sha256 = None, None, None
    person_id = await _person_by_subject(database, link.tenant_id, link.issuer, record.subject)
    matched_by = "pulse_sign_in" if person_id is not None else None
    if person_id is None and record.email and record.email_verified:
        person_id = await _person_by_email(database, link.tenant_id, record.email)
        matched_by = "email" if person_id is not None else None
    row.person_id, row.matched_by = person_id, matched_by
    await database.flush()
    if person_id is not None:
        counts.matched += 1
        if record.status == "active":
            await record_profile(
                database,
                person_id=person_id,
                claims=PulseClaims(
                    issuer=link.issuer,
                    subject=record.subject,
                    name=record.name,
                    title=record.title,
                    team=record.team,
                    picture=picture,
                ),
                source="org_link",
                now=now,
            )
    elif record.status == "active":
        counts.missing += 1
    if picture is not None and row.photo_source_sha256 != picture_source_sha256(picture):
        return row.id, picture
    return None


async def mark_gone(
    database: AsyncSession, link: PulseOrgLink, seen: set[str], *, now: datetime
) -> int:
    """After a complete read: members Pulse no longer lists have left the Pulse org."""
    rows = (
        await database.scalars(
            select(PulseOrgMember).where(
                PulseOrgMember.link_id == link.id, PulseOrgMember.removed_at.is_(None)
            )
        )
    ).all()
    gone = 0
    for row in rows:
        if row.subject not in seen:
            row.removed_at, row.status = now, "removed"
            gone += 1
    await database.flush()
    return gone


async def save_member_photo(
    database: AsyncSession, member_id: UUID, picture: str, jpeg: bytes, *, now: datetime
) -> UUID | None:
    """Store a fetched photo on the directory row; the matched person, if any."""
    row = await database.get(PulseOrgMember, member_id, with_for_update=True)
    if row is None or row.picture_url != picture:
        return None
    row.photo_jpeg = jpeg
    row.photo_sha256 = hashlib.sha256(jpeg).hexdigest()
    row.photo_source_sha256 = picture_source_sha256(picture)
    await database.flush()
    return row.person_id


async def directory(database: AsyncSession, link: PulseOrgLink) -> list[dict[str, Any]]:
    rows = (
        await database.scalars(
            select(PulseOrgMember)
            .where(PulseOrgMember.link_id == link.id)
            .order_by(PulseOrgMember.removed_at.is_not(None), PulseOrgMember.name)
            .limit(1000)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "email": row.email,
            "title": row.title,
            "team": row.team,
            "pulse_role": row.role,
            "status": "left" if row.removed_at is not None else row.status,
            "photo_url": (
                f"/v1/sales-xray/pulse/members/{row.id}/photo" if row.photo_sha256 else None
            ),
            "person_id": str(row.person_id) if row.person_id else None,
            "matched_by": row.matched_by,
            "can_invite": (
                row.person_id is None
                and row.removed_at is None
                and row.status == "active"
                and bool(row.email)
                and row.email_verified
            ),
            "invited_at": row.invited_at.isoformat() if row.invited_at else None,
        }
        for row in rows
    ]


async def member_photo(
    database: AsyncSession, tenant_id: UUID, member_id: UUID
) -> tuple[bytes, str] | None:
    row = await database.scalar(
        select(PulseOrgMember)
        .options(undefer(PulseOrgMember.photo_jpeg))
        .where(PulseOrgMember.id == member_id, PulseOrgMember.tenant_id == tenant_id)
    )
    if row is None or row.photo_jpeg is None or row.photo_sha256 is None:
        return None
    return bytes(row.photo_jpeg), row.photo_sha256


def invite_command(link_id: UUID, subject: str) -> UUID:
    return uuid5(_NAMESPACE, f"invite:{link_id}:{subject}")


async def invitable(
    database: AsyncSession, link: PulseOrgLink, member_ids: Sequence[UUID]
) -> list[PulseOrgMember]:
    rows = (
        await database.scalars(
            select(PulseOrgMember)
            .where(PulseOrgMember.link_id == link.id, PulseOrgMember.id.in_(list(member_ids)))
            .with_for_update()
        )
    ).all()
    return [
        row
        for row in rows
        if row.person_id is None
        and row.removed_at is None
        and row.status == "active"
        and row.email
        and row.email_verified
    ]


# ----- webhooks -------------------------------------------------------------------


def verify_signature(
    header: str | None, body: bytes, secret: str, *, now: float | None = None
) -> bool:
    """``t=<unix>,v1=<hex HMAC-SHA256 of "t.body">`` (several v1 while Pulse rotates)."""
    if not header or len(header) > 1024:
        return False
    stamp: str | None = None
    signatures: list[str] = []
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "t":
            stamp = value
        elif name == "v1":
            signatures.append(value)
    if stamp is None or not stamp.isdigit() or not signatures:
        return False
    current = time.time() if now is None else now
    if abs(current - int(stamp)) > WEBHOOK_TOLERANCE_SECONDS:
        return False
    expected = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, given) for given in signatures)


def webhook_secret(key: sealed.SealKey, link: PulseOrgLink) -> str | None:
    if link.sealed_webhook_secret is None:
        return None
    try:
        return _unseal(key, link, "pulse_webhook", link.sealed_webhook_secret)
    except PulseLinkError:
        return None


async def end_link(
    database: AsyncSession,
    link_id: UUID,
    *,
    by: str,
    person_id: UUID | None,
    now: datetime,
    reason: str,
) -> PulseOrgLink | None:
    link = await database.get(PulseOrgLink, link_id, with_for_update=True)
    if link is None or link.status == "revoked":
        return None
    link.status = "revoked"
    link.revoked_at = now
    link.revoked_by = by[:160]
    # The keys go with the link; the directory stays as history, without photos.
    link.sealed_refresh_token = None
    link.sealed_access_token = None
    link.sealed_webhook_secret = None
    link.sealed_verifier = None
    link.state_sha256 = None
    await database.flush()
    for row in (
        await database.scalars(select(PulseOrgMember).where(PulseOrgMember.link_id == link.id))
    ).all():
        row.photo_jpeg, row.photo_sha256, row.photo_source_sha256 = None, None, None
    await database.flush()
    await AuditRepository(database).append(
        tenant_id=link.tenant_id,
        actor_person_id=person_id,
        actor_type="person" if person_id is not None else "system",
        action="pulse.org_unlinked",
        resource_type="pulse_org_link",
        resource_id=link.id,
        payload={"by": by[:40], "pulse_org_id": link.pulse_org_id},
        reason=reason,
        now=now,
    )
    return link


__all__ = [
    "CALLBACK_PATH",
    "EVENTS",
    "SHARING_CHOICES",
    "SHARING_DEFAULTS",
    "STALE_AFTER",
    "WEBHOOK_APP_PATH",
    "WEBHOOK_PATH",
    "Attempt",
    "Grant",
    "LinkSession",
    "MemberRecord",
    "PulseLinkError",
    "SyncCounts",
    "activate",
    "apply_member",
    "begin",
    "directory",
    "end_link",
    "exchange",
    "invitable",
    "invite_command",
    "mark_gone",
    "member_photo",
    "open_link",
    "save_member_photo",
    "save_webhook",
    "seal_key_from",
    "sharing_of",
    "take_attempt",
    "verify_signature",
    "webhook_secret",
]
