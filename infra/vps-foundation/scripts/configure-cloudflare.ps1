param(
    [string]$AccountId = $env:CLOUDFLARE_ACCOUNT_ID,
    [string]$ZoneId = $env:CLOUDFLARE_ZONE_ID,
    [string]$TunnelName = "ac-kvm4-prod",
    [string]$Hostname = "infra.dipakvishwakarma.com",
    [string]$Origin = "http://localhost:8080"
)

$ErrorActionPreference = "Stop"
$apiToken = $env:CLOUDFLARE_API_TOKEN
if ([string]::IsNullOrWhiteSpace($apiToken)) {
    throw "Set CLOUDFLARE_API_TOKEN in the process environment; credentials are not accepted as command-line parameters."
}
if ([string]::IsNullOrWhiteSpace($AccountId) -or [string]::IsNullOrWhiteSpace($ZoneId)) {
    throw "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_ZONE_ID or pass the non-secret IDs explicitly."
}
$headers = @{ Authorization = "Bearer $apiToken" }
$api = "https://api.cloudflare.com/client/v4"

function Invoke-CloudflareApi {
    param([string]$Method, [string]$Path, $Body = $null)
    $parameters = @{
        Method = $Method
        Uri = "$api$Path"
        Headers = $headers
        ContentType = "application/json"
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    $response = Invoke-RestMethod @parameters
    if (-not $response.success) {
        throw "Cloudflare API request failed: $($response.errors | ConvertTo-Json -Compress)"
    }
    return $response
}

$encodedName = [uri]::EscapeDataString($TunnelName)
$existing = Invoke-CloudflareApi -Method GET -Path "/accounts/$AccountId/cfd_tunnel?is_deleted=false&name=$encodedName"
$matches = @($existing.result | Where-Object { $_.name -eq $TunnelName -and -not $_.deleted_at })
if ($matches.Count -gt 1) {
    throw "More than one active Cloudflare tunnel is named $TunnelName"
}

if ($matches.Count -eq 1) {
    $tunnel = $matches[0]
    $created = $false
} else {
    $createdResponse = Invoke-CloudflareApi -Method POST -Path "/accounts/$AccountId/cfd_tunnel" -Body @{
        name = $TunnelName
        config_src = "cloudflare"
    }
    $tunnel = $createdResponse.result
    $created = $true
}

$null = Invoke-CloudflareApi -Method PUT -Path "/accounts/$AccountId/cfd_tunnel/$($tunnel.id)/configurations" -Body @{
    config = @{
        ingress = @(
            @{
                hostname = $Hostname
                service = $Origin
                originRequest = @{
                    connectTimeout = 10
                    tcpKeepAlive = 30
                }
            },
            @{ service = "http_status:404" }
        )
    }
}

$encodedHostname = [uri]::EscapeDataString($Hostname)
$records = Invoke-CloudflareApi -Method GET -Path "/zones/$ZoneId/dns_records?name=$encodedHostname"
$recordMatches = @($records.result)
$dnsBody = @{
    type = "CNAME"
    name = $Hostname
    content = "$($tunnel.id).cfargotunnel.com"
    proxied = $true
    ttl = 1
    comment = "Authority Closers foundation health endpoint via Cloudflare Tunnel"
}

if ($recordMatches.Count -gt 1) {
    throw "More than one DNS record exists for $Hostname"
} elseif ($recordMatches.Count -eq 1) {
    if ($recordMatches[0].type -ne "CNAME") {
        throw "Existing DNS record for $Hostname is not a CNAME"
    }
    $dnsResponse = Invoke-CloudflareApi -Method PUT -Path "/zones/$ZoneId/dns_records/$($recordMatches[0].id)" -Body $dnsBody
} else {
    $dnsResponse = Invoke-CloudflareApi -Method POST -Path "/zones/$ZoneId/dns_records" -Body $dnsBody
}

[ordered]@{
    tunnel_id = $tunnel.id
    tunnel_name = $tunnel.name
    tunnel_created = $created
    hostname = $Hostname
    dns_record_id = $dnsResponse.result.id
    target = $dnsResponse.result.content
    proxied = $dnsResponse.result.proxied
} | ConvertTo-Json -Compress
