param(
    [string]$ZoneId = $env:CLOUDFLARE_ZONE_ID,
    [string]$ZoneName = "authorityclosers.com",
    [string]$DomainName = "authorityclosers.com"
)

$ErrorActionPreference = "Stop"
$resendApiKey = $env:RESEND_API_KEY
$cloudflareApiToken = $env:CLOUDFLARE_API_TOKEN
if ([string]::IsNullOrWhiteSpace($resendApiKey) -or [string]::IsNullOrWhiteSpace($cloudflareApiToken)) {
    throw "Set RESEND_API_KEY and CLOUDFLARE_API_TOKEN in the process environment; credentials are not accepted as command-line parameters."
}
if ([string]::IsNullOrWhiteSpace($ZoneId)) {
    throw "Set CLOUDFLARE_ZONE_ID or pass the non-secret zone ID explicitly."
}
if ($ZoneName -ne "authorityclosers.com" -or $DomainName -ne "authorityclosers.com") {
    throw "This AC release may configure only the reviewed authorityclosers.com Resend sending domain."
}
$resendHeaders = @{ Authorization = "Bearer $resendApiKey" }
$cloudflareHeaders = @{ Authorization = "Bearer $cloudflareApiToken" }

function Invoke-ResendApi {
    param([string]$Method, [string]$Path, $Body = $null)
    $parameters = @{
        Method = $Method
        Uri = "https://api.resend.com$Path"
        Headers = $resendHeaders
        ContentType = "application/json"
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    Invoke-RestMethod @parameters
}

function Invoke-CloudflareApi {
    param([string]$Method, [string]$Path, $Body = $null)
    $parameters = @{
        Method = $Method
        Uri = "https://api.cloudflare.com/client/v4$Path"
        Headers = $cloudflareHeaders
        ContentType = "application/json"
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    $response = Invoke-RestMethod @parameters
    if (-not $response.success) {
        throw "Cloudflare API request failed: $($response.errors | ConvertTo-Json -Compress)"
    }
    $response
}

function Resolve-RecordName {
    param([string]$Name)
    $trimmed = $Name.Trim().TrimEnd('.')
    if ($trimmed -eq "@" -or $trimmed -eq $DomainName) {
        return $DomainName
    }
    if ($trimmed -eq $ZoneName -or $trimmed.EndsWith(".$ZoneName", [StringComparison]::OrdinalIgnoreCase)) {
        return $trimmed
    }
    return "$trimmed.$ZoneName"
}

$listed = Invoke-ResendApi -Method GET -Path "/domains"
$domains = if ($null -ne $listed.data) { @($listed.data) } else { @($listed) }
$matches = @($domains | Where-Object { $_.name -eq $DomainName })
if ($matches.Count -gt 1) {
    throw "More than one Resend domain is named $DomainName"
}

if ($matches.Count -eq 1) {
    $domainId = $matches[0].id
    $created = $false
    $domain = Invoke-ResendApi -Method GET -Path "/domains/$domainId"
} else {
    $domain = Invoke-ResendApi -Method POST -Path "/domains" -Body @{
        name = $DomainName
        region = "ap-northeast-1"
        tls = "enforced"
        capabilities = @{
            sending = "enabled"
            receiving = "disabled"
        }
    }
    $domainId = $domain.id
    $created = $true
}

$changed = 0
$unchanged = 0
foreach ($record in @($domain.records)) {
    $fqdn = Resolve-RecordName -Name $record.name
    $recordType = $record.type.ToUpperInvariant()
    $content = ([string]$record.value).Trim()
    if ($recordType -eq "TXT" -and $content.StartsWith('"') -and $content.EndsWith('"')) {
        $content = $content.Substring(1, $content.Length - 2)
    }
    $body = @{
        type = $recordType
        name = $fqdn
        content = $content
        ttl = 1
        proxied = $false
        comment = "Resend verification for $DomainName"
    }
    if ($recordType -eq "MX") {
        $body.priority = if ($null -ne $record.priority) { [int]$record.priority } else { 10 }
    }

    $encodedName = [uri]::EscapeDataString($fqdn)
    $existing = Invoke-CloudflareApi -Method GET -Path "/zones/$ZoneId/dns_records?type=$recordType&name=$encodedName"
    $matchesForRecord = @($existing.result)
    $same = @($matchesForRecord | Where-Object {
        $_.content.TrimEnd('.') -eq $content.TrimEnd('.') -and
        ($recordType -ne "MX" -or [int]$_.priority -eq [int]$body.priority)
    })
    if ($same.Count -ge 1) {
        $unchanged++
        continue
    }
    if ($matchesForRecord.Count -gt 1) {
        throw "Multiple conflicting $recordType records exist at $fqdn"
    }
    if ($matchesForRecord.Count -eq 1) {
        $null = Invoke-CloudflareApi -Method PUT -Path "/zones/$ZoneId/dns_records/$($matchesForRecord[0].id)" -Body $body
    } else {
        $null = Invoke-CloudflareApi -Method POST -Path "/zones/$ZoneId/dns_records" -Body $body
    }
    $changed++
}

$dmarcName = "_dmarc.$DomainName"
$dmarcBody = @{
    type = "TXT"
    name = $dmarcName
    content = "v=DMARC1; p=quarantine; adkim=s; aspf=r; pct=100"
    ttl = 1
    proxied = $false
    comment = "DMARC policy for Authority Closers transactional mail test domain"
}
$encodedDmarc = [uri]::EscapeDataString($dmarcName)
$existingDmarc = Invoke-CloudflareApi -Method GET -Path "/zones/$ZoneId/dns_records?type=TXT&name=$encodedDmarc"
$dmarcMatches = @($existingDmarc.result)
if ($dmarcMatches.Count -eq 0) {
    $null = Invoke-CloudflareApi -Method POST -Path "/zones/$ZoneId/dns_records" -Body $dmarcBody
    $changed++
} elseif ($dmarcMatches.Count -eq 1 -and $dmarcMatches[0].content -ne $dmarcBody.content) {
    $null = Invoke-CloudflareApi -Method PUT -Path "/zones/$ZoneId/dns_records/$($dmarcMatches[0].id)" -Body $dmarcBody
    $changed++
}

$null = Invoke-ResendApi -Method POST -Path "/domains/$domainId/verify"
$current = Invoke-ResendApi -Method GET -Path "/domains/$domainId"

[ordered]@{
    domain_id = $domainId
    domain = $DomainName
    created = $created
    status = $current.status
    records_required = @($domain.records).Count
    dns_records_changed = $changed
    dns_records_unchanged = $unchanged
    tls = $current.tls
    region = $current.region
} | ConvertTo-Json -Compress
