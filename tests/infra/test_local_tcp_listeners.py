"""Read-only port inspection; ephemeral test listener, no application processes."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")


@pytest.mark.skipif(PWSH is None, reason="PowerShell unavailable")
def test_native_tcp_inspection_detects_and_releases_exact_loopback_listener():
    helper = str(ROOT / "scripts/Get-LocalTcpListeners.ps1").replace("'", "''")
    command = f"""
    $ErrorActionPreference = 'Stop'
    . '{helper}'
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {{
        $listener.Start()
        $port = $listener.LocalEndpoint.Port
        $during = @(Get-LocalTcpListeners -Port $port)
        if ($during.Count -ne 1 -or $during[0].LocalAddress -ne '127.0.0.1') {{
            throw 'Listener mismatch'
        }}
    }} finally {{ $listener.Stop() }}
    @{{
        found=$during.Count; port=$during[0].LocalPort; expected=$port
        after=@(Get-LocalTcpListeners -Port $port).Count
    }} | ConvertTo-Json -Compress
    """
    result = subprocess.run(  # noqa: S603 - fixed read-only helper and disposable loopback listener
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["found"] == 1
    assert observed["port"] == observed["expected"]
    assert observed["after"] == 0


def test_managed_launchers_use_fail_closed_native_inspection():
    helper = (ROOT / "scripts/Get-LocalTcpListeners.ps1").read_text(encoding="utf-8")
    assert "GetActiveTcpListeners()" in helper
    assert "SilentlyContinue" not in helper
    assert "catch" not in helper
    for name in ("Api", "Platform", "Postgres"):
        source = (ROOT / f"scripts/Start-Local{name}.ps1").read_text(encoding="utf-8")
        assert "Get-NetTCPConnection" not in source
        assert "Get-LocalTcpListeners.ps1" in source
        assert "Get-LocalTcpListeners" in source
