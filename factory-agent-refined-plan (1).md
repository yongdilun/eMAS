# 🏭 Factory Operations Agent — Final Hardened Architecture Plan
> Version 3.0 — Production-Complete Blueprint

---

## 0. Document Purpose

This document is the complete, final architecture blueprint. It covers:
- **LLM prompt contract** (exact schema, context, validation, tool scoping)
- **Session & conversation model** (lifecycle, multi-turn, mid-execution changes)
- **Error decision tree** (replan vs. retry vs. fail vs. DLQ)
- **Service-to-service auth** (Go ↔ FastAPI)
- **tools.md regeneration triggers + capability scoping**
- **Plan validation rules** (dependency graph, parallel steps)
- **Exactly-once execution guarantee** (strong idempotency contract)
- **Dead Letter Queue** (no silent failures)
- **Rate limiting & cost control** (hard session limits)
- **Plan explainability** (operator-readable plan descriptions)
- **Cold start recovery** (startup sweep for stuck sessions)
- **Backpressure handling** (session queue + worker pool)

---

## 1. System Overview

```
User (Browser/API Client)
   │
   ▼
FastAPI Agent Server
   ├── Session Queue              ← backpressure: cap concurrent sessions
   ├── Worker Pool                ← N async workers pulling from queue
   ├── Session Manager            ← lifecycle, cold start recovery
   ├── Agent Orchestrator         ← state machine + agentic loop
   │     ├── Planner              ← LLM plan generation
   │     │     └── Tool Scope Filter ← filters tools to intent before LLM call
   │     ├── Plan Validator       ← schema + safety + dependency validation
   │     ├── Execution Engine     ← transactional, exactly-once execution
   │     └── Memory Manager      ← working / compact / persistent
   ├── Approval Gateway           ← human-in-the-loop
   ├── Rate Limiter               ← hard limits per session
   ├── DLQ Manager                ← dead letter queue for failed sessions
   └── Tool Registry              ← versioned + scoped tool definitions
         │
         ▼
   Go Backend API (CRUD + OpenAPI 3.0)
         └── Strong Idempotency Store ← payload hash → response cache
         │
         ▼
   Postgres (canonical state + DLQ + audit)
   Redis   (events, pub/sub, resume triggers, idempotency cache)
```

---

## 2. Core Principles

| Principle | Rule |
|---|---|
| No double execution | Every step has idempotency key + payload hash, checked before execution |
| Exactly-once guarantee | Non-strongly-idempotent tools disable retry entirely |
| No memory-only state | All state written to DB before returning |
| Transactional execution | Step status transitions happen inside DB transactions |
| Approval-gated writes | All POST/PATCH/DELETE require approval record |
| Versioned tools | Tool + schema version stored on every ExecutionSnapshot |
| Crash recovery | On restart, startup sweep resumes stuck sessions |
| LLM is untrusted | All LLM output is schema-validated before execution |
| Auth is layered | User auth (JWT) + service auth (API key) are separate |
| Bounded execution | Hard limits on steps, replans, LLM calls, and duration per session |
| No silent failure | Failed/blocked sessions always land in DLQ with full context |
| Backpressure enforced | Session queue caps concurrency; excess requests wait or are rejected |

---

## 3. Data Models (Complete)

### 3.1 Session

```python
class Session:
    session_id: UUID
    user_id: str
    status: SessionStatus          # IDLE | PLANNING | WAITING_APPROVAL | EXECUTING | BLOCKED | FAILED | COMPLETED
    
    # Conversation
    messages: List[Message]        # full conversation history (persisted)
    current_intent: str            # current user goal (extracted by LLM)
    
    # Plan
    plan_id: Optional[UUID]
    plan_version: int              # increments on replan
    plan_hash: str                 # SHA256 of plan JSON
    
    # Execution
    current_step_index: int
    retry_count: int

    # Rate limiting counters
    step_count: int                # total steps executed this session
    replan_count: int              # number of replans triggered
    llm_call_count: int            # total LLM calls made
    session_started_at: datetime   # for duration enforcement
    
    # Metadata
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    error: Optional[str]
    version: int                   # optimistic lock
```

### 3.2 Message

```python
class Message:
    message_id: UUID
    session_id: UUID
    role: Literal["user", "assistant", "system", "tool_result"]
    content: str
    
    # If role == "tool_result"
    step_id: Optional[UUID]
    tool_name: Optional[str]
    
    created_at: datetime
```

### 3.3 Plan

```python
class Plan:
    plan_id: UUID
    session_id: UUID
    version: int                   # 1, 2, 3... increments on replan
    
    steps: List[PlanStep]
    dependency_graph: Dict[int, List[int]]   # step_index → [depends_on_step_index]
    parallel_groups: List[List[int]]         # steps that can run concurrently
    
    plan_hash: str

    # Explainability
    plan_explanation: str          # LLM-generated plain-English: what each step does and why
    risk_summary: str              # LLM-generated: what's irreversible, what could go wrong

    created_at: datetime
    created_by: Literal["llm", "human_edit"]
    invalidated_at: Optional[datetime]
    invalidated_reason: Optional[str]
```

### 3.4 PlanStep (Extended)

```python
class PlanStep:
    step_id: UUID
    plan_id: UUID
    step_index: int                # ordering within plan
    
    tool_name: str
    args: dict                     # validated against tool schema
    
    status: StepStatus
    # NOT_STARTED | IN_PROGRESS | DONE | FAILED | SKIPPED | AMBIGUOUS
    # AMBIGUOUS = request was sent but result unknown (network timeout on non-idempotent tool)
    
    idempotency_key: str           # SHA256(session_id + step_index + plan_version + args)
    requires_approval: bool
    approval_id: Optional[UUID]
    
    # Retry
    retry_count: int
    max_retries: int
    last_error: Optional[str]
    
    # Result
    result: Optional[dict]
    result_summary: Optional[str]  # LLM-generated human-readable summary
    
    # Audit
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
```

### 3.5 Tool (Extended)

```python
class Tool:
    tool_id: UUID
    name: str
    description: str               # shown to LLM in tools.md
    
    endpoint: str
    method: HttpMethod             # GET | POST | PATCH | DELETE
    
    version: int
    schema_version: int
    input_schema: dict             # JSON Schema
    output_schema: dict            # JSON Schema
    
    is_read_only: bool
    requires_approval: bool
    side_effect_level: SideEffectLevel   # NONE | LOW | HIGH | CRITICAL
    
    is_concurrency_safe: bool
    is_idempotent: bool

    # Strong idempotency: backend stores (key + request_hash) → response
    # and returns deterministic result on replay.
    # If False: retry is DISABLED for this tool (too risky to re-execute)
    is_strongly_idempotent: bool

    # Capability tags for tool scoping — used to filter tools before LLM prompt
    # e.g. ["machine", "status"] or ["maintenance", "schedule"]
    capability_tags: List[str]
    
    # Version compatibility
    deprecated_at: Optional[datetime]
    replacement_tool: Optional[str]
    
    created_at: datetime
    updated_at: datetime
```

### 3.6 Approval (Extended)

```python
class Approval:
    approval_id: UUID
    session_id: UUID
    step_id: UUID
    
    tool_name: str
    args: dict
    risk_summary: str              # LLM-generated: "This will delete machine #42"
    side_effect_level: SideEffectLevel
    
    status: ApprovalStatus         # PENDING | APPROVED | REJECTED | EXPIRED
    
    # Expiry
    expires_at: datetime           # default: 24 hours
    
    # Decision
    decided_by: Optional[str]      # user_id
    decided_at: Optional[datetime]
    rejection_reason: Optional[str]
    
    created_at: datetime
```

### 3.7 ExecutionSnapshot (Audit Trail)

```python
class ExecutionSnapshot:
    snapshot_id: UUID
    step_id: UUID
    session_id: UUID
    
    # What was called
    tool_name: str
    tool_version: int
    schema_version: int
    input_args: dict
    
    # Context at time of execution
    plan_hash: str
    plan_version: int
    idempotency_key: str
    
    # Result
    http_status: int
    response_body: dict
    latency_ms: int
    
    # Timestamps
    executed_at: datetime
```

### 3.8 DeadLetter

```python
class DeadLetter:
    dlq_id: UUID
    session_id: UUID
    step_id: Optional[UUID]        # None if failure was at planning level

    failure_type: Literal[
        "max_retries_exceeded",
        "replan_limit_reached",
        "unrecoverable_error",
        "rate_limit_exceeded",
        "session_timeout",
        "validation_failure",
        "ambiguous_execution"      # sent but result unknown
    ]
    reason: str                    # human-readable explanation
    payload: dict                  # full context: args, last error, step state

    # Resolution tracking
    status: Literal["PENDING", "REPLAYED", "DISMISSED", "ESCALATED"]
    replayed_at: Optional[datetime]
    replayed_by: Optional[str]     # ops user_id
    dismissed_at: Optional[datetime]
    dismissed_reason: Optional[str]

    created_at: datetime
```

---

## 4. LLM Prompt Contract

This is the most important section. The LLM is the planner only — it never executes directly.

### 4.0 Tool Scope Filter (runs before every LLM call)

Before building the prompt, filter tools to only those relevant to the user's intent.
This reduces prompt size, improves plan accuracy, and prevents the LLM from choosing irrelevant tools.

```python
def select_relevant_tools(intent: str, all_tools: List[Tool]) -> List[Tool]:
    """
    Strategy 1 (start here, <50 tools):
        Keyword match intent against tool.capability_tags + tool.description.
        Return tools where at least 1 tag or keyword matches.

    Strategy 2 (upgrade path, >50 tools):
        Embed intent + tool descriptions using pgvector.
        Return top-K by cosine similarity.

    Always include:  read-only tools, tools with side_effect_level=NONE
    Always exclude:  deprecated tools, unrelated domain tools
    """
    keywords = extract_keywords(intent)
    scored = []
    for tool in all_tools:
        if tool.deprecated_at:
            continue
        score = keyword_overlap(keywords, tool.capability_tags + [tool.description])
        always_include = tool.is_read_only or tool.side_effect_level == "NONE"
        if score > 0 or always_include:
            scored.append((score, tool))
    scored.sort(reverse=True)
    return [t for _, t in scored[:MAX_TOOLS_IN_PROMPT]]

MAX_TOOLS_IN_PROMPT = 30   # above this, switch to RAG retrieval
```

### 4.1 System Prompt Template

```
You are a Factory Operations Agent planner.
Your job is to convert a user request into a structured execution plan.

## Available Tools (pre-filtered for this request)
{filtered_tools_md}

## Rules
1. Only use tools listed above. Never invent tool names.
2. Your output MUST be valid JSON matching the PlanSchema below.
3. Steps must be ordered. If step B depends on step A's output, set dependency.
4. Mark steps that can run in parallel in parallel_group (same group number).
5. Any POST/PATCH/DELETE step MUST have requires_approval: true.
6. If the request is ambiguous, set needs_clarification: true and list questions.
7. If the request is impossible with available tools, set is_feasible: false.
8. Provide plan_explanation: plain-English description of what this plan does,
   step by step, written for a non-technical factory operator.
9. Provide risk_summary: what actions are irreversible, what could go wrong.

## Session Context
- Session ID: {session_id}
- Completed steps this session: {action_history_summary}
- Relevant factory state: {relevant_context}

## Limits
- Max steps in plan: 20
- Do not duplicate tool+args combinations

## Output (STRICT JSON only — no markdown, no explanation outside JSON)
{plan_json_schema}
```

### 4.2 Plan JSON Schema (LLM Output Contract)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema",
  "type": "object",
  "required": ["is_feasible", "needs_clarification", "steps", "plan_explanation", "risk_summary"],
  "properties": {
    "is_feasible": { "type": "boolean" },
    "infeasibility_reason": { "type": "string" },
    
    "needs_clarification": { "type": "boolean" },
    "clarification_questions": {
      "type": "array",
      "items": { "type": "string" }
    },
    
    "intent_summary": {
      "type": "string",
      "description": "One sentence: what this plan accomplishes"
    },

    "plan_explanation": {
      "type": "string",
      "description": "Plain-English step-by-step explanation written for a non-technical operator"
    },

    "risk_summary": {
      "type": "string",
      "description": "What actions are irreversible, what could go wrong"
    },
    
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["step_index", "tool_name", "args", "requires_approval", "description"],
        "properties": {
          "step_index": { "type": "integer", "minimum": 0 },
          "tool_name": { "type": "string" },
          "args": { "type": "object" },
          "description": { "type": "string" },
          "requires_approval": { "type": "boolean" },
          "depends_on": {
            "type": "array",
            "items": { "type": "integer" },
            "description": "step_index values this step depends on"
          },
          "parallel_group": {
            "type": "integer",
            "description": "Steps with same group number can run concurrently"
          }
        }
      }
    }
  }
}
```

### 4.3 LLM Output Validation Pipeline

```
LLM Response
    │
    ├─ 1. JSON parse (hard fail if invalid JSON)
    │
    ├─ 2. Schema validation (jsonschema library)
    │       └── fail → PlanValidationError (do NOT retry LLM automatically)
    │
    ├─ 3. Tool name check (every tool_name must exist in DB registry)
    │       └── fail → PlanValidationError with unknown_tools list
    │
    ├─ 4. Arg schema check (each step args validated against tool.input_schema)
    │       └── fail → PlanValidationError with field-level errors
    │
    ├─ 5. Dependency cycle check (topological sort)
    │       └── fail → PlanValidationError
    │
    ├─ 6. Destructive action approval check
    │       └── any POST/PATCH/DELETE with requires_approval=false → auto-correct to true + warn
    │
    └─ 7. Feasibility check
            └── is_feasible=false → return clarification to user, do not create plan
```

### 4.4 LLM Retry on Plan Failure

```
Max LLM replan attempts: 3

Attempt 1: original prompt
Attempt 2: original prompt + "Previous plan had errors: {validation_errors}. Fix them."
Attempt 3: original prompt + all previous errors + "Be very careful about tool names and schema."

After 3 failures:
    session.state = BLOCKED
    push_to_dlq(session, failure_type="validation_failure")
    notify user with error details
```

---

## 5. Session Lifecycle (Complete)

### 5.1 Session States + Transitions

```
                    ┌─────────────────────────────┐
                    │                             │
              user_message                  replan_triggered
                    │                             │
                    ▼                             │
   IDLE ──────► PLANNING ◄────────────────────────┘
                    │
             plan_generated &
             validated
                    │
                    ▼
          WAITING_APPROVAL ◄──────────────── EXECUTING
                    │                           ▲    │
             approval_received                  │    │
                    │                    step_done   step_failed (retryable)
                    ▼                           │    │
              EXECUTING ────────────────────────┘    │
                    │                                │
             all_steps_done              max_retries_exceeded
                    │                          OR
                    ▼                    unrecoverable_error
              COMPLETED                         │
                                                ▼
                                             FAILED
                                                │
                                        user_provides_fix
                                                │
                                                ▼
                                           PLANNING (replan)
```

### 5.2 Mid-Execution User Message Handling

This is a critical edge case. Three scenarios:

**Scenario A: User adds information (safe)**
```
e.g. "also update the maintenance schedule while you're at it"

→ If session.state == WAITING_APPROVAL:
    → Append to session.messages
    → Trigger replan (increment plan_version)
    → New plan replaces old, DONE steps are preserved

→ If session.state == EXECUTING:
    → Pause after current step completes
    → Trigger replan
```

**Scenario B: User cancels (safe)**
```
e.g. "stop, don't do this"

→ Any state: immediately set session.state = IDLE
→ Mark all NOT_STARTED steps as SKIPPED
→ Do NOT rollback DONE steps (log warning to user)
→ Notify user: "Stopped. X steps were already completed and cannot be undone."
```

**Scenario C: User contradicts in-progress step (dangerous)**
```
e.g. "actually use machine #10 not machine #5" while step is IN_PROGRESS

→ Queue the message, do NOT interrupt the in-flight API call
→ After step completes/fails: surface conflict to user
→ Ask: "Step already ran with machine #5. Do you want to replan with machine #10?"
```

---

## 6. Agentic Loop (Production Version)

```python
# Hard limits enforced throughout the loop
SESSION_LIMITS = {
    "MAX_STEPS_PER_SESSION":   20,
    "MAX_REPLANS":              3,
    "MAX_LLM_CALLS":           10,
    "MAX_SESSION_DURATION_S": 600,   # 10 minutes
}

async def run_agent(session_id: UUID):
    session = await db.get_session_with_lock(session_id)

    # ── Rate limit check (runs at every entry point) ──────────────────
    duration_s = (datetime.utcnow() - session.session_started_at).total_seconds()
    if (session.step_count    >= SESSION_LIMITS["MAX_STEPS_PER_SESSION"] or
        session.replan_count  >= SESSION_LIMITS["MAX_REPLANS"]           or
        session.llm_call_count >= SESSION_LIMITS["MAX_LLM_CALLS"]        or
        duration_s            >= SESSION_LIMITS["MAX_SESSION_DURATION_S"]):
        reason = identify_limit_hit(session, duration_s)
        session.state = SessionState.FAILED
        session.error = f"Session limit exceeded: {reason}"
        await db.save(session)
        await push_to_dlq(session, failure_type="rate_limit_exceeded", reason=reason)
        await notify_user(session, f"Session stopped: {reason}. Start a new session to continue.")
        return

    # --- PLANNING ---
    if session.state == SessionState.PLANNING:
        relevant_tools = select_relevant_tools(session.current_intent, tool_registry.all())
        context = await build_llm_context(session, tools=relevant_tools)

        session.llm_call_count += 1
        await db.save(session)
        plan_result = await llm_generate_plan(context, attempt=1)
        
        # LLM validation loop (max 3 attempts)
        for attempt in range(1, 4):
            errors = validate_plan(plan_result)
            if not errors:
                break
            if attempt == 3:
                session.state = SessionState.BLOCKED
                session.error = f"Plan generation failed after 3 attempts: {errors}"
                await db.save(session)
                await push_to_dlq(session,
                    failure_type="validation_failure",
                    reason=f"LLM produced invalid plan 3 times: {errors}")
                await notify_user(session, "Planning failed. Please rephrase your request.")
                return
            session.llm_call_count += 1
            await db.save(session)
            plan_result = await llm_generate_plan(context, attempt=attempt+1, prior_errors=errors)
        
        # Handle infeasible / needs clarification
        if not plan_result.is_feasible:
            await send_message(session, plan_result.infeasibility_reason)
            session.state = SessionState.IDLE
            await db.save(session)
            return
        
        if plan_result.needs_clarification:
            await send_message(session, plan_result.clarification_questions)
            session.state = SessionState.IDLE
            await db.save(session)
            return
        
        plan = await persist_plan(session, plan_result)
        session.plan_id = plan.plan_id
        session.state = SessionState.WAITING_APPROVAL
        await db.save(session)
        # plan_explanation and risk_summary are part of plan shown in approval UI
        await notify_user(session, "Plan ready for review", plan=plan)
        return

    # --- EXECUTION LOOP ---
    while True:
        # Rate check inside loop too
        duration_s = (datetime.utcnow() - session.session_started_at).total_seconds()
        if (session.step_count >= SESSION_LIMITS["MAX_STEPS_PER_SESSION"] or
            duration_s >= SESSION_LIMITS["MAX_SESSION_DURATION_S"]):
            reason = identify_limit_hit(session, duration_s)
            session.state = SessionState.FAILED
            await db.save(session)
            await push_to_dlq(session, failure_type="rate_limit_exceeded", reason=reason)
            return

        step = await next_executable_step(session)
        
        if step is None:
            session.llm_call_count += 1
            summary = await llm_summarize_execution(session)
            session.state = SessionState.COMPLETED
            await db.save(session)
            await notify_user(session, summary)
            return
        
        if step.status == StepStatus.DONE:
            continue
        
        tool = await tool_registry.get(step.tool_name)
        
        # Approval gate
        if step.requires_approval and not step.approval_id:
            session.llm_call_count += 1
            risk_summary = await llm_generate_risk_summary(step, tool)
            approval = await create_approval(session, step, risk_summary)
            step.approval_id = approval.approval_id
            session.state = SessionState.WAITING_APPROVAL
            await db.save_all(session, step)
            await notify_user(session, "Approval required", approval=approval)
            return
        
        if step.approval_id:
            approval = await db.get_approval(step.approval_id)
            if approval.status == ApprovalStatus.PENDING:
                session.state = SessionState.WAITING_APPROVAL
                await db.save(session)
                return
            if approval.status == ApprovalStatus.REJECTED:
                step.status = StepStatus.SKIPPED
                await db.save(step)
                await handle_rejection(session, step, approval)
                return
            if approval.status == ApprovalStatus.EXPIRED:
                await re_request_approval(session, step)
                return
        
        # Execute with transaction (exactly-once guard)
        async with db.transaction():
            await db.lock_step(step.step_id)
            if step.status == StepStatus.DONE:
                continue
            step.status = StepStatus.IN_PROGRESS
            step.started_at = datetime.utcnow()
            await db.save(step)
        
        try:
            result = await execute_tool(step, tool)   # see Section 19 for exactly-once logic
            
            async with db.transaction():
                step.status = StepStatus.DONE
                step.result = result
                step.completed_at = datetime.utcnow()
                session.step_count += 1
                await db.save_all(step, session)
                await persist_snapshot(step, result)
        
        except Exception as e:
            await handle_step_error(session, step, tool, e)
            if session.state in (SessionState.FAILED, SessionState.BLOCKED):
                await push_to_dlq(session,
                    step_id=step.step_id,
                    failure_type="max_retries_exceeded",
                    reason=str(e),
                    payload={"args": step.args, "last_error": str(e)})
                return
```

---

## 7. Error Decision Tree

```
Step raises exception
        │
        ▼
Classify error
        │
        ├── NetworkError / TimeoutError
        │         │
        │         └── tool.is_strongly_idempotent AND retry_count < max_retries?
        │                   ├── YES → exponential backoff retry
        │                   └── NO  → if sent: mark AMBIGUOUS → DLQ
        │                             if not sent: REPLAN
        │
        ├── HTTP 400 Bad Request  → REPLAN (LLM sent wrong args)
        ├── HTTP 401 Unauthorized → FAIL HARD → DLQ (auth, needs human fix)
        ├── HTTP 403 Forbidden    → FAIL HARD → DLQ (permission issue)
        ├── HTTP 404 Not Found    → REPLAN (resource doesn't exist, LLM used wrong ID)
        ├── HTTP 409 Conflict     → REPLAN (state conflict, re-read state first)
        ├── HTTP 5xx              → retry up to max_retries (if strongly idempotent) → REPLAN
        ├── SchemaValidationError → REPLAN immediately (no retry — same args will fail again)
        └── UnknownError          → FAIL HARD → DLQ

REPLAN trigger:
    1. Mark current step as FAILED
    2. Build replan context: original intent + completed steps + failed step + error
    3. LLM generates new plan (modifies remaining steps only; DONE steps never re-executed)
    4. Increment plan_version; increment session.replan_count
    5. If session.replan_count >= MAX_REPLANS:
           session.state = BLOCKED
           push_to_dlq(failure_type="replan_limit_reached")

FAIL HARD trigger:
    1. session.state = FAILED
    2. push_to_dlq(session, step, failure_type, reason)
    3. notify_user with actionable message
```

---

## 8. Service-to-Service Auth

### 8.1 Auth Layers

```
Layer 1: User → FastAPI
    Method: JWT (Bearer token)
    Issued by: Auth service (or FastAPI itself)
    Contains: user_id, roles, session_id
    Expiry: 1 hour (refresh token: 7 days)

Layer 2: FastAPI Agent → Go Backend API
    Method: API Key (X-Service-Key header)
    Issued by: Go backend (static, per-environment)
    Stored in: FastAPI env vars / secrets manager
    Rotation: manual (quarterly) or via secrets manager auto-rotation

Layer 3: Go Backend → Postgres/Redis
    Method: Connection string with credentials
    Stored in: environment variables / secrets manager
```

### 8.2 Request Flow with Auth

```
User (JWT) → FastAPI
    FastAPI validates JWT → extracts user_id
    FastAPI calls Go API with:
        X-Service-Key: {api_key}
        X-User-ID: {user_id}        ← forwarded for audit logging
        Idempotency-Key: {key}
    Go API:
        Validates X-Service-Key
        Logs X-User-ID in audit trail
        Does NOT re-validate user JWT (service trust model)
```

### 8.3 What FastAPI Must NOT Do

```
- Never forward the user's JWT to Go backend
- Never store user credentials
- Never allow a session to call tools outside its user scope
```

---

## 9. Tools.md — Generation & Regeneration

### 9.1 Content Structure

```markdown
# Available Tools

## tool_name
**Description**: What this tool does (shown to LLM for planning)
**Method**: POST
**Endpoint**: /machines/{id}/status
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
  - id (integer, required): Machine ID
  - status (string, required): One of: ACTIVE | INACTIVE | MAINTENANCE
**Output**: Updated machine object
**Example**:
  Input:  {"id": 42, "status": "MAINTENANCE"}
  Output: {"id": 42, "status": "MAINTENANCE", "updated_at": "..."}
---
```

### 9.2 Regeneration Triggers

| Trigger | Action |
|---|---|
| Go backend deployed (CI/CD hook) | Auto-regenerate tools.md + reload tool registry |
| New endpoint added to OpenAPI spec | Detected by hash diff → regenerate |
| Tool version bumped | Regenerate + alert on breaking schema changes |
| FastAPI startup | Always regenerate if hash mismatch (safety net) |
| Manual admin command | `POST /admin/regenerate-tools` endpoint |

### 9.3 Generation Pipeline

```
Go Server starts / deploys
    │
    ▼
Export OpenAPI 3.0 spec (GET /openapi.json)
    │
    ▼
FastAPI tool_generator.py:
    1. Parse all paths + methods
    2. Map to Tool model (name, schema, method, side_effect_level)
    3. Detect breaking changes (schema diff vs DB)
       └── Breaking change → log warning + keep old version active
    4. Write to DB tool registry (upsert)
    5. Generate tools.md from DB
    6. Hash tools.md → store hash
    7. tools.md cached in memory for prompt injection
```

---

## 10. Plan Validation Rules (Complete)

### 10.1 Dependency Graph Validation

```python
def validate_dependency_graph(steps: List[PlanStep]) -> List[str]:
    errors = []
    
    # Rule 1: No self-dependency
    for step in steps:
        if step.step_index in step.depends_on:
            errors.append(f"Step {step.step_index} depends on itself")
    
    # Rule 2: No forward-only dependencies (must depend on earlier steps)
    for step in steps:
        for dep in step.depends_on:
            if dep >= step.step_index:
                errors.append(f"Step {step.step_index} depends on future step {dep}")
    
    # Rule 3: No cycles (topological sort)
    if has_cycle(steps):
        errors.append("Dependency graph contains a cycle")
    
    # Rule 4: Parallel steps must not have shared write targets
    parallel_groups = group_by_parallel_group(steps)
    for group in parallel_groups:
        targets = [extract_write_target(s) for s in group if not s.tool.is_read_only]
        if has_duplicates(targets):
            errors.append(f"Parallel group {group} has conflicting write targets")
    
    return errors
```

### 10.2 Tool Chain Safety Rules

```python
def validate_tool_chain(steps: List[PlanStep]) -> List[str]:
    errors = []
    
    # Rule 1: DELETE must never appear before a GET of same resource in same plan
    # (Ensure we read before we destroy — audit trail)
    
    # Rule 2: No two CRITICAL side-effect steps in same parallel group
    
    # Rule 3: Approval steps must not be in a parallel group with other steps
    # (Approval is a synchronization point)
    
    # Rule 4: Max 10 steps per plan (complexity guard)
    if len(steps) > 10:
        errors.append("Plan exceeds 10 steps. Break into smaller tasks.")
    
    # Rule 5: No duplicate (tool_name + args) pairs
    # (Idempotency guard at plan level)
    seen = set()
    for step in steps:
        key = f"{step.tool_name}:{json.dumps(step.args, sort_keys=True)}"
        if key in seen:
            errors.append(f"Duplicate step detected: {step.tool_name} with same args")
        seen.add(key)
    
    return errors
```

---

## 11. Memory System (Detailed)

```
Working Memory (in-process, RAM)
    Content: current session object, current step, tool registry cache
    Lifetime: request lifetime
    Max size: no limit (single session scope)

Compact Memory (DB, per session)
    Content: LLM-generated summary of completed steps
    Format:  "Completed: fetched machine list (12 machines), updated machine #5 status to MAINTENANCE"
    Updated: after every 5 steps, or after plan completion
    Used in: LLM context for replanning

Persistent Memory (DB, structured logs)
    Content: ExecutionSnapshot per step, full message history, approval records
    Retention: indefinite (configurable archive policy)
    Used in: audit, debugging, compliance
```

---

## 12. Concurrency Control (Detailed)

### 12.1 Optimistic Locking (for concurrent API clients)

```sql
-- Session table
ALTER TABLE sessions ADD COLUMN version INTEGER DEFAULT 1;

-- Update pattern
UPDATE sessions
SET state = $new_state, version = version + 1
WHERE session_id = $id AND version = $expected_version;

-- If 0 rows updated → version conflict → fetch latest and retry
```

### 12.2 Step-Level Locking (prevent double execution)

```sql
-- In execution transaction
SELECT * FROM plan_steps
WHERE step_id = $id
FOR UPDATE NOWAIT;    -- fail immediately if locked (another worker has it)
```

### 12.3 Parallel Step Execution

```python
async def execute_parallel_group(steps: List[PlanStep]):
    # Only safe if all steps are concurrency_safe
    assert all(tool_registry.get(s.tool_name).is_concurrency_safe for s in steps)
    
    results = await asyncio.gather(
        *[execute_step(step) for step in steps],
        return_exceptions=True
    )
    
    # If any failed: pause remaining parallel steps, enter error handling
    failures = [r for r in results if isinstance(r, Exception)]
    if failures:
        await handle_parallel_failure(steps, failures)
```

---

## 13. Observability

### 13.1 Structured Log Format

```json
{
  "timestamp": "2025-01-15T10:23:45.123Z",
  "level": "INFO",
  "event": "step_completed",

  "session_id": "sess_abc123",
  "plan_id": "plan_xyz456",
  "plan_version": 1,
  "step_id": "step_def789",
  "step_index": 3,

  "tool": "update_machine_status",
  "tool_version": 2,
  "schema_version": 1,
  "is_strongly_idempotent": true,

  "status": "DONE",
  "latency_ms": 182,
  "http_status": 200,
  "idempotency_key": "sha256:abc...",
  "idempotent_replay": false,

  "required_approval": true,
  "approval_latency_ms": 34500,

  "session_step_count": 4,
  "session_llm_call_count": 3,
  "session_replan_count": 0,
  "session_duration_s": 142,

  "user_id": "user_123",
  "environment": "production"
}
```

### 13.2 Metrics to Track

```
Agent Metrics:
    - plan_generation_latency_ms (p50, p95, p99)
    - plan_validation_failure_rate
    - replan_rate (replans per session)
    - steps_per_session (distribution)
    - session_completion_rate

Execution Metrics:
    - step_execution_latency_ms (per tool)
    - tool_error_rate (per tool, per error type)
    - retry_rate (per tool)
    - approval_wait_time_ms (p50, p95)
    - approval_rejection_rate

Exactly-Once Metrics:
    - idempotent_replay_rate       (how often replays hit the cache)
    - payload_mismatch_409_rate    (same key, different payload)
    - ambiguous_step_count (gauge) (steps in AMBIGUOUS state needing review)

DLQ Metrics:
    - dlq_push_rate                (failures pushed per minute)
    - dlq_pending_count (gauge)    (unresolved items)
    - dlq_replay_success_rate

Rate Limit Metrics:
    - sessions_rate_limited_total
    - limit_type_distribution      (which limit is hit most often)

Backpressure Metrics:
    - session_queue_depth (gauge)
    - worker_pool_utilization (gauge)
    - sessions_rejected_429_total

System Metrics:
    - active_sessions (gauge)
    - pending_approvals (gauge)
    - redis_event_queue_depth
    - db_connection_pool_usage
```

---

## 14. Go API Standards (Complete)

### 14.1 Endpoint Conventions

```http
# List with filtering
GET /api/v1/{resource}
    ?filter=field:value,field2:value2
    &sort=field:asc|desc
    &fields=id,name,status          (field selection)
    &limit=50&offset=0
    &include=related_resource       (eager load)

# Single resource
GET    /api/v1/{resource}/{id}
POST   /api/v1/{resource}
PATCH  /api/v1/{resource}/{id}
DELETE /api/v1/{resource}/{id}
```

### 14.2 Response Envelope

```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "total": 150,
    "limit": 50,
    "offset": 0
  },
  "error": null
}
```

### 14.3 Error Response

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "status must be one of: ACTIVE, INACTIVE, MAINTENANCE",
    "field": "status",
    "request_id": "req_abc123"
  }
}
```

### 14.4 Strong Idempotency Implementation

The v1 middleware only cached by key. This upgrade adds payload hash validation to prevent reuse of the same key with different payloads, and stores a DB-level backup in case Redis is unavailable.

```go
// Middleware on all POST/PATCH/DELETE
func IdempotencyMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        key := r.Header.Get("Idempotency-Key")
        if key == "" {
            http.Error(w, `{"error":"Idempotency-Key header required"}`, 400)
            return
        }

        // Buffer body for hashing (body can only be read once)
        bodyBytes, _ := io.ReadAll(r.Body)
        r.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
        requestHash := sha256Hex(bodyBytes)

        type CachedEntry struct {
            RequestHash  string `json:"request_hash"`
            ResponseBody []byte `json:"response_body"`
            StatusCode   int    `json:"status_code"`
        }

        cacheKey := "idempotency:" + key
        cached, err := redis.Get(ctx, cacheKey)
        if err == nil {
            var entry CachedEntry
            json.Unmarshal([]byte(cached), &entry)

            // Same key, DIFFERENT payload → reject (prevents accidental reuse)
            if entry.RequestHash != requestHash {
                w.WriteHeader(409)
                w.Write([]byte(`{"error":"Idempotency key reused with different payload"}`))
                return
            }

            // Same key, same payload → deterministic replay
            w.Header().Set("X-Idempotent-Replayed", "true")
            w.WriteHeader(entry.StatusCode)
            w.Write(entry.ResponseBody)
            return
        }

        // Execute and cache (Redis TTL: 24h)
        rec := &ResponseRecorder{ResponseWriter: w}
        next.ServeHTTP(rec, r)

        entry := CachedEntry{requestHash, rec.Body.Bytes(), rec.StatusCode}
        entryJSON, _ := json.Marshal(entry)
        redis.Set(ctx, cacheKey, entryJSON, 24*time.Hour)

        // DB-level backup (survives Redis restart)
        db.Exec(
            `INSERT INTO idempotency_log (key, request_hash, response, status_code, created_at)
             VALUES ($1, $2, $3, $4, now()) ON CONFLICT (key) DO NOTHING`,
            key, requestHash, rec.Body.Bytes(), rec.StatusCode)
    })
}
```

**FastAPI execution rule — retry gate based on strong idempotency:**

```python
async def execute_tool(step: PlanStep, tool: Tool) -> dict:
    if tool.is_strongly_idempotent:
        # Safe to retry — backend returns same result for same key+payload
        return await call_tool_with_retry(step, tool)
    else:
        # Retry DISABLED — re-execution may cause duplicate side effects
        return await call_tool_once(step, tool)

async def call_tool_once(step: PlanStep, tool: Tool) -> dict:
    try:
        return await http_call(tool, step.args, step.idempotency_key)
    except NetworkTimeoutError as e:
        if e.request_was_sent:
            # We don't know if the backend executed — flag for human review
            step.status = StepStatus.AMBIGUOUS
            await db.save(step)
            raise AmbiguousExecutionError(step)
        raise  # Timeout before send → safe to bubble up normally
```

---

## 15. Redis Event System

### 15.1 Event Types

```python
class AgentEvent:
    event_type: Literal[
        "approval_decided",      # User approved/rejected
        "session_resume",        # External trigger to resume
        "tool_registry_updated", # tools.md regenerated
        "session_cancel",        # Force-cancel from UI
        "dlq_replay_requested",  # Ops triggers manual replay of a DLQ entry
        "worker_available"       # Backpressure: a worker slot opened up
    ]
    session_id: UUID
    payload: dict
    published_at: datetime
```

### 15.2 Subscribe Pattern (FastAPI)

```python
async def start_event_listener():
    pubsub = redis.pubsub()
    await pubsub.subscribe("agent_events")
    
    async for message in pubsub.listen():
        if message["type"] == "message":
            event = AgentEvent.parse_raw(message["data"])
            
            if event.event_type == "approval_decided":
                await resume_session(event.session_id)
            
            elif event.event_type == "session_cancel":
                await cancel_session(event.session_id)

            elif event.event_type == "dlq_replay_requested":
                dlq_id = event.payload["dlq_id"]
                await replay_dlq_entry(dlq_id)
```

---

## 16. Implementation Phases

### Phase 0 — Foundation (Week 1–2)
- [x] Go CRUD API for all factory resources
- [x] OpenAPI 3.0 export endpoint {change to swaggo}
- [x] Strong idempotency middleware in Go (key + payload hash + DB backup log)
- [x] Postgres schema (all tables including DLQ, rate limit columns, capability tags) {change to adapt mysql}
- [x] FastAPI project scaffold + worker pool startup
- [x] Tool auto-generation script (OpenAPI → DB → tools.md with capability tags)

### Phase 1 — Core Agent (Week 3–4)
- [x] LLM prompt template + plan JSON schema (with explainability fields)
- [x] Tool scope filter (intent → relevant tools subset)
- [x] Plan validation engine (all rules in section 10)
- [x] Session manager (CRUD + state transitions + rate limit counters)
- [x] Execution engine (transactional + exactly-once + AMBIGUOUS handling)
- [x] Approval system (create, notify, decide, resume)
- [x] Redis event pub/sub (including DLQ replay event)

_Repo note: Phase 1 baseline is implemented in `factory-agent/agent/*` and wired in `factory-agent/main.py`. Exactly-once uses `plan_steps.idempotency_key` + `execution_snapshots` replay; AMBIGUOUS moves the session to `BLOCKED` and creates a `dead_letters` entry._

### Phase 2 — Resilience (Week 5)
- [ ] Error classification + decision tree (with strong idempotency retry gate)
- [ ] Retry with exponential backoff
- [ ] Replan trigger + context builder
- [ ] DLQ manager (push, list, replay, dismiss endpoints)
- [ ] Rate limiter (hard limits enforced at loop entry + inside loop)
- [ ] Mid-execution user message handling
- [ ] Optimistic locking + concurrency control

### Phase 3 — Observability + Recovery (Week 6)
- [ ] Structured logging (all events including DLQ pushes, rate limit hits)
- [ ] Metrics (Prometheus or similar — all metrics in section 13.2)
- [ ] ExecutionSnapshot audit trail
- [ ] Memory compression (compact memory after N steps)
- [ ] Cold start recovery sweep (startup hook — section 19)
- [ ] Admin dashboard: session list, approval queue, DLQ viewer, tool registry

### Phase 4 — Hardening (Week 7–8)
- [ ] Session queue + worker pool backpressure (section 20)
- [ ] Load testing (concurrent sessions, queue saturation)
- [ ] Chaos testing (crash mid-step, Redis failure, DB failure, cold restart)
- [ ] Security audit (auth, injection, schema validation)
- [ ] Performance tuning (DB indexes, query optimization)
- [ ] Documentation + runbooks (including DLQ replay procedures)

---

## 17. Database Schema (Postgres)

```sql
-- Sessions (rate limit counters added)
CREATE TABLE sessions (
    session_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'IDLE',
    current_intent      TEXT,
    plan_id             UUID,
    plan_version        INTEGER DEFAULT 0,
    plan_hash           TEXT,
    current_step_index  INTEGER DEFAULT 0,
    retry_count         INTEGER DEFAULT 0,
    step_count          INTEGER DEFAULT 0,
    replan_count        INTEGER DEFAULT 0,
    llm_call_count      INTEGER DEFAULT 0,
    session_started_at  TIMESTAMPTZ DEFAULT now(),
    error               TEXT,
    version             INTEGER DEFAULT 1,          -- optimistic lock
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

-- Messages
CREATE TABLE messages (
    message_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(session_id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    step_id     UUID,
    tool_name   TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Plans (explainability fields added)
CREATE TABLE plans (
    plan_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES sessions(session_id),
    version             INTEGER NOT NULL,
    dependency_graph    JSONB,
    parallel_groups     JSONB,
    plan_hash           TEXT NOT NULL,
    plan_explanation    TEXT,                       -- LLM-generated plain-English explanation
    risk_summary        TEXT,                       -- LLM-generated risk description
    created_at          TIMESTAMPTZ DEFAULT now(),
    created_by          TEXT DEFAULT 'llm',
    invalidated_at      TIMESTAMPTZ,
    invalidated_reason  TEXT
);

-- Plan Steps (AMBIGUOUS status supported via TEXT column)
CREATE TABLE plan_steps (
    step_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id             UUID NOT NULL REFERENCES plans(plan_id),
    session_id          UUID NOT NULL,
    step_index          INTEGER NOT NULL,
    tool_name           TEXT NOT NULL,
    args                JSONB NOT NULL,
    status              TEXT NOT NULL DEFAULT 'NOT_STARTED',
    -- valid: NOT_STARTED | IN_PROGRESS | DONE | FAILED | SKIPPED | AMBIGUOUS
    idempotency_key     TEXT NOT NULL UNIQUE,
    requires_approval   BOOLEAN DEFAULT false,
    approval_id         UUID,
    retry_count         INTEGER DEFAULT 0,
    max_retries         INTEGER DEFAULT 3,
    last_error          TEXT,
    result              JSONB,
    result_summary      TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ
);

-- Tools (strong idempotency + capability tags added)
CREATE TABLE tools (
    tool_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL UNIQUE,
    description             TEXT NOT NULL,
    endpoint                TEXT NOT NULL,
    method                  TEXT NOT NULL,
    version                 INTEGER DEFAULT 1,
    schema_version          INTEGER DEFAULT 1,
    input_schema            JSONB NOT NULL,
    output_schema           JSONB,
    is_read_only            BOOLEAN DEFAULT false,
    requires_approval       BOOLEAN DEFAULT false,
    side_effect_level       TEXT DEFAULT 'NONE',
    is_concurrency_safe     BOOLEAN DEFAULT true,
    is_idempotent           BOOLEAN DEFAULT false,
    is_strongly_idempotent  BOOLEAN DEFAULT false,
    capability_tags         TEXT[] DEFAULT '{}',
    deprecated_at           TIMESTAMPTZ,
    replacement_tool        TEXT,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

-- Approvals
CREATE TABLE approvals (
    approval_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES sessions(session_id),
    step_id             UUID NOT NULL REFERENCES plan_steps(step_id),
    tool_name           TEXT NOT NULL,
    args                JSONB NOT NULL,
    risk_summary        TEXT NOT NULL,
    side_effect_level   TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'PENDING',
    expires_at          TIMESTAMPTZ NOT NULL,
    decided_by          TEXT,
    decided_at          TIMESTAMPTZ,
    rejection_reason    TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- Execution Snapshots
CREATE TABLE execution_snapshots (
    snapshot_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    step_id             UUID NOT NULL REFERENCES plan_steps(step_id),
    session_id          UUID NOT NULL,
    tool_name           TEXT NOT NULL,
    tool_version        INTEGER NOT NULL,
    schema_version      INTEGER NOT NULL,
    input_args          JSONB NOT NULL,
    plan_hash           TEXT NOT NULL,
    plan_version        INTEGER NOT NULL,
    idempotency_key     TEXT NOT NULL,
    http_status         INTEGER,
    response_body       JSONB,
    latency_ms          INTEGER,
    executed_at         TIMESTAMPTZ DEFAULT now()
);

-- Dead Letter Queue
CREATE TABLE dead_letters (
    dlq_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES sessions(session_id),
    step_id             UUID REFERENCES plan_steps(step_id),   -- NULL if planning-level failure
    failure_type        TEXT NOT NULL,
    -- valid: max_retries_exceeded | replan_limit_reached | unrecoverable_error
    --        rate_limit_exceeded | session_timeout | validation_failure | ambiguous_execution
    reason              TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'PENDING',
    -- valid: PENDING | REPLAYED | DISMISSED | ESCALATED
    replayed_at         TIMESTAMPTZ,
    replayed_by         TEXT,
    dismissed_at        TIMESTAMPTZ,
    dismissed_reason    TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- Idempotency Log (DB-level backup for when Redis is unavailable)
CREATE TABLE idempotency_log (
    key          TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    response     BYTEA NOT NULL,
    status_code  INTEGER NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_sessions_user_id           ON sessions(user_id);
CREATE INDEX idx_sessions_status            ON sessions(status);
CREATE INDEX idx_messages_session_id        ON messages(session_id);
CREATE INDEX idx_plan_steps_session_id      ON plan_steps(session_id);
CREATE INDEX idx_plan_steps_status          ON plan_steps(status);
CREATE INDEX idx_plan_steps_idempotency     ON plan_steps(idempotency_key);
CREATE INDEX idx_approvals_session_id       ON approvals(session_id);
CREATE INDEX idx_approvals_status           ON approvals(status);
CREATE INDEX idx_snapshots_session_id       ON execution_snapshots(session_id);
CREATE INDEX idx_dlq_status                 ON dead_letters(status);
CREATE INDEX idx_dlq_session_id             ON dead_letters(session_id);
CREATE INDEX idx_tools_capability_tags      ON tools USING GIN(capability_tags);
```
