[CmdletBinding()]
param([switch]$Stop, [ValidateSet('all', 'both', 'learner', 'admin', 'coach')][string]$SurfaceSelection = 'all', [switch]$StudioVideo)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Local-RuntimeBootstrap.ps1')
if (Invoke-LocalRuntimeRelaunch -ScriptPath $PSCommandPath -Parameters $PSBoundParameters) { return }

# One-tree local development. No staging/production network or credentials.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-LocalTcpListeners.ps1')
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Repository '.tmp/local-platform'
$ProcessFile = Join-Path $Runtime 'ui-processes.json'
$Node = Get-LocalNodeExecutable

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

function Assert-LocalAnonymousApiRoute {
    param([Parameter(Mandatory = $true)][hashtable]$Surface)

    $Handler = [Net.Http.HttpClientHandler]::new()
    $Handler.UseCookies = $false
    $Handler.UseProxy = $false
    $Handler.AllowAutoRedirect = $false
    $Client = [Net.Http.HttpClient]::new($Handler)
    $Client.Timeout = [TimeSpan]::FromSeconds(5)
    $Request = $null
    $Response = $null
    try {
        $Request = [Net.Http.HttpRequestMessage]::new(
            [Net.Http.HttpMethod]::Get,
            "http://127.0.0.1:$($Surface.port)/v1/me"
        )
        $Request.Headers.Host = "$($Surface.name).localhost:$($Surface.port)"
        $Request.Headers.Accept.ParseAdd('application/json')
        $Response = $Client.SendAsync(
            $Request,
            [Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        $Status = [int]$Response.StatusCode
        $CacheControl = $Response.Headers.CacheControl
        if (
            $Status -ne 401 -or
            $null -eq $CacheControl -or
            -not $CacheControl.Private -or
            -not $CacheControl.NoStore -or
            $Response.Headers.Contains('Set-Cookie')
        ) {
            $CacheValue = if ($null -eq $CacheControl) { '<missing>' } else { $CacheControl.ToString() }
            throw "Anonymous /v1/me returned status $Status with cache-control '$CacheValue'."
        }
    }
    catch {
        throw "Anonymous $($Surface.name) /v1/me route is not healthy: $($_.Exception.Message)"
    }
    finally {
        if ($null -ne $Response) { $Response.Dispose() }
        if ($null -ne $Request) { $Request.Dispose() }
        $Client.Dispose()
        $Handler.Dispose()
    }
}

try {
    $Live = @()
    $OwnedSelectedNames = @()
    $SeenNames = @{}
    $SeenProcessIds = @{}
    $PreservedRecords = @()
    $SelectedSurfaces = @(@{ name = 'learner'; port = 3100 }, @{ name = 'admin'; port = 3101 }, @{ name = 'coach'; port = 3102 }) |
        Where-Object { $SurfaceSelection -eq 'all' -or ($SurfaceSelection -eq 'both' -and $_.name -in @('learner', 'admin')) -or $_.name -eq $SurfaceSelection }
    if (Test-Path -LiteralPath $ProcessFile) {
        $Record = Get-Content -LiteralPath $ProcessFile -Raw | ConvertFrom-Json
        if ($Record.repository -ne $Repository) { throw 'UI process record belongs to another tree.' }
        foreach ($Tracked in $Record.processes) {
            # A count alone cannot establish ownership of all three surfaces.
            # Reject ambiguous records before looking up or controlling any PID.
            $ExpectedPort = @{ learner = 3100; admin = 3101; coach = 3102 }[[string]$Tracked.name]
            if (-not $ExpectedPort -or $Tracked.port -ne $ExpectedPort -or [int]$Tracked.id -le 0 -or
                $SeenNames.ContainsKey([string]$Tracked.name) -or $SeenProcessIds.ContainsKey([int]$Tracked.id)) {
                throw 'Local UI process records are ambiguous or invalid. Existing processes are preserved.'
            }
            $SeenNames[[string]$Tracked.name] = $true
            $SeenProcessIds[[int]$Tracked.id] = $true
            $Process = Get-Process -Id $Tracked.id -ErrorAction SilentlyContinue
            if ($Process -and $Process.StartTime.ToFileTimeUtc() -eq $Tracked.started_at) {
                if ($Process.Path -ne $Tracked.executable -or $Process.Path -ne $Node) {
                    throw 'Tracked UI executable changed; refusing process control.'
                }
                if ($Tracked.name -in @($SelectedSurfaces.name)) {
                    $Live += $Process
                    $OwnedSelectedNames += $Tracked.name
                }
                else { $PreservedRecords += $Tracked }
            }
        }
    }
    if ($Stop) {
        foreach ($Process in $Live) { & taskkill.exe /PID $Process.Id /T /F *> $null }
        Write-Host 'Stopped only the selected managed local UI processes. API, database, other surfaces, edits and logs are preserved.'
        return
    }
    if ($Live.Count -eq @($SelectedSurfaces).Count) {
        if (@($SelectedSurfaces | Where-Object { $_.name -notin $OwnedSelectedNames }).Count) {
            throw 'Not every selected app has a verified process owner. Existing processes are preserved.'
        }
        # Starting twice is safe. Reuse only owned processes, and verify that
        # they are actually healthy before reporting the apps as available.
        & (Join-Path $PSScriptRoot 'Start-LocalApi.ps1') -StudioVideo:$StudioVideo
        $Health = Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 3 -NoProxy
        if ($Health.status -ne 'ready') { throw 'The running local API is not ready. Existing processes are preserved.' }
        foreach ($Surface in $SelectedSurfaces) {
            $Response = Invoke-WebRequest "http://127.0.0.1:$($Surface.port)/login" `
                -Headers @{ Host = "$($Surface.name).localhost:$($Surface.port)" } -TimeoutSec 5 -NoProxy
            if ($Response.StatusCode -ne 200) { throw 'A running local app is not ready. Existing processes are preserved.' }
            Assert-LocalAnonymousApiRoute -Surface $Surface
            Write-Host "Local $($Surface.name) already ready: http://$($Surface.name).localhost:$($Surface.port)/login"
        }
        return
    }
    if ($Live.Count) { throw 'Some selected apps are already running. Start only the missing app with -SurfaceSelection, or use -Stop for an explicit restart.' }
    if (Get-LocalTcpListeners |
        Where-Object { $_.LocalPort -in @($SelectedSurfaces.port) }) {
        throw 'A selected local app port is occupied. Stop the tracked old bridge explicitly; unknown processes are not stopped.'
    }
    & (Join-Path $PSScriptRoot 'Start-LocalApi.ps1') -StudioVideo:$StudioVideo
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
    $ChildEnvironment['AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED'] = if ($StudioVideo) { 'true' } else { 'false' }
    $ChildEnvironment['AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN'] = 'http://admin.localhost:3101'
    $ChildEnvironment['NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED'] = 'true'
    $ChildEnvironment['NODE_ENV'] = 'development'
    $ChildEnvironment['NODE_DEBUG'] = ''
    $ChildEnvironment['NODE_OPTIONS'] = ''
    $ChildEnvironment['NEXT_TRACE_SPAN_THRESHOLD_MS'] = '9007199254740991'
    $ChildEnvironment['NEXT_TELEMETRY_DISABLED'] = '1'
    $Started = @()
    $Records = @()
    $ChildEnvironment['PATH'] = (Split-Path -Parent $Node) + [IO.Path]::PathSeparator + $env:PATH
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
            $LastReadinessError = ''
            while ([DateTime]::UtcNow -lt $Deadline) {
                $Process = Get-Process -Id $Surface.id -ErrorAction SilentlyContinue
                if (-not $Process) { throw 'A local UI process exited during startup.' }
                try {
                    $Response = Invoke-WebRequest "http://127.0.0.1:$($Surface.port)/login" `
                        -Headers @{ Host = "$($Surface.name).localhost:$($Surface.port)" } -TimeoutSec 5 -NoProxy
                    if ($Response.StatusCode -eq 200) {
                        try {
                            Assert-LocalAnonymousApiRoute -Surface $Surface
                            $Ready = $true
                            break
                        }
                        catch { $LastReadinessError = $_.Exception.Message }
                    }
                }
                catch { $LastReadinessError = $_.Exception.Message }
                Start-Sleep -Milliseconds 500
            }
            if (-not $Ready) {
                $Detail = if ($LastReadinessError) { " Last readiness error: $LastReadinessError" } else { '' }
                throw "Local UI did not become ready within 60 seconds.$Detail"
            }
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
