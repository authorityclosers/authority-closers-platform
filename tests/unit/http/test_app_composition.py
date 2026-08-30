from __future__ import annotations

import pytest

import ac_platform.http.app as app_module
from ac_platform.http.app import create_app


def test_shipped_application_mounts_g1_command_and_query_routes() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/certificates/{certificate_id}" in paths
    assert "/v1/admin/program-versions/{program_version_id}/publish" in paths
    assert "/v1/admin/corrections" in paths
    assert "/v1/admin/enrollment-grants" in paths
    assert "/v1/admin/jobs/{job_id}/retry" in paths
    assert "/v1/admin/recovery/reconcile" in paths

    # Provider callbacks stay fail-closed until a signed adapter is explicitly
    # registered by application composition.
    assert "/internal/v1/providers/{provider}/webhooks" not in paths


def test_public_api_documentation_is_available_outside_deployments() -> None:
    application = create_app()

    assert application.docs_url == "/docs"
    assert application.openapi_url == "/openapi.json"


def test_staging_and_production_disable_public_api_documentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for environment in ("staging", "production"):
        deployment_settings = app_module.settings.model_copy(update={"environment": environment})
        monkeypatch.setattr(app_module, "settings", deployment_settings)

        application = create_app()

        assert application.docs_url is None
        assert application.openapi_url is None
