from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from factory_agent.persistence.models import Approval as ApprovalRow
from factory_agent.persistence.models import DeadLetter as DeadLetterRow
from factory_agent.persistence.models import ExecutionSnapshot as SnapshotRow
from factory_agent.persistence.models import Message as MessageRow
from factory_agent.persistence.models import Plan as PlanRow
from factory_agent.persistence.models import PlanStep as PlanStepRow
from factory_agent.persistence.models import Session as SessionRow
from factory_agent.persistence.models import generate_uuid

from ..config import Settings
from ..graph.session_detection import is_graph_native_session
from ..observability.events import AgentEvent, EventBus
from .memory_manager import MemoryManager
from ..observability.metrics import metrics
from ..analysis.presentation import extract_table_from_result
from ..planning.reasoning_pipeline import ReasoningPipeline
from ..schemas import ToolInfo
from ..analysis.tabular_analysis import analyze_result
from ..observability.telemetry import log_event, log_llm_prompt, log_llm_prompt_skipped, log_step_status_changed
from ..planning.intent_verifier import normalize_predicate_value
from . import execution_runtime

FailureDecision = Literal["RETRY", "REPLAN", "FAIL_HARD", "AMBIGUOUS"]


class AmbiguousExecutionError(Exception):
    pass


class ToolHTTPError(Exception):
    def __init__(self, status_code: int, body: dict[str, Any] | None):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}")


class ToolNetworkError(Exception):
    def __init__(self, message: str, *, request_was_sent: bool):
        self.request_was_sent = request_was_sent
        super().__init__(message)


class ToolInputError(Exception):
    pass


class PredicateVerificationError(Exception):
    def __init__(self, message: str, *, coverage: dict[str, Any]):
        self.coverage = coverage
        super().__init__(message)


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def compute_idempotency_key(*, session_id: str, step_index: int, plan_version: int, args: dict[str, Any]) -> str:
    payload = f"{session_id}:{step_index}:{plan_version}:{_stable_json(args)}"
    return _sha256_hex(payload)


def compute_payload_hash(*, args: dict[str, Any]) -> str:
    return _sha256_hex(_stable_json(args))


_PATH_PARAM_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _normalize_tool_args(tool: ToolInfo, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = args or {}
    if any(key in payload for key in ("path", "query", "body", "path_args", "query_args", "body_args")):
        path_args = payload.get("path") if isinstance(payload.get("path"), dict) else payload.get("path_args") if isinstance(payload.get("path_args"), dict) else {}
        query_args = payload.get("query") if isinstance(payload.get("query"), dict) else payload.get("query_args") if isinstance(payload.get("query_args"), dict) else {}
        body_args = payload.get("body") if isinstance(payload.get("body"), dict) else payload.get("body_args") if isinstance(payload.get("body_args"), dict) else {}
        return dict(path_args), dict(query_args), dict(body_args)

    path_param_names = tool.path_params or [match.group(1) for match in _PATH_PARAM_RE.finditer(tool.endpoint or "")]
    query_param_names = tool.query_params or [
        key for key, source in (tool.param_sources or {}).items() if source == "query"
    ]
    path_args = {key: payload[key] for key in path_param_names if key in payload}
    query_args = {
        key: payload[key]
        for key in query_param_names
        if key in payload
    }
    consumed = set(path_args.keys()) | set(query_args.keys())
    body_args = {key: value for key, value in payload.items() if key not in consumed}
    return path_args, query_args, body_args


def _result_items(body: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not isinstance(body, dict):
        return None
    for key in ("data", "items"):
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]
    return None


def _result_path_parts(path: str) -> list[str]:
    normalized = (path or "data").strip()
    if normalized.startswith("$."):
        normalized = normalized[2:]
    if normalized.startswith("result."):
        normalized = normalized[len("result.") :]
    if normalized.endswith("[*]"):
        normalized = normalized[:-3]
    if normalized.endswith("[]"):
        normalized = normalized[:-2]
    return [part for part in normalized.split(".") if part]


def _items_at_path(body: dict[str, Any] | None, path: str) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    node: Any = body
    for part in _result_path_parts(path):
        if not isinstance(node, dict):
            return []
        node = node.get(part)
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    if isinstance(node, dict):
        return [node]
    return []


@dataclass(frozen=True)
class ExecuteResult:
    status: str
    current_step_index: int


class ExecutionEngine:
    """Legacy relational plan-step execution engine.

    LangGraph-native sessions use graph checkpoint state as execution truth.
    This engine remains only for compatibility sessions that still execute
    relational `PlanRow`/`PlanStepRow` records.
    """

    def __init__(self, settings: Settings, event_bus: EventBus):
        self._settings = settings
        self._event_bus = event_bus
        self._memory_manager = MemoryManager(settings)
        self._reasoning = ReasoningPipeline(settings)

    def _session_duration_s(self, session: SessionRow) -> int:
        if not session.session_started_at:
            return 0
        return int((datetime.utcnow() - session.session_started_at).total_seconds())

    def _checkpoint_state(self, session: SessionRow) -> dict[str, Any]:
        return {
            "status": session.status,
            "plan_id": session.plan_id,
            "plan_version": session.plan_version,
            "plan_hash": session.plan_hash,
            "current_step_index": session.current_step_index,
            "step_count": session.step_count,
            "replan_count": session.replan_count,
            "retry_count": session.retry_count,
            "llm_call_count": session.llm_call_count,
            "error": session.error,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

    def _entity_label(self, args: dict[str, Any]) -> str:
        for key in ("id", "machine_id", "job_id", "inventory_id", "approval_id", "proposal_id", "line_id"):
            value = args.get(key)
            if value not in (None, ""):
                return f"{key}={value}"
        if args:
            first_key = next(iter(args.keys()))
            return f"{first_key}={args[first_key]}"
        return "target"

    def _build_text_model(self):
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.tool_result_summary_model,
            "temperature": 0,
            "timeout": self._settings.tool_result_summary_timeout_s,
            "max_retries": 0,
            "max_tokens": self._settings.tool_result_summary_max_tokens,
        }
        if self._settings.tool_result_summary_openai_base_url:
            kwargs["base_url"] = self._settings.tool_result_summary_openai_base_url
            kwargs["api_key"] = self._settings.openai_api_key or "local"
        elif self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    async def _compose_text(
        self,
        *,
        component: str,
        prompt: str,
        fallback: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        backend = self._tool_result_summary_backend()
        if backend != "langchain":
            log_llm_prompt_skipped(
                component=component,
                backend=backend,
                reason="text_backend!=langchain",
                metadata=metadata or {},
            )
            return fallback

        try:
            from langchain_openai import ChatOpenAI  # noqa: F401
        except Exception:
            log_llm_prompt_skipped(
                component=component,
                backend=backend,
                reason="langchain_openai_unavailable",
                metadata=metadata or {},
            )
            return fallback

        log_llm_prompt(
            component=component,
            backend=backend,
            model=self._settings.tool_result_summary_model,
            prompt=prompt,
            metadata=metadata or {},
        )
        try:
            model = self._build_text_model()
            resp = await model.ainvoke(prompt)
            content = (getattr(resp, "content", "") or "").strip()
            if not content:
                return fallback
            return content.replace("\n", " ").strip()
        except Exception as exc:
            log_event(
                f"{component}_failed",
                level="WARNING",
                error=str(exc),
                **(metadata or {}),
            )
            return fallback

    async def _build_not_found_summary(self, *, tool_name: str, args: dict[str, Any], body: dict[str, Any] | None) -> str:
        detail = (body or {}).get("detail")
        if isinstance(detail, str) and detail.strip():
            fallback = detail.strip()
        else:
            target = (
                args.get("id")
                or args.get("machine_id")
                or args.get("job_id")
                or args.get("material_id")
                or args.get("inventory_id")
                or args.get("proposal_id")
                or args.get("approval_id")
            )
            fallback = (
                f"Requested resource {target} was not found."
                if target not in (None, "")
                else "Requested resource was not found."
            )

        prompt = (
            "Write one short operator-facing sentence for a not-found tool call.\n"
            "Rules:\n"
            "- Use only the provided tool name, args, and response body.\n"
            "- Do not invent entities or IDs.\n"
            "- Keep <= 20 words.\n\n"
            f"Tool: {tool_name}\n"
            f"Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
            f"Response: {json.dumps(body or {}, ensure_ascii=False)}\n"
        )
        generated = await self._compose_text(
            component="not_found_summary",
            prompt=prompt,
            fallback=fallback,
            metadata={"tool_name": tool_name},
        )
        if "not found" not in generated.lower():
            return fallback
        return generated

    def _is_soft_not_found(self, *, tool: ToolInfo, http_status: int | None, body: dict[str, Any] | None) -> bool:
        return bool(tool.is_read_only and tool.method == "GET" and http_status == 404 and isinstance(body, dict))

    def _tool_result_summary_backend(self) -> str:
        backend = (self._settings.tool_result_summary_backend or "auto").strip().lower()
        if backend == "auto":
            if self._settings.tool_result_summary_openai_base_url or self._settings.openai_api_key:
                return "langchain"
            return "deterministic"
        return backend

    def _summarize_step_result_fallback(self, *, tool_name: str, body: dict[str, Any] | None) -> str:
        if body is None:
            return f"{tool_name} completed."
        if isinstance(body, dict):
            if body.get("not_found"):
                summary = body.get("_summary")
                if isinstance(summary, str) and summary.strip():
                    return summary.strip()
            for key in ("message", "detail", "status", "summary"):
                val = body.get(key)
                if isinstance(val, str) and val.strip():
                    return f"{tool_name}: {val.strip()}"
            if isinstance(body.get("data"), list):
                return f"{tool_name} completed. Returned {len(body['data'])} record(s)."
            if isinstance(body.get("items"), list):
                return f"{tool_name} completed. Retrieved {len(body['items'])} item(s)."
            keys = ", ".join(list(body.keys())[:4])
            return f"{tool_name} completed. Response keys: {keys or 'none'}."
        return f"{tool_name} completed."

    def _result_has_records(self, body: dict[str, Any] | None) -> bool:
        if not isinstance(body, dict):
            return False
        data = body.get("data")
        if isinstance(data, list) and len(data) > 0:
            return True
        items = body.get("items")
        if isinstance(items, list) and len(items) > 0:
            return True
        data_count = body.get("data_count")
        try:
            if data_count is not None and int(data_count) > 0:
                return True
        except Exception:
            pass
        return False

    def _attach_result_analysis(self, *, body: dict[str, Any] | None, intent: str | None) -> dict[str, Any] | None:
        if not isinstance(body, dict):
            return body
        analysis = analyze_result(intent=intent or "", result=body)
        if analysis is None:
            return body
        enriched = dict(body)
        enriched["_analysis"] = {
            "dataset": asdict(analysis.dataset),
            "operations": [asdict(operation) for operation in analysis.operations],
            "results": analysis.results,
            "facts": analysis.facts,
            "grounding_refs": analysis.grounding_refs,
        }
        return enriched

    async def _summarize_step_result(
        self,
        *,
        tool_name: str,
        body: dict[str, Any] | None,
        args: dict[str, Any] | None = None,
        intent: str | None = None,
    ) -> str:
        fallback = self._summarize_step_result_fallback(tool_name=tool_name, body=body)
        if not isinstance(body, dict):
            return fallback
        render_context = extract_table_from_result(tool_name=tool_name, result=body, intent=intent)

        facts = await self._reasoning.extract_facts(
            intent=intent or "tool_result_summary",
            tool_name=tool_name,
            args=args or {},
            result=body,
        )
        if facts:
            policy = self._reasoning.response_policy(facts=facts)
            deterministic_contract = self._reasoning.deterministic_response_contract(facts=facts)
            if policy == "deterministic" and deterministic_contract:
                return deterministic_contract
            if policy == "deterministic":
                return self._reasoning.fallback_response_from_facts(facts=facts)
            if not self._reasoning.should_generate_response(facts=facts):
                return self._reasoning.fallback_response_from_facts(facts=facts)
            generated = await self._reasoning.generate_response(
                intent=intent or "tool_result_summary",
                facts=facts,
                render_context=render_context,
            )
            if generated:
                grounded = await self._reasoning.verify_grounding(response_text=generated, facts=facts)
                if grounded:
                    return generated
                return self._reasoning.fallback_response_from_facts(facts=facts)
            return self._reasoning.fallback_response_from_facts(facts=facts)

        prompt_payload = body
        try:
            raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
            if len(raw) > 3500:
                raw = raw[:3500] + "..."
                prompt_payload = {"truncated": True, "preview": raw}
        except Exception:
            prompt_payload = {"unserializable": True}

        prompt = (
            "You are writing a short operator-facing status message for a factory tool result.\n"
            "Rules:\n"
            "- Use only facts present in the result JSON.\n"
            "- Never invent IDs or statuses.\n"
            "- Keep it short (1 sentence, <= 25 words).\n"
            "- Use simple language.\n\n"
            f"Tool: {tool_name}\n"
            f"Tool Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
            f"Result JSON: {json.dumps(prompt_payload, ensure_ascii=False)}\n"
        )
        return await self._compose_text(
            component="tool_result_summary",
            prompt=prompt,
            fallback=fallback,
            metadata={"tool_name": tool_name},
        )

    async def _build_approval_risk_summary(
        self,
        *,
        tool: ToolInfo,
        args: dict[str, Any],
        target_preview: str | None = None,
    ) -> str:
        target = self._entity_label(args)
        fallback = f"This request will perform a write operation for {target}."
        if target_preview:
            fallback = f"{fallback} Target check: {target_preview}"
        prompt = (
            "Write one short approval risk summary for operators.\n"
            "Rules:\n"
            "- Mention this is a write-side effect.\n"
            "- Use only facts provided below.\n"
            "- One sentence, <= 25 words.\n\n"
            f"Tool: {tool.name}\n"
            f"Method: {tool.method}\n"
            f"Endpoint: {tool.endpoint}\n"
            f"Args: {json.dumps(args or {}, ensure_ascii=False)}\n"
            f"Target preview: {target_preview or ''}\n"
        )
        return await self._compose_text(
            component="approval_risk_summary",
            prompt=prompt,
            fallback=fallback,
            metadata={"tool_name": tool.name},
        )

    async def _build_completion_text(self, *, plan_kind: str, step_count: int) -> str:
        fallback = (
            "Safe discovery completed. Preparing execution proposal."
            if (plan_kind or "execution") == "discovery"
            else f"Execution completed successfully. {step_count} step(s) completed."
        )
        prompt = (
            "Write one short completion message for a workflow engine.\n"
            "Rules:\n"
            "- One sentence.\n"
            "- Mention completion outcome.\n"
            "- Use only the context below.\n\n"
            f"Plan kind: {plan_kind}\n"
            f"Completed steps: {step_count}\n"
        )
        return await self._compose_text(
            component="session_completion_text",
            prompt=prompt,
            fallback=fallback,
            metadata={"plan_kind": plan_kind, "step_count": step_count},
        )

    def _approval_target_identifier(self, args: dict[str, Any]) -> Any | None:
        return (
            args.get("id")
            or args.get("machine_id")
            or args.get("job_id")
            or args.get("inventory_id")
            or args.get("material_id")
            or args.get("proposal_id")
            or args.get("approval_id")
        )

    def _is_preapproval_probe_candidate(self, *, tool: ToolInfo, args: dict[str, Any]) -> bool:
        if tool.method not in {"PUT", "PATCH", "DELETE"}:
            return False
        if "{id}" not in (tool.endpoint or ""):
            return False
        return self._approval_target_identifier(args) not in (None, "")

    async def _probe_entity_for_approval(
        self,
        *,
        endpoint: str,
        args: dict[str, Any],
        summary_tool_name: str,
    ) -> tuple[bool | None, str | None]:
        path_args = {"id": self._approval_target_identifier(args)}
        rendered_endpoint, leftover_path_args = self._materialize_endpoint(endpoint=endpoint, args=path_args)
        if leftover_path_args:
            path_args.update(leftover_path_args)
        url = f"{self._settings.go_api_base_url}{rendered_endpoint}"
        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
                resp = await client.get(url)
        except (httpx.TimeoutException, httpx.NetworkError):
            return None, None

        payload: dict[str, Any] | None = None
        try:
            if resp.content:
                parsed = resp.json()
                if isinstance(parsed, dict):
                    payload = parsed
        except Exception:
            payload = None

        if resp.status_code == 404:
            summary = await self._build_not_found_summary(tool_name=summary_tool_name, args=args, body=payload)
            return False, summary
        if resp.status_code >= 400:
            return None, None
        if isinstance(payload, dict):
            return True, await self._summarize_step_result(tool_name=summary_tool_name, body=payload, args=args)
        return True, None

    async def _preflight_approval_guard(
        self,
        *,
        session: SessionRow,
        plan: PlanRow,
        step: PlanStepRow,
        tool: ToolInfo,
        db: AsyncSession,
    ) -> tuple[bool, str | None]:
        args = step.args or {}
        if not self._is_preapproval_probe_candidate(tool=tool, args=args):
            return False, None

        exists, preview = await self._probe_entity_for_approval(
            endpoint=tool.endpoint or "",
            args=args,
            summary_tool_name=tool.name,
        )
        if exists is False:
            generated = await self._build_not_found_summary(tool_name=tool.name, args=args, body=None)
            summary = (preview or generated).strip()
            summary = f"{summary} No changes were made."
            step.status = "DONE"
            step.result = {"not_found": True, "_summary": summary, "preflight": True}
            step.result_summary = summary
            step.completed_at = datetime.utcnow()
            self._log_step_status_change(session=session, plan=plan, step=step, tool=tool, status=step.status)
            await self._append_tool_result_message(
                db,
                session_id=session.session_id,
                step=step,
                intent=session.current_intent,
            )
            session.current_step_index += 1
            session.step_count += 1
            session.version += 1
            await db.commit()
            return True, None

        risk_summary_override = None
        if preview:
            risk_summary_override = await self._build_approval_risk_summary(tool=tool, args=args, target_preview=preview)
        return False, risk_summary_override

    async def _append_tool_result_message(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        step: PlanStepRow,
        intent: str | None = None,
    ) -> None:
        text = step.result_summary or await self._summarize_step_result(
            tool_name=step.tool_name,
            body=step.result,
            args=step.args,
            intent=intent,
        )
        msg = MessageRow(
            message_id=generate_uuid(),
            session_id=session_id,
            role="tool_result",
            content=text,
            step_id=step.step_id,
            tool_name=step.tool_name,
        )
        db.add(msg)
        await self._memory_manager.index_message(
            db,
            session_id=session_id,
            message_id=msg.message_id,
            role="tool_result",
            content=text,
            tool_name=step.tool_name,
            commit=False,
        )

    def _log_step_status_change(
        self,
        *,
        session: SessionRow,
        plan: PlanRow | None,
        step: PlanStepRow,
        tool: ToolInfo | None,
        status: str,
        latency_ms: int | None = None,
        http_status: int | None = None,
        idempotent_replay: bool = False,
        approval_latency_ms: int | None = None,
    ) -> None:
        log_step_status_changed(
            session_id=session.session_id,
            plan_id=plan.plan_id if plan else session.plan_id,
            plan_version=plan.version if plan else session.plan_version,
            step_id=step.step_id,
            step_index=step.step_index,
            tool=(tool.name if tool else step.tool_name or ""),
            is_strongly_idempotent=bool(tool.is_strongly_idempotent) if tool else None,
            status=status,
            latency_ms=latency_ms,
            http_status=http_status,
            idempotency_key=step.idempotency_key,
            idempotent_replay=idempotent_replay,
            required_approval=bool(step.requires_approval),
            approval_latency_ms=approval_latency_ms,
            session_step_count=session.step_count,
            session_llm_call_count=session.llm_call_count,
            session_replan_count=session.replan_count,
            session_duration_s=self._session_duration_s(session),
            user_id=session.user_id,
        )

    async def _push_dlq(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        step_id: str | None,
        failure_type: str,
        reason: str,
        payload: dict[str, Any],
    ) -> DeadLetterRow:
        dlq = DeadLetterRow(
            dlq_id=generate_uuid(),
            session_id=session_id,
            step_id=step_id,
            failure_type=failure_type,
            reason=reason,
            payload=payload,
            status="PENDING",
        )
        db.add(dlq)
        await db.commit()
        await db.refresh(dlq)
        metrics.inc("dlq_push_total", labels={"failure_type": failure_type})
        metrics.inc("dlq_push_rate", labels={"failure_type": failure_type})
        log_event(
            "dlq_pushed",
            level="WARNING",
            session_id=session_id,
            step_id=step_id,
            failure_type=failure_type,
            reason=reason,
            dlq_id=dlq.dlq_id,
        )
        return dlq

    async def _create_approval(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        step: PlanStepRow,
        tool: ToolInfo,
        risk_summary_override: str | None = None,
    ) -> ApprovalRow:
        risk_summary = risk_summary_override
        if not risk_summary:
            risk_summary = await self._build_approval_risk_summary(tool=tool, args=step.args or {})

        approval = ApprovalRow(
            approval_id=generate_uuid(),
            session_id=session_id,
            subject_type="step",
            plan_id=None,
            step_id=step.step_id,
            tool_name=tool.name,
            args=step.args,
            risk_summary=risk_summary,
            side_effect_level=tool.side_effect_level or "HIGH",
            status="PENDING",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.add(approval)
        step.approval_id = approval.approval_id
        step.requires_approval = True
        session = await db.get(SessionRow, session_id)
        if session:
            session.version += 1
        await db.commit()
        await db.refresh(approval)
        log_event(
            "approval_created",
            session_id=session_id,
            step_id=step.step_id,
            tool=tool.name,
            side_effect_level=tool.side_effect_level,
        )
        return approval

    def _bulk_risk_summary(self, *, tool: ToolInfo, step: PlanStepRow) -> str | None:
        state = step.bulk_state if isinstance(getattr(step, "bulk_state", None), dict) else {}
        total = int(state.get("total_items") or 0)
        if total <= 0:
            return None
        threshold = int(state.get("max_foreach_items") or self._settings.max_foreach_items)
        if total > threshold:
            return (
                f"This bulk write will run `{tool.name}` for {total} item(s), "
                f"which exceeds the safe threshold of {threshold}."
            )
        return f"This bulk write will run `{tool.name}` for {total} item(s)."

    async def _auto_page_items(
        self,
        *,
        source_tool: ToolInfo,
        source_step: PlanStepRow,
        initial_items: list[dict[str, Any]],
        result_path: str,
        plan: PlanRow,
        session: SessionRow,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        if "limit" not in set(source_tool.query_params or []) or "offset" not in set(source_tool.query_params or []):
            return initial_items
        if "limit" in (source_step.args or {}) or "offset" in (source_step.args or {}):
            return initial_items
        if not initial_items or self._settings.max_auto_pages <= 1:
            return initial_items

        items = list(initial_items)
        for page_index in range(1, max(1, self._settings.max_auto_pages)):
            page_args = dict(source_step.args or {})
            page_args["limit"] = self._settings.foreach_page_size
            page_args["offset"] = len(items)
            page_key = compute_idempotency_key(
                session_id=session.session_id,
                step_index=source_step.step_index,
                plan_version=plan.version,
                args={**page_args, "__auto_page": page_index},
            )
            body, _ = await self._execute_tool_call(
                tool=source_tool,
                args=page_args,
                idempotency_key=page_key,
                plan_hash=plan.plan_hash,
                plan_version=plan.version,
                session_id=session.session_id,
                step_id=source_step.step_id,
                db=db,
            )
            page_items = _items_at_path(body, result_path)
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < self._settings.foreach_page_size:
                break
        return items

    async def _prepare_bound_step(
        self,
        *,
        db: AsyncSession,
        session: SessionRow,
        plan: PlanRow,
        step: PlanStepRow,
        tool: ToolInfo,
        steps_by_index: dict[int, PlanStepRow],
        tools_by_name: dict[str, ToolInfo],
    ) -> None:
        bindings = [binding for binding in (step.bindings or []) if isinstance(binding, dict)]
        if not bindings:
            return
        foreach_bindings = [binding for binding in bindings if binding.get("mode") == "foreach"]
        args = dict(step.args or {})

        if not foreach_bindings:
            for binding in bindings:
                source_step = steps_by_index.get(int(binding.get("from_step")))
                if not source_step or source_step.status != "DONE":
                    raise ToolInputError(f"Binding source step {binding.get('from_step')} has not completed.")
                items = _items_at_path(source_step.result if isinstance(source_step.result, dict) else None, str(binding.get("result_path") or "data"))
                if not items:
                    raise AmbiguousExecutionError(f"Binding source step {source_step.step_index} returned no usable items.")
                value = items[0].get(str(binding.get("field")))
                if value in (None, ""):
                    raise AmbiguousExecutionError(f"Binding field {binding.get('field')} was missing from source result.")
                args[str(binding.get("target_arg"))] = value
            if args != (step.args or {}):
                step.args = args
                step.idempotency_key = compute_idempotency_key(
                    session_id=session.session_id,
                    step_index=step.step_index,
                    plan_version=plan.version,
                    args=args,
                )
                await db.commit()
            return

        source_index = int(foreach_bindings[0].get("from_step"))
        source_step = steps_by_index.get(source_index)
        source_tool = tools_by_name.get(source_step.tool_name) if source_step else None
        if not source_step or not source_tool or source_step.status != "DONE":
            raise ToolInputError(f"Foreach source step {source_index} has not completed.")
        result_path = str(foreach_bindings[0].get("result_path") or "data")
        items = _items_at_path(source_step.result if isinstance(source_step.result, dict) else None, result_path)
        items = await self._auto_page_items(
            source_tool=source_tool,
            source_step=source_step,
            initial_items=items,
            result_path=result_path,
            plan=plan,
            session=session,
            db=db,
        )
        prepared_args: list[dict[str, Any]] = []
        for item in items:
            item_args = dict(args)
            skip = False
            for binding in foreach_bindings:
                value = item.get(str(binding.get("field")))
                if value in (None, ""):
                    skip = True
                    break
                item_args[str(binding.get("target_arg"))] = value
            if not skip:
                prepared_args.append(item_args)
        if not prepared_args:
            raise AmbiguousExecutionError("Foreach binding resolved zero executable items.")
        existing_state = step.bulk_state if isinstance(step.bulk_state, dict) else {}
        step.bulk_state = {
            **existing_state,
            "total_items": len(prepared_args),
            "max_foreach_items": self._settings.max_foreach_items,
            "max_auto_pages": self._settings.max_auto_pages,
            "prepared_args": prepared_args,
            "requires_bulk_approval": len(prepared_args) > self._settings.max_foreach_items,
        }
        flag_modified(step, "bulk_state")
        await db.commit()

    async def _execute_foreach_step(
        self,
        *,
        tool: ToolInfo,
        step: PlanStepRow,
        plan: PlanRow,
        session: SessionRow,
        db: AsyncSession,
    ) -> dict[str, Any]:
        state = step.bulk_state if isinstance(step.bulk_state, dict) else {}
        prepared_args = state.get("prepared_args") if isinstance(state.get("prepared_args"), list) else []
        if not prepared_args:
            raise ToolInputError("Foreach step has no prepared item args.")

        succeeded = list(state.get("succeeded") or [])
        failed = list(state.get("failed") or [])
        succeeded_indexes = {int(item.get("index")) for item in succeeded if isinstance(item, dict) and "index" in item}

        for index, item_args in enumerate(prepared_args):
            if index in succeeded_indexes:
                continue
            if not isinstance(item_args, dict):
                continue
            item_key = compute_idempotency_key(
                session_id=session.session_id,
                step_index=step.step_index,
                plan_version=plan.version,
                args={**item_args, "__foreach_index": index},
            )
            existing_snapshot = (
                await db.execute(
                    select(SnapshotRow)
                    .where(SnapshotRow.idempotency_key == item_key)
                    .where(SnapshotRow.plan_hash == plan.plan_hash)
                    .order_by(SnapshotRow.executed_at.desc())
                )
            ).scalars().first()
            if existing_snapshot and existing_snapshot.http_status and existing_snapshot.http_status < 400:
                succeeded.append({"index": index, "idempotency_key": item_key, "replayed": True})
                step.bulk_state = {**state, "succeeded": succeeded, "failed": failed}
                flag_modified(step, "bulk_state")
                await db.commit()
                continue
            try:
                body, _ = await self._execute_tool_call(
                    tool=tool,
                    args=item_args,
                    idempotency_key=item_key,
                    plan_hash=plan.plan_hash,
                    plan_version=plan.version,
                    session_id=session.session_id,
                    step_id=step.step_id,
                    db=db,
                )
                succeeded.append({"index": index, "idempotency_key": item_key, "result": body})
                state = {**state, "succeeded": succeeded, "failed": failed}
                step.bulk_state = state
                flag_modified(step, "bulk_state")
                await db.commit()
            except Exception as exc:
                decision = self._classify_error(err=exc, tool=tool, step=step)
                failed.append({"index": index, "args": item_args, "error": str(exc), "decision": decision})
                step.bulk_state = {**state, "succeeded": succeeded, "failed": failed}
                flag_modified(step, "bulk_state")
                await db.commit()
                if decision == "RETRY":
                    raise
                raise AmbiguousExecutionError(
                    f"Bulk step stopped after {len(succeeded)} success(es) and {len(failed)} failure(s): {exc}"
                ) from exc

        return {
            "bulk": True,
            "total": len(prepared_args),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "items": succeeded[:20],
        }

    async def _record_snapshot(
        self,
        db: AsyncSession,
        *,
        step_id: str,
        session_id: str,
        tool: ToolInfo,
        args: dict[str, Any],
        plan_hash: str,
        plan_version: int,
        idempotency_key: str,
        http_status: int | None,
        response_body: dict[str, Any] | None,
        latency_ms: int | None,
    ) -> None:
        snapshot = SnapshotRow(
            snapshot_id=generate_uuid(),
            step_id=step_id,
            session_id=session_id,
            tool_name=tool.name,
            tool_version=1,
            schema_version=1,
            input_args=args,
            plan_hash=plan_hash,
            plan_version=plan_version,
            idempotency_key=idempotency_key,
            http_status=http_status,
            response_body=response_body,
            latency_ms=latency_ms,
            executed_at=datetime.utcnow(),
        )
        db.add(snapshot)
        await db.commit()

    def _materialize_endpoint(self, *, endpoint: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        used_keys: set[str] = set()
        unresolved_keys: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = args.get(key)
            if value is None:
                unresolved_keys.add(key)
                return match.group(0)
            used_keys.add(key)
            return quote(str(value), safe="")

        rendered = _PATH_PARAM_RE.sub(replace, endpoint)
        if unresolved_keys:
            missing = ", ".join(sorted(unresolved_keys))
            raise ToolInputError(f"Missing required path args: {missing}")
        remaining_args = {key: value for key, value in args.items() if key not in used_keys}
        return rendered, remaining_args

    async def _execute_tool_call(
        self,
        *,
        tool: ToolInfo,
        args: dict[str, Any],
        idempotency_key: str,
        plan_hash: str,
        plan_version: int,
        session_id: str,
        step_id: str,
        db: AsyncSession,
    ) -> tuple[dict[str, Any] | None, int]:
        path_args, query_args, body_args = _normalize_tool_args(tool, args)
        rendered_endpoint, leftover_path_args = self._materialize_endpoint(endpoint=tool.endpoint, args=path_args)
        if leftover_path_args:
            path_args.update(leftover_path_args)
        url = f"{self._settings.go_api_base_url}{rendered_endpoint}"
        headers = {
            "Idempotency-Key": idempotency_key,
            "X-Idempotency-Key": idempotency_key,
            "X-Plan-Hash": plan_hash,
            "X-Plan-Version": str(plan_version),
            "X-Payload-Hash": compute_payload_hash(args=args),
        }

        start = time.time()
        body: dict[str, Any] | None = None
        try:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
                if tool.method == "GET":
                    params = query_args or body_args
                    resp = await client.get(url, params=params, headers=headers)
                elif tool.method == "POST":
                    resp = await client.post(url, params=query_args or None, json=body_args, headers=headers)
                elif tool.method == "PUT":
                    resp = await client.put(url, params=query_args or None, json=body_args, headers=headers)
                elif tool.method == "PATCH":
                    resp = await client.patch(url, params=query_args or None, json=body_args, headers=headers)
                elif tool.method == "DELETE":
                    resp = await client.request("DELETE", url, params=query_args or None, json=body_args or None, headers=headers)
                else:
                    raise ValueError(f"Unsupported method: {tool.method}")
        except httpx.TimeoutException as e:
            await self._record_snapshot(
                db,
                step_id=step_id,
                session_id=session_id,
                tool=tool,
                args=args,
                plan_hash=plan_hash,
                plan_version=plan_version,
                idempotency_key=idempotency_key,
                http_status=None,
                response_body={"error_type": "timeout", "message": str(e)},
                latency_ms=int((time.time() - start) * 1000),
            )
            raise ToolNetworkError(str(e), request_was_sent=True) from e
        except httpx.NetworkError as e:
            await self._record_snapshot(
                db,
                step_id=step_id,
                session_id=session_id,
                tool=tool,
                args=args,
                plan_hash=plan_hash,
                plan_version=plan_version,
                idempotency_key=idempotency_key,
                http_status=None,
                response_body={"error_type": "network", "message": str(e)},
                latency_ms=int((time.time() - start) * 1000),
            )
            raise ToolNetworkError(str(e), request_was_sent=False) from e

        latency_ms = int((time.time() - start) * 1000)
        try:
            if resp.content:
                body = resp.json()
        except Exception:
            body = {"raw": resp.text}

        await self._record_snapshot(
            db,
            step_id=step_id,
            session_id=session_id,
            tool=tool,
            args=args,
            plan_hash=plan_hash,
            plan_version=plan_version,
            idempotency_key=idempotency_key,
            http_status=resp.status_code,
            response_body=body,
            latency_ms=latency_ms,
        )
        metrics.observe("step_execution_latency_ms", latency_ms, labels={"tool": tool.name})
        log_event(
            "step_http_result",
            session_id=session_id,
            step_id=step_id,
            tool=tool.name,
            method=tool.method,
            endpoint=rendered_endpoint,
            status=resp.status_code,
            latency_ms=latency_ms,
            idempotency_key=idempotency_key,
        )

        if self._is_soft_not_found(tool=tool, http_status=resp.status_code, body=body):
            body = dict(body)
            body["not_found"] = True
            body["_summary"] = await self._build_not_found_summary(tool_name=tool.name, args=args, body=body)
            return body, latency_ms

        if resp.status_code >= 400:
            raise ToolHTTPError(resp.status_code, body)
        return body, latency_ms

    def _classify_error(self, *, err: Exception, tool: ToolInfo, step: PlanStepRow) -> FailureDecision:
        if isinstance(err, AmbiguousExecutionError):
            return "AMBIGUOUS"
        if isinstance(err, PredicateVerificationError):
            return "REPLAN"
        if isinstance(err, ToolNetworkError):
            if tool.is_strongly_idempotent and step.retry_count < step.max_retries:
                return "RETRY"
            if err.request_was_sent:
                return "AMBIGUOUS"
            return "REPLAN"

        if isinstance(err, ToolHTTPError):
            status_code = err.status_code
            if status_code in (400, 404, 409):
                return "REPLAN"
            if status_code in (401, 403):
                return "FAIL_HARD"
            if status_code >= 500:
                if tool.is_strongly_idempotent and step.retry_count < step.max_retries:
                    return "RETRY"
                return "REPLAN"
            return "FAIL_HARD"

        if isinstance(err, ToolInputError):
            return "REPLAN"

        return "FAIL_HARD"

    def _contract_clause_for_step(self, *, session: SessionRow, step: PlanStepRow) -> dict[str, Any] | None:
        context = session.replan_context if isinstance(session.replan_context, dict) else {}
        contract = context.get("intent_contract") if isinstance(context.get("intent_contract"), dict) else {}
        clauses = contract.get("clauses") if isinstance(contract.get("clauses"), list) else []
        for clause in clauses:
            if not isinstance(clause, dict):
                continue
            if clause.get("tool_name") == step.tool_name and int(clause.get("step_index", step.step_index)) == int(step.step_index):
                return clause
        if 0 <= int(step.step_index or 0) < len(clauses):
            candidate = clauses[int(step.step_index or 0)]
            return candidate if isinstance(candidate, dict) else None
        return None

    def _verify_predicate_contract(
        self,
        *,
        session: SessionRow,
        step: PlanStepRow,
        tool: ToolInfo,
        body: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if tool.method != "GET":
            return None
        clause = self._contract_clause_for_step(session=session, step=step)
        if not clause:
            return None
        predicates = clause.get("predicates") if isinstance(clause.get("predicates"), list) else []
        requested = [p for p in predicates if isinstance(p, dict) and p.get("requested")]
        if not requested:
            return None

        path_args, query_args, body_args = _normalize_tool_args(tool, step.args or {})
        sent_args = {**body_args, **path_args, **query_args}
        items = _result_items(body)
        coverage_predicates: list[dict[str, Any]] = []
        errors: list[str] = []
        unknowns = 0
        verified_count = 0
        for pred in requested:
            field = pred.get("field")
            expected = pred.get("value")
            current = dict(pred)
            sent = bool(field and field in sent_args and sent_args.get(field) not in (None, ""))
            current["sent"] = sent
            if not pred.get("resolved") or not field:
                errors.append(f"predicate unresolved: {pred.get('raw_term')}")
                current["verified"] = False
            elif not sent:
                errors.append(f"predicate not sent: {field}={expected}")
                current["verified"] = False
            elif items is None:
                current["verified"] = "unknown"
                current["reason"] = "response has no comparable list/data field"
                unknowns += 1
            elif len(items) == 0:
                # Empty result is AMBIGUOUS: the filter may be correct (no data)
                # OR the term was mapped to the wrong field.  Mark unknown_empty so
                # the repair loop in _repair_empty_predicate_result can investigate
                # alternative candidate fields before surfacing the result.
                current["verified"] = "unknown_empty"
                current["reason"] = "empty result â€” filter sent but result is ambiguous; repair loop may retry"
                unknowns += 1
            else:
                comparable = [item for item in items if field in item]
                if not comparable:
                    current["verified"] = "unknown"
                    current["reason"] = "response rows do not include comparable field"
                    unknowns += 1
                else:
                    expected_norm = normalize_predicate_value(str(expected))
                    mismatches = [
                        item.get(field)
                        for item in comparable
                        if normalize_predicate_value(str(item.get(field))) != expected_norm
                    ]
                    if mismatches:
                        current["verified"] = False
                        current["reason"] = "comparable rows did not match predicate"
                        errors.append(f"predicate mismatch: {field}={expected}")
                    else:
                        current["verified"] = True
                        current["reason"] = "all comparable rows matched"
                        verified_count += 1
            coverage_predicates.append(current)

        total_checks = max(1, len(requested) * 3)
        met = 0
        for pred in coverage_predicates:
            for key in ("requested", "resolved", "sent"):
                if pred.get(key):
                    met += 1
        coverage = {
            "predicates": coverage_predicates,
            "predicate_coverage_score": round(met / total_checks, 3),
            "verified_count": verified_count,
            "unknown_count": unknowns,
            "errors": errors,
        }
        if errors:
            log_event(
                "predicate_verifier_blocked",
                level="WARNING",
                session_id=session.session_id,
                step_id=step.step_id,
                tool=tool.name,
                coverage=coverage,
            )
            raise PredicateVerificationError("; ".join(errors), coverage=coverage)
        log_event(
            "predicate_verifier_passed",
            session_id=session.session_id,
            step_id=step.step_id,
            tool=tool.name,
            coverage=coverage,
        )
        return coverage

    # ------------------------------------------------------------------
    # Schema-field repair loop
    # ------------------------------------------------------------------

    def _get_repair_candidates(
        self,
        *,
        session: SessionRow,
        step: PlanStepRow,
        tool: ToolInfo,
        live_coverage: dict[str, Any],
        tried_args: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return ordered list of untried (field, value) pairs from the predicate
        candidate_fields that were recorded during intent verification.

        Uses the live coverage dict (from _verify_predicate_contract) to find
        predicates that came back unknown_empty, then reads candidate_fields from
        the planning-time contract clause to discover alternatives."""
        # Live coverage tells us which predicates are ambiguous right now.
        live_preds = live_coverage.get("predicates") if isinstance(live_coverage.get("predicates"), list) else []
        unknown_fields: dict[str, str] = {}  # field -> raw_term
        for p in live_preds:
            if not isinstance(p, dict):
                continue
            if p.get("verified") == "unknown_empty":
                field = p.get("field")
                value = p.get("value") or p.get("raw_term")
                if field and value:
                    unknown_fields[str(field)] = str(value)
        if not unknown_fields:
            return []

        # The planning-time contract clause holds candidate_fields per predicate.
        clause = self._contract_clause_for_step(session=session, step=step)
        contract_preds = clause.get("predicates") if clause and isinstance(clause.get("predicates"), list) else []
        properties = (tool.input_schema or {}).get("properties", {})
        candidates: list[dict[str, Any]] = []

        for pred in contract_preds:
            if not isinstance(pred, dict):
                continue
            tried_field = pred.get("field")
            # Only process predicates whose tried field is ambiguous.
            if tried_field not in unknown_fields:
                continue
            raw_term = unknown_fields[tried_field]
            for cand in pred.get("candidate_fields") or []:
                if not isinstance(cand, dict):
                    continue
                alt_field = cand.get("field")
                if not isinstance(alt_field, str) or not alt_field:
                    continue
                if alt_field == tried_field:
                    continue
                if alt_field not in properties:
                    continue
                # Skip if we already tried this field in a previous repair attempt.
                if tried_args.get(alt_field) not in (None, ""):
                    continue
                candidates.append(
                    {
                        "field": alt_field,
                        "value": raw_term,
                        "confidence": float(cand.get("confidence") or 0.0),
                        "reason": str(cand.get("reason") or ""),
                        "tried_field": tried_field,
                    }
                )
        # Highest-confidence alternative first.
        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        # Deduplicate by (field, value) while preserving order.
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for c in candidates:
            key = (c["field"], str(c["value"]).lower())
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        return deduped

    async def _repair_empty_predicate_result(
        self,
        *,
        session: SessionRow,
        plan: PlanRow,
        step: PlanStepRow,
        tool: ToolInfo,
        original_args: dict[str, Any],
        original_body: dict[str, Any] | None,
        live_coverage: dict[str, Any],
        db: AsyncSession,
    ) -> dict[str, Any] | None:
        return await execution_runtime._repair_empty_predicate_result(
            self,
            session=session,
            plan=plan,
            step=step,
            tool=tool,
            original_args=original_args,
            original_body=original_body,
            live_coverage=live_coverage,
            db=db,
        )

    async def _claim_step(self, db: AsyncSession, *, step_id: str) -> bool:
        stmt = (
            update(PlanStepRow)
            .where(PlanStepRow.step_id == step_id)
            .where(PlanStepRow.status.in_(["NOT_STARTED", "FAILED"]))
            .values(status="IN_PROGRESS", started_at=datetime.utcnow())
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount == 1

    def _parallel_groups_for_plan(self, plan: PlanRow) -> list[list[int]]:
        if not self._settings.enable_parallel_execution:
            return []
        groups = plan.parallel_groups if isinstance(plan.parallel_groups, list) else []
        normalized: list[list[int]] = []
        for group in groups:
            if not isinstance(group, list):
                continue
            indexes = sorted({int(idx) for idx in group})
            if len(indexes) >= 2:
                normalized.append(indexes)
        return normalized

    async def _complete_step_with_body(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        plan: PlanRow,
        step: PlanStepRow,
        tool: ToolInfo,
        body: dict[str, Any] | None,
    ) -> None:
        coverage = self._verify_predicate_contract(
            session=session,
            step=step,
            tool=tool,
            body=body,
        )
        if coverage and coverage.get("unknown_count", 0) > 0 and tool.method == "GET":
            repaired = await self._repair_empty_predicate_result(
                session=session,
                plan=plan,
                step=step,
                tool=tool,
                original_args=step.args or {},
                original_body=body,
                live_coverage=coverage,
                db=db,
            )
            if repaired is not None:
                body = repaired
                coverage = self._verify_predicate_contract(
                    session=session,
                    step=step,
                    tool=tool,
                    body=body,
                )
        if coverage and isinstance(body, dict):
            body["_predicate_coverage"] = coverage
        body = self._attach_result_analysis(body=body, intent=session.current_intent) or body
        step.status = "DONE"
        step.result = body
        step.result_summary = await self._summarize_step_result(
            tool_name=tool.name,
            body=body,
            args=step.args,
            intent=session.current_intent,
        )
        step.completed_at = datetime.utcnow()
        self._log_step_status_change(
            session=session,
            plan=plan,
            step=step,
            tool=tool,
            status=step.status,
        )
        log_event(
            "step_completed",
            session_id=session.session_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            step_id=step.step_id,
            step_index=step.step_index,
            tool=tool.name,
            status=step.status,
            session_step_count=session.step_count,
            session_llm_call_count=session.llm_call_count,
            session_replan_count=session.replan_count,
        )
        await self._append_tool_result_message(
            db,
            session_id=session.session_id,
            step=step,
            intent=session.current_intent,
        )
        session.step_count += 1

    async def _execute_parallel_group(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        plan: PlanRow,
        group_steps: list[PlanStepRow],
        steps: list[PlanStepRow],
        tools_by_name: dict[str, ToolInfo],
    ) -> ExecuteResult | None:
        return await execution_runtime._execute_parallel_group(
            self,
            db,
            session=session,
            plan=plan,
            group_steps=group_steps,
            steps=steps,
            tools_by_name=tools_by_name,
        )

    def _build_replan_context(
        self,
        *,
        session: SessionRow,
        steps: list[PlanStepRow],
        failed_step: PlanStepRow | None,
        reason: str,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        completed = []
        for s in steps:
            if s.status == "DONE":
                completed.append(
                    {
                        "step_index": s.step_index,
                        "tool_name": s.tool_name,
                        "args": s.args,
                        "result": s.result,
                    }
                )
        context: dict[str, Any] = {
            "original_intent": session.current_intent,
            "plan_id": session.plan_id,
            "plan_version": session.plan_version,
            "completed_steps": completed,
            "error": reason,
            "failed_step": None,
        }
        if failed_step is not None:
            context["failed_step"] = {
                "step_id": failed_step.step_id,
                "step_index": failed_step.step_index,
                "tool_name": failed_step.tool_name,
                "args": failed_step.args,
                "last_error": failed_step.last_error,
            }
        if user_message:
            context["user_message"] = user_message
        return context

    async def _trigger_replan(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        plan: PlanRow,
        steps: list[PlanStepRow],
        failed_step: PlanStepRow | None,
        reason: str,
        user_message: str | None = None,
    ) -> ExecuteResult:
        if failed_step is not None:
            failed_step.status = "FAILED"
            failed_step.last_error = reason
            failed_step.completed_at = datetime.utcnow()
            self._log_step_status_change(
                session=session,
                plan=plan,
                step=failed_step,
                tool=None,
                status=failed_step.status,
            )

        if not plan.invalidated_at:
            plan.invalidated_at = datetime.utcnow()
            plan.invalidated_reason = reason

        session.replan_count += 1
        metrics.inc("replan_total")
        metrics.inc("replan_rate")
        session.plan_version = (session.plan_version or 0) + 1
        session.replan_context = self._build_replan_context(
            session=session,
            steps=steps,
            failed_step=failed_step,
            reason=reason,
            user_message=user_message,
        )
        session.pending_user_message = None

        if reason.startswith("predicate_") and session.replan_count > max(0, int(self._settings.intent_repair_attempts)):
            session.status = "BLOCKED"
            session.error = f"Predicate repair attempts exceeded ({reason})"
            session.version += 1
            await db.commit()
            await self._push_dlq(
                db,
                session_id=session.session_id,
                step_id=failed_step.step_id if failed_step else None,
                failure_type="predicate_repair_limit_reached",
                reason=reason,
                payload=session.replan_context or {},
            )
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

        if session.replan_count >= self._settings.max_replans:
            session.status = "BLOCKED"
            session.error = f"Session exceeded MAX_REPLANS ({reason})"
            session.version += 1
            await db.commit()
            await self._push_dlq(
                db,
                session_id=session.session_id,
                step_id=failed_step.step_id if failed_step else None,
                failure_type="replan_limit_reached",
                reason=reason,
                payload=session.replan_context or {},
            )
            return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

        session.status = "PLANNING"
        session.error = reason
        session.version += 1
        await db.commit()
        log_event(
            "session_replan_triggered",
            level="WARNING",
            session_id=session.session_id,
            plan_id=plan.plan_id,
            reason=reason,
            replan_count=session.replan_count,
            failed_step_id=failed_step.step_id if failed_step else None,
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    async def _fail_hard(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        step: PlanStepRow,
        reason: str,
        failure_type: str,
        payload: dict[str, Any],
    ) -> ExecuteResult:
        step.status = "FAILED"
        step.last_error = reason
        step.completed_at = datetime.utcnow()
        self._log_step_status_change(session=session, plan=None, step=step, tool=None, status=step.status)
        session.status = "FAILED"
        session.error = reason
        session.version += 1
        await db.commit()
        metrics.inc("session_failed_total", labels={"reason": failure_type})
        metrics.observe("steps_per_session", float(session.step_count))
        log_event(
            "session_failed",
            level="ERROR",
            session_id=session.session_id,
            step_id=step.step_id,
            tool=step.tool_name,
            failure_type=failure_type,
            reason=reason,
        )
        await self._push_dlq(
            db,
            session_id=session.session_id,
            step_id=step.step_id,
            failure_type=failure_type,
            reason=reason,
            payload=payload,
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    async def _check_limits_and_fail_if_needed(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
    ) -> ExecuteResult | None:
        duration_s = 0.0
        if session.session_started_at:
            duration_s = (datetime.utcnow() - session.session_started_at).total_seconds()
        limit_reason: str | None = None
        if session.step_count >= self._settings.max_session_steps:
            limit_reason = "MAX_SESSION_STEPS"
        elif session.replan_count >= self._settings.max_replans:
            limit_reason = "MAX_REPLANS"
        elif session.llm_call_count >= self._settings.max_llm_calls:
            limit_reason = "MAX_LLM_CALLS"
        elif duration_s >= self._settings.max_session_duration_s:
            limit_reason = "MAX_SESSION_DURATION_S"

        if not limit_reason:
            return None

        metrics.inc("sessions_rate_limited_total", labels={"limit_type": limit_reason})
        metrics.inc("limit_type_distribution", labels={"limit_type": limit_reason})
        log_event(
            "session_rate_limit_hit",
            level="WARNING",
            session_id=session.session_id,
            limit_type=limit_reason,
            step_count=session.step_count,
            replan_count=session.replan_count,
            llm_call_count=session.llm_call_count,
            duration_s=duration_s,
        )
        session.status = "FAILED"
        session.error = f"Session limit exceeded: {limit_reason}"
        session.version += 1
        await db.commit()
        metrics.inc("session_failed_total", labels={"reason": "rate_limit"})
        metrics.observe("steps_per_session", float(session.step_count))
        await self._push_dlq(
            db,
            session_id=session.session_id,
            step_id=None,
            failure_type="rate_limit_exceeded",
            reason=limit_reason,
            payload={
                "step_count": session.step_count,
                "replan_count": session.replan_count,
                "llm_call_count": session.llm_call_count,
                "duration_s": duration_s,
            },
        )
        return ExecuteResult(status=session.status, current_step_index=session.current_step_index)

    async def execute_until_blocked(
        self,
        db: AsyncSession,
        *,
        session: SessionRow,
        tools_by_name: dict[str, ToolInfo],
    ) -> ExecuteResult:
        if await is_graph_native_session(db, session):
            raise RuntimeError(
                "ExecutionEngine.execute_until_blocked is legacy compatibility code "
                "and is disabled for graph-native sessions."
            )
        result = await execution_runtime.execute_until_blocked(
            self,
            db,
            session=session,
            tools_by_name=tools_by_name,
        )
        try:
            await self._memory_manager.save_checkpoint(
                db,
                session_id=session.session_id,
                thread_id=session.session_id,
                state=self._checkpoint_state(session),
            )
        except Exception as exc:
            log_event(
                "checkpoint_save_failed",
                level="WARNING",
                session_id=session.session_id,
                error=str(exc),
            )
        return result



