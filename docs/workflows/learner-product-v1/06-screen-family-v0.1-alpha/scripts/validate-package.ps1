[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$matrixPath = Join-Path $packageRoot '02-ux-state-spec\state-transition-matrix.csv'
$sourceManifestPath = Join-Path $packageRoot '01-research-journeys\source-manifest.csv'
$contextPath = Join-Path $packageRoot '04-ai-context\ai-design-context.json'
$manifestPath = Join-Path $packageRoot '05-handoff-qa\asset-manifest.json'
$diagramManifestPath = Join-Path $packageRoot '05-handoff-qa\diagram-manifest.json'
$diagramPath = Join-Path $packageRoot '04-ai-context\learner-screen-family.puml'
$catalogPath = Join-Path $packageRoot '01-research-journeys\flow-catalog.md'
$inventoryPath = Join-Path $packageRoot '01-research-journeys\screen-inventory.md'
$visualPath = Join-Path $packageRoot '03-visual-exploration\README.md'

function Assert-Condition([bool]$condition, [string]$message) {
    if (-not $condition) { throw "VALIDATION FAILED: $message" }
}

foreach ($jsonPath in (Get-ChildItem -Path $packageRoot -Recurse -Filter '*.json' -File)) {
    $null = Get-Content -Raw $jsonPath.FullName | ConvertFrom-Json
}

$rows = Import-Csv $matrixPath
$required = @('flow_id','screen_id','route','actor','state','trigger','visible_structure','primary_action','secondary_action','system_response','preserved_input','error_or_status','recovery','analytics_event','accessibility_requirement','source_of_truth','qa_status')
Assert-Condition ($rows.Count -gt 0) 'state matrix has no rows'
foreach ($column in $required) {
    Assert-Condition ($rows[0].PSObject.Properties.Name -contains $column) "missing column $column"
}
foreach ($row in $rows) {
    foreach ($column in $required) {
        Assert-Condition (-not [string]::IsNullOrWhiteSpace([string]$row.$column)) "blank $column in $($row.screen_id)/$($row.state)"
    }
}

$sourceRows = Import-Csv $sourceManifestPath
$sourceRequired = @('fetch_order','source_key','title','drive_id','drive_url','source_kind','authority_role','observed_revision_id','fetched_at','status','package_use')
Assert-Condition ($sourceRows.Count -eq 23) "expected 23 controlled source rows, got $($sourceRows.Count)"
foreach ($column in $sourceRequired) {
    Assert-Condition ($sourceRows[0].PSObject.Properties.Name -contains $column) "source manifest missing column $column"
}
foreach ($source in $sourceRows) {
    foreach ($column in $sourceRequired) {
        if ($source.source_key -eq 'AC-UXA-01' -and $column -eq 'observed_revision_id') { continue }
        Assert-Condition (-not [string]::IsNullOrWhiteSpace([string]$source.$column)) "blank source $column for $($source.source_key)"
    }
    Assert-Condition ([string]$source.drive_url -match [regex]::Escape([string]$source.drive_id)) "source URL/ID mismatch for $($source.source_key)"
}
Assert-Condition ((@($sourceRows | ForEach-Object { [int]$_.fetch_order }) -join ',') -eq ((1..23) -join ',')) 'source fetch order must be exactly 1..23'

foreach ($csvPath in (Get-ChildItem -Path $packageRoot -Recurse -Filter '*.csv' -File)) {
    $null = Import-Csv $csvPath.FullName
}

$catalogText = Get-Content -Raw $catalogPath
$inventoryText = Get-Content -Raw $inventoryPath
$context = Get-Content -Raw $contextPath | ConvertFrom-Json
$flowIds = @($context.flows | ForEach-Object { [string]$_.id })
$screenIds = @($context.flows | ForEach-Object { $_.screens } | ForEach-Object { [string]$_ })
$matrixFlowIds = @($rows | ForEach-Object { [string]$_.flow_id } | Sort-Object -Unique)
$matrixScreenIds = @($rows | ForEach-Object { [string]$_.screen_id } | Sort-Object -Unique)
foreach ($id in $flowIds) { Assert-Condition ($catalogText.Contains($id)) "flow $id missing from catalog" }
foreach ($id in $screenIds) { Assert-Condition ($catalogText.Contains($id) -and $inventoryText.Contains($id)) "screen $id missing from catalog/inventory" }
foreach ($id in $matrixFlowIds) { Assert-Condition ($flowIds -contains $id) "matrix references unknown flow $id" }
foreach ($id in $matrixScreenIds) { Assert-Condition ($screenIds -contains $id) "matrix references unknown screen $id" }

$manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
$diagramManifest = Get-Content -Raw $diagramManifestPath | ConvertFrom-Json
Assert-Condition ([string]$manifest.visual_assets.status -eq 'pending') 'visual asset status must remain pending'
Assert-Condition ([int]$manifest.visual_assets.count -eq 0) 'visual asset count must remain zero while generation is pending'
Assert-Condition ([string]$context.visual_generation.status -eq 'pending') 'AI context visual status must remain pending'
Assert-Condition ((Get-Content -Raw $visualPath).Contains('VISUAL GENERATION PENDING')) 'visual README must state generation is pending'
Assert-Condition ((Get-Content -Raw $diagramPath).Contains('@startuml') -and (Get-Content -Raw $diagramPath).Contains('@enduml')) 'PlantUML source must have start/end markers'
foreach ($asset in $manifest.assets) {
    Assert-Condition (Test-Path (Join-Path $packageRoot ([string]$asset.local_path))) "asset path missing: $($asset.local_path)"
}
foreach ($diagram in $diagramManifest.diagrams) {
    Assert-Condition (Test-Path (Join-Path $packageRoot ([string]$diagram.local_path))) "diagram path missing: $($diagram.local_path)"
}
$visualFiles = @(Get-ChildItem (Join-Path $packageRoot '03-visual-exploration') -Recurse -File | Where-Object { $_.Extension -match '\.(png|jpe?g|webp|gif)$' })
Assert-Condition ($visualFiles.Count -eq [int]$manifest.visual_assets.count) "visual file count $($visualFiles.Count) does not match manifest $($manifest.visual_assets.count)"

Write-Output "VALIDATION PASSED: $($rows.Count) matrix rows; $($flowIds.Count) flows; $($screenIds.Count) screens; visuals pending (0 assets)."
