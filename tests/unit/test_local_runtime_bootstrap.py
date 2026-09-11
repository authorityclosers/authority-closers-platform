"""Offline tests for the PowerShell compatibility bootstrap.

These tests exercise only temporary fixture scripts and already-installed
tooling. They never start or stop an application, database, scanner, or
other repository runtime.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "scripts" / "Local-RuntimeBootstrap.ps1"
PWSH = shutil.which("pwsh")
WINDOWS_POWERSHELL = shutil.which("powershell.exe")


def _quote(path: Path | str) -> str:
    """Return a single-quoted PowerShell literal."""

    return "'" + str(path).replace("'", "''") + "'"


def _run_powershell(
    executable: str,
    command: str,
    *,
    env: dict[str, str] | None = None,
    timeout: float = 20,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed executable and isolated command
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )


def _last_json(stdout: str) -> dict[str, object]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"No JSON result in PowerShell output: {stdout!r}")


def _fixture_script(path: Path, *, exit_code: int | None = None) -> Path:
    exit_line = f"exit {exit_code}" if exit_code is not None else ""
    path.write_text(
        """[CmdletBinding()]
param(
    [switch]$Stop,
    [ValidateSet('all', 'both', 'learner', 'admin', 'coach')]
    [string]$SurfaceSelection = 'all',
    [ValidateRange(1024, 65535)]
    [int]$Port = 55432
)
$record = [ordered]@{
    stop = [bool]$Stop
    selection = $SurfaceSelection
    port = $Port
    port_type = $Port.GetType().FullName
    powershell_version = $PSVersionTable.PSVersion.ToString()
}
[IO.File]::WriteAllText(
    (Join-Path $PSScriptRoot 'marker.json'),
    ($record | ConvertTo-Json -Compress)
)
"""
        + exit_line
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_bootstrap_parses_without_running_a_launcher() -> None:
    assert BOOTSTRAP.is_file()
    command = (
        "$errors = $null; $tokens = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"{_quote(BOOTSTRAP)}, [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | Out-String; exit 1 }; 'parsed'"
    )
    result = _run_powershell(PWSH, command)
    assert result.returncode == 0, result.stderr
    assert "parsed" in result.stdout


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_modern_powershell_does_not_relaunch_or_touch_fixture(tmp_path: Path) -> None:
    fixture = _fixture_script(tmp_path / "fixture.ps1")
    marker = _quote(tmp_path / "marker.json")
    command = f"""
. {_quote(BOOTSTRAP)}
$result = Invoke-LocalRuntimeRelaunch -ScriptPath {_quote(fixture)} -Parameters @{{
    Stop = $true
    SurfaceSelection = 'coach'
    Port = 45678
}}
[ordered]@{{ result = [bool]$result; marker = [IO.File]::Exists({marker}) }} |
    ConvertTo-Json -Compress
"""
    result = _run_powershell(PWSH, command)
    assert result.returncode == 0, result.stderr
    observed = _last_json(result.stdout)
    assert observed == {"result": False, "marker": False}


@pytest.mark.skipif(
    WINDOWS_POWERSHELL is None or PWSH is None,
    reason="Windows PowerShell 5.1 and PowerShell 7 are required",
)
@pytest.mark.parametrize(
    ("stop", "selection", "port"),
    [(True, "coach", 45678), (False, "learner", 45679)],
)
def test_windows_powershell_forwards_typed_literal_arguments(
    tmp_path: Path, stop: bool, selection: str, port: int
) -> None:
    fixture = _fixture_script(tmp_path / "fixture.ps1")
    marker = _quote(tmp_path / "marker.json")
    command = f"""
$ErrorActionPreference = 'Stop'
. {_quote(BOOTSTRAP)}
$result = Invoke-LocalRuntimeRelaunch -ScriptPath {_quote(fixture)} -Parameters @{{
    Stop = ${str(stop).lower()}
    SurfaceSelection = '{selection}'
    Port = {port}
}}
[ordered]@{{ result = [bool]$result; marker = [IO.File]::Exists({marker}) }} |
    ConvertTo-Json -Compress
"""
    result = _run_powershell(WINDOWS_POWERSHELL, command)
    assert result.returncode == 0, result.stderr
    observed = _last_json(result.stdout)
    assert observed == {"result": True, "marker": True}
    marker = json.loads((tmp_path / "marker.json").read_text(encoding="utf-8-sig"))
    version_text = str(marker.pop("powershell_version"))
    assert marker == {
        "stop": stop,
        "selection": selection,
        "port": port,
        "port_type": "System.Int32",
    }
    assert tuple(int(part) for part in version_text.split(".")[:2]) >= (7, 4)


@pytest.mark.skipif(
    WINDOWS_POWERSHELL is None or PWSH is None,
    reason="Windows PowerShell 5.1 and PowerShell 7 are required",
)
def test_relaunch_throws_on_child_failure_without_reporting_child_output(
    tmp_path: Path,
) -> None:
    fixture = _fixture_script(tmp_path / "failing.ps1", exit_code=19)
    marker = _quote(tmp_path / "marker.json")
    command = f"""
$ErrorActionPreference = 'Stop'
. {_quote(BOOTSTRAP)}
try {{
    $null = Invoke-LocalRuntimeRelaunch -ScriptPath {_quote(fixture)} -Parameters @{{
        Stop = $false
        SurfaceSelection = 'admin'
        Port = 45680
    }}
    'NO_THROW'
    exit 2
}}
catch {{
    [ordered]@{{ threw = $true; marker = [IO.File]::Exists({marker}) }} |
        ConvertTo-Json -Compress
}}
"""
    result = _run_powershell(WINDOWS_POWERSHELL, command)
    assert result.returncode == 0, result.stderr
    assert _last_json(result.stdout) == {"threw": True, "marker": True}


@pytest.mark.skipif(
    WINDOWS_POWERSHELL is None or PWSH is None,
    reason="Windows PowerShell 5.1 and PowerShell 7 are required",
)
@pytest.mark.parametrize(
    "parameters",
    [
        "@{ Unexpected = 'value' }",
        "@{ Stop = 'true' }",
        "@{ SurfaceSelection = 'remote' }",
        "@{ Port = '45681' }",
    ],
)
def test_relaunch_rejects_untyped_or_unsupported_arguments_before_child(
    tmp_path: Path, parameters: str
) -> None:
    fixture = _fixture_script(tmp_path / "fixture.ps1")
    marker = _quote(tmp_path / "marker.json")
    command = f"""
$ErrorActionPreference = 'Stop'
. {_quote(BOOTSTRAP)}
try {{
    $null = Invoke-LocalRuntimeRelaunch -ScriptPath {_quote(fixture)} -Parameters {parameters}
    [ordered]@{{ threw = $false; marker = [IO.File]::Exists({marker}) }} |
        ConvertTo-Json -Compress
}}
catch {{
    [ordered]@{{ threw = $true; marker = [IO.File]::Exists({marker}) }} |
        ConvertTo-Json -Compress
}}
"""
    result = _run_powershell(WINDOWS_POWERSHELL, command)
    assert result.returncode == 0, result.stderr
    assert _last_json(result.stdout) == {"threw": True, "marker": False}


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_node_resolution_prefers_existing_path_node24_without_mutating_path(
    tmp_path: Path,
) -> None:
    node24 = (
        Path(os.environ["USERPROFILE"])
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node.exe"
    )
    if not node24.is_file():
        pytest.skip("The bundled Node 24 runtime is not installed")
    node_dir = node24.parent
    command = f"""
. {_quote(BOOTSTRAP)}
$before_user = [Environment]::GetEnvironmentVariable('PATH', 'User')
$before_machine = [Environment]::GetEnvironmentVariable('PATH', 'Machine')
$env:PATH = {_quote(node_dir)}
$before = $env:PATH
$resolved = Get-LocalNodeExecutable
[ordered]@{{
    path = $resolved
    process_path_unchanged = ($env:PATH -eq $before)
    user_path_unchanged = ([Environment]::GetEnvironmentVariable('PATH', 'User') -eq $before_user)
    machine_path_unchanged = (
        [Environment]::GetEnvironmentVariable('PATH', 'Machine') -eq $before_machine
    )
}} | ConvertTo-Json -Compress
"""
    result = _run_powershell(PWSH, command)
    assert result.returncode == 0, result.stderr
    observed = _last_json(result.stdout)
    assert Path(str(observed["path"])).resolve().samefile(node24)
    assert observed["process_path_unchanged"] is True
    assert observed["user_path_unchanged"] is True
    assert observed["machine_path_unchanged"] is True


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_node_resolution_uses_existing_codex_fallback_without_installing(
    tmp_path: Path,
) -> None:
    source = (
        Path(os.environ["USERPROFILE"])
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node.exe"
    )
    if not source.is_file():
        pytest.skip("The bundled Node 24 runtime is not installed")
    user_profile = tmp_path / "user-profile"
    fallback = (
        user_profile
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node.exe"
    )
    fallback.parent.mkdir(parents=True)
    shutil.copy2(source, fallback)
    command = f"""
. {_quote(BOOTSTRAP)}
$env:USERPROFILE = {_quote(user_profile)}
$env:PATH = {_quote(tmp_path)}
$resolved = Get-LocalNodeExecutable
[ordered]@{{
    path = $resolved
    process_path = $env:PATH
    fallback_exists = [IO.File]::Exists({_quote(fallback)})
}} | ConvertTo-Json -Compress
"""
    result = _run_powershell(PWSH, command)
    assert result.returncode == 0, result.stderr
    observed = _last_json(result.stdout)
    assert Path(str(observed["path"])).resolve().samefile(fallback)
    assert observed["process_path"] == str(tmp_path)
    assert observed["fallback_exists"] is True


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")
def test_node_resolution_rejects_only_node22_and_does_not_download_or_install(
    tmp_path: Path,
) -> None:
    node22 = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "nodejs"
    node22_executable = node22 / "node.exe"
    if not node22_executable.is_file():
        pytest.skip("The installed Node 22 fixture is not available")
    user_profile = tmp_path / "empty-user-profile"
    command = f"""
. {_quote(BOOTSTRAP)}
$env:USERPROFILE = {_quote(user_profile)}
$env:PATH = {_quote(node22)}
try {{
    $null = Get-LocalNodeExecutable
    [ordered]@{{ threw = $false }} | ConvertTo-Json -Compress
}}
catch {{
    [ordered]@{{
        threw = $true
        fallback_created = [IO.Directory]::Exists({_quote(user_profile / ".cache")})
    }} | ConvertTo-Json -Compress
}}
"""
    result = _run_powershell(PWSH, command)
    assert result.returncode == 0, result.stderr
    assert _last_json(result.stdout) == {"threw": True, "fallback_created": False}


def test_bootstrap_has_no_elevation_install_or_execution_policy_bypass() -> None:
    source = BOOTSTRAP.read_text(encoding="utf-8")
    assert "-NoProfile" in source
    assert "-NonInteractive" in source
    assert "-File" in source
    assert "-Verb RunAs" not in source
    assert "ExecutionPolicy Bypass" not in source
    assert "Invoke-WebRequest" not in source
    assert "Start-BitsTransfer" not in source
    assert "winget" not in source.lower()
    assert "SetEnvironmentVariable" not in source


def _existing_process_branch() -> str:
    source = (ROOT / "scripts" / "Start-LocalPlatform.ps1").read_text(encoding="utf-8")
    start = "    if ($Live.Count -eq @($SelectedSurfaces).Count) {"
    end = "    if ($Live.Count) {"
    return start + source.split(start, 1)[1].split(end, 1)[0]


def _process_record_gate() -> str:
    source = (ROOT / "scripts" / "Start-LocalPlatform.ps1").read_text(encoding="utf-8")
    start = "    $Live = @()"
    end = "    if ($Stop) {"
    return start + source.split(start, 1)[1].split(end, 1)[0]


def _run_existing_process_branch(
    tmp_path: Path,
    *,
    health_status: str,
    login_status: int,
    owned_selected_names: tuple[str, ...] = ("learner", "admin", "coach"),
    anonymous_ok: bool = True,
) -> dict[str, object]:
    api_marker = tmp_path / "api-called.txt"
    (tmp_path / "Start-LocalApi.ps1").write_text(
        """[CmdletBinding()]
param([switch]$StudioVideo)
[IO.File]::WriteAllText(
    """
        + _quote(api_marker)
        + """,
    [string][bool]$StudioVideo
)
""",
        encoding="utf-8",
    )
    branch = _existing_process_branch().replace("$PSScriptRoot", "$scriptRoot")
    owned_names = ", ".join(f"'{name}'" for name in owned_selected_names)
    command = f"""
$ErrorActionPreference = 'Stop'
$scriptRoot = {_quote(tmp_path)}
$script:HealthStatus = '{health_status}'
$script:LoginStatus = {login_status}
$script:HealthCalls = 0
$script:Requests = @()
$script:AnonymousProbes = @()
function Assert-LocalAnonymousApiRoute {{
    param([hashtable]$Surface)
    $script:AnonymousProbes += $Surface.name
    if (${str(not anonymous_ok).lower()}) {{ throw 'anonymous API probe failed' }}
}}
function Invoke-RestMethod {{
    param([string]$Uri, [int]$TimeoutSec, [switch]$NoProxy)
    $script:HealthCalls += 1
    if ($script:HealthStatus -eq '__unavailable__') {{ throw 'health endpoint unavailable' }}
    [pscustomobject]@{{ status = $script:HealthStatus }}
}}
function Invoke-WebRequest {{
    param([string]$Uri, [hashtable]$Headers, [int]$TimeoutSec, [switch]$NoProxy)
    $script:Requests += "$Uri|$($Headers['Host'])"
    [pscustomobject]@{{ StatusCode = $script:LoginStatus }}
}}
function Invoke-ExistingProcessBranch {{
    $Live = @(@{{ id = 1 }}, @{{ id = 2 }}, @{{ id = 3 }})
    $SelectedSurfaces = @(
        @{{ name = 'learner'; port = 3100 }}
        @{{ name = 'admin'; port = 3101 }}
        @{{ name = 'coach'; port = 3102 }}
    )
    $OwnedSelectedNames = @({owned_names})
    $Stop = $false
    $StudioVideo = $true
    {branch}
    'completed'
}}
$completed = $false
try {{
    $null = Invoke-ExistingProcessBranch
    $completed = $true
}}
catch {{
    $error_text = $_.Exception.Message
}}
[ordered]@{{
    completed = $completed
    error_text = if ($error_text) {{ $error_text }} else {{ '' }}
    health_calls = $script:HealthCalls
    requests = @($script:Requests)
    anonymous_probes = @($script:AnonymousProbes)
    api_called = [IO.File]::Exists({_quote(api_marker)})
}} | ConvertTo-Json -Compress
"""
    result = _run_powershell(PWSH, command)
    assert result.returncode == 0, result.stderr
    return _last_json(result.stdout)


def test_existing_process_branch_rejects_unready_api_without_ready_claim(
    tmp_path: Path,
) -> None:
    observed = _run_existing_process_branch(tmp_path, health_status="starting", login_status=200)
    assert observed["completed"] is False
    assert observed["health_calls"] == 1
    assert observed["requests"] == []
    assert observed["api_called"] is True
    assert "not ready" in str(observed["error_text"])


def test_existing_process_branch_rejects_unavailable_api_without_ready_claim(
    tmp_path: Path,
) -> None:
    observed = _run_existing_process_branch(
        tmp_path, health_status="__unavailable__", login_status=200
    )
    assert observed["completed"] is False
    assert observed["health_calls"] == 1
    assert observed["requests"] == []
    assert observed["api_called"] is True
    assert "unavailable" in str(observed["error_text"])


def test_existing_process_branch_rejects_matching_count_without_every_owner(
    tmp_path: Path,
) -> None:
    observed = _run_existing_process_branch(
        tmp_path,
        health_status="ready",
        login_status=200,
        owned_selected_names=("learner", "learner", "admin"),
    )
    assert observed["completed"] is False
    assert observed["health_calls"] == 0
    assert observed["requests"] == []
    assert observed["api_called"] is False
    assert "every selected app" in str(observed["error_text"])


def test_existing_process_branch_checks_all_logins_without_destructive_actions(
    tmp_path: Path,
) -> None:
    branch = _existing_process_branch()
    assert "Start-Process" not in branch
    assert "taskkill" not in branch.lower()
    assert "Stop-Process" not in branch

    observed = _run_existing_process_branch(tmp_path, health_status="ready", login_status=200)
    assert observed["completed"] is True
    assert observed["health_calls"] == 1
    assert observed["api_called"] is True
    assert observed["requests"] == [
        "http://127.0.0.1:3100/login|learner.localhost:3100",
        "http://127.0.0.1:3101/login|admin.localhost:3101",
        "http://127.0.0.1:3102/login|coach.localhost:3102",
    ]
    assert observed["anonymous_probes"] == ["learner", "admin", "coach"]


def test_existing_process_branch_rejects_failed_anonymous_probe(tmp_path: Path) -> None:
    observed = _run_existing_process_branch(
        tmp_path, health_status="ready", login_status=200, anonymous_ok=False
    )
    assert observed["completed"] is False
    assert observed["anonymous_probes"] == ["learner"]
    assert "anonymous API probe failed" in str(observed["error_text"])


def test_existing_process_branch_rejects_unready_surface_without_ready_claim(
    tmp_path: Path,
) -> None:
    observed = _run_existing_process_branch(tmp_path, health_status="ready", login_status=503)
    assert observed["completed"] is False
    assert observed["health_calls"] == 1
    assert len(observed["requests"]) == 1
    assert "not ready" in str(observed["error_text"])


def test_process_record_gate_rejects_duplicate_surface_before_ready_path(
    tmp_path: Path,
) -> None:
    process_file = tmp_path / "ui-processes.json"
    process_file.write_text(
        json.dumps(
            {
                "repository": "repo",
                "processes": [
                    {
                        "name": "learner",
                        "port": 3100,
                        "id": 101,
                        "started_at": 1,
                        "executable": "node.exe",
                    },
                    {
                        "name": "learner",
                        "port": 3100,
                        "id": 102,
                        "started_at": 1,
                        "executable": "node.exe",
                    },
                    {
                        "name": "admin",
                        "port": 3101,
                        "id": 103,
                        "started_at": 1,
                        "executable": "node.exe",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    gate = _process_record_gate()
    command = f"""
$ErrorActionPreference = 'Stop'
$Repository = 'repo'
$Node = 'node.exe'
$ProcessFile = {_quote(process_file)}
$SurfaceSelection = 'all'
$Stop = $false
$script:Lookups = @()
function Get-Process {{
    param([int]$Id, [object]$ErrorAction)
    $script:Lookups += $Id
    [pscustomobject]@{{
        Id = $Id
        StartTime = [DateTime]::FromFileTimeUtc(1)
        Path = 'node.exe'
    }}
}}
$stage = 'not-entered'
$error_text = ''
try {{
    {gate}
    if ($Live.Count -eq @($SelectedSurfaces).Count) {{ $stage = 'ready-branch' }}
    elseif ($Live.Count) {{ $stage = 'partial' }}
    else {{ $stage = 'empty' }}
}}
catch {{
    $stage = 'rejected'
    $error_text = $_.Exception.Message
}}
[ordered]@{{
    stage = $stage
    lookups = @($script:Lookups)
    error_text = $error_text
}} | ConvertTo-Json -Compress
"""
    result = _run_powershell(PWSH, command)
    assert result.returncode == 0, result.stderr
    observed = _last_json(result.stdout)
    assert observed["stage"] == "rejected"
    assert observed["stage"] != "ready-branch"
    assert "ambiguous" in str(observed["error_text"])
