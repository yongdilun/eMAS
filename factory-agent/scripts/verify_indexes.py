from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


EXPECTED_INDEXES: dict[str, set[str]] = {
    "sessions": {"idx_sessions_user_id", "idx_sessions_status"},
    "messages": {"idx_messages_session_id"},
    "plan_steps": {"idx_plan_steps_session_id", "idx_plan_steps_status", "idx_plan_steps_idempotency"},
    "approvals": {"idx_approvals_session_id", "idx_approvals_status"},
    "execution_snapshots": {"idx_snapshots_session_id"},
    "dead_letters": {"idx_dlq_status", "idx_dlq_session_id"},
}


def _missing_indexes(existing: Iterable[str], expected: set[str]) -> set[str]:
    return expected - set(existing)


async def verify(database_url: str) -> int:
    engine = create_async_engine(database_url, echo=False)
    try:
        async with engine.connect() as conn:
            def _check(sync_conn):
                insp = inspect(sync_conn)
                failed = False
                for table, expected in EXPECTED_INDEXES.items():
                    indexes = insp.get_indexes(table)
                    names = [idx["name"] for idx in indexes]
                    missing = _missing_indexes(names, expected)
                    if missing:
                        failed = True
                        print(f"[FAIL] {table}: missing indexes {sorted(missing)}")
                    else:
                        print(f"[PASS] {table}: all expected indexes present")
                return failed

            failed = await conn.run_sync(_check)
            return 1 if failed else 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify required DB indexes for Phase 4 hardening.")
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(verify(args.database_url)))


if __name__ == "__main__":
    main()
