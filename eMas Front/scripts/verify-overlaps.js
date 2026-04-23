/**
 * Script to call verify-overlaps API and print results to console.
 * Run: node scripts/verify-overlaps.js
 * Requires backend at http://localhost:8080
 */
const BASE = 'http://localhost:8080/api/v1'
const headers = { 'Content-Type': 'application/json', 'X-User-Role': 'planner' }

async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  return res.json()
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  return res.json()
}

function toList(d) {
  if (!d) return []
  if (Array.isArray(d)) return d
  return d.data || d.items || d.proposals || d.jobs || []
}

function toData(d) {
  if (!d) return null
  if (d.data !== undefined) return d.data
  return d
}

/** Parse proposal (top-level or proposal_json) to get proposed_slots */
function getProposedSlots(p) {
  if (p?.proposed_slots && Array.isArray(p.proposed_slots)) return p.proposed_slots
  if (p?.proposal_json) {
    try {
      const j = typeof p.proposal_json === 'string' ? JSON.parse(p.proposal_json) : p.proposal_json
      return j?.proposed_slots || []
    } catch { return [] }
  }
  return []
}

/** Partial overlap: intervals share ANY time (A_start < B_end && A_end > B_start) */
function overlaps(startA, endA, startB, endB) {
  const a = new Date(startA).getTime()
  const ae = new Date(endA).getTime()
  const b = new Date(startB).getTime()
  const be = new Date(endB).getTime()
  return a < be && ae > b
}

async function main() {
  console.log('=== Verify Overlaps API Check ===\n')

  try {
    // 1. Fetch jobs
    console.log('1. Fetching jobs...')
    const jobsRes = await get('/jobs')
    const jobs = toList(toData(jobsRes) || jobsRes)
    const jobIds = jobs.map((j) => j.job_id || j.jobId || j.id).filter(Boolean)
    console.log(`   Found ${jobIds.length} jobs: ${jobIds.slice(0, 5).join(', ')}${jobIds.length > 5 ? '...' : ''}\n`)

    // 2. Fetch full proposals per job (same data the UI displays)
    const proposals = []
    const proposalIds = []
    for (const id of jobIds) {
      const listRes = await get(`/ai/scheduling/jobs/${id}/proposals`)
      const list = toList(toData(listRes) || listRes)
      const draft = list.find((p) => (p.status || 'draft') === 'draft') || list[0]
      if (draft?.proposal_id) {
        proposalIds.push(draft.proposal_id)
        proposals.push({ ...draft, job_id: draft.job_id ?? id })
      }
    }
    console.log(`2. Fetched proposals for ${jobIds.length} jobs → ${proposalIds.length} proposal IDs`)
    if (proposalIds.length > 0) console.log(`   IDs: ${proposalIds.slice(0, 5).join(', ')}${proposalIds.length > 5 ? '...' : ''}\n`)

    // 2b. Local overlap check (same data + logic as UI)
    // Standard definition: overlap = ANY shared time (startA < endB && endA > startB)
    console.log('2b. LOCAL overlap check (partial overlap: any shared time on same machine)')
    const allSlots = []
    for (const p of proposals) {
      const slots = getProposedSlots(p)
      const jobId = p.job_id
      for (const s of slots) {
        if (s.machine_id && s.scheduled_start) {
          allSlots.push({
            job_id: jobId,
            machine_id: s.machine_id,
            start: s.scheduled_start,
            end: s.scheduled_end || s.scheduled_start,
          })
        }
      }
    }
    const byMachine = new Map()
    for (const s of allSlots) {
      if (!byMachine.has(s.machine_id)) byMachine.set(s.machine_id, [])
      byMachine.get(s.machine_id).push(s)
    }
    const localOverlaps = []
    for (const [machineId, slots] of byMachine) {
      for (let i = 0; i < slots.length; i++) {
        for (let j = i + 1; j < slots.length; j++) {
          const a = slots[i], b = slots[j]
          if (overlaps(a.start, a.end, b.start, b.end)) {
            localOverlaps.push({
              machine_id: machineId,
              jobA: a.job_id,
              jobB: b.job_id,
              startA: a.start,
              endA: a.end,
              startB: b.start,
              endB: b.end,
            })
          }
        }
      }
    }
    if (localOverlaps.length > 0) {
      console.log(`   ❌ FOUND ${localOverlaps.length} overlap(s) in display data:`)
      localOverlaps.forEach((o, i) => {
        console.log(`      [${i + 1}] machine ${o.machine_id}: ${o.jobA} [${o.startA} → ${o.endA}] vs ${o.jobB} [${o.startB} → ${o.endB}]`)
      })
      console.log('   → Backend may check "whole" overlap only; frontend shows partial overlap.')
    } else {
      console.log('   ✓ No overlaps in display data (partial-overlap check).')
    }
    console.log('')

    // 3. Verify proposals (scope=proposals)
    console.log('3. POST /ai/scheduling/verify-overlaps { scope: "proposals", proposal_ids: [...] }')
    const verifyProposals = proposalIds.length
      ? await post('/ai/scheduling/verify-overlaps', { scope: 'proposals', proposal_ids: proposalIds })
      : { success: false, error: 'No proposal IDs' }
    const vp = toData(verifyProposals) || verifyProposals
    console.log(JSON.stringify(verifyProposals, null, 2))
    if (vp) {
      console.log(`\n   → valid: ${vp.valid}, total_slots: ${vp.total_slots ?? '?'}, overlap_count: ${vp.overlap_count ?? '?'}`)
      if (vp.overlaps?.length > 0) {
        console.log('   → OVERLAPS FOUND:')
        vp.overlaps.forEach((o, i) => console.log(`      [${i}] ${typeof o === 'string' ? o : JSON.stringify(o)}`))
      }
    }
    console.log('')

    // 4. Verify applied slots (scope=applied)
    console.log('4. POST /ai/scheduling/verify-overlaps { scope: "applied" }')
    const verifyApplied = await post('/ai/scheduling/verify-overlaps', { scope: 'applied' })
    const va = toData(verifyApplied) || verifyApplied
    console.log(JSON.stringify(verifyApplied, null, 2))
    if (va) {
      console.log(`\n   → valid: ${va.valid}, total_slots: ${va.total_slots ?? '?'}, overlap_count: ${va.overlap_count ?? '?'}`)
      if (va.overlaps?.length > 0) {
        console.log('   → OVERLAPS FOUND (persisted slots):')
        va.overlaps.forEach((o, i) => console.log(`      [${i}] ${typeof o === 'string' ? o : JSON.stringify(o)}`))
      }
    }

    console.log('\n=== Done ===')
  } catch (err) {
    console.error('Error:', err.message)
    if (err.cause) console.error('Cause:', err.cause)
    process.exit(1)
  }
}

main()
