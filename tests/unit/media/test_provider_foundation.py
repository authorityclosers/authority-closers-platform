from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import ac_platform.media.config as media_config
import ac_platform.media.processing as media_processing
import ac_platform.media.storage as media_storage
from ac_platform.application.settings import Settings
from ac_platform.media.config import (
    MediaProviderActivationVerifier,
    MediaProviderConfig,
    resolve_media_endpoint_addresses,
)
from ac_platform.media.contracts import (
    MediaAssetId,
    MediaAssetVersion,
    MediaVersionId,
    create_media_authorization_context,
)
from ac_platform.media.errors import (
    MediaConfigurationError,
    MediaForbidden,
    MediaProcessingError,
    MediaQuotaExceeded,
    MediaRangeError,
    MediaStorageUnavailable,
)
from ac_platform.media.lifecycle import (
    InMemoryMediaLifecycleHooks,
    MediaLifecycleAction,
    MediaLifecycleEvent,
    MediaObjectDeletionWorker,
    MediaObjectReference,
    MediaRetentionPolicy,
)
from ac_platform.media.models import MediaPurpose
from ac_platform.media.policy import MediaCorsPolicy, RangePolicy, SignedMediaDeliveryPort
from ac_platform.media.processing import (
    DEFAULT_TRANSCODE_PROFILES,
    CaptionPassthrough,
    FFmpegMediaProcessor,
    ProcessingQuota,
    inspect_hls_playlist_inventory,
)
from ac_platform.media.processing import (
    TestTranscodingProcessor as LocalTranscodingProcessor,
)
from ac_platform.media.runtime import create_media_runtime
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import (
    InMemoryPrivateObjectStorage,
    S3CompatiblePrivateObjectStorage,
    StorageUploadIntent,
    StoredObjectMetadata,
    UnconfiguredPrivateObjectStorage,
    compose_private_object_storage,
)
from ac_platform.media.telemetry import JsonlMediaTelemetryExporter, MediaTelemetryRecorder
from ac_platform.media.video_probe import VideoMetadata


def _environment(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "AC_ENVIRONMENT": "test",
        "AC_MEDIA_PROVIDER_ENABLED": "true",
        "AC_MEDIA_PROVIDER": "minio",
        "AC_MEDIA_STORAGE_ENDPOINT": "https://minio.test",
        "AC_MEDIA_STORAGE_APPROVED_ENDPOINT_HOSTS": "minio.test",
        "AC_MEDIA_STORAGE_BUCKET": "ac-media",
        "AC_MEDIA_STORAGE_REGION": "us-east-1",
        "AC_MEDIA_STORAGE_ACCESS_KEY_ID": "access-key",
        "AC_MEDIA_STORAGE_SECRET_ACCESS_KEY": "x" * 32,
        "AC_MEDIA_DELIVERY_ORIGIN": "https://media.test",
        "AC_MEDIA_CORS_ORIGINS": "https://app.test",
        "AC_MEDIA_GOVERNANCE_REFERENCE": "AC-GOV-AUD-001",
        "AC_MEDIA_GAP_REFERENCE": "GAP-MEDIA-001",
    }
    values.update(overrides)
    return values


class _TestActivationVerifier:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    def verify(
        self,
        *,
        config_fingerprint: str,
        governance_reference: str,
        media_gap_reference: str,
    ) -> bool:
        return (
            config_fingerprint == self.fingerprint
            and governance_reference == "AC-GOV-AUD-001"
            and media_gap_reference == "GAP-MEDIA-001"
        )


def test_media_configuration_is_disabled_without_provider_contact() -> None:
    config = MediaProviderConfig.from_environment({})
    storage = compose_private_object_storage(config)

    assert config.enabled is False
    assert isinstance(storage, UnconfiguredPrivateObjectStorage)


def test_application_settings_reject_enabled_incomplete_provider() -> None:
    with pytest.raises(ValueError, match="invalid media provider configuration"):
        Settings(environment="test", media_provider_enabled=True)


def test_runtime_keeps_provider_and_delivery_unconfigured_by_default() -> None:
    runtime = create_media_runtime(Settings(environment="test"))

    assert isinstance(runtime.service.storage, UnconfiguredPrivateObjectStorage)
    assert runtime.media_delivery is None
    assert runtime.media_cors_policy is None


def test_activation_has_no_in_process_seal_or_issuer() -> None:
    assert not hasattr(media_config, "MediaProviderActivationApproval")
    assert not hasattr(media_config, "_ACTIVATION_APPROVAL_SEAL")


def test_verified_provider_composition_stays_unavailable_without_peer_bound_transport() -> None:
    config = MediaProviderConfig.from_environment(_environment())
    verifier = _TestActivationVerifier(config.activation_fingerprint)
    factory_called = False

    def factory(**kwargs: object) -> object:
        nonlocal factory_called
        del kwargs
        factory_called = True
        return object()

    with pytest.raises(MediaStorageUnavailable, match="safe provider transport"):
        compose_private_object_storage(
            config,
            activation_verifier=verifier,
            client_factory=factory,
        )
    assert factory_called is False


def test_public_s3_adapter_cannot_bypass_activation_or_transport() -> None:
    config = MediaProviderConfig.from_environment(_environment())
    verifier = _TestActivationVerifier(config.activation_fingerprint)

    with pytest.raises(MediaStorageUnavailable, match="safe provider transport"):
        S3CompatiblePrivateObjectStorage(
            object(),
            bucket="ac-media",
            public_alias="https://media.test",
            endpoint_url="https://minio.test",
            activation_config=config,
            activation_verifier=verifier,
        )


def test_s3_adapter_uses_approved_resolver_not_caller_endpoint_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MediaProviderConfig.from_environment(_environment())
    verifier = _TestActivationVerifier(config.activation_fingerprint)
    monkeypatch.setattr(media_storage, "_safe_provider_transport_available", lambda: True)
    monkeypatch.setattr(
        media_config,
        "resolve_media_endpoint_addresses",
        lambda endpoint: ("8.8.8.8",),
    )
    with pytest.raises(MediaStorageUnavailable, match="do not match"):
        S3CompatiblePrivateObjectStorage(
            object(),
            bucket="ac-media",
            public_alias="https://media.test",
            endpoint_url="https://minio.test",
            endpoint_addresses=("1.1.1.1",),
            activation_config=config,
            activation_verifier=verifier,
        )
    adapter = S3CompatiblePrivateObjectStorage(
        object(),
        bucket="ac-media",
        public_alias="https://media.test",
        endpoint_url="https://minio.test",
        endpoint_addresses=("8.8.8.8",),
        activation_config=config,
        activation_verifier=verifier,
    )
    assert adapter._endpoint_addresses == ("8.8.8.8",)


def test_s3_adapter_rechecks_all_endpoint_addresses_before_each_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MediaProviderConfig.from_environment(_environment())
    verifier = _TestActivationVerifier(config.activation_fingerprint)
    answers = iter((("8.8.8.8",), ("1.1.1.1",)))
    monkeypatch.setattr(media_storage, "_safe_provider_transport_available", lambda: True)
    monkeypatch.setattr(
        media_config,
        "resolve_media_endpoint_addresses",
        lambda endpoint: next(answers),
    )
    adapter = S3CompatiblePrivateObjectStorage(
        object(),
        bucket="ac-media",
        public_alias="https://media.test",
        endpoint_url="https://minio.test",
        endpoint_addresses=("8.8.8.8",),
        activation_config=config,
        activation_verifier=verifier,
    )
    with pytest.raises(MediaStorageUnavailable, match="resolution changed"):
        adapter._assert_endpoint_safe()


def test_upload_adapter_output_rejects_unsigned_or_unbounded_targets() -> None:
    with pytest.raises(MediaStorageUnavailable):
        StorageUploadIntent(
            "http://provider.test/upload",
            "tenants/test/media/video/a/v/original",
            datetime.now(UTC) + timedelta(minutes=5),
            {"Content-Type": "video/mp4", "Content-Length": "1"},
        )


def test_upload_adapter_output_rejects_malformed_expiry_and_headers() -> None:
    with pytest.raises(MediaStorageUnavailable):
        StorageUploadIntent(
            "https://provider.test/upload?signature=opaque",
            "tenants/test/media/video/a/v/original",
            object(),  # type: ignore[arg-type]
            {"Content-Type": "video/mp4", "Content-Length": "1"},
        )

    with pytest.raises(MediaStorageUnavailable, match="not a constructible activation contract"):
        StorageUploadIntent(
            "https://provider.test/upload?signature=opaque",
            "tenants/test/media/video/a/v/original",
            datetime.now(UTC) + timedelta(minutes=5),
            {"Content-Type": "video/mp4", "Content-Length": "1"},
        )
    with pytest.raises(MediaStorageUnavailable, match="unapproved upload header"):
        StorageUploadIntent(
            "https://provider.test/upload?token=bounded",
            "tenants/test/media/video/a/v/original",
            datetime.now(UTC) + timedelta(minutes=5),
            {
                "Content-Type": "video/mp4",
                "Content-Length": "1",
                "Authorization": "opaque",
            },
            _contract=media_storage._LOCAL_UPLOAD_CONTRACT,
        )


def test_s3_upload_intent_binds_exact_path_query_and_headers() -> None:
    adapter = object.__new__(S3CompatiblePrivateObjectStorage)
    adapter._bucket = "ac-media"
    adapter._endpoint_url = "https://minio.test"
    adapter._access_key_id = "access-key"
    adapter._region = "us-east-1"
    object_key = "tenants/test/media/video/asset/version/original"
    today = datetime.now(UTC).strftime("%Y%m%d")
    amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    intent = StorageUploadIntent(
        "https://minio.test/ac-media/tenants/test/media/video/asset/version/original"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential="
        f"access-key%2F{today}%2Fus-east-1%2Fs3%2Faws4_request"
        f"&X-Amz-Date={amz_date}&X-Amz-Expires=300"
        "&X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost"
        f"&X-Amz-Signature={'a' * 64}",
        object_key,
        datetime.now(UTC) + timedelta(minutes=5),
        {"Content-Type": "video/mp4", "Content-Length": "7"},
        _contract=media_storage._S3_UPLOAD_CONTRACT,
    )

    adapter._validate_upload_intent(
        intent,
        object_key=object_key,
        content_type="video/mp4",
        content_length=7,
        checksum_sha256=None,
    )

    with pytest.raises(MediaStorageUnavailable, match="path"):
        adapter._validate_upload_intent(
            replace(intent, upload_url=intent.upload_url.replace("/original", "/other")),
            object_key=object_key,
            content_type="video/mp4",
            content_length=7,
            checksum_sha256=None,
        )

    with pytest.raises(MediaStorageUnavailable, match="query"):
        StorageUploadIntent(
            intent.upload_url + "&x-amz-expires=601",
            object_key,
            datetime.now(UTC) + timedelta(minutes=5),
            {"Content-Type": "video/mp4", "Content-Length": "7"},
            _contract=media_storage._S3_UPLOAD_CONTRACT,
        )

    extra_query = replace(intent, upload_url=intent.upload_url + "&token=unexpected")
    with pytest.raises(MediaStorageUnavailable, match="extra"):
        adapter._validate_upload_intent(
            extra_query,
            object_key=object_key,
            content_type="video/mp4",
            content_length=7,
            checksum_sha256=None,
        )


@pytest.mark.parametrize(
    "replacement",
    [
        ("AWS4-HMAC-SHA256", "AWS3-HMAC-SHA256"),
        ("access-key%2F", "other-key%2F"),
        ("%2Fs3%2Faws4_request", "%2Fec2%2Faws4_request"),
        (
            "X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost",
            "X-Amz-SignedHeaders=content-type",
        ),
        (
            "X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost",
            "X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost%3Bx-extra",
        ),
        (
            "X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost",
            "X-Amz-SignedHeaders=content-length%3Bcontent-type",
        ),
        (
            "X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost",
            "X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost%3Bhost",
        ),
    ],
)
def test_s3_upload_intent_rejects_sigv4_algorithm_scope_and_signed_header_tampering(
    replacement: tuple[str, str],
) -> None:
    adapter = object.__new__(S3CompatiblePrivateObjectStorage)
    adapter._bucket = "ac-media"
    adapter._endpoint_url = "https://minio.test"
    adapter._access_key_id = "access-key"
    adapter._region = "us-east-1"
    object_key = "tenants/test/media/video/asset/version/original"
    now = datetime.now(UTC)
    today = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    url = (
        "https://minio.test/ac-media/tenants/test/media/video/asset/version/original"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential="
        f"access-key%2F{today}%2Fus-east-1%2Fs3%2Faws4_request"
        f"&X-Amz-Date={amz_date}&X-Amz-Expires=300"
        "&X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost"
        f"&X-Amz-Signature={'a' * 64}"
    )
    intent = StorageUploadIntent(
        url.replace(*replacement),
        object_key,
        now + timedelta(minutes=5),
        {"Content-Type": "video/mp4", "Content-Length": "7"},
        _contract=media_storage._S3_UPLOAD_CONTRACT,
    )
    with pytest.raises(MediaStorageUnavailable):
        adapter._validate_upload_intent(
            intent,
            object_key=object_key,
            content_type="video/mp4",
            content_length=7,
            checksum_sha256=None,
        )


def test_s3_upload_intent_rejects_caller_supplied_host_header() -> None:
    object_key = "tenants/test/media/video/asset/version/original"
    now = datetime.now(UTC)
    today = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    with pytest.raises(MediaStorageUnavailable, match="unapproved upload header"):
        StorageUploadIntent(
            "https://minio.test/ac-media/tenants/test/media/video/asset/version/original"
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential="
            f"access-key%2F{today}%2Fus-east-1%2Fs3%2Faws4_request"
            f"&X-Amz-Date={amz_date}&X-Amz-Expires=300"
            "&X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost"
            f"&X-Amz-Signature={'a' * 64}",
            object_key,
            now + timedelta(minutes=5),
            {
                "Content-Type": "video/mp4",
                "Content-Length": "7",
                "Host": "attacker.test",
            },
            _contract=media_storage._S3_UPLOAD_CONTRACT,
        )


def test_s3_upload_intent_rejects_bad_timestamp_expiry_and_duplicate_queries() -> None:
    adapter = object.__new__(S3CompatiblePrivateObjectStorage)
    adapter._bucket = "ac-media"
    adapter._endpoint_url = "https://minio.test"
    adapter._access_key_id = "access-key"
    adapter._region = "us-east-1"
    object_key = "tenants/test/media/video/asset/version/original"
    now = datetime.now(UTC)
    today = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    base_url = (
        "https://minio.test/ac-media/tenants/test/media/video/asset/version/original"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential="
        f"access-key%2F{today}%2Fus-east-1%2Fs3%2Faws4_request"
        f"&X-Amz-Date={amz_date}&X-Amz-Expires=300"
        "&X-Amz-SignedHeaders=content-length%3Bcontent-type%3Bhost"
        f"&X-Amz-Signature={'a' * 64}"
    )
    invalid_timestamp = StorageUploadIntent(
        base_url.replace(amz_date, "20261340T250000Z"),
        object_key,
        now + timedelta(minutes=5),
        {"Content-Type": "video/mp4", "Content-Length": "7"},
        _contract=media_storage._S3_UPLOAD_CONTRACT,
    )
    with pytest.raises(MediaStorageUnavailable, match="timestamp"):
        adapter._validate_upload_intent(
            invalid_timestamp,
            object_key=object_key,
            content_type="video/mp4",
            content_length=7,
            checksum_sha256=None,
        )
    invalid_expiry = StorageUploadIntent(
        base_url.replace("X-Amz-Expires=300", "X-Amz-Expires=3601"),
        object_key,
        now + timedelta(minutes=5),
        {"Content-Type": "video/mp4", "Content-Length": "7"},
        _contract=media_storage._S3_UPLOAD_CONTRACT,
    )
    with pytest.raises(MediaStorageUnavailable, match="expiry"):
        adapter._validate_upload_intent(
            invalid_expiry,
            object_key=object_key,
            content_type="video/mp4",
            content_length=7,
            checksum_sha256=None,
        )
    with pytest.raises(MediaStorageUnavailable, match="duplicate"):
        StorageUploadIntent(
            base_url + "&X-Amz-Date=" + amz_date,
            object_key,
            now + timedelta(minutes=5),
            {"Content-Type": "video/mp4", "Content-Length": "7"},
            _contract=media_storage._S3_UPLOAD_CONTRACT,
        )


def test_s3_caption_copy_returns_verified_head_metadata() -> None:
    class Client:
        def copy_object(self, **kwargs: object) -> dict[str, object]:
            del kwargs
            return {"ETag": '"copy"'}

        def head_object(self, **kwargs: object) -> dict[str, object]:
            del kwargs
            return {
                "ContentType": "text/vtt",
                "ContentLength": 8,
                "ChecksumSHA256": "a" * 64,
                "VersionId": "version-1",
            }

    adapter = object.__new__(S3CompatiblePrivateObjectStorage)
    adapter._client = Client()
    adapter._bucket = "ac-media"
    adapter._public_alias = "https://media.test"
    adapter._endpoint_url = None
    adapter._endpoint_addresses = ()

    copied = adapter.copy(
        source_key="tenants/test/captions/en.vtt",
        destination_key="tenants/test/media/video/asset/version/original/captions/en.vtt",
        content_type="text/vtt",
    )

    assert copied.content_length == 8
    assert copied.checksum_sha256 == "a" * 64
    assert copied.storage_version_id == "version-1"


def test_ffmpeg_preflight_reserves_disk_budget_before_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    storage.put(object_key=source_key, body=b"fixture", content_type="video/mp4")
    runner_called = False

    def runner(command: tuple[str, ...], cwd: Path) -> None:
        nonlocal runner_called
        del command, cwd
        runner_called = True

    monkeypatch.setattr(
        media_processing.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100, used=91, free=9),
    )
    with pytest.raises(MediaQuotaExceeded, match="reserve"):
        FFmpegMediaProcessor(
            profiles=DEFAULT_TRANSCODE_PROFILES[:1],
            command_runner=runner,
            quota=ProcessingQuota(
                max_source_bytes=100,
                max_output_bytes=100,
                max_temp_bytes=200,
            ),
        ).process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
        )
    assert runner_called is False
    with pytest.raises(MediaStorageUnavailable):
        StorageUploadIntent(
            "https://provider.test/upload?signature=opaque",
            "tenants/test/media/video/a/v/original",
            datetime.now(UTC) + timedelta(minutes=5),
            [],  # type: ignore[arg-type]
        )
    with pytest.raises(MediaStorageUnavailable):
        StorageUploadIntent(
            "https://provider.test/upload?signature=opaque",
            "tenants/test/media/video/a/v/original",
            datetime.now(UTC) + timedelta(minutes=5),
            {
                "Content-Type": "video/mp4",
                "content-type": "video/mp4",
                "Content-Length": "1",
            },
        )


def test_ffmpeg_workspace_budget_ledger_prevents_concurrent_overcommit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        media_processing.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=1_000, used=900, free=100),
    )
    quota = ProcessingQuota(
        max_source_bytes=10,
        max_output_bytes=50,
        max_temp_bytes=100,
        max_output_files=1,
    )
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    first = media_processing._reserve_workspace_budget(
        first_workspace, quota, source_bytes=10, output_file_count=1
    )
    try:
        with pytest.raises(MediaQuotaExceeded, match="reserve"):
            media_processing._reserve_workspace_budget(
                second_workspace, quota, source_bytes=10, output_file_count=1
            )
    finally:
        first.release()
    second = media_processing._reserve_workspace_budget(
        second_workspace, quota, source_bytes=10, output_file_count=1
    )
    second.release()


def test_ffmpeg_workspace_budget_consumption_and_error_release_are_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        media_processing.shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=1_000, used=100, free=900),
    )
    quota = ProcessingQuota(
        max_source_bytes=10,
        max_output_bytes=50,
        max_temp_bytes=100,
        max_output_files=1,
    )
    workspace = tmp_path / "worker"
    workspace.mkdir()
    reservation = media_processing._reserve_workspace_budget(
        workspace, quota, source_bytes=10, output_file_count=1
    )
    initial = reservation.bytes_reserved
    (workspace / "source.bin").write_bytes(b"1234567890")
    reservation.consume(10)
    assert reservation.bytes_reserved == initial - 10
    assert reservation.path.stat().st_size == initial - 10
    with pytest.raises(MediaQuotaExceeded, match="reserved disk budget"):
        reservation.consume(reservation.bytes_reserved + 1)
    reservation.release()
    assert not reservation.path.exists()
    retry = media_processing._reserve_workspace_budget(
        workspace, quota, source_bytes=10, output_file_count=1
    )
    retry.release()


def test_runtime_composes_delivery_policy_only_for_complete_enabled_config() -> None:
    settings = Settings(
        environment="test",
        media_provider_enabled=True,
        media_provider="minio",
        media_storage_endpoint="https://minio.test",
        media_storage_approved_endpoint_hosts="minio.test",
        media_storage_bucket="ac-media",
        media_storage_region="us-east-1",
        media_storage_access_key_id="access-key",
        media_storage_secret_access_key="x" * 32,
        media_delivery_origin="https://media.test",
        media_cors_origins="https://app.test",
        media_governance_reference="AC-GOV-AUD-001",
        media_gap_reference="GAP-MEDIA-001",
        media_allow_range_requests=False,
    )
    runtime = create_media_runtime(
        settings,
        client_factory=lambda **kwargs: object(),
        lifecycle_hooks=InMemoryMediaLifecycleHooks(),
        retention_policy=MediaRetentionPolicy("test-retention"),
    )

    assert isinstance(runtime.service.storage, UnconfiguredPrivateObjectStorage)
    assert runtime.media_delivery is None
    assert runtime.media_cors_policy is None


def test_approved_runtime_without_explicit_delivery_handler_stays_unavailable() -> None:
    settings = Settings(
        environment="test",
        media_provider_enabled=True,
        media_provider="minio",
        media_storage_endpoint="https://minio.test",
        media_storage_approved_endpoint_hosts="minio.test",
        media_storage_bucket="ac-media",
        media_storage_region="us-east-1",
        media_storage_access_key_id="access-key",
        media_storage_secret_access_key="x" * 32,
        media_delivery_origin="https://media.test",
        media_cors_origins="https://app.test",
        media_governance_reference="AC-GOV-AUD-001",
        media_gap_reference="GAP-MEDIA-001",
    )
    config = MediaProviderConfig.from_settings(settings)
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    runtime = create_media_runtime(
        settings,
        storage=InMemoryPrivateObjectStorage(signer),
        lifecycle_hooks=InMemoryMediaLifecycleHooks(),
        retention_policy=MediaRetentionPolicy("test-retention"),
        activation_verifier=_TestActivationVerifier(config.activation_fingerprint),
    )

    assert runtime.provider_activation_verified is True
    assert runtime.media_delivery is None
    assert runtime.media_cors_policy is None
    assert runtime.service.delivery_port is None


def test_approved_runtime_rejects_noop_retention_before_provider_composition() -> None:
    settings = Settings(
        environment="test",
        media_provider_enabled=True,
        media_provider="minio",
        media_storage_endpoint="https://minio.test",
        media_storage_approved_endpoint_hosts="minio.test",
        media_storage_bucket="ac-media",
        media_storage_region="us-east-1",
        media_storage_access_key_id="access-key",
        media_storage_secret_access_key="x" * 32,
        media_delivery_origin="https://media.test",
        media_cors_origins="https://app.test",
        media_governance_reference="AC-GOV-AUD-001",
        media_gap_reference="GAP-MEDIA-001",
    )
    config = MediaProviderConfig.from_settings(settings)
    verifier: MediaProviderActivationVerifier = _TestActivationVerifier(
        config.activation_fingerprint
    )
    factory_called = False

    def factory(**kwargs: object) -> object:
        nonlocal factory_called
        del kwargs
        factory_called = True
        return object()

    with pytest.raises(MediaConfigurationError, match="non-noop retention"):
        create_media_runtime(
            settings,
            activation_verifier=verifier,
            client_factory=factory,
        )
    assert factory_called is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"AC_MEDIA_STORAGE_BUCKET": None},
        {"AC_MEDIA_STORAGE_SECRET_ACCESS_KEY": "short"},
        {"AC_MEDIA_GOVERNANCE_REFERENCE": "wrong"},
        {"AC_MEDIA_GAP_REFERENCE": "wrong"},
        {"AC_MEDIA_CORS_ORIGINS": "*"},
        {"AC_MEDIA_CORS_ORIGINS": "https://app.test,https://app.test"},
        {"AC_MEDIA_DELIVERY_ORIGIN": "http://media.test"},
    ],
)
def test_enabled_media_configuration_fails_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MediaProviderConfig.from_environment(_environment(**overrides))


def test_deployment_media_storage_endpoint_must_use_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        MediaProviderConfig.from_environment(
            _environment(
                AC_ENVIRONMENT="production",
                AC_MEDIA_STORAGE_ENDPOINT="http://minio.test",
            )
        )


def test_reference_strings_never_activate_s3_composition() -> None:
    config = MediaProviderConfig.from_environment(
        _environment(
            AC_MEDIA_PROVIDER="s3",
            AC_MEDIA_STORAGE_ENDPOINT="https://s3.test",
            AC_MEDIA_STORAGE_APPROVED_ENDPOINT_HOSTS="s3.test",
        )
    )
    calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    storage = compose_private_object_storage(config, client_factory=factory)

    assert isinstance(storage, UnconfiguredPrivateObjectStorage)
    assert calls == []
    assert "x" * 32 not in repr(config)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://minio.test",
        "https://localhost:9000",
        "https://127.0.0.1:9000",
        "https://10.0.0.10:9000",
        "https://169.254.169.254/latest",
        "https://evil.example",
        "https://s3.amazonaws.com",
    ],
)
def test_storage_endpoint_rejects_private_or_unapproved_targets(endpoint: str) -> None:
    with pytest.raises(ValueError):
        MediaProviderConfig.from_environment(
            _environment(
                AC_MEDIA_STORAGE_ENDPOINT=endpoint,
                AC_MEDIA_STORAGE_APPROVED_ENDPOINT_HOSTS="minio.test",
            )
        )


def test_storage_dns_resolution_rejects_private_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def resolve(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        del args, kwargs
        return [(2, 1, 6, "", ("10.0.0.7", 443))]

    monkeypatch.setattr(media_config.socket, "getaddrinfo", resolve)
    with pytest.raises(ValueError, match="private or non-routable"):
        resolve_media_endpoint_addresses("https://minio.test")


def test_storage_dns_resolution_rejects_answer_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(("8.8.8.8", "1.1.1.1"))

    def resolve(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        del kwargs
        port = args[1] if len(args) > 1 else 443
        return [(2, 1, 6, "", (next(answers), port))]

    monkeypatch.setattr(media_config.socket, "getaddrinfo", resolve)
    with pytest.raises(ValueError, match="changed during validation"):
        resolve_media_endpoint_addresses("https://minio.test")


def test_s3_composition_does_not_call_factory_without_audited_approval() -> None:
    config = MediaProviderConfig.from_environment(_environment())

    def factory(**kwargs: object) -> object:
        del kwargs
        raise RuntimeError("adapter rejected credentials")

    storage = compose_private_object_storage(config, client_factory=factory)
    assert isinstance(storage, UnconfiguredPrivateObjectStorage)


def test_test_transcoder_emits_hls_ladder_and_caption_passthrough() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    caption_key = "tenants/tenant/captions/en.vtt"
    source = b"fixture-video-bytes"
    storage.put(object_key=source_key, body=source, content_type="video/mp4")
    storage.put(object_key=caption_key, body=b"WEBVTT\n", content_type="text/vtt")

    result = LocalTranscodingProcessor(
        profiles=DEFAULT_TRANSCODE_PROFILES[:2],
        quota=ProcessingQuota(max_source_bytes=100, max_output_bytes=10_000),
    ).process(
        storage=storage,
        version_id=uuid4(),
        purpose=MediaPurpose.VIDEO,
        source_key=source_key,
        content_type="video/mp4",
        crop=None,
        captions=(
            CaptionPassthrough(
                language="en",
                kind="captions",
                content_type="text/vtt",
                source_key=caption_key,
                is_default=True,
            ),
        ),
    )

    assert result.hls_manifest is not None
    assert len(result.hls_manifest.renditions) == 2
    assert len(result.captions) == 1
    assert result.renditions[0].protocol == "hls"
    assert result.renditions[1].protocol == "progressive"
    assert storage.head(result.hls_manifest.master_object_key) is not None
    assert storage.head(result.captions[0].object_key) is not None
    assert set(result.object_keys) >= {
        result.hls_manifest.master_object_key,
        result.captions[0].object_key,
    }
    assert all(
        f"{source_key}/renditions/hls/{profile.name}/index.m3u8" in result.object_keys
        and f"{source_key}/renditions/hls/{profile.name}/segment-000.ts" in result.object_keys
        for profile in DEFAULT_TRANSCODE_PROFILES[:2]
    )
    assert result.output_bytes is not None and result.output_bytes >= len(b"WEBVTT\n")
    master = storage.read(result.hls_manifest.master_object_key).decode()
    assert "360p/index.m3u8" in master
    assert "720p/index.m3u8" in master


def test_hls_inventory_follows_only_existing_private_relative_objects() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    master_key = f"{source_key}/renditions/master.m3u8"
    playlist_key = f"{source_key}/renditions/hls/360p/index.m3u8"
    segment_key = f"{source_key}/renditions/hls/360p/segment-000.ts"
    storage.put(
        object_key=master_key,
        body=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nhls/360p/index.m3u8\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(
        object_key=playlist_key,
        body=b"#EXTM3U\n#EXTINF:1,\nsegment-000.ts\n#EXT-X-ENDLIST\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(object_key=segment_key, body=b"segment", content_type="video/mp2t")

    assert inspect_hls_playlist_inventory(
        storage,
        root_key=master_key,
        namespace_prefix=source_key,
    ) == (master_key, playlist_key, segment_key)


def test_hls_inventory_rejects_external_playlist_uris() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    master_key = f"{source_key}/renditions/master.m3u8"
    storage.put(
        object_key=master_key,
        body=b"#EXTM3U\nhttps://provider.example/segment.ts\n",
        content_type="application/vnd.apple.mpegurl",
    )

    with pytest.raises(MediaProcessingError, match="external URI"):
        inspect_hls_playlist_inventory(
            storage,
            root_key=master_key,
            namespace_prefix=source_key,
        )


def test_hls_inventory_bounds_duration_and_head_work() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    master_key = f"{source_key}/renditions/master.m3u8"
    segment_key = f"{source_key}/renditions/segment.ts"
    storage.put(
        object_key=master_key,
        body=b"#EXTM3U\n#EXTINF:6.0,\nsegment.ts\n#EXT-X-ENDLIST\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(object_key=segment_key, body=b"segment", content_type="video/mp2t")

    with pytest.raises(MediaProcessingError, match="duration"):
        inspect_hls_playlist_inventory(
            storage,
            root_key=master_key,
            namespace_prefix=source_key,
            max_duration_seconds=5,
        )
    with pytest.raises(MediaProcessingError, match="work limit"):
        inspect_hls_playlist_inventory(
            storage,
            root_key=master_key,
            namespace_prefix=source_key,
            max_head_operations=1,
        )


def test_hls_inventory_rejects_unbounded_live_playlists() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    playlist_key = f"{source_key}/renditions/hls/360p/index.m3u8"
    segment_key = f"{source_key}/renditions/hls/360p/segment-000.ts"
    storage.put(
        object_key=playlist_key,
        body=b"#EXTM3U\n#EXTINF:1,\nsegment-000.ts\n",
        content_type="application/vnd.apple.mpegurl",
    )
    storage.put(object_key=segment_key, body=b"segment", content_type="video/mp2t")

    with pytest.raises(MediaProcessingError, match="bounded VOD"):
        inspect_hls_playlist_inventory(
            storage,
            root_key=playlist_key,
            namespace_prefix=source_key,
        )


def test_hls_inventory_rejects_playlist_checksum_mismatch() -> None:
    source_key = "tenants/tenant/media/video/asset/version/original"
    playlist_key = f"{source_key}/renditions/hls/360p/index.m3u8"

    class TamperedChecksumStorage(InMemoryPrivateObjectStorage):
        def head(self, object_key: str) -> StoredObjectMetadata | None:
            metadata = super().head(object_key)
            if metadata is not None and object_key == playlist_key:
                return StoredObjectMetadata(
                    metadata.object_key,
                    metadata.content_type,
                    metadata.content_length,
                    "0" * 64,
                    metadata.storage_version_id,
                )
            return metadata

    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = TamperedChecksumStorage(signer)
    storage.put(
        object_key=playlist_key,
        body=b"#EXTM3U\n#EXT-X-ENDLIST\n",
        content_type="application/vnd.apple.mpegurl",
    )

    with pytest.raises(MediaProcessingError, match="changed while it was read"):
        inspect_hls_playlist_inventory(
            storage,
            root_key=playlist_key,
            namespace_prefix=source_key,
        )


def test_test_transcoder_rejects_processing_quota_before_output() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    storage.put(object_key=source_key, body=b"0123456789", content_type="video/mp4")

    with pytest.raises(MediaQuotaExceeded):
        LocalTranscodingProcessor(
            profiles=DEFAULT_TRANSCODE_PROFILES[:1],
            quota=ProcessingQuota(max_source_bytes=5),
        ).process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
        )


def test_test_transcoder_cleans_partial_outputs_when_caption_quota_fails() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    caption_key = "tenants/tenant/captions/en.vtt"
    storage.put(object_key=source_key, body=b"fixture", content_type="video/mp4")
    storage.put(object_key=caption_key, body=b"WEBVTT\n", content_type="text/vtt")

    with pytest.raises(MediaQuotaExceeded):
        LocalTranscodingProcessor(
            profiles=DEFAULT_TRANSCODE_PROFILES[:1],
            quota=ProcessingQuota(
                max_source_bytes=100,
                max_output_bytes=10_000,
                max_caption_bytes=3,
            ),
        ).process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
            captions=(
                CaptionPassthrough(
                    language="en",
                    kind="captions",
                    content_type="text/vtt",
                    source_key=caption_key,
                ),
            ),
        )

    assert storage.head(f"{source_key}/renditions/master.m3u8") is None
    assert storage.head(f"{source_key}/renditions/hls/360p/index.m3u8") is None
    assert storage.head(f"{source_key}/renditions/hls/360p/segment-000.ts") is None


def test_test_transcoder_cleans_partial_outputs_when_storage_fails() -> None:
    class FailingStorage(InMemoryPrivateObjectStorage):
        writes = 0

        def put(self, **kwargs: object):  # type: ignore[no-untyped-def]
            self.writes += 1
            if self.writes == 2:
                raise RuntimeError("fixture storage failure")
            return super().put(**kwargs)

    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = FailingStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    storage.put(object_key=source_key, body=b"fixture", content_type="video/mp4")
    storage.writes = 0

    with pytest.raises(RuntimeError):
        LocalTranscodingProcessor(
            profiles=DEFAULT_TRANSCODE_PROFILES[:1],
            quota=ProcessingQuota(max_source_bytes=100, max_output_bytes=10_000),
        ).process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
        )

    assert storage.head(f"{source_key}/renditions/hls/360p/segment-000.ts") is None


def test_caption_passthrough_rejects_cross_tenant_source() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant-a/media/video/asset/version/original"
    caption_key = "tenants/tenant-b/captions/en.vtt"
    storage.put(object_key=source_key, body=b"fixture", content_type="video/mp4")
    storage.put(object_key=caption_key, body=b"WEBVTT\n", content_type="text/vtt")

    with pytest.raises(MediaProcessingError, match="tenant scope"):
        LocalTranscodingProcessor(
            profiles=DEFAULT_TRANSCODE_PROFILES[:1],
            include_progressive=False,
            quota=ProcessingQuota(max_source_bytes=100, max_output_bytes=10_000),
        ).process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
            captions=(
                CaptionPassthrough(
                    language="en",
                    kind="captions",
                    content_type="text/vtt",
                    source_key=caption_key,
                ),
            ),
        )


def test_local_scanner_binds_clean_verdict_to_storage_metadata() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    key = "tenants/tenant/media/image/asset/version/original"
    body = b"\x89PNG\r\n\x1a\nfixture"
    metadata = storage.put(object_key=key, body=body, content_type="image/png")
    scanner = SignatureContentScanner()

    clean = scanner.scan(
        storage=storage,
        object_key=key,
        declared_content_type="image/png",
        content_length=len(body),
        checksum_sha256=metadata.checksum_sha256,
    )
    mismatched = scanner.scan(
        storage=storage,
        object_key=key,
        declared_content_type="image/png",
        content_length=len(body),
        checksum_sha256="0" * 64,
    )

    assert clean.clean is True
    assert mismatched.clean is False
    assert mismatched.reason_code == "CHECKSUM_MISMATCH"


def test_ffmpeg_command_boundary_is_injected_and_never_uses_shell() -> None:
    processor = FFmpegMediaProcessor(profiles=DEFAULT_TRANSCODE_PROFILES[:1])
    command = processor.build_hls_command(
        input_path=Path("source.bin"),
        playlist_path=Path("hls/index.m3u8"),
        segment_pattern=Path("hls/segment-%05d.ts"),
        profile=DEFAULT_TRANSCODE_PROFILES[0],
    )

    assert command[0] == "ffmpeg"
    assert "-nostdin" in command
    assert "-hls_playlist_type" in command
    assert "-hls_segment_filename" in command


def test_ffmpeg_worker_boundary_stores_injected_local_outputs() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    storage.put(object_key=source_key, body=b"fixture", content_type="video/mp4")

    def runner(command: tuple[str, ...], cwd: Path) -> None:
        del cwd
        if "-f" in command and "hls" in command:
            playlist = Path(command[-1])
            segment_pattern = Path(command[command.index("-hls_segment_filename") + 1])
            playlist.parent.mkdir(parents=True, exist_ok=True)
            playlist.write_text(
                "#EXTM3U\n#EXTINF:6.0,\nsegment-00000.ts\n#EXT-X-ENDLIST\n",
                encoding="utf-8",
            )
            segment_pattern.parent.mkdir(parents=True, exist_ok=True)
            segment_pattern.with_name("segment-00000.ts").write_bytes(b"segment")
        else:
            Path(command[-1]).write_bytes(b"progressive")

    result = FFmpegMediaProcessor(
        profiles=DEFAULT_TRANSCODE_PROFILES[:1],
        command_runner=runner,
        video_probe=lambda path: VideoMetadata(640, 360, 6.0),
        quota=ProcessingQuota(max_source_bytes=100, max_output_bytes=10_000),
    ).process(
        storage=storage,
        version_id=uuid4(),
        purpose=MediaPurpose.VIDEO,
        source_key=source_key,
        content_type="video/mp4",
        crop=None,
    )

    assert {row.protocol for row in result.renditions} == {"hls", "progressive"}
    assert result.output_bytes is not None
    assert storage.head(result.renditions[0].object_key) is not None


def test_ffmpeg_worker_cleans_outputs_when_a_later_rendition_fails() -> None:
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    source_key = "tenants/tenant/media/video/asset/version/original"
    storage.put(object_key=source_key, body=b"fixture", content_type="video/mp4")
    hls_calls = 0

    def runner(command: tuple[str, ...], cwd: Path) -> None:
        nonlocal hls_calls
        del cwd
        if "-f" in command and "hls" in command:
            hls_calls += 1
            if hls_calls == 2:
                raise RuntimeError("fixture ffmpeg failure")
            playlist = Path(command[-1])
            segment_pattern = Path(command[command.index("-hls_segment_filename") + 1])
            playlist.parent.mkdir(parents=True, exist_ok=True)
            playlist.write_text(
                "#EXTM3U\n#EXTINF:6.0,\nsegment-00000.ts\n#EXT-X-ENDLIST\n",
                encoding="utf-8",
            )
            segment_pattern.parent.mkdir(parents=True, exist_ok=True)
            segment_pattern.with_name("segment-00000.ts").write_bytes(b"segment")

    with pytest.raises(RuntimeError):
        FFmpegMediaProcessor(
            profiles=DEFAULT_TRANSCODE_PROFILES[:2],
            include_progressive=False,
            command_runner=runner,
            video_probe=lambda path: VideoMetadata(
                640 if path.parent.name == "360p" else 1280,
                360 if path.parent.name == "360p" else 720,
                6.0,
            ),
            quota=ProcessingQuota(max_source_bytes=100, max_output_bytes=10_000),
        ).process(
            storage=storage,
            version_id=uuid4(),
            purpose=MediaPurpose.VIDEO,
            source_key=source_key,
            content_type="video/mp4",
            crop=None,
        )

    assert storage.head(f"{source_key}/renditions/hls/360p/index.m3u8") is None
    assert storage.head(f"{source_key}/renditions/hls/360p/segment-00000.ts") is None


def test_signed_delivery_cors_and_range_are_exact_and_expiring() -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    authorization = create_media_authorization_context(
        tenant_id="tenant-1", person_id="person-1", session_id="session-1"
    )
    media_version = MediaAssetVersion(MediaAssetId("asset-1"), MediaVersionId("version-1"))
    delivery = SignedMediaDeliveryPort(
        signer=MediaSigner("media-test-signer-value-32-bytes-long!!"),
        delivery_origin="https://media.test",
        playback_ttl=timedelta(minutes=5),
    )
    signed = delivery.issue(
        authorization=authorization,
        activity_id="activity-1",
        activity_version="v1",
        media_version=media_version,
        object_key="tenants/tenant/media/video/asset/version/original",
        now=now,
    )

    assert str(signed.url).startswith("https://media.test/")
    claims = delivery.verify(signed, now=now, authorization=authorization)
    assert claims["version_id"] == "version-1"
    with pytest.raises(MediaForbidden):
        delivery.verify(
            signed,
            now=now,
            authorization=create_media_authorization_context(
                tenant_id="tenant-2", person_id="person-1", session_id="session-1"
            ),
        )
    with pytest.raises(MediaRangeError):
        RangePolicy().validate_header("bytes=0-10,20-30")
    assert RangePolicy().validate_header("bytes=0-10") == (0, 10)
    with pytest.raises(ValueError):
        MediaCorsPolicy(("https://app.test", "https://app.test"))
    assert MediaCorsPolicy(("https://app.test",)).allows_origin("https://app.test")
    assert MediaCorsPolicy(("http://localhost:3000",)).allows_origin("http://localhost:3000")


def test_lifecycle_hooks_schedule_deletion_without_overwriting_history() -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    tenant_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    reference = MediaObjectReference(
        tenant_id, asset_id, version_id, f"tenants/{tenant_id}/media/v/original"
    )
    hooks = InMemoryMediaLifecycleHooks()
    hooks.version_superseded(
        reference,
        superseded_at=now,
        policy=MediaRetentionPolicy(
            policy_id="media-retention-test",
            superseded_after=timedelta(days=7),
            delete_objects=True,
        ),
    )

    assert [event.action for event in hooks.events] == [
        MediaLifecycleAction.VERSION_SUPERSEDED,
        MediaLifecycleAction.DELETE_SCHEDULED,
    ]
    assert hooks.events[0].reference == reference


def test_lifecycle_inventory_includes_hls_playlists_and_segments() -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    tenant_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    source_key = f"tenants/{tenant_id}/media/video/asset/version/original"
    reference = MediaObjectReference(tenant_id, asset_id, version_id, source_key)
    playlist = f"{source_key}/renditions/hls/360p/index.m3u8"
    segment = f"{source_key}/renditions/hls/360p/segment-000.ts"
    hooks = InMemoryMediaLifecycleHooks()
    hooks.objects_materialized(reference, (playlist, segment))

    assert {item.object_key for item in hooks.object_references(reference)} == {
        source_key,
        playlist,
        segment,
    }
    hooks.version_superseded(
        reference,
        superseded_at=now,
        policy=MediaRetentionPolicy(
            policy_id="media-retention-test",
            superseded_after=timedelta(days=7),
            delete_objects=True,
        ),
    )
    scheduled_keys = {
        event.reference.object_key
        for event in hooks.events
        if event.action is MediaLifecycleAction.DELETE_SCHEDULED
    }
    assert scheduled_keys == {source_key, playlist, segment}


def test_due_deletion_worker_removes_bytes_but_returns_completion_history() -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    tenant_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    key = f"tenants/{tenant_id}/media/video/asset/version/original"
    storage.put(object_key=key, body=b"fixture", content_type="video/mp4")
    reference = MediaObjectReference(tenant_id, asset_id, version_id, key)
    event = MediaLifecycleEvent(
        action=MediaLifecycleAction.DELETE_SCHEDULED,
        reference=reference,
        occurred_at=now,
        not_before=now,
        policy_id="media-retention-test",
    )

    completed = MediaObjectDeletionWorker(storage).delete_due((event,), now=now)

    assert storage.head(key) is None
    assert completed[0].action is MediaLifecycleAction.DELETE_COMPLETED
    assert completed[0].reference == reference


def test_due_deletion_worker_does_not_repeat_completed_object_deletion() -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    tenant_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    key = f"tenants/{tenant_id}/media/video/asset/version/original"
    storage.put(object_key=key, body=b"fixture", content_type="video/mp4")
    reference = MediaObjectReference(tenant_id, asset_id, version_id, key)
    scheduled = MediaLifecycleEvent(
        action=MediaLifecycleAction.DELETE_SCHEDULED,
        reference=reference,
        occurred_at=now,
        not_before=now,
        policy_id="media-retention-test",
    )
    completed = MediaLifecycleEvent(
        action=MediaLifecycleAction.DELETE_COMPLETED,
        reference=reference,
        occurred_at=now,
        policy_id="media-retention-test",
    )

    assert MediaObjectDeletionWorker(storage).delete_due((scheduled, completed), now=now) == ()
    assert storage.head(key) is not None


def test_due_deletion_worker_retries_recorded_output_cleanup() -> None:
    now = datetime(2026, 9, 3, 12, tzinfo=UTC)
    signer = MediaSigner("media-test-signer-value-32-bytes-long!!")
    storage = InMemoryPrivateObjectStorage(signer)
    tenant_id, asset_id, version_id = uuid4(), uuid4(), uuid4()
    source_key = f"tenants/{tenant_id}/media/video/asset/version/original"
    orphan_key = f"{source_key}/renditions/orphan.mp4"
    storage.put(object_key=orphan_key, body=b"partial", content_type="video/mp4")
    reference = MediaObjectReference(tenant_id, asset_id, version_id, source_key)
    hooks = InMemoryMediaLifecycleHooks()
    hooks.outputs_cleanup_failed(
        reference,
        object_keys=(orphan_key,),
        reason_code="MEDIA_OUTPUT_CLEANUP_FAILED",
    )

    completed = MediaObjectDeletionWorker(storage).delete_due(tuple(hooks.events), now=now)

    assert storage.head(orphan_key) is None
    assert completed[0].reference.object_key == orphan_key
    assert completed[0].reason_code == "MEDIA_OUTPUT_CLEANUP_FAILED"


def test_media_telemetry_is_bounded_but_not_canonical_progress(tmp_path: Path) -> None:
    path = tmp_path / "media-events.jsonl"
    exporter = JsonlMediaTelemetryExporter(path)
    event = MediaTelemetryRecorder(exporter).emit(
        "media.processing.completed",
        operation="processing",
        outcome="succeeded",
        status="ready",
        protocol="hls",
        rendition_count=3,
    )

    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["name"] == event.name
    assert "progress" not in row
    assert "object_key" not in row
    assert "token" not in row


def test_media_telemetry_export_failure_is_fail_soft() -> None:
    class BrokenExporter:
        def export(self, event: object) -> None:
            del event
            raise RuntimeError("adapter unavailable")

    recorder = MediaTelemetryRecorder(BrokenExporter())
    event = recorder.emit(
        "media.delivery.failed",
        operation="delivery",
        outcome="failed",
        reason_code="origin_error",
    )

    assert event.outcome == "failed"
    assert recorder.last_export_error == "adapter unavailable"
