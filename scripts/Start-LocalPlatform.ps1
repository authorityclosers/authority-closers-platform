[CmdletBinding()]
param([switch]$Stop, [ValidateSet('all', 'both', 'learner', 'admin', 'coach')][string]$SurfaceSelection = 'all')

# One-tree local development. No staging/production network or credentials.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Repository '.tmp/local-platform'
$ProcessFile = Join-Path $Runtime 'ui-processes.json'
$Node = (Get-Command node.exe -ErrorAction Stop).Source
if ((& $Node --version) -notmatch '^v24\.') { throw 'Node 24 must be first on PATH.' }
if ($PSVersionTable.PSVersion -lt [version]'7.4') { throw 'PowerShell 7.4 or later is required.' }

foreach ($ManagedPath in @($Runtime, $ProcessFile, (Join-Path $Runtime 'ui-startup.lock'),
        (Join-Path $Runtime 'learner.stdout.log'), (Join-Path $Runtime 'learner.stderr.log'),
        (Join-Path $Runtime 'admin.stdout.log'), (Join-Path $Runtime 'admin.stderr.log'),
        (Join-Path $Runtime 'coach.stdout.log'), (Join-Path $Runtime 'coach.stderr.log'))) {
    $Ancestor = [IO.Path]::GetFullPath($ManagedPath)
    while ($Ancestor) {
        if ((Test-Path -LiteralPath $Ancestor) -and
            ((Get-Item -LiteralPath $Ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Local UI state must not pass through a reparse point.'
        }
        $Ancestor = [IO.Path]::GetDirectoryName($Ancestor)
    }
}
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$Lock = [IO.File]::Open((Join-Path $Runtime 'ui-startup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $Live = @()
    $PreservedRecords = @()
    $SelectedSurfaces = @(@{ name = 'learner'; port = 3100 }, @{ name = 'admin'; port = 3101 }, @{ name = 'coach'; port = 3102 }) |
        Where-Object { $SurfaceSelection -eq 'all' -or ($SurfaceSelection -eq 'both' -and $_.name -in @('learner', 'admin')) -or $_.name -eq $SurfaceSelection }
    if (Test-Path -LiteralPath $ProcessFile) {
        $Record = Get-Content -LiteralPath $ProcessFile -Raw | ConvertFrom-Json
        if ($Record.repository -ne $Repository) { throw 'UI process record belongs to another tree.' }
        foreach ($Tracked in $Record.processes) {
            $Process = Get-Process -Id $Tracked.id -ErrorAction SilentlyContinue
            if ($Process -and $Process.StartTime.ToFileTimeUtc() -eq $Tracked.started_at) {
                if ($Process.Path -ne $Tracked.executable -or $Process.Path -ne $Node) {
                    throw 'Tracked UI executable changed; refusing process control.'
                }
                if ($Tracked.name -in @($SelectedSurfaces.name)) { $Live += $Process }
                else { $PreservedRecords += $Tracked }
            }
        }
    }
    if ($Stop) {
        foreach ($Process in $Live) { & taskkill.exe /PID $Process.Id /T /F *> $null }
        Write-Host 'Stopped only the selected managed local UI processes. API, database, other surfaces, edits and logs are preserved.'
        return
    }
    if ($Live.Count) { throw 'Local UI is already running. Use -Stop before restarting it.' }
    if (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in @($SelectedSurfaces.port) }) {
        throw 'A selected local app port is occupied. Stop the tracked old bridge explicitly; unknown processes are not stopped.'
    }
    & (Join-Path $PSScriptRoot 'Start-LocalApi.ps1')
    $Health = Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 3 -NoProxy
    if ($Health.status -ne 'ready') { throw 'Local API readiness failed.' }

    $ChildEnvironment = @{}
    foreach ($Entry in Get-ChildItem Env: | Where-Object {
        $_.Name -like 'AC_*' -or $_.Name -like 'PG*' -or $_.Name -like 'NEXT_PUBLIC_AC_*'
    }) { $ChildEnvironment[$Entry.Name] = $null }
    # These flags override inherited environments and optional .env files.
    $ChildEnvironment['AC_DEV_AUTH_BRIDGE_ENABLED'] = 'false'
    $ChildEnvironment['AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED'] = 'false'
    $ChildEnvironment['AC_DEV_ADMIN_ACCESS_JWT'] = ''
    $ChildEnvironment['AC_DEV_API_ORIGIN'] = 'http://127.0.0.1:8000'
    $ChildEnvironment['AC_DEV_ADMIN_API_ORIGIN'] = 'http://127.0.0.1:8000'
    $ChildEnvironment['AC_API_URL'] = 'http://127.0.0.1:8000'
    $ChildEnvironment['AC_ADMIN_API_URL'] = 'http://127.0.0.1:8000'
    $ChildEnvironment['AC_DEV_LOCAL_SANDBOX_ENABLED'] = 'true'
    $ChildEnvironment['AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN'] = 'http://admin.localhost:3101'
    $ChildEnvironment['NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED'] = 'true'
    $ChildEnvironment['NODE_ENV'] = 'development'
    $ChildEnvironment['NODE_DEBUG'] = ''
    $ChildEnvironment['NODE_OPTIONS'] = ''
    $ChildEnvironment['NEXT_TRACE_SPAN_THRESHOLD_MS'] = '9007199254740991'
    $ChildEnvironment['NEXT_TELEMETRY_DISABLED'] = '1'
    $Started = @()
    $Records = @()
    try {
        foreach ($Surface in $SelectedSurfaces) {
            $ChildEnvironment['AC_DEV_OPERATIONS_SURFACE'] = $Surface.name
            $ChildEnvironment['AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN'] = if ($Surface.name -eq 'coach') { 'http://coach.localhost:3102' } else { 'http://admin.localhost:3101' }
            $ChildEnvironment['AC_COACH_APP_URL'] = 'http://coach.localhost:3102'
            $App = Join-Path $Repository "apps/$($Surface.name)-web"
            $Next = Join-Path $App 'node_modules/next/dist/bin/next'
            if (-not (Test-Path -LiteralPath $Next)) { throw 'Install workspace dependencies before starting the UI.' }
            $Process = Start-Process -FilePath $Node `
                -ArgumentList @("`"$Next`"", 'dev', '--webpack', '--hostname', '127.0.0.1', '--port', "$($Surface.port)") `
                -WorkingDirectory $App -Environment $ChildEnvironment -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $Runtime "$($Surface.name).stdout.log") `
                -RedirectStandardError (Join-Path $Runtime "$($Surface.name).stderr.log")
            $Started += $Process
            $Records += @{
                name = $Surface.name; port = $Surface.port; id = $Process.Id
                started_at = $Process.StartTime.ToFileTimeUtc(); executable = $Node
            }
        }
        @{ repository = $Repository; processes = @($PreservedRecords) + @($Records) } |
            ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ProcessFile
        foreach ($Surface in $Records) {
            $Deadline = [DateTime]::UtcNow.AddSeconds(60)
            $Ready = $false
            while ([DateTime]::UtcNow -lt $Deadline) {
                $Process = Get-Process -Id $Surface.id -ErrorAction SilentlyContinue
                if (-not $Process) { throw 'A local UI process exited during startup.' }
                try {
                    $Response = Invoke-WebRequest "http://127.0.0.1:$($Surface.port)/login" `
                        -Headers @{ Host = "$($Surface.name).localhost:$($Surface.port)" } -TimeoutSec 5 -NoProxy
                    if ($Response.StatusCode -eq 200) { $Ready = $true; break }
                }
                catch { Start-Sleep -Milliseconds 500 }
            }
            if (-not $Ready) { throw 'Local UI did not become ready within 60 seconds.' }
        }
    }
    catch {
        foreach ($Process in $Started) {
            $Process.Refresh()
            if (-not $Process.HasExited) { & taskkill.exe /PID $Process.Id /T /F *> $null }
        }
        throw 'Local UI startup failed. Only newly started UI processes were stopped; inspect local-platform logs.'
    }
    Write-Host 'Local learner: http://learner.localhost:3100/login'
    Write-Host 'Local Admin:   http://admin.localhost:3101/login'
    Write-Host 'Local Coach:   http://coach.localhost:3102/login'
    Write-Host 'Managed apps use the isolated local API/database. Staging and production are untouched.'
}
finally { $Lock.Dispose() }
