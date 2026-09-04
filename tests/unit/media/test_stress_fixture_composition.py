from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ac_platform.application.settings import Settings
from ac_platform.media import stress_fixtures
from ac_platform.media.contracts import (
    MediaAssetId,
    MediaAssetVersion,
    MediaAuthorizationContext,
    MediaVersionId,
    PlaybackGrantDescriptor,
    create_media_authorization_context,
)
from ac_platform.media.stress_fixtures import (
    FixturePlaybackGrantVerifier,
    FixtureProviderActivationVerifier,
    MediaStressFixtureDenied,
    compose_staging_test_fixture_source,
    compose_staging_test_fixture_source_from_settings,
)


@dataclass
class _ProviderGate:
    verified: bool = True

    def verify_fixture_provider_activation(
        self,
        *,
        authorization_context: MediaAuthorizationContext,
        playback_grant: PlaybackGrantDescriptor,
        environment: str,
        fixture_id: str,
        manifest_sha256: str,
    ) -> bool:
        return self.verified and playback_grant.authorization == authorization_context


@dataclass
class _GrantGate:
    verified: bool = True

    def verify_fixture_playback_grant(
        self,
        *,
        authorization_context: MediaAuthorizationContext,
        playback_grant: PlaybackGrantDescriptor,
        fixture_id: str,
        source_sha256: str,
        manifest_sha256: str,
        content_type: str,
        width: int,
        height: int,
        duration_seconds: float,
    ) -> bool:
        return self.verified and playback_grant.authorization == authorization_context


AUTHORIZATION_CONTEXT = create_media_authorization_context(
    tenant_id="tenant-fixture",
    person_id="person-fixture",
    session_id="session-fixture",
)
PLAYBACK_GRANT = PlaybackGrantDescriptor(
    grant_id="grant-fixture",
    authorization=AUTHORIZATION_CONTEXT,
    activity_id="activity-fixture",
    activity_version="activity-v1",
    media_version=MediaAssetVersion(
        asset_id=MediaAssetId("asset-fixture"),
        version_id=MediaVersionId("asset-v1"),
    ),
    issued_at=datetime(2026, 1, 1, tzinfo=UTC),
    expires_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=1),
)


def _stub_approved_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Stub only the already-verified registry result; gates remain real."""

    cache_root = tmp_path / ".artifacts"
    cache_root.mkdir()
    source = SimpleNamespace(
        fixture_id="generated-16x9-4s",
        local_path=cache_root / "generated-16x9-4s.mp4",
        content_type="video/mp4",
        width=320,
        height=180,
        duration_seconds=4.0,
        source_sha256="b" * 64,
        manifest_sha256="a" * 64,
        test_only=True,
        provider_activation_required=True,
        playback_grant_required=True,
    )
    monkeypatch.setattr(stress_fixtures, "_CACHE_ROOT_BOUNDARY", cache_root)
    monkeypatch.setattr(
        stress_fixtures,
        "_load_registry_fixture",
        lambda fixture_id: ({"id": fixture_id}, "a" * 64),
    )
    monkeypatch.setattr(
        stress_fixtures,
        "_verify_registry_fixture",
        lambda fixture, manifest_sha256, *, cache_root: source,
    )
    return cache_root


def _compose(
    *,
    cache_root: Path,
    provider: object | None = None,
    grant: object | None = None,
    environment: str = "test",
    enabled: bool = True,
    authorization_context: MediaAuthorizationContext = AUTHORIZATION_CONTEXT,
    playback_grant: PlaybackGrantDescriptor = PLAYBACK_GRANT,
):
    return compose_staging_test_fixture_source(
        environment=environment,
        enabled=enabled,
        fixture_id="generated-16x9-4s",
        cache_root=cache_root,
        provider_activation_verifier=(provider or _ProviderGate()),
        playback_grant_verifier=(grant or _GrantGate()),
        authorization_context=authorization_context,
        playback_grant=playback_grant,
    )


def test_composition_requires_typed_verifiers_and_approved_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = _stub_approved_registry(monkeypatch, tmp_path)

    source = _compose(cache_root=cache_root)

    assert source.fixture_id == "generated-16x9-4s"
    assert source.source_sha256 == "b" * 64
    assert source.test_only is True
    assert source.provider_activation_required is True
    assert source.playback_grant_required is True
    assert isinstance(_ProviderGate(), FixtureProviderActivationVerifier)
    assert isinstance(_GrantGate(), FixturePlaybackGrantVerifier)


@pytest.mark.parametrize(
    ("environment", "enabled", "provider", "grant", "message"),
    [
        ("production", True, _ProviderGate(), _GrantGate(), "production"),
        ("test", False, _ProviderGate(), _GrantGate(), "explicit opt-in"),
        ("test", True, _ProviderGate(False), _GrantGate(), "did not attest"),
        ("test", True, _ProviderGate(), _GrantGate(False), "did not attest"),
        ("local", True, _ProviderGate(), _GrantGate(), "test, development, or staging"),
    ],
)
def test_composition_fails_closed_for_environment_and_authorization_gates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment: str,
    enabled: bool,
    provider: object,
    grant: object,
    message: str,
) -> None:
    cache_root = _stub_approved_registry(monkeypatch, tmp_path)

    with pytest.raises(MediaStressFixtureDenied, match=message):
        _compose(
            cache_root=cache_root,
            provider=provider,
            grant=grant,
            environment=environment,
            enabled=enabled,
        )


def test_bare_gate_booleans_and_caller_metadata_are_not_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = _stub_approved_registry(monkeypatch, tmp_path)

    with pytest.raises(MediaStressFixtureDenied, match="typed media authorization verifier"):
        _compose(cache_root=cache_root, provider=True)
    with pytest.raises(TypeError):
        compose_staging_test_fixture_source(  # type: ignore[call-arg]
            environment="test",
            enabled=True,
            fixture_id="generated-16x9-4s",
            cache_root=cache_root,
            provider_activation_verifier=_ProviderGate(),
            playback_grant_verifier=_GrantGate(),
            authorization_context=AUTHORIZATION_CONTEXT,
            playback_grant=PLAYBACK_GRANT,
            width=320,
        )


def test_composition_requires_matching_server_created_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = _stub_approved_registry(monkeypatch, tmp_path)
    other_context = create_media_authorization_context(
        tenant_id="other-tenant",
        person_id="other-person",
        session_id="other-session",
    )
    other_grant = PlaybackGrantDescriptor(
        grant_id="other-grant",
        authorization=other_context,
        activity_id="other-activity",
        activity_version="other-v1",
        media_version=PLAYBACK_GRANT.media_version,
        issued_at=PLAYBACK_GRANT.issued_at,
        expires_at=PLAYBACK_GRANT.expires_at,
    )

    with pytest.raises(MediaStressFixtureDenied, match="does not match"):
        _compose(
            cache_root=cache_root,
            authorization_context=AUTHORIZATION_CONTEXT,
            playback_grant=other_grant,
        )
    with pytest.raises(MediaStressFixtureDenied, match="server-created"):
        _compose(cache_root=cache_root, authorization_context=object())  # type: ignore[arg-type]


def test_composition_rejects_outside_cache_and_parent_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = _stub_approved_registry(monkeypatch, tmp_path)

    with pytest.raises(MediaStressFixtureDenied, match=r"ignored .*boundary"):
        _compose(cache_root=tmp_path / "outside")
    with pytest.raises(MediaStressFixtureDenied, match="must not contain '..'"):
        _compose(cache_root=cache_root / ".." / "escape")


def test_settings_reject_fixture_opt_in_in_production_local_or_without_root(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="forbidden in production"):
        Settings(
            environment="production",
            _env_file=None,
            media_stress_fixtures_enabled=True,
            media_stress_fixtures_cache_root=str(tmp_path / ".artifacts"),
        )
    with pytest.raises(ValidationError, match="test, development, or staging"):
        Settings(
            environment="local",
            _env_file=None,
            media_stress_fixtures_enabled=True,
            media_stress_fixtures_cache_root=str(tmp_path / ".artifacts"),
        )
    with pytest.raises(ValidationError, match="configured cache root"):
        Settings(
            environment="test",
            _env_file=None,
            media_stress_fixtures_enabled=True,
        )
    with pytest.raises(ValidationError, match="must not contain '..'"):
        Settings(
            environment="test",
            _env_file=None,
            media_stress_fixtures_enabled=True,
            media_stress_fixtures_cache_root=str(tmp_path / ".artifacts" / ".." / "escape"),
        )


def test_settings_wrapper_uses_only_configured_cache_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = _stub_approved_registry(monkeypatch, tmp_path)
    settings = Settings(
        environment="test",
        _env_file=None,
        media_stress_fixtures_enabled=True,
        media_stress_fixtures_cache_root=str(cache_root),
    )

    source = compose_staging_test_fixture_source_from_settings(
        settings,
        fixture_id="generated-16x9-4s",
        provider_activation_verifier=_ProviderGate(),
        playback_grant_verifier=_GrantGate(),
        authorization_context=AUTHORIZATION_CONTEXT,
        playback_grant=PLAYBACK_GRANT,
    )

    assert source.local_path == cache_root / "generated-16x9-4s.mp4"
    with pytest.raises(TypeError):
        compose_staging_test_fixture_source_from_settings(  # type: ignore[call-arg]
            settings,
            fixture_id="generated-16x9-4s",
            cache_root=tmp_path / "outside",
            provider_activation_verifier=_ProviderGate(),
            playback_grant_verifier=_GrantGate(),
        )
