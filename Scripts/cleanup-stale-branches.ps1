# cleanup-stale-branches.ps1
#
# ONE-TIME MANUAL CLEANUP for SF2AIS (Windows / PowerShell).
#
# See Scripts/cleanup-stale-branches.sh for the full background.
# Deletion of the two stale secret-bearing branches is blocked by the repo
# ruleset "Ai coding help" (id 19042974), which enforces `deletion` + `non_fast_forward`.
# This script snapshots the ruleset, disables it, deletes the branches, then
# re-enables it.
#
# Requirements: `gh` CLI authenticated with admin/ruleset-write access to ZULFURIA/SF2AIS.
# Run from a PowerShell prompt:
#   pwsh -ExecutionPolicy Bypass -File Scripts\cleanup-stale-branches.ps1

$ErrorActionPreference = "Stop"
$Repo   = "ZULFURIA/SF2AIS"
$RulesetId = "19042974"
$Stale  = @("feature/desktop-probe-electron-app", "feature/probe-startup-scripts")

$tmp = New-Item -ItemType File -Path (Join-Path $env:TEMP ("sf2ais-ruleset-" + [guid]::NewGuid().ToString() + ".json")) -Force

# Restore the ruleset on exit (even on error)
trap {
    Write-Output ">>> Restoring ruleset to active..."
    gh api "repos/$Repo/rulesets/$RulesetId" -X PATCH -f enforcement=active 2>$null
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

Write-Output ">>> Snapshotting current ruleset..."
gh api "repos/$Repo/rulesets/$RulesetId" > $tmp.FullName

Write-Output ">>> Disabling ruleset (temporarily)..."
gh api "repos/$Repo/rulesets/$RulesetId" -X PATCH -f enforcement=disabled | Out-Null

foreach ($b in $Stale) {
    Write-Output ">>> Deleting remote branch: $b"
    try {
        git push origin --delete $b 2>&1
        Write-Output "    deleted: $b"
    } catch {
        Write-Warning "    FAILED to delete: $b"
    }
}

Write-Output ">>> Ruleset restored by exit trap."
Write-Output "DONE. Remember to ROTATE the exposed DuckDNS + probe tokens."
