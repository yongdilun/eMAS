# Evaluate reschedule-all API and verify overlaps
# Prerequisites: Server running on localhost:8080 with X-User-Role: planner
# For apply to succeed: start server with AI_APPLY_SKIP_STALENESS_CHECK=true
#   Example: $env:AI_APPLY_SKIP_STALENESS_CHECK="true"; go run ./cmd/emas
#
# Flow: reschedule-all -> verify proposals -> approve+apply each proposal -> verify applied slots
# verify-overlaps supports scope "proposals" (draft data) and "applied" (job_step_schedule_slots).
# The Gantt displays applied slots; use scope=applied to validate what the Gantt shows.

$base = "http://localhost:8080/api/v1"
$headers = @{
    "Content-Type" = "application/json"
    "X-User-Role" = "planner"
}

Write-Host "1. Calling POST /ai/scheduling/reschedule-all with order_by=readiness..."
$reschedule = Invoke-RestMethod -Uri "$base/ai/scheduling/reschedule-all" -Method POST -Headers $headers -Body '{"order_by":"readiness"}'
$props = $reschedule.data.proposals
$ids = @($props | ForEach-Object { $_.proposal_id })
Write-Host "   Generated $($ids.Count) proposals"

Write-Host "2. Calling POST /ai/scheduling/verify-overlaps (scope=proposals, proposal_ids)..."
$verifyProposals = Invoke-RestMethod -Uri "$base/ai/scheduling/verify-overlaps" -Method POST -Headers $headers -Body (@{ proposal_ids = $ids; scope = "proposals" } | ConvertTo-Json)
Write-Host "   [proposal_ids] valid=$($verifyProposals.data.valid) overlap_count=$($verifyProposals.data.overlap_count) total_slots=$($verifyProposals.data.total_slots)"

Write-Host "2b. Verify-overlaps with inline proposals (from batch response, compare to proposal_ids)..."
$inlineProposals = @($props | ForEach-Object {
    $p = $_
    $slots = @($p.proposed_slots | ForEach-Object {
        @{ job_step_id = $_.job_step_id; machine_id = $_.machine_id; scheduled_start = ($_.scheduled_start -as [DateTime]).ToString("o"); scheduled_end = ($_.scheduled_end -as [DateTime]).ToString("o") }
    })
    @{ proposal_id = $p.proposal_id; job_id = $p.job_id; proposed_slots = $slots }
})
try {
    $body = @{ scope = "proposals"; proposals = $inlineProposals } | ConvertTo-Json -Depth 10 -Compress
    $verifyInline = Invoke-RestMethod -Uri "$base/ai/scheduling/verify-overlaps" -Method POST -Headers $headers -Body $body
    Write-Host "   [inline] valid=$($verifyInline.data.valid) overlap_count=$($verifyInline.data.overlap_count) total_slots=$($verifyInline.data.total_slots)"
    if ($verifyProposals.data.overlap_count -ne $verifyInline.data.overlap_count) {
        Write-Host "   WARNING: Mismatch! proposal_ids=$($verifyProposals.data.overlap_count) vs inline=$($verifyInline.data.overlap_count)"
    } else {
        Write-Host "   Match: overlap_count=$($verifyProposals.data.overlap_count)"
    }
    if ($verifyInline.data.overlaps -and $verifyInline.data.overlap_count -gt 0) {
        Write-Host "   Overlaps:"
        $verifyInline.data.overlaps | ForEach-Object {
            Write-Host "     $($_.machine_id): $($_.slot_a.job_id) vs $($_.slot_b.job_id) @ $($_.overlap_start) - $($_.overlap_end)"
        }
    }
} catch {
    Write-Host "   [inline] Failed: $_ (proposal_ids result above is authoritative)"
}

Write-Host "3. Approving and applying each proposal (order=readiness; set AI_APPLY_SKIP_STALENESS_CHECK=true on server for batch apply)..."
$applied = 0
$failed = 0
foreach ($proposalId in $ids) {
    try {
        $null = Invoke-RestMethod -Uri "$base/ai/scheduling/proposals/$proposalId/approve" -Method POST -Headers $headers -Body '{"notes":"evaluation"}'
        $null = Invoke-RestMethod -Uri "$base/ai/scheduling/proposals/$proposalId/apply" -Method POST -Headers $headers -Body '{}'
        $applied++
    } catch {
        $failed++
        Write-Host "   Failed: $proposalId - $_"
    }
}
Write-Host "   Applied $applied proposals, failed $failed"

Write-Host "4. Calling POST /ai/scheduling/verify-overlaps (scope=applied)..."
$verifyApplied = Invoke-RestMethod -Uri "$base/ai/scheduling/verify-overlaps" -Method POST -Headers $headers -Body '{"scope":"applied"}'
Write-Host "   [applied] valid=$($verifyApplied.data.valid) overlap_count=$($verifyApplied.data.overlap_count) total_slots=$($verifyApplied.data.total_slots)"

# Save proposals for inspection
$reschedule | ConvertTo-Json -Depth 20 | Out-File -FilePath "reschedule_output.json" -Encoding utf8
Write-Host "5. Saved to reschedule_output.json"

# Timeline summary
Write-Host "`n--- Timeline ---"
$props | Sort-Object { [datetime]$_.earliest_start } | ForEach-Object {
    $es = [datetime]$_.earliest_start
    $ec = [datetime]$_.estimated_completion
    Write-Host "$($_.job_id) | $($es.ToString('yyyy-MM-dd HH:mm')) -> $($ec.ToString('yyyy-MM-dd HH:mm')) | span ~$([math]::Round(($ec - $es).TotalHours, 1))h"
}
