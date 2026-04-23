from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import sys

import httpx


async def run_session(client: httpx.AsyncClient, user_id: str, *, auth_header: str | None = None) -> int:
    headers = {"Authorization": auth_header} if auth_header else None
    create = await client.post("/sessions", json={"user_id": user_id})
    create.raise_for_status()
    session_id = create.json()["session_id"]
    execute = await client.post(
        f"/sessions/{session_id}/execute",
        params={"background": "true"},
        headers=headers,
    )
    return execute.status_code


async def run_load(base_url: str, concurrency: int, total_sessions: int, *, auth_header: str | None = None) -> Counter:
    counter: Counter = Counter()
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        async def one(i: int) -> None:
            async with sem:
                code = await run_session(client, user_id=f"load-user-{i}", auth_header=auth_header)
                counter[code] += 1

        await asyncio.gather(*[one(i) for i in range(total_sessions)])
    return counter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backpressure load test for factory-agent session queue.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--concurrency", type=int, default=50, help="Concurrent request cap")
    parser.add_argument("--sessions", type=int, default=500, help="Total sessions to create")
    parser.add_argument("--require-100-success", action="store_true", help="Exit non-zero if 100-session run has non-200 responses.")
    parser.add_argument("--require-all-200", action="store_true", help="Exit non-zero if any response is non-200.")
    parser.add_argument("--expect-429", action="store_true", help="Exit non-zero when no queue saturation (429) responses occur.")
    parser.add_argument("--auth-header", default=None, help="Optional Authorization header value, e.g. 'Bearer <token>'.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = asyncio.run(run_load(args.base_url, args.concurrency, args.sessions, auth_header=args.auth_header))
    total = sum(counts.values())
    print("=== Backpressure Load Test ===")
    print(f"base_url={args.base_url} concurrency={args.concurrency} total_sessions={args.sessions}")
    print(f"total_responses={total}")
    for code in sorted(counts.keys()):
        print(f"status_{code}={counts[code]}")
    if args.require_100_success and args.sessions == 100:
        non_200 = total - counts.get(200, 0)
        if non_200 > 0:
            print(f"FAIL: {non_200} sessions were not accepted (status != 200).")
            sys.exit(2)
    if args.require_all_200:
        non_200 = total - counts.get(200, 0)
        if non_200 > 0:
            print(f"FAIL: expected all 200 responses, got {non_200} non-200.")
            sys.exit(4)
    if args.expect_429 and counts.get(429, 0) == 0:
        print("FAIL: expected queue saturation (429) but none observed.")
        sys.exit(3)


if __name__ == "__main__":
    main()
