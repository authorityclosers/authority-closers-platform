[CmdletBinding()]
param(
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

function Get-TrackedProcess {
    param([Parameter(Mandatory)] [object]$Tracked)

    $Process = Get-Process -Id ([int]$Tracked.id) -ErrorAction SilentlyContinue
    if ($null -eq $Process) { return $null }
    $ExpectedStart = [long]$Tracked.started_at_file_time_utc
    $ActualStart = $Process.StartTime.ToFileTimeUtc()
    if ([Math]::Abs($ActualStart - $ExpectedStart) -gt [TimeSpan]::TicksPerSecond) { return $null }
    return $Process
}

function Get-HttpJson {
    param([Parameter(Mandatory)] [string]$Url)
    $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 10
    return [pscustomobject]@{
        status = [int]$Response.StatusCode
        body = ($Response.Content | ConvertFrom-Json)
    }
}

try {
    if (-not (Test-Path -LiteralPath $PidFile -PathType Leaf)) {
        throw "No tracked local Sales Xray bridge is running. Start it with dev:sales-xray:production."
    }
    $Record = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    if ($Record.repository -ne $RepositoryRoot) {
        throw "The tracked process file belongs to a different workspace."
    }
    $Tracked = @($Record.processes)
    if ($Tracked.Count -ne 2) { throw "The local Sales Xray pair is incomplete in the process tracker." }
    foreach ($Name in @("sales-xray", "bridge")) {
        $Entry = $Tracked | Where-Object { $_.name -eq $Name } | Select-Object -First 1
        if ($null -eq $Entry -or $null -eq (Get-TrackedProcess $Entry)) {
            throw "The tracked $Name process is not running with the expected start time."
        }
    }

    $Inner = Get-HttpJson "$InnerOrigin/health"
    if ($Inner.status -ne 200 -or $Inner.body.status -ne "ok") {
        throw "The Next Sales Xray UI health endpoint is not healthy."
    }
    $Bridge = Get-HttpJson "$BrowserOrigin/health"
    if (
        $Bridge.status -ne 200 -or
        $Bridge.body.status -ne "ok" -or
        $Bridge.body.mode -ne "development-only" -or
        $Bridge.body.data_mode -ne "production-live" -or
        $Bridge.body.upstream_origin -ne $ProductionOrigin
    ) {
        throw "The local production bridge health contract is not healthy."
    }
    $Page = Invoke-WebRequest -UseBasicParsing -Uri "$BrowserOrigin/" -TimeoutSec 10
    if ($Page.StatusCode -ne 200 -or [string]::IsNullOrWhiteSpace($Page.Content)) {
        throw "The browser-facing Sales Xray page is not responding."
    }
    Write-Host "Local Sales Xray frontend + production bridge are healthy." -ForegroundColor Green
    Write-Host "UI:       $BrowserOrigin"
    Write-Host "Next:     $InnerOrigin"
    Write-Host "Data:     $ProductionOrigin"
    exit 0
}
catch {
    Write-Error "Local Sales Xray pair health check failed: $($_.Exception.Message)"
    exit 1
}
