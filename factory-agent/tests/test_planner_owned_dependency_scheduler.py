from __future__ import annotations

from typing import Any

from factory_agent.planning.v2_agent_state import PlannerOwnedAgentGraphState
from factory_agent.planning.v2_contracts import (
    CandidateTool,
    CandidateToolWindow,
    CapabilityNeed,
    EvidenceLedgerEntry,
    HydratedToolCard,
    HydratedToolCards,
    RequirementLedger,
    RequirementLedgerEntry,
)
from factory_agent.planning.v2_dependency_scheduler import build_dependency_plan
from factory_agent.services.planner_activity_captions import (
    build_activity_caption_context_from_graph_state,
    enrich_activity_step_rows,
)


def _requirement(
    requirement_id: str,
    *,
    requirement_type: str = "single_entity_status",
    entity: str | None = "machine",
    intent_operation: str = "report_status",
    source_of_truth: str = "operational_state",
    constraints: dict[str, Any] | None = None,
    requested_fields: list[str] | None = None,
    status: str = "open",
    required: bool = True,
    depends_on: list[str] | None = None,
    parent_requirement_id: str | None = None,
    derived_from_evidence_refs: list[str] | None = None,
) -> RequirementLedgerEntry:
    return RequirementLedgerEntry(
        id=requirement_id,
        goal=f"Requirement {requirement_id}",
        requirement_type=requirement_type,  # type: ignore[arg-type]
        entity=entity,
        intent_operation=intent_operation,  # type: ignore[arg-type]
        source_of_truth=source_of_truth,  # type: ignore[arg-type]
        constraints=({f"{entity}_id": f"{entity.upper()}-001"} if constraints is None and entity else constraints or {}),
        requested_fields=requested_fields or ["status"],
        status=status,  # type: ignore[arg-type]
        required=required,
        depends_on=list(depends_on or []),
        parent_requirement_id=parent_requirement_id,
        derived_from_evidence_refs=list(derived_from_evidence_refs or []),
    )


def _card(
    tool_name: str,
    *,
    source_of_truth: str = "operational_state",
    actions: list[str] | None = None,
    required_args: list[str] | None = None,
    path_params: list[str] | None = None,
    endpoint_shape: str = "item",
    is_read_only: bool = True,
    requires_approval: bool = False,
    side_effect_level: str = "NONE",
    supports_filters: bool = False,
    supports_limit: bool = False,
) -> HydratedToolCard:
    return HydratedToolCard(
        tool_name=tool_name,
        source_of_truth=source_of_truth,  # type: ignore[arg-type]
        actions=actions or ["read_one", "read"],  # type: ignore[arg-type]
        required_args=required_args or ["id"],
        path_params=path_params or ["id"],
        supports_filters=supports_filters,
        supports_limit=supports_limit,
        is_read_only=is_read_only,
        requires_approval=requires_approval,
        metadata={
            "endpoint_shape": endpoint_shape,
            "endpoint_root": tool_name.split("__", 1)[-1].split("_", 1)[0],
            "side_effect_level": side_effect_level,
        },
    )


def _state(
    requirements: list[RequirementLedgerEntry],
    *,
    cards: dict[str, list[HydratedToolCard]] | None = None,
    candidates: dict[str, list[CandidateTool]] | None = None,
    evidence: list[EvidenceLedgerEntry] | None = None,
) -> PlannerOwnedAgentGraphState:
    state = PlannerOwnedAgentGraphState(
        original_query="planner owned dependency scheduler test",
        requirement_ledger=RequirementLedger(
            user_goal="planner owned dependency scheduler test",
            requirements=requirements,
        ),
    )
    state.hydrated_tool_cards = [
        HydratedToolCards(requirement_id=requirement_id, cards=card_list)
        for requirement_id, card_list in (cards or {}).items()
    ]
    state.candidate_tool_windows = [
        CandidateToolWindow(
            requirement_id=requirement_id,
            capability_need=CapabilityNeed(
                source_of_truth="operational_state",
                entity="machine",
                action="read_one",
                requirement_id=requirement_id,
            ),
            candidates=candidate_list,
        )
        for requirement_id, candidate_list in (candidates or {}).items()
    ]
    state.evidence_ledger.evidence = list(evidence or [])
    return state


def _labels(plan):
    return {item.requirement_id: item.label for item in plan.requirements}


def _items(plan):
    return {item.requirement_id: item for item in plan.requirements}


def test_dependency_scheduler_labels_satisfied_and_terminal_requirements_not_ready():
    state = _state(
        [
            _requirement("req-satisfied", status="satisfied"),
            _requirement("req-failed", status="failed"),
            _requirement("req-skipped", status="skipped"),
            _requirement("req-superseded", status="superseded"),
        ]
    )

    plan = build_dependency_plan(state)

    assert set(_labels(plan).values()) == {"satisfied_or_terminal"}
    assert all(item.ready is False for item in plan.requirements)
    assert plan.ready_groups == []


def test_dependency_scheduler_labels_blocked_requirement_not_ready_variant():
    state = _state([_requirement("req-blocked", status="blocked")])

    plan = build_dependency_plan(state)

    item = _items(plan)["req-blocked"]
    assert item.label == "blocked"
    assert item.ready is False
    assert item.blocked_reasons == ["requirement_status_blocked"]


def test_dependency_scheduler_labels_child_requirement_depends_on_parent_evidence():
    state = _state(
        [
            _requirement("req-parent", constraints={"job_id": "JOB-001"}, entity="job"),
            _requirement(
                "req-parent.a",
                entity="product",
                constraints={"product_id": "P-001"},
                parent_requirement_id="req-parent",
                derived_from_evidence_refs=["ev-parent"],
            ),
        ],
        cards={"req-parent.a": [_card("get__products_{id}")]},
    )

    plan = build_dependency_plan(state)

    child = _items(plan)["req-parent.a"]
    assert child.label == "depends_on_evidence"
    assert child.ready is False
    assert child.depends_on_requirement_ids == ["req-parent"]
    assert child.depends_on_evidence_refs == ["ev-parent"]
    assert "missing_active_parent_evidence:req-parent" in child.blocked_reasons
    assert "missing_active_evidence_ref:ev-parent" in child.blocked_reasons


def test_dependency_scheduler_rejects_stale_parent_evidence_variant():
    evidence = EvidenceLedgerEntry(
        id="ev-parent",
        requirement_id="req-parent",
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name="get__jobs_{id}",
        normalized_result={"fields": {"job_id": "JOB-001", "product_id": "P-001"}},
        diagnostic_metadata={"active_revision_satisfaction": False, "stale_after_graph_replan": True},
    )
    state = _state(
        [
            _requirement("req-parent", constraints={"job_id": "JOB-001"}, entity="job"),
            _requirement(
                "req-parent.a",
                entity="product",
                constraints={"product_id": "P-001"},
                parent_requirement_id="req-parent",
                derived_from_evidence_refs=["ev-parent"],
                depends_on=["ev-parent"],
            ),
        ],
        cards={"req-parent.a": [_card("get__products_{id}")]},
        evidence=[evidence],
    )

    child = _items(build_dependency_plan(state))["req-parent.a"]

    assert child.label == "depends_on_evidence"
    assert child.ready is False
    assert "missing_active_evidence_ref:ev-parent" in child.blocked_reasons


def test_dependency_scheduler_marks_child_ready_after_active_parent_evidence():
    evidence = EvidenceLedgerEntry(
        id="ev-parent",
        requirement_id="req-parent",
        source_type="api_tool",
        source_of_truth="operational_state",
        tool_name="get__jobs_{id}",
        normalized_result={"fields": {"job_id": "JOB-001", "product_id": "P-001"}},
        diagnostic_metadata={"active_revision_satisfaction": True},
    )
    state = _state(
        [
            _requirement("req-parent", constraints={"job_id": "JOB-001"}, entity="job"),
            _requirement(
                "req-parent.a",
                entity="product",
                constraints={"product_id": "P-001"},
                parent_requirement_id="req-parent",
                derived_from_evidence_refs=["ev-parent"],
            ),
        ],
        cards={"req-parent.a": [_card("get__products_{id}")]},
        evidence=[evidence],
    )

    child = _items(build_dependency_plan(state))["req-parent.a"]

    assert child.label == "independent_read"
    assert child.ready is True
    assert child.depends_on_requirement_ids == ["req-parent"]
    assert child.depends_on_evidence_refs == ["ev-parent"]


def test_dependency_scheduler_labels_mutation_as_approval_required():
    state = _state(
        [
            _requirement(
                "req-update",
                requirement_type="mutation_request",
                intent_operation="stage_mutation",
                entity="job",
                constraints={"priority": "high", "new_priority": "medium", "requires_approval": True},
            )
        ],
        cards={
            "req-update": [
                _card(
                    "put__jobs_{id}",
                    actions=["update"],
                    is_read_only=False,
                    requires_approval=True,
                    side_effect_level="HIGH",
                    endpoint_shape="mutation",
                )
            ]
        },
    )

    item = _items(build_dependency_plan(state))["req-update"]

    assert item.label == "approval_required"
    assert item.ready is True
    assert item.can_batch is False


def test_dependency_scheduler_serializes_mutation_until_prerequisite_read_is_satisfied_variant():
    state = _state(
        [
            _requirement("req-read", entity="job", constraints={"job_id": "JOB-001"}),
            _requirement(
                "req-update",
                requirement_type="mutation_request",
                intent_operation="stage_mutation",
                entity="job",
                constraints={"job_id": "JOB-001", "new_priority": "medium", "requires_approval": True},
                depends_on=["req-read"],
            ),
        ],
        cards={
            "req-update": [
                _card(
                    "put__jobs_{id}",
                    actions=["update"],
                    is_read_only=False,
                    requires_approval=True,
                    side_effect_level="HIGH",
                    endpoint_shape="mutation",
                )
            ]
        },
    )

    item = _items(build_dependency_plan(state))["req-update"]

    assert item.label == "approval_required"
    assert item.ready is False
    assert item.depends_on_requirement_ids == ["req-read"]
    assert item.blocked_reasons == ["missing_active_parent_evidence:req-read"]


def test_independent_machine_and_job_reads_are_ready_together():
    state = _state(
        [
            _requirement("req-machine", entity="machine", constraints={"machine_id": "M-001"}),
            _requirement("req-job", entity="job", constraints={"job_id": "JOB-001"}),
        ],
        cards={
            "req-machine": [_card("get__machines_{id}")],
            "req-job": [_card("get__jobs_{id}")],
        },
    )

    plan = build_dependency_plan(state)

    assert _labels(plan) == {
        "req-machine": "independent_read",
        "req-job": "independent_read",
    }
    assert all(item.ready for item in plan.requirements)
    assert len(plan.ready_groups) == 1
    assert plan.ready_groups[0].mode == "parallel_read_batch"
    assert plan.ready_groups[0].requirement_ids == ["req-machine", "req-job"]


def test_scheduler_uses_candidate_source_when_hydrated_card_source_is_unknown_variant():
    state = _state(
        [_requirement("req-machine", entity="machine", constraints={"machine_id": "M-001"})],
        cards={
            "req-machine": [
                _card(
                    "get__machines_{id}",
                    source_of_truth="unknown",
                )
            ],
        },
        candidates={
            "req-machine": [
                CandidateTool(
                    tool_name="get__machines_{id}",
                    rank=1,
                    source_of_truth="operational_state",
                    actions=["read_one", "read"],
                )
            ],
        },
    )

    item = _items(build_dependency_plan(state))["req-machine"]

    assert item.label == "independent_read"
    assert item.ready is True
    assert item.can_batch is True


def test_unbounded_collection_read_is_not_batched_with_single_entity_reads():
    state = _state(
        [
            _requirement("req-machine", entity="machine", constraints={"machine_id": "M-001"}),
            _requirement(
                "req-jobs",
                requirement_type="filtered_collection",
                intent_operation="report_filtered_collection",
                entity="job",
                constraints={"priority": "low"},
            ),
        ],
        cards={
            "req-machine": [_card("get__machines_{id}")],
            "req-jobs": [
                _card(
                    "get__jobs",
                    actions=["list", "read_many", "read"],
                    required_args=[],
                    path_params=[],
                    endpoint_shape="collection",
                    supports_filters=True,
                    supports_limit=True,
                )
            ],
        },
    )

    plan = build_dependency_plan(state)

    assert _items(plan)["req-machine"].label == "independent_read"
    assert _items(plan)["req-jobs"].label == "sequential_read"
    assert plan.ready_groups == []


def test_unhydrated_collection_read_is_sequential_before_tool_metadata_variant():
    state = _state(
        [
            _requirement(
                "req-jobs",
                requirement_type="multi_entity_status",
                intent_operation="report_multi_status",
                entity="job",
                constraints={},
            ),
        ]
    )

    plan = build_dependency_plan(state)

    item = _items(plan)["req-jobs"]
    assert item.label == "sequential_read"
    assert item.ready is True
    assert item.can_batch is False
    assert plan.ready_groups == []


def test_document_and_api_reads_do_not_batch_unless_supported_by_contract_variant():
    state = _state(
        [
            _requirement("req-machine", entity="machine", constraints={"machine_id": "M-001"}),
            _requirement(
                "req-doc",
                requirement_type="document_answer",
                intent_operation="answer_document_question",
                source_of_truth="document_knowledge",
                entity=None,
                constraints={"query": "LOTO procedure"},
            ),
        ],
        cards={
            "req-machine": [_card("get__machines_{id}")],
            "req-doc": [
                _card(
                    "rag_search_documents",
                    source_of_truth="document_knowledge",
                    actions=["search_documents", "read"],
                    required_args=["query"],
                    path_params=[],
                    endpoint_shape="document_search",
                )
            ],
        },
    )

    plan = build_dependency_plan(state)

    assert _items(plan)["req-doc"].label == "sequential_read"
    assert plan.ready_groups == []


def test_parallel_read_batch_caps_ready_group_at_three_calls():
    state = _state(
        [
            _requirement(f"req-{index}", entity="job", constraints={"job_id": f"JOB-{index:03d}"})
            for index in range(1, 5)
        ],
        cards={f"req-{index}": [_card("get__jobs_{id}")] for index in range(1, 5)},
    )

    group = build_dependency_plan(state).ready_groups[0]

    assert group.mode == "parallel_read_batch"
    assert group.requirement_ids == ["req-1", "req-2", "req-3"]
    assert group.max_batch_size == 3


def test_parallel_read_batch_caption_uses_ready_group_count_and_entity():
    state = _state(
        [
            _requirement(f"req-{index}", entity="job", constraints={"job_id": f"JOB-{index:03d}"})
            for index in range(1, 5)
        ],
        cards={f"req-{index}": [_card("get__jobs_{id}")] for index in range(1, 5)},
    )
    plan = build_dependency_plan(state)
    state.execution_trace.diagnostics["dependency_plan"] = plan.model_dump(mode="json")
    state.execution_trace.diagnostics["dependency_plan_history"] = [
        {
            "ready_groups": [group.model_dump(mode="json") for group in plan.ready_groups],
            "ready_requirement_ids": [rid for group in plan.ready_groups for rid in group.requirement_ids],
        }
    ]

    rows = enrich_activity_step_rows(
        [],
        {
            "intent_contract": {
                "activity_caption_context": build_activity_caption_context_from_graph_state(state),
            }
        },
        fallback_timestamp=1_770_000_000,
        session_status="EXECUTING",
    )

    batch = next(row for row in rows if row["label"] == "Reading 3 job records")
    assert batch["detail"] == "Parallel read batch scheduled"
    assert batch["state"] == "running"


def test_parallel_read_batch_caption_uses_estimated_call_count_for_single_requirement():
    state = _state(
        [
            _requirement(
                "req-1",
                requirement_type="multi_entity_status",
                entity="job",
                intent_operation="report_multi_status",
                constraints={"job_id": ["JOB-SEED-001", "JOB-SEED-002", "JOB-SEED-003"]},
                requested_fields=[],
            )
        ],
        cards={"req-1": [_card("get__jobs_{id}")]},
    )
    state.execution_trace.diagnostics["dependency_plan_history"] = [
        {
            "ready_groups": [
                {
                    "group_id": "dependency-group-001",
                    "mode": "parallel_read_batch",
                    "requirement_ids": ["req-1"],
                    "diagnostic_metadata": {"estimated_tool_call_count": 3},
                }
            ],
            "ready_requirement_ids": ["req-1"],
        }
    ]

    rows = enrich_activity_step_rows(
        [],
        {
            "intent_contract": {
                "activity_caption_context": build_activity_caption_context_from_graph_state(state),
            }
        },
        fallback_timestamp=1_770_000_000,
        session_status="EXECUTING",
    )

    labels = [row["label"] for row in rows]
    assert "Reading 3 job records" in labels
    assert "Reading job records" not in labels


def test_parallel_read_batch_caption_does_not_insert_into_older_graph_pass():
    state = _state(
        [
            _requirement("req-product-1", entity="product", constraints={"product_id": "P-001"}),
            _requirement("req-product-2", entity="product", constraints={"product_id": "P-002"}),
        ],
        cards={
            "req-product-1": [_card("get__products_{id}")],
            "req-product-2": [_card("get__products_{id}")],
        },
    )
    plan = build_dependency_plan(state)
    state.execution_trace.diagnostics["dependency_plan"] = plan.model_dump(mode="json")
    state.execution_trace.diagnostics["dependency_plan_history"] = [
        {
            "ready_groups": [group.model_dump(mode="json") for group in plan.ready_groups],
            "ready_requirement_ids": [rid for group in plan.ready_groups for rid in group.requirement_ids],
        }
    ]
    rows = [
        {
            "id": "graph:000006:tool_execution_node",
            "timestamp": 6,
            "order": 6,
            "group": "research",
            "label": "Running selected tool",
            "detail": "Checking relevant records",
            "state": "success",
        },
        {
            "id": "graph:000007:evidence_observation_node",
            "timestamp": 7,
            "order": 7,
            "group": "response",
            "label": "Checking result",
            "detail": "Checking tool evidence",
            "state": "success",
        },
        {
            "id": "graph:000008:satisfaction_node",
            "timestamp": 8,
            "order": 8,
            "group": "response",
            "label": "Verifying result",
            "detail": "Verifying the result",
            "state": "success",
        },
        {
            "id": "graph:000009:planner_decision_node",
            "timestamp": 9,
            "order": 9,
            "group": "planning",
            "label": "Choosing next action",
            "detail": "Choosing the next backend action",
            "state": "running",
        },
    ]

    enriched = enrich_activity_step_rows(
        rows,
        {
            "intent_contract": {
                "activity_caption_context": build_activity_caption_context_from_graph_state(state),
            }
        },
        fallback_timestamp=1,
        session_status="EXECUTING",
    )
    labels = [row["label"] for row in enriched]

    assert labels.index("Reading 2 product records") > labels.index("Verifying result")
    assert labels.index("Reading 2 product records") > labels.index("Choosing next action")


def test_dependency_scheduler_fails_closed_when_read_label_cannot_be_proven_variant():
    state = _state(
        [
            _requirement(
                "req-unknown",
                source_of_truth="unknown",
                entity=None,
                constraints={},
            )
        ]
    )

    item = _items(build_dependency_plan(state))["req-unknown"]

    assert item.label == "blocked"
    assert item.ready is False
    assert item.blocked_reasons == ["dependency_label_not_proven"]
