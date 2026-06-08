from __future__ import annotations

import os

import pytest

from .node_benchmark_runner import (
    assert_benchmark_result,
    baseline_mark_for_case,
    env_enabled,
    load_cases,
    run_benchmark_case,
)


pytestmark = pytest.mark.skipif(
    not env_enabled(),
    reason="set FACTORY_AGENT_RUN_NODE_BENCHMARKS=1 to run planner-owned node benchmarks",
)


def pytest_generate_tests(metafunc):
    if "benchmark_case" not in metafunc.fixturenames:
        return
    node = os.getenv("FACTORY_AGENT_NODE_BENCHMARK_NODE", "all").strip() or "all"
    params = []
    for case in load_cases(node):
        marks = []
        xfail = baseline_mark_for_case(case)
        if xfail is not None:
            marks.append(pytest.mark.xfail(reason=str(xfail.get("reason") or "first-run baseline"), strict=True))
        params.append(pytest.param(case, id=str(case["id"]), marks=marks))
    metafunc.parametrize("benchmark_case", params)


@pytest.mark.asyncio
async def test_planner_owned_node_benchmark_case(benchmark_case):
    result = await run_benchmark_case(benchmark_case)
    assert_benchmark_result(result)

