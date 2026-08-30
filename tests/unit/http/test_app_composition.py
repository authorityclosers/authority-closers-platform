from __future__ import annotations

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
