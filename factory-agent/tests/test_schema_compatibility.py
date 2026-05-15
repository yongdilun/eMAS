from __future__ import annotations

import main
import pytest


class _FakeDialect:
    name = "mysql"


class _FakeConnection:
    dialect = _FakeDialect()

    def __init__(self) -> None:
        self.sql: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.sql.append(statement)

    def execute(self, statement) -> None:
        self.sql.append(str(statement))


class _FakeInspector:
    def get_table_names(self) -> list[str]:
        return ["sessions", "approvals"]

    def get_columns(self, table: str) -> list[dict[str, object]]:
        if table == "sessions":
            return [{"name": "session_id", "nullable": False}, {"name": "name", "nullable": True}]
        if table == "approvals":
            return [
                {"name": "approval_id", "nullable": False},
                {"name": "subject_type", "nullable": False},
                {"name": "plan_id", "nullable": True},
                {"name": "step_id", "nullable": False},
            ]
        return []


def test_schema_compatibility_relaxes_approval_step_id_for_graph_approvals(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr(main, "inspect", lambda sync_conn: _FakeInspector())

    main._ensure_schema_compatibility(conn)

    assert "ALTER TABLE approvals MODIFY step_id VARCHAR(36) NULL" in conn.sql


def test_schema_compatibility_read_only_mode_reports_pending_ddl_without_mutation(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr(main, "inspect", lambda sync_conn: _FakeInspector())

    with pytest.raises(RuntimeError, match="ENABLE_STARTUP_SCHEMA_COMPAT=0"):
        main._ensure_schema_compatibility(conn, allow_mutation=False)

    assert conn.sql == []
