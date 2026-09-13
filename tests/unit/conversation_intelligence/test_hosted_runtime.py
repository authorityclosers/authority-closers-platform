"""Release composition uses synthetic non-secret approval data and private temp roots."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.hosted_runtime import (
    PinnedApprovalLoader,
    compose_hosted_intake,
)
from ac_platform.http.conversation_analysis import AnalysisAcceptance, AnalysisSelection


def approval_data(environment: str = "test") -> dict[str, Any]:
    now = int(datetime.now(UTC).timestamp())
    tenant, person = str(uuid4()), str(uuid4())
    return {
        "schema": "ac.sales-xray.hosted-approval/1",
        "environment": environment,
        "provider_control_tenant_id": tenant,
        "deployment_ref": "ref:synthetic/deployment",
        "issued_at_epoch": now - 1,
        "expires_at_epoch": now + 3600,
        "budget_scope_id": str(uuid4()),
        "budget_authorization_ref": "ref:synthetic/budget",
        "budget_owner_id": person,
        "intake_authorization_ref": "ref:synthetic/intake",
        "intake_retention_ref": "ref:synthetic/retention",
        "retention_days": 7,
        "max_stored_source_bytes": 1_073_741_824,
        "allowances": [
            {
                "id": str(uuid4()),
                "tenant_id": tenant,
                "person_id": person,
                "seconds": 300,
                "max_recordings": 4,
                "max_source_bytes": 134_217_728,
                "max_stored_source_bytes": 536_870_912,
                "authorization_ref": "ref:synthetic/allowance",
                "granted_by": person,
                "reason": "Approved internal testing allowance",
            }
        ],
        "stages": [],
    }


def settings_for(tmp_path: Path, data: dict[str, Any]) -> Settings:
    path = tmp_path / "approval.json"
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    return Settings(
        environment="test",
        operations_tenant_id=UUID(data["provider_control_tenant_id"]),
        sales_xray_enabled=True,
        sales_xray_approval_path=str(path),
        sales_xray_approval_sha256=hashlib.sha256(raw).hexdigest(),
        sales_xray_storage_root=str(tmp_path / "objects"),
        sales_xray_scratch_root=str(tmp_path / "scratch"),
    )


def test_disabled_runtime_does_not_create_storage(tmp_path: Path) -> None:
    settings = Settings(environment="test", sales_xray_storage_root=str(tmp_path / "unused"))
    assert compose_hosted_intake(settings) is None
    assert not (tmp_path / "unused").exists()


def test_complete_pinned_runtime_loads_and_rechecks_artifact(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, approval_data())
    runtime = compose_hosted_intake(settings)
    assert runtime.authority is not None
    assert runtime.policy.acoustic_recipe == "audioatlas-16000-v1"
    assert runtime.storage.root == tmp_path / "objects"
    assert runtime.scratch.root == tmp_path / "scratch"
    assert runtime.storage.root != runtime.scratch.root
    assert runtime.authority.current(datetime.now(UTC)).digest
    Path(settings.sales_xray_approval_path).write_text("changed")
    with pytest.raises(ValueError, match="approved processing configuration"):
        runtime.authority.current(datetime.now(UTC))


@pytest.mark.parametrize(
    "field",
    [
        "sales_xray_approval_path",
        "sales_xray_approval_sha256",
        "sales_xray_storage_root",
        "sales_xray_scratch_root",
        "operations_tenant_id",
    ],
)
def test_incomplete_activation_cannot_mount_intake(tmp_path: Path, field: str) -> None:
    settings = settings_for(tmp_path, approval_data()).model_copy(update={field: None})
    with pytest.raises(ValueError, match="configuration_incomplete"):
        compose_hosted_intake(settings)
    assert not (tmp_path / "objects").exists()


@pytest.mark.parametrize("change", ["digest", "expired", "environment", "unknown", "missing"])
def test_invalid_approval_is_sanitized_before_storage_creation(tmp_path: Path, change: str) -> None:
    data = approval_data()
    if change == "expired":
        data["issued_at_epoch"], data["expires_at_epoch"] = 1, 2
    if change == "environment":
        data["environment"] = "production"
    if change == "unknown":
        data["unapproved_field"] = "private-data-sentinel-do-not-return"
    settings = settings_for(tmp_path, data)
    if change == "digest":
        settings = settings.model_copy(update={"sales_xray_approval_sha256": "a" * 64})
    if change == "missing":
        Path(settings.sales_xray_approval_path).unlink()
    with pytest.raises(ValueError, match="^hosted_approval_unavailable$"):
        compose_hosted_intake(settings)
    assert not (tmp_path / "objects").exists()


def test_private_roots_cannot_overlap(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, approval_data()).model_copy(
        update={
            "sales_xray_scratch_root": str(tmp_path / "objects" / "scratch"),
        }
    )
    with pytest.raises(ValueError, match="roots_must_be_separate"):
        compose_hosted_intake(settings)


def test_approval_cannot_select_a_different_control_tenant(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, approval_data()).model_copy(
        update={"operations_tenant_id": uuid4()}
    )
    with pytest.raises(ValueError, match="^hosted_approval_unavailable$"):
        compose_hosted_intake(settings)
    assert not (tmp_path / "objects").exists()


def test_loader_rejects_relative_path_and_malformed_digest() -> None:
    with pytest.raises(ValueError, match="^hosted_approval_unavailable$"):
        PinnedApprovalLoader(Path("approval.json"), "a" * 64, "test", uuid4())()


def test_unavailable_sales_approval_keeps_the_existing_api_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ac_platform.http.app as app_module
    from tests.unit.http.test_app_composition import _deployment_settings

    settings = _deployment_settings("staging").model_copy(
        update={
            "sales_xray_enabled": True,
            "sales_xray_approval_path": str(tmp_path / "missing.json"),
            "sales_xray_approval_sha256": "a" * 64,
            "sales_xray_storage_root": str(tmp_path / "objects"),
            "sales_xray_scratch_root": str(tmp_path / "scratch"),
        }
    )
    monkeypatch.setattr(app_module, "settings", settings)
    application = app_module.create_app()
    paths = application.openapi()["paths"]
    assert "/v1/learning/home" in paths
    assert "/v1/conversation/recordings" in paths
    assert "/v1/conversation/intake/quote" not in paths
    assert application.state.sales_xray_intake_configured is False


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_composition_has_owned_routes_without_local_proof_import(
    environment: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ac_platform.http.app as app_module
    from tests.unit.http.test_app_composition import _deployment_settings

    data = approval_data(environment)
    configured = settings_for(tmp_path, data)
    settings = _deployment_settings(environment).model_copy(
        update={
            key: value
            for key, value in configured.model_dump().items()
            if key.startswith("sales_xray_") or key == "operations_tenant_id"
        }
    )
    monkeypatch.setattr(app_module, "settings", settings)
    application = app_module.create_app()
    paths = application.openapi()["paths"]
    assert "/v1/conversation/intake/quote" in paths
    assert "/v1/conversation/recordings/{recording_id}/source" in paths
    assert "/v1/conversation/recordings/{recording_id}/analysis/quote" in paths
    assert "/v1/admin/conversation/runs/{run_id}/draft" not in paths
    assert application.docs_url is None
    # Deployment composition still rejects arbitrary injected local runtimes.
    with pytest.raises(RuntimeError, match="Hosted conversation intake"):
        app_module.create_app(conversation_intake_runtime=compose_hosted_intake(settings))


@pytest.mark.parametrize("field", ["provider", "model", "profile", "credential_ref", "tenant_id"])
def test_learner_cannot_select_provider_settings(field: str) -> None:
    with pytest.raises(ValueError):
        AnalysisSelection.model_validate({"stage": "C2", field: "caller-input"})


def test_acceptance_requires_explicit_exact_owner_consent() -> None:
    with pytest.raises(ValueError):
        AnalysisAcceptance.model_validate(
            {
                "quote_id": str(uuid4()),
                "selection": {"stage": "C2"},
                "quote_fingerprint": "a" * 64,
                "privacy_revision": "privacy-v1",
                "accepted": False,
            }
        )
