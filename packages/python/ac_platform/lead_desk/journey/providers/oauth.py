"""Connect an ad platform (LinkedIn, TikTok, Microsoft Advertising) to an organisation.

The same shape as Continue with Meta and Google: a manager presses Connect, signs in at
the platform and allows Sales Xray; the callback swaps the code for tokens, seals them
to the organisation (AES-GCM, ``AC_LEAD_DESK_TOKEN_KEY``) and keeps them in its Lead
Desk settings under ``ad_connections``. Nothing here runs until the platform's app
settings exist on the environment (``app()`` returns None and the card says the
platform isn't set up here yet).
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from ac_platform.lead_desk.connectors import meta

KEY: Final[str] = "ad_connections"
# The address part of each platform's connect and callback routes.
SLUGS: Final[dict[str, str]] = {
    "linkedin": "linkedin",
    "tiktok": "tiktok",
    "microsoft_ads": "microsoft",
}
_ENV: Final[dict[str, tuple[str, str, tuple[str, ...]]]] = {
    "linkedin": ("AC_LINKEDIN_CLIENT_ID", "AC_LINKEDIN_CLIENT_SECRET", ()),
    "tiktok": ("AC_TIKTOK_APP_ID", "AC_TIKTOK_APP_SECRET", ()),
    "microsoft_ads": (
        "AC_MICROSOFT_ADS_CLIENT_ID",
        "AC_MICROSOFT_ADS_CLIENT_SECRET",
        ("AC_MICROSOFT_ADS_DEVELOPER_TOKEN",),
    ),
}


class ConnectError(ValueError):
    """Connecting failed; the message is safe to show a manager."""


@dataclass(frozen=True, slots=True)
class App:
    provider: str
    client_id: str
    client_secret: str
    token_key: bytes
    extra: dict[str, str] = field(default_factory=dict)


def app(provider: str, env: Mapping[str, str] | None = None) -> App | None:
    """AC's app for this platform on this environment, or None while any setting is missing."""
    env = os.environ if env is None else env
    names = _ENV.get(provider)
    if names is None:
        return None
    client_name, secret_name, extra_names = names
    values = {
        name: (env.get(name) or "").strip()
        for name in (client_name, secret_name, *extra_names, "AC_LEAD_DESK_TOKEN_KEY")
    }
    if not all(values.values()):
        return None
    try:
        key = base64.urlsafe_b64decode(values["AC_LEAD_DESK_TOKEN_KEY"] + "==")
    except (ValueError, TypeError):
        return None
    if len(key) != 32:
        return None
    extra = {name: values[name] for name in extra_names}
    for name in ("AC_MICROSOFT_ADS_SANDBOX", "AC_LINKEDIN_VERSION", "AC_TIKTOK_SANDBOX"):
        if env.get(name):
            extra[name] = str(env[name]).strip()
    return App(provider, values[client_name], values[secret_name], key, extra)


def bound(provider: str, tenant_id: UUID) -> str:
    """What a platform's tokens are sealed to: they can't move to another organisation."""
    return f"{provider}:organisation:{tenant_id}"


def make_state(cfg: App, *, tenant_id: UUID, person_id: UUID) -> str:
    return meta.make_state(cfg.client_secret, tenant_id=tenant_id, person_id=person_id)


def read_state(cfg: App, state: str, *, tenant_id: UUID, person_id: UUID) -> dict[str, Any]:
    try:
        return meta.read_state(cfg.client_secret, state, tenant_id=tenant_id, person_id=person_id)
    except meta.MetaError as error:
        raise ConnectError(str(error).replace("Meta", "the platform")) from None


def saved(
    config: Mapping[str, Any],
    cfg: App,
    tenant_id: UUID,
    *,
    tokens: Mapping[str, Any],
    accounts: list[dict[str, str]],
    by: UUID,
) -> dict[str, Any]:
    """The Lead Desk config with this platform's sealed tokens and the accounts seen."""
    out = dict(config)
    box = dict(out.get(KEY) or {}) if isinstance(out.get(KEY), Mapping) else {}
    box[cfg.provider] = {
        "token": meta.seal(
            cfg.token_key, json.dumps(dict(tokens)), page_id=bound(cfg.provider, tenant_id)
        ),
        "accounts": accounts[:50],
        "by": str(by),
        "at": int(time.time()),
    }
    out[KEY] = box
    return out


def tokens_of(config: Mapping[str, Any], cfg: App, tenant_id: UUID) -> dict[str, Any] | None:
    box = config.get(KEY)
    entry = box.get(cfg.provider) if isinstance(box, Mapping) else None
    sealed = entry.get("token") if isinstance(entry, Mapping) else None
    if not isinstance(sealed, Mapping):
        return None
    try:
        raw = meta.unseal(cfg.token_key, sealed, page_id=bound(cfg.provider, tenant_id))
    except Exception:  # noqa: BLE001 - any failure means the tokens can't be used
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def accounts_of(config: Mapping[str, Any], provider: str) -> list[dict[str, str]]:
    box = config.get(KEY)
    entry = box.get(provider) if isinstance(box, Mapping) else None
    found = entry.get("accounts") if isinstance(entry, Mapping) else None
    return [
        {"id": str(item.get("id")), "name": str(item.get("name") or item.get("id"))}
        for item in found or []
        if isinstance(item, Mapping) and item.get("id")
    ]


def with_tokens(
    config: Mapping[str, Any], cfg: App, tenant_id: UUID, tokens: Mapping[str, Any]
) -> dict[str, Any]:
    """The config with refreshed tokens (the accounts and who connected stay)."""
    out = dict(config)
    box = dict(out.get(KEY) or {})
    entry = dict(box.get(cfg.provider) or {})
    entry["token"] = meta.seal(
        cfg.token_key, json.dumps(dict(tokens)), page_id=bound(cfg.provider, tenant_id)
    )
    box[cfg.provider] = entry
    out[KEY] = box
    return out


async def store_tokens(db: Any, tenant_id: UUID, cfg: App, tokens: Mapping[str, Any]) -> None:
    """Keep refreshed tokens on the organisation's settings (a short row lock)."""
    from ac_platform.lead_desk.models import LeadDeskSettings

    row = await db.get(LeadDeskSettings, tenant_id, with_for_update=True)
    if row is not None:
        row.config = with_tokens(row.config or {}, cfg, tenant_id, tokens)


def expired(tokens: Mapping[str, Any], *, margin: int = 300) -> bool:
    at = tokens.get("expires_at")
    return isinstance(at, (int, float)) and at - margin <= time.time()


def stamped(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Tokens from an OAuth answer, with when the access token ends."""
    out: dict[str, Any] = {
        "access_token": str(answer.get("access_token") or ""),
        "refresh_token": str(answer.get("refresh_token") or "") or None,
    }
    lasts = answer.get("expires_in")
    if isinstance(lasts, (int, float)) and lasts > 0:
        out["expires_at"] = int(time.time() + lasts)
    return out
