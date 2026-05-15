from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateColumn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import factory_agent.persistence.models as models  # noqa: F401
from factory_agent.persistence.database import Base
from main import _ensure_schema_compatibility


def _quote(name: str) -> str:
    return f"`{name}`"


def _to_sync_url(url: str) -> str:
    return url.replace("+aiomysql", "+pymysql")


def apply_compatibility_migrations(conn) -> None:
    _ensure_schema_compatibility(conn, allow_mutation=True)


def migrate(database_url: str) -> None:
    sync_url = _to_sync_url(database_url)
    engine = create_engine(sync_url, echo=False, future=True)
    dialect = mysql.dialect()

    with engine.begin() as conn:
        inspector = inspect(conn)
        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                print(f"[CREATE] table {table_name}")
                table.create(bind=conn, checkfirst=True)
                continue

            db_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name in db_cols:
                    continue
                col_def = str(CreateColumn(col).compile(dialect=dialect)).strip()
                sql = f"ALTER TABLE {_quote(table_name)} ADD COLUMN {col_def}"
                print(f"[ADD COLUMN] {table_name}.{col.name}")
                conn.execute(text(sql))

            db_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
            for idx in table.indexes:
                if idx.name in db_indexes:
                    continue
                print(f"[ADD INDEX] {idx.name} on {table_name}")
                idx.create(bind=conn, checkfirst=True)

        apply_compatibility_migrations(conn)

    engine.dispose()


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required")
    migrate(url)
    print("Safe schema migration completed.")

