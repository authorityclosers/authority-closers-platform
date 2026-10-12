"""Construct the actual combined API with fictional intake, without live I/O."""

import pytest

import ac_platform.http.app as app_module
from tests.unit.http.test_conversation_learner_acquisition import _runtime, _settings


@pytest.mark.parametrize("configured", [False, True])
def test_actual_application_constructs_with_and_without_sales_xray_intake(
    configured, tmp_path, monkeypatch
):
    runtime = _runtime(tmp_path) if configured else None
    intake = None if runtime is None else runtime.intake
    monkeypatch.setattr(app_module, "settings", _settings())
    monkeypatch.setattr(app_module, "compose_hosted_intake", lambda _settings: intake)
    monkeypatch.setattr(app_module, "compose_acquisition", lambda _settings, _intake: runtime)

    application = app_module.create_app()
    paths = application.openapi()["paths"]
    assert application.state.sales_xray_intake_configured is configured
    assert application.state.sales_xray_acquisition_configured is configured
    assert "/v1/me/sales-xray-workspaces" in paths
    assert "/v1/me/sales-xray-profile" in paths
    assert "/v1/admin/conversation/insights" in paths
    # Saved-report reads remain available when upload/provider composition is absent.
    assert "/v1/conversation/acquisition/insights" in paths
    assert ("/v1/conversation/acquisition/submissions" in paths) is configured
