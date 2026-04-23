from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx


@dataclass
class CheckResult:
    requirement: str
    passed: bool
    command: str


def run_cmd(command: str) -> bool:
    completed = subprocess.run(command, shell=True)
    return completed.returncode == 0


def wait_health(base_url: str, timeout_s: int = 20) -> bool:
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


def run_e42_with_constrained_server(base_url: str) -> bool:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    py = os.path.abspath(os.path.join(root, "..", ".venv", "Scripts", "python.exe"))
    load_script = os.path.abspath(os.path.join(root, "scripts", "load_test_backpressure.py"))
    env = os.environ.copy()
    env["MAX_CONCURRENT"] = "1"
    env["MAX_QUEUE"] = "2"
    constrained_base = "http://127.0.0.1:8001"
    server = subprocess.Popen(
        [py, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=root,
        env=env,
    )
    try:
        if not wait_health(constrained_base):
            return False
        sat = subprocess.run(
            [py, load_script, "--base-url", constrained_base, "--sessions", "400", "--concurrency", "200", "--expect-429"],
            cwd=os.path.abspath(os.path.join(root, "..")),
        )
        if sat.returncode != 0:
            return False
        resume = subprocess.run(
            [py, load_script, "--base-url", constrained_base, "--sessions", "1", "--concurrency", "1", "--require-all-200"],
            cwd=os.path.abspath(os.path.join(root, "..")),
        )
        return resume.returncode == 0
    finally:
        server.kill()
        server.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 4 exit checks (E4.1-E4.9).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database-url", default=None, help="Required for index verification.")
    parser.add_argument("--skip-live", action="store_true", help="Skip load/chaos checks requiring running services.")
    args = parser.parse_args()

    checks: list[tuple[str, str, bool]] = [
        ("E4.6", ".\\.venv\\Scripts\\python -m pytest factory-agent/tests/test_api_endpoints.py -k tampered_jwt -q", False),
        ("E4.7", ".\\.venv\\Scripts\\python -m pytest factory-agent/tests/test_api_endpoints.py -k injection_attempt -q", False),
        ("E4.4", ".\\.venv\\Scripts\\python -m pytest factory-agent/tests/test_execution_engine.py -k db_failure_mid_step -q", False),
    ]
    if not args.skip_live:
        checks.extend(
            [
                ("E4.1", f".\\.venv\\Scripts\\python factory-agent/scripts/load_test_backpressure.py --base-url {args.base_url} --sessions 100 --concurrency 100 --require-100-success", True),
                ("E4.8", f".\\.venv\\Scripts\\python factory-agent/scripts/profile_query_growth.py --base-url {args.base_url}", True),
            ]
        )
        if args.database_url:
            checks.append(("Perf-Indexes", f".\\.venv\\Scripts\\python factory-agent/scripts/verify_indexes.py --database-url \"{args.database_url}\"", True))

    results: list[CheckResult] = []
    for requirement, command, _ in checks:
        ok = run_cmd(command)
        results.append(CheckResult(requirement=requirement, passed=ok, command=command))
        print(f"[{'PASS' if ok else 'FAIL'}] {requirement}: {command}")

    if not args.skip_live:
        e42_ok = run_e42_with_constrained_server(args.base_url)
        e42_cmd = "constrained_server(MAX_CONCURRENT=1,MAX_QUEUE=2)+saturation+resume_check"
        results.append(CheckResult(requirement="E4.2", passed=e42_ok, command=e42_cmd))
        print(f"[{'PASS' if e42_ok else 'FAIL'}] E4.2: {e42_cmd}")

    failed = [r for r in results if not r.passed]
    if failed:
        print("\nFailed checks:")
        for item in failed:
            print(f"- {item.requirement}: {item.command}")
        sys.exit(2)


if __name__ == "__main__":
    main()
