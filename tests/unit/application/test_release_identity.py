from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application import release_identity
from ac_platform.application import settings as settings_module
from ac_platform.application.release_identity import ReleaseIdentityError
from ac_platform.application.settings import Settings
from ac_platform.seed.application import SeedApplicationError, StagingSeedApplication


def _write_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_id: str,
) -> None:
    marker = tmp_path / ".ac-release-id"
    marker.write_text(f"{release_id}\n", encoding="ascii")
    monkeypatch.setattr(release_identity, "BAKED_RELEASE_ID_PATH", marker)


def test_baked_release_marker_is_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release_id = "a" * 40
    _write_marker(tmp_path, monkeypatch, release_id)

    assert release_identity.read_baked_release_id() == release_id


def test_baked_release_marker_is_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_identity, "BAKED_RELEASE_ID_PATH", tmp_path / "missing")

    with pytest.raises(ReleaseIdentityError, match="unavailable"):
        release_identity.read_baked_release_id()


@pytest.mark.parametrize("contents", ("", "a" * 40, "A" * 40 + "\n", "a" * 41 + "\n"))
def test_baked_release_marker_rejects_malformed_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contents: str,
) -> None:
    marker = tmp_path / ".ac-release-id"
    marker.write_text(contents, encoding="ascii")
    monkeypatch.setattr(release_identity, "BAKED_RELEASE_ID_PATH", marker)

    with pytest.raises(ReleaseIdentityError, match="malformed"):
        release_identity.read_baked_release_id()


def test_staging_seed_application_rejects_fabricated_runtime_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_marker(tmp_path, monkeypatch, "a" * 40)

    with pytest.raises(SeedApplicationError, match="baked API release marker"):
        StagingSeedApplication(
            cast(AsyncSession, object()),
            environment="staging",
            expected_release_id="b" * 40,
        )


def test_runtime_settings_reject_fabricated_environment_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_marker(tmp_path, monkeypatch, "a" * 40)
    configured = cast(Settings, SimpleNamespace(environment="staging", release_id="b" * 40))
    monkeypatch.setattr(settings_module, "Settings", lambda: configured)
    settings_module.get_settings.cache_clear()

    try:
        with pytest.raises(ReleaseIdentityError, match="runtime AC_RELEASE_ID"):
            settings_module.get_settings()
    finally:
        settings_module.get_settings.cache_clear()
