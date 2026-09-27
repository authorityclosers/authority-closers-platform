<#
.SYNOPSIS
  Run one phase of the Sales Xray v0.2 "Lightbox" UI implementation with Claude Code (Opus 5.5, effort xhigh), headless.

.DESCRIPTION
  Intended to be called by Codex (the integration and release owner). Claude edits and commits inside the given
  worktree only; it may not push, deploy, ssh or touch other worktrees. Each run prints Claude's final JSON report
  and saves the full JSON result (with session_id) under $HOME\.sales-xray-lightbox-runs\.

  Verified against Claude Code 2.1.281 (`claude --help`):
    --model <id>  --effort low|medium|high|xhigh|max  -p/--print  --output-format json
    --permission-mode acceptEdits  --permission-prompts none  --allowedTools/--disallowedTools
    --session-id <uuid>  -r/--resume <id>  -n/--name  --append-system-prompt  --max-budget-usd
  There is NO --cwd flag: the script Set-Locations into the worktree. Do NOT use --bare (it disables normal login).

.EXAMPLE
  # Phase 0 (plan only)
  pwsh -File .\run-claude-ui.ps1 -Phase P0 -Worktree C:\Users\Suyash\.codex\worktrees\sales-xray-lightbox-ui\authority-closers-platform

.EXAMPLE
  # Continue the same Claude session with review feedback from Codex
  pwsh -File .\run-claude-ui.ps1 -Phase P2 -Worktree <path> -Resume <session-id> -Message "Codex review: fix the failing test in acquisition-client.test.ts and keep U1 semantics"
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][ValidateSet('P0','P1','P2','P3','P4','P5','P6')][string]$Phase,
  [Parameter(Mandatory = $true)][string]$Worktree,
  [string]$Resume = '',
  [string]$Message = '',
  [double]$MaxBudgetUsd = 0,
  [string]$Model = 'claude-opus-5-5',
  [ValidateSet('high','xhigh','max')][string]$Effort = 'xhigh'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw 'Claude Code CLI (claude) is not on PATH.' }
try { $auth = (claude auth status 2>$null | Out-String) | ConvertFrom-Json } catch { $auth = $null }
if (-not $auth -or -not $auth.loggedIn) {
  throw 'Claude Code CLI is not signed in. The founder must run `claude auth login` (or `claude setup-token` for a long-lived headless token) once on this PC, then re-run.'
}
if (-not (Test-Path (Join-Path $Worktree '.git'))) { throw "Not a git worktree: $Worktree" }

Set-Location $Worktree
$branch = (git branch --show-current).Trim()
if (-not $branch -or $branch -in @('main','master')) { throw "Refusing to run on branch '$branch'. Use the Lightbox UI branch." }
$brief = 'docs/design/sales-xray-v02-lightbox-20260924/CLAUDE_UI_BRIEF.md'
if (-not (Test-Path $brief)) { throw "Missing $brief in this worktree. Commit the design package to the branch first." }
$dirty = git status --porcelain
if ($dirty) { Write-Warning "Worktree has uncommitted changes; Claude will see them:`n$dirty" }

$runsDir = Join-Path $HOME '.sales-xray-lightbox-runs'
New-Item -ItemType Directory -Force $runsDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$guard = @'
You are running headless for Codex on the Sales Xray Lightbox UI. Hard rules: edit only apps/sales-xray-web/** (and packages/typescript/sales-xray-client/** if strictly needed) plus the Lightbox docs folder; never git push, never force, never ssh, never deploy, never read .env values, cookies, provider payloads or customer audio/transcripts; never change packages/python, db, infra or .github. Finish every run with the JSON report block defined in CLAUDE_UI_BRIEF.md section 6.
'@

$allowed = @(
  'Read','Edit','Write','Glob','Grep','TodoWrite',
  'Bash(pnpm *)','Bash(npx *)','Bash(node *)',
  'Bash(git status*)','Bash(git diff*)','Bash(git add *)','Bash(git commit *)','Bash(git log*)','Bash(git show*)','Bash(git restore *)','Bash(git mv *)','Bash(git rm *)',
  'Bash(ls*)','Bash(cat *)','Bash(mkdir *)','Bash(cp *)','Bash(mv *)','Bash(rm apps/sales-xray-web/*)',
  'PowerShell(pnpm *)','PowerShell(npx *)','PowerShell(node *)',
  'PowerShell(git status*)','PowerShell(git diff*)','PowerShell(git add *)','PowerShell(git commit *)','PowerShell(git log*)','PowerShell(git show*)','PowerShell(git restore *)','PowerShell(git mv *)','PowerShell(git rm *)',
  'PowerShell(Get-ChildItem*)','PowerShell(Get-Content*)','PowerShell(New-Item*)','PowerShell(Copy-Item*)','PowerShell(Move-Item*)'
) -join ','
$disallowed = @(
  'Bash(git push*)','Bash(git reset --hard*)','Bash(git rebase*)','Bash(git worktree*)','Bash(ssh *)','Bash(scp *)','Bash(curl *)','Bash(gh *)',
  'PowerShell(git push*)','PowerShell(git reset --hard*)','PowerShell(git rebase*)','PowerShell(git worktree*)','PowerShell(ssh *)','PowerShell(scp *)','PowerShell(gh *)','PowerShell(Invoke-WebRequest*)',
  'WebFetch'
) -join ','

$common = @(
  '-p',
  '--model', $Model,
  '--effort', $Effort,
  '--permission-mode', 'acceptEdits',
  '--permission-prompts', 'none',
  '--allowedTools', $allowed,
  '--disallowedTools', $disallowed,
  '--append-system-prompt', $guard,
  '--output-format', 'json'
)
if ($MaxBudgetUsd -gt 0) { $common += @('--max-budget-usd', "$MaxBudgetUsd") }

if ($Resume) {
  if (-not $Message) { throw '-Resume needs -Message (the follow-up instruction from Codex).' }
  $prompt = "PHASE=$Phase (continuing). $Message"
  $claudeArgs = @($prompt, '--resume', $Resume) + $common
} else {
  $sessionId = [guid]::NewGuid().ToString()
  $prompt = "PHASE=$Phase. Read $brief and follow it for this phase only. Current branch: $branch."
  if ($Message) { $prompt += " Extra instruction from Codex: $Message" }
  $claudeArgs = @($prompt, '--session-id', $sessionId, '--name', "sales-xray-lightbox-$Phase") + $common
}

Write-Host "Running Claude ($Model, effort $Effort) for $Phase on branch $branch ..."
$raw = & claude @claudeArgs
$exit = $LASTEXITCODE
$outFile = Join-Path $runsDir "$Phase-$stamp.json"
$raw | Set-Content -Path $outFile -Encoding utf8
Write-Host "Saved full result: $outFile"

try {
  $json = $raw | ConvertFrom-Json
  Write-Host "session_id: $($json.session_id)   is_error: $($json.is_error)   cost_usd: $($json.total_cost_usd)"
  $text = [string]$json.result
  $m = [regex]::Match($text, '```json\s*(\{[\s\S]*?\})\s*```\s*$')
  if ($m.Success) { Write-Host "`n--- Claude phase report ---"; $m.Groups[1].Value } else { Write-Host "`n--- Claude final message ---"; $text }
} catch {
  Write-Warning "Could not parse JSON output; see $outFile"
}
exit $exit
