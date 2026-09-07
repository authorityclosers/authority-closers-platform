[CmdletBinding()]
param([ValidateRange(1024, 65535)][int]$LearnerPort = 3100)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProbeRepository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProbeOrigin = "http://learner.localhost:$LearnerPort"
$ProbeMarker = "synthetic-local-media-privacy-" + [Guid]::NewGuid().ToString("N")
$ProbeFiles = @(
    (Join-Path $ProbeRepository "apps/learner-web/.next/dev/trace"),
    (Join-Path $ProbeRepository "apps/learner-web/.next/trace"),
    (Join-Path $ProbeRepository "apps/learner-web/.next/dev/trace-build")
) + @(Get-ChildItem -LiteralPath (Join-Path $ProbeRepository ".tmp/local-staging-bridge") -File -Filter "learner*.log" | Select-Object -ExpandProperty FullName)

function Get-SyntheticProbeCounts {
    $MarkerCount = 0
    $InspectedFiles = 0
    $DiagnosticBytes = 0
    foreach ($ProbeFile in $ProbeFiles) {
        if (-not (Test-Path -LiteralPath $ProbeFile -PathType Leaf)) { continue }
        # Share read/write with the managed server's active stdout/stderr handles.
        # Never copy or emit the contents of a diagnostic file.
        $ProbeStream = [IO.File]::Open($ProbeFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        $ProbeReader = [IO.StreamReader]::new($ProbeStream)
        try {
            $ProbeText = $ProbeReader.ReadToEnd()
            $MarkerCount += ([regex]::Matches($ProbeText, [regex]::Escape($ProbeMarker))).Count
            $DiagnosticBytes += $ProbeStream.Length
            $InspectedFiles++
        }
        finally { $ProbeReader.Dispose(); $ProbeStream.Dispose() }
    }
    return @{ marker_count = $MarkerCount; inspected_files = $InspectedFiles; diagnostic_bytes = $DiagnosticBytes }
}

$Before = Get-SyntheticProbeCounts
$ProbeHandler = [Net.Http.HttpClientHandler]::new()
$ProbeHandler.UseCookies = $false
$ProbeHandler.AllowAutoRedirect = $false
$ProbeClient = [Net.Http.HttpClient]::new($ProbeHandler)
$ProbeClient.Timeout = [TimeSpan]::FromSeconds(30)
try {
    # Deliberately invalid synthetic token, never a real signed media source.
    # Even this marker occurs only in the POST body, never a localhost URL.
    $SyntheticSource = "https://staging.authorityclosers.com/v1/media/playback/tenants%2Ffixture%2Fmedia%2Fvideo%2Fasset%2Fversion%2Foriginal?token=AC-MEDIA." + $ProbeMarker + "." + ("s" * 43)
    $ProbePost = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Post, "$ProbeOrigin/v1/dev-bridge/media")
    $ProbePost.Headers.Add("Origin", $ProbeOrigin)
    $ProbePost.Content = [Net.Http.StringContent]::new((@{ sources = @($SyntheticSource) } | ConvertTo-Json -Compress), [Text.Encoding]::UTF8, "application/json")
    $ProbeResponse = $ProbeClient.SendAsync($ProbePost).GetAwaiter().GetResult()
    $PostStatus = [int]$ProbeResponse.StatusCode
    $PostNoStore = $ProbeResponse.Headers.CacheControl.NoStore
    $ProbeResponse.Dispose()
    $ProbePost.Dispose()

    $ByteStatuses = @()
    foreach ($ProbeMethod in @("GET", "HEAD")) {
        $ByteRequest = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::new($ProbeMethod), "$ProbeOrigin/v1/dev-bridge/media/" + ("m" * 43))
        $ByteRequest.Headers.Add("Origin", $ProbeOrigin)
        $ByteRequest.Headers.Add("Range", "bytes=0-31")
        $ByteResponse = $ProbeClient.SendAsync($ByteRequest).GetAwaiter().GetResult()
        $ByteStatuses += [int]$ByteResponse.StatusCode
        $ByteResponse.Dispose()
        $ByteRequest.Dispose()
    }

    # More than 100 request/child spans if the old reporter were recording them.
    $Batch401 = 0
    for ($ProbeIndex = 0; $ProbeIndex -lt 55; $ProbeIndex++) {
        $BatchResponse = $ProbeClient.GetAsync("$ProbeOrigin/v1/me").GetAwaiter().GetResult()
        if ([int]$BatchResponse.StatusCode -eq 401) { $Batch401++ }
        $BatchResponse.Dispose()
    }
    $After = Get-SyntheticProbeCounts
    $Passed = $PostStatus -eq 401 -and $PostNoStore -and $ByteStatuses.Count -eq 2 -and @($ByteStatuses | Where-Object { $_ -ne 401 }).Count -eq 0 -and $Batch401 -eq 55 -and $Before.marker_count -eq 0 -and $After.marker_count -eq 0 -and $After.inspected_files -gt 0
    [pscustomobject]@{ fixture_only = $true; cookies_sent = $false; post_status = $PostStatus; post_no_store = $PostNoStore; get_head_statuses = $ByteStatuses; batch_401 = $Batch401; before = $Before; after = $After; passed = $Passed } | ConvertTo-Json -Depth 4
    if (-not $Passed) { throw "Synthetic local media privacy acceptance failed; no diagnostic contents were emitted." }
}
finally { $ProbeClient.Dispose(); $ProbeHandler.Dispose() }
