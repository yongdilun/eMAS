from __future__ import annotations

from factory_agent.planning.tool_output_alignment import align_tool_outputs_to_steps


def test_align_matches_tools_in_order():
    rows = [
        {"tool_name": "get__machines", "http_status": 200, "result": {"items": [{"machine_id": "M-CNC"}]}},
        {"tool_name": "get__materials", "http_status": 200, "result": {"items": [{"material_id": "MAT-001"}]}},
    ]
    aligned = align_tool_outputs_to_steps(step_tool_names=["get__machines", "get__materials"], tool_outputs=rows)
    assert len(aligned) == 2
    assert aligned[0][0] == {"items": [{"machine_id": "M-CNC"}]}
    assert aligned[1][0] == {"items": [{"material_id": "MAT-001"}]}


def test_align_skips_non_matching_scan():
    rows = [
        {"tool_name": "get__health", "http_status": 200, "result": {"ok": True}},
        {"tool_name": "get__machines", "http_status": 200, "result": {"items": [{"machine_id": "M-X"}]}},
    ]
    aligned = align_tool_outputs_to_steps(step_tool_names=["get__machines"], tool_outputs=rows)
    assert aligned[0][0] == {"items": [{"machine_id": "M-X"}]}


def test_align_ignores_http_errors():
    rows = [
        {"tool_name": "get__machines", "http_status": 503, "result": {"detail": "no"}},
        {"tool_name": "get__machines", "http_status": 200, "result": {"items": []}},
    ]
    aligned = align_tool_outputs_to_steps(step_tool_names=["get__machines"], tool_outputs=rows)
    assert aligned[0][0] == {"items": []}


def test_align_keeps_not_found_client_result_for_operator_summary():
    rows = [
        {"tool_name": "get__machines_{id}", "http_status": 404, "result": {"detail": "machine not found"}},
    ]

    aligned = align_tool_outputs_to_steps(step_tool_names=["get__machines_{id}"], tool_outputs=rows)

    assert aligned[0][0] == {"detail": "machine not found"}
    assert aligned[0][1] == "machine not found"


def test_align_builds_operator_summary_from_list_result():
    rows = [
        {
            "tool_name": "get__jobs",
            "http_status": 200,
            "args": {"priority": "low"},
            "result": {
                "data": [
                    {"job_id": "JOB-SEED-005", "product_id": "P-005", "priority": "low"},
                    {"job_id": "JOB-SEED-009", "product_id": "P-003", "priority": "low"},
                ]
            },
        }
    ]

    aligned = align_tool_outputs_to_steps(step_tool_names=["get__jobs"], tool_outputs=rows)

    assert aligned[0][1] == (
        "Found 2 low-priority jobs: JOB-SEED-005, JOB-SEED-009. "
        "Details are shown in the table below."
    )


def test_align_prefers_provided_operator_summary():
    rows = [
        {
            "tool_name": "post__jobs",
            "http_status": 200,
            "args": {"product_id": "P-005", "quantity_total": 4},
            "result": {"success": True, "data": {"job_id": "JOB-NEW-004"}},
            "summary": "Created job JOB-NEW-004 for quantity 4.",
        }
    ]

    aligned = align_tool_outputs_to_steps(step_tool_names=["post__jobs"], tool_outputs=rows)

    assert aligned[0][1] == "Created job JOB-NEW-004 for quantity 4."
