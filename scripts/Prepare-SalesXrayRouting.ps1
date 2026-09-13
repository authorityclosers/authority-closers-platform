[CmdletBinding()]
param(
    [string]$AccountId = $env:CLOUDFLARE_ACCOUNT_ID,
    [string]$ZoneId = $env:CLOUDFLARE_ZONE_ID,
    [string]$TunnelId = $env:CLOUDFLARE_TUNNEL_ID,
    [ValidateSet("staging", "production")]
    [string]$TargetEnvironment = "staging",
    [string]$ApiBaseUrl = "https://api.cloudflare.com/client/v4",
    [switch]$Apply,
    [string]$ConfigSnapshotPath,
    [string]$DnsSnapshotPath,
    [string]$ReceiptPath
)

# This source-owned reconciler is deliberately dry-run by default. It only uses
# CLOUDFLARE_API_TOKEN from the process environment and never accepts credentials
# as parameters or prints API responses. -Apply is the explicit mutation gate.

$ErrorActionPreference = "Stop"
$ExpectedTunnelName = "ac-kvm4-prod"
$ExpectedZoneName = "authorityclosers.com"
$ExpectedCaddyOrigin = "http://localhost:8080"
$ExpectedCatchallService = "http_status:404"
$DefaultApiBaseUrl = "https://api.cloudflare.com/client/v4"
$MockApiTokenSentinel = "AC_TEST_CLOUDFLARE_API_TOKEN_SENTINEL"
$TargetHostname = if ($TargetEnvironment -eq "staging") {
    "salesxray-staging.authorityclosers.com"
}
else {
    "salesxray.authorityclosers.com"
}
$SalesXrayHostnames = @($TargetHostname)

function Assert-RequiredValue {
    param(
        [string]$Value,
        [string]$Name
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is required; use the existing non-secret environment reference or an explicit non-secret value."
    }
}

function Invoke-CloudflareApi {
    param(
        [ValidateSet("GET", "POST", "PUT", "PATCH", "DELETE")]
        [string]$Method,
        [string]$Path,
        $Body = $null
    )

    $parameters = @{
        Method = $Method
        Uri = "$script:ApiBaseUrl$Path"
        Headers = @{ Authorization = "Bearer $script:ApiToken" }
        ContentType = "application/json"
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 50 -Compress
    }

    $response = Invoke-RestMethod @parameters
    if (-not $response.success) {
        $errorSummary = @($response.errors | ForEach-Object { $_.message }) -join "; "
        throw "Cloudflare API request failed ($Method $Path): $errorSummary"
    }
    return $response
}

function Assert-ApiBaseUrl {
    param([string]$BaseUrl)

    if ($BaseUrl -ceq $DefaultApiBaseUrl) {
        return
    }
    try {
        $uri = [Uri]$BaseUrl
    }
    catch {
        throw "ApiBaseUrl must be the exact Cloudflare API endpoint."
    }
    $loopbackHost = $uri.Host -eq "127.0.0.1" -or $uri.Host -eq "localhost"
    $loopbackAllowed = (
        $uri.Scheme -eq "http" -and
        $loopbackHost -and
        [string]::IsNullOrEmpty($uri.UserInfo) -and
        [string]::IsNullOrEmpty($uri.Query) -and
        [string]::IsNullOrEmpty($uri.Fragment) -and
        ($uri.AbsolutePath -eq "/") -and
        $script:ApiToken -ceq $MockApiTokenSentinel
    )
    if (-not $loopbackAllowed) {
        throw "ApiBaseUrl must be exactly https://api.cloudflare.com/client/v4; loopback HTTP is reserved for the test sentinel."
    }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not [IO.File]::Exists($Path)) {
        throw "Snapshot file does not exist: $Path"
    }
    try {
        return (Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json)
    }
    catch {
        throw "Snapshot file is not valid JSON: $Path"
    }
}

function Get-PropertyValue {
    param(
        $Object,
        [string]$Name
    )
    if ($null -eq $Object) {
        return $null
    }
    if ($Object -is [System.Collections.IDictionary] -and $Object.Contains($Name)) {
        return $Object[$Name]
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Normalize-Hostname {
    param([string]$Name)
    if ($null -eq $Name) {
        return ""
    }
    return $Name.Trim().TrimEnd('.').ToLowerInvariant()
}

function Normalize-Target {
    param([string]$Target)
    if ($null -eq $Target) {
        return ""
    }
    return $Target.Trim().TrimEnd('.').ToLowerInvariant()
}

function Assert-ExactZoneAndTunnel {
    param(
        $Zone,
        $Tunnel
    )

    $zoneNameValue = [string](Get-PropertyValue -Object $Zone -Name "name")
    $zoneIdValue = [string](Get-PropertyValue -Object $Zone -Name "id")
    $zoneStatus = [string](Get-PropertyValue -Object $Zone -Name "status")
    $zoneAccount = Get-PropertyValue -Object $Zone -Name "account"
    $zoneAccountId = [string](Get-PropertyValue -Object $zoneAccount -Name "id")
    if ($zoneIdValue -ne $ZoneId) {
        throw "Cloudflare zone check failed: the returned zone ID does not match the supplied zone ID."
    }
    if ((Normalize-Hostname $zoneNameValue) -ne (Normalize-Hostname $ExpectedZoneName) -or $zoneStatus -ne "active") {
        throw "Cloudflare zone check failed: the supplied zone is not the active authorityclosers.com zone."
    }
    if ($zoneAccountId -ne $AccountId) {
        throw "Cloudflare zone check failed: the zone account does not match the supplied account."
    }

    $tunnelIdValue = [string](Get-PropertyValue -Object $Tunnel -Name "id")
    $tunnelNameValue = [string](Get-PropertyValue -Object $Tunnel -Name "name")
    $deletedAt = Get-PropertyValue -Object $Tunnel -Name "deleted_at"
    $configSource = [string](Get-PropertyValue -Object $Tunnel -Name "config_src")
    $tunnelStatus = [string](Get-PropertyValue -Object $Tunnel -Name "status")
    if ($tunnelIdValue -ne $TunnelId -or $tunnelNameValue -ne $ExpectedTunnelName -or $null -ne $deletedAt) {
        throw "Cloudflare tunnel check failed: the supplied tunnel ID is not the active $ExpectedTunnelName tunnel."
    }
    if ($configSource -ne "cloudflare") {
        throw "Cloudflare tunnel check failed: the tunnel is not remotely configured."
    }
    if ($tunnelStatus -ne "healthy") {
        throw "Cloudflare tunnel check failed: the tunnel is not healthy."
    }
}

function Get-ConfigurationObject {
    param($Configuration)

    $config = Get-PropertyValue -Object $Configuration -Name "config"
    if ($null -eq $config) {
        $config = Get-PropertyValue -Object $Configuration -Name "ingress"
        if ($null -eq $config) {
            throw "Cloudflare tunnel configuration has no config object."
        }
        return $Configuration
    }
    return $config
}

function Get-ConfigIngress {
    param($Configuration)

    $config = Get-ConfigurationObject -Configuration $Configuration
    $ingress = Get-PropertyValue -Object $config -Name "ingress"
    if ($null -eq $ingress) {
        throw "Cloudflare tunnel configuration has no ingress array."
    }
    return @($ingress)
}

function Get-ConfigurationVersion {
    param($Configuration)
    return Get-PropertyValue -Object $Configuration -Name "version"
}

function Get-ConfigurationFingerprint {
    param($Configuration)

    $config = Get-ConfigurationObject -Configuration $Configuration
    $canonical = Convert-ToCanonicalValue -Value $config
    $serialized = $canonical | ConvertTo-Json -Depth 50 -Compress
    $bytes = [Text.Encoding]::UTF8.GetBytes($serialized)
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hash.Dispose()
    }
}

function Convert-ToCanonicalValue {
    param($Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $canonical = [ordered]@{}
        foreach ($key in @($Value.Keys | ForEach-Object { [string]$_ } | Sort-Object)) {
            $canonical[$key] = Convert-ToCanonicalValue -Value $Value[$key]
        }
        return $canonical
    }
    if ($Value -is [pscustomobject]) {
        $canonical = [ordered]@{}
        foreach ($property in @($Value.PSObject.Properties | Sort-Object -Property Name)) {
            $canonical[$property.Name] = Convert-ToCanonicalValue -Value $property.Value
        }
        return $canonical
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        $canonical = @()
        foreach ($item in $Value) {
            $canonical += ,(Convert-ToCanonicalValue -Value $item)
        }
        return ,$canonical
    }
    return $Value
}

function New-ConfigurationWithIngress {
    param(
        $Configuration,
        [object[]]$Ingress
    )

    $current = Get-ConfigurationObject -Configuration $Configuration
    $desired = [ordered]@{}
    foreach ($property in $current.PSObject.Properties) {
        $desired[$property.Name] = $property.Value
    }
    $desired["ingress"] = @($Ingress)
    return $desired
}

function New-IngressPlan {
    param(
        [object[]]$Ingress,
        [string[]]$Hostnames
    )

    $entries = @($Ingress)
    $catchallIndexes = @()
    for ($index = 0; $index -lt $entries.Count; $index++) {
        $entry = $entries[$index]
        $hostname = [string](Get-PropertyValue -Object $entry -Name "hostname")
        $service = [string](Get-PropertyValue -Object $entry -Name "service")
        if ([string]::IsNullOrWhiteSpace($hostname) -and $service -eq $ExpectedCatchallService) {
            $catchallIndexes += $index
        }
    }
    if ($catchallIndexes.Count -ne 1 -or $catchallIndexes[0] -ne ($entries.Count - 1)) {
        throw "Cloudflare tunnel ingress must contain exactly one final http_status:404 catchall."
    }
    $catchallIndex = [int]$catchallIndexes[0]

    $missing = @()
    $unchanged = @()
    foreach ($hostname in $Hostnames) {
        $normalized = Normalize-Hostname $hostname
        $matches = @($entries | Where-Object {
            (Normalize-Hostname ([string](Get-PropertyValue -Object $_ -Name "hostname"))) -eq $normalized
        })
        if ($matches.Count -gt 1) {
            throw "Cloudflare tunnel ingress conflict: more than one route exists for $hostname."
        }
        if ($matches.Count -eq 1) {
            $service = [string](Get-PropertyValue -Object $matches[0] -Name "service")
            if ($service -ne $ExpectedCaddyOrigin) {
                throw "Cloudflare tunnel ingress conflict: $hostname does not use the reviewed Caddy origin."
            }
            $unchanged += $hostname
        }
        else {
            $missing += $hostname
        }
    }

    # Build a new array without touching any existing object. New routes are
    # inserted in stable staging/production order immediately before catchall.
    $desired = @()
    for ($index = 0; $index -lt $entries.Count; $index++) {
        if ($index -eq $catchallIndex) {
            foreach ($hostname in $missing) {
                $desired += [ordered]@{
                    hostname = $hostname
                    service = $ExpectedCaddyOrigin
                }
            }
        }
        $desired += $entries[$index]
    }

    $preservedExistingCount = 0
    foreach ($entry in $entries) {
        foreach ($candidate in $desired) {
            if ([object]::ReferenceEquals($entry, $candidate)) {
                $preservedExistingCount++
                break
            }
        }
    }
    if ($preservedExistingCount -ne $entries.Count) {
        throw "Cloudflare tunnel ingress plan failed to preserve an existing entry."
    }

    [ordered]@{
        existing_count = $entries.Count
        desired_count = $desired.Count
        preserved_existing_count = $preservedExistingCount
        catchall_index = $catchallIndex
        missing_hosts = @($missing)
        unchanged_hosts = @($unchanged)
        desired_ingress = @($desired)
    }
}

function Get-DnsRecordsFromSnapshot {
    param(
        $Snapshot,
        [string]$Hostname
    )

    $property = $Snapshot.PSObject.Properties[$Hostname]
    if ($null -eq $property) {
        throw "DNS snapshot is missing an exact entry for $Hostname."
    }
    return @($property.Value)
}

function Assert-DnsRecordShape {
    param(
        [object[]]$Records,
        [string]$Hostname,
        [string]$Target,
        [switch]$AllowMissing
    )

    $matches = @($Records)
    if ($matches.Count -eq 0 -and $AllowMissing) {
        return "create"
    }
    if ($matches.Count -ne 1) {
        throw "DNS conflict: expected exactly one record or no record at $Hostname; found $($matches.Count)."
    }

    $record = $matches[0]
    $recordType = [string](Get-PropertyValue -Object $record -Name "type")
    $recordName = [string](Get-PropertyValue -Object $record -Name "name")
    $content = [string](Get-PropertyValue -Object $record -Name "content")
    $proxied = Get-PropertyValue -Object $record -Name "proxied"
    $ttl = Get-PropertyValue -Object $record -Name "ttl"
    if (
        $recordType -ne "CNAME" -or
        (Normalize-Hostname $recordName) -ne (Normalize-Hostname $Hostname) -or
        (Normalize-Target $content) -ne (Normalize-Target $Target) -or
        $proxied -ne $true -or
        [int]$ttl -ne 1
    ) {
        throw "DNS conflict: the existing record at $Hostname is not the reviewed proxied CNAME target."
    }
    return "unchanged"
}

function Get-DnsBody {
    param(
        [string]$Hostname,
        [string]$Target
    )
    return [ordered]@{
        type = "CNAME"
        name = $Hostname
        content = $Target
        proxied = $true
        ttl = 1
        comment = "Authority Closers Sales Xray via existing Cloudflare Tunnel"
    }
}

function Assert-FinalConfiguration {
    param(
        $Configuration,
        $ExpectedConfiguration,
        [string[]]$Hostnames
    )
    $actualFingerprint = Get-ConfigurationFingerprint -Configuration $Configuration
    $expectedFingerprint = Get-ConfigurationFingerprint -Configuration $ExpectedConfiguration
    if ($actualFingerprint -ne $expectedFingerprint) {
        throw "Tunnel configuration readback did not preserve the complete planned configuration."
    }
    $plan = New-IngressPlan -Ingress (Get-ConfigIngress -Configuration $Configuration) -Hostnames $Hostnames
    if (@($plan.missing_hosts).Count -ne 0) {
        throw "Tunnel configuration readback did not contain the selected Sales Xray route."
    }
    return $plan
}

function Assert-FinalDns {
    param(
        [object[]]$Records,
        [string]$Hostname,
        [string]$Target
    )
    $null = Assert-DnsRecordShape -Records $Records -Hostname $Hostname -Target $Target
}

$offline = (-not [string]::IsNullOrWhiteSpace($ConfigSnapshotPath)) -or
    (-not [string]::IsNullOrWhiteSpace($DnsSnapshotPath))
if ((-not [string]::IsNullOrWhiteSpace($ConfigSnapshotPath)) -xor
    (-not [string]::IsNullOrWhiteSpace($DnsSnapshotPath))) {
    throw "ConfigSnapshotPath and DnsSnapshotPath must be supplied together."
}
if ($offline -and $Apply) {
    throw "-Apply cannot be used with offline snapshots."
}

Assert-RequiredValue -Value $AccountId -Name "AccountId"
Assert-RequiredValue -Value $ZoneId -Name "ZoneId"
Assert-RequiredValue -Value $TunnelId -Name "TunnelId"

if (-not $offline) {
    $script:ApiToken = $env:CLOUDFLARE_API_TOKEN
    Assert-RequiredValue -Value $script:ApiToken -Name "CLOUDFLARE_API_TOKEN"
    Assert-ApiBaseUrl -BaseUrl $ApiBaseUrl
    $zoneResponse = Invoke-CloudflareApi -Method GET -Path "/zones/$ZoneId"
    $zone = $zoneResponse.result
    $tunnelResponse = Invoke-CloudflareApi -Method GET -Path "/accounts/$AccountId/cfd_tunnel/$TunnelId"
    $tunnel = $tunnelResponse.result
    $configurationResponse = Invoke-CloudflareApi -Method GET -Path "/accounts/$AccountId/cfd_tunnel/$TunnelId/configurations"
    $configuration = $configurationResponse.result
    $dnsRecordsByHost = @{}
    foreach ($hostname in $SalesXrayHostnames) {
        $encodedHostname = [uri]::EscapeDataString($hostname)
        $recordsResponse = Invoke-CloudflareApi -Method GET -Path "/zones/$ZoneId/dns_records?name=$encodedHostname"
        $dnsRecordsByHost[$hostname] = @($recordsResponse.result)
    }
}
else {
    $configSnapshot = Read-JsonFile -Path $ConfigSnapshotPath
    $dnsSnapshot = Read-JsonFile -Path $DnsSnapshotPath
    $zone = Get-PropertyValue -Object $configSnapshot -Name "zone"
    $tunnel = Get-PropertyValue -Object $configSnapshot -Name "tunnel"
    $configuration = Get-PropertyValue -Object $configSnapshot -Name "configuration"
    if ($null -eq $configuration) {
        $configuration = $configSnapshot
    }
    $dnsRecordsByHost = @{}
    foreach ($hostname in $SalesXrayHostnames) {
        $dnsRecordsByHost[$hostname] = @(Get-DnsRecordsFromSnapshot -Snapshot $dnsSnapshot -Hostname $hostname)
    }
}

Assert-ExactZoneAndTunnel -Zone $zone -Tunnel $tunnel
$currentIngress = Get-ConfigIngress -Configuration $configuration
$ingressPlan = New-IngressPlan -Ingress $currentIngress -Hostnames $SalesXrayHostnames
$initialConfigFingerprint = Get-ConfigurationFingerprint -Configuration $configuration
$initialConfigVersion = Get-ConfigurationVersion -Configuration $configuration
$target = "$TunnelId.cfargotunnel.com"
$dnsPlan = @()
foreach ($hostname in $SalesXrayHostnames) {
    $action = Assert-DnsRecordShape -Records $dnsRecordsByHost[$hostname] -Hostname $hostname -Target $target -AllowMissing
    $dnsPlan += [ordered]@{
        hostname = $hostname
        action = $action
    }
}

$configChanged = $false
$dnsChanged = $false
$readbackVerified = $false
if ($Apply) {
    if (@($ingressPlan.missing_hosts).Count -gt 0) {
        # Re-read immediately before the PUT and refuse a stale plan. The
        # fingerprint covers complete config fields; version catches a server
        # update even when an API response has an equivalent serialized config.
        $preWriteResponse = Invoke-CloudflareApi -Method GET -Path "/accounts/$AccountId/cfd_tunnel/$TunnelId/configurations"
        $preWriteConfiguration = $preWriteResponse.result
        $preWriteFingerprint = Get-ConfigurationFingerprint -Configuration $preWriteConfiguration
        $preWriteVersion = Get-ConfigurationVersion -Configuration $preWriteConfiguration
        $versionChanged = $false
        if ($null -ne $initialConfigVersion -or $null -ne $preWriteVersion) {
            $versionChanged = [string]$initialConfigVersion -ne [string]$preWriteVersion
        }
        if ($versionChanged -or $initialConfigFingerprint -ne $preWriteFingerprint) {
            throw "Tunnel configuration changed before write; refusing PUT."
        }

        $preWriteIngress = Get-ConfigIngress -Configuration $preWriteConfiguration
        $preWritePlan = New-IngressPlan -Ingress $preWriteIngress -Hostnames $SalesXrayHostnames
        $desiredConfiguration = New-ConfigurationWithIngress `
            -Configuration $preWriteConfiguration -Ingress $preWritePlan.desired_ingress
        $body = @{ config = $desiredConfiguration }
        $null = Invoke-CloudflareApi -Method PUT -Path "/accounts/$AccountId/cfd_tunnel/$TunnelId/configurations" -Body $body
        $configChanged = $true

        # Configuration readback is intentionally before any DNS POST. If the
        # API drops an unknown property or entry, do not publish its hostname.
        $configurationReadback = Invoke-CloudflareApi -Method GET -Path "/accounts/$AccountId/cfd_tunnel/$TunnelId/configurations"
        $null = Assert-FinalConfiguration `
            -Configuration $configurationReadback.result `
            -ExpectedConfiguration $desiredConfiguration `
            -Hostnames $SalesXrayHostnames
    }

    foreach ($entry in @($dnsPlan)) {
        if ($entry.action -ne "create") {
            continue
        }
        $hostname = [string]$entry.hostname
        $null = Invoke-CloudflareApi -Method POST -Path "/zones/$ZoneId/dns_records" -Body (Get-DnsBody -Hostname $hostname -Target $target)
        $dnsChanged = $true
        $encodedHostname = [uri]::EscapeDataString($hostname)
        $finalRecordsResponse = Invoke-CloudflareApi -Method GET -Path "/zones/$ZoneId/dns_records?name=$encodedHostname"
        Assert-FinalDns -Records @($finalRecordsResponse.result) -Hostname $hostname -Target $target
    }
    $readbackVerified = $true
}

$result = [ordered]@{
    schema = "ac.sales-xray-routing-reconcile/1"
    mode = if ($Apply) { "apply" } else { "dry-run" }
    target_environment = $TargetEnvironment
    zone = $ExpectedZoneName
    tunnel_name = $ExpectedTunnelName
    tunnel_id_redacted = if ($TunnelId.Length -gt 12) {
        "$($TunnelId.Substring(0, 8))...$($TunnelId.Substring($TunnelId.Length - 5))"
    }
    else { "redacted" }
    tunnel_status = [string](Get-PropertyValue -Object $tunnel -Name "status")
    target = $target
    hostnames = @($SalesXrayHostnames)
    ingress = [ordered]@{
        existing_count = $ingressPlan.existing_count
        desired_count = $ingressPlan.desired_count
        preserved_existing_count = $ingressPlan.preserved_existing_count
        missing_hosts = @($ingressPlan.missing_hosts)
        unchanged_hosts = @($ingressPlan.unchanged_hosts)
        catchall_index = $ingressPlan.catchall_index
        desired_host_order = @($ingressPlan.desired_ingress | ForEach-Object {
            [string](Get-PropertyValue -Object $_ -Name "hostname")
        })
    }
    dns = @($dnsPlan)
    config_changed = $configChanged
    dns_changed = $dnsChanged
    readback_verified = $readbackVerified
    records_changed = ($configChanged -or $dnsChanged)
}
$json = $result | ConvertTo-Json -Depth 20 -Compress
if (-not [string]::IsNullOrWhiteSpace($ReceiptPath)) {
    $receiptParent = Split-Path -Parent $ReceiptPath
    if (-not [string]::IsNullOrWhiteSpace($receiptParent)) {
        New-Item -ItemType Directory -Path $receiptParent -Force | Out-Null
    }
    Set-Content -LiteralPath $ReceiptPath -Value $json -Encoding UTF8
}
Write-Output $json
