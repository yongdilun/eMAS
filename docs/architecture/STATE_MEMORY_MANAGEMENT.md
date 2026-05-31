# State And Memory Management Architecture

## Purpose

The factory agent should not treat all persisted context as the same thing. Runtime state, short-term chat memory, and long-term memory have different lifetimes, safety requirements, deletion rules, and prompt budgets.

This design separates those concepts into explicit modules and scopes so a cancelled or paused run can recover safely without leaking stale state into a later conversation, while useful memory can still be retrieved on demand.

## Current Findings

The root `mem0` folder is currently documentation and examples, not an integrated runtime dependency. There are no `from mem0` or `MemoryClient` imports in `factory-agent`, `emas`, the frontend, or tests.

Useful local mem0 notes:

- `mem0/add_memory.md` says every memory write needs at least one entity id: `user_id`, `agent_id`, `app_id`, or `run_id`.
- `mem0/partition_memories_by_entity.md` shows why filtering only by `user_id` leaks memories across agents or workflows, and recommends explicit `user_id`, `agent_id`, `app_id`, and `run_id`.
- `mem0/build_a_companion_with_Mem0.md` separates recent chat context from long-term memory and says not to send every message to memory.
- `mem0/control_memory_ingestion.md` recommends conservative ingestion rules, confidence thresholds, updates instead of duplicates, and consistent `infer` mode per data source.
- `mem0/search_memory.md` is empty, so search policy still needs to be designed locally.

Current factory-agent behavior:

- `MemoryManager.build_planner_context` loads recent messages from the same session and can retrieve vector memories, then places only retrieved hits into planner context.
- `SqlVectorStore` already has `session`, `user`, and `global` reusable scopes, but the default `index_message` scope is `session`.
- `VectorMemory` stores `session_id`, `user_id`, `memory_type`, `memory_metadata`, `reusable_scope`, and `expires_at`.
- `WorkflowCheckpoint` stores runtime state by `thread_id`, `session_id`, `user_id`, and `expires_at`.
- Session delete already removes session-owned `VectorMemory` and `WorkflowCheckpoint` rows.
- LangGraph checkpointing stores native checkpoint payloads in `workflow_checkpoints`, with `session_id=thread_id` and a fixed 30 day expiry.

The main architecture gap is not that deletion is absent. The gap is that the names and interfaces blur "runtime recovery state" and "memory". That makes stale state look like reusable conversation memory.

## Definitions

### Runtime State

Runtime state is the live execution snapshot for one active chat run. It is used for pause, cancel, retry, approval resume, graph checkpoint recovery, and crash recovery.

Rules:

- Scope: one `session_id` and one active graph `thread_id`.
- Lifetime: only while the chat run is active, paused, waiting approval, or within a short recovery TTL.
- Prompt use: never injected as human memory. Only restored through typed recovery logic.
- Deletion: delete when the chat session is deleted. Expire after recovery TTL.
- Examples: current step, ledger revision, pending approval id, staged writes, tool outputs, graph checkpoint pointer.

### Short-Term Memory

Short-term memory is the conversation memory inside one chat thread. It lets the assistant understand follow-up messages such as "now show its slots" without dumping the whole chat.

Rules:

- Scope: one `session_id`.
- Lifetime: the chat lifetime, optionally compacted as the chat grows.
- Prompt use: small recency window plus targeted summaries.
- Deletion: delete with the chat session.
- Examples: recent user/assistant turns, compacted same-chat summary, unresolved questions, entities mentioned in this chat.

### Long-Term Memory

Long-term memory is durable, reusable knowledge about a user, tenant, factory, agent role, or recurring workflow. It is retrieved by search only when relevant.

Rules:

- Scope: `tenant_id/app_id`, `user_id`, `agent_id`, optional `run_id`, and memory bucket.
- Lifetime: weeks to permanent depending on retention policy.
- Prompt use: only retrieved snippets that pass relevance, safety, and freshness gates.
- Deletion: user, tenant, app, run, and memory-id deletion must be supported.
- Examples: user communication preferences, plant naming conventions, recurring constraints, stable machine policy preferences, approved operating assumptions.

## Target Module Design

### 1. RuntimeState Module

Interface:

- `save_runtime_state(session_id, thread_id, state, ttl)`
- `load_runtime_state(session_id, thread_id)`
- `clear_runtime_state(session_id, reason)`
- `mark_paused(session_id, checkpoint_id)`
- `resume_from_checkpoint(session_id, checkpoint_id)`

Implementation:

- Keep using `WorkflowCheckpoint` for graph-native recovery.
- Add explicit metadata: `state_scope="runtime"`, `state_status`, `paused_at`, `cancelled_at`, `recovery_until`, `cleared_reason`.
- Do not expose runtime state to planner prompts through general memory retrieval.
- On successful completion, retain only an audit projection if needed. Clear live recovery state after the recovery window.

Depth:

- Callers ask for recovery operations, not raw checkpoint rows.
- The module owns TTL, state status transitions, stale checkpoint cleanup, and graph checkpoint delete.

### 2. ConversationMemory Module

Interface:

- `append_turn(session_id, message)`
- `recent_turns(session_id, limit)`
- `compact_session(session_id, before_message_id)`
- `search_session(session_id, query, filters)`
- `delete_session_memory(session_id)`

Implementation:

- Keep `Message` rows as the canonical chat transcript.
- Store compacted summaries as `VectorMemory(memory_type="chat_summary", reusable_scope="session")`.
- Store extracted same-chat entities as `VectorMemory(memory_type="chat_entity", reusable_scope="session")`.
- Recent window should remain bounded, for example last 12 to 24 planner-visible messages.
- Compact old turns into typed summary sections: goals, entities, decisions, open questions, failed tools, approvals.

Depth:

- The planner asks for "conversation context", not all messages.
- The module decides the blend of recent turns, summaries, and searched same-chat memory.

### 3. LongTermMemory Module

Interface:

- `ingest_candidate(memory_candidate)`
- `search_relevant(query, scope, budget)`
- `update_memory(memory_id, replacement, reason)`
- `delete_memory(memory_id)`
- `delete_scope(scope)`
- `audit_scope(scope)`

Implementation options:

- Near term: extend current `VectorMemory` table with enterprise fields and real embeddings.
- Later: add a Mem0 adapter implementing the same interface.
- Use Mem0-style identifiers on every memory: `tenant_id/app_id`, `user_id`, `agent_id`, optional `run_id`.
- Use stable metadata, not AI-only categories, for guaranteed filters.
- Suggested memory buckets: `preference`, `factory_policy`, `entity_alias`, `workflow_pattern`, `constraint`, `safety_note`, `user_profile`, `agent_behavior`, `temporary_fact`.

Depth:

- Planner code should not know whether memory comes from SQL vectors, Chroma, Qdrant, or Mem0.
- The retrieval interface owns filters, ranking, freshness, dedupe, and prompt budget.

### 4. MemoryRouter Module

Interface:

- `build_context_pack(session_id, user_id, agent_id, app_id, intent, mode)`

Implementation:

The router returns a typed context pack:

```json
{
  "runtime_recovery": {
    "status": "paused",
    "checkpoint_id": "..."
  },
  "short_term": {
    "recent_turns": [],
    "session_summaries": [],
    "session_hits": []
  },
  "long_term": {
    "hits": [],
    "omitted": []
  },
  "prompt_budget": {
    "recent_turn_tokens": 1200,
    "short_term_tokens": 800,
    "long_term_tokens": 800
  }
}
```

Rules:

- Runtime recovery data is not blended into memory text.
- Short-term memory is always session-scoped.
- Long-term memory is searched only if the intent classifier says it may help.
- Each included memory must include `source`, `scope`, `score`, `reason_included`, and `expires_at`.

## Scope Model

Every memory row should answer these questions:

- Who owns it: `tenant_id`, `user_id`
- Which product/app can use it: `app_id`
- Which agent role can use it: `agent_id`
- Which temporary workflow owns it: `run_id`
- Which chat created it: `source_session_id`
- What kind of memory it is: `memory_type`, `memory_bucket`
- How long it lives: `expires_at`, `retention_policy`
- Whether it can enter a prompt: `prompt_eligible`
- Whether it contains sensitive data: `pii_redacted`, `sensitivity`

Recommended mapping:

| Concept | Field | Example |
| --- | --- | --- |
| Enterprise tenant | `tenant_id` or `app_id` | `emas_factory_demo` |
| User profile | `user_id` | `operator_123` |
| Agent role | `agent_id` | `factory_planner_v2` |
| Single chat | `session_id` or `source_session_id` | chat uuid |
| Single workflow | `run_id` | approval bundle uuid |
| Memory class | `memory_bucket` | `factory_policy` |
| Runtime recovery | `thread_id` | graph thread uuid |

Important rule: never retrieve long-term memory with `user_id` alone. Minimum production filter should include `tenant_id/app_id` and `agent_id`; add `run_id` for workflow-isolated data.

## Prompt Assembly Policy

Do not dump memory into the LLM prompt. Build a small context pack:

1. Current user request.
2. Current system and tool constraints.
3. Recent same-chat turns, capped.
4. Same-chat summary or session search hits, capped.
5. Long-term memory search hits, capped.
6. Explicit citation block for every memory item used.

Suggested default limits:

- Recent turns: max 12 turns or 1200 tokens.
- Short-term summary and same-chat search: max 5 items or 800 tokens.
- Long-term memory: max 5 items or 800 tokens.
- Hard total memory budget: max 25 percent of prompt context.

Retrieval gates:

- Must match scope filter.
- Must pass minimum score.
- Must not be expired.
- Must be prompt eligible.
- Must pass sensitivity policy.
- Must have a reason to include for this intent.
- Must dedupe against recent turns.

## Ingestion Policy

Not everything should become long-term memory.

Candidate extraction should run after the assistant response or after a completed workflow, not in the middle of fragile execution. Each candidate should include:

- `content`
- `memory_bucket`
- `scope`
- `confidence`
- `source_session_id`
- `source_message_ids`
- `expires_at`
- `ingestion_reason`
- `review_required`

Store long-term memory only when one of these is true:

- The user explicitly says to remember it.
- It is a stable preference or factory convention.
- It is a recurring workflow decision.
- It is a durable alias or entity mapping.
- It is a safety or compliance note approved for reuse.

Do not store:

- One-off tool results.
- Runtime execution state.
- Speculation.
- Raw approvals or staged write payloads.
- Sensitive data unless policy allows it and it is redacted or protected.
- Failed intermediate thoughts.

Use updates rather than duplicates for the same fact. Use `infer=True` or equivalent conflict resolution for natural conversation facts; use `infer=False` only for curated imports in a separate scope.

## Deletion And Retention

Session delete:

- Delete `Message`.
- Delete `VectorMemory` where `session_id` or `source_session_id` matches the chat.
- Delete `WorkflowCheckpoint` where `session_id` or `thread_id` matches the chat.
- Keep only audit logs required by business policy, with prompt eligibility false.

Cancel:

- Mark runtime state cancelled.
- Clear pending approval resume pointers.
- Keep a short recovery/audit TTL if needed.
- Do not promote cancelled runtime state into long-term memory.

Pause:

- Keep runtime state with `state_status="paused"`.
- Store resume pointer and expiry.
- Show paused state in UI as recoverable state, not memory.

Completion:

- Clear live runtime state after a short recovery window.
- Extract candidate long-term memories only from final, user-visible, stable facts.
- Keep short-term chat transcript and compacted same-chat summaries.

Long-term deletion:

- Delete by `memory_id`.
- Delete by `user_id`.
- Delete by `app_id/tenant_id`.
- Delete by `run_id`.
- Delete by `source_session_id`.

## Enterprise Controls

Security:

- Tenant/app scoped filters are mandatory.
- User isolation is mandatory.
- Agent role isolation is mandatory for behavior/personality memories.
- Memory access should be authorized the same way session access is authorized.

Compliance:

- Every long-term memory needs provenance: source session, message ids, created by, ingestion reason.
- Every retrieval should be logged with query, filters, returned ids, scores, and prompt inclusion decision.
- Support export and delete by user, tenant/app, and run.

Observability:

- Track retrieval empty rate, retrieval inclusion rate, stale-hit rate, low-score-hit rate, and memory-write rejection reasons.
- Add dashboards for memory growth by bucket and scope.

Testing:

- Cross-session leak tests.
- Cross-user leak tests.
- Cross-agent leak tests.
- Same-chat follow-up tests.
- Cancel and pause recovery tests.
- Memory deletion cascade tests.
- Prompt budget tests.
- Memory contradiction/update tests.

## Recommended Implementation Phases

### Phase 1: Rename And Separate Interfaces

- Split `MemoryManager` into `RuntimeStateStore`, `ConversationMemory`, `LongTermMemory`, and `MemoryRouter`.
- Keep the current SQL tables initially.
- Make `build_planner_context` return a typed context pack.
- Remove generic `checkpoint_state` from planner memory context and move it under `runtime_recovery`.

### Phase 2: Fix Scope And Schema

- Add `tenant_id/app_id`, `agent_id`, `run_id`, `source_session_id`, `memory_bucket`, `prompt_eligible`, `sensitivity`, `confidence`, and `ingestion_reason` to memory storage.
- Add runtime checkpoint metadata: `state_scope`, `state_status`, `recovery_until`, `cleared_reason`.
- Ensure all session deletion paths clear both session vectors and runtime checkpoints.

### Phase 3: Retrieval-Only Prompt Memory

- Implement `search_relevant` with required filters and budgets.
- Use real embeddings instead of hashed vectors for long-term memory.
- Keep same-chat recent turns separate from long-term memory hits.
- Add prompt inclusion reasons and retrieval audit rows.

### Phase 4: Mem0 Adapter

- Add `Mem0LongTermMemoryAdapter` behind the `LongTermMemory` interface.
- Map fields:
  - `user_id` to user owner.
  - `agent_id` to factory agent role.
  - `app_id` to tenant/app.
  - `run_id` to workflow or temporary memory scope.
  - metadata to bucket, source session, confidence, expiry, sensitivity.
- Keep current SQL adapter for local dev and tests.

### Phase 5: Governance And UI

- Add memory inspection UI for admins and users.
- Add "remember this", "forget this", and "do not use memory for this chat" controls.
- Add retention policy jobs.
- Add audit export.

## Deepening Opportunities

1. Runtime state store
   - Files: `factory_agent/orchestration/memory_manager.py`, `factory_agent/memory/checkpoint.py`, `factory_agent/graph/checkpointing.py`
   - Problem: runtime recovery and memory retrieval share a manager name and storage table vocabulary.
   - Solution: create a dedicated runtime state module with pause, cancel, resume, and clear operations.
   - Benefits: better locality for recovery logic and less chance of stale state leaking into prompt context.

2. Conversation memory module
   - Files: `factory_agent/orchestration/memory_manager.py`, `factory_agent/persistence/models.py`
   - Problem: same-chat history, compaction summaries, and vector search are handled as one generic memory path.
   - Solution: make same-chat context a first-class module with recent turns, compacted summaries, and session-only search.
   - Benefits: follow-ups work without dumping transcripts, and deletion stays session-local.

3. Long-term memory adapter
   - Files: `factory_agent/memory/vector_store.py`, `factory_agent/persistence/models.py`, future Mem0 adapter
   - Problem: current vector memory can technically use `user` and `global` scopes, but lacks enterprise filters and ingestion policy.
   - Solution: add a long-term memory interface and adapter with strict scope filters, provenance, retention, and prompt gates.
   - Benefits: callers gain leverage from one retrieval interface while storage can evolve from SQL vectors to Mem0 or Qdrant.

4. Memory router
   - Files: `factory_agent/services/plan_creation_service.py`, `factory_agent/services/planner_owned_graph_runtime.py`
   - Problem: context assembly is spread across plan creation, graph runtime, session replan context, and memory manager.
   - Solution: centralize context pack assembly in a router that returns typed runtime, short-term, and long-term sections.
   - Benefits: one test surface for prompt budget, memory safety, and cross-session isolation.

