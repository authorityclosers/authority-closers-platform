[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure {
    param([string]$Message)
    [void]$script:failures.Add($Message)
}

function Require-File {
    param([string]$RelativePath)
    $path = Join-Path $packageRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Failure "Missing required artifact: $RelativePath"
    }
}

$required = @(
    'README.md', '00-start-here/scope-and-authority.md',
    '00-start-here/experience-brief.md',
    '01-research-journeys/source-manifest.csv',
    '01-research-journeys/source-manifest.md',
    '01-research-journeys/research-scan.md',
    '01-research-journeys/journeys.md',
    '01-research-journeys/screen-inventory.csv',
    '02-ux-state-spec/state-taxonomy.md', '02-ux-state-spec/route-contract.md',
    '02-ux-state-spec/behavioral-spec.md',
    '02-ux-state-spec/state-transition-matrix.csv',
    '03-visual-exploration/README.md',
    '03-visual-exploration/responsive-reference-wireframes.md',
    '04-ai-context/ai-design-context.json', '04-ai-context/prompt-pack.md',
    '04-ai-context/instructor-admin-workflow.puml',
    '05-handoff-qa/component-contract.md',
    '05-handoff-qa/asset-manifest.json', '05-handoff-qa/diagram-manifest.json',
    '05-handoff-qa/decision-log.md', '05-handoff-qa/qa-release-checklist.md',
    '05-handoff-qa/validation-report.md', 'scripts/validate-package.ps1'
)
foreach ($relative in $required) { Require-File $relative }

function Read-Json {
    param([string]$RelativePath)
    try { return (Get-Content -LiteralPath (Join-Path $packageRoot $RelativePath) -Raw | ConvertFrom-Json) }
    catch { Add-Failure "Invalid JSON: $RelativePath ($($_.Exception.Message))"; return $null }
}

$ai = Read-Json '04-ai-context/ai-design-context.json'
$assets = Read-Json '05-handoff-qa/asset-manifest.json'
$diagrams = Read-Json '05-handoff-qa/diagram-manifest.json'
foreach ($json in @($ai, $assets, $diagrams)) {
    if ($null -ne $json -and $json.package_id -ne 'AC-WF-INSTRUCTOR-ADMIN-V0.1') {
        Add-Failure 'JSON package_id does not match AC-WF-INSTRUCTOR-ADMIN-V0.1'
    }
}

$sourceKeys = @{}
$sourcePath = Join-Path $packageRoot '01-research-journeys/source-manifest.csv'
try { $sources = @(Import-Csv -LiteralPath $sourcePath) }
catch { $sources = @(); Add-Failure "Cannot parse source manifest CSV: $($_.Exception.Message)" }
$sourceHeaders = @('fetch_order','source_key','title','drive_id','drive_url','source_kind','authority_role','observed_revision_id','fetched_at','status','package_use')
if ($sources.Count -gt 0) {
    $actualHeaders = @($sources[0].PSObject.Properties.Name)
    if ($null -ne (Compare-Object $sourceHeaders $actualHeaders)) { Add-Failure 'Source manifest headers are not the required schema' }
    foreach ($row in $sources) {
        if ($sourceKeys.ContainsKey($row.source_key)) { Add-Failure "Duplicate source_key: $($row.source_key)" }
        $sourceKeys[$row.source_key] = $row
        if ([string]::IsNullOrWhiteSpace($row.drive_id) -or -not $row.drive_url.Contains($row.drive_id)) {
            Add-Failure "Drive URL does not contain exact ID for source: $($row.source_key)"
        }
    }
}
$expectedKeys = @('MASTER-INDEX','BRD','AC-IMP-00','AC-IMP-01','AC-IMP-03','AC-IMP-04','AC-IMP-05','PRD','IA','UX-RESEARCH','UX-STATES','UI-SYSTEM','SRS','DATA-TENANCY','API-MCP','SECURITY','ADMIN','TELEMETRY','MOBILE-PWA','DEVOPS-SRE','QA-RELEASE','ADR-RISK','AC-UXA-01','AC-SVAL-01')
foreach ($key in $expectedKeys) { if (-not $sourceKeys.ContainsKey($key)) { Add-Failure "Missing required source key: $key" } }
if ($sources.Count -lt $expectedKeys.Count) { Add-Failure "Source manifest has $($sources.Count) rows; expected at least $($expectedKeys.Count)" }

$inventoryPath = Join-Path $packageRoot '01-research-journeys/screen-inventory.csv'
$matrixPath = Join-Path $packageRoot '02-ux-state-spec/state-transition-matrix.csv'
try { $inventory = @(Import-Csv -LiteralPath $inventoryPath) } catch { $inventory = @(); Add-Failure "Cannot parse screen inventory CSV: $($_.Exception.Message)" }
try { $matrix = @(Import-Csv -LiteralPath $matrixPath) } catch { $matrix = @(); Add-Failure "Cannot parse state matrix CSV: $($_.Exception.Message)" }
$inventoryById = @{}
foreach ($row in $inventory) {
    if ($inventoryById.ContainsKey($row.screen_id)) { Add-Failure "Duplicate screen_id: $($row.screen_id)" }
    $inventoryById[$row.screen_id] = $row
}
$matrixHeaders = @('flow_id','screen_id','route','actor','state','trigger','visible_structure','primary_action','secondary_action','system_response','preserved_input','error_or_status','recovery','analytics_event','accessibility_requirement','source_of_truth','qa_status')
if ($matrix.Count -gt 0) {
    if ($null -ne (Compare-Object $matrixHeaders @($matrix[0].PSObject.Properties.Name))) { Add-Failure 'State matrix headers are not the required 17-column schema' }
    $allowedFlows = @('FLOW-IAS-01','FLOW-IAS-02','FLOW-IAS-03','FLOW-IAS-04','FLOW-IAS-05','FLOW-IAS-06')
    $allowedStates = @('loading','ready','empty','permission_denied','session_expired','offline_or_stale','retryable_error','terminal_error','draft','validation_error','in_review','version_conflict','success','partial','reconciliation_required','provider_failed','processing','uploaded','upload_failed','assessment_authoring_blocked','support_required','blocked')
    foreach ($row in $matrix) {
        if ($row.PSObject.Properties.Name.Count -ne 17) { Add-Failure "State matrix row has wrong field count: $($row.screen_id)/$($row.state)" }
        foreach ($field in @('flow_id','screen_id','route','actor','state','system_response','recovery','accessibility_requirement','source_of_truth','qa_status')) {
            if ([string]::IsNullOrWhiteSpace([string]$row.$field)) { Add-Failure "Empty state matrix field $field at $($row.screen_id)/$($row.state)" }
        }
        if ($allowedFlows -notcontains $row.flow_id) { Add-Failure "Unknown flow_id: $($row.flow_id)" }
        if ($allowedStates -notcontains $row.state) { Add-Failure "Unknown state: $($row.state)" }
        if (-not $inventoryById.ContainsKey($row.screen_id)) { Add-Failure "Matrix references unknown screen: $($row.screen_id)" }
        elseif ($inventoryById[$row.screen_id].route -ne $row.route) { Add-Failure "Route mismatch for $($row.screen_id)" }
    }
}

if ($null -ne $ai) {
    $contextScreens = @($ai.screens | ForEach-Object { $_.id })
    foreach ($screenId in $inventoryById.Keys) { if ($contextScreens -notcontains $screenId) { Add-Failure "AI context missing screen: $screenId" } }
}
if ($null -ne $diagrams) {
    foreach ($diagram in @($diagrams.diagrams)) {
        $path = Join-Path $packageRoot $diagram.path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Add-Failure "Missing diagram path: $($diagram.path)"; continue }
        $puml = Get-Content -LiteralPath $path -Raw
        if (-not $puml.Contains('@startuml') -or -not $puml.Contains('@enduml')) { Add-Failure "Invalid PlantUML boundary: $($diagram.path)" }
        foreach ($stableId in @($diagram.stable_ids)) { if (-not $puml.Contains($stableId)) { Add-Failure "PlantUML missing stable ID: $stableId" } }
    }
}

$linkPattern = '(?<!\!)\[[^\]]+\]\(([^)]+)\)'
foreach ($md in @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File -Filter '*.md')) {
    $content = Get-Content -LiteralPath $md.FullName -Raw
    foreach ($match in [regex]::Matches($content, $linkPattern)) {
        $target = $match.Groups[1].Value.Trim()
        if ($target.StartsWith('http://') -or $target.StartsWith('https://') -or $target.StartsWith('#') -or $target.StartsWith('mailto:')) { continue }
        $target = ($target -replace '#.*$','').Trim('<','>')
        if (-not (Test-Path -LiteralPath (Join-Path $md.DirectoryName $target))) { Add-Failure "Broken local link in $($md.Name): $target" }
    }
}

$allowedExtensions = @('.md','.csv','.json','.puml','.ps1')
foreach ($file in @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File)) {
    if ($allowedExtensions -notcontains $file.Extension.ToLowerInvariant()) {
        Add-Failure "Non-doc artifact in package: $($file.FullName.Substring($packageRoot.Length + 1))"
    }
}

if ($failures.Count -gt 0) {
    Write-Output "VALIDATION_FAILED ($($failures.Count) issue(s))"
    foreach ($failure in $failures) { Write-Output "- $failure" }
    exit 1
}
Write-Output 'VALIDATION_PASSED'
Write-Output "Artifacts: $($required.Count); sources: $($sources.Count); screens: $($inventory.Count); matrix rows: $($matrix.Count)"
Write-Output 'JSON, CSV, Markdown links, PlantUML IDs and docs-only scope checks passed.'
