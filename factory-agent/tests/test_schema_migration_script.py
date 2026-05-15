from __future__ import annotations

from scripts import migrate_mysql_schema_safe


def test_mysql_migration_script_runs_startup_compatibility_migrations(monkeypatch):
    calls: list[tuple[object, bool]] = []

    def fake_ensure(conn, *, allow_mutation: bool) -> None:
        calls.append((conn, allow_mutation))

    monkeypatch.setattr(migrate_mysql_schema_safe, "_ensure_schema_compatibility", fake_ensure)
    conn = object()

    migrate_mysql_schema_safe.apply_compatibility_migrations(conn)

    assert calls == [(conn, True)]
