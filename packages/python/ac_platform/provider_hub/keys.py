"""Provider keys in Admin's Providers hub (owner, 20 Oct 2026: "add key and boom it's there,
and all its models listed").

- A verified AC control account adds a provider's API key in Admin, within 10 minutes of
  signing in. It is sealed for this environment in ``integration_secrets`` (purpose
  ``provider_key``, under the operations workspace, AES-256-GCM with the platform key) and
  never shown again: the page keeps only its last four characters. One active key per
  provider; a new key retires the one before it, and removing a key retires it, so the
  history stays. Each change is audited with the provider and the last four characters,
  never the key.
- The connection test unseals the key and makes the provider's free read: its model list,
  or OpenRouter's key read, or Deepgram's project list. It answers the status, a failure
  in plain words and how many models the key can use; the model ids stay in memory so the
  hub lists them. No body is kept, nothing is charged and the key goes only to the
  provider's own fixed address.
- Providers with no free read (AssemblyAI, Sarvam, Gladia, Speechmatics, a custom
  gateway) keep their key untested: the first real use is the test.

Using a sealed key for analysis comes next: the workers need the platform key first
(Root), and production also needs the owner's approval (the production approval design).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.identity.models import Session
from ac_platform.integrations import sealed
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.models import IntegrationSecret
from ac_platform.kernel.authz import ActorContext
from ac_platform.provider_hub.catalogue import BY_ID
from ac_platform.provider_hub.health import plain_words

PURPOSE = "provider_key"
ADDED = "admin.provider_key_added"
REMOVED = "admin.provider_key_removed"
TESTED = "admin.provider_key_tested"
RESOURCE = "integration_secret"
# A key is added only right after signing in, as a staff key is made.
FRESH_SIGN_IN = timedelta(minutes=10)
MAX_BODY = 4 * 1024 * 1024
MAX_MODELS = 1000
MODEL_ID = re.compile(r"[A-Za-z0-9][\w.:/@+-]{0,127}")
KEY_TEXT = re.compile(r"[\x21-\x7e]{8,512}")


@dataclass(frozen=True, slots=True)
class FreeRead:
    """A provider's free read with a key: where, which header, and where its models are."""

    url: str
    header: str
    scheme: str = ""  # written before the key in the header, e.g. "Bearer "
    listing: str | None = "data"  # the answer's model list ("": the whole answer; None: none)
    extra: tuple[tuple[str, str], ...] = ()


FREE_READS: dict[str, FreeRead] = {
    "openrouter": FreeRead(
        "https://openrouter.ai/api/v1/key", "Authorization", "Bearer ", listing=None
    ),
    "gemini": FreeRead(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
        "x-goog-api-key",
        listing="models",
    ),
    "openai": FreeRead("https://api.openai.com/v1/models", "Authorization", "Bearer "),
    "anthropic": FreeRead(
        "https://api.anthropic.com/v1/models?limit=1000",
        "x-api-key",
        extra=(("anthropic-version", "2023-06-01"),),
    ),
    "groq": FreeRead("https://api.groq.com/openai/v1/models", "Authorization", "Bearer "),
    "deepseek": FreeRead("https://api.deepseek.com/models", "Authorization", "Bearer "),
    "mistral": FreeRead("https://api.mistral.ai/v1/models", "Authorization", "Bearer "),
    "together": FreeRead(
        "https://api.together.xyz/v1/models", "Authorization", "Bearer ", listing=""
    ),
    "fireworks": FreeRead(
        "https://api.fireworks.ai/inference/v1/models", "Authorization", "Bearer "
    ),
    "cerebras": FreeRead("https://api.cerebras.ai/v1/models", "Authorization", "Bearer "),
    "elevenlabs": FreeRead("https://api.elevenlabs.io/v1/models", "xi-api-key", listing=""),
    "deepgram": FreeRead(
        "https://api.deepgram.com/v1/projects", "Authorization", "Token ", listing=None
    ),
}

# Provider id → (when, model ids) from its key's last good test, for the hub's model list.
LISTED: dict[str, tuple[datetime, list[str]]] = {}

Read = Callable[[FreeRead, str], Awaitable[tuple[int, Any]]]


async def free_read(check: FreeRead, key: str) -> tuple[int, Any]:
    """The status and, on 200, the JSON answer; 0 when the provider can't be reached."""
    headers = {
        "Accept": "application/json",
        check.header: f"{check.scheme}{key}",
        **dict(check.extra),
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            answer = await client.get(check.url, headers=headers)
    except httpx.HTTPError:
        return 0, None
    if answer.status_code != 200 or len(answer.content) > MAX_BODY:
        return answer.status_code, None
    try:
        return 200, answer.json()
    except ValueError:
        return 200, None


def model_ids(check: FreeRead, document: Any) -> list[str]:
    """The model ids a free read lists (Gemini's "models/" prefix dropped), at most 1,000."""
    if check.listing is None:
        return []
    if check.listing == "":
        items = document
    else:
        items = document.get(check.listing) if isinstance(document, Mapping) else None
    ids: list[str] = []
    for item in items if isinstance(items, list) else []:
        value = None
        if isinstance(item, Mapping):
            value = item.get("id") or item.get("model_id") or item.get("name")
        if isinstance(value, str):
            value = value.removeprefix("models/")
            if MODEL_ID.fullmatch(value) and value not in ids:
                ids.append(value)
        if len(ids) >= MAX_MODELS:
            break
    return ids


def outcome_words(status: int, models: int, listing: bool) -> tuple[bool, str, str | None]:
    """Whether the key works, in plain words, and what fixes it when it doesn't."""
    if status == 200:
        if not listing:
            return True, "The key works.", None
        noun = "model" if models == 1 else "models"
        return True, f"The key works: {models} {noun} listed.", None
    if status == 0:
        return False, "The provider could not be reached just now. Try again.", "wait"
    if status == 404:
        return (
            False,
            "The provider's check address answered 404. An engineer needs to look.",
            ("engineer"),
        )
    words, fix = plain_words(status, None)
    return False, words, fix


class ProviderKeys:
    """Add, remove and test provider keys: browser only, verified control accounts."""

    def __init__(
        self,
        database: AsyncSession,
        settings: Settings,
        *,
        environ: Mapping[str, str] | None = None,
        read: Read = free_read,
    ) -> None:
        self.database = database
        self.settings = settings
        self.seal_key = sealed.load_key(environ)
        self.read = read

    async def _admit(self, actor: ActorContext) -> UUID:
        tenant = self.settings.operations_tenant_id
        if tenant is None or actor.tenant_id != tenant:
            raise ConversationDenied("Provider keys need the AC operations workspace.")
        await ConversationProviderAdmin(ConversationApplication(self.database)).admit(actor)
        return tenant

    async def _fresh(self, actor: ActorContext, now: datetime) -> None:
        signed_in = await self.database.scalar(
            select(Session.created_at).where(Session.id == actor.session_id)
        )
        if signed_in is None or now - signed_in > FRESH_SIGN_IN:
            raise ConversationDenied(
                "Sign in again to add a key: it needs a sign-in within the last 10 minutes."
            )

    async def _active(self, tenant: UUID, provider: str | None = None) -> list[IntegrationSecret]:
        rows = (
            await self.database.scalars(
                select(IntegrationSecret)
                .where(
                    IntegrationSecret.tenant_id == tenant,
                    IntegrationSecret.purpose == PURPOSE,
                    IntegrationSecret.retired_at.is_(None),
                )
                .order_by(IntegrationSecret.created_at.desc())
            )
        ).all()
        return [
            row for row in rows if provider is None or (row.meta or {}).get("provider") == provider
        ]

    async def _retire(
        self, rows: list[IntegrationSecret], actor: ActorContext, now: datetime
    ) -> None:
        by = f"settings:person:{actor.person_id}"
        for row in rows:
            await self.database.run_sync(
                lambda sync, secret_id=row.id: sealed.retire(
                    sync.connection(), secret_id, by=by, now=now
                )
            )

    async def view(self, actor: ActorContext) -> dict[str, Any]:
        """Which providers have a key here: the last four characters and the last test."""
        tenant = await self._admit(actor)
        rows = await self._active(tenant)
        tests: dict[str, dict[str, Any]] = {}
        if rows:
            events = (
                await self.database.execute(
                    select(AuditEvent.resource_id, AuditEvent.payload, AuditEvent.occurred_at)
                    .where(
                        AuditEvent.tenant_id == tenant,
                        AuditEvent.action == TESTED,
                        AuditEvent.resource_type == RESOURCE,
                        AuditEvent.resource_id.in_([str(row.id) for row in rows]),
                    )
                    .order_by(AuditEvent.occurred_at.desc())
                )
            ).all()
            for resource_id, payload, at in events:
                if resource_id not in tests:
                    tests[resource_id] = {**dict(payload or {}), "at": at.isoformat()}
        keys = []
        seen: set[str] = set()
        for row in rows:
            provider = str((row.meta or {}).get("provider") or "")
            if provider in seen or provider not in BY_ID:
                continue
            seen.add(provider)
            tested = tests.get(str(row.id))
            check = FREE_READS.get(provider)
            words: tuple[bool, str, str | None] | None = None
            if tested is not None and check is not None:
                words = outcome_words(
                    int(tested.get("status") or 0),
                    int(tested.get("models") or 0),
                    check.listing is not None,
                )
            keys.append(
                {
                    "provider": provider,
                    "hint": row.hint,
                    "added_at": row.created_at.isoformat(),
                    "free_check": provider in FREE_READS,
                    "tested": None
                    if tested is None
                    else {
                        "at": tested["at"],
                        "ok": bool(tested.get("ok")),
                        "status": tested.get("status"),
                        "models": tested.get("models"),
                        "words": words[1] if words else "",
                        "fix": words[2] if words else None,
                    },
                }
            )
        return {
            "environment": self.settings.environment,
            "sealing": self.seal_key is not None,
            "fresh_minutes": int(FRESH_SIGN_IN.total_seconds() // 60),
            "keys": keys,
        }

    async def add(
        self, actor: ActorContext, provider: str, value: str, *, now: datetime
    ) -> dict[str, Any]:
        """Seal a provider's key for this environment; the one before it is retired."""
        tenant = await self._admit(actor)
        if provider not in BY_ID:
            raise ConversationNotFound("There is no such provider in the catalogue.")
        key = self.seal_key
        if key is None:
            raise ConversationError(
                "Keys can't be sealed here yet: this environment's API has no platform key."
            )
        await self._fresh(actor, now)
        text = value.strip()
        if not KEY_TEXT.fullmatch(text):
            raise ConversationError(
                "Paste the key as the provider shows it: 8 to 512 characters, no spaces."
            )
        before = await self._active(tenant, provider)
        await self._retire(before, actor, now)
        secret_id = await self.database.run_sync(
            lambda sync: sealed.create(
                sync.connection(),
                key,
                tenant_id=tenant,
                purpose=PURPOSE,
                value=text,
                person_id=actor.person_id,
                meta={"provider": provider, "source": "admin"},
                now=now,
            )
        )
        await AuditRepository(self.database).append_for_actor(
            actor,
            action=ADDED,
            resource_type=RESOURCE,
            resource_id=secret_id,
            payload={
                "provider": provider,
                "hint": text[-4:],
                "replaced": len(before),
                "environment": self.settings.environment,
            },
        )
        LISTED.pop(provider, None)
        return {"provider": provider, "hint": text[-4:], "added_at": now.isoformat()}

    async def remove(self, actor: ActorContext, provider: str, *, now: datetime) -> dict[str, Any]:
        """Retire a provider's key here; nothing can use it after this."""
        tenant = await self._admit(actor)
        rows = await self._active(tenant, provider)
        if not rows:
            raise ConversationNotFound("This provider has no key here.")
        await self._retire(rows, actor, now)
        for row in rows:
            await AuditRepository(self.database).append_for_actor(
                actor,
                action=REMOVED,
                resource_type=RESOURCE,
                resource_id=row.id,
                payload={"provider": provider, "hint": row.hint},
            )
        LISTED.pop(provider, None)
        return {"provider": provider, "removed": len(rows)}

    async def test(self, actor: ActorContext, provider: str, *, now: datetime) -> dict[str, Any]:
        """The provider's free read with its key: works or not, in plain words, and models."""
        tenant = await self._admit(actor)
        rows = await self._active(tenant, provider)
        if not rows:
            raise ConversationNotFound("Add a key first.")
        check = FREE_READS.get(provider)
        if check is None:
            return {
                "provider": provider,
                "ok": None,
                "status": None,
                "models": None,
                "words": "This provider has no free check: its first real use is the test.",
                "fix": None,
            }
        key = self.seal_key
        if key is None:
            raise ConversationError(
                "Keys can't be opened here: this environment's API has no platform key."
            )
        row = rows[0]
        try:
            value = sealed.unseal(key, row).decode("utf-8")
        except IntegrationError:
            raise ConversationError(
                "This key was sealed under another platform key. Add it again."
            ) from None
        status, document = await self.read(check, value)
        ids = model_ids(check, document) if status == 200 else []
        ok, words, fix = outcome_words(status, len(ids), check.listing is not None)
        if ids:
            LISTED[provider] = (now, ids)
        result = {
            "provider": provider,
            "ok": ok,
            "status": status or None,
            "models": len(ids) if check.listing is not None and status == 200 else None,
        }
        await AuditRepository(self.database).append_for_actor(
            actor,
            action=TESTED,
            resource_type=RESOURCE,
            resource_id=row.id,
            payload=result,
        )
        return {**result, "words": words, "fix": fix, "at": now.isoformat()}
