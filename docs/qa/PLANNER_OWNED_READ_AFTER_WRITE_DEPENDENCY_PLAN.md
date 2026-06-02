# Planner-Owned Read-After-Write Dependency Plan

## Context

The planner-owned graph currently uses a hybrid intake design:

- The LLM can label user clauses during `semantic_intake_node`.
- The deterministic compiler has final authority over the requirement ledger.
- The ledger schema already supports `depends_on`, `conditional_branches`, `clarification_needs`, and requirement origins.

This is the right authority split. The issue is that the deterministic compiler does not yet recognize some read-after-write follow-up phrases as executable dependencies.

## Observed Failure

Prompt:

```text
Change planned low-priority jobs to medium priority, then show the updated jobs.
```

Current compiled ledger:

```yaml
requirements:
  - id: req-001
    goal: Change planned low-priority jobs to medium priority
    requirement_type: mutation_request
    entity: job
    depends_on: []

clarification_needs:
  - id: clarification-001
    text: show the updated jobs.
    reason: dependent_singular_read_missing_bound_entity
    blocked_entity: updated
```

Problem:

- `show the updated jobs` is treated as a clarification.
- No dependent read requirement is created.
- Final validation can pass after the write because the graph only knows about `req-001`.
- The user expected a second step: show the jobs affected by the write.

## Desired Ledger Behavior

The same prompt should compile into two requirements:

```yaml
requirements:
  - id: req-001
    goal: Change planned low-priority jobs to medium priority
    requirement_type: mutation_request
    entity: job
    intent_operation: update_many
    constraints:
      status: planned
      priority: low
      new_priority: medium
      requires_approval: true
    produces:
      alias: updated_jobs
      entity: job
      binding: affected_entity_ids

  - id: req-002
    goal: show the updated jobs
    requirement_type: filtered_collection
    entity: job
    intent_operation: read_many
    status: blocked
    depends_on:
      - req-001
    consumes:
      alias: updated_jobs
      from_requirement: req-001
      binding: affected_entity_ids
```

The existing `RequirementLedgerEntry` does not currently have explicit `produces` or `consumes` fields. Until those fields are added, the binding can be represented through deterministic constraints and diagnostics:

```yaml
req-002:
  depends_on:
    - req-001
  constraints:
    depends_on_result_binding: updated_jobs
    result_binding_source_requirement: req-001
    result_binding_field: affected_entity_ids
```

## Dependency Recognition Rule

Add a deterministic compiler rule after semantic intake and before clarification fallback:

```text
IF current clause is a read/show/list/get request
AND current clause references a previous result using one of:
  updated jobs
  changed jobs
  affected jobs
  modified jobs
  same jobs
  those jobs
  these jobs
  them
AND the previous executable requirement is a mutation_request
AND the previous requirement has the same entity or a compatible plural entity
THEN create a dependent read requirement
AND set depends_on to the previous mutation requirement id
```

For the target prompt:

```text
show the updated jobs
```

should bind to:

```text
the job records affected by req-001
```

not to an entity named:

```text
updated
```

## Runtime Behavior

The graph should execute like this:

1. Compile `req-001` mutation and `req-002` dependent read.
2. Planner runs `req-001`.
3. Write tool calls are staged for approval.
4. Graph pauses for approval.
5. After approval, the staged writes are committed.
6. Evidence records the affected job IDs and committed after-state.
7. Satisfaction marks `req-001` satisfied.
8. Dependency scheduler unblocks `req-002`.
9. Planner loops back and reads the updated jobs.
10. Final response renders the updated jobs.

If approval is rejected or the write fails, `req-002` must remain blocked or be marked unsatisfied. It must not run as if the write happened.

## Related Approval Bug

The current approval resume path also appears to overwrite every staged bulk write with the same approved args. In the observed run, staged calls targeted multiple jobs before approval, but after approval every API evidence targeted `JOB-SEED-005`.

Fix separately:

- Preserve each staged call's identity/path args during bulk approval.
- Do not merge global `approved_args.id` into every staged call.
- Only allow approved args to change shared mutable fields such as `priority` or `status`.

## Test Plan

### Unit Tests

Add tests for requirement compilation:

- `Change planned low-priority jobs to medium priority, then show the updated jobs.`
  - Expect `req-001` mutation.
  - Expect `req-002` read.
  - Expect `req-002.depends_on == ["req-001"]`.
  - Expect no clarification for `show the updated jobs`.

- `Update those jobs to high priority` after a previous read requirement.
  - Preserve existing previous-result-set mutation binding behavior.

- `Show the updated jobs` with no previous mutation.
  - Keep clarification behavior because there is no safe parent binding.

- `Change planned low-priority jobs to medium priority, then show the affected jobs.`
  - Same behavior as `updated jobs`.

### Graph/E2E Tests

Add an approval-resume graph test:

1. Submit the prompt.
2. Verify pending approval includes staged writes for all matching jobs.
3. Approve the write.
4. Verify each staged call preserves its own job ID.
5. Verify write evidence records all affected IDs.
6. Verify the graph loops back to execute `req-002`.
7. Verify final response contains updated job rows.

Add rejection test:

1. Submit the same prompt.
2. Reject approval.
3. Verify write is not executed.
4. Verify dependent read does not run.
5. Verify final response explains the write was rejected and dependent result is unavailable.

## Acceptance Criteria

- The target prompt creates a two-requirement ledger.
- The dependent read is blocked until the write requirement has committed evidence.
- Approval rejection prevents dependent read execution.
- Bulk approval preserves row-specific IDs.
- Final response can show the updated jobs after approval.
- Existing conditional branch behavior remains unchanged.
