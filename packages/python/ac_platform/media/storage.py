"""Private object-storage port and explicit test/S3-compatible adapters."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn, Protocol
from urllib.parse import quote

from ac_platform.media.contracts import EphemeralMediaUrl
from ac_platform.media.errors import MediaStorageUnavailable
from ac_platform.media.signing import MediaSigner


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


def _secure_url(value: str) -> str:
    try:
        return EphemeralMediaUrl(value).value
    except (TypeError, ValueError) as error:
        raise MediaStorageUnavailable(
            "The private media adapter returned a non-HTTPS URL."
        ) from error


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

    def create_read_url(
        self, *, object_key: str, expires_at: datetime, content_type: str | None = None
    ) -> str: ...

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

    def create_read_url(self, **kwargs: Any) -> str:
        del kwargs
        self._unavailable()

    def put(self, **kwargs: Any) -> StoredObjectMetadata:
        del kwargs
        self._unavailable()

    def copy(self, **kwargs: Any) -> StoredObjectMetadata:
        del kwargs
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
        token = self._signer.sign(
            {"key": object_key, "bytes": content_length, "checksum": checksum_sha256 or ""},
            now=datetime.now(expires_at.tzinfo),
            lifetime=max(expires_at - datetime.now(expires_at.tzinfo), datetime.resolution),
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
            expires_at,
            headers,
        )

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        item = self._objects.get(object_key)
        return item[1] if item else None

    def read_prefix(self, object_key: str, *, max_bytes: int = 512) -> bytes:
        item = self._objects.get(object_key)
        if item is None:
            raise MediaStorageUnavailable("The private media object is unavailable.")
        return item[0][:max_bytes]

    def create_read_url(
        self, *, object_key: str, expires_at: datetime, content_type: str | None = None
    ) -> str:
        token = self._signer.sign(
            {"key": object_key, "content_type": content_type or ""},
            now=datetime.now(expires_at.tzinfo),
            lifetime=max(expires_at - datetime.now(expires_at.tzinfo), datetime.resolution),
            token_type="read",  # noqa: S106 - bounded token kind, not a secret
        )
        return _secure_url(
            f"{self._public_alias}/private-read/"
            f"{quote(object_key, safe='')}?token={quote(token, safe='')}"
        )

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
    """Injected S3/R2-compatible adapter; credentials stay in composition."""

    def __init__(self, client: Any, *, bucket: str, public_alias: str) -> None:
        self._client = client
        self._bucket = bucket
        self._public_alias = _secure_url(public_alias).rstrip("/")

    def create_upload_intent(
        self,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str | None,
        expires_at: datetime,
    ) -> StorageUploadIntent:
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
        return StorageUploadIntent(_secure_url(str(url)), object_key, expires_at, headers)

    def head(self, object_key: str) -> StoredObjectMetadata | None:
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
        result = self._client.get_object(
            Bucket=self._bucket, Key=object_key, Range=f"bytes=0-{max(0, max_bytes - 1)}"
        )
        body = result["Body"]
        return bytes(body.read(max_bytes))

    def create_read_url(
        self, *, object_key: str, expires_at: datetime, content_type: str | None = None
    ) -> str:
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": object_key}
        if content_type:
            params["ResponseContentType"] = content_type
        seconds = max(1, int((expires_at - datetime.now(expires_at.tzinfo)).total_seconds()))
        return _secure_url(
            str(
                self._client.generate_presigned_url(
                    "get_object", Params=params, ExpiresIn=seconds, HttpMethod="GET"
                )
            )
        )

    def put(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        storage_version_id: str | None = None,
    ) -> StoredObjectMetadata:
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
        result = self._client.copy_object(
            Bucket=self._bucket,
            Key=destination_key,
            CopySource={"Bucket": self._bucket, "Key": source_key},
            ContentType=content_type,
            MetadataDirective="REPLACE",
        )
        return StoredObjectMetadata(
            destination_key,
            content_type,
            0,
            "",
            str(
                result.get("VersionId") or result.get("CopyObjectResult", {}).get("ETag", "")
            ).strip('"'),
        )


__all__ = [
    "InMemoryPrivateObjectStorage",
    "PrivateObjectStorage",
    "S3CompatiblePrivateObjectStorage",
    "StorageUploadIntent",
    "StoredObjectMetadata",
    "UnconfiguredPrivateObjectStorage",
]
