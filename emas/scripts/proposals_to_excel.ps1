# Convert proposals to Excel-compatible CSV for manual overlap check
# Usage: .\proposals_to_excel.ps1 [input.json]
#   Default input: all_proposals.json or reschedule_output.json (in script directory)
# Output: proposals_overlap_check.csv (opens in Excel)
#
# Columns: machine_id, machine_name, job_id, product_id, step_name, scheduled_start, scheduled_end, duration_mins
# Sort: machine, then start time - check rows on same machine for overlapping start/end

param(
    [string]$InputFile = ""
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $InputFile) {
    if (Test-Path (Join-Path $scriptDir "..\all_proposals.json")) {
        $InputFile = Join-Path $scriptDir "..\all_proposals.json"
    } elseif (Test-Path (Join-Path $scriptDir "..\reschedule_output.json")) {
        $InputFile = Join-Path $scriptDir "..\reschedule_output.json"
    } else {
        Write-Host "No input file found. Run check_overlaps_manually.ps1 first, or: .\proposals_to_excel.ps1 path\to\proposals.json"
        exit 1
    }
}

if (-not (Test-Path $InputFile)) {
    Write-Host "File not found: $InputFile"
    exit 1
}

Write-Host "Reading $InputFile..."
$raw = Get-Content $InputFile -Raw | ConvertFrom-Json

# Normalize to array of proposals
# Priority: array of { data } (batch response) > single object with .data.proposals
$props = @()
if ($raw.Count -gt 0 -and $raw[0].data) {
    $props = @($raw | ForEach-Object { $_.data })
} elseif ($raw.data -and ($raw.data -isnot [array]) -and $raw.data.proposals) {
    $props = @($raw.data.proposals)
} elseif ($raw -is [array] -and $raw.Count -gt 0) {
    $props = @($raw)
} else {
    $props = @($raw)
}

Write-Host "Found $($props.Count) proposals"

$rows = @()
foreach ($p in $props) {
    if (-not $p) { continue }
    $slots = @($p.proposed_slots)
    if ($slots.Count -eq 0) { $slots = @($p.ProposedSlots) }
    foreach ($s in $slots) {
        if (-not $s) { continue }
        $start = [datetime]$s.scheduled_start
        $end = [datetime]$s.scheduled_end
        $durMins = [math]::Round(($end - $start).TotalMinutes, 0)
        $rows += [PSCustomObject]@{
            machine_id      = $s.machine_id
            machine_name    = $s.machine_name
            job_id          = $p.job_id
            product_id      = $p.product_id
            step_name       = $s.step_name
            scheduled_start = $start.ToString("yyyy-MM-dd HH:mm")
            scheduled_end   = $end.ToString("yyyy-MM-dd HH:mm")
            duration_mins   = $durMins
            job_step_id     = $s.job_step_id
            proposal_id     = $p.proposal_id
        }
    }
}

# Sort by machine, then start
$rows = $rows | Sort-Object machine_id, scheduled_start

$outPath = Join-Path (Split-Path -Parent $InputFile) "proposals_overlap_check.csv"
$rows | Export-Csv -Path $outPath -NoTypeInformation -Encoding UTF8
Write-Host "Saved to $outPath ($($rows.Count) slots)"
Write-Host ""
Write-Host "Manual overlap check in Excel:"
Write-Host "  1. Open the CSV in Excel"
Write-Host "  2. Filter/sort by machine_id"
Write-Host "  3. For each machine, check consecutive rows: if RowN.scheduled_end > RowN+1.scheduled_start = OVERLAP"
Write-Host "  Overlap rule: A overlaps B when A.start < B.end AND A.end > B.start"
