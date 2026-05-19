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
EXACT_RESPONSE_DOCUMENT_PROMPTS = [
    "change all medium priority job to high then change all high priority job to low",
    "change all high priority job to low then change all low priority job to medium",
    "Show status for machine with machine id M-CNC-01",
    "According to the LOTO procedure, what notification is required before starting lockout",
    "According to the OSHA lockout/tagout guide, what notification is required before reenergizing a machine after removing lockout or tagout devices?",
    "According to the OSHA lockout/tagout guide, what notification is required before starting lockout?",
]
SYNTHETIC_LOTO_POLICY_SOURCE_RE = re.compile(
    r"loto_notification_requirement|LOTO Notification Requirements|policy:loto-notification-requirement"
)
PRODUCT_RUNTIME_LITERAL_RE = re.compile(
    "|".join(
        [
            r"M-CNC-01",
            r"JOB-SEED",
            r"loto_notification_requirement",
            r"LOTO Notification Requirements",
            r"policy:loto-notification-requirement",
            r"osha_3120_lockout_tagout(?:_c\d+)?",
            *[re.escape(prompt) for prompt in EXACT_RESPONSE_DOCUMENT_PROMPTS],
        ]
    ),
    re.IGNORECASE,
)
FORBIDDEN_BRANCH_LITERAL_RE = re.compile(
    "|".join(
        [
            r"M-CNC-01",
            r"JOB-SEED",
            r"Medium\s*->\s*High",
            r"Original\s+High\s*->\s*Low",
            r"Updated\s+63\s+jobs\s+across\s+22\s+approved\s+steps",
            *[re.escape(prompt) for prompt in EXACT_RESPONSE_DOCUMENT_PROMPTS],
        ]
    ),
    re.IGNORECASE,
)
JS_BRANCH_MARKER_RE = re.compile(r"\b(?:if|else\s+if|switch|case)\b|[?:]")

RUNTIME_BRANCH_GUARD_PATHS = [
    "factory-agent/factory_agent/planning/intent.py",
    "factory-agent/factory_agent/planning/tool_selector.py",
    "factory-agent/factory_agent/services/plan_creation_service.py",
    "factory-agent/factory_agent/api/routers/events.py",
    "factory-agent/factory_agent/testing_seeded_adapters.py",
]

PRODUCT_BRANCH_GUARD_ROOTS = [
    "factory-agent/factory_agent",
    "eMas Front/src",
]

PRODUCT_BRANCH_GUARD_EXCLUDED_PARTS = (
    "/generated/",
    "/testing_seeded_adapters.py",
    "/testing_seeded_scenarios.py",
)

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
    "factory-agent/factory_agent/testing_seeded_adapters.py": "Seeded adapter fixtures may carry canonical ids and prompts for deterministic browser scenarios.",
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


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _is_product_branch_guard_file(rel_path: str) -> bool:
    normalized = "/" + rel_path.replace("\\", "/")
    if any(part in normalized for part in PRODUCT_BRANCH_GUARD_EXCLUDED_PARTS):
        return False
    name = Path(rel_path).name
    if re.search(r"\.test\.(?:mjs|js|jsx|ts|tsx)$", name):
        return False
    if name.endswith((".pyc", ".map")):
        return False
    return True


def _product_branch_guard_files() -> list[str]:
    files: list[str] = []
    for root in PRODUCT_BRANCH_GUARD_ROOTS:
        root_path = REPO_ROOT / root
        for path in root_path.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".jsx", ".mjs", ".ts", ".tsx"}:
                continue
            rel_path = _rel(path)
            if _is_product_branch_guard_file(rel_path):
                files.append(rel_path)
    return sorted(files)


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


def _forbidden_python_branch_hits(rel_path: str) -> list[str]:
    source = _read(rel_path)
    tree = ast.parse(source, filename=rel_path)
    hits: list[str] = []

    def check(segment: str | None, lineno: int, label: str) -> None:
        text = segment or ""
        if FORBIDDEN_BRANCH_LITERAL_RE.search(text):
            hits.append(f"{rel_path}:{lineno}: {label}: {text.strip()}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While)):
            check(ast.get_source_segment(source, node.test), node.lineno, "branch condition")
        elif isinstance(node, ast.Match):
            check(ast.get_source_segment(source, node.subject), node.lineno, "match subject")
            for case in node.cases:
                check(ast.get_source_segment(source, case.pattern), case.pattern.lineno, "match case")
                if case.guard is not None:
                    check(ast.get_source_segment(source, case.guard), case.guard.lineno, "match guard")
    return hits


def _forbidden_js_branch_hits(rel_path: str) -> list[str]:
    source = _read(rel_path)
    lines = source.splitlines()
    hits: list[str] = []
    for index, line in enumerate(lines):
        if not FORBIDDEN_BRANCH_LITERAL_RE.search(line):
            continue
        window_start = max(0, index - 4)
        window_end = min(len(lines), index + 5)
        window = "\n".join(lines[window_start:window_end])
        if JS_BRANCH_MARKER_RE.search(window):
            hits.append(f"{rel_path}:{index + 1}: {line.strip()}")
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


def test_product_branch_conditions_do_not_use_seeded_ids_exact_prompts_or_fixture_labels():
    hits: list[str] = []
    for rel_path in _product_branch_guard_files():
        if rel_path.endswith(".py"):
            hits.extend(_forbidden_python_branch_hits(rel_path))
        else:
            hits.extend(_forbidden_js_branch_hits(rel_path))

    assert hits == [], (
        "Product-code branches must not key behavior off deterministic fixture ids, exact prompts, "
        "or canonical response-document labels. Put constants in fixtures/scenarios or route through "
        "typed metadata/contracts instead:\n" + "\n".join(hits)
    )


def test_runtime_product_code_does_not_emit_synthetic_loto_notification_policy_sources():
    hits: list[str] = []
    for rel_path in _product_branch_guard_files():
        source = _read(rel_path)
        for match in SYNTHETIC_LOTO_POLICY_SOURCE_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            hits.append(f"{rel_path}:{line}: {match.group(0)}")

    assert hits == [], (
        "Runtime/product code must not emit synthetic LOTO notification fallback sources. "
        "Tests, seeded fixtures, and docs may mention them only as scoped regression evidence:\n"
        + "\n".join(hits)
    )


def test_runtime_product_code_does_not_embed_phase27_source_prompt_or_fixture_literals():
    hits: list[str] = []
    for rel_path in _product_branch_guard_files():
        source = _read(rel_path)
        for match in PRODUCT_RUNTIME_LITERAL_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            hits.append(f"{rel_path}:{line}: {match.group(0)}")

    assert hits == [], (
        "Runtime/product source must not embed exact Phase 27+ source ids, chunk ids, seeded ids, "
        "or exact RAG regression prompts. Put those values in tests, seeded fixtures, docs, "
        "or source/entity registries instead:\n" + "\n".join(hits)
    )


def test_knowledge_policy_uses_registry_metadata_not_policy_id_branches():
    source = _read("factory-agent/factory_agent/rag/knowledge_policy.py")
    hits: list[str] = []
    for pattern in (
        re.compile(r"\bpolicy\.policy_id\s*(?:==|!=)"),
        re.compile(r"\bif\s+policy\.policy_id\b"),
    ):
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            hits.append(f"factory-agent/factory_agent/rag/knowledge_policy.py:{line}: {match.group(0)}")

    assert hits == [], (
        "Knowledge policies should route through registry metadata such as EvidenceSupportProfile, "
        "not one-off policy_id branches:\n" + "\n".join(hits)
    )
    assert "EvidenceSupportProfile" in source


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


def test_frontend_response_document_probe_requires_contract_evidence_for_generic_business_checks():
    probe_source = _read("eMas Front/e2e/support/responseDocumentProbe.js")
    final_response_spec = _read("eMas Front/e2e/specs/final-response-quality.spec.js")

    assert "text-only business group expectation" in probe_source
    assert "typed contract evidence" in probe_source
    assert "contract: 'business_change_v1'" in final_response_spec
    assert "entityType: 'job'" in final_response_spec
    assert "fieldChangeCountMin: 1" in final_response_spec
    assert "responseContracts: ['business_change_v1']" in final_response_spec
