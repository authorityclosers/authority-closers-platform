from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    HOSTED_APPROVAL_SCHEMA,
    HostedApprovalBundle,
    StageApproval,
)

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

_TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
_PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")
_APPROVER_ID = UUID("30000000-0000-4000-8000-000000000004")
_BUDGET_SCOPE_ID = UUID("40000000-0000-4000-8000-000000000005")


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


def test_prepare_native_reuse_is_verified_and_recorded_separately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_activation, source_bytes = _write_source_activation(tmp_path)
    target = "2" * 40
    _patch_target_native(monkeypatch, "3" * 40)
    sibling = str(_SCRIPT.parent)
    if sibling not in sys.path:
        sys.path.insert(0, sibling)
    import native_artifact_compatibility as compatibility

    def verified(**arguments):
        assert arguments["target_release"] == target
        assert arguments["proof_path"] == tmp_path / "proof.json"
        assert arguments["proof_sha256"] == "b" * 64
        assert arguments["repository_root"] == tmp_path
        return {"native_source_commit": "3" * 40, "target_release_id": target}

    monkeypatch.setattr(compatibility, "verify_reuse", verified)
    result = _MODULE.prepare(
        source_activation=source_activation,
        target_release_id=target,
        native_artifact_manifest=tmp_path / "native.json",
        native_artifact_sha256="a" * 64,
        output_dir=tmp_path / "prepared-reuse",
        native_reuse_proof=tmp_path / "proof.json",
        native_reuse_proof_sha256="b" * 64,
        source_repository=tmp_path,
    )
    activation = Path(result["activation"]).read_bytes()
    receipt = json.loads(Path(result["native_compatibility_receipt"]).read_bytes())
    assert receipt["activation_sha256"] == hashlib.sha256(activation).hexdigest()
    assert receipt["native_source_commit"] == result["native_source_commit"] == "3" * 40
    assert json.loads(activation)["release_id"] == target
    assert result["approval_replaced"] is False
    assert result["writes"] == 5
    assert all(Path(path).read_bytes() == raw for path, raw in source_bytes.items())

    def refused(**_arguments):
        raise compatibility.NativeCompatibilityError("native_inputs_changed")

    monkeypatch.setattr(compatibility, "verify_reuse", refused)
    with pytest.raises(_MODULE.PrepareError, match="native_inputs_changed"):
        _MODULE.prepare(
            source_activation=source_activation,
            target_release_id=target,
            native_artifact_manifest=tmp_path / "native.json",
            native_artifact_sha256="a" * 64,
            output_dir=tmp_path / "must-not-exist",
            native_reuse_proof=tmp_path / "proof.json",
            native_reuse_proof_sha256="b" * 64,
            source_repository=tmp_path,
        )
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize(
    "provided", ["native_reuse_proof", "native_reuse_proof_sha256", "source_repository"]
)
def test_prepare_reuse_arguments_must_be_complete(tmp_path: Path, provided: str) -> None:
    values = {
        "native_reuse_proof": tmp_path / "proof.json",
        "native_reuse_proof_sha256": "b" * 64,
        "source_repository": tmp_path,
    }
    with pytest.raises(_MODULE.PrepareError, match="requires a proof"):
        _MODULE.prepare(
            source_activation=tmp_path / "source.json",
            target_release_id="2" * 40,
            native_artifact_manifest=tmp_path / "native.json",
            native_artifact_sha256="a" * 64,
            output_dir=tmp_path / "must-not-exist",
            **{provided: values[provided]},
        )
    assert not (tmp_path / "must-not-exist").exists()


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


def _hosted_approval(
    *,
    environment: str = "staging",
    tenant_id: UUID = _TENANT_ID,
    stage_expires_at_epoch: int = 1_900,
    bundle_expires_at_epoch: int = 2_000,
    provider_id: str = "elevenlabs",
    credential_ref: str = "ref:credential/elevenlabs/1",
    zero_cost_basis: str = "verified_free_allowance",
) -> bytes:
    stage = StageApproval(
        id=UUID("60000000-0000-4000-8000-000000000007"),
        tenant_id=_TENANT_ID,
        person_id=_PERSON_ID,
        source_sha256="a" * 64,
        configuration_sha256="b" * 64,
        stage="C2",
        provider_id=provider_id,
        model_id="scribe_v2",
        recipe_revision="scribe-v2-native-normalized-v1",
        permission_ref="ref:permission/1",
        retention_ref="ref:retention/1",
        professional_gate_ref="ref:professional/1",
        pricing_ref="ref:pricing/zero/1",
        provider_terms_ref="ref:provider-terms/1",
        privacy_ref="ref:privacy/1",
        credential_ref=credential_ref,
        free_allowance_ref="ref:allowance/1",
        no_paid_overage_ref="ref:billing/overage-disabled",
        privacy_revision="privacy-20260913-v1",
        privacy_notice="Approved internal testing only; retain the source for the stated window.",
        expires_at_epoch=stage_expires_at_epoch,
        max_requests=1,
        entitlement_seconds=None,
        zero_cost_basis=zero_cost_basis,  # type: ignore[arg-type]
        price_evidence_sha256="c" * 64,
        max_cost_paise=0,
        max_source_duration_ms=60_000,
        max_input_bytes=1_000_000,
        max_completion_tokens=0,
        profile_sha256=None,
    )
    return HostedApprovalBundle(
        schema_id=HOSTED_APPROVAL_SCHEMA,
        environment=environment,  # type: ignore[arg-type]
        provider_control_tenant_id=tenant_id,
        deployment_ref="ref:deployment/approval-rotation-test",
        issued_at_epoch=1_000,
        expires_at_epoch=bundle_expires_at_epoch,
        budget_scope_id=_BUDGET_SCOPE_ID,
        budget_authorization_ref="ref:budget/approval-rotation-test",
        budget_owner_id=_APPROVER_ID,
        intake_authorization_ref="ref:intake/approval-rotation-test",
        intake_retention_ref="ref:intake-retention/approval-rotation-test",
        retention_days=7,
        max_stored_source_bytes=1_000_000,
        allowances=(),
        stages=(stage,),
    ).to_json()


def _write_source_activation(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    release_id = "1" * 40
    image_ref = "sha256:" + "c" * 64
    config_id = "sha256:" + "d" * 64
    approval_path = source_dir / "source-approval.json"
    approval_raw = (
        b'{"schema":"ac.sales-xray.hosted-approval/1",'
        b'"environment":"staging",'
        b'"provider_control_tenant_id":"10000000-0000-4000-8000-000000000001"}\n'
    )
    approval_path.write_bytes(approval_raw)
    service_path = source_dir / "service.json"
    service = {
        "schema_version": "ac.sales_xray.worker_service/1",
        "environment": "staging",
        "release_id": release_id,
        "operations_tenant_id": str(_TENANT_ID),
        "sales_xray_enabled": True,
        "bootstrap_only": False,
        "sales_xray_approval_path": "/run/ac-sales-xray/approval.json",
        "sales_xray_approval_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "sales_xray_storage_root": "/var/lib/ac-sales-xray/storage",
        "sales_xray_scratch_root": "/var/lib/ac-sales-xray/scratch",
        "database_url_file": "/run/secrets/ac-sales-xray-database-url",
        "native_socket_path": "/run/ac-sales-xray/native/native.sock",
        "native_image_ref": image_ref,
        "providers": [
            {
                "provider_id": "elevenlabs",
                "credential_ref": "ref:credential/elevenlabs/1",
                "executable": "/usr/bin/false",
                "project_ref": "ref:project/staging",
                "environment_ref": "ref:environment/staging",
                "secret_path_ref": "ref:path/elevenlabs-token",
                "token_file_ref": "/run/ac-sales-xray/identities/elevenlabs/token",
            }
        ],
    }
    service_raw = _MODULE._json_bytes(service)
    service_path.write_bytes(service_raw)

    env_path = source_dir / "compose.env"
    env = _env_values()
    env.update(
        {
            "AC_XRAY_SERVICE_CONFIG": service_path.as_posix(),
            "AC_XRAY_SERVICE_SHA256": hashlib.sha256(service_raw).hexdigest(),
            "AC_XRAY_APPROVAL_FILE": approval_path.as_posix(),
            "AC_XRAY_APPROVAL_SHA256": hashlib.sha256(approval_raw).hexdigest(),
            "AC_XRAY_NATIVE_IMAGE_REF": image_ref,
        }
    )
    env_raw = _MODULE._env_bytes(env)
    env_path.write_bytes(env_raw)

    descriptor_path = source_dir / "activation.json"
    descriptor = {
        "schema_version": "ac.sales_xray.hosted_activation/1",
        "environment": "staging",
        "release_id": release_id,
        "compose_overlay": _MODULE.OVERLAY,
        "compose_profile": _MODULE.PROFILE,
        "compose_env_file": str(env_path),
        "compose_env_sha256": hashlib.sha256(env_raw).hexdigest(),
        "service_config_file": str(service_path),
        "service_config_sha256": hashlib.sha256(service_raw).hexdigest(),
        "approval_file": str(approval_path),
        "approval_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "native_image_ref": image_ref,
        "native_image_config_id": config_id,
        "helper_unit": "sales-xray-native@staging.service",
        "previous_release_policy": "exact_target_release",
    }
    descriptor_raw = _MODULE._json_bytes(descriptor)
    descriptor_path.write_bytes(descriptor_raw)
    return descriptor_path, {
        str(descriptor_path): descriptor_raw,
        str(env_path): env_raw,
        str(service_path): service_raw,
        str(approval_path): approval_raw,
    }


def _patch_target_native(monkeypatch: pytest.MonkeyPatch, target_release: str) -> None:
    monkeypatch.setattr(
        _MODULE,
        "_load_native_manifest",
        lambda _path, _digest: (
            target_release,
            "sha256:" + "e" * 64,
            "sha256:" + "f" * 64,
        ),
    )
    monkeypatch.setattr(_MODULE.time, "time", lambda: 1_500)


def test_prepare_replaces_approval_as_a_new_immutable_digest_bound_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_activation, source_bytes = _write_source_activation(tmp_path)
    target_release = "2" * 40
    _patch_target_native(monkeypatch, target_release)
    replacement = _hosted_approval()
    approval_input = tmp_path / "replacement-approval.json"
    approval_input.write_bytes(replacement)
    output_dir = tmp_path / "prepared"

    result = _MODULE.prepare(
        source_activation=source_activation,
        target_release_id=target_release,
        native_artifact_manifest=tmp_path / "native-manifest.json",
        native_artifact_sha256="a" * 64,
        output_dir=output_dir,
        approval_file=approval_input,
        approval_sha256=hashlib.sha256(replacement).hexdigest(),
    )

    activation_raw = Path(result["activation"]).read_bytes()
    activation = json.loads(activation_raw)
    service_raw = Path(result["service"]).read_bytes()
    service = json.loads(service_raw)
    env_raw = Path(result["compose_env"]).read_bytes()
    env = dict(line.split("=", 1) for line in env_raw.decode().splitlines())
    approval_output = Path(activation["approval_file"])
    replacement_digest = hashlib.sha256(replacement).hexdigest()

    assert result["approval_replaced"] is True
    assert result["writes"] == 5
    assert result["provider_calls"] == 0
    assert approval_output.read_bytes() == replacement
    assert activation["approval_sha256"] == replacement_digest
    assert env["AC_XRAY_APPROVAL_FILE"] == str(approval_output)
    assert env["AC_XRAY_APPROVAL_SHA256"] == replacement_digest
    assert service["sales_xray_approval_sha256"] == replacement_digest
    assert activation["service_config_sha256"] == hashlib.sha256(service_raw).hexdigest()
    assert activation["compose_env_sha256"] == hashlib.sha256(env_raw).hexdigest()
    assert (
        Path(result["activation_sha256"]).read_text().strip()
        == hashlib.sha256(activation_raw).hexdigest()
    )
    assert result["native_source_commit"] == target_release
    assert all(Path(path).read_bytes() == raw for path, raw in source_bytes.items())

    with pytest.raises(_MODULE.PrepareError, match="output-dir must be a new empty directory"):
        _MODULE.prepare(
            source_activation=source_activation,
            target_release_id=target_release,
            native_artifact_manifest=tmp_path / "native-manifest.json",
            native_artifact_sha256="a" * 64,
            output_dir=output_dir,
            approval_file=approval_input,
            approval_sha256=replacement_digest,
        )


def test_prepare_carries_source_approval_unchanged_when_replacement_is_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_activation, source_bytes = _write_source_activation(tmp_path)
    source_descriptor = json.loads(source_activation.read_bytes())
    target_release = "2" * 40
    _patch_target_native(monkeypatch, target_release)
    output_dir = tmp_path / "prepared-default"

    result = _MODULE.prepare(
        source_activation=source_activation,
        target_release_id=target_release,
        native_artifact_manifest=tmp_path / "native-manifest.json",
        native_artifact_sha256="a" * 64,
        output_dir=output_dir,
    )

    activation = json.loads(Path(result["activation"]).read_bytes())
    service = json.loads(Path(result["service"]).read_bytes())
    env = dict(line.split("=", 1) for line in Path(result["compose_env"]).read_text().splitlines())
    assert result["approval_replaced"] is False
    assert result["writes"] == 4
    assert activation["approval_file"] == source_descriptor["approval_file"]
    assert activation["approval_sha256"] == source_descriptor["approval_sha256"]
    assert env["AC_XRAY_APPROVAL_FILE"] == source_descriptor["approval_file"]
    assert env["AC_XRAY_APPROVAL_SHA256"] == source_descriptor["approval_sha256"]
    assert service["sales_xray_approval_sha256"] == source_descriptor["approval_sha256"]
    assert all(Path(path).read_bytes() == raw for path, raw in source_bytes.items())


@pytest.mark.parametrize(
    ("replacement_options", "digest_override", "target_is_source", "now", "message"),
    [
        ({}, None, True, 1_500, "replacement approval requires a new target release"),
        (
            {"bundle_expires_at_epoch": 1_400, "stage_expires_at_epoch": 1_300},
            None,
            False,
            1_500,
            "replacement approval is not current",
        ),
        ({"stage_expires_at_epoch": 1_400}, None, False, 1_500, "expired provider scope"),
        ({"environment": "production"}, None, False, 1_500, "environment differs"),
        (
            {"tenant_id": UUID("90000000-0000-4000-8000-000000000009")},
            None,
            False,
            1_500,
            "tenant differs",
        ),
        (
            {"provider_id": "groq", "credential_ref": "ref:credential/groq/1"},
            None,
            False,
            1_500,
            "provider credential is not configured",
        ),
        (
            {"credential_ref": "ref:credential/other/1"},
            None,
            False,
            1_500,
            "provider credential is not configured",
        ),
        ({"zero_cost_basis": "synthetic"}, None, False, 1_500, "cannot contain synthetic"),
    ],
)
def test_prepare_refuses_replacement_approval_outside_exact_hosted_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replacement_options: dict[str, object],
    digest_override: str | None,
    target_is_source: bool,
    now: int,
    message: str,
) -> None:
    source_activation, source_bytes = _write_source_activation(tmp_path)
    target_release = "1" * 40 if target_is_source else "2" * 40
    _patch_target_native(monkeypatch, target_release)
    monkeypatch.setattr(_MODULE.time, "time", lambda: now)
    replacement = _hosted_approval(**replacement_options)  # type: ignore[arg-type]
    approval_input = tmp_path / "replacement-approval.json"
    approval_input.write_bytes(replacement)
    output_dir = tmp_path / "prepared"

    with pytest.raises(_MODULE.PrepareError, match=message):
        _MODULE.prepare(
            source_activation=source_activation,
            target_release_id=target_release,
            native_artifact_manifest=tmp_path / "native-manifest.json",
            native_artifact_sha256="a" * 64,
            output_dir=output_dir,
            approval_file=approval_input,
            approval_sha256=digest_override or hashlib.sha256(replacement).hexdigest(),
        )

    assert not output_dir.exists()
    assert all(Path(path).read_bytes() == raw for path, raw in source_bytes.items())


def test_prepare_rejects_replacement_digest_and_noncanonical_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_activation, source_bytes = _write_source_activation(tmp_path)
    target_release = "2" * 40
    _patch_target_native(monkeypatch, target_release)
    canonical = _hosted_approval()
    approval_input = tmp_path / "replacement-approval.json"
    approval_input.write_bytes(canonical)
    with pytest.raises(_MODULE.PrepareError, match="digest differs"):
        _MODULE.prepare(
            source_activation=source_activation,
            target_release_id=target_release,
            native_artifact_manifest=tmp_path / "native-manifest.json",
            native_artifact_sha256="a" * 64,
            output_dir=tmp_path / "wrong-digest",
            approval_file=approval_input,
            approval_sha256="0" * 64,
        )

    noncanonical = canonical + b" "
    approval_input.write_bytes(noncanonical)
    with pytest.raises(_MODULE.PrepareError, match="canonical hosted contract bytes"):
        _MODULE.prepare(
            source_activation=source_activation,
            target_release_id=target_release,
            native_artifact_manifest=tmp_path / "native-manifest.json",
            native_artifact_sha256="a" * 64,
            output_dir=tmp_path / "noncanonical",
            approval_file=approval_input,
            approval_sha256=hashlib.sha256(noncanonical).hexdigest(),
        )

    assert not (tmp_path / "wrong-digest").exists()
    assert not (tmp_path / "noncanonical").exists()
    assert all(Path(path).read_bytes() == raw for path, raw in source_bytes.items())


def test_prepare_requires_replacement_path_and_digest_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_activation, _ = _write_source_activation(tmp_path)
    target_release = "2" * 40
    _patch_target_native(monkeypatch, target_release)

    with pytest.raises(_MODULE.PrepareError, match="must be supplied together"):
        _MODULE.prepare(
            source_activation=source_activation,
            target_release_id=target_release,
            native_artifact_manifest=tmp_path / "native-manifest.json",
            native_artifact_sha256="a" * 64,
            output_dir=tmp_path / "prepared",
            approval_file=tmp_path / "missing-approval.json",
        )

    assert not (tmp_path / "prepared").exists()
