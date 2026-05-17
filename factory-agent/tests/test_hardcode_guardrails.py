from __future__ import annotations

import ast
import re
from pathlib import Path

from factory_agent.testing_seeded_scenarios import SeededScenarioInterpreter


REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_PHASE_PROMPT_RE = re.compile(r"\bphase\s+(?:9|10|14|19)\b", re.IGNORECASE)
SEEDED_MACHINE_DEFAULT_RE = re.compile(
    r"intent_constraint_values\([^)]*[\"']machine_id[\"'][^)]*\)\s+or\s+\[\s*[\"']M-CNC-01[\"']",
    re.IGNORECASE | re.DOTALL,
)
SEEDED_JOB_DEFAULT_RE = re.compile(
    r"intent_constraint_values\([^)]*[\"']job_id[\"'][^)]*\)\s+or\s+\[\s*[\"']JOB-SEED-[^\"']+[\"']",
    re.IGNORECASE | re.DOTALL,
)

RUNTIME_BRANCH_GUARD_PATHS = [
    "factory-agent/factory_agent/planning/intent.py",
    "factory-agent/factory_agent/planning/tool_selector.py",
    "factory-agent/factory_agent/services/plan_creation_service.py",
    "factory-agent/factory_agent/api/routers/events.py",
    "factory-agent/factory_agent/testing_seeded_adapters.py",
]

PRODUCT_PHASE_STRING_GUARD_PATHS = [
    "factory-agent/factory_agent/planning/intent.py",
    "factory-agent/factory_agent/planning/tool_selector.py",
    "factory-agent/factory_agent/services/plan_creation_service.py",
    "factory-agent/factory_agent/api/routers/events.py",
]

SEEDED_DEFAULT_GUARD_PATHS = [
    "factory-agent/factory_agent/planning/intent.py",
    "factory-agent/factory_agent/planning/tool_selector.py",
    "factory-agent/factory_agent/services/plan_creation_service.py",
    "factory-agent/factory_agent/api/routers/events.py",
    "factory-agent/factory_agent/testing_seeded_adapters.py",
]

ALLOWED_FIXTURE_PATHS_WITH_REASONS = {
    "factory-agent/factory_agent/testing_seeded_scenarios.py": "Data-driven seeded scenario catalog owns phase prompt triggers and fixture ids.",
    "factory-agent/tests": "Backend pytest fixtures and assertions may use canonical seeded prompts and ids.",
    "eMas Front/e2e": "Playwright fixtures/specs may use seeded prompts, ids, and expected visible text.",
    "tests/e2e/scenarios": "Shared e2e scenario data may use canonical prompt fixtures.",
    "docs/qa": "QA plans and trackers document accepted hardcodes and migration history.",
}

FRONTEND_PHRASE_ALLOWLIST_COUNTS = {
    "eMas Front/src/components/features/chat/turns/turnAssembler.js": {
        "please approve": (6, "Legacy fallback cleanup for snapshots without typed presentation."),
        "will be updated from": (1, "Legacy approval-wait fallback for snapshots without typed presentation."),
        "risk summary": (1, "Legacy plan-like answer filter for snapshots without typed presentation."),
        "run complete": (1, "Diagnostic prose; state still prefers typed presentation."),
    },
    "eMas Front/src/components/features/chat/factory-agent/FactoryAgentChatPanel.jsx": {
        "please approve": (1, "Legacy completed-approval fallback after typed presentation is absent."),
        "will be updated from": (1, "Legacy completed-approval fallback after typed presentation is absent."),
        "risk summary": (1, "Legacy plan-like detail filter for snapshots without typed presentation."),
    },
    "eMas Front/src/components/features/chat/factory-agent/activityTimelineUtils.js": {
        "run complete": (7, "Display label and stale terminal fallback guarded by typed presentation state."),
    },
    "eMas Front/src/components/features/chat/factory-agent/presentationContract.js": {
        "run complete": (1, "Typed presentation maps completed state to a display label."),
    },
}

FRONTEND_STATE_PHRASES = [
    "please approve",
    "will be updated from",
    "risk summary",
    "run complete",
    "all requested changes completed",
]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8-sig")


def _phase_prompt_branch_hits(rel_path: str) -> list[str]:
    source = _read(rel_path)
    tree = ast.parse(source, filename=rel_path)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        segment = ast.get_source_segment(source, node.test) or ""
        if FORBIDDEN_PHASE_PROMPT_RE.search(segment):
            hits.append(f"{rel_path}:{node.lineno}: {segment.strip()}")
    return hits


def _seeded_default_hits(rel_path: str) -> list[str]:
    source = _read(rel_path)
    hits: list[str] = []
    for pattern, label in [
        (SEEDED_MACHINE_DEFAULT_RE, "missing machine_id defaults to M-CNC-01"),
        (SEEDED_JOB_DEFAULT_RE, "missing job_id defaults to JOB-SEED-*"),
    ]:
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            hits.append(f"{rel_path}:{line}: {label}")
    return hits


def test_product_runtime_code_has_no_phase_prompt_branches():
    hits = [
        hit
        for rel_path in RUNTIME_BRANCH_GUARD_PATHS
        for hit in _phase_prompt_branch_hits(rel_path)
    ]

    assert hits == [], (
        "Phase prompt routing branches belong in explicit scenario data, not product/runtime code:\n"
        + "\n".join(hits)
    )


def test_product_runtime_files_do_not_embed_seeded_phase_prompt_strings():
    hits: list[str] = []
    for rel_path in PRODUCT_PHASE_STRING_GUARD_PATHS:
        source = _read(rel_path)
        for match in FORBIDDEN_PHASE_PROMPT_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            hits.append(f"{rel_path}:{line}: {match.group(0)}")

    assert hits == [], (
        "Seeded Playwright phase prompts are only allowed in fixture/test/data paths:\n"
        + "\n".join(hits)
    )


def test_runtime_code_does_not_default_missing_entities_to_seeded_fixture_ids():
    hits = [
        hit
        for rel_path in SEEDED_DEFAULT_GUARD_PATHS
        for hit in _seeded_default_hits(rel_path)
    ]

    assert hits == [], "Missing entities must not silently route to seeded ids:\n" + "\n".join(hits)


def test_phase_and_seeded_fixture_allowlist_is_explicit():
    for rel_path, reason in ALLOWED_FIXTURE_PATHS_WITH_REASONS.items():
        assert reason.strip(), f"{rel_path} needs an allowlist reason"

    scenario_text = _read("factory-agent/factory_agent/testing_seeded_scenarios.py")
    assert "phase 9" in scenario_text.lower()
    assert "M-CNC-01" in scenario_text


def test_release_phase10_machine_status_prompts_are_fixture_data():
    interpreter = SeededScenarioInterpreter()

    slow = interpreter.match("Run Phase 10 slow network machine status")
    latency = interpreter.match("Run Phase 10 release latency budget machine status")

    assert slow is not None
    assert slow.scenario_id == "phase10_release_machine_status"
    assert latency is not None
    assert latency.scenario_id == "phase10_release_machine_status"


def test_frontend_phrase_based_state_fallbacks_stay_allowlisted():
    hits: list[str] = []
    for rel_path, allowlist in FRONTEND_PHRASE_ALLOWLIST_COUNTS.items():
        source = _read(rel_path).lower()
        for phrase in FRONTEND_STATE_PHRASES:
            actual_count = source.count(phrase)
            allowed_count = allowlist.get(phrase, (0, ""))[0]
            if actual_count > allowed_count:
                hits.append(
                    f"{rel_path}: phrase {phrase!r} appears {actual_count} time(s), "
                    f"allowlist permits {allowed_count}"
                )

    assert hits == [], (
        "Frontend state should prefer typed `presentation`; phrase fallbacks need an explicit allowlist:\n"
        + "\n".join(hits)
    )
