"""The dev adapter retains ordinary authority and never sends a session elsewhere."""

import importlib.util
from pathlib import Path

import httpx
import pytest

from tests.unit.conversation_intelligence.test_recording_import_cli import fixture


def adapter():
    path = Path(__file__).parents[3] / "scripts/dev/import-sales-xray-drive.py"
    spec = importlib.util.spec_from_file_location("dev_recording_import", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dev_headers_retain_the_ordinary_session_and_tenant():
    module = adapter()
    requests = []

    def receive(request):
        requests.append(request)
        assert request.headers["Host"] == module.HOST
        assert request.headers["Origin"] == module.ORIGIN
        assert request.headers["Cookie"] == "fictional-session"
        assert request.headers["X-Recording-Import-Tenant"] == "fictional-tenant"
        return httpx.Response(200, json={"ok": True})

    with module.DevClient(
        base_url=module.LIVE,
        headers={
            "Cookie": "fictional-session",
            "Origin": module.LIVE,
            "X-Recording-Import-Tenant": "fictional-tenant",
        },
        transport=httpx.MockTransport(receive),
    ) as client:
        assert client.get(module.PREFIX + "imports/preview").json() == {"ok": True}
    assert len(requests) == 1


@pytest.mark.parametrize(
    "base",
    [
        "http://127.0.0.1:8102",
        "http://localhost:8101",
        "https://salesxray-staging.authorityclosers.com",
        "https://salesxray.authorityclosers.com",
        "http://127.0.0.1:8101?host=remote",
        "http://127.0.0.1:8101/other",
    ],
)
def test_refuses_other_origins_before_any_transport(base):
    module = adapter()
    with pytest.raises(ValueError, match="exact shared dev"):
        module.DevClient(base_url=base)


@pytest.mark.parametrize(
    "url,headers",
    [
        ("https://remote.invalid/v1/conversation/acquisition/imports", {}),
        ("http://127.0.0.1:8102/v1/conversation/acquisition/imports", {}),
        ("/health/ready", {}),
        ("/v1/conversation/acquisition/imports", {"Host": "foreign.invalid"}),
        ("/v1/conversation/acquisition/imports", {"Origin": "https://foreign.invalid"}),
    ],
)
def test_refuses_rerouted_requests_before_any_transport(url, headers):
    module = adapter()
    with (
        module.DevClient(
            base_url=module.LIVE,
            headers={"Cookie": "fictional-session"},
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("No outbound request allowed.")
            ),
        ) as client,
        pytest.raises(ValueError, match="destination or surface"),
    ):
        client.get(url, headers=headers)


def test_redirect_cannot_forward_the_session_even_if_a_caller_requests_it():
    module = adapter()
    requests = []

    def receive(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://remote.invalid/imports"})

    with module.DevClient(
        base_url=module.LIVE,
        follow_redirects=True,
        transport=httpx.MockTransport(receive),
    ) as client:
        response = client.get(module.PREFIX + "imports", follow_redirects=True)
    assert response.status_code == 307
    assert len(requests) == 1


def test_offline_mode_and_client_restoration(tmp_path, monkeypatch, capsys):
    module = adapter()
    manifest, assignments, _ = fixture(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["dev-import", "--manifest", str(manifest), "--members-file", str(assignments)]
    )
    original_client = httpx.Client
    assert module.main() == 0
    assert '"total_files": 2' in capsys.readouterr().out
    assert httpx.Client is original_client


def test_ordinary_apply_still_requires_explicit_rights_and_plan_acceptance(
    tmp_path, monkeypatch, capsys
):
    module = adapter()
    manifest, assignments, member = fixture(tmp_path)
    monkeypatch.setenv("AC_RECORDING_IMPORT_COOKIE", "fictional-session")
    monkeypatch.setattr(
        "sys.argv",
        [
            "dev-import",
            "--manifest",
            str(manifest),
            "--members-file",
            str(assignments),
            "--base-url",
            module.LIVE,
            "--tenant-id",
            member,
            "--apply",
        ],
    )
    original_client = httpx.Client
    monkeypatch.setattr(
        module.DevClient,
        "__init__",
        lambda *_args, **_kwargs: pytest.fail("No HTTP before consent."),
    )
    assert module.main() == 2
    captured = capsys.readouterr()
    assert "fictional-session" not in captured.out + captured.err
    assert httpx.Client is original_client
