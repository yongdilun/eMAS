# Current Factory Agent Structure Deep Analysis

Generated: 2026-05-25  
Scope checked: current `factory-agent` backend, Factory Agent frontend chat path, graph runtime, LLM call sites, RAG document path, and focused contract tests.

## Executive Summary

The current agent runtime is planner-owned LangGraph v2. A normal user query from the React chat UI is saved as a session message, promoted to `Session.current_intent`, and then executed inline by `POST /sessions/{session_id}/plans` through `PlanCreationService._create_planner_owned_graph_plan`.

Check: frontend sends the message then creates the plan in `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:611`; the REST client targets `/sessions/{session_id}/messages` and `/sessions/{session_id}/plans` in `eMas Front/src/services/factoryAgentApi.js:152`; the backend plans router calls `plan_creation_service.create_plan` in `factory-agent/factory_agent/api/routers/plans.py:21`; the v2 branch calls `_create_planner_owned_graph_plan` in `factory-agent/factory_agent/services/plan_creation_service.py:1053`.

The graph node order is fixed and linear:

```text
semantic_intake_node
  -> requirement_ledger_node
  -> planner_decision_node
  -> tool_retrieval_node
  -> planner_choose_tool_node
  -> tool_execution_node
  -> evidence_observation_node
  -> satisfaction_node
  -> approval_node
  -> finalize_node
  -> response_document_node
  -> END
```

Check: `PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER` defines this sequence in `factory-agent/factory_agent/graph/v2_agent_graph.py:119`, `_compile_graph` registers nodes and edges in `factory-agent/factory_agent/graph/v2_agent_graph.py:566`, and `test_phase3_simple_read_query_flows_through_graph_nodes_in_order` asserts the same order in `factory-agent/tests/test_planner_owned_graph_shell_contract.py:143`.

LLM calls are not made by every node. The current runtime has these possible model call surfaces:

| Call Surface | When It Runs | Prompt Type | Primary Check |
|:---|:---|:---|:---|
| Planner decision proposer | In `planner_decision_node`, `planner_choose_tool_node`, and approval staging when planner decisions are required and planner LLM config exists | Compact JSON-only `PlannerDecisionSubmission` prompt | `factory-agent/factory_agent/planning/v2_planner_proposer.py:206`, `factory-agent/factory_agent/planning/v2_planner_proposer.py:415` |
| Tool selector reranker | Only when deterministic retrieval has multiple close candidates and LLM reranking is enabled/configured | JSON rerank prompt choosing from candidate backend tools | `factory-agent/factory_agent/planning/tool_selector.py:717`, `factory-agent/factory_agent/planning/tool_selector.py:838` |
| RAG answer generator | Only when the selected tool is the virtual document search tool or direct knowledge route | System + human message with strict citation contract and retrieved context | `factory-agent/factory_agent/rag/generation.py:51`, `factory-agent/factory_agent/rag/generation.py:197` |
| RAG reranker | Default is BGE cross-encoder, not chat LLM; legacy injected `llm` path can call a model | JSON list of ranked chunk IDs only in legacy injected mode | `factory-agent/factory_agent/rag/reranking.py:81`, `factory-agent/factory_agent/rag/reranking.py:270` |
| Summary adapter | Mostly deterministic in current graph persistence; `summarize_plan` can call LangChain for non-empty plans if summary backend is configured | Operator-facing <=120-word plan summary | `factory-agent/factory_agent/analysis/summary_backend.py:340`, `factory-agent/factory_agent/analysis/summary_backend.py:366` |

The main operational tools come from the DB-backed registry generated from Swagger/OpenAPI plus one injected virtual RAG tool named `rag_search_documents`.

Check: `build_router` wires `ToolRegistry`, `ToolSelector`, `PlanCreationService`, and `PlannerOwnedGraphRuntimeAdapter` in `factory-agent/factory_agent/api/routes.py:34`; `ensure_v2_rag_tool` adds `rag_search_documents` in `factory-agent/factory_agent/planning/v2_rag_tool.py:12`; `tools.md` is generated registry documentation beginning at `factory-agent/factory_agent/tools.md:1`.

## Query Flow From Frontend To Graph

1. The React hook starts or reuses a chat session.

   Check: `startNewSession` calls `factoryAgentApi.createSession` in `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:538`; the REST wrapper posts `/sessions` in `eMas Front/src/services/factoryAgentApi.js:124`; backend `create_session` persists an `IDLE` session in `factory-agent/factory_agent/api/routers/sessions.py:27` and `factory-agent/factory_agent/orchestration/session_manager.py:49`.

2. The user query is saved as a message.

   Check: `runIntent` calls `factoryAgentApi.addMessage(sessionId, { role: 'user', content: text, mode })` in `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:611`; backend `add_message` persists it through `SessionManager.add_message` in `factory-agent/factory_agent/api/routers/messages.py:80`; `SessionManager.add_message` creates the `MessageRow` in `factory-agent/factory_agent/orchestration/session_manager.py:65`.

3. A normal user message moves terminal/idle sessions into planning state and stores the current intent.

   Check: for statuses `IDLE`, `COMPLETED`, `BLOCKED`, or `FAILED`, the messages router assigns `sess.current_intent = user_message` and `sess.status = "PLANNING"` in `factory-agent/factory_agent/api/routers/messages.py:234`.

4. The frontend immediately asks the backend to create a plan.

   Check: `runIntent` calls `factoryAgentApi.createPlan(sessionId)` after snapshot refresh in `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:614`; the REST wrapper posts `/sessions/{sessionId}/plans` in `eMas Front/src/services/factoryAgentApi.js:155`; the backend route is `@router.post("/sessions/{session_id}/plans")` in `factory-agent/factory_agent/api/routers/plans.py:21`.

5. `PlanCreationService.create_plan` loads the session, derives the runtime intent, handles LOTO context carry-over, filters allowed tools by role, and resolves the engine.

   Check: session/user validation is in `factory-agent/factory_agent/services/plan_creation_service.py:1021`; intent, latest user mode, semantic frame, and LOTO contextual resolution are in `factory-agent/factory_agent/services/plan_creation_service.py:1030`; role-filtered registry tools are loaded in `factory-agent/factory_agent/services/plan_creation_service.py:1046`; engine resolution happens in `factory-agent/factory_agent/services/plan_creation_service.py:1051`.

6. The v2 engine is forced, so normal no-draft planning enters the planner-owned graph path.

   Check: `normalize_factory_agent_engine` always returns `"v2"` in `factory-agent/factory_agent/config.py:152`; the v2 branch calls `_create_planner_owned_graph_plan` in `factory-agent/factory_agent/services/plan_creation_service.py:1053`.

7. `PlannerOwnedGraphRuntimeAdapter.run_plan` builds and runs `PlannerOwnedAgentGraph`, then persists the graph result into relational plan/session/message rows.

   Check: `run_plan` injects the virtual RAG tool, builds the graph, calls `graph.run(...)`, increments LLM count, and calls `persist_result` in `factory-agent/factory_agent/services/planner_owned_graph_runtime.py:47`.

8. In current graph-native execution, the legacy worker pool is not the authority.

   Check: startup logs the legacy worker pool as retired because LangGraph sessions execute inline/checkpointed through the API in `factory-agent/main.py:611`; `is_graph_native_session` detects graph plans, approvals, and checkpoints in `factory-agent/factory_agent/graph/session_detection.py:64`; the execution endpoint reruns planner-owned creation if it is called, rather than running old step workers, in `factory-agent/factory_agent/services/execution_service.py:30`.

## Graph Runtime Anatomy

### Graph Shell

`PlannerOwnedAgentGraph` wraps a LangGraph `StateGraph` of `PlannerOwnedAgentGraphState`.

Check: the shell is defined at `factory-agent/factory_agent/graph/v2_agent_graph.py:335`; `StateGraph(PlannerOwnedAgentGraphState)` is created at `factory-agent/factory_agent/graph/v2_agent_graph.py:567`.

Initial state is built before the first node runs. It creates a capability map from available tools, builds a deterministic requirement sketch and ledger from the original query, and records initial capability needs.

Check: `build_initial_planner_owned_agent_graph_state` builds `capability_map`, `requirement_sketch`, `requirement_ledger`, and `capability_needs` in `factory-agent/factory_agent/planning/v2_agent_state.py:174`.

Checkpointer behavior is native LangGraph checkpointing with preference order: Postgres saver, DB-backed saver, memory saver, or none if disabled.

Check: `build_graph_checkpointer` documents and implements that preference order in `factory-agent/factory_agent/graph/checkpointing.py:372`.

### Node-by-node Trace

| Node | What It Consumes | What It Does | LLM? | Check |
|:---|:---|:---|:---|:---|
| `semantic_intake_node` | Initial graph state and original query | Records that the original query exists and updates graph diagnostics | No | `factory-agent/factory_agent/graph/v2_agent_graph.py:596` |
| `requirement_ledger_node` | Deterministic requirement ledger | Copies ledger revision and requirement IDs into response document context | No | `factory-agent/factory_agent/graph/v2_agent_graph.py:604` |
| `planner_decision_node` | Open requirements without evidence | Asks proposer for `retrieve_tools` decisions, or records no decision | Possible planner LLM | `factory-agent/factory_agent/graph/v2_agent_graph.py:658` |
| `tool_retrieval_node` | Persisted `retrieve_tools` decisions | Calls `V2CapabilityToolRetriever`, stores candidate windows and hydrated tool cards | Possible tool selector LLM reranker | `factory-agent/factory_agent/graph/v2_agent_graph.py:712`, `factory-agent/factory_agent/planning/v2_tool_retriever.py:75` |
| `planner_choose_tool_node` | Candidate windows and hydrated cards | Either deterministically selects a single document tool or asks proposer for `choose_tool` | Possible planner LLM | `factory-agent/factory_agent/graph/v2_agent_graph.py:783` |
| `tool_execution_node` | Persisted selected tool calls | Executes authorized read calls, batches parallel reads, or stages approval for writes | No direct LLM; RAG tool may call RAG generator | `factory-agent/factory_agent/graph/v2_agent_graph.py:879` |
| `evidence_observation_node` | Pending execution result payloads | Converts execution results into typed `EvidenceLedgerEntry` records and aggregates multi-entity status evidence | No | `factory-agent/factory_agent/graph/v2_agent_graph.py:1014`, `factory-agent/factory_agent/planning/v2_graph_adapters.py:330` |
| `satisfaction_node` | Active evidence and requirement ledger | Applies deterministic satisfaction and final validation, deferring if approval/write follow-up is open | No | `factory-agent/factory_agent/graph/v2_agent_graph.py:1124`, `factory-agent/factory_agent/planning/v2_satisfaction.py:159` |
| `approval_node` | Pending approval state | Records approval diagnostics and checkpoint details | No | `factory-agent/factory_agent/graph/v2_agent_graph.py:1169` |
| `finalize_node` | Final validation and pending approval/write state | Records deterministic `finalize` if validation passed, otherwise deterministic `fail`; defers while approval/write is pending | No | `factory-agent/factory_agent/graph/v2_agent_graph.py:1181` |
| `response_document_node` | Evidence, validation, pending approval, diagnostics | Builds response blocks, summary, state, pending approval link, and response document context | No | `factory-agent/factory_agent/graph/v2_agent_graph.py:1228`, `factory-agent/factory_agent/graph/v2_graph_response_projection.py:12` |

## Planner Decision Proposer

The proposer is the main planner LLM surface. It is called through `_propose_and_record_planner_decision`, which increments `state.execution_trace.planner.call_count`, invokes the configured proposer, validates the submitted decision, records acceptance or rejection diagnostics, and applies proposed requirement-ledger revisions only when valid.

Check: `_propose_and_record_planner_decision` is implemented in `factory-agent/factory_agent/graph/v2_agent_graph.py:618`; decision validation is enforced by `record_planner_decision` and `validate_planner_decision`; locked constraints are preserved by validation in `factory-agent/factory_agent/planning/v2_planner_decisions.py:190`.

Runtime proposer selection:

- If `PLANNER_OPENAI_BASE_URL`, `OPENAI_BASE_URL`, `LLM_BASE_URL`, `OPENAI_API_KEY`, or `LLM_API_KEY` config resolves to planner/OpenAI credentials, the runtime uses `OpenAICompatibleQwenPlannerDecisionProposer`.
- If offline proposer is explicitly allowed, it uses `OfflineStructuredPlannerDecisionProposer`.
- Otherwise it fails closed with `PlannerLLMConfigurationRequiredProposer`.

Check: `build_planner_decision_proposer` implements this selection in `factory-agent/factory_agent/planning/v2_planner_proposer.py:331`; the missing-config fail-closed proposer is defined in `factory-agent/factory_agent/planning/v2_planner_proposer.py:115`; config sources are loaded in `factory-agent/factory_agent/config.py:337`.

The planner prompt is compact JSON, not a free-form chat transcript. It includes a `task`, strict `rules`, a `response_contract`, and a bounded `decision_state`.

Check: `_build_planner_decision_prompt` constructs that JSON payload in `factory-agent/factory_agent/planning/v2_planner_proposer.py:415`.

Important planner prompt rules checked in code:

- Return JSON only.
- Do not invent tools outside `decision_state.candidate_tool_calls`.
- Choose tools by `selected_tool_name`.
- For approval-required mutations, choose the write/mutation tool because approval preview reads source rows before execution.
- Do not include `proposed_requirement_ledger` unless revising requirements.
- Do not drop locked constraints.

Check: the rule strings live in `factory-agent/factory_agent/planning/v2_planner_proposer.py:424`; the decision-state tool policy is added in `factory-agent/factory_agent/planning/v2_planner_proposer.py:531`; tests assert the prompt omits full schemas/catalog and stays compact in `factory-agent/tests/test_planner_owned_graph_llm_proposer.py:359`.

The actual LLM call is `await model.ainvoke(prompt)` using `ChatOpenAI` with JSON mode.

Check: the proposer builds the prompt and model at `factory-agent/factory_agent/planning/v2_planner_proposer.py:206`; the call is at `factory-agent/factory_agent/planning/v2_planner_proposer.py:218`; `build_planner_chat_model` sets model, temperature 0, timeout, max tokens, and JSON response format in `factory-agent/factory_agent/llm/models.py:14`.

The proposer does not receive the full OpenAPI catalog. It receives bounded summaries of requirements, candidate tool calls, hydrated tool summaries, evidence, and policy flags.

Check: `_bounded_decision_state` includes `full_openapi_catalog_visible: False` in `factory-agent/factory_agent/planning/v2_planner_proposer.py:505`; tests assert `full_openapi_catalog_visible is False` and candidate tools are limited in `factory-agent/tests/test_planner_owned_graph_llm_proposer.py:274`.

If the model returns malformed JSON, invalid schema, an outside-window tool, or an invalid locked-constraint revision, execution fails closed before tool execution.

Check: invalid model output is rejected in `factory-agent/factory_agent/planning/v2_planner_proposer.py:276`; outside candidate windows are rejected in `factory-agent/factory_agent/planning/v2_planner_decisions.py:401`; tests assert malformed output causes no executor calls in `factory-agent/tests/test_planner_owned_graph_llm_proposer.py:297`.

## Tool Retrieval And Tool Choice

Tool retrieval starts with a deterministic capability need built from the query and requirement ledger.

Check: `build_capability_needs_for_text` maps requirement source/entity/action/constraints into `CapabilityNeed` in `factory-agent/factory_agent/planning/v2_capability_map.py:164`.

The tool retriever calls `ToolSelector.select_tools` with a retrieval phrase derived from the need and then hydrates candidate tools into `CandidateToolWindow` and `HydratedToolCards`.

Check: `V2CapabilityToolRetriever.retrieve_tools_for_need` calls `select_tools` in `factory-agent/factory_agent/planning/v2_tool_retriever.py:90`, creates candidates at `factory-agent/factory_agent/planning/v2_tool_retriever.py:112`, and creates hydrated cards at `factory-agent/factory_agent/planning/v2_tool_retriever.py:133`.

`ToolSelector` first attempts deterministic semantic routes, diagnostic shortcuts, token/profile scoring, and optional sentence-transformer embeddings. It only invokes an LLM reranker when there are at least two candidates, reranking is allowed, and the top candidates are close or forced tracing is enabled.

Check: early deterministic returns are in `factory-agent/factory_agent/planning/tool_selector.py:800`; `_should_rerank` gates LLM use in `factory-agent/factory_agent/planning/tool_selector.py:394`.

The tool selector LLM prompt asks for one JSON object with `primary_tool`, `additional_tools`, `confidence`, `missing_fields`, and `reason`, choosing only from provided candidates.

Check: `_build_rerank_prompt` defines the prompt in `factory-agent/factory_agent/planning/tool_selector.py:717`; `_invoke_reranker` sends it through `ChatOpenAI` in JSON mode in `factory-agent/factory_agent/planning/tool_selector.py:761`.

Tool choice is planner-authored when there is no deterministic single-document shortcut. The chosen tool must pass the decision gate before execution.

Check: `planner_choose_tool_node` invokes the deterministic document shortcut first and then proposer fallback in `factory-agent/factory_agent/graph/v2_agent_graph.py:807`; validation checks selected tools are from the hydrated candidate window in `factory-agent/factory_agent/planning/v2_planner_decisions.py:401`.

## Tool Execution

Execution requires a persisted, validated `execute_tool` or `execute_parallel_read_batch` decision. The graph does not execute arbitrary planner output directly.

Check: `require_graph_execution_authorization` requires a persisted decision and validates it in `factory-agent/factory_agent/planning/v2_graph_adapters.py:110`.

API tools execute through `execute_tool_http`, which materializes path params, normalizes path/query/body args, sends an HTTP request to `settings.go_api_base_url`, and returns a normalized envelope.

Check: `execute_graph_api_tool_call` calls the HTTP executor in `factory-agent/factory_agent/planning/v2_graph_adapters.py:135`; `execute_tool_http` handles methods and normalized response envelope in `factory-agent/factory_agent/graph/http_tool_client.py:62`.

RAG tool execution uses the virtual `rag_search_documents` tool and calls `RAGPipeline.run(query=..., route="RAG_ONLY")`.

Check: `execute_graph_tool_call` branches on `call.kind == "rag_tool"` in `factory-agent/factory_agent/planning/v2_graph_adapters.py:88`; `execute_graph_rag_tool` calls the pipeline in `factory-agent/factory_agent/planning/v2_graph_adapters.py:186`; the virtual tool is defined in `factory-agent/factory_agent/planning/v2_rag_tool.py:12`.

Writes do not execute immediately. If the selected tool requires approval, the graph stages an approval preview, expands exact staged write calls, persists an approval row, saves checkpoint identity, and pauses with `PendingApprovalState(status="pending")`.

Check: `_tool_execution_node` branches to `_stage_write_approval` when graph approval is required in `factory-agent/factory_agent/graph/v2_agent_graph.py:961`; approval staging builds preview/staged calls/payload and sets pending state in `factory-agent/factory_agent/graph/v2_agent_graph.py:1353`.

After approval, `POST /approvals/{approval_id}/approve` marks the approval approved, stores `langgraph_approval_resume`, moves the session to `EXECUTING`, and resumes the graph from the native checkpoint.

Check: the approval route handles graph approvals in `factory-agent/factory_agent/api/routers/approvals.py:81`; the planner-owned resume path calls `resume_planner_owned_graph_approval` and persists the resumed result in `factory-agent/factory_agent/services/approval_resume_service.py:366`; `PlannerOwnedAgentGraph.resume_from_approval` loads the checkpoint and continues from approval/satisfaction/finalize/response nodes in `factory-agent/factory_agent/graph/v2_agent_graph.py:410`.

## Evidence, Satisfaction, And Final Response

Tool results become typed evidence in `evidence_observation_node`.

Check: the node reads pending execution results and appends `EvidenceLedgerEntry` objects in `factory-agent/factory_agent/graph/v2_agent_graph.py:1014`; `observe_graph_tool_result` constructs `EvidenceLedgerEntry` from normalized execution results in `factory-agent/factory_agent/planning/v2_graph_adapters.py:330`.

Satisfaction is deterministic: it excludes stale evidence, applies deterministic requirement satisfaction, and runs final validation.

Check: `satisfaction_node` filters active evidence in `factory-agent/factory_agent/graph/v2_agent_graph.py:1140`; `apply_deterministic_evidence_satisfaction` is called in `factory-agent/factory_agent/graph/v2_agent_graph.py:1148`; final validation is called in `factory-agent/factory_agent/graph/v2_agent_graph.py:1166`.

Finalization is deterministic. A passed final validation records a `finalize` decision authored by `deterministic_guard`; otherwise it records a deterministic `fail`.

Check: `finalize_node` creates the passed-finalize decision in `factory-agent/factory_agent/graph/v2_agent_graph.py:1197` and the failed decision in `factory-agent/factory_agent/graph/v2_agent_graph.py:1213`.

The response document is built from evidence/approval/validation state rather than by a final LLM answer composer.

Check: `response_document_node` builds response blocks and summary in `factory-agent/factory_agent/graph/v2_agent_graph.py:1228`; `_phase6_response_blocks` and `_phase6_response_summary` are deterministic functions in `factory-agent/factory_agent/graph/v2_graph_response_projection.py:12`.

Graph output is projected back into `PlanDraft`, `PlanStepRow`, session status, and assistant message rows by `PlannerOwnedGraphRuntimeAdapter.persist_result` and `PlanCreationService._persist_plan`.

Check: `persist_result` chooses pending approval vs plan artifacts in `factory-agent/factory_agent/services/planner_owned_graph_runtime.py:109`; `_plan_artifacts` builds `PlanDraft` and tool outputs in `factory-agent/factory_agent/services/planner_owned_graph_runtime.py:386`; `_persist_plan` writes plan/steps/session/message rows in `factory-agent/factory_agent/services/plan_creation_service.py:709`.

Planner-owned graph context is stored under `replan_context.intent_contract` and `replan_context.planner_owned_agent_graph`, including the graph state, execution trace, node order, evidence refs, response document context, and checkpoint config.

Check: `_graph_context` writes those fields in `factory-agent/factory_agent/services/planner_owned_graph_runtime.py:343`.

## RAG Document Path

The document path is a tool path, not a separate conversational endpoint in the current graph. The virtual tool `rag_search_documents` is made available alongside real API tools and selected through the same retrieval/choice/authorization/evidence process.

Check: `ensure_v2_rag_tool` injects `rag_search_documents` in `factory-agent/factory_agent/planning/v2_rag_tool.py:61`; RAG tool execution is authorized through `execute_graph_tool_call` in `factory-agent/factory_agent/planning/v2_graph_adapters.py:70`.

RAG pipeline stages are retrieval, rerank, context building, and generation.

Check: `RAGPipeline._run_sync` performs retrieval at `factory-agent/factory_agent/rag/pipeline.py:111`, reranking at `factory-agent/factory_agent/rag/pipeline.py:130`, context building at `factory-agent/factory_agent/rag/pipeline.py:162`, and answer generation at `factory-agent/factory_agent/rag/pipeline.py:179`.

Retrieval uses a hybrid retriever backed by vector search and BM25, with configurable vector/keyword/fusion top-k values.

Check: `RAGPipelineConfig` defaults to `retrieval_mode="hybrid"`, vector/keyword/fusion top-k values, and rerank settings in `factory-agent/factory_agent/rag/pipeline.py:21`; `HybridRetriever` is imported and used in `factory-agent/factory_agent/rag/pipeline.py:15`.

The default reranker is BGE cross-encoder through `build_bge_reranker`, not a chat LLM. The legacy LLM rerank path only runs if `self.llm` is injected.

Check: `LLMReranker.__init__` builds `build_bge_reranker` and sets `self.llm = None` in `factory-agent/factory_agent/rag/reranking.py:81`; the legacy LLM branch is guarded by `if legacy_llm is not None` in `factory-agent/factory_agent/rag/reranking.py:126`.

The answer-generation LLM prompt is a strict cited-answer prompt. It says to answer only from context/source numbers, use citation markers like `[^1]`, avoid unsupported claims, and output an insufficient-context sentence when support is not present.

Check: `ANSWER_PROMPT` is defined in `factory-agent/factory_agent/rag/generation.py:51`; the generator formats it with context, API data section, query, and insufficient-answer text in `factory-agent/factory_agent/rag/generation.py:188`; tests verify the citation contract appears in the first generation call in `factory-agent/tests/test_rag_generation.py:155`.

The RAG generator sends two messages to the chat model: a short system message and the formatted human prompt.

Check: `messages = [SystemMessage(...), HumanMessage(...)]` and `self.llm.invoke(messages)` are in `factory-agent/factory_agent/rag/generation.py:197`.

Current source register documents are:

| Doc ID | Title | Organization | Risk | Use Class |
|:---|:---|:---|:---|:---|
| `nist_ams_300_1` | Reference Architecture for Smart Manufacturing Part 1: Functional Models | NIST | low | smart manufacturing / architecture background |
| `nist_ams_300_11` | Recommendations for Collecting, Curating, and Re-Using Manufacturing Data | NIST | low | manufacturing data / decision support background |
| `osha_3120_lockout_tagout` | Control of Hazardous Energy Lockout/Tagout | OSHA | high | LOTO and hazardous energy guidance |
| `osha_machine_guarding_checklist` | Machine Guarding Checklist | OSHA / NJ State AFL-CIO | high | machine guarding and safeguard checks |
| `nist_csf_2_0` | The NIST Cybersecurity Framework (CSF) 2.0 | NIST | medium | cybersecurity/cloud/API security discussion |

Check: `rag_sources/00_metadata_templates/source_register.json` lists these five documents; the default source-register path is `rag_sources/00_metadata_templates/source_register.json` in `factory-agent/factory_agent/rag/document_registry.py:11`.

Source PDF routes are exposed as `/documents/{doc_id}/pdf` rather than raw local file paths.

Check: `source_pdf_url` returns `/documents/{safe_doc_id}/pdf` in `factory-agent/factory_agent/rag/document_registry.py:15`; `resolve_source_pdf_path` rejects paths outside the source root in `factory-agent/factory_agent/rag/document_registry.py:34`.

## Prompt Inventory

### Current Planner Decision Prompt

Shape: JSON string sent as one prompt to the planner model.

Purpose: produce one compact `PlannerDecisionSubmission` for a requested decision kind such as `retrieve_tools`, `choose_tool`, `request_approval`, `finalize`, or `fail`.

Contains:

- `task`: return one compact JSON object.
- `rules`: JSON-only, no invented tools, candidate-window-only tool choice, approval mutation write-tool preference, locked-constraint preservation.
- `response_contract`: minimal JSON contract and forbidden fields.
- `decision_state`: original query, current/all requirements, capability need, bounded evidence summary, pending approval status, and candidate calls/cards when relevant.

Check: built in `factory-agent/factory_agent/planning/v2_planner_proposer.py:415`; sent in `factory-agent/factory_agent/planning/v2_planner_proposer.py:218`; compactness/candidate-only behavior checked by `factory-agent/tests/test_planner_owned_graph_llm_proposer.py:359`.

### Tool Selector Rerank Prompt

Shape: plain text with a JSON response instruction.

Purpose: choose the best backend tools from a precomputed candidate list.

Contains:

- User intent.
- Execution mode.
- Rules to prefer exact action/entity alignment, avoid specialized sub-resources unless asked, and use read-only tools in plan mode.
- Candidate cards.
- Required output JSON with `primary_tool`, `additional_tools`, `confidence`, `missing_fields`, and `reason`.

Check: prompt builder is `factory-agent/factory_agent/planning/tool_selector.py:717`; LLM invocation is `factory-agent/factory_agent/planning/tool_selector.py:761`; rerank gate is `factory-agent/factory_agent/planning/tool_selector.py:394`.

### RAG Answer Prompt

Shape: system message plus human prompt.

Purpose: answer from retrieved context and optional live API data with citations.

Contains:

- Role: eMAS industrial maintenance/safety/operations assistant.
- Task: answer only using provided context/source numbers.
- Citation contract with `[^N]` markers.
- Procedure and non-procedure output formats.
- Context block and optional API data block.
- Final checks before answering.

Check: prompt text is `ANSWER_PROMPT` in `factory-agent/factory_agent/rag/generation.py:51`; the system/human messages are created in `factory-agent/factory_agent/rag/generation.py:197`; answer contract tests cover grouped citations and insufficient context in `factory-agent/tests/test_rag_answer_contract.py:38`.

### Summary Prompt

Shape: plain text prompt to summarize an execution plan in <=120 words.

Purpose: operator-facing summary for non-empty plan drafts when `summary_backend` resolves to LangChain.

Contains:

- Intent.
- Plan explanation.
- Risk summary.

Check: summary prompt is built in `factory-agent/factory_agent/analysis/summary_backend.py:366`; no-step drafts skip this LLM and return the plan explanation deterministically in `factory-agent/factory_agent/analysis/summary_backend.py:340`.

### Legacy Planner Prompt

Shape: JSON-schema plan-draft prompt in `planning/prompting.py`.

Status: present for compatibility/tests, but not the current planner-owned graph prompt path. I did not find runtime imports of `build_planner_prompt` under `factory_agent/`, only a test import.

Check: `build_planner_prompt` exists in `factory-agent/factory_agent/planning/prompting.py:33`; `rg` found only `factory-agent/tests/test_prompt_schema.py` importing it; current v2 planning routes through `_create_planner_owned_graph_plan` in `factory-agent/factory_agent/services/plan_creation_service.py:1053`.

## State And Persistence Map

| State/Persistence Item | Role | Check |
|:---|:---|:---|
| `Session.current_intent` | Carries latest actionable user query into planning | `factory-agent/factory_agent/api/routers/messages.py:234` |
| `MessageRow` | Stores user/assistant messages and assistant plan response | `factory-agent/factory_agent/orchestration/session_manager.py:65`, `factory-agent/factory_agent/services/plan_creation_service.py:888` |
| `PlannerOwnedAgentGraphState.original_query` | Root query used to build requirement ledger and graph trace | `factory-agent/factory_agent/planning/v2_agent_state.py:205` |
| `RequirementLedger` | Locked deterministic requirements derived from query | `factory-agent/factory_agent/planning/v2_capability_map.py:418` |
| `planner_decisions` | Planner/guard decisions accepted by graph decision gate | `factory-agent/factory_agent/graph/v2_agent_graph.py:618`, `factory-agent/factory_agent/planning/v2_planner_decisions.py:75` |
| `candidate_tool_windows` / `hydrated_tool_cards` | Bounded tool universe visible to planner chooser | `factory-agent/factory_agent/planning/v2_tool_retriever.py:124`, `factory-agent/factory_agent/planning/v2_tool_retriever.py:133` |
| `EvidenceLedger` | Typed source of truth from API/RAG/approval/system guards | `factory-agent/factory_agent/graph/v2_agent_graph.py:1042` |
| `PendingApprovalState` | Graph-native pause/resume metadata for approval-gated writes | `factory-agent/factory_agent/graph/v2_agent_graph.py:1478` |
| `ResponseDocumentContext` | Renderable final/pending response state | `factory-agent/factory_agent/graph/v2_agent_graph.py:1249` |
| `PlanRow` / `PlanStepRow` | Relational projection for API/UI compatibility | `factory-agent/factory_agent/services/plan_creation_service.py:764`, `factory-agent/factory_agent/services/plan_creation_service.py:808` |
| `replan_context.intent_contract` | Persisted graph trace/state snapshot for UI/history/debugging | `factory-agent/factory_agent/services/planner_owned_graph_runtime.py:354` |

## Safety And Guardrails

The graph locks deterministic constraints before planner execution and rejects planner revisions that drop or mutate locked constraints.

Check: initial requirement ledger records locked constraints and revision history in `factory-agent/factory_agent/planning/v2_capability_map.py:260` and `factory-agent/factory_agent/planning/v2_capability_map.py:418`; validation rejects dropped or changed locked values in `factory-agent/factory_agent/planning/v2_planner_decisions.py:190`.

The planner cannot authorize execution by itself. Execution is only allowed after the graph records and validates a matching `execute_tool` or `execute_parallel_read_batch` decision.

Check: `require_graph_execution_authorization` enforces persisted validated execution decisions in `factory-agent/factory_agent/planning/v2_graph_adapters.py:110`.

Tool choice is constrained to hydrated candidate windows and approval requests must target approval-gated tools.

Check: candidate-window validation is in `factory-agent/factory_agent/planning/v2_planner_decisions.py:401`; approval-gated validation is in `factory-agent/factory_agent/planning/v2_planner_decisions.py:293`.

RAG answers are forced to insufficient-context output if they do not have acceptable citations or source support.

Check: `AnswerGenerator._validate_answer` is called after LLM generation in `factory-agent/factory_agent/rag/generation.py:219`; `answer_or_insufficient_context` is used when building v2 RAG evidence in `factory-agent/factory_agent/planning/v2_rag_tool.py:80`; tests cover uncited answer rejection in `factory-agent/tests/test_rag_generation.py:260`.

Graph-native approvals check stale session state, expiry, and ledger revision before resuming.

Check: the approval route rejects expired/stale approvals and ledger mismatch in `factory-agent/factory_agent/api/routers/approvals.py:111`; resume uses checkpoint/ledger values from approval payload in `factory-agent/factory_agent/services/approval_resume_service.py:366`.

## Worked Example: `Show machine M-LTH-77 status.`

1. The frontend posts the user message and creates a plan.

   Check: `runIntent` posts message then calls `createPlan` in `eMas Front/src/components/features/chat/factory-agent/useFactoryAgentChat.js:611`.

2. `messages.py` stores the message, indexes it, sets `current_intent` to `Show machine M-LTH-77 status.`, and marks the session `PLANNING`.

   Check: message persistence and status/current-intent update are in `factory-agent/factory_agent/api/routers/messages.py:80` and `factory-agent/factory_agent/api/routers/messages.py:234`.

3. `create_plan` enters the v2 planner-owned graph path with registry tools plus `rag_search_documents`.

   Check: v2 branch and `ensure_v2_rag_tool` are in `factory-agent/factory_agent/services/plan_creation_service.py:1053` and `factory-agent/factory_agent/planning/v2_rag_tool.py:61`.

4. Initial graph state builds one machine operational-state requirement and a capability need.

   Check: initial graph state and deterministic capability needs are built in `factory-agent/factory_agent/planning/v2_agent_state.py:174`; query-to-requirement sketch logic calls `semantic_frame_for_text` in `factory-agent/factory_agent/planning/v2_capability_map.py:193`.

5. `planner_decision_node` requests retrieval for the open requirement.

   Check: it builds a `PlannerDecisionProposalContext` with requested kind `retrieve_tools` in `factory-agent/factory_agent/graph/v2_agent_graph.py:669`.

6. `tool_retrieval_node` asks the tool selector for candidates and hydrates cards.

   Check: retrieval calls `select_tools` and stores candidates/cards in `factory-agent/factory_agent/planning/v2_tool_retriever.py:90`.

7. `planner_choose_tool_node` selects a matching machine status tool from the hydrated window.

   Check: choice logic records selected tool names in `factory-agent/factory_agent/graph/v2_agent_graph.py:841`; tests assert the selected tool is `get__machines_{id}` for this query in `factory-agent/tests/test_planner_owned_graph_shell_contract.py:152`.

8. `tool_execution_node` records a deterministic execution guard and calls the HTTP tool adapter.

   Check: deterministic `execute_tool` guard and call to adapter are in `factory-agent/factory_agent/graph/v2_agent_graph.py:971`; HTTP execution uses `execute_tool_http` in `factory-agent/factory_agent/graph/http_tool_client.py:62`.

9. `evidence_observation_node` converts the result into typed evidence.

   Check: evidence append is in `factory-agent/factory_agent/graph/v2_agent_graph.py:1042`; test asserts evidence tool name and final validation pass in `factory-agent/tests/test_planner_owned_graph_shell_contract.py:154`.

10. `satisfaction_node`, `finalize_node`, and `response_document_node` deterministically validate and render the response.

    Check: satisfaction/final validation are in `factory-agent/factory_agent/graph/v2_agent_graph.py:1124`; finalize decision is in `factory-agent/factory_agent/graph/v2_agent_graph.py:1197`; response document context is in `factory-agent/factory_agent/graph/v2_agent_graph.py:1249`.

## Verification Ledger

| Item | Check Performed |
|:---|:---|
| Frontend query flow | Read `factoryAgentApi.js` and `useFactoryAgentChat.js`; traced `addMessage` and `createPlan` calls. |
| API route flow | Read sessions, messages, plans, approvals, and execution routers. |
| Current engine | Checked `normalize_factory_agent_engine` always resolves `"v2"` and `create_plan` v2 branch is first for no-draft normal planning. |
| Graph node order | Checked `PLANNER_OWNED_AGENT_GRAPH_NODE_ORDER`, `_compile_graph`, and node-order pytest. |
| Per-node behavior | Read every node method body from `_semantic_intake_node` through `_response_document_node`. |
| Planner LLM prompt | Read `_build_planner_decision_prompt`, proposer invocation, model builder, and LLM proposer tests. |
| Tool selector LLM prompt | Read `_build_rerank_prompt`, `_should_rerank`, `_invoke_reranker`, and selector config defaults. |
| RAG answer prompt | Read `ANSWER_PROMPT`, generator invocation, RAG answer contract tests, and RAG generation tests. |
| RAG documents | Read `source_register.json` and `document_registry.py`. |
| API tool execution | Read `execute_graph_api_tool_call` and `execute_tool_http`. |
| RAG tool execution | Read virtual RAG tool definition, `execute_graph_rag_tool`, and `RAGPipeline`. |
| Approval resume | Read approval router, approval resume service, graph resume path, and checkpoint factory. |
| Persistence projection | Read `PlannerOwnedGraphRuntimeAdapter.persist_result`, `_graph_context`, `_plan_artifacts`, and `_persist_plan`. |
| Safety/fail-closed claims | Read decision validation, authorization validation, stale approval checks, and tests for malformed proposer output. |

## Focused Tests Worth Running After Changes

These are the tests I used as source-level checks and would use as the minimum regression gate for this area:

```powershell
Set-Location "C:\Users\dilun\OneDrive\Documents\eMas APi"
.\factory-agent\.venv\Scripts\python.exe -m pytest `
  factory-agent/tests/test_planner_owned_graph_shell_contract.py `
  factory-agent/tests/test_planner_owned_graph_llm_proposer.py `
  factory-agent/tests/test_planner_owned_graph_runtime_adapter.py `
  factory-agent/tests/test_rag_generation.py `
  factory-agent/tests/test_rag_answer_contract.py `
  -q
```

Check: these files directly cover the graph node order, planner decision guardrails, runtime persistence projection, RAG prompt/citation behavior, and answer validation contracts.

Latest verification run from this workspace:

```text
57 passed, 14 warnings in 33.06s
```

Check: ran the command above on 2026-05-25 after creating this document; warnings were deprecation/runtime warnings and no test failed.
