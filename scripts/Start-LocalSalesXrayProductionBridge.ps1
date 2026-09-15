[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [ValidateRange(1024, 65535)]
    [int]$BrowserPort = 3016,
    [ValidateRange(1024, 65535)]
    [int]$InnerPort = 3116
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDirectory = Join-Path $RepositoryRoot ".tmp\local-sales-xray-production-bridge"
$PidFile = Join-Path $RuntimeDirectory "processes.json"
$BrowserOrigin = "http://salesxray.localhost:$BrowserPort"
$InnerOrigin = "http://127.0.0.1:$InnerPort"
$ProductionOrigin = "https://salesxray.authorityclosers.com"

if ($BrowserPort -eq $InnerPort) {
    throw "BrowserPort and InnerPort must be different."
}

function Assert-MajorVersion {
    param(
        [Parameter(Mandatory)] [string]$Command,
        [Parameter(Mandatory)] [int]$RequiredMajor
    )
    $Executable = Get-Command $Command -ErrorAction Stop
    $VersionText = (& $Executable.Source --version 2>$null | Select-Object -First 1).Trim().TrimStart("v")
    $Parsed = $null
    if (-not [version]::TryParse($VersionText, [ref]$Parsed) -or $Parsed.Major -ne $RequiredMajor) {
        throw "$Command major version $RequiredMajor is required; found '$VersionText'."
    }
    return $Executable.Source
}

function Find-Node24 {
    $Candidates = @(& where.exe node.exe 2>$null) | Select-Object -Unique
    foreach ($Candidate in $Candidates) {
        try {
            $VersionText = (& $Candidate --version 2>$null | Select-Object -First 1).Trim().TrimStart("v")
            $Parsed = $null
            if ([version]::TryParse($VersionText, [ref]$Parsed) -and $Parsed.Major -eq 24) {
                return (Resolve-Path -LiteralPath $Candidate).Path
            }
        }
        catch {
            continue
        }
    }
    throw "Node major version 24 is required and was not found on PATH."
}

function Stop-StartedProcess {
    param([System.Diagnostics.Process]$Process)
    if ($null -eq $Process -or $Process.HasExited) { return }
    & taskkill.exe /PID $Process.Id /T /F *> $null
}

function Test-HttpHealth {
    param(
        [Parameter(Mandatory)] [string]$Url,
        [Parameter(Mandatory)] [scriptblock]$Predicate
    )
    try {
        $Response = Invoke-WebRequest -Uri $Url -TimeoutSec 10
        return [bool](& $Predicate $Response)
    }
    catch {
        return $false
    }
}

function Wait-ForHttpHealth {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory)] [string]$Url,
        [Parameter(Mandatory)] [scriptblock]$Predicate
    )
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds(120)
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        if ($Process.HasExited) { throw "$Name exited before its health check passed." }
        if (Test-HttpHealth -Url $Url -Predicate $Predicate) { return }
        Start-Sleep -Seconds 2
        $Process.Refresh()
    }
    throw "$Name did not become healthy within 120 seconds."
}

function Get-TrackedProcesses {
    param([Parameter(Mandatory)] [object]$Record)
    if ($Record.repository -ne $RepositoryRoot) {
        throw "The tracked process file belongs to a different workspace."
    }
    return @($Record.processes | ForEach-Object {
            $Tracked = $_
            $Process = Get-Process -Id ([int]$Tracked.id) -ErrorAction SilentlyContinue
            if ($null -eq $Process) { return }
            $ExpectedStart = [long]$Tracked.started_at_file_time_utc
            $ActualStart = $Process.StartTime.ToFileTimeUtc()
            if ([Math]::Abs($ActualStart - $ExpectedStart) -le [TimeSpan]::TicksPerSecond) { $Tracked }
        })
}

if ($PSVersionTable.PSEdition -ne "Core" -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or later is required."
}
if (-not (Get-Command Start-Process).Parameters.ContainsKey("Environment")) {
    throw "This workflow requires PowerShell 7.4 or later."
}
if (-not (Test-Path -LiteralPath (Join-Path $RepositoryRoot "apps\sales-xray-web\package.json") -PathType Leaf)) {
    throw "The Sales Xray app is not present in this worktree. Use the reviewed UI snapshot before starting the bridge."
}

$NodePath = Find-Node24
$NodeDirectory = Split-Path -Parent $NodePath
$env:PATH = "$NodeDirectory$([IO.Path]::PathSeparator)$env:PATH"
$null = Assert-MajorVersion -Command "node" -RequiredMajor 24
$PnpmPath = Assert-MajorVersion -Command "pnpm.cmd" -RequiredMajor 11

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null
$StartupLock = $null
$CreatedPidFile = $false
$InnerProcess = $null
$BridgeProcess = $null
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
        throw "Another local Sales Xray bridge start or stop operation is already running."
    }

    if (Test-Path -LiteralPath $PidFile -PathType Leaf) {
        $Existing = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
        if ((Get-TrackedProcesses -Record $Existing).Count -gt 0) {
            throw "A tracked local Sales Xray bridge is already running. Run the stop script first."
        }
        Remove-Item -LiteralPath $PidFile -Force
    }

    $OccupiedPorts = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in @($BrowserPort, $InnerPort) }
    if ($OccupiedPorts) {
        $Owners = ($OccupiedPorts | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "Requested ports $BrowserPort or $InnerPort are already in use (process IDs: $Owners)."
    }

    $CommonEnvironment = @{
        PATH = $env:PATH
        NODE_ENV = "development"
        AC_CONVERSATION_API_ORIGIN = ""
        AC_SALES_XRAY_DEV_LIVE_DATA = "true"
        NEXT_TRACE_SPAN_THRESHOLD_MS = "9007199254740991"
        NODE_DEBUG = ""
    }

    $InnerProcess = Start-Process -FilePath $PnpmPath `
        -ArgumentList @("--filter", "@ac/sales-xray-web", "exec", "next", "dev", "--webpack", "--hostname", "127.0.0.1", "--port", "$InnerPort") `
        -WorkingDirectory $RepositoryRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $RuntimeDirectory "sales-xray.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDirectory "sales-xray.err.log") `
        -Environment $CommonEnvironment `
        -PassThru

    $BridgeEnvironment = @{
        PATH = $env:PATH
        NODE_ENV = "development"
        NODE_DEBUG = ""
    }
    $BridgeProcess = Start-Process -FilePath $NodePath `
        -ArgumentList @(
            (Join-Path $RepositoryRoot "scripts\sales-xray-production-bridge.mjs"),
            "--browser-origin", $BrowserOrigin,
            "--inner-origin", $InnerOrigin,
            "--port", "$BrowserPort"
        ) `
        -WorkingDirectory $RepositoryRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $RuntimeDirectory "bridge.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDirectory "bridge.err.log") `
        -Environment $BridgeEnvironment `
        -PassThru

    $Record = @{
        repository = $RepositoryRoot
        created_at = [DateTimeOffset]::UtcNow.ToString("o")
        browser_origin = $BrowserOrigin
        inner_origin = $InnerOrigin
        production_origin = $ProductionOrigin
        processes = @(
            @{ name = "sales-xray"; id = $InnerProcess.Id; started_at_file_time_utc = $InnerProcess.StartTime.ToFileTimeUtc() },
            @{ name = "bridge"; id = $BridgeProcess.Id; started_at_file_time_utc = $BridgeProcess.StartTime.ToFileTimeUtc() }
        )
    }
    $Record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $PidFile -Encoding utf8
    $CreatedPidFile = $true

    Wait-ForHttpHealth -Name "Sales Xray UI" -Process $InnerProcess -Url "$InnerOrigin/" -Predicate {
        param($Response)
        $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500
    }
    Wait-ForHttpHealth -Name "Sales Xray production bridge" -Process $BridgeProcess -Url "$BrowserOrigin/health" -Predicate {
        param($Response)
        $Value = $Response.Content | ConvertFrom-Json
        $Value.status -eq "ok" -and
        $Value.mode -eq "development-only" -and
        $Value.data_mode -eq "production-live" -and
        $Value.upstream_origin -eq $ProductionOrigin
    }
}
catch {
    Stop-StartedProcess -Process $BridgeProcess
    Stop-StartedProcess -Process $InnerProcess
    if ($CreatedPidFile -and (Test-Path -LiteralPath $PidFile)) { Remove-Item -LiteralPath $PidFile -Force }
    throw "Local Sales Xray production bridge startup failed: $($_.Exception.Message) Logs: $RuntimeDirectory"
}
finally {
    if ($null -ne $StartupLock) { $StartupLock.Dispose() }
}

Write-Host "Local Sales Xray production bridge is healthy."
Write-Host "UI:       $BrowserOrigin/login"
Write-Host "Data:     live production API through $ProductionOrigin"
Write-Host "Sessions: ephemeral HttpOnly local handle; sign in normally in this browser"
Write-Host "Provider: no automatic analysis jobs are started by the bridge"
Write-Host "Stop:     pwsh -NoProfile -File scripts/Stop-LocalSalesXrayProductionBridge.ps1"
if (-not $NoBrowser) { Start-Process $BrowserOrigin }
