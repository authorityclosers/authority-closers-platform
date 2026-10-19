"""Messenger and Instagram for the Sales Xray CRM: AC's Messaging app and each Page.

An organisation connects its Facebook Pages (and the Instagram professional accounts
linked to them) with Facebook Login for Business on AC's "Sales Xray Messaging" app
(docs/product/lead-desk/instagram-messenger-app.md). Sales Xray keeps each Page's
token sealed to that Page and subscribes the Page to the app's webhook. Messages and
comments arrive on ``/v1/lead-desk/messaging/webhook``; replies go out through the
Page's ``/messages`` edge, for Messenger and Instagram alike.

Meta's rules, enforced here and in ``inbox``:

- A business may answer only someone who wrote first, within 24 hours of their last
  message. A person (never an automation) may answer up to 7 days later with the
  ``HUMAN_AGENT`` tag, once Meta has granted the app that feature and the organisation
  has turned it on.
- A comment gets at most one private reply, within 7 days of the comment. It does not
  open the 24-hour window; the person's answer does.

Nothing runs until the app's settings exist; ``config()`` is None until then.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from urllib.parse import urlencode

import httpx

from ac_platform.lead_desk.connectors import meta

Channel = Literal["messenger", "instagram"]
GRAPH: Final[str] = "https://graph.facebook.com"
WINDOW: Final[timedelta] = timedelta(hours=24)
HUMAN_AGENT_WINDOW: Final[timedelta] = timedelta(days=7)
COMMENT_REPLY_WINDOW: Final[timedelta] = timedelta(days=7)
TEXT_LIMIT: Final[dict[str, int]] = {"messenger": 2000, "instagram": 1000}
META_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9]{5,32}$")
SCOPED_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9]{5,40}$")
COMMENT_ID: Final[re.Pattern[str]] = re.compile(r"^[0-9_]{5,80}$")
ATTACHMENTS: Final[dict[str, str]] = {
    "image": "image",
    "audio": "audio",
    "video": "video",
    "file": "file",
    "sticker": "sticker",
    "share": "share",
    "story_mention": "story_mention",
    "ig_reel": "share",
    "reel": "share",
}
# Page webhook fields Sales Xray subscribes each Page to (POST /{page}/subscribed_apps).
PAGE_FIELDS: Final[tuple[str, ...]] = (
    "messages",
    "messaging_postbacks",
    "message_echoes",
    "message_deliveries",
    "message_reads",
    "feed",
)


class SocialError(ValueError):
    """Something about Messenger or Instagram failed; the message is safe to show."""

    def __init__(self, message: str, code: int | None = None, subcode: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode


@dataclass(frozen=True, slots=True)
class SocialConfig:
    app_id: str
    app_secret: str
    login_config_id: str
    verify_token: str
    token_key: bytes
    graph_version: str

    @property
    def graph(self) -> str:
        return f"{GRAPH}/{self.graph_version}"


def config(env: Mapping[str, str] | None = None) -> SocialConfig | None:
    """AC's Messaging app (the same app as WhatsApp) with its Messenger and Instagram
    login configuration, or None while any setting is missing (the channel stays off)."""
    env = os.environ if env is None else env
    names = (
        "AC_WHATSAPP_APP_ID",
        "AC_WHATSAPP_APP_SECRET",
        "AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
        "AC_MESSAGING_LOGIN_CONFIG_ID",
    )
    values = {name: (env.get(name) or "").strip() for name in names}
    if not all(values.values()):
        return None
    key = meta.token_key(env.get("AC_LEAD_DESK_TOKEN_KEY") or "")
    if key is None:
        return None
    version = (
        env.get("AC_WHATSAPP_GRAPH_VERSION") or env.get("AC_META_GRAPH_VERSION") or "v23.0"
    ).strip()
    return SocialConfig(
        app_id=values["AC_WHATSAPP_APP_ID"],
        app_secret=values["AC_WHATSAPP_APP_SECRET"],
        login_config_id=values["AC_MESSAGING_LOGIN_CONFIG_ID"],
        verify_token=values["AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN"],
        token_key=key,
        graph_version=version,
    )


def seal(cfg: SocialConfig, value: str, *, page_id: str) -> dict[str, str]:
    """A Page token, sealed to that Page and to this channel."""
    return meta.seal(cfg.token_key, value, page_id=f"social:{page_id}")


def unseal(cfg: SocialConfig, box: Mapping[str, Any], *, page_id: str) -> str:
    try:
        return meta.unseal(cfg.token_key, box, page_id=f"social:{page_id}")
    except meta.MetaError:
        raise SocialError("Connect this Page again in Settings → Integrations.") from None


def dialog_url(cfg: SocialConfig, *, redirect_uri: str, state: str) -> str:
    """Facebook Login for Business with the Messenger and Instagram configuration."""
    query = urlencode(
        {
            "client_id": cfg.app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "config_id": cfg.login_config_id,
            "response_type": "code",
            "override_default_response_type": "true",
        }
    )
    return f"https://www.facebook.com/{cfg.graph_version}/dialog/oauth?{query}"


# ----- the messaging window ---------------------------------------------------------------


def window_open(last_inbound: datetime | None, now: datetime) -> bool:
    return last_inbound is not None and now - last_inbound < WINDOW


def human_agent_open(last_inbound: datetime | None, now: datetime) -> bool:
    return last_inbound is not None and now - last_inbound < HUMAN_AGENT_WINDOW


# ----- webhook --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Inbound:
    """A message from a person to a Page or its Instagram account."""

    channel: Channel
    account_id: str  # the Page id (Messenger) or Instagram account id
    user_id: str  # PSID or IGSID
    mid: str
    kind: str
    body: str | None
    at: datetime


@dataclass(frozen=True, slots=True)
class Echo:
    """A message the business sent (from Sales Xray or Meta's own inbox)."""

    channel: Channel
    account_id: str
    user_id: str
    mid: str
    body: str | None
    at: datetime
    app_id: str | None


@dataclass(frozen=True, slots=True)
class Seen:
    """Messages to a person were delivered or read up to a time (or by message ids)."""

    channel: Channel
    account_id: str
    user_id: str
    status: Literal["delivered", "read"]
    until: datetime | None
    mids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment on the Page's post or the Instagram account's media."""

    channel: Channel
    account_id: str
    comment_id: str
    post_id: str | None
    user_id: str
    user_name: str | None
    text: str | None
    at: datetime


@dataclass(slots=True)
class Delivery:
    inbound: list[Inbound] = field(default_factory=list)
    echoes: list[Echo] = field(default_factory=list)
    seen: list[Seen] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    unsent: list[str] = field(default_factory=list)  # message ids the person took back


def _time(value: Any) -> datetime:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return datetime.now(UTC)
    try:
        # Messaging timestamps are milliseconds; some fields are seconds.
        return datetime.fromtimestamp(number / 1000 if number > 10**11 else number, UTC)
    except (OverflowError, OSError, ValueError):
        return datetime.now(UTC)


def _iso(value: Any) -> datetime:
    if isinstance(value, int | float):
        return _time(value)
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z").astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def _message(message: Mapping[str, Any], limit: int) -> tuple[str, str | None]:
    """A message's kind and words. Attachments are kept as their kind only."""
    text = message.get("text")
    if isinstance(text, str) and text.strip():
        return "text", text[:limit]
    attachments = message.get("attachments")
    if isinstance(attachments, list) and attachments and isinstance(attachments[0], Mapping):
        kind = ATTACHMENTS.get(str(attachments[0].get("type") or ""), "unsupported")
        return kind, None
    if isinstance(message.get("reply_to"), Mapping) and "story" in message["reply_to"]:
        return "story_reply", None
    return "unsupported", None


def parse(payload: Mapping[str, Any]) -> Delivery:
    """What one webhook delivery says, for Page (Messenger) and Instagram objects."""
    out = Delivery()
    kind_of = payload.get("object")
    if kind_of not in ("page", "instagram"):
        return out
    channel: Channel = "messenger" if kind_of == "page" else "instagram"
    limit = 4096
    for entry in payload.get("entry") or []:
        if not isinstance(entry, Mapping):
            continue
        account = str(entry.get("id") or "")
        if not META_ID.fullmatch(account):
            continue
        for event in entry.get("messaging") or []:
            if not isinstance(event, Mapping):
                continue
            sender = str((event.get("sender") or {}).get("id") or "")
            recipient = str((event.get("recipient") or {}).get("id") or "")
            at = _time(event.get("timestamp"))
            message = event.get("message")
            if isinstance(message, Mapping):
                mid = str(message.get("mid") or "")[:200]
                if not mid:
                    continue
                if message.get("is_deleted") is True:
                    out.unsent.append(mid)
                    continue
                if message.get("is_echo") is True:
                    if SCOPED_ID.fullmatch(recipient):
                        _, body = _message(message, limit)
                        app = message.get("app_id")
                        out.echoes.append(
                            Echo(
                                channel,
                                account,
                                recipient,
                                mid,
                                body,
                                at,
                                str(app) if app else None,
                            )
                        )
                    continue
                if not SCOPED_ID.fullmatch(sender) or sender == account:
                    continue
                kind, body = _message(message, limit)
                quick = message.get("quick_reply")
                if kind == "text" and isinstance(quick, Mapping) and not body:
                    body = str(quick.get("payload") or "")[:limit] or None
                out.inbound.append(Inbound(channel, account, sender, mid, kind, body, at))
                continue
            postback = event.get("postback")
            if isinstance(postback, Mapping) and SCOPED_ID.fullmatch(sender):
                mid = str(postback.get("mid") or f"postback:{sender}:{event.get('timestamp')}")
                title = str(postback.get("title") or postback.get("payload") or "")[:limit]
                out.inbound.append(
                    Inbound(channel, account, sender, mid[:200], "postback", title or None, at)
                )
                continue
            for name, status in (("delivery", "delivered"), ("read", "read")):
                part = event.get(name)
                if isinstance(part, Mapping) and SCOPED_ID.fullmatch(sender):
                    mids = tuple(str(m)[:200] for m in part.get("mids") or [] if m)
                    if part.get("mid"):
                        mids += (str(part["mid"])[:200],)
                    watermark = part.get("watermark")
                    out.seen.append(
                        Seen(
                            channel,
                            account,
                            sender,
                            "delivered" if status == "delivered" else "read",
                            _time(watermark) if watermark else None,
                            mids,
                        )
                    )
        for change in entry.get("changes") or []:
            if not isinstance(change, Mapping) or not isinstance(change.get("value"), Mapping):
                continue
            value = change["value"]
            found = _comment(channel, account, str(change.get("field") or ""), value)
            if found is not None:
                out.comments.append(found)
    return out


def _comment(channel: Channel, account: str, name: str, value: Mapping[str, Any]) -> Comment | None:
    sender = value.get("from") if isinstance(value.get("from"), Mapping) else {}
    user = str(sender.get("id") or "") if isinstance(sender, Mapping) else ""
    if channel == "messenger":
        if name != "feed" or value.get("item") != "comment" or value.get("verb") != "add":
            return None
        comment_id = str(value.get("comment_id") or "")
        if not COMMENT_ID.fullmatch(comment_id) or not SCOPED_ID.fullmatch(user) or user == account:
            return None
        return Comment(
            channel,
            account,
            comment_id,
            str(value.get("post_id") or "")[:100] or None,
            user,
            str(sender.get("name") or "")[:200] or None if isinstance(sender, Mapping) else None,
            str(value.get("message") or "")[:4096] or None,
            _iso(value.get("created_time")),
        )
    if name != "comments":
        return None
    comment_id = str(value.get("id") or "")
    if not COMMENT_ID.fullmatch(comment_id) or not SCOPED_ID.fullmatch(user) or user == account:
        return None
    media = value.get("media") if isinstance(value.get("media"), Mapping) else {}
    username = str(sender.get("username") or "")[:100] if isinstance(sender, Mapping) else ""
    return Comment(
        channel,
        account,
        comment_id,
        str(media.get("id") or "")[:100] or None if isinstance(media, Mapping) else None,
        user,
        f"@{username}" if username else None,
        str(value.get("text") or "")[:4096] or None,
        datetime.now(UTC),
    )


# ----- comment rules ------------------------------------------------------------------------


def matches(rule_keywords: list[str], text: str | None) -> bool:
    """A comment matches a rule when it has one of its keywords as a word (any case)."""
    if not text:
        return False
    words = set(re.findall(r"[\w']+", text.casefold()))
    folded = text.casefold()
    for keyword in rule_keywords:
        key = keyword.strip().casefold()
        if not key:
            continue
        if (" " in key and key in folded) or key in words:
            return True
    return False


def first_name(name: str | None) -> str:
    words = (name or "").strip().lstrip("@").split()
    return words[0][:60] if words else "there"


def fill(text: str, name: str | None) -> str:
    return text.replace("{first_name}", first_name(name))


# ----- Graph API ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Page:
    page_id: str
    name: str
    token: str
    ig_user_id: str | None
    ig_username: str | None


class Graph:
    """The Messenger and Instagram calls Sales Xray makes. Errors become plain words."""

    def __init__(
        self, cfg: SocialConfig, client: httpx.AsyncClient | None = None, *, timeout: float = 15
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
            raise SocialError("Meta didn't answer. Try again in a minute.") from None
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

    async def user_token(self, *, code: str, redirect_uri: str) -> str:
        """The login's code for a long-lived user token (its Page tokens then last)."""
        body = await self._call(
            "GET",
            "oauth/access_token",
            token=None,
            client_id=self.cfg.app_id,
            client_secret=self.cfg.app_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
        short = str(body.get("access_token") or "")
        if not short:
            raise SocialError("Facebook didn't finish connecting. Start again.")
        long_lived = await self._call(
            "GET",
            "oauth/access_token",
            token=None,
            grant_type="fb_exchange_token",
            client_id=self.cfg.app_id,
            client_secret=self.cfg.app_secret,
            fb_exchange_token=short,
        )
        return str(long_lived.get("access_token") or short)

    async def pages(self, user_token: str) -> list[Page]:
        """The Pages the person shared, with each Page's linked Instagram account."""
        out: list[Page] = []
        after: str | None = None
        for _ in range(10):
            body = await self._call(
                "GET",
                "me/accounts",
                token=user_token,
                fields="id,name,access_token,instagram_business_account{id,username}",
                limit=100,
                **({"after": after} if after else {}),
            )
            for row in body.get("data") or []:
                if not isinstance(row, Mapping):
                    continue
                page_id, token = str(row.get("id") or ""), str(row.get("access_token") or "")
                if not META_ID.fullmatch(page_id) or not token:
                    continue
                ig = row.get("instagram_business_account")
                ig_id = str(ig.get("id") or "") if isinstance(ig, Mapping) else ""
                out.append(
                    Page(
                        page_id,
                        str(row.get("name") or page_id)[:200],
                        token,
                        ig_id if META_ID.fullmatch(ig_id) else None,
                        str(ig.get("username") or "")[:100] or None
                        if isinstance(ig, Mapping)
                        else None,
                    )
                )
            page_info = body.get("paging")
            paging: Mapping[str, Any] = page_info if isinstance(page_info, Mapping) else {}
            cursor_info = paging.get("cursors")
            cursors: Mapping[str, Any] = cursor_info if isinstance(cursor_info, Mapping) else {}
            after = str(cursors["after"]) if paging.get("next") and cursors.get("after") else None
            if after is None:
                break
        return out[:50]

    async def subscribe(self, page_id: str, page_token: str) -> None:
        """AC's Messaging app gets this Page's (and its Instagram account's) messages."""
        body = await self._call(
            "POST",
            f"{page_id}/subscribed_apps",
            token=page_token,
            subscribed_fields=",".join(PAGE_FIELDS),
        )
        if body.get("success") not in (True, "true"):
            raise SocialError("Facebook didn't switch on messages for this Page. Try again.")

    async def profile(self, channel: str, user_id: str, page_token: str) -> str | None:
        """The person's name (Messenger) or @username (Instagram), if Meta shares it."""
        try:
            if channel == "messenger":
                body = await self._call(
                    "GET", user_id, token=page_token, fields="first_name,last_name"
                )
                name = " ".join(
                    str(body.get(part) or "").strip() for part in ("first_name", "last_name")
                ).strip()
                return name[:200] or None
            body = await self._call("GET", user_id, token=page_token, fields="name,username")
            username = str(body.get("username") or "").strip()
            name = str(body.get("name") or "").strip()
            return (name or (f"@{username}" if username else ""))[:200] or None
        except SocialError:
            return None

    async def send(
        self,
        page_id: str,
        page_token: str,
        *,
        user_id: str,
        text: str,
        channel: str,
        human_agent: bool = False,
    ) -> str:
        """A message to someone who wrote to the Page or its Instagram account."""
        body: dict[str, Any] = {
            "recipient": {"id": user_id},
            "message": {"text": text[: TEXT_LIMIT[channel]]},
        }
        if human_agent:
            body.update(messaging_type="MESSAGE_TAG", tag="HUMAN_AGENT")
        else:
            body["messaging_type"] = "RESPONSE"
        reply = await self._call("POST", f"{page_id}/messages", token=page_token, json=body)
        return _mid(reply)

    async def private_reply(
        self, page_id: str, page_token: str, *, comment_id: str, text: str, channel: str
    ) -> tuple[str, str]:
        """One private message to the person who commented; their messaging id and the
        message id come back."""
        reply = await self._call(
            "POST",
            f"{page_id}/messages",
            token=page_token,
            json={
                "recipient": {"comment_id": comment_id},
                "message": {"text": text[: TEXT_LIMIT[channel]]},
            },
        )
        recipient = str(reply.get("recipient_id") or "")
        return _mid(reply), recipient if SCOPED_ID.fullmatch(recipient) else ""

    async def public_reply(
        self, page_token: str, *, comment_id: str, text: str, channel: str
    ) -> str:
        """A short public answer under the comment ("We've sent you a message")."""
        edge = "comments" if channel == "messenger" else "replies"
        reply = await self._call(
            "POST", f"{comment_id}/{edge}", token=page_token, json={"message": text[:1000]}
        )
        return str(reply.get("id") or "")[:100]


def _mid(reply: Mapping[str, Any]) -> str:
    mid = str(reply.get("message_id") or "")
    if not mid:
        raise SocialError("Meta didn't take the message. Try again.")
    return mid[:200]


def refusal(error: Mapping[str, Any]) -> SocialError:
    """A Messenger or Instagram error in words a seller or manager can act on."""
    raw, sub = error.get("code"), error.get("error_subcode")
    code = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
    subcode = sub if isinstance(sub, int) and not isinstance(sub, bool) else None
    if code in (190, 102):
        return SocialError("Meta ended this connection. Connect the Page again.", code, subcode)
    if subcode == 2018278 or (code == 10 and subcode in (2018065, 2534022)):
        return SocialError(
            "It's more than 24 hours since their last message, so Meta won't deliver this.",
            code,
            subcode,
        )
    if code in (551, 1545041) or subcode == 1545041:
        return SocialError("This person can't get messages from you right now.", code, subcode)
    if code in (4, 17, 32, 613) or (code is not None and 80000 <= code < 80100):
        return SocialError("Meta is limiting messages right now. Try again later.", code, subcode)
    if code in (10, 200, 3, 230) or (code is not None and 200 <= code < 300):
        return SocialError(
            "Meta didn't give permission for this. Connect the Page again.", code, subcode
        )
    return SocialError("Meta refused the message. Try again.", code, subcode)
