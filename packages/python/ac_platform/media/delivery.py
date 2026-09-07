"""Fail-closed application media delivery for a reviewed local/test seam.

The storage and signing foundations intentionally do not expose a public
object URL.  This module is the next, still provider-neutral boundary: it
verifies the application-issued token, delegates authorization to an injected
server-owned grant checker, streams one bounded object range, and rewrites
private HLS references with exact child tokens.  It is an explicit adapter
that a future deployment can review and compose; the shipped application does
not install it by default and the S3/MinIO transport remains unavailable.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Literal, Protocol, cast
from urllib.parse import quote

from ac_platform.media.contracts import (
    EphemeralMediaUrl,
    MediaAssetId,
    MediaAssetVersion,
    MediaVersionId,
    create_media_authorization_context,
)
from ac_platform.media.errors import (
    MediaForbidden,
    MediaProcessingError,
    MediaRangeError,
    MediaStorageUnavailable,
)
from ac_platform.media.policy import MediaCorsPolicy, SignedMediaDeliveryPort, SignedMediaUrl
from ac_platform.media.processing import (
    inspect_hls_playlist_inventory,
    resolve_hls_child_object_key,
)
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import PrivateObjectStorage, StoredObjectMetadata

_TOKEN_TYPES = frozenset({"read", "playback"})
_HLS_CONTENT_TYPES = frozenset(
    {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
    }
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_HLS_URI_ATTRIBUTE = re.compile(r'\bURI\s*=\s*"([^"]+)"', re.IGNORECASE)
_MAX_OBJECT_KEY_LENGTH = 512
# Keep delivery validation aligned with the bounded HLS inspector.  The
# inspector intentionally caps each playlist at one MiB so a malformed or
# provider-side changing manifest cannot make the delivery seam allocate more.
_MAX_MANIFEST_BYTES = 1 * 1024 * 1024
_MAX_HLS_HEAD_OPERATIONS = 8192
_MAX_CHUNK_SIZE = 16 * 1024 * 1024
_DEFAULT_CHUNK_SIZE = 1024 * 1024
_DEFAULT_MAX_OBJECT_BYTES = 8 * 1024 * 1024 * 1024
_OPAQUE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

MediaTokenType = Literal["read", "playback"]


class MediaDeliveryAuthorizer(Protocol):
    """Port for the server-owned session/grant authorization decision."""

    def authorize(self, claims: Mapping[str, object], token_type: MediaTokenType) -> bool:
        """Return true only when the persisted grant remains usable."""

        ...


@dataclass(frozen=True, slots=True)
class MediaDeliveryResult:
    """HTTP-neutral result consumed by the dedicated delivery route."""

    status_code: int
    content_type: str
    content_length: int
    headers: Mapping[str, str]
    body: Iterable[bytes] | None = None

    def __post_init__(self) -> None:
        if self.status_code not in {200, 206, 204, 416}:
            raise ValueError("media delivery result status is unsupported")
        if not isinstance(self.content_type, str) or not self.content_type.strip():
            raise ValueError("media delivery result content type is required")
        if (
            isinstance(self.content_length, bool)
            or not isinstance(self.content_length, int)
            or self.content_length < 0
        ):
            raise ValueError("media delivery result content length is invalid")
        if not isinstance(self.headers, Mapping):
            raise TypeError("media delivery result headers must be a mapping")
        normalized = {
            str(name): str(value) for name, value in self.headers.items() if str(name).strip()
        }
        object.__setattr__(self, "headers", MappingProxyType(normalized))


def _claim_text(claims: Mapping[str, object], name: str, *, maximum: int = 512) -> str:
    value = claims.get(name)
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        or any(character.isspace() for character in value)
    ):
        raise MediaForbidden("The media authorization token is invalid.")
    return value


def _claim_timestamp(claims: Mapping[str, object], name: str) -> datetime:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise MediaForbidden("The media authorization token is invalid.")
    try:
        timestamp = datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise MediaForbidden("The media authorization token is invalid.") from error
    return timestamp


def _object_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_OBJECT_KEY_LENGTH
        or value.startswith("/")
        or "\\" in value
        or ".." in value
        or any(character.isspace() for character in value)
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise MediaForbidden("The media object is outside the signed scope.")
    return value


def _canonical_version_prefix(
    object_key: str,
    *,
    tenant_id: str,
    asset_id: str,
    version_id: str,
) -> str:
    """Return the structured immutable-version prefix for one object key.

    A substring such as ``/asset/version/`` is not sufficient: a misleading
    path can place the same marker in a different tenant, purpose, or segment
    position.  The storage contract uses exactly six canonical components
    before the immutable object's child path.
    """

    components = object_key.split("/")
    if (
        len(components) < 7
        or components[0] != "tenants"
        or components[1] != tenant_id
        or components[2] != "media"
        or components[4] != asset_id
        or components[5] != version_id
        or any(_OPAQUE_SEGMENT.fullmatch(component) is None for component in components[:6])
        or any(
            not component
            or component in {".", ".."}
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in component)
            or any(character.isspace() for character in component)
            for component in components[6:]
        )
    ):
        raise MediaForbidden("The media object is outside the signed scope.")
    return "/".join(components[:6])


def _media_content_type(metadata: StoredObjectMetadata) -> str:
    content_type = getattr(metadata, "content_type", None)
    if (
        not isinstance(content_type, str)
        or not content_type.strip()
        or len(content_type) > 128
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in content_type)
    ):
        raise MediaStorageUnavailable("The private media adapter returned an invalid MIME.")
    normalized = content_type.lower().split(";", 1)[0].strip()
    if "/" not in normalized or normalized.startswith("/") or normalized.endswith("/"):
        raise MediaStorageUnavailable("The private media adapter returned an invalid MIME.")
    return normalized


class PrivateMediaDeliveryHandler:
    """Serve application-signed private media without exposing provider URLs."""

    def __init__(
        self,
        *,
        storage: PrivateObjectStorage,
        signer: MediaSigner,
        delivery_port: SignedMediaDeliveryPort,
        cors_policy: MediaCorsPolicy,
        authorizer: Callable[[Mapping[str, object], MediaTokenType], bool]
        | MediaDeliveryAuthorizer,
        max_object_bytes: int = _DEFAULT_MAX_OBJECT_BYTES,
        max_manifest_bytes: int = _MAX_MANIFEST_BYTES,
        max_hls_head_operations: int = _MAX_HLS_HEAD_OPERATIONS,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        clock_skew: timedelta = timedelta(minutes=5),
    ) -> None:
        if not isinstance(storage, PrivateObjectStorage):
            raise TypeError("media delivery requires a private object storage adapter")
        if not isinstance(signer, MediaSigner):
            raise TypeError("media delivery requires a MediaSigner")
        if not isinstance(delivery_port, SignedMediaDeliveryPort):
            raise TypeError("media delivery requires a signed delivery port")
        if delivery_port.signer is not signer:
            raise ValueError("media delivery signer must match the signed delivery port")
        if not isinstance(cors_policy, MediaCorsPolicy):
            raise TypeError("media delivery requires an exact-origin CORS policy")
        if not callable(authorizer) and not callable(getattr(authorizer, "authorize", None)):
            raise TypeError("media delivery requires an explicit grant authorizer")
        for value, name, maximum in (
            (max_object_bytes, "max_object_bytes", _DEFAULT_MAX_OBJECT_BYTES),
            (max_manifest_bytes, "max_manifest_bytes", _MAX_MANIFEST_BYTES),
            (max_hls_head_operations, "max_hls_head_operations", _MAX_HLS_HEAD_OPERATIONS),
            (chunk_size, "chunk_size", _MAX_CHUNK_SIZE),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value > maximum
            ):
                raise ValueError(f"{name} is outside the bounded delivery limit")
        if clock_skew < timedelta(0) or clock_skew > timedelta(minutes=15):
            raise ValueError("clock_skew is outside the bounded delivery limit")
        if max_object_bytes > delivery_port.range_policy.max_bytes:
            raise ValueError("max_object_bytes exceeds the signed range policy")
        self.storage = storage
        self.signer = signer
        self.delivery_port = delivery_port
        self.cors_policy = cors_policy
        self.authorizer = authorizer
        self.max_object_bytes = max_object_bytes
        self.max_manifest_bytes = max_manifest_bytes
        self.max_hls_head_operations = max_hls_head_operations
        self.chunk_size = chunk_size
        self.clock_skew = clock_skew

    def serve(
        self,
        *,
        token: str,
        token_type: str,
        object_key: str,
        method: str = "GET",
        origin: str | None = None,
        range_header: str | None = None,
        now: datetime | None = None,
    ) -> MediaDeliveryResult:
        """Validate and stream one signed object or bounded HLS playlist.

        ``OPTIONS`` is intentionally handled by the HTTP installer because a
        preflight has no bearer token. All object methods require a token and
        the injected persisted-grant decision.
        """

        normalized_method = method.upper()
        if normalized_method not in {"GET", "HEAD"}:
            raise ValueError("media delivery method is unsupported")
        if token_type not in _TOKEN_TYPES:
            raise MediaForbidden("The media delivery kind is invalid.")
        normalized_key = _object_key(object_key)
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("media delivery verification time must be timezone-aware")
        current = current.astimezone(UTC)
        claims, media_version, supports_range, version_prefix = self._verify_token(
            token=token,
            token_type=token_type,
            object_key=normalized_key,
            now=current,
        )
        self._authorize(claims, cast(MediaTokenType, token_type))
        try:
            metadata = self.storage.head(normalized_key)
        except MediaStorageUnavailable:
            raise
        except Exception as error:
            raise MediaStorageUnavailable(
                "The private media object could not be inspected."
            ) from error
        if metadata is None:
            raise MediaStorageUnavailable("The private media object is unavailable.")
        self._verify_metadata(metadata, normalized_key)
        content_type = _media_content_type(metadata)
        cors_headers = self.cors_policy.response_headers(origin)
        base_headers = {
            **cors_headers,
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{metadata.checksum_sha256.lower()}"',
            "Accept-Ranges": "bytes"
            if supports_range and content_type not in _HLS_CONTENT_TYPES
            else "none",
        }
        if content_type in _HLS_CONTENT_TYPES or normalized_key.lower().endswith(".m3u8"):
            return self._serve_manifest(
                metadata=metadata,
                content_type=content_type,
                claims=claims,
                media_version=media_version,
                version_prefix=version_prefix,
                token_type=token_type,
                object_key=normalized_key,
                method=normalized_method,
                range_header=range_header,
                now=current,
                headers=base_headers,
            )
        return self._serve_object(
            metadata=metadata,
            content_type=content_type,
            supports_range=supports_range,
            method=normalized_method,
            range_header=range_header,
            headers=base_headers,
        )

    def _verify_token(
        self,
        *,
        token: str,
        token_type: str,
        object_key: str,
        now: datetime,
    ) -> tuple[Mapping[str, object], MediaAssetVersion, bool, str]:
        try:
            claims = self.signer.verify(token, now=now, token_type=token_type)
        except MediaForbidden:
            raise
        tenant_id = _claim_text(claims, "tenant_id")
        person_id = _claim_text(claims, "person_id")
        session_id = _claim_text(claims, "session_id")
        _claim_text(claims, "activity_id")
        _claim_text(claims, "activity_version")
        asset_id = _claim_text(claims, "asset_id")
        version_id = _claim_text(claims, "version_id")
        claim_key = _claim_text(claims, "key", maximum=_MAX_OBJECT_KEY_LENGTH)
        if claim_key != object_key:
            raise MediaForbidden("The media object is outside the signed scope.")
        issued_at = _claim_timestamp(claims, "iat")
        expires_at = _claim_timestamp(claims, "exp")
        if issued_at > now + self.clock_skew or expires_at <= now:
            raise MediaForbidden("The media authorization token is invalid or expired.")
        lifetime = expires_at - issued_at
        if lifetime <= timedelta(0) or lifetime > self.delivery_port.playback_ttl:
            raise MediaForbidden("The media authorization token lifetime is invalid.")
        try:
            media_version = MediaAssetVersion(MediaAssetId(asset_id), MediaVersionId(version_id))
            authorization = create_media_authorization_context(
                tenant_id=tenant_id,
                person_id=person_id,
                session_id=session_id,
            )
        except (TypeError, ValueError) as error:
            raise MediaForbidden("The media authorization token is invalid.") from error
        version_prefix = _canonical_version_prefix(
            object_key,
            tenant_id=tenant_id,
            asset_id=asset_id,
            version_id=version_id,
        )
        claimed_supports_range = claims.get("supports_range")
        if (
            not isinstance(claimed_supports_range, bool)
            or claimed_supports_range
            and not self.delivery_port.range_policy.supports_range
        ):
            raise MediaForbidden("The media authorization token range policy is invalid.")
        expected_url = (
            f"{self.delivery_port.delivery_origin}/v1/media/{token_type}/"
            f"{quote(object_key, safe='')}?token={quote(token, safe='')}"
        )
        signed = SignedMediaUrl(
            url=EphemeralMediaUrl(expected_url),
            expires_at=expires_at,
            media_version=media_version,
            kind=token_type,
            supports_range=claimed_supports_range,
            token=token,
        )
        try:
            self.delivery_port.verify(
                signed,
                now=now,
                authorization=authorization,
                media_version=media_version,
            )
        except MediaForbidden:
            raise
        except Exception as error:
            raise MediaForbidden("The media authorization token is invalid.") from error
        return claims, media_version, claimed_supports_range, version_prefix

    def _authorize(self, claims: Mapping[str, object], token_type: MediaTokenType) -> None:
        try:
            allowed = (
                self.authorizer.authorize(claims, token_type)
                if not callable(self.authorizer)
                else self.authorizer(claims, token_type)
            )
        except Exception as error:
            raise MediaForbidden("The media grant could not be authorized.") from error
        if allowed is not True:
            raise MediaForbidden("The media grant is no longer authorized.")

    @staticmethod
    def _verify_metadata(metadata: StoredObjectMetadata, object_key: str) -> None:
        storage_version_id = getattr(metadata, "storage_version_id", None)
        if (
            not isinstance(metadata, StoredObjectMetadata)
            or metadata.object_key != object_key
            or isinstance(metadata.content_length, bool)
            or not isinstance(metadata.content_length, int)
            or metadata.content_length <= 0
            or not isinstance(metadata.checksum_sha256, str)
            or _SHA256.fullmatch(metadata.checksum_sha256) is None
            or not isinstance(storage_version_id, str)
            or not storage_version_id
            or len(storage_version_id) > 512
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in storage_version_id
            )
            or any(character.isspace() for character in storage_version_id)
        ):
            raise MediaStorageUnavailable("The private media adapter returned unverified metadata.")

    @staticmethod
    def _metadata_identity(metadata: StoredObjectMetadata) -> tuple[str, str, int, str, str]:
        """Snapshot the object identity used across a streamed response."""

        return (
            metadata.object_key,
            _media_content_type(metadata),
            metadata.content_length,
            metadata.checksum_sha256.lower(),
            metadata.storage_version_id,
        )

    def _verify_stream_identity(
        self,
        object_key: str,
        *,
        expected_identity: tuple[str, str, int, str, str],
    ) -> None:
        """Reject an object that changed between head and range streaming."""

        try:
            current = self.storage.head(object_key)
        except Exception as error:
            raise MediaStorageUnavailable(
                "The private media object could not be revalidated after streaming."
            ) from error
        if current is None:
            raise MediaStorageUnavailable("The private media object changed while streaming.")
        self._verify_metadata(current, object_key)
        if self._metadata_identity(current) != expected_identity:
            raise MediaStorageUnavailable("The private media object changed while streaming.")

    def _serve_object(
        self,
        *,
        metadata: StoredObjectMetadata,
        content_type: str,
        supports_range: bool,
        method: str,
        range_header: str | None,
        headers: Mapping[str, str],
    ) -> MediaDeliveryResult:
        if metadata.content_length > self.max_object_bytes:
            raise MediaStorageUnavailable("The private media object exceeds the delivery limit.")
        if range_header is not None and not supports_range:
            return MediaDeliveryResult(
                status_code=416,
                content_type=content_type,
                content_length=0,
                headers={**headers, "Content-Range": f"bytes */{metadata.content_length}"},
            )
        try:
            requested_range = self.delivery_port.range_policy.validate_header(range_header)
        except MediaRangeError:
            return MediaDeliveryResult(
                status_code=416,
                content_type=content_type,
                content_length=0,
                headers={**headers, "Content-Range": f"bytes */{metadata.content_length}"},
            )
        if requested_range is None:
            start, end, status_code = 0, metadata.content_length - 1, 200
        else:
            start, requested_end = requested_range
            if start >= metadata.content_length:
                return MediaDeliveryResult(
                    status_code=416,
                    content_type=content_type,
                    content_length=0,
                    headers={**headers, "Content-Range": f"bytes */{metadata.content_length}"},
                )
            end = (
                metadata.content_length - 1
                if requested_end is None
                else min(requested_end, metadata.content_length - 1)
            )
            if end < start:
                return MediaDeliveryResult(
                    status_code=416,
                    content_type=content_type,
                    content_length=0,
                    headers={**headers, "Content-Range": f"bytes */{metadata.content_length}"},
                )
            status_code = 206
        length = end - start + 1
        if length > self.max_object_bytes:
            raise MediaStorageUnavailable("The private media range exceeds the delivery limit.")
        response_headers = {
            **headers,
            "Content-Length": str(length),
            **(
                {"Content-Range": f"bytes {start}-{end}/{metadata.content_length}"}
                if status_code == 206
                else {}
            ),
        }
        body = (
            None
            if method == "HEAD"
            else self._stream(
                metadata.object_key,
                start=start,
                end=end,
                expected_length=length,
                expected_checksum=metadata.checksum_sha256,
                expected_identity=self._metadata_identity(metadata),
                verify_full_checksum=start == 0 and end == metadata.content_length - 1,
            )
        )
        return MediaDeliveryResult(
            status_code=status_code,
            content_type=content_type,
            content_length=length,
            headers=response_headers,
            body=body,
        )

    def _serve_manifest(
        self,
        *,
        metadata: StoredObjectMetadata,
        content_type: str,
        claims: Mapping[str, object],
        media_version: MediaAssetVersion,
        version_prefix: str,
        token_type: str,
        object_key: str,
        method: str,
        range_header: str | None,
        now: datetime,
        headers: Mapping[str, str],
    ) -> MediaDeliveryResult:
        if range_header is not None:
            return MediaDeliveryResult(
                status_code=416,
                content_type=content_type,
                content_length=0,
                headers={**headers, "Content-Range": f"bytes */{metadata.content_length}"},
            )
        if not object_key.lower().endswith(".m3u8"):
            raise MediaStorageUnavailable("The HLS playlist object has an unverified key.")
        if metadata.content_length > self.max_manifest_bytes:
            raise MediaStorageUnavailable("The HLS playlist exceeds the delivery limit.")
        try:
            body = self.storage.read_prefix(object_key, max_bytes=self.max_manifest_bytes + 1)
        except Exception as error:
            raise MediaStorageUnavailable("The HLS playlist could not be read.") from error
        if (
            not isinstance(body, bytes)
            or len(body) != metadata.content_length
            or len(body) > self.max_manifest_bytes
        ):
            raise MediaStorageUnavailable("The HLS playlist changed while it was read.")
        if hashlib.sha256(body).hexdigest() != metadata.checksum_sha256.lower():
            raise MediaStorageUnavailable("The HLS playlist checksum is unverified.")
        self._verify_stream_identity(
            object_key,
            expected_identity=self._metadata_identity(metadata),
        )
        try:
            playlist = body.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise MediaStorageUnavailable("The HLS playlist is not valid UTF-8.") from error
        # The service's canonical source object is
        # ``.../{version}/original`` and processing stores outputs below
        # ``original/renditions``.  Keep the compact test/local layout
        # ``.../{version}/renditions`` valid as well, but accept only these
        # two structured descendants of the verified version prefix.  A
        # substring marker or an arbitrary intermediate path must not widen
        # the HLS graph's namespace.
        rendition_prefixes = (
            f"{version_prefix}/renditions",
            f"{version_prefix}/original/renditions",
        )
        rendition_prefix = next(
            (prefix for prefix in rendition_prefixes if object_key.startswith(prefix + "/")),
            None,
        )
        if rendition_prefix is None:
            raise MediaStorageUnavailable("The HLS playlist is outside the rendition namespace.")
        namespace_prefix = rendition_prefix
        try:
            inventory = inspect_hls_playlist_inventory(
                self.storage,
                root_key=object_key,
                namespace_prefix=namespace_prefix,
                max_playlist_bytes=self.max_manifest_bytes,
                max_head_operations=self.max_hls_head_operations,
            )
        except Exception as error:
            if isinstance(error, MediaProcessingError):
                raise MediaStorageUnavailable("The HLS object graph is not deliverable.") from error
            raise MediaStorageUnavailable("The HLS object graph could not be inspected.") from error
        inventory_set = frozenset(inventory)
        rewritten = self._rewrite_playlist(
            playlist,
            playlist_key=object_key,
            namespace_prefix=namespace_prefix,
            inventory=inventory_set,
            claims=claims,
            media_version=media_version,
            token_type=token_type,
            now=now,
        )
        encoded = rewritten.encode("utf-8")
        if len(encoded) > self.max_manifest_bytes * 4:
            raise MediaStorageUnavailable("The signed HLS playlist exceeds the delivery limit.")
        response_headers = {
            **headers,
            # The response body is a transformed manifest, so the object
            # checksum cannot be reused as its HTTP entity tag.
            "ETag": f'"{hashlib.sha256(encoded).hexdigest()}"',
            "Accept-Ranges": "none",
            "Content-Length": str(len(encoded)),
        }
        return MediaDeliveryResult(
            status_code=200,
            content_type=content_type,
            content_length=len(encoded),
            headers=response_headers,
            body=None if method == "HEAD" else (encoded,),
        )

    def _rewrite_playlist(
        self,
        playlist: str,
        *,
        playlist_key: str,
        namespace_prefix: str,
        inventory: frozenset[str],
        claims: Mapping[str, object],
        media_version: MediaAssetVersion,
        token_type: str,
        now: datetime,
    ) -> str:
        issued_at = _claim_timestamp(claims, "iat")
        expires_at = _claim_timestamp(claims, "exp")
        authorization = create_media_authorization_context(
            tenant_id=_claim_text(claims, "tenant_id"),
            person_id=_claim_text(claims, "person_id"),
            session_id=_claim_text(claims, "session_id"),
        )
        activity_id = _claim_text(claims, "activity_id")
        activity_version = _claim_text(claims, "activity_version")
        # Preserve the durable grant scope without extending its TTL or the
        # independently validated HLS object inventory.
        from ac_platform.media.policy import PersistedMediaGrantScope

        grant_scope = PersistedMediaGrantScope.from_claims(claims)

        def signed_child(uri: str) -> str:
            try:
                child = resolve_hls_child_object_key(
                    playlist_key=playlist_key,
                    uri=uri,
                    namespace_prefix=namespace_prefix,
                )
            except MediaProcessingError as error:
                raise MediaStorageUnavailable("The HLS playlist contains an unsafe URI.") from error
            if child not in inventory:
                raise MediaStorageUnavailable("The HLS playlist references an unverified object.")
            signed = self.delivery_port.issue(
                authorization=authorization,
                activity_id=activity_id,
                activity_version=activity_version,
                media_version=media_version,
                object_key=child,
                now=issued_at,
                kind=token_type,
                supports_range=False,
                grant_scope=grant_scope,
            )
            if signed.expires_at != expires_at or signed.expires_at <= now:
                raise MediaStorageUnavailable("The HLS child token lifetime is unverified.")
            return signed.url.value

        output: list[str] = []
        for raw_line in playlist.splitlines(keepends=True):
            line = raw_line.rstrip("\r\n")
            newline = raw_line[len(line) :]
            if not line:
                output.append(raw_line)
                continue
            if line.startswith("#"):
                try:
                    rewritten_line = _HLS_URI_ATTRIBUTE.sub(
                        lambda match: f'URI="{signed_child(match.group(1))}"',
                        line,
                    )
                except MediaStorageUnavailable:
                    raise
                output.append(rewritten_line + newline)
                continue
            output.append(signed_child(line) + newline)
        return "".join(output)

    def _stream(
        self,
        object_key: str,
        *,
        start: int,
        end: int,
        expected_length: int,
        expected_checksum: str,
        expected_identity: tuple[str, str, int, str, str],
        verify_full_checksum: bool,
    ) -> Iterator[bytes]:
        """Stream an exact range and revalidate its immutable object identity."""

        observed_length = 0
        digest = hashlib.sha256()
        iterator: Iterator[bytes] | None = None
        try:
            iterator = self.storage.iter_range(
                object_key,
                start=start,
                end=end,
                chunk_size=self.chunk_size,
            )
            for chunk in iterator:
                if (
                    not isinstance(chunk, bytes)
                    or not chunk
                    or len(chunk) > self.chunk_size
                    or observed_length + len(chunk) > expected_length
                ):
                    raise MediaStorageUnavailable(
                        "The private media adapter returned an oversized or invalid chunk."
                    )
                observed_length += len(chunk)
                digest.update(chunk)
                yield chunk
            if observed_length != expected_length:
                raise MediaStorageUnavailable(
                    "The private media adapter returned a truncated range."
                )
            if verify_full_checksum and digest.hexdigest() != expected_checksum.lower():
                raise MediaStorageUnavailable(
                    "The private media adapter returned bytes with an unverified checksum."
                )
            self._verify_stream_identity(object_key, expected_identity=expected_identity)
        except MediaStorageUnavailable:
            raise
        except Exception as error:
            raise MediaStorageUnavailable(
                "The private media object could not be streamed."
            ) from error
        finally:
            if iterator is not None:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()


__all__ = [
    "MediaDeliveryAuthorizer",
    "MediaDeliveryResult",
    "MediaTokenType",
    "PrivateMediaDeliveryHandler",
]
