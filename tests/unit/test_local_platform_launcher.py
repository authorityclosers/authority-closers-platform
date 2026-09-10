"""Offline launcher configuration checks; never start or stop runtime processes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "Start-LocalPlatform.ps1"
POWERSHELL = shutil.which("pwsh")


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required for launcher parsing")
def test_launcher_parses_without_executing_runtime_operations():
    command = (
        "$errors = $null; $tokens = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{str(LAUNCHER).replace(chr(39), chr(39) * 2)}', [ref]$tokens, [ref]$errors)"
        " | Out-Null; if ($errors.Count) { exit 1 }"
    )
    result = subprocess.run(  # noqa: S603 - fixed offline parser invocation
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required for environment evaluation")
def test_child_environment_is_local_only_and_disables_sensitive_native_tracing():
    source = LAUNCHER.read_text(encoding="utf-8")
    # Evaluate only the environment-building block, never the launcher body.
    configuration = source.split("    $ChildEnvironment = @{}", 1)[1].split(
        "    $Started = @()", 1
    )[0]
    command = "$ChildEnvironment = @{}\n" + configuration
    command += "\n$ChildEnvironment | ConvertTo-Json -Compress"
    result = subprocess.run(  # noqa: S603 - fixed offline configuration block
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        env={
            **os.environ,
            "AC_TEST_REMOTE_SETTING": "synthetic-remote-fixture",
            "PG_TEST_SETTING": "synthetic-fixture",
            "NEXT_PUBLIC_AC_TEST_SETTING": "synthetic-fixture",
            "NODE_DEBUG": "http,net",
            "NODE_OPTIONS": "--trace-warnings",
            "NEXT_TRACE_SPAN_THRESHOLD_MS": "0",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    environment = json.loads(result.stdout)
    for name in ("AC_TEST_REMOTE_SETTING", "PG_TEST_SETTING", "NEXT_PUBLIC_AC_TEST_SETTING"):
        assert environment[name] is None
    assert environment["AC_DEV_AUTH_BRIDGE_ENABLED"] == "false"
    assert environment["AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED"] == "false"
    assert environment["AC_DEV_ADMIN_ACCESS_JWT"] == ""
    assert environment["AC_DEV_LOCAL_SANDBOX_ENABLED"] == "true"
    assert environment["NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED"] == "true"
    assert environment["AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN"] == "http://admin.localhost:3101"
    assert environment["AC_DEV_ADMIN_API_ORIGIN"] == "http://127.0.0.1:8000"
    assert environment["AC_DEV_API_ORIGIN"] == "http://127.0.0.1:8000"
    assert environment["NODE_DEBUG"] == environment["NODE_OPTIONS"] == ""
    assert environment["NEXT_TRACE_SPAN_THRESHOLD_MS"] == "9007199254740991"
    assert environment["NEXT_TELEMETRY_DISABLED"] == "1"


def test_launcher_process_and_file_guards_remain_explicit():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "$Record.repository -ne $Repository" in source
    assert "$Process.StartTime.ToFileTimeUtc() -eq $Tracked.started_at" in source
    assert "$Process.Path -ne $Tracked.executable -or $Process.Path -ne $Node" in source
    assert "-WindowStyle Hidden" in source
    assert "-NoProxy" in source
    assert "ReparsePoint" in source
    assert "'ui-startup.lock'" in source
    assert "'learner.stdout.log'" in source
    assert "'admin.stderr.log'" in source
    assert "unknown processes are not stopped" in source


def test_individual_surface_restart_preserves_the_other_managed_process():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "[ValidateSet('all', 'both', 'learner', 'admin', 'coach')]" in source
    assert "name = 'coach'; port = 3102" in source
    assert "$PreservedRecords += $Tracked" in source
    assert "processes = @($PreservedRecords) + @($Records)" in source
    assert "foreach ($Surface in $SelectedSurfaces)" in source
    assert "$_.LocalPort -in @($SelectedSurfaces.port)" in source


def test_local_backup_is_pinned_to_sandbox_and_does_not_restore():
    source = (ROOT / "scripts/Backup-LocalSandbox.ps1").read_text(encoding="utf-8")
    assert "$Marker.repository -ne $Repository" in source
    assert "$Marker.port -ne 55432" in source
    assert "-d ac_local_sandbox -Fc -f $Archive" in source
    assert "pg_restore.exe') --list $Archive" in source
    assert "ReparsePoint" in source
    assert "Backup target already exists" in source


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required for child environment proof")
@pytest.mark.parametrize("fail_inside", [False, True])
def test_api_environment_removes_names_and_restores_original_empty_values(fail_inside):
    source = (ROOT / "scripts/Start-LocalApi.ps1").read_text(encoding="utf-8")
    # Only evaluate the exact two environment blocks. Never run migrations,
    # load credentials, seed data, or start/stop the application.
    configuration = source.split("$Previous = @{}", 1)[1].split("    Push-Location $Repository", 1)[
        0
    ]
    cleanup = source.rsplit("\nfinally {\n", 1)[1].split("\n$Deadline", 1)[0]
    python = str(Path(sys.executable)).replace("'", "''")
    probe = (
        "import json,os; print(json.dumps({"
        '"no_pg_names":not any(n.upper().startswith("PG") for n in os.environ),'
        '"no_prior_ac":"AC_PARENT_VALUE_FIXTURE" not in os.environ and '
        '"AC_PARENT_EMPTY_FIXTURE" not in os.environ,'
        '"local_present":os.environ.get("AC_CHILD_FIXTURE")=="local-fixture",'
        '"unrelated_present":os.environ.get("LAUNCHER_UNRELATED_FIXTURE")=="keep"}))'
    )
    command = (
        "$ErrorActionPreference = 'Stop'\n"
        "$env:PG_PARENT_VALUE_FIXTURE = 'synthetic-original'\n"
        "$env:PG_PARENT_EMPTY_FIXTURE = ''\n"
        "$env:AC_PARENT_VALUE_FIXTURE = 'synthetic-original'\n"
        "$env:AC_PARENT_EMPTY_FIXTURE = ''\n"
        "$env:LAUNCHER_UNRELATED_FIXTURE = 'keep'\n"
        "$LocalEnvironment = @{ AC_CHILD_FIXTURE = 'local-fixture' }\n"
        "$Previous = @{}\n"
        + configuration
        + f"\n    $ChildProbe = & '{python}' -c '{probe}' | ConvertFrom-Json\n"
        + "    if ($LASTEXITCODE -ne 0) { throw 'child probe failed' }\n"
        + ("    throw 'synthetic startup failure'\n" if fail_inside else "")
        + "}\ncatch { if ($_.Exception.Message -ne 'synthetic startup failure') { throw } }"
        + "\nfinally {\n"
        + cleanup
        + "\n$Restored = [Environment]::GetEnvironmentVariables('Process')\n"
        + "[ordered]@{ child = $ChildProbe; "
        "pg_value = $env:PG_PARENT_VALUE_FIXTURE -eq 'synthetic-original'; "
        "ac_value = $env:AC_PARENT_VALUE_FIXTURE -eq 'synthetic-original'; "
        "pg_empty = $Restored.Contains('PG_PARENT_EMPTY_FIXTURE') -and "
        "$Restored['PG_PARENT_EMPTY_FIXTURE'] -eq ''; "
        "ac_empty = $Restored.Contains('AC_PARENT_EMPTY_FIXTURE') -and "
        "$Restored['AC_PARENT_EMPTY_FIXTURE'] -eq ''; "
        "child_removed = -not $Restored.Contains('AC_CHILD_FIXTURE'); "
        "unrelated = $env:LAUNCHER_UNRELATED_FIXTURE -eq 'keep' "
        "} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(  # noqa: S603 - exact offline environment blocks and synthetic probe
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    observed = json.loads(result.stdout)
    assert all(observed.pop("child").values())
    assert all(observed.values())
