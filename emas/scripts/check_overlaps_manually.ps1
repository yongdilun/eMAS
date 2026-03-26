# Manual overlap check: GET all proposals, save to JSON, and print slots by machine
# Prerequisites: Server running on localhost:8080. Run evaluate_reschedule.ps1 first, OR
#                this script will call reschedule-all to get fresh proposals.
# Output: all_proposals.json (full data), slots_by_machine.json (for manual overlap check)

$base = "http://localhost:8080/api/v1"
$headers = @{
    "Content-Type" = "application/json"
    "X-User-Role" = "planner"
}

Write-Host "1. Getting proposals (POST reschedule-all)..."
$reschedule = Invoke-RestMethod -Uri "$base/ai/scheduling/reschedule-all" -Method POST -Headers $headers -Body '{"order_by":"readiness"}'
$props = $reschedule.data.proposals
$ids = @($props | ForEach-Object { $_.proposal_id })

Write-Host "2. GET each proposal and collect full data..."
$allProposals = @()
foreach ($proposalId in $ids) {
    $p = Invoke-RestMethod -Uri "$base/ai/scheduling/proposals/$proposalId" -Method GET -Headers $headers
    $allProposals += $p
}

Write-Host "3. Saving all proposals to all_proposals.json..."
$allProposals | ConvertTo-Json -Depth 15 | Out-File -FilePath "all_proposals.json" -Encoding utf8
Write-Host "   Saved $($allProposals.Count) proposals"

Write-Host "4. Building slots-by-machine view for manual overlap check..."
$byMachine = @{}
foreach ($p in $allProposals) {
    foreach ($s in $p.proposed_slots) {
        $mid = $s.machine_id
        if (-not $byMachine[$mid]) { $byMachine[$mid] = @() }
        $byMachine[$mid] += @{
            job_id = $p.job_id
            proposal_id = $p.proposal_id
            job_step_id = $s.job_step_id
            scheduled_start = $s.scheduled_start
            scheduled_end = $s.scheduled_end
            step_name = $s.step_name
        }
    }
}
$slotsByMachine = @{}
$byMachine.Keys | Sort-Object | ForEach-Object {
    $slotsByMachine[$_] = @($byMachine[$_] | Sort-Object { [datetime]$_.scheduled_start })
}
$slotsByMachine | ConvertTo-Json -Depth 10 | Out-File -FilePath "slots_by_machine.json" -Encoding utf8

Write-Host "5. Printing slots by machine (check for overlapping times on same machine)..."
Write-Host ""
foreach ($machineId in ($slotsByMachine.Keys | Sort-Object)) {
    Write-Host "=== $machineId ==="
    $slots = $slotsByMachine[$machineId]
    foreach ($s in $slots) {
        $start = [datetime]$s.scheduled_start
        $end = [datetime]$s.scheduled_end
        Write-Host "  $($s.job_id) | $($start.ToString('yyyy-MM-dd HH:mm')) - $($end.ToString('HH:mm')) | $($s.step_name)"
    }
    Write-Host ""
}

Write-Host "6. Calling verify-overlaps API for comparison..."
$verify = Invoke-RestMethod -Uri "$base/ai/scheduling/verify-overlaps" -Method POST -Headers $headers -Body (@{ proposal_ids = $ids; scope = "proposals" } | ConvertTo-Json)
Write-Host "   API says: valid=$($verify.data.valid) overlap_count=$($verify.data.overlap_count)"

Write-Host ""
Write-Host "Done. Files created:"
Write-Host "  - all_proposals.json (full proposal data)"
Write-Host "  - slots_by_machine.json (slots grouped by machine)"
Write-Host ""
Write-Host "Manual overlap check: Two slots overlap if on same machine and (A.start < B.end AND A.end > B.start)"
