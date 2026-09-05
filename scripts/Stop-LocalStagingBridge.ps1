[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDirectory = Join-Path $RepositoryRoot ".tmp\local-staging-bridge"
$PidFile = Join-Path $RuntimeDirectory "processes.json"
$StartupLock = $null

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null
try {
    try {
        $StartupLock = [IO.File]::Open(
            (Join-Path $RuntimeDirectory "startup.lock"),
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None
        )
    }
    catch {
        throw "Another local staging bridge start or stop operation is already running."
    }

    if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) {
        Write-Host "No tracked local staging bridge is running."
        return
    }

    $ResolvedPidFile = (Resolve-Path -LiteralPath $PidFile).Path
    $ExpectedPrefix = $RuntimeDirectory.TrimEnd("\") + "\"
    if (-not $ResolvedPidFile.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to use a process file outside the expected runtime directory."
    }

    $Record = Get-Content -LiteralPath $ResolvedPidFile -Raw | ConvertFrom-Json
    if ($Record.repository -ne $RepositoryRoot) {
        throw "The tracked process file belongs to a different workspace."
    }

    foreach ($Tracked in $Record.processes) {
        $Process = Get-Process -Id ([int]$Tracked.id) -ErrorAction SilentlyContinue
        if ($null -eq $Process) {
            continue
        }
        $ExpectedStart = [long]$Tracked.started_at_file_time_utc
        $ActualStart = $Process.StartTime.ToFileTimeUtc()
        if ([Math]::Abs($ActualStart - $ExpectedStart) -gt [TimeSpan]::TicksPerSecond) {
            Write-Warning "Skipping process $($Tracked.id): its start time no longer matches the tracked $($Tracked.name) process."
            continue
        }
        & taskkill.exe /PID $Process.Id /T /F *> $null
        Write-Host "Stopped $($Tracked.name) process $($Process.Id)."
    }

    Remove-Item -LiteralPath $ResolvedPidFile -Force
    Write-Host "Local staging bridge stopped. Logs remain at $RuntimeDirectory."
}
finally {
    if ($null -ne $StartupLock) {
        $StartupLock.Dispose()
    }
}
