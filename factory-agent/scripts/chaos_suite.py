from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass

import httpx


@dataclass
class ChaosResult:
    name: str
    passed: bool
    detail: str


def run_hook(command: str | None) -> None:
    if not command:
        return
    subprocess.run(command, shell=True, check=True)


def wait_for_status(client: httpx.Client, session_id: str, expected: set[str], timeout_s: int = 60) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = client.get(f"/sessions/{session_id}")
        if resp.status_code == 200:
            status = resp.json().get("status")
            if status in expected:
                return status
        time.sleep(1)
    raise TimeoutError(f"session {session_id} did not reach one of {expected}")


def redis_failure_test(client: httpx.Client, session_id: str, stop_hook: str | None, start_hook: str | None) -> ChaosResult:
    try:
        run_hook(stop_hook)
        status = wait_for_status(client, session_id, {"BLOCKED", "WAITING_APPROVAL"}, timeout_s=45)
        run_hook(start_hook)
        resumed = wait_for_status(client, session_id, {"EXECUTING", "COMPLETED", "WAITING_APPROVAL"}, timeout_s=90)
        return ChaosResult("redis_failure", True, f"blocked={status} resumed={resumed}")
    except Exception as e:
        return ChaosResult("redis_failure", False, str(e))


def db_failure_test(client: httpx.Client, session_id: str, stop_hook: str | None, start_hook: str | None) -> ChaosResult:
    try:
        run_hook(stop_hook)
        time.sleep(5)
        run_hook(start_hook)
        time.sleep(5)
        session = client.get(f"/sessions/{session_id}")
        if session.status_code != 200:
            return ChaosResult("db_failure", False, f"session fetch failed: {session.status_code}")
        # Operator can validate plan step status from admin/dashboard or DB query.
        return ChaosResult("db_failure", True, f"session_status={session.json().get('status')}")
    except Exception as e:
        return ChaosResult("db_failure", False, str(e))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run chaos checks against factory-agent.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--session-id", required=True, help="Existing active session ID used for chaos scenarios.")
    parser.add_argument("--stop-redis-hook", default=None, help="Shell command to stop Redis.")
    parser.add_argument("--start-redis-hook", default=None, help="Shell command to start Redis.")
    parser.add_argument("--stop-db-hook", default=None, help="Shell command to stop DB.")
    parser.add_argument("--start-db-hook", default=None, help="Shell command to start DB.")
    args = parser.parse_args()

    results: list[ChaosResult] = []
    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        results.append(redis_failure_test(client, args.session_id, args.stop_redis_hook, args.start_redis_hook))
        results.append(db_failure_test(client, args.session_id, args.stop_db_hook, args.start_db_hook))

    output = [
        {"name": r.name, "passed": r.passed, "detail": r.detail}
        for r in results
    ]
    print(json.dumps(output, indent=2))
    failed = [r for r in results if not r.passed]
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
