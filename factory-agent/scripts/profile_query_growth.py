from __future__ import annotations

import argparse
import re

import httpx


def read_metric(metrics_text: str, name: str) -> float:
    pattern = re.compile(rf"^{re.escape(name)}(?:\{{.*\}})?\s+([0-9eE.+-]+)$", re.MULTILINE)
    matches = pattern.findall(metrics_text)
    if not matches:
        return 0.0
    return sum(float(v) for v in matches)


def run_load(client: httpx.Client, sessions: int) -> None:
    for i in range(sessions):
        create = client.post("/sessions", json={"user_id": f"profile-{i}"})
        create.raise_for_status()
        sid = create.json()["session_id"]
        execute = client.post(f"/sessions/{sid}/execute", params={"background": "true"})
        if execute.status_code not in (200, 429):
            raise RuntimeError(f"unexpected status {execute.status_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile query growth to detect N+1 patterns.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--batch-a", type=int, default=25)
    parser.add_argument("--batch-b", type=int, default=100)
    parser.add_argument("--max-growth-ratio", type=float, default=6.0)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        before = read_metric(client.get("/metrics").text, "db_query_total")
        run_load(client, args.batch_a)
        after_a = read_metric(client.get("/metrics").text, "db_query_total")
        run_load(client, args.batch_b)
        after_b = read_metric(client.get("/metrics").text, "db_query_total")

    delta_a = max(after_a - before, 1.0)
    delta_b = max(after_b - after_a, 1.0)
    growth_ratio = delta_b / delta_a
    print(f"batch_a_queries={delta_a:.0f} batch_b_queries={delta_b:.0f} growth_ratio={growth_ratio:.2f}")
    if growth_ratio > args.max_growth_ratio:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
