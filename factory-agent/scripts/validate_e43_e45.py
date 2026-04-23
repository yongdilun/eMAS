from __future__ import annotations

import argparse
import asyncio
import os
import sys
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import Tool, generate_uuid


TOOL_NAME = "get__mock_slow"
ADMIN_KEY = os.getenv("ADMIN_API_KEY", "admin123")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def wait_health(base_url: str, timeout_s: int = 30) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with httpx.Client(base_url=base_url, timeout=2.0) as client:
                r = client.get("/health")
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


async def seed_mock_tool(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)
    maker = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as db:
            existing = (await db.execute(select(Tool).where(Tool.name == TOOL_NAME))).scalars().first()
            if existing:
                existing.endpoint = "/_mock/slow"
                existing.method = "GET"
                existing.input_schema = {"type": "object", "properties": {"ms": {"type": "integer"}}, "required": ["ms"]}
                existing.is_read_only = True
                existing.requires_approval = False
                existing.side_effect_level = "NONE"
                existing.is_concurrency_safe = True
                existing.is_strongly_idempotent = True
                existing.capability_tags = '["chaos","slow"]'
            else:
                db.add(
                    Tool(
                        tool_id=generate_uuid(),
                        name=TOOL_NAME,
                        description="slow mock endpoint for chaos tests",
                        endpoint="/_mock/slow",
                        method="GET",
                        version=1,
                        schema_version=1,
                        input_schema={"type": "object", "properties": {"ms": {"type": "integer"}}, "required": ["ms"]},
                        output_schema={"type": "object"},
                        is_read_only=True,
                        requires_approval=False,
                        side_effect_level="NONE",
                        is_concurrency_safe=True,
                        is_strongly_idempotent=True,
                        capability_tags='["chaos","slow"]',
                    )
                )
            await db.commit()
    finally:
        await engine.dispose()


def start_server(repo_root: str, *, port: int, database_url: str) -> subprocess.Popen:
    py = os.path.join(repo_root, ".venv", "Scripts", "python.exe")
    server_dir = os.path.join(repo_root, "factory-agent")
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["GO_API_BASE_URL"] = f"http://127.0.0.1:{port}"
    env["MAX_CONCURRENT"] = env.get("MAX_CONCURRENT", "100")
    env["MAX_QUEUE"] = env.get("MAX_QUEUE", "500")
    return subprocess.Popen(
        [py, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=server_dir,
        env=env,
    )


def create_session_with_plan(client: httpx.Client, *, slow_ms: int, steps: int) -> str:
    session_id = client.post("/sessions", json={"user_id": "chaos-user"}).json()["session_id"]
    client.post(f"/sessions/{session_id}/messages", json={"role": "user", "content": "run slow chaos workflow"})
    draft_steps = [
        {
            "step_index": i,
            "tool_name": TOOL_NAME,
            "args": {"ms": slow_ms + i},
        }
        for i in range(steps)
    ]
    plan = {
        "draft": {
            "plan_explanation": "Chaos test slow plan",
            "risk_summary": "Read-only slow mock",
            "steps": draft_steps,
        }
    }
    resp = client.post(f"/sessions/{session_id}/plans", json=plan)
    resp.raise_for_status()
    run = client.post(f"/sessions/{session_id}/execute", params={"background": "true"})
    run.raise_for_status()
    return session_id


def wait_session_status(client: httpx.Client, session_id: str, wanted: set[str], timeout_s: int = 120) -> str:
    deadline = time.time() + timeout_s
    last_status = "UNKNOWN"
    while time.time() < deadline:
        resp = client.get(f"/sessions/{session_id}")
        resp.raise_for_status()
        body = resp.json()
        last_status = body.get("status", "UNKNOWN")
        if last_status in wanted:
            return last_status
        time.sleep(0.5)
    raise TimeoutError(f"{session_id} final={last_status} not in {wanted}")


def run_e43(base_url: str) -> Check:
    try:
        with httpx.Client(base_url=base_url, timeout=20.0) as client:
            sid = create_session_with_plan(client, slow_ms=1000, steps=4)
            fault_down = client.post("/admin/faults/redis/down", headers={"X-Admin-Key": ADMIN_KEY})
            fault_down.raise_for_status()
            blocked = wait_session_status(client, sid, {"BLOCKED"}, timeout_s=30)
            fault_up = client.post("/admin/faults/redis/up", headers={"X-Admin-Key": ADMIN_KEY})
            fault_up.raise_for_status()
            resumed = wait_session_status(client, sid, {"EXECUTING", "COMPLETED"}, timeout_s=60)
            final = wait_session_status(client, sid, {"COMPLETED"}, timeout_s=120)
            return Check("E4.3", True, f"blocked={blocked}, resumed={resumed}, final={final}")
    except Exception as e:
        return Check("E4.3", False, str(e))


def run_e45(repo_root: str, database_url: str, *, port: int) -> Check:
    server = None
    try:
        server = start_server(repo_root, port=port, database_url=database_url)
        if not wait_health(f"http://127.0.0.1:{port}"):
            return Check("E4.5", False, "restart server did not become healthy")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20.0) as client:
            session_ids = [create_session_with_plan(client, slow_ms=5000, steps=1) for _ in range(20)]
            time.sleep(1.0)
        server.kill()
        server.wait(timeout=10)

        server = start_server(repo_root, port=port, database_url=database_url)
        if not wait_health(f"http://127.0.0.1:{port}", timeout_s=40):
            return Check("E4.5", False, "post-crash restart not healthy")

        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20.0) as client:
            terminal_ok = {"COMPLETED", "BLOCKED"}
            for sid in session_ids:
                st = wait_session_status(client, sid, terminal_ok, timeout_s=180)
                if st == "BLOCKED":
                    dlq = client.get("/dlq", params={"session_id": sid})
                    dlq.raise_for_status()
                    if not dlq.json():
                        return Check("E4.5", False, f"{sid} blocked without DLQ entry")
            return Check("E4.5", True, f"validated {len(session_ids)} sessions")
    except Exception as e:
        return Check("E4.5", False, str(e))
    finally:
        if server is not None and server.poll() is None:
            server.kill()
            server.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate E4.3 and E4.5 chaos requirements.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    asyncio.run(seed_mock_tool(args.database_url))

    server = start_server(args.repo_root, port=args.port, database_url=args.database_url)
    try:
        if not wait_health(f"http://127.0.0.1:{args.port}", timeout_s=40):
            raise SystemExit("Main server did not become healthy")
        e43 = run_e43(f"http://127.0.0.1:{args.port}")
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=10)

    e45 = run_e45(args.repo_root, args.database_url, port=args.port)

    checks = [e43, e45]
    for c in checks:
        print(f"[{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    if any(not c.passed for c in checks):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
