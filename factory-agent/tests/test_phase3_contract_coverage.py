from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import database
from factory_agent.api import build_router
from factory_agent.config import Settings
from factory_agent.persistence import database as persistence_database
from factory_agent.persistence.models import Approval, Session
from factory_agent.registry.tool_registry import ToolRegistry


class _FakeEventBus:
    async def publish(self, event: object) -> None:
        return None

    async def listen(self, handler: object) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url=None,
        go_api_base_url="http://testserver",
        admin_api_key="test-admin-key",
        worker_count=0,
        session_queue_size=10,
        max_plan_steps=10,
        max_session_steps=50,
        max_replans=5,
        max_llm_calls=20,
        max_session_duration_s=1800,
        http_timeout_s=1.0,
        jwt_required=False,
        enforce_tool_registry_health=False,
        auto_repair_tool_registry=False,
        min_healthy_tool_count=0,
    )


async def _make_app(sessionmaker_override) -> FastAPI:
    app = FastAPI()

    async def override_get_db():
        async with sessionmaker_override() as session:
            yield session

    app.dependency_overrides[database.get_db] = override_get_db
    app.dependency_overrides[persistence_database.get_db] = override_get_db
    app.include_router(build_router(settings=_settings(), tool_registry=ToolRegistry(), event_bus=_FakeEventBus()))
    return app


EXPECTED_PATH_METHODS = {
    "/admin/approvals/pending": ["get"],
    "/admin/dashboard": ["get"],
    "/admin/dlq": ["get"],
    "/admin/faults/redis/down": ["post"],
    "/admin/faults/redis/up": ["post"],
    "/admin/regenerate-tools": ["post"],
    "/admin/sessions": ["get"],
    "/admin/tools": ["get"],
    "/approvals/pending": ["get"],
    "/approvals/{approval_id}": ["get"],
    "/approvals/{approval_id}/approve": ["post"],
    "/approvals/{approval_id}/reject": ["post"],
    "/dlq": ["get"],
    "/dlq/push": ["post"],
    "/dlq/{dlq_id}/dismiss": ["post"],
    "/dlq/{dlq_id}/replay": ["post"],
    "/dlq/{dlq_id}/replay-request": ["post"],
    "/documents/{doc_id}/pdf": ["get"],
    "/metrics": ["get"],
    "/sessions": ["delete", "get", "post"],
    "/sessions/{session_id}": ["delete", "get", "patch"],
    "/sessions/{session_id}/cancel": ["post"],
    "/sessions/{session_id}/confirm": ["post"],
    "/sessions/{session_id}/events": ["get"],
    "/sessions/{session_id}/events/activity": ["get"],
    "/sessions/{session_id}/events/semantic": ["get"],
    "/sessions/{session_id}/execute": ["post"],
    "/sessions/{session_id}/interactions/{interaction_id}/decide": ["post"],
    "/sessions/{session_id}/messages": ["get", "post"],
    "/sessions/{session_id}/plans": ["post"],
    "/sessions/{session_id}/snapshot": ["get"],
    "/sessions/{session_id}/steps": ["get"],
    "/tools": ["get"],
}


EXPECTED_RESPONSE_REFS = {
    ("post", "/sessions", "200"): "#/components/schemas/SessionResponse",
    ("delete", "/sessions", "200"): "#/components/schemas/SessionBulkDeleteResponse",
    ("get", "/sessions/{session_id}/snapshot", "200"): "#/components/schemas/SessionSnapshotResponse",
    ("get", "/sessions/{session_id}/messages", "200"): {
        "items": {"$ref": "#/components/schemas/MessageResponse"},
        "type": "array",
    },
    ("post", "/sessions/{session_id}/plans", "200"): "#/components/schemas/PlanResponse",
    ("get", "/approvals/pending", "200"): {
        "items": {"$ref": "#/components/schemas/ApprovalResponse"},
        "type": "array",
    },
    ("get", "/dlq", "200"): {
        "items": {"$ref": "#/components/schemas/DeadLetterResponse"},
        "type": "array",
    },
}


USER_AUTH_CONTRACTS = [
    ("delete", "/sessions"),
    ("get", "/sessions/{session_id}/snapshot"),
    ("get", "/sessions/{session_id}/events"),
    ("get", "/sessions/{session_id}/events/activity"),
    ("get", "/sessions/{session_id}/events/semantic"),
    ("get", "/dlq"),
    ("post", "/dlq/push"),
    ("post", "/dlq/{dlq_id}/replay"),
    ("post", "/dlq/{dlq_id}/replay-request"),
    ("post", "/dlq/{dlq_id}/dismiss"),
    ("get", "/documents/{doc_id}/pdf"),
]


ADMIN_AUTH_CONTRACTS = [
    ("get", "/metrics"),
    ("post", "/admin/regenerate-tools"),
    ("get", "/admin/sessions"),
    ("get", "/admin/approvals/pending"),
    ("get", "/admin/dlq"),
    ("get", "/admin/tools"),
    ("post", "/admin/faults/redis/down"),
    ("post", "/admin/faults/redis/up"),
    ("get", "/admin/dashboard"),
]


def _operation_parameters(spec: dict[str, Any], method: str, path: str) -> set[str]:
    return {param["name"] for param in spec["paths"][path][method].get("parameters", [])}


def _json_response_schema(spec: dict[str, Any], method: str, path: str, status_code: str) -> dict[str, Any]:
    return (
        spec["paths"][path][method]["responses"][status_code]
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )


def _contract_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in schema.items() if key != "title"}


@pytest.mark.asyncio
async def test_openapi_route_contract_snapshot(sessionmaker_override):
    app = await _make_app(sessionmaker_override)

    spec = app.openapi()

    assert {path: sorted(methods) for path, methods in spec["paths"].items()} == EXPECTED_PATH_METHODS
    assert set(spec["components"]["schemas"]) >= {
        "ApprovalResponse",
        "DeadLetterResponse",
        "MessageResponse",
        "PlanResponse",
        "SessionBulkDeleteResponse",
        "SessionResponse",
        "SessionSnapshotResponse",
    }
    for (method, path, status_code), expected_schema in EXPECTED_RESPONSE_REFS.items():
        schema = _json_response_schema(spec, method, path, status_code)
        if isinstance(expected_schema, str):
            assert schema == {"$ref": expected_schema}
        else:
            assert _contract_schema(schema) == expected_schema


@pytest.mark.asyncio
async def test_openapi_documents_sensitive_endpoint_auth_contracts(sessionmaker_override):
    app = await _make_app(sessionmaker_override)
    spec = app.openapi()

    for method, path in USER_AUTH_CONTRACTS:
        assert "Authorization" in _operation_parameters(spec, method, path)

    for method, path in ADMIN_AUTH_CONTRACTS:
        assert "X-Admin-Key" in _operation_parameters(spec, method, path)


@pytest.mark.asyncio
async def test_documents_pdf_route_serves_inline_pdf_from_source_register(
    sessionmaker_override,
    tmp_path,
    monkeypatch,
):
    source_root = tmp_path / "rag_sources"
    register_dir = source_root / "00_metadata_templates"
    pdf_dir = source_root / "03_safety_and_maintenance"
    register_dir.mkdir(parents=True)
    pdf_dir.mkdir(parents=True)
    pdf_path = pdf_dir / "osha_lockout_tagout_guide.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    register_path = register_dir / "source_register.json"
    register_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "osha_3120_lockout_tagout",
                        "title": "Control of Hazardous Energy Lockout/Tagout",
                        "file_path": "03_safety_and_maintenance/osha_lockout_tagout_guide.pdf",
                        "source_type": "official_public_pdf",
                        "organization": "OSHA",
                        "domain": "safety_maintenance",
                        "subdomain": "lockout_tagout",
                        "authority_level": "official_public_guidance",
                        "use_for": ["explain lockout tagout"],
                        "do_not_use_for": ["legal or compliance certification"],
                        "related_entities": ["lockout", "tagout"],
                        "risk_level": "high",
                        "license": "public",
                        "version": "2002 (Revised)",
                        "retrieved_date": "2026-05-10",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RAG_SOURCE_REGISTER_PATH", str(register_path))
    app = await _make_app(sessionmaker_override)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/documents/osha_3120_lockout_tagout/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"].lower().startswith("inline;")
    assert response.content.startswith(b"%PDF")


def _approval_row(*, approval_id: str, session_id: str, subject_type: str) -> Approval:
    return Approval(
        approval_id=approval_id,
        session_id=session_id,
        subject_type=subject_type,
        plan_id="legacy-plan" if subject_type == "plan" else None,
        step_id="legacy-step" if subject_type == "step" else None,
        tool_name="post__jobs",
        args={"job_id": "J-001"},
        risk_summary="legacy write approval",
        side_effect_level="HIGH",
        status="PENDING",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_type", ["plan", "step"])
@pytest.mark.parametrize("decision_path", ["approve", "reject"])
async def test_legacy_approval_decision_contracts_are_retired(
    sessionmaker_override,
    db_session,
    subject_type,
    decision_path,
):
    session_id = f"phase3-{subject_type}-{decision_path}"
    approval_id = f"approval-{subject_type}-{decision_path}"
    db_session.add(Session(session_id=session_id, user_id="u1", status="WAITING_APPROVAL"))
    db_session.add(_approval_row(approval_id=approval_id, session_id=session_id, subject_type=subject_type))
    await db_session.commit()

    app = await _make_app(sessionmaker_override)
    body = {"decided_by": "u1"}
    if decision_path == "reject":
        body["rejection_reason"] = "not approved"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/approvals/{approval_id}/{decision_path}", json=body)

    assert response.status_code == 410
    assert "legacy" in response.json()["detail"]
    refreshed = await db_session.get(Approval, approval_id)
    assert refreshed.status == "PENDING"
    assert refreshed.decided_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "json_body", "expected_detail"),
    [
        (
            "/dlq/push",
            {"session_id": "s1", "failure_type": "manual", "reason": "legacy", "payload": {}},
            "legacy step-based DLQ push is retired",
        ),
        (
            "/dlq/dlq-1/replay",
            {"replayed_by": "ops"},
            "legacy step-based DLQ replay is retired",
        ),
        (
            "/dlq/dlq-1/replay-request",
            None,
            "legacy step-based DLQ replay is retired",
        ),
    ],
)
async def test_legacy_dlq_write_contracts_are_retired(sessionmaker_override, path, json_body, expected_detail):
    app = await _make_app(sessionmaker_override)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json=json_body) if json_body is not None else await client.post(path)

    assert response.status_code == 410
    assert expected_detail in response.json()["detail"]


@pytest.mark.asyncio
async def test_graph_native_approval_read_contract_remains_active(sessionmaker_override, db_session):
    session_id = "phase3-graph-approval"
    approval_id = "graph-approval"
    db_session.add(
        Session(
            session_id=session_id,
            user_id="u1",
            status="WAITING_APPROVAL",
            replan_context={"langgraph_pending_approval": {"approval_id": approval_id, "thread_id": session_id}},
        )
    )
    db_session.add(_approval_row(approval_id=approval_id, session_id=session_id, subject_type="graph"))
    await db_session.commit()

    app = await _make_app(sessionmaker_override)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        by_id = await client.get(f"/approvals/{approval_id}")
        pending = await client.get("/approvals/pending", params={"session_id": session_id})

    assert by_id.status_code == 200
    assert by_id.json()["subject_type"] == "graph"
    assert pending.status_code == 200
    assert [row["approval_id"] for row in pending.json()] == [approval_id]
