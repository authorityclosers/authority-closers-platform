"""Secrets the app must use again, sealed with AES-256-GCM under one platform key.

- ``webhook_signing``: made here (``whsec_`` and 40 letters and digits), shown once to
  the organisation's owner or admin, then only ever unsealed by the webhook runner to
  sign a delivery.
- ``partner_key``: a key the organisation pastes for an app Sales X-Ray calls (for
  example a hand-over service key). Never shown again.
- ``provider_key``: an AI provider's API key a control account adds in Admin's Providers
  hub, held under the operations workspace, one active per provider (``provider_hub.keys``).
  Never shown again.

The platform key is ``AC_INTEGRATIONS_SEAL_KEY``: 32 random bytes, base64url, one per
environment, held in Infisical and given to the API and the partner-events runner.
Each value is sealed with a fresh 96-bit nonce and bound (associated data) to its
row id, organisation and purpose, so a sealed value copied to another row does not
open. ``seal_key_id`` names the platform key that sealed it, for a later rotation.

A partner webhook endpoint or hand-over recipient made in the UI names its secret
``AC_PARTNER_WEBHOOK_SECRET__SEALED_<32 hex>``: it fits the 0096/0102 ``secret_ref``
pattern, and ``resolve`` reads it from here instead of the environment.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import secrets
import string
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Table, insert, select, update

from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.models import IntegrationSecret

ENV = "AC_INTEGRATIONS_SEAL_KEY"
REF_PREFIX = "AC_PARTNER_WEBHOOK_SECRET__SEALED_"  # noqa: S105 - a name, never a value
REF_PATTERN = re.compile(r"^AC_PARTNER_WEBHOOK_SECRET__SEALED_([0-9A-F]{32})$")
PURPOSES = frozenset({"webhook_signing", "partner_key", "provider_key"})
WEBHOOK_PREFIX = "whsec_"
_ALPHABET = string.ascii_letters + string.digits
_TABLE = cast(Table, IntegrationSecret.__table__)
_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class SealKey:
    key: bytes
    key_id: str


def key_from(value: str) -> SealKey | None:
    try:
        raw = base64.urlsafe_b64decode(value.strip() + "=" * (-len(value.strip()) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(raw) != 32:
        return None
    key_id = hashlib.sha256(b"ac-integrations-seal-key-id\x00" + raw).hexdigest()[:16]
    return SealKey(raw, key_id)


def load_key(environ: Mapping[str, str] | None = None) -> SealKey | None:
    """The platform key from the environment, or None when it is not set up here."""
    value = (os.environ if environ is None else environ).get(ENV, "")
    return key_from(value) if value else None


def _aad(secret_id: UUID, tenant_id: UUID, purpose: str) -> bytes:
    return f"ac-integrations:{_VERSION}:{secret_id}:{tenant_id}:{purpose}".encode()


def seal(key: SealKey, *, secret_id: UUID, tenant_id: UUID, purpose: str, value: bytes) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(key.key).encrypt(nonce, value, _aad(secret_id, tenant_id, purpose))
    return f"{_VERSION}." + base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")


def unseal(key: SealKey, row: Any) -> bytes:
    if row.seal_key_id != key.key_id:
        raise IntegrationError("seal_key_mismatch", 503)
    version, _, body = str(row.sealed).partition(".")
    if version != _VERSION:
        raise IntegrationError("seal_version", 503)
    blob = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    try:
        return AESGCM(key.key).decrypt(
            blob[:12], blob[12:], _aad(row.id, row.tenant_id, row.purpose)
        )
    except InvalidTag:
        raise IntegrationError("seal_invalid", 503) from None


def new_webhook_secret() -> str:
    return WEBHOOK_PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(40))


def ref_for(secret_id: UUID) -> str:
    return REF_PREFIX + secret_id.hex.upper()


def id_from_ref(ref: str | None) -> UUID | None:
    match = REF_PATTERN.fullmatch(ref or "")
    return UUID(match.group(1)) if match else None


def create(
    connection: Any,
    key: SealKey,
    *,
    tenant_id: UUID,
    purpose: str,
    value: str,
    person_id: UUID | None,
    meta: dict[str, Any],
    now: datetime,
) -> UUID:
    if purpose not in PURPOSES:
        raise IntegrationError("purpose")
    if not value or len(value) > 4096 or any(ord(ch) < 32 for ch in value):
        raise IntegrationError("secret_value")
    secret_id = uuid4()
    connection.execute(
        insert(_TABLE).values(
            id=secret_id,
            tenant_id=tenant_id,
            purpose=purpose,
            sealed=seal(
                key,
                secret_id=secret_id,
                tenant_id=tenant_id,
                purpose=purpose,
                value=value.encode("utf-8"),
            ),
            seal_key_id=key.key_id,
            hint=value[-4:],
            meta=meta,
            created_by_person_id=person_id,
            created_at=now,
            retired_at=None,
            retired_by=None,
        )
    )
    return secret_id


def retire(connection: Any, secret_id: UUID, *, by: str, now: datetime) -> None:
    connection.execute(
        update(_TABLE)
        .where(_TABLE.c.id == secret_id, _TABLE.c.retired_at.is_(None))
        .values(retired_at=now, retired_by=by)
    )


def hint(connection: Any, ref: str | None) -> str | None:
    """The last four characters of a sealed secret, for the page; None for env names."""
    secret_id = id_from_ref(ref)
    if secret_id is None:
        return None
    found = connection.scalar(select(_TABLE.c.hint).where(_TABLE.c.id == secret_id))
    return None if found is None else str(found)


def resolve(
    connection: Any, ref: str, *, tenant_id: UUID, key: SealKey | None = None
) -> bytes | None:
    """A sealed secret's value for the partner-events runner.

    None when ``ref`` is not a sealed name, the row is missing, retired or another
    organisation's, or the platform key is not set up here. Never raises for those, so
    the runner records ``secret_missing`` and retries as it does for a missing variable.
    """
    secret_id = id_from_ref(ref)
    if secret_id is None:
        return None
    key = key or load_key()
    if key is None:
        return None
    row = connection.execute(select(_TABLE).where(_TABLE.c.id == secret_id)).first()
    if row is None or row.retired_at is not None or row.tenant_id != tenant_id:
        return None
    try:
        return unseal(key, row)
    except IntegrationError:
        return None
