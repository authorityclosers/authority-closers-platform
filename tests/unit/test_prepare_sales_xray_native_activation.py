from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).parents[2]
    / "infra"
    / "application"
    / "scripts"
    / "prepare-sales-xray-native-activation.py"
)
_SPEC = importlib.util.spec_from_file_location("prepare_sales_xray_native_activation", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def test_prepare_rejects_native_artifact_from_different_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target_release = "a" * 40
    descriptor = {"environment": "staging"}
    env: dict[str, str] = {}
    service: dict[str, object] = {}
    approval: dict[str, object] = {}

    monkeypatch.setattr(
        _MODULE,
        "_load_source",
        lambda _path: (descriptor, b"", env, service, b"", approval, b""),
    )
    monkeypatch.setattr(
        _MODULE,
        "_load_native_manifest",
        lambda _path, _digest: ("b" * 40, "sha256:" + "1" * 64, "sha256:" + "2" * 64),
    )

    with pytest.raises(
        _MODULE.PrepareError,
        match="native artifact source commit differs from target release",
    ):
        _MODULE.prepare(
            source_activation=tmp_path / "source.json",
            target_release_id=target_release,
            native_artifact_manifest=tmp_path / "native.json",
            native_artifact_sha256="c" * 64,
            output_dir=tmp_path / "output",
        )

    assert not (tmp_path / "output").exists()


def _env_values() -> dict[str, str]:
    identity_dir = "C:/ac-test/identity" if os.name == "nt" else "/etc/ac-test/identity"
    values = {key: identity_dir for key in _MODULE.ABSOLUTE_ENV_KEYS}
    values.update(
        {
            "AC_XRAY_SERVICE_SHA256": "a" * 64,
            "AC_XRAY_APPROVAL_SHA256": "b" * 64,
            "AC_XRAY_ACQUISITION_ENABLED": "true",
            "AC_XRAY_NATIVE_IMAGE_REF": "sha256:" + "c" * 64,
            "AC_XRAY_CHALLENGE_SITE_KEY": "synthetic-public-site-key",
            "AC_XRAY_ACQUISITION_POLICY_REVISION": "synthetic-policy-v1",
        }
    )
    return values


def test_prepare_keeps_openai_identity_optional_for_existing_four_provider_env() -> None:
    values = _env_values()
    parsed = _MODULE._parse_env(
        "".join(f"{key}={values[key]}\n" for key in sorted(values)).encode()
    )
    assert "AC_XRAY_OPENAI_IDENTITY_DIR" not in parsed


def test_prepare_accepts_openai_identity_only_as_an_absolute_optional_path() -> None:
    values = _env_values()
    values["AC_XRAY_OPENAI_IDENTITY_DIR"] = str(_MODULE.OPENAI_HOST_IDENTITY_DIR)
    parsed = _MODULE._parse_env(
        "".join(f"{key}={values[key]}\n" for key in sorted(values)).encode()
    )
    assert parsed["AC_XRAY_OPENAI_IDENTITY_DIR"] == values["AC_XRAY_OPENAI_IDENTITY_DIR"]

    values["AC_XRAY_OPENAI_IDENTITY_DIR"] = "/etc/authority-closers/secrets/sales-xray/identities"
    with pytest.raises(_MODULE.PrepareError, match="dedicated host path"):
        _MODULE._parse_env("".join(f"{key}={values[key]}\n" for key in sorted(values)).encode())


def test_prepare_binds_openai_directory_to_dedicated_overlay_and_token_path() -> None:
    descriptor = {"compose_overlay": _MODULE.OPENAI_OVERLAY}
    openai_identity_dir = str(_MODULE.OPENAI_HOST_IDENTITY_DIR)
    env = {"AC_XRAY_OPENAI_IDENTITY_DIR": openai_identity_dir}
    service = {
        "providers": [
            {
                "provider_id": "openai",
                "token_file_ref": _MODULE.OPENAI_TOKEN_FILE,
            }
        ]
    }
    _MODULE._validate_openai_identity_selection(descriptor, env, service)

    with pytest.raises(_MODULE.PrepareError, match="dedicated mounted identity path"):
        _MODULE._validate_openai_identity_selection(
            descriptor,
            env,
            {"providers": [{"provider_id": "openai", "token_file_ref": "/run/unexpected/token"}]},
        )


def test_prepare_rejects_openai_mount_without_provider_and_missing_path() -> None:
    env = {"AC_XRAY_OPENAI_IDENTITY_DIR": str(_MODULE.OPENAI_HOST_IDENTITY_DIR)}
    with pytest.raises(_MODULE.PrepareError, match="unexpected without an OpenAI provider"):
        _MODULE._validate_openai_identity_selection(
            {"compose_overlay": _MODULE.OVERLAY},
            env,
            {"providers": [{"provider_id": "groq"}]},
        )
    with pytest.raises(_MODULE.PrepareError, match="requires its separately scoped identity"):
        _MODULE._validate_openai_identity_selection(
            {"compose_overlay": _MODULE.OPENAI_OVERLAY},
            {},
            {"providers": [{"provider_id": "openai", "token_file_ref": _MODULE.OPENAI_TOKEN_FILE}]},
        )
