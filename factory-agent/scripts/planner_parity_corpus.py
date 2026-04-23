from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.config import Settings
from agent.plan_validator import validate_plan
from agent.planner import LangChainPlannerBackend, LegacyPlannerBackend, PlannerBackendError
from agent.schemas import ToolInfo
from agent.tool_scope import filter_tools_for_intent


@dataclass
class BackendMetrics:
    backend: str
    total_intents: int
    validator_pass_count: int = 0
    unknown_tool_count: int = 0
    clarification_count: int = 0
    infeasible_count: int = 0
    total_steps: int = 0
    write_step_count: int = 0
    missing_approval_flags_count: int = 0
    errors: int = 0
    error_samples: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        total = max(1, self.total_intents)
        write_total = max(1, self.write_step_count)
        return {
            "backend": self.backend,
            "total_intents": self.total_intents,
            "validator_pass_rate": self.validator_pass_count / total,
            "unknown_tool_rate": self.unknown_tool_count / total,
            "clarification_rate": self.clarification_count / total,
            "average_step_count": self.total_steps / total,
            "infeasible_rate": self.infeasible_count / total,
            "missing_approval_flags_rate": self.missing_approval_flags_count / write_total,
            "errors": self.errors,
            "error_samples": self.error_samples or [],
        }


def _tool_catalog() -> dict[str, ToolInfo]:
    tools = [
        ToolInfo(
            name="get__machines",
            description="Read machines and status",
            endpoint="/machines",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            capability_tags=["machine", "status", "downtime"],
        ),
        ToolInfo(
            name="get__inventory",
            description="Read inventory by sku or id",
            endpoint="/inventory",
            method="GET",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}, "sku": {"type": "string"}}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            capability_tags=["inventory", "sku", "availability"],
        ),
        ToolInfo(
            name="post__inventory_update",
            description="Update inventory quantity",
            endpoint="/inventory",
            method="POST",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            is_read_only=False,
            requires_approval=True,
            side_effect_level="HIGH",
            capability_tags=["inventory", "update", "quantity"],
        ),
        ToolInfo(
            name="post__jobs_create",
            description="Create a production job",
            endpoint="/jobs",
            method="POST",
            input_schema={"type": "object", "properties": {"job_id": {"type": "integer"}}, "required": ["job_id"]},
            is_read_only=False,
            requires_approval=True,
            side_effect_level="HIGH",
            capability_tags=["job", "create", "production"],
        ),
        ToolInfo(
            name="patch__jobs_reschedule",
            description="Reschedule a job",
            endpoint="/jobs/reschedule",
            method="PATCH",
            input_schema={"type": "object", "properties": {"job_id": {"type": "integer"}}, "required": ["job_id"]},
            is_read_only=False,
            requires_approval=True,
            side_effect_level="HIGH",
            capability_tags=["job", "reschedule"],
        ),
        ToolInfo(
            name="delete__inventory_record",
            description="Delete an inventory record",
            endpoint="/inventory",
            method="DELETE",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            is_read_only=False,
            requires_approval=True,
            side_effect_level="CRITICAL",
            capability_tags=["inventory", "delete"],
        ),
        ToolInfo(
            name="get__chatbot_approval_pending",
            description="List pending approvals",
            endpoint="/chatbot/approval/pending",
            method="GET",
            input_schema={"type": "object", "properties": {}},
            is_read_only=True,
            requires_approval=False,
            side_effect_level="NONE",
            capability_tags=["approval", "pending"],
        ),
        ToolInfo(
            name="post__chatbot_approval_{id}_approve",
            description="Approve an approval request",
            endpoint="/chatbot/approval/{id}/approve",
            method="POST",
            input_schema={"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            is_read_only=False,
            requires_approval=True,
            side_effect_level="HIGH",
            capability_tags=["approval", "approve"],
        ),
    ]
    return {t.name: t for t in tools}


async def _evaluate_backend(
    *,
    backend_name: str,
    intents: list[str],
    tools_by_name: dict[str, ToolInfo],
    model: str,
    base_url: str | None,
    api_key: str | None,
) -> BackendMetrics:
    if backend_name == "legacy":
        backend = LegacyPlannerBackend()
    elif backend_name == "langchain":
        settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            redis_url=None,
            go_api_base_url="http://localhost:8080",
            worker_count=0,
            session_queue_size=1,
            max_plan_steps=10,
            max_session_steps=50,
            max_replans=5,
            max_llm_calls=20,
            max_session_duration_s=1800,
            http_timeout_s=5.0,
            planner_model=model,
            openai_base_url=base_url,
            openai_api_key=api_key,
        )
        backend = LangChainPlannerBackend(settings)
    else:
        raise ValueError(f"unsupported backend: {backend_name}")

    metrics = BackendMetrics(backend=backend_name, total_intents=len(intents))
    metrics.error_samples = []

    for intent in intents:
        scoped = filter_tools_for_intent(intent=intent, tools_by_name=tools_by_name, max_tools=30)
        scoped_tools = [tools_by_name[name] for name in scoped.tool_names if name in tools_by_name]
        if not scoped_tools:
            metrics.clarification_count += 1
            metrics.infeasible_count += 1
            continue
        try:
            result = await backend.generate_plan(
                intent=intent,
                scoped_tools=scoped_tools,
                context={},
                tools_markdown="# tools",
            )
        except PlannerBackendError as e:
            metrics.clarification_count += 1
            metrics.infeasible_count += 1
            metrics.errors += 1
            if len(metrics.error_samples) < 5:
                metrics.error_samples.append(f"PlannerBackendError: {e}")
            continue
        except Exception as e:
            metrics.errors += 1
            metrics.infeasible_count += 1
            if len(metrics.error_samples) < 5:
                metrics.error_samples.append(f"{type(e).__name__}: {e}")
            continue

        draft = result.draft
        metrics.total_steps += len(draft.steps)

        validation = validate_plan(draft, tools_by_name, max_steps=10)
        if validation.ok:
            metrics.validator_pass_count += 1
        else:
            metrics.infeasible_count += 1
            if any("Unknown tool:" in err for err in validation.errors):
                metrics.unknown_tool_count += 1

        for step in draft.steps:
            tool = tools_by_name.get(step.tool_name)
            if not tool:
                continue
            if not tool.is_read_only:
                metrics.write_step_count += 1
                # "missing approval flags" here means write step mapped to a non-approval tool metadata.
                if not tool.requires_approval:
                    metrics.missing_approval_flags_count += 1

    return metrics


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Run planner parity metrics on a fixed intent corpus.")
    parser.add_argument(
        "--corpus",
        default=str(Path(__file__).with_name("planner_intent_corpus.json")),
        help="Path to JSON file containing an array of intents.",
    )
    parser.add_argument("--backend", choices=["legacy", "langchain", "both"], default="both")
    parser.add_argument("--planner-model", default="Qwen3.5-9B", help="Model used for langchain backend.")
    parser.add_argument("--openai-base-url", default="", help="OpenAI-compatible base URL, e.g. http://127.0.0.1:9000/v1")
    parser.add_argument("--openai-api-key", default="", help="API key for the provider; local servers can use any dummy value.")
    parser.add_argument("--out", default="", help="Optional output JSON path.")
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    intents = json.loads(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(intents, list) or not all(isinstance(x, str) for x in intents):
        raise ValueError("corpus must be a JSON array of strings")

    tools_by_name = _tool_catalog()
    backends = ["legacy", "langchain"] if args.backend == "both" else [args.backend]

    results: list[dict[str, Any]] = []
    for name in backends:
        metrics = await _evaluate_backend(
            backend_name=name,
            intents=intents,
            tools_by_name=tools_by_name,
            model=args.planner_model,
            base_url=(args.openai_base_url.strip() or None),
            api_key=(args.openai_api_key.strip() or None),
        )
        result = {
            "raw": asdict(metrics),
            "rates": metrics.to_dict(),
        }
        results.append(result)

    payload = {"corpus_size": len(intents), "results": results}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
