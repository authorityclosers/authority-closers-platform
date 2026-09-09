"""Private object-storage port and explicit test/S3-compatible adapters."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import mimetypes
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, Protocol, runtime_checkable
from urllib.parse import parse_qsl, quote, urlsplit

from ac_platform.media.contracts import EphemeralMediaUrl
from ac_platform.media.errors import MediaStorageUnavailable
from ac_platform.media.signing import MediaSigner

_OBJECT_KEY_PATTERN = re.compile(r"^[^\\/\x00-\x1f\x7f]+(?:/[^\\/\x00-\x1f\x7f]+)*$")
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_HEADER_VALUE_MAX_LENGTH = 1024
_MAX_UPLOAD_LIFETIME_SECONDS = 3600
_PRESIGNED_QUERY_NAMES = frozenset(
    {
        "x-amz-algorithm",
        "x-amz-credential",
        "x-amz-date",
        "x-amz-expires",
        "x-amz-security-token",
        "x-amz-signature",
        "x-amz-signedheaders",
        "x-amz-content-sha256",
        "expires",
        "expiresin",
        "signature",
        "sig",
        "token",
    }
)
_PRESIGNED_EXPIRY_NAMES = frozenset({"x-amz-expires", "expires", "expiresin"})
_PRESIGNED_SIGNATURE_NAMES = frozenset({"x-amz-signature", "signature", "sig", "token"})
_PRESIGNED_AWS_REQUIRED_QUERY_NAMES = frozenset(
    {
        "x-amz-algorithm",
        "x-amz-credential",
        "x-amz-date",
        "x-amz-expires",
        "x-amz-signedheaders",
        "x-amz-signature",
    }
)
_PRESIGNED_AWS_OPTIONAL_QUERY_NAMES = frozenset({"x-amz-security-token", "x-amz-content-sha256"})
_LOCAL_UPLOAD_CONTRACT = object()
_LOCAL_AVATAR_UPLOAD_CONTRACT = object()
_S3_UPLOAD_CONTRACT = object()


def _safe_provider_transport_available() -> bool:
    """Return whether a peer/IP-bound credential transport is composed."""

    # No transport in this repository binds the HTTP client's peer to the
    # approved DNS answer yet. Keep the provider adapter impossible to build.
    return False


@dataclass(frozen=True, slots=True)
class StoredObjectMetadata:
    object_key: str
    content_type: str
    content_length: int
    checksum_sha256: str
    storage_version_id: str


@dataclass(frozen=True, slots=True)
class StorageUploadIntent:
    upload_url: str
    object_key: str
    expires_at: datetime
    headers: dict[str, str]
    # Only the module-private local/S3 concrete adapters can pass a contract
    # sentinel. A generic caller cannot smuggle an opaque provider signature,
    # expiry query, Authorization header, or arbitrary request headers into an
    # activation path by constructing this data class directly.
    _contract: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate adapter output before it crosses the application boundary."""

        if not isinstance(self.upload_url, str):
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid upload URL."
            )
        try:
            parsed = urlsplit(self.upload_url)
            parsed_hostname = parsed.hostname
            parsed_username = parsed.username
            parsed_password = parsed.password
            parsed_port = parsed.port
        except (TypeError, ValueError) as error:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid upload URL."
            ) from error
        local_avatar = (
            self._contract is _LOCAL_AVATAR_UPLOAD_CONTRACT
            and parsed.scheme == "http"
            and parsed.netloc == "learner.localhost:3100"
            and parsed.path.startswith("/v1/media/local-avatar-upload/")
        )
        if self._contract is _LOCAL_AVATAR_UPLOAD_CONTRACT and not local_avatar:
            raise MediaStorageUnavailable("The local avatar upload origin is invalid.")
        if (
            (parsed.scheme != "https" and not local_avatar)
            or not parsed_hostname
            or parsed_username
            or parsed_password
            or parsed_port is not None
            and not 1 <= parsed_port <= 65535
        ):
            raise MediaStorageUnavailable(
                "The private media adapter returned an unsafe upload URL."
            )
        normalized_host = parsed_hostname.rstrip(".").lower()
        if not local_avatar and (
            normalized_host == "localhost"
            or normalized_host.endswith((".localhost", ".local", ".internal", ".lan"))
        ):
            raise MediaStorageUnavailable("The private media adapter returned a local upload host.")
        try:
            host_address = ipaddress.ip_address(normalized_host)
        except ValueError:
            host_address = None
        if host_address is not None and not host_address.is_global:
            raise MediaStorageUnavailable(
                "The private media adapter returned a non-public upload host."
            )
        if parsed.fragment or not parsed.query:
            raise MediaStorageUnavailable(
                "The private media adapter returned an unsigned upload URL."
            )
        try:
            query_pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError as error:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid upload query."
            ) from error
        seen_query_names: set[str] = set()
        for name, value in query_pairs:
            normalized_name = name.strip().lower()
            if (
                not normalized_name
                or normalized_name not in _PRESIGNED_QUERY_NAMES
                or normalized_name in seen_query_names
                or not value
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in name)
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
                or any(character.isspace() for character in value)
            ):
                raise MediaStorageUnavailable(
                    "The private media adapter returned an invalid or duplicate upload query."
                )
            seen_query_names.add(normalized_name)
        if self._contract not in {
            _LOCAL_UPLOAD_CONTRACT,
            _LOCAL_AVATAR_UPLOAD_CONTRACT,
            _S3_UPLOAD_CONTRACT,
        }:
            raise MediaStorageUnavailable(
                "The generic upload intent is not a constructible activation contract."
            )
        if self._contract in {
            _LOCAL_UPLOAD_CONTRACT,
            _LOCAL_AVATAR_UPLOAD_CONTRACT,
        } and seen_query_names != {"token"}:
            raise MediaStorageUnavailable(
                "The generic upload intent requires the bounded local token contract."
            )
        if any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in self.upload_url
        ) or any(character.isspace() for character in self.upload_url):
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid upload URL."
            )
        if not isinstance(self.object_key, str):
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid object key."
            )
        key = self.object_key.strip()
        if (
            key != self.object_key
            or len(key) > 512
            or not _OBJECT_KEY_PATTERN.fullmatch(key)
            or any(part in {".", ".."} for part in key.split("/"))
            or any(character.isspace() for character in key)
        ):
            raise MediaStorageUnavailable(
                "The private media adapter returned an unsafe object key."
            )
        if not isinstance(self.expires_at, datetime):
            raise MediaStorageUnavailable("The private media adapter returned an invalid expiry.")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise MediaStorageUnavailable("The private media adapter returned an invalid expiry.")
        remaining = (self.expires_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        if remaining <= 0 or remaining > _MAX_UPLOAD_LIFETIME_SECONDS + 5:
            raise MediaStorageUnavailable("The private media adapter returned an invalid expiry.")
        if not isinstance(self.headers, dict):
            raise MediaStorageUnavailable("The private media adapter returned invalid headers.")
        normalized_headers: dict[str, str] = {}
        for name, value in self.headers.items():
            if (
                not isinstance(name, str)
                or _HEADER_NAME_PATTERN.fullmatch(name) is None
                or not isinstance(value, str)
                or len(value) > _HEADER_VALUE_MAX_LENGTH
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
            ):
                raise MediaStorageUnavailable(
                    "The private media adapter returned invalid upload headers."
                )
            normalized_name = name.lower()
            if normalized_name in normalized_headers:
                raise MediaStorageUnavailable(
                    "The private media adapter returned duplicate upload headers."
                )
            normalized_headers[normalized_name] = value
        allowed_headers = {"content-type", "content-length"}
        if self._contract is _S3_UPLOAD_CONTRACT:
            allowed_headers.add("x-amz-checksum-sha256")
        else:
            allowed_headers.add("x-content-sha256")
        if set(normalized_headers) - allowed_headers:
            raise MediaStorageUnavailable(
                "The private media adapter returned an unapproved upload header."
            )
        if (
            "x-content-sha256" in normalized_headers
            and _SHA256.fullmatch(normalized_headers["x-content-sha256"]) is None
        ):
            raise MediaStorageUnavailable(
                "The generic upload intent returned an invalid checksum header."
            )
        if normalized_headers.get("content-length") is None:
            raise MediaStorageUnavailable("The private media adapter omitted Content-Length.")
        try:
            if re.fullmatch(r"[1-9][0-9]*", normalized_headers["content-length"]) is None:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid Content-Length."
            ) from error
        if not normalized_headers.get("content-type", "").strip():
            raise MediaStorageUnavailable("The private media adapter omitted Content-Type.")
        object.__setattr__(self, "object_key", key)
        object.__setattr__(self, "headers", normalized_headers)


def _secure_url(value: str) -> str:
    try:
        return EphemeralMediaUrl(value).value
    except (TypeError, ValueError) as error:
        raise MediaStorageUnavailable(
            "The private media adapter returned a non-HTTPS URL."
        ) from error


@runtime_checkable
class PrivateObjectStorage(Protocol):
    def create_upload_intent(
        self,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> StorageUploadIntent: ...

    def head(self, object_key: str) -> StoredObjectMetadata | None: ...

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes: ...

    def read(self, object_key: str) -> bytes: ...

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]: ...

    def put(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        storage_version_id: str | None = None,
    ) -> StoredObjectMetadata: ...

    def copy(
        self, *, source_key: str, destination_key: str, content_type: str
    ) -> StoredObjectMetadata: ...

    def delete(self, object_key: str) -> None: ...

    def list_prefix(self, prefix: str) -> tuple[str, ...]: ...


class UnconfiguredPrivateObjectStorage:
    """Fail-closed composition root adapter; it never uses local memory."""

    def _unavailable(self) -> NoReturn:
        raise MediaStorageUnavailable("A private media storage adapter is not configured.")

    def create_upload_intent(self, **kwargs: Any) -> StorageUploadIntent:
        del kwargs
        self._unavailable()

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        del object_key
        self._unavailable()

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes:
        del object_key, max_bytes
        self._unavailable()

    def read(self, object_key: str) -> bytes:
        del object_key
        self._unavailable()

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        del object_key, start, end, chunk_size
        self._unavailable()

    def put(self, **kwargs: Any) -> StoredObjectMetadata:
        del kwargs
        self._unavailable()

    def copy(self, **kwargs: Any) -> StoredObjectMetadata:
        del kwargs
        self._unavailable()

    def delete(self, object_key: str) -> None:
        del object_key
        self._unavailable()

    def list_prefix(self, prefix: str) -> tuple[str, ...]:
        del prefix
        self._unavailable()


class InMemoryPrivateObjectStorage:
    """Explicit test adapter; it is never selected by production composition."""

    def __init__(self, signer: MediaSigner, *, public_alias: str = "https://media.test") -> None:
        self._signer = signer
        self._public_alias = _secure_url(public_alias).rstrip("/")
        self._objects: dict[str, tuple[bytes, StoredObjectMetadata]] = {}

    def create_upload_intent(
        self,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> StorageUploadIntent:
        normalized_expires_at = (
            expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
        )
        token = self._signer.sign(
            {"key": object_key, "bytes": content_length, "checksum": checksum_sha256 or ""},
            now=datetime.now(normalized_expires_at.tzinfo),
            lifetime=max(
                normalized_expires_at - datetime.now(normalized_expires_at.tzinfo),
                datetime.resolution,
            ),
            token_type="upload",  # noqa: S106 - bounded token kind, not a secret
        )
        headers = {"Content-Type": content_type, "Content-Length": str(content_length)}
        if checksum_sha256:
            headers["x-content-sha256"] = checksum_sha256
        return StorageUploadIntent(
            _secure_url(
                f"{self._public_alias}/private-upload/"
                f"{quote(object_key, safe='')}?token={quote(token, safe='')}"
            ),
            object_key,
            normalized_expires_at,
            headers,
            _contract=_LOCAL_UPLOAD_CONTRACT,
        )

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        item = self._objects.get(object_key)
        return item[1] if item else None

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes:
        item = self._objects.get(object_key)
        if item is None:
            raise MediaStorageUnavailable("The private media object is unavailable.")
        return item[0][:max_bytes]

    def read(self, object_key: str) -> bytes:
        item = self._objects.get(object_key)
        if item is None:
            raise MediaStorageUnavailable("The private media object is unavailable.")
        return bytes(item[0])

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        """Yield one bounded object range without making a second copy.

        The delivery layer validates the range against a verified ``head``
        before calling this primitive.  Keeping the validation here as well
        prevents a future caller from accidentally creating an unbounded or
        negative slice through the test adapter.
        """

        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or start < 0
            or end is not None
            and (isinstance(end, bool) or not isinstance(end, int) or end < start)
            or isinstance(chunk_size, bool)
            or not isinstance(chunk_size, int)
            or chunk_size <= 0
            or chunk_size > 16 * 1024 * 1024
        ):
            raise MediaStorageUnavailable("The private media range is invalid.")
        item = self._objects.get(object_key)
        if item is None:
            raise MediaStorageUnavailable("The private media object is unavailable.")
        body = item[0]
        bounded_end = len(body) - 1 if end is None else min(end, len(body) - 1)
        if start >= len(body) or bounded_end < start:
            raise MediaStorageUnavailable("The private media range is unavailable.")
        for offset in range(start, bounded_end + 1, chunk_size):
            yield bytes(body[offset : min(offset + chunk_size, bounded_end + 1)])

    def put(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        storage_version_id: str | None = None,
    ) -> StoredObjectMetadata:
        metadata = StoredObjectMetadata(
            object_key,
            content_type,
            len(body),
            hashlib.sha256(body).hexdigest(),
            storage_version_id or hashlib.sha256(body + object_key.encode()).hexdigest()[:32],
        )
        self._objects[object_key] = (bytes(body), metadata)
        return metadata

    def copy(
        self, *, source_key: str, destination_key: str, content_type: str
    ) -> StoredObjectMetadata:
        item = self._objects.get(source_key)
        if item is None:
            raise MediaStorageUnavailable("The private media object is unavailable.")
        return self.put(object_key=destination_key, body=item[0], content_type=content_type)

    def delete(self, object_key: str) -> None:
        self._objects.pop(object_key, None)

    def list_prefix(self, prefix: str) -> tuple[str, ...]:
        normalized = prefix.rstrip("/")
        if not normalized:
            return ()
        return tuple(
            sorted(
                key
                for key in self._objects
                if key == normalized or key.startswith(normalized + "/")
            )
        )


def _provider_checksum_to_hex(value: str | None) -> str:
    if not value:
        return ""
    try:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) == 32:
            return decoded.hex()
    except (ValueError, TypeError):
        pass
    return value.lower() if len(value) == 64 else ""


class S3CompatiblePrivateObjectStorage:
    """Future S3-compatible adapter shape; transport is unavailable here."""

    def __init__(
        self,
        client: Any,
        *,
        bucket: str,
        public_alias: str,
        endpoint_url: str | None = None,
        endpoint_addresses: tuple[str, ...] | None = None,
        access_key_id: str | None = None,
        region: str | None = None,
        activation_config: Any | None = None,
        activation_verifier: Any | None = None,
    ) -> None:
        from ac_platform.media.config import MediaProviderConfig

        activation_verified = isinstance(activation_config, MediaProviderConfig) and (
            activation_config.activation_verified(activation_verifier)
        )
        if not activation_verified:
            raise MediaStorageUnavailable(
                "The media provider adapter requires an externally verified activation."
            )
        # DNS validation alone cannot bind a credential-bearing HTTP client to
        # the validated peer. Keep this adapter impossible to instantiate until
        # a reviewed peer-bound transport is composed.
        if not _safe_provider_transport_available():
            raise MediaStorageUnavailable("The safe provider transport is not composed.")

        # The remaining fields are retained as the reviewed adapter shape for
        # a future peer-bound transport implementation.
        approved_endpoint = getattr(activation_config, "endpoint_url", None)
        approved_bucket = getattr(activation_config, "bucket", None)
        approved_delivery_origin = getattr(activation_config, "delivery_origin", None)
        if (
            not isinstance(approved_endpoint, str)
            or endpoint_url is not None
            and endpoint_url != approved_endpoint
            or bucket != approved_bucket
            or not isinstance(approved_delivery_origin, str)
            or public_alias.rstrip("/") != approved_delivery_origin.rstrip("/")
        ):
            raise MediaStorageUnavailable(
                "The provider adapter inputs do not match approved configuration."
            )
        self._client = client
        self._bucket = bucket
        self._public_alias = _secure_url(public_alias).rstrip("/")
        self._endpoint_url = approved_endpoint
        configured_access_key = getattr(activation_config, "access_key_id", None)
        configured_region = getattr(activation_config, "region", None)
        if (
            access_key_id is not None
            and configured_access_key is not None
            and access_key_id != configured_access_key
        ) or (region is not None and configured_region is not None and region != configured_region):
            raise MediaStorageUnavailable(
                "The provider credential scope does not match approved configuration."
            )
        self._access_key_id = configured_access_key or access_key_id
        self._region = configured_region or region
        # Caller-provided DNS answers are never an authority.  Resolve the
        # configured endpoint ourselves and only use an injected tuple as a
        # consistency check for a future reviewed composition.
        self._endpoint_addresses = self._resolve_endpoint_addresses()
        if endpoint_addresses is not None:
            supplied_addresses = tuple(endpoint_addresses)
            if any(
                not isinstance(address, str) or address != address.strip()
                for address in supplied_addresses
            ) or len(set(supplied_addresses)) != len(supplied_addresses):
                raise MediaStorageUnavailable(
                    "The supplied provider endpoint addresses are invalid."
                )
            if tuple(sorted(supplied_addresses)) != self._endpoint_addresses:
                raise MediaStorageUnavailable(
                    "The supplied provider endpoint addresses do not match the approved resolver."
                )

    def _resolve_endpoint_addresses(self) -> tuple[str, ...]:
        if self._endpoint_url is None:
            return ()
        from ac_platform.media.config import resolve_media_endpoint_addresses

        try:
            return resolve_media_endpoint_addresses(self._endpoint_url)
        except (TypeError, ValueError) as error:
            raise MediaStorageUnavailable(
                "The media provider endpoint could not be validated safely."
            ) from error

    def _assert_endpoint_safe(self) -> None:
        """Reject DNS rebinding before any credential-bearing provider call."""

        if self._endpoint_url is None:
            return
        current = self._resolve_endpoint_addresses()
        if current != self._endpoint_addresses:
            raise MediaStorageUnavailable(
                "The media provider endpoint resolution changed; storage is unavailable."
            )

    def create_upload_intent(
        self,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> StorageUploadIntent:
        self._assert_endpoint_safe()
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": object_key,
            "ContentType": content_type,
            "ContentLength": content_length,
        }
        if checksum_sha256:
            params["ChecksumSHA256"] = base64.b64encode(bytes.fromhex(checksum_sha256)).decode(
                "ascii"
            )
        seconds = max(1, int((expires_at - datetime.now(expires_at.tzinfo)).total_seconds()))
        url = self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=seconds, HttpMethod="PUT"
        )
        headers = {"Content-Type": content_type, "Content-Length": str(content_length)}
        if checksum_sha256:
            headers["x-amz-checksum-sha256"] = params["ChecksumSHA256"]
        intent = StorageUploadIntent(
            _secure_url(str(url)),
            object_key,
            expires_at,
            headers,
            _contract=_S3_UPLOAD_CONTRACT,
        )
        self._validate_upload_intent(
            intent,
            object_key=object_key,
            content_type=content_type,
            content_length=content_length,
            checksum_sha256=checksum_sha256,
        )
        return intent

    def _validate_upload_intent(
        self,
        intent: StorageUploadIntent,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str | None,
    ) -> None:
        """Bind adapter output to the exact requested object and upload contract."""

        if (
            isinstance(content_length, bool)
            or not isinstance(content_length, int)
            or content_length <= 0
            or not isinstance(content_type, str)
            or not content_type
            or checksum_sha256 is not None
            and _SHA256.fullmatch(checksum_sha256) is None
        ):
            raise MediaStorageUnavailable(
                "The private media adapter received an invalid upload contract."
            )
        if intent.object_key != object_key:
            raise MediaStorageUnavailable(
                "The private media adapter changed the upload object key."
            )
        parsed = urlsplit(intent.upload_url)
        if not self._endpoint_url:
            raise MediaStorageUnavailable(
                "The private media adapter has no approved upload endpoint."
            )
        configured_endpoint = urlsplit(self._endpoint_url)
        endpoint_host = configured_endpoint.hostname
        returned_host = parsed.hostname
        configured_port = configured_endpoint.port or 443
        returned_port = parsed.port or 443
        if (
            endpoint_host is None
            or returned_host is None
            or returned_host.rstrip(".").lower() != endpoint_host.rstrip(".").lower()
            or returned_port != configured_port
            or parsed.scheme != configured_endpoint.scheme
        ):
            raise MediaStorageUnavailable(
                "The private media adapter returned an unapproved upload host."
            )
        endpoint_path = configured_endpoint.path.rstrip("/")
        encoded_key = quote(object_key, safe="/-._~")
        encoded_bucket = quote(self._bucket, safe="-._~")
        approved_paths = {
            f"{endpoint_path}/{encoded_key}",
            f"{endpoint_path}/{encoded_bucket}/{encoded_key}",
        }
        if parsed.path not in approved_paths:
            raise MediaStorageUnavailable(
                "The private media adapter returned an unapproved upload path."
            )
        try:
            query_pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError as error:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid upload query."
            ) from error
        query: dict[str, str] = {}
        for name, value in query_pairs:
            normalized_name = name.lower()
            if (
                normalized_name not in _PRESIGNED_QUERY_NAMES
                or normalized_name in query
                or not value
                or any(character.isspace() for character in value)
            ):
                raise MediaStorageUnavailable(
                    "The private media adapter returned an invalid or duplicate upload query."
                )
            query[normalized_name] = value
        if "x-amz-algorithm" not in query:
            raise MediaStorageUnavailable(
                "The private media adapter requires an AWS SigV4 upload contract."
            )
        allowed_aws_names = (
            _PRESIGNED_AWS_REQUIRED_QUERY_NAMES | _PRESIGNED_AWS_OPTIONAL_QUERY_NAMES
        )
        query_names = set(query)
        if not _PRESIGNED_AWS_REQUIRED_QUERY_NAMES.issubset(
            query_names
        ) or not query_names.issubset(allowed_aws_names):
            raise MediaStorageUnavailable(
                "The private media adapter returned an incomplete or extra signed query."
            )
        if query["x-amz-algorithm"] != "AWS4-HMAC-SHA256":
            raise MediaStorageUnavailable(
                "The private media adapter returned an unsupported signing algorithm."
            )
        credential_parts = query["x-amz-credential"].split("/")
        if len(credential_parts) != 5:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid SigV4 credential scope."
            )
        access_key, scope_date, scope_region, scope_service, scope_terminal = credential_parts
        configured_access_key = getattr(self, "_access_key_id", None)
        configured_region = getattr(self, "_region", None)
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{5,127}", access_key)
            or not isinstance(configured_access_key, str)
            or access_key != configured_access_key
            or not re.fullmatch(r"[0-9]{8}", scope_date)
            or not isinstance(configured_region, str)
            or scope_region != configured_region
            or scope_service != "s3"
            or scope_terminal != "aws4_request"
        ):
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid SigV4 credential scope."
            )
        amz_date = query["x-amz-date"]
        if re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", amz_date) is None:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid SigV4 timestamp."
            )
        try:
            signed_at = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError as error:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid SigV4 timestamp."
            ) from error
        if scope_date != amz_date[:8]:
            raise MediaStorageUnavailable(
                "The private media adapter returned a mismatched SigV4 scope date."
            )
        expiry_names = _PRESIGNED_EXPIRY_NAMES.intersection(query)
        if len(expiry_names) != 1:
            raise MediaStorageUnavailable(
                "The private media adapter returned an upload URL without an expiry."
            )
        declared_expiry = query[next(iter(expiry_names))]
        try:
            if (
                not re.fullmatch(r"[0-9]{1,4}", declared_expiry)
                or int(declared_expiry) <= 0
                or int(declared_expiry) > _MAX_UPLOAD_LIFETIME_SECONDS
            ):
                raise ValueError
        except (TypeError, ValueError) as error:
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid upload expiry."
            ) from error
        signed_until = signed_at + timedelta(seconds=int(declared_expiry))
        now = datetime.now(UTC)
        if signed_at > now + timedelta(minutes=5) or signed_until < now - timedelta(seconds=5):
            raise MediaStorageUnavailable(
                "The private media adapter returned an expired or future SigV4 timestamp."
            )
        remaining_seconds = max(
            1,
            int((intent.expires_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()),
        )
        if abs(int(declared_expiry) - remaining_seconds) > 5:
            raise MediaStorageUnavailable(
                "The private media adapter returned a mismatched upload expiry."
            )
        if abs((intent.expires_at.astimezone(UTC) - signed_until).total_seconds()) > 5:
            raise MediaStorageUnavailable(
                "The private media adapter returned a mismatched SigV4 expiry."
            )
        signature_names = _PRESIGNED_SIGNATURE_NAMES.intersection(query)
        if signature_names != {"x-amz-signature"}:
            raise MediaStorageUnavailable(
                "The private media adapter returned an unsigned upload URL."
            )
        signature_name = next(iter(signature_names))
        signature = query[signature_name]
        if (
            signature_name == "x-amz-signature"
            and re.fullmatch(r"[0-9a-fA-F]{64}", signature) is None
        ):
            raise MediaStorageUnavailable(
                "The private media adapter returned an invalid upload signature."
            )
        headers = {name.lower(): value for name, value in intent.headers.items()}
        expected_headers = {"content-type", "content-length"}
        if checksum_sha256:
            expected_headers.add("x-amz-checksum-sha256")
        if set(headers) != expected_headers:
            raise MediaStorageUnavailable(
                "The private media adapter returned extra or missing upload headers."
            )
        # SigV4 always binds the request host in addition to each required
        # upload header.  ``host`` is derived from the validated URL and is
        # intentionally not accepted as a caller-supplied header value.
        expected_signed_headers = expected_headers | {"host"}
        signed_headers = query["x-amz-signedheaders"].split(";")
        if (
            not signed_headers
            or any(not name or name != name.lower() for name in signed_headers)
            or len(set(signed_headers)) != len(signed_headers)
            or set(signed_headers) != expected_signed_headers
            or ";".join(sorted(signed_headers)) != query["x-amz-signedheaders"]
        ):
            raise MediaStorageUnavailable(
                "The private media adapter returned an incomplete or extra signed header set."
            )
        if headers.get("content-type") != content_type:
            raise MediaStorageUnavailable("The private media adapter changed the upload MIME.")
        if headers.get("content-length") != str(content_length):
            raise MediaStorageUnavailable("The private media adapter changed the upload size.")
        if checksum_sha256:
            expected_header = base64.b64encode(bytes.fromhex(checksum_sha256)).decode("ascii")
            checksum_header = headers.get("x-amz-checksum-sha256") or headers.get(
                "x-content-sha256"
            )
            if checksum_header != expected_header and checksum_header != checksum_sha256:
                raise MediaStorageUnavailable(
                    "The private media adapter changed the upload checksum."
                )

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        self._assert_endpoint_safe()
        try:
            result = self._client.head_object(
                Bucket=self._bucket, Key=object_key, ChecksumMode="ENABLED"
            )
        except TypeError:
            result = self._client.head_object(Bucket=self._bucket, Key=object_key)
        except Exception as error:
            code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
            if error.__class__.__name__ in {"NoSuchKey", "NotFound"} or code in {
                "404",
                "NoSuchKey",
                "NotFound",
            }:
                return None
            raise
        return StoredObjectMetadata(
            object_key,
            result.get("ContentType")
            or mimetypes.guess_type(object_key)[0]
            or "application/octet-stream",
            int(result.get("ContentLength", 0)),
            _provider_checksum_to_hex(result.get("ChecksumSHA256")),
            str(result.get("VersionId") or result.get("ETag", "")).strip('"'),
        )

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes:
        self._assert_endpoint_safe()
        result = self._client.get_object(
            Bucket=self._bucket, Key=object_key, Range=f"bytes=0-{max(0, max_bytes - 1)}"
        )
        body = result.get("Body") if isinstance(result, Mapping) else None
        if body is None or not callable(getattr(body, "read", None)):
            raise MediaStorageUnavailable("The private media object prefix is unavailable.")
        try:
            return bytes(body.read(max_bytes))
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def read(self, object_key: str) -> bytes:
        self._assert_endpoint_safe()
        result = self._client.get_object(Bucket=self._bucket, Key=object_key)
        body = result.get("Body") if isinstance(result, Mapping) else None
        if body is None or not callable(getattr(body, "read", None)):
            raise MediaStorageUnavailable("The private media object is unavailable.")
        try:
            return bytes(body.read())
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def iter_range(
        self,
        object_key: str,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        """Stream one object range from the peer-bound S3-compatible client.

        The adapter remains impossible to compose in this repository.  This
        method defines the reviewed transport contract so a future S3/MinIO
        implementation can stream bounded ranges instead of allocating an
        entire video in the API process.
        """

        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or start < 0
            or end is not None
            and (isinstance(end, bool) or not isinstance(end, int) or end < start)
            or isinstance(chunk_size, bool)
            or not isinstance(chunk_size, int)
            or chunk_size <= 0
            or chunk_size > 16 * 1024 * 1024
        ):
            raise MediaStorageUnavailable("The private media range is invalid.")
        self._assert_endpoint_safe()
        range_value = f"bytes={start}-{end if end is not None else ''}"
        try:
            result = self._client.get_object(
                Bucket=self._bucket,
                Key=object_key,
                Range=range_value,
            )
        except Exception as error:
            raise MediaStorageUnavailable(
                "The private media object range is unavailable."
            ) from error
        body = result.get("Body") if isinstance(result, Mapping) else None
        if body is None or not callable(getattr(body, "read", None)):
            raise MediaStorageUnavailable("The private media object range is unavailable.")

        def chunks() -> Iterator[bytes]:
            consumed = 0
            expected = None if end is None else end - start + 1
            try:
                while True:
                    requested = chunk_size
                    if expected is not None:
                        remaining = expected - consumed
                        if remaining <= 0:
                            break
                        requested = min(requested, remaining)
                    piece = body.read(requested)
                    if not piece:
                        break
                    if not isinstance(piece, bytes):
                        raise MediaStorageUnavailable(
                            "The private media adapter returned a non-byte range."
                        )
                    consumed += len(piece)
                    if expected is not None and consumed > expected:
                        raise MediaStorageUnavailable(
                            "The private media adapter returned an oversized range."
                        )
                    yield piece
                if expected is not None and consumed != expected:
                    raise MediaStorageUnavailable(
                        "The private media adapter returned a truncated range."
                    )
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()

        return chunks()

    def put(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        storage_version_id: str | None = None,
    ) -> StoredObjectMetadata:
        self._assert_endpoint_safe()
        del storage_version_id
        result = self._client.put_object(
            Bucket=self._bucket, Key=object_key, Body=body, ContentType=content_type
        )
        return StoredObjectMetadata(
            object_key,
            content_type,
            len(body),
            hashlib.sha256(body).hexdigest(),
            str(result.get("VersionId") or result.get("ETag", "")).strip('"'),
        )

    def copy(
        self, *, source_key: str, destination_key: str, content_type: str
    ) -> StoredObjectMetadata:
        self._assert_endpoint_safe()
        result = self._client.copy_object(
            Bucket=self._bucket,
            Key=destination_key,
            CopySource={"Bucket": self._bucket, "Key": source_key},
            ContentType=content_type,
            MetadataDirective="REPLACE",
        )
        del result
        verified = self.head(destination_key)
        if (
            verified is None
            or verified.object_key != destination_key
            or verified.content_type.lower().split(";", 1)[0].strip()
            != content_type.lower().split(";", 1)[0].strip()
            or verified.content_length <= 0
            or not verified.checksum_sha256
            or re.fullmatch(r"[0-9a-fA-F]{64}", verified.checksum_sha256) is None
        ):
            raise MediaStorageUnavailable(
                "The private media caption copy could not be verified after storage."
            )
        return verified

    def delete(self, object_key: str) -> None:
        self._assert_endpoint_safe()
        self._client.delete_object(Bucket=self._bucket, Key=object_key)

    def list_prefix(self, prefix: str) -> tuple[str, ...]:
        self._assert_endpoint_safe()
        normalized = prefix.rstrip("/")
        if not normalized:
            return ()
        keys: list[str] = []
        continuation: str | None = None
        while True:
            params: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": normalized + "/",
                "MaxKeys": 1000,
            }
            if continuation:
                params["ContinuationToken"] = continuation
            result = self._client.list_objects_v2(**params)
            for item in result.get("Contents", ()):
                key = item.get("Key") if isinstance(item, dict) else None
                if isinstance(key, str) and key.startswith(normalized + "/"):
                    keys.append(key)
                    if len(keys) > 10_000:
                        raise MediaStorageUnavailable(
                            "The media output inventory is too large to clean safely."
                        )
            if not result.get("IsTruncated"):
                break
            next_token = result.get("NextContinuationToken")
            if not isinstance(next_token, str) or not next_token:
                raise MediaStorageUnavailable(
                    "The media output inventory could not be paged safely."
                )
            continuation = next_token
        return tuple(sorted(dict.fromkeys(keys)))


def compose_private_object_storage(
    config: Any,
    *,
    activation_verifier: Any | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> PrivateObjectStorage:
    """Compose a concrete S3-compatible adapter only from approved config.

    Disabled configuration returns the inert fail-closed adapter without
    importing ``boto3``.  Enabled configuration remains unavailable because
    this repository has no immutable deployment attestation or peer-bound
    credential transport; no client is constructed and no bucket is contacted.
    """

    from ac_platform.media.config import MediaProviderConfig, MediaStorageProvider

    if not isinstance(config, MediaProviderConfig):
        raise TypeError("media storage composition requires MediaProviderConfig")
    if not config.activation_verified(activation_verifier):
        return UnconfiguredPrivateObjectStorage()
    if config.provider not in {MediaStorageProvider.S3, MediaStorageProvider.MINIO}:
        raise ValueError("media storage provider is unsupported")
    # The current application has no peer/IP-bound provider transport.  Keep
    # credentials, SDK construction, DNS, and provider requests impossible
    # until deployment composition supplies that reviewed transport.
    del client_factory
    raise MediaStorageUnavailable("The safe provider transport is not composed.")


__all__ = [
    "InMemoryPrivateObjectStorage",
    "PrivateObjectStorage",
    "S3CompatiblePrivateObjectStorage",
    "compose_private_object_storage",
    "StorageUploadIntent",
    "StoredObjectMetadata",
    "UnconfiguredPrivateObjectStorage",
]
