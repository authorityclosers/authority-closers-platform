"""WhatsApp Cloud API for the Sales Xray CRM: AC's Meta app, and each customer's own number.

An organisation connects its own WhatsApp Business number with Meta's Embedded Signup
(the "Sales Xray WhatsApp" app, see docs/product/lead-desk/whatsapp-app.md). The page
gets a one-time code and the number's ids; the server swaps the code for a business
integration token, subscribes AC's app to the account's webhook and registers the
number for the Cloud API. The token is sealed to the number. The customer's own
WhatsApp account is billed by Meta; Sales Xray never pays for or shows a price.

Messages follow Meta's rules: free text only inside the 24-hour customer service
window (from the person's last message); outside it, an approved template only, and
only to someone who opted in.

Nothing runs until AC's WhatsApp app settings exist; ``config()`` is None until then.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx

from ac_platform.lead_desk.connectors import meta

GRAPH: Final[str] = "https://graph.facebook.com"
WINDOW: Final[timedelta] = timedelta(hours=24)
TEXT_LIMIT: Final[int] = 4096
WA_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9]{6,20}$")
META_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9]{5,32}$")
TEMPLATE_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_]{1,512}$")
LANGUAGE: Final[re.Pattern[str]] = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")
KINDS: Final[frozenset[str]] = frozenset(
    {
        "text",
        "image",
        "audio",
        "video",
        "document",
        "sticker",
        "location",
        "contacts",
        "interactive",
        "button",
        "reaction",
    }
)
STATUSES: Final[tuple[str, ...]] = ("sent", "delivered", "read", "failed")


class WhatsAppError(ValueError):
    """Something about WhatsApp failed; the message is safe to show a person."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WhatsAppConfig:
    app_id: str
    app_secret: str
    config_id: str
    verify_token: str
    token_key: bytes
    graph_version: str

    @property
    def graph(self) -> str:
        return f"{GRAPH}/{self.graph_version}"


def config(env: Mapping[str, str] | None = None) -> WhatsAppConfig | None:
    """AC's WhatsApp app settings, or None while any is missing (the channel stays off)."""
    env = os.environ if env is None else env
    names = (
        "AC_WHATSAPP_APP_ID",
        "AC_WHATSAPP_APP_SECRET",
        "AC_WHATSAPP_CONFIG_ID",
        "AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
    )
    values = {name: (env.get(name) or "").strip() for name in names}
    if not all(values.values()):
        return None
    # The same sealing key as the Meta leads connector (AC_LEAD_DESK_TOKEN_KEY).
    key = meta.token_key(env.get("AC_LEAD_DESK_TOKEN_KEY") or "")
    if key is None:
        return None
    version = (
        env.get("AC_WHATSAPP_GRAPH_VERSION") or env.get("AC_META_GRAPH_VERSION") or "v23.0"
    ).strip()
    return WhatsAppConfig(
        app_id=values["AC_WHATSAPP_APP_ID"],
        app_secret=values["AC_WHATSAPP_APP_SECRET"],
        config_id=values["AC_WHATSAPP_CONFIG_ID"],
        verify_token=values["AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN"],
        token_key=key,
        graph_version=version,
    )


def seal(cfg: WhatsAppConfig, value: str, *, phone_number_id: str, what: str) -> dict[str, str]:
    """Sealed to one number and one use: a token can't be moved to another number."""
    return meta.seal(cfg.token_key, value, page_id=f"whatsapp:{what}:{phone_number_id}")


def unseal(cfg: WhatsAppConfig, box: Mapping[str, Any], *, phone_number_id: str, what: str) -> str:
    try:
        return meta.unseal(cfg.token_key, box, page_id=f"whatsapp:{what}:{phone_number_id}")
    except meta.MetaError:
        raise WhatsAppError("Connect this WhatsApp number again.") from None


def dialog_url(cfg: WhatsAppConfig, *, redirect_uri: str, state: str) -> str:
    """Meta's Embedded Signup as a page the browser goes to (no SDK on our pages)."""
    from urllib.parse import urlencode

    query = urlencode(
        {
            "client_id": cfg.app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "config_id": cfg.config_id,
            "response_type": "code",
            "override_default_response_type": "true",
            "extras": '{"setup":{}}',
        }
    )
    return f"https://www.facebook.com/{cfg.graph_version}/dialog/oauth?{query}"


def new_pin() -> str:
    """The two-step verification PIN Sales Xray sets when it registers a number."""
    return f"{secrets.randbelow(1_000_000):06d}"


# ----- numbers and the 24-hour window ------------------------------------------------


def wa_id(phone: str | None) -> str | None:
    """A lead's E.164 phone as WhatsApp's id: the digits with the country code."""
    digits = re.sub(r"[^0-9]", "", phone or "")
    return digits if WA_ID.fullmatch(digits) else None


def e164(wa: str) -> str:
    return f"+{wa}"


def window_open(last_inbound: datetime | None, now: datetime) -> bool:
    """Free text is allowed for 24 hours after the person's last message."""
    return last_inbound is not None and now - last_inbound < WINDOW


def window_closes(last_inbound: datetime | None) -> datetime | None:
    return last_inbound + WINDOW if last_inbound is not None else None


def template_text(components: list[Any]) -> str:
    """A template's body text, with its {{1}} placeholders, for showing it."""
    for component in components:
        if isinstance(component, Mapping) and str(component.get("type")).upper() == "BODY":
            return str(component.get("text") or "")
    return ""


def placeholders(text: str) -> int:
    """How many {{n}} values a template's body asks for."""
    numbers = {int(found) for found in re.findall(r"\{\{(\d{1,2})\}\}", text)}
    return max(numbers) if numbers else 0


def fill(text: str, values: list[str]) -> str:
    """The body as the person will read it."""
    return re.sub(
        r"\{\{(\d{1,2})\}\}",
        lambda match: (
            values[int(match.group(1)) - 1]
            if 0 < int(match.group(1)) <= len(values)
            else match.group(0)
        ),
        text,
    )


# ----- webhook -------------------------------------------------------------------------


def signature_ok(app_secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@dataclass(frozen=True, slots=True)
class Inbound:
    phone_number_id: str
    wa_id: str
    wamid: str
    kind: str
    body: str | None
    media: dict[str, Any] | None
    at: datetime
    profile_name: str | None


@dataclass(frozen=True, slots=True)
class Status:
    phone_number_id: str
    wamid: str
    status: str
    at: datetime
    error_code: str | None = None
    error_title: str | None = None


@dataclass(frozen=True, slots=True)
class TemplateUpdate:
    waba_id: str
    meta_id: str
    name: str | None
    language: str | None
    status: str
    reason: str | None


@dataclass(slots=True)
class Delivery:
    inbound: list[Inbound] = field(default_factory=list)
    statuses: list[Status] = field(default_factory=list)
    templates: list[TemplateUpdate] = field(default_factory=list)
    quality: list[tuple[str, str]] = field(default_factory=list)  # (display number, rating)


def _time(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(UTC)


def _body(message: Mapping[str, Any], kind: str) -> tuple[str | None, dict[str, Any] | None]:
    """The words of a message, and what a media message carries (ids only, no download)."""
    found = message.get(kind)
    part: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    if kind == "text":
        return str(part.get("body") or "")[:TEXT_LIMIT] or None, None
    if kind == "button":
        return str(part.get("text") or "")[:TEXT_LIMIT] or None, None
    if kind == "interactive":
        reply = part.get("button_reply") or part.get("list_reply") or {}
        title = reply.get("title") if isinstance(reply, Mapping) else None
        return (str(title)[:TEXT_LIMIT] if title else None), None
    if kind == "reaction":
        return str(part.get("emoji") or "")[:16] or None, None
    if kind in {"image", "audio", "video", "document", "sticker"}:
        media = {
            key: str(part[key])[:300] for key in ("id", "mime_type", "filename") if part.get(key)
        }
        caption = str(part.get("caption") or "")[:TEXT_LIMIT] or None
        return caption, media or None
    if kind == "location":
        name = part.get("name") or part.get("address")
        return (str(name)[:300] if name else None), None
    return None, None


def parse(payload: Mapping[str, Any]) -> Delivery:
    """What one webhook delivery says: new messages, delivery statuses, template reviews."""
    out = Delivery()
    if payload.get("object") != "whatsapp_business_account":
        return out
    for entry in payload.get("entry") or []:
        if not isinstance(entry, Mapping):
            continue
        waba_id = str(entry.get("id") or "")
        for change in entry.get("changes") or []:
            if not isinstance(change, Mapping) or not isinstance(change.get("value"), Mapping):
                continue
            value = change["value"]
            name = change.get("field")
            if name == "messages":
                meta_info = value.get("metadata")
                metadata: Mapping[str, Any] = meta_info if isinstance(meta_info, Mapping) else {}
                number = str(metadata.get("phone_number_id") or "")
                if not META_ID.fullmatch(number):
                    continue
                profiles = {
                    str(contact.get("wa_id")): str(
                        (contact.get("profile") or {}).get("name") or ""
                    )[:200]
                    for contact in value.get("contacts") or []
                    if isinstance(contact, Mapping)
                }
                for message in value.get("messages") or []:
                    if not isinstance(message, Mapping):
                        continue
                    sender = str(message.get("from") or "")
                    wamid = str(message.get("id") or "")[:200]
                    if not WA_ID.fullmatch(sender) or not wamid:
                        continue
                    raw_kind = str(message.get("type") or "")
                    kind = raw_kind if raw_kind in KINDS else "unsupported"
                    body, media = _body(message, kind)
                    out.inbound.append(
                        Inbound(
                            number,
                            sender,
                            wamid,
                            kind,
                            body,
                            media,
                            _time(message.get("timestamp")),
                            profiles.get(sender) or None,
                        )
                    )
                for status in value.get("statuses") or []:
                    if not isinstance(status, Mapping) or status.get("status") not in STATUSES:
                        continue
                    errors = status.get("errors") if isinstance(status.get("errors"), list) else []
                    first = errors[0] if errors and isinstance(errors[0], Mapping) else {}
                    out.statuses.append(
                        Status(
                            number,
                            str(status.get("id") or "")[:200],
                            str(status["status"]),
                            _time(status.get("timestamp")),
                            str(first.get("code"))[:32] if first.get("code") else None,
                            str(first.get("title") or first.get("message") or "")[:200] or None,
                        )
                    )
            elif name == "message_template_status_update":
                meta_id = str(value.get("message_template_id") or "")
                if META_ID.fullmatch(meta_id) and value.get("event"):
                    out.templates.append(
                        TemplateUpdate(
                            waba_id,
                            meta_id,
                            str(value.get("message_template_name") or "") or None,
                            str(value.get("message_template_language") or "") or None,
                            str(value["event"]).upper()[:24],
                            str(value.get("reason") or "")[:200] or None,
                        )
                    )
            elif name == "phone_number_quality_update":
                number = str(value.get("display_phone_number") or "")
                rating = str(value.get("event") or value.get("current_limit") or "")
                if number and rating:
                    out.quality.append((number[:32], rating[:16]))
    return out


# ----- Graph API -------------------------------------------------------------------------


class Cloud:
    """The WhatsApp Cloud API calls Sales Xray makes. Errors become plain messages."""

    def __init__(
        self, cfg: WhatsAppConfig, client: httpx.AsyncClient | None = None, *, timeout: float = 15
    ) -> None:
        self.cfg = cfg
        self._client = client
        self.timeout = timeout

    async def _call(
        self, method: str, path: str, *, token: str | None, json: Any = None, **params: Any
    ) -> dict[str, Any]:
        url = f"{self.cfg.graph}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.request(
                method, url, params=params or None, json=json, headers=headers
            )
        except httpx.HTTPError:
            raise WhatsAppError("WhatsApp didn't answer. Try again in a minute.") from None
        finally:
            if self._client is None:
                await client.aclose()
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            error = body.get("error", {}) if isinstance(body, dict) else {}
            raise refusal(error if isinstance(error, Mapping) else {})
        return body if isinstance(body, dict) else {}

    async def exchange(self, code: str, *, redirect_uri: str | None = None) -> str:
        """Embedded Signup's one-time code for the business's token. A code from the
        redirect flow is swapped with the same return address."""
        body = await self._call(
            "GET",
            "oauth/access_token",
            token=None,
            client_id=self.cfg.app_id,
            client_secret=self.cfg.app_secret,
            code=code,
            **({"redirect_uri": redirect_uri} if redirect_uri else {}),
        )
        token = str(body.get("access_token") or "")
        if not token:
            raise WhatsAppError("WhatsApp didn't finish connecting. Start again.")
        return token

    async def shared_accounts(self, token: str) -> list[str]:
        """The WhatsApp Business accounts the customer shared during Embedded Signup."""
        body = await self._call(
            "GET",
            "debug_token",
            token=None,
            input_token=token,
            access_token=f"{self.cfg.app_id}|{self.cfg.app_secret}",
        )
        data = body.get("data") if isinstance(body.get("data"), Mapping) else {}
        accounts: list[str] = []
        for scope in data.get("granular_scopes") or [] if isinstance(data, Mapping) else []:
            if isinstance(scope, Mapping) and scope.get("scope") == "whatsapp_business_management":
                accounts.extend(
                    str(target)
                    for target in scope.get("target_ids") or []
                    if META_ID.fullmatch(str(target))
                )
        return list(dict.fromkeys(accounts))[:20]

    async def phone_numbers(self, waba_id: str, token: str) -> list[str]:
        """The numbers in one shared WhatsApp Business account."""
        body = await self._call(
            "GET", f"{waba_id}/phone_numbers", token=token, fields="id", limit=50
        )
        return [
            str(row["id"])
            for row in body.get("data") or []
            if isinstance(row, Mapping) and META_ID.fullmatch(str(row.get("id") or ""))
        ][:50]

    async def number(self, phone_number_id: str, token: str) -> dict[str, str]:
        body = await self._call(
            "GET",
            phone_number_id,
            token=token,
            fields="display_phone_number,verified_name,quality_rating",
        )
        return {
            "display_number": str(body.get("display_phone_number") or phone_number_id)[:32],
            "verified_name": str(body.get("verified_name") or "")[:200],
            "quality": str(body.get("quality_rating") or "")[:16],
        }

    async def subscribe(self, waba_id: str, token: str) -> None:
        """AC's app gets this account's messages and statuses on its webhook."""
        body = await self._call("POST", f"{waba_id}/subscribed_apps", token=token)
        if body.get("success") is not True:
            raise WhatsAppError("WhatsApp didn't switch on messages for this number. Try again.")

    async def register(self, phone_number_id: str, token: str, pin: str) -> None:
        """Register the number for the Cloud API. A number already registered is fine."""
        try:
            await self._call(
                "POST",
                f"{phone_number_id}/register",
                token=token,
                json={"messaging_product": "whatsapp", "pin": pin},
            )
        except WhatsAppError as error:
            if error.code not in (133005, 133010, 133016):
                raise

    async def send_text(self, phone_number_id: str, token: str, *, to: str, body: str) -> str:
        reply = await self._call(
            "POST",
            f"{phone_number_id}/messages",
            token=token,
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body[:TEXT_LIMIT]},
            },
        )
        return _wamid(reply)

    async def send_template(
        self,
        phone_number_id: str,
        token: str,
        *,
        to: str,
        name: str,
        language: str,
        values: list[str],
    ) -> str:
        template: dict[str, Any] = {"name": name, "language": {"code": language}}
        if values:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": value[:1024]} for value in values],
                }
            ]
        reply = await self._call(
            "POST",
            f"{phone_number_id}/messages",
            token=token,
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": template,
            },
        )
        return _wamid(reply)

    async def mark_read(self, phone_number_id: str, token: str, wamid: str) -> None:
        await self._call(
            "POST",
            f"{phone_number_id}/messages",
            token=token,
            json={"messaging_product": "whatsapp", "status": "read", "message_id": wamid},
        )

    async def templates(self, waba_id: str, token: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(20):
            body = await self._call(
                "GET",
                f"{waba_id}/message_templates",
                token=token,
                fields="id,name,language,status,category,components,quality_score,rejected_reason",
                limit=100,
                **({"after": after} if after else {}),
            )
            out.extend(dict(row) for row in body.get("data") or [] if isinstance(row, Mapping))
            page_info = body.get("paging")
            paging: Mapping[str, Any] = page_info if isinstance(page_info, Mapping) else {}
            cursor_info = paging.get("cursors")
            cursors: Mapping[str, Any] = cursor_info if isinstance(cursor_info, Mapping) else {}
            after = str(cursors["after"]) if paging.get("next") and cursors.get("after") else None
            if after is None:
                break
        return out

    async def create_template(
        self,
        waba_id: str,
        token: str,
        *,
        name: str,
        language: str,
        category: str,
        body: str,
        example: list[str],
    ) -> dict[str, Any]:
        component: dict[str, Any] = {"type": "BODY", "text": body}
        if example:
            component["example"] = {"body_text": [example]}
        return await self._call(
            "POST",
            f"{waba_id}/message_templates",
            token=token,
            json={
                "name": name,
                "language": language,
                "category": category,
                "components": [component],
            },
        )

    async def delete_template(self, waba_id: str, token: str, *, name: str) -> None:
        await self._call("DELETE", f"{waba_id}/message_templates", token=token, name=name)


def _wamid(reply: Mapping[str, Any]) -> str:
    messages = reply.get("messages") if isinstance(reply.get("messages"), list) else []
    first = messages[0] if messages and isinstance(messages[0], Mapping) else {}
    wamid = str(first.get("id") or "")
    if not wamid:
        raise WhatsAppError("WhatsApp didn't take the message. Try again.")
    return wamid[:200]


def refusal(error: Mapping[str, Any]) -> WhatsAppError:
    """A Cloud API error in words a seller or manager can act on."""
    raw = error.get("code")
    code = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
    if code in (190, 102):
        return WhatsAppError("WhatsApp ended this connection. Connect the number again.", code)
    if code == 131047:
        return WhatsAppError(
            "More than 24 hours since their last message: send an approved template.", code
        )
    if code in (131026, 131021):
        return WhatsAppError("This number can't get WhatsApp messages.", code)
    if code == 132001:
        return WhatsAppError("That template isn't approved in this language yet.", code)
    if code in (131048, 131056, 130429, 80007):
        return WhatsAppError("WhatsApp is limiting messages right now. Try again later.", code)
    if code in (10, 200, 3) or (code is not None and 200 <= code < 300):
        return WhatsAppError(
            "WhatsApp didn't give permission for this. Connect the number again.", code
        )
    return WhatsAppError("WhatsApp refused the message. Try again.", code)
