[CmdletBinding()]
param(
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDirectory = Join-Path $RepositoryRoot ".tmp\local-staging-bridge"
$PidFile = Join-Path $RuntimeDirectory "processes.json"
$LearnerOrigin = "http://learner.localhost:3000"
$AdminOrigin = "http://admin.localhost:3001"
$AdminStagingOrigin = "https://admin-staging.authorityclosers.com"
$LearnerStagingOrigin = "https://staging.authorityclosers.com"
$AccessJwtPattern = '^[A-Za-z0-9_-]{16,2048}\.[A-Za-z0-9_-]{16,4096}\.[A-Za-z0-9_-]{16,2048}$'

function Assert-ToolVersion {
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

function Find-NodeMajor {
    param([Parameter(Mandatory)] [int]$RequiredMajor)
    $Candidates = @(& where.exe node.exe 2>$null) | Select-Object -Unique
    foreach ($Candidate in $Candidates) {
        try {
            $VersionText = (& $Candidate --version 2>$null | Select-Object -First 1).Trim().TrimStart("v")
            $Parsed = $null
            if ([version]::TryParse($VersionText, [ref]$Parsed) -and $Parsed.Major -eq $RequiredMajor) {
                return (Resolve-Path -LiteralPath $Candidate).Path
            }
        }
        catch {
            continue
        }
    }
    throw "Node major version $RequiredMajor is required and was not found on PATH. The repository .nvmrc declares the supported version."
}

function Test-Health {
    param([Parameter(Mandatory)] [scriptblock]$Probe)
    try {
        return [bool](& $Probe)
    }
    catch {
        return $false
    }
}

function Wait-ForHealth {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [System.Diagnostics.Process]$Process,
        [Parameter(Mandatory)] [scriptblock]$Probe
    )
    $Deadline = [DateTimeOffset]::UtcNow.AddSeconds(90)
    while ([DateTimeOffset]::UtcNow -lt $Deadline) {
        if ($Process.HasExited) {
            throw "$Name exited before its health check passed."
        }
        if (Test-Health -Probe $Probe) {
            return
        }
        Start-Sleep -Seconds 2
        $Process.Refresh()
    }
    throw "$Name did not become healthy within 90 seconds."
}

function Stop-StartedProcess {
    param([System.Diagnostics.Process]$Process)
    if ($null -eq $Process -or $Process.HasExited) {
        return
    }
    & taskkill.exe /PID $Process.Id /T /F *> $null
}

if ($PSVersionTable.PSEdition -ne "Core" -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7 or later is required."
}
if (-not (Get-Command Start-Process).Parameters.ContainsKey("Environment")) {
    throw "This workflow requires a PowerShell 7 release with Start-Process -Environment support (7.4 or later)."
}

$NodePath = Find-NodeMajor -RequiredMajor 24
$NodeDirectory = Split-Path -Parent $NodePath
$env:PATH = "$NodeDirectory$([IO.Path]::PathSeparator)$env:PATH"
$null = Assert-ToolVersion -Command "node" -RequiredMajor 24
$PnpmPath = Assert-ToolVersion -Command "pnpm.cmd" -RequiredMajor 11
$CloudflaredPath = (Get-Command "cloudflared.exe" -ErrorAction Stop).Source

$OccupiedPorts = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @(3000, 3001) }
if ($OccupiedPorts) {
    $Owners = ($OccupiedPorts | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "Ports 3000 or 3001 are already in use (process IDs: $Owners). Run 'pnpm dev:staging:down' or stop the exact owning process."
}

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null

Write-Host "Checking the existing Cloudflare Access user session..."
$AccessJwt = (& $CloudflaredPath access token --app $AdminStagingOrigin 2>$null | Out-String).Trim()
if ($AccessJwt -notmatch $AccessJwtPattern) {
    Write-Host "Cloudflare Access authentication is required. Complete the browser prompt for the approved admin identity."
    & $CloudflaredPath access login --quiet --auto-close $AdminStagingOrigin
    if ($LASTEXITCODE -ne 0) {
        throw "Cloudflare Access login did not complete."
    }
    $AccessJwt = (& $CloudflaredPath access token --app $AdminStagingOrigin 2>$null | Out-String).Trim()
}
if ($AccessJwt -notmatch $AccessJwtPattern -or $AccessJwt.Length -gt 8192) {
    throw "A current Cloudflare Access user token was not available."
}

$CommonEnvironment = @{
    "PATH" = $env:PATH
    "NODE_ENV" = "development"
}
$LearnerEnvironment = $CommonEnvironment.Clone()
$LearnerEnvironment["AC_DEV_AUTH_BRIDGE_ENABLED"] = "true"
$LearnerEnvironment["AC_DEV_AUTH_BRIDGE_ORIGIN"] = $LearnerOrigin
$LearnerEnvironment["AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN"] = $LearnerStagingOrigin
$LearnerEnvironment["AC_DEV_API_ORIGIN"] = ""

$AdminEnvironment = $CommonEnvironment.Clone()
$AdminEnvironment["AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED"] = "true"
$AdminEnvironment["AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN"] = $AdminOrigin
$AdminEnvironment["AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN"] = $AdminStagingOrigin
$AdminEnvironment["AC_DEV_ADMIN_ACCESS_JWT"] = $AccessJwt
$AdminEnvironment["AC_DEV_ADMIN_API_ORIGIN"] = "http://127.0.0.1:8000"

$LearnerProcess = $null
$AdminProcess = $null
try {
    $LearnerProcess = Start-Process -FilePath $PnpmPath `
        -ArgumentList @("--filter", "@ac/learner-web", "exec", "next", "dev", "--webpack", "--hostname", "127.0.0.1", "--port", "3000") `
        -WorkingDirectory $RepositoryRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $RuntimeDirectory "learner.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDirectory "learner.err.log") `
        -Environment $LearnerEnvironment `
        -PassThru

    $AdminProcess = Start-Process -FilePath $PnpmPath `
        -ArgumentList @("--filter", "@ac/admin-web", "exec", "next", "dev", "--webpack", "--hostname", "127.0.0.1", "--port", "3001") `
        -WorkingDirectory $RepositoryRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $RuntimeDirectory "admin.out.log") `
        -RedirectStandardError (Join-Path $RuntimeDirectory "admin.err.log") `
        -Environment $AdminEnvironment `
        -PassThru

    $AccessJwt = $null
    $AdminEnvironment.Remove("AC_DEV_ADMIN_ACCESS_JWT")

    $ProcessRecord = @{
        repository = $RepositoryRoot
        created_at = [DateTimeOffset]::UtcNow.ToString("o")
        processes = @(
            @{ name = "learner"; id = $LearnerProcess.Id; started_at_file_time_utc = $LearnerProcess.StartTime.ToFileTimeUtc() },
            @{ name = "admin"; id = $AdminProcess.Id; started_at_file_time_utc = $AdminProcess.StartTime.ToFileTimeUtc() }
        )
    }
    $ProcessRecord | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PidFile -Encoding utf8

    Wait-ForHealth -Name "Learner UI" -Process $LearnerProcess -Probe {
        $Response = Invoke-WebRequest "$LearnerOrigin/v1/programs?limit=1" -TimeoutSec 10
        $Response.StatusCode -eq 200 -and $Response.Headers["X-AC-Dev-Data-Mode"] -contains "staging-public-catalog"
    }
    Wait-ForHealth -Name "Admin bridge" -Process $AdminProcess -Probe {
        $Response = Invoke-RestMethod "$AdminOrigin/v1/dev-bridge/health" -TimeoutSec 10
        $Response.status -eq "ok" -and $Response.transport -eq "connected"
    }
}
catch {
    Stop-StartedProcess -Process $AdminProcess
    Stop-StartedProcess -Process $LearnerProcess
    if (Test-Path -LiteralPath $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
    throw "Local staging bridge startup failed: $($_.Exception.Message) Logs: $RuntimeDirectory"
}

Write-Host "Local staging bridge is healthy."
Write-Host "Learner: $LearnerOrigin/login"
Write-Host "Admin:   $AdminOrigin/login"
Write-Host "Logs:    $RuntimeDirectory"
Write-Host "Stop:    pnpm dev:staging:down"

if (-not $NoBrowser) {
    Start-Process $LearnerOrigin | Out-Null
    Start-Process "$AdminOrigin/login" | Out-Null
}
