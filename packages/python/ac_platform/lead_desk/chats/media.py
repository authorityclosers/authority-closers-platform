"""Photos, voice notes, videos and files in Chats, shown through Sales Xray.

Meta keeps the file; Sales Xray keeps only what a message already had (WhatsApp's media
id, Messenger's or Instagram's message id). When someone with the lead on their desk
opens a chat, the file is fetched from Meta with the organisation's token and streamed
straight to their browser: nothing is written to disk or to the database, no link to
Meta's copy reaches the page, and nothing (AI included) reads the file on the way.

- WhatsApp: ``GET /{media-id}`` gives a short-lived link that needs the number's token.
- Messenger and Instagram: ``GET /{message-id}?fields=attachments`` gives Meta's links.
Only Meta's own file hosts are fetched, at most ``MAX_BYTES``, and a link that moved
elsewhere is not followed.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select

from ac_platform.lead_desk.models import (
    LeadSocialAccount,
    LeadSocialMessage,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.lead_desk.social import graph
from ac_platform.lead_desk.store import LeadDesk
from ac_platform.lead_desk.whatsapp import cloud

log = structlog.get_logger(__name__)

MAX_BYTES: Final[int] = 32 * 1024 * 1024
MAX_HOPS: Final[int] = 3
CHUNK: Final[int] = 64 * 1024
TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(20.0, read=60.0)
# Where Meta keeps message files (WhatsApp, Messenger and Instagram).
META_HOSTS: Final[tuple[str, ...]] = (
    "fbcdn.net",
    "fbsbx.com",
    "facebook.com",
    "cdninstagram.com",
    "instagram.com",
    "whatsapp.net",
)
MEDIA_KINDS: Final[dict[str, frozenset[str]]] = {
    "whatsapp": frozenset({"image", "audio", "video", "document", "sticker"}),
    "messenger": frozenset({"image", "audio", "video", "file", "sticker"}),
    "instagram": frozenset({"image", "audio", "video", "file", "sticker"}),
}
# Shown in the page; anything else is offered as a download.
INLINE: Final[tuple[str, ...]] = ("image/", "audio/", "video/")
SAFE_TYPE: Final[re.Pattern[str]] = re.compile(r"^[a-z]+/[a-z0-9.+-]{1,80}$")
GONE_WORDS: Final[str] = "This file isn't available from Meta any more."
RECONNECT_WORDS: Final[str] = "Connect this account again to see its files."
# Tests put a fake Meta here; the server always talks to Meta itself.
TRANSPORT: httpx.AsyncBaseTransport | None = None
FAILED_WORDS: Final[str] = "Meta didn't send this file. Try again in a minute."


class MediaError(Exception):
    """Why a file can't be shown, in words a person can act on."""

    def __init__(self, status: int, words: str) -> None:
        super().__init__(words)
        self.status = status


@dataclass(frozen=True, slots=True)
class Source:
    url: str
    token: str | None  # WhatsApp's links need the number's token; Meta's CDN links don't
    mime: str
    name: str | None
    size: int | None
    kind: str


def meta_host(url: str) -> bool:
    """An https link on one of Meta's file hosts (no other address is ever fetched)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and parts.port in (None, 443)
        and not parts.username
        and any(host == suffix or host.endswith(f".{suffix}") for suffix in META_HOSTS)
    )


def content_type(mime: str | None) -> str:
    """A type the browser may use; an unknown or active one (HTML, SVG) is a download."""
    value = (mime or "").split(";")[0].strip().lower()
    if not SAFE_TYPE.fullmatch(value) or value in {"image/svg+xml", "text/html"}:
        return "application/octet-stream"
    return value


def disposition(mime: str, name: str | None, kind: str) -> str:
    inline = mime.startswith(INLINE)
    base = re.sub(r"[^\w .()-]+", "_", (name or "").strip())[:120].strip(" .")
    if not base:
        base = {"image": "photo", "audio": "voice-note", "video": "video"}.get(kind, "file")
    ascii_name = base.encode("ascii", "ignore").decode() or "file"
    return (
        f'{"inline" if inline else "attachment"}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(base)}"
    )


def client() -> httpx.AsyncClient:
    """A client for one request to Meta; redirects are checked by hand."""
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, transport=TRANSPORT)


def _int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


async def _graph_get(
    client: httpx.AsyncClient, base: str, path: str, token: str, **params: Any
) -> dict[str, Any]:
    try:
        response = await client.get(
            f"{base}/{path}",
            params=params or None,
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError:
        raise MediaError(502, FAILED_WORDS) from None
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, Mapping) and _int(error.get("code")) == 190:
        raise MediaError(409, RECONNECT_WORDS)  # the organisation's token stopped working
    if response.status_code in (400, 404) or isinstance(error, Mapping):
        # Meta forgets a file after a while (WhatsApp: 30 days) or once it was taken back.
        raise MediaError(410, GONE_WORDS)
    if response.status_code >= 400 or not isinstance(body, dict):
        raise MediaError(502, FAILED_WORDS)
    return body


async def _whatsapp(desk: LeadDesk, message_id: UUID, client: httpx.AsyncClient) -> Source:
    message = await desk.db.scalar(
        select(LeadWhatsAppMessage).where(
            LeadWhatsAppMessage.id == message_id,
            LeadWhatsAppMessage.tenant_id == desk.tenant_id,
            LeadWhatsAppMessage.erased_at.is_(None),
        )
    )
    if message is None or message.lead_id is None:
        raise MediaError(404, "This file isn't in a chat on your desk.")
    await desk._lead(message.lead_id)
    media = message.media or {}
    media_id = str(media.get("id") or "")
    if message.kind not in MEDIA_KINDS["whatsapp"] or not cloud.META_ID.fullmatch(media_id):
        raise MediaError(404, "This message has no file.")
    cfg = cloud.config()
    number = await desk.db.get(LeadWhatsAppNumber, message.number_id)
    if cfg is None or number is None or number.tenant_id != desk.tenant_id:
        raise MediaError(409, "Connect this WhatsApp number again to see its files.")
    try:
        token = cloud.unseal(
            cfg, number.token, phone_number_id=number.phone_number_id, what="token"
        )
    except cloud.WhatsAppError:
        raise MediaError(409, "Connect this WhatsApp number again to see its files.") from None
    body = await _graph_get(client, cfg.graph, media_id, token)
    url = str(body.get("url") or "")
    if not meta_host(url):
        raise MediaError(502, FAILED_WORDS)
    return Source(
        url=url,
        token=token,
        mime=content_type(str(body.get("mime_type") or media.get("mime_type") or "")),
        name=str(media.get("filename") or "") or None,
        size=_int(body.get("file_size")),
        kind=message.kind,
    )


def _part(item: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    found = item.get(key)
    return found if isinstance(found, Mapping) else {}


def _attachment_url(item: Mapping[str, Any], preview: bool) -> str:
    image, video, audio, payload = (
        _part(item, key) for key in ("image_data", "video_data", "audio_data", "payload")
    )
    choices = [
        image.get("preview_url") if preview else None,
        image.get("url"),
        video.get("url"),
        audio.get("url"),
        item.get("file_url"),
        payload.get("url"),
        item.get("url"),
    ]
    return next((str(found) for found in choices if found), "")


async def _social(
    desk: LeadDesk,
    channel: str,
    message_id: UUID,
    part: int,
    preview: bool,
    client: httpx.AsyncClient,
) -> Source:
    message = await desk.db.scalar(
        select(LeadSocialMessage).where(
            LeadSocialMessage.id == message_id,
            LeadSocialMessage.tenant_id == desk.tenant_id,
            LeadSocialMessage.channel == channel,
            LeadSocialMessage.erased_at.is_(None),
        )
    )
    if message is None or message.lead_id is None:
        raise MediaError(404, "This file isn't in a chat on your desk.")
    await desk._lead(message.lead_id)
    if message.kind not in MEDIA_KINDS[channel] or not message.mid:
        raise MediaError(404, "This message has no file.")
    cfg = graph.config()
    account = await desk.db.get(LeadSocialAccount, message.account_id)
    if cfg is None or account is None or account.tenant_id != desk.tenant_id:
        raise MediaError(409, "Connect this Page again to see its files.")
    if account.status != "active":
        raise MediaError(409, "Connect this Page again to see its files.")
    try:
        token = graph.unseal(cfg, account.token, page_id=account.page_id)
    except graph.SocialError:
        raise MediaError(409, "Connect this Page again to see its files.") from None
    body = await _graph_get(
        client, cfg.graph, quote(message.mid, safe=""), token, fields="attachments"
    )
    found = body.get("attachments")
    items = found.get("data") if isinstance(found, Mapping) else None
    if not isinstance(items, list) or not 0 <= part < len(items):
        raise MediaError(410, GONE_WORDS)
    item = items[part] if isinstance(items[part], Mapping) else {}
    url = _attachment_url(item, preview)
    if not meta_host(url):
        raise MediaError(410, GONE_WORDS)
    return Source(
        url=url,
        token=None,
        mime=content_type(str(item.get("mime_type") or "")),
        name=str(item.get("name") or "") or None,
        size=_int(item.get("size")),
        kind=message.kind,
    )


async def find(
    desk: LeadDesk,
    channel: str,
    message_id: UUID,
    *,
    part: int = 0,
    preview: bool = False,
    client: httpx.AsyncClient,
) -> Source:
    """Where Meta keeps one message's file, for someone who may see the lead."""
    if channel == "whatsapp":
        return await _whatsapp(desk, message_id, client)
    if channel in ("messenger", "instagram"):
        return await _social(desk, channel, message_id, part, preview, client)
    raise MediaError(404, "Pick WhatsApp, Messenger or Instagram.")


@dataclass(slots=True)
class Download:
    """Meta's answer, open for streaming; ``chunks`` closes it when done."""

    status: int
    headers: dict[str, str]
    response: httpx.Response
    client: httpx.AsyncClient

    async def chunks(self) -> AsyncIterator[bytes]:
        sent = 0
        try:
            async for chunk in self.response.aiter_bytes(CHUNK):
                sent += len(chunk)
                if sent > MAX_BYTES:
                    break
                yield chunk
        finally:
            await self.close()

    async def close(self) -> None:
        await self.response.aclose()
        await self.client.aclose()


async def download(source: Source, *, byte_range: str | None) -> Download:
    """Open Meta's file for streaming. A browser's Range (seeking in a voice note or a
    video) is passed on. Each hop must stay on Meta's file hosts; the token only goes
    to the first one."""
    owner = client()
    url = source.url
    try:
        for hop in range(MAX_HOPS + 1):
            if not meta_host(url):
                raise MediaError(502, FAILED_WORDS)
            headers = {"Accept": "*/*"}
            if hop == 0 and source.token:
                headers["Authorization"] = f"Bearer {source.token}"
            if byte_range and re.fullmatch(r"bytes=\d{0,12}-\d{0,12}", byte_range):
                headers["Range"] = byte_range
            try:
                response = await owner.send(
                    owner.build_request("GET", url, headers=headers), stream=True
                )
            except httpx.HTTPError:
                raise MediaError(502, FAILED_WORDS) from None
            if response.is_redirect and hop < MAX_HOPS:
                url = str(response.headers.get("location") or "")
                url = str(httpx.URL(source.url).join(url)) if url else ""
                await response.aclose()
                continue
            if response.status_code in (404, 410):
                await response.aclose()
                raise MediaError(410, GONE_WORDS)
            if response.status_code not in (200, 206):
                await response.aclose()
                raise MediaError(502, FAILED_WORDS)
            length = _int(response.headers.get("content-length"))
            if length is not None and length > MAX_BYTES:
                await response.aclose()
                raise MediaError(413, "This file is too large to show here.")
            mime = (
                source.mime
                if source.mime != "application/octet-stream"
                else content_type(response.headers.get("content-type"))
            )
            out = {
                "Content-Type": mime,
                "Content-Disposition": disposition(mime, source.name, source.kind),
                "Cache-Control": "private, max-age=300",
                "Vary": "Cookie",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "Accept-Ranges": "bytes",
            }
            if length is not None:
                out["Content-Length"] = str(length)
            if response.status_code == 206 and response.headers.get("content-range"):
                out["Content-Range"] = str(response.headers["content-range"])
            log.info(
                "lead_desk_chat_media",
                kind=source.kind,
                status=response.status_code,
                bytes=length,
            )
            return Download(response.status_code, out, response, owner)
        raise MediaError(502, FAILED_WORDS)
    except BaseException:
        await owner.aclose()
        raise


@dataclass(frozen=True, slots=True)
class Info:
    kind: str
    mime: str
    name: str | None
    size: int | None


def info(source: Source) -> Info:
    return Info(kind=source.kind, mime=source.mime, name=source.name, size=source.size)
