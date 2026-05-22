"""LangGraph nodes: tool HTTP execution, write staging, relevance filter, bundle dry-run, and commit."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

import httpx

from ...config import Settings
from ...llm.models import build_planner_chat_model
from ...schemas import ToolInfo
from ..approval_summary import _infer_bulk_job_priority_mutation
from ..http_tool_client import compute_planner_write_idempotency_key, execute_tool_http, stable_json
from ..planner_graph_helpers import _message_content_text
from .planner_loop import planner_tool_output_tail
from ..state import AgentState, user_query_text


_REF_TOKEN_RE = re.compile(r"^\$ref:[A-Za-z0-9_\-]+$")


def _scalar_from_tool_result_body(body: Any) -> str | None:
    """Pick a single id-like string from a typical Go JSON tool response."""
    if body is None:
        return None
    if isinstance(body, str) and body.strip():
        return body.strip()
    if not isinstance(body, dict):
        return None
    for key in (
        "job_id",
        "id",
        "product_id",
        "machine_id",
        "material_id",
        "proposal_id",
        "slot_id",
        "step_id",
    ):
        v = body.get(key)
        if v is not None and isinstance(v, (str, int, float)):
            s = str(v).strip()
            if s:
                return s
    data = body.get("data")
    if isinstance(data, dict):
        inner = _scalar_from_tool_result_body(data)
        if inner:
            return inner
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            inner = _scalar_from_tool_result_body(first)
            if inner:
                return inner
    return None


def _scalar_from_tool_output_row(row: dict[str, Any]) -> str | None:
    res = row.get("result")
    if isinstance(res, dict):
        return _scalar_from_tool_result_body(res)
    return None


def _deep_resolve_ref_args(obj: Any, registry: dict[str, Any]) -> Any:
    if isinstance(obj, str) and obj.startswith("$ref:") and obj in registry:
        return registry[obj]
    if isinstance(obj, dict):
        return {k: _deep_resolve_ref_args(v, registry) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_resolve_ref_args(v, registry) for v in obj]
    return obj


def _batch_contains_ref_placeholders(raw_calls: list[Any]) -> bool:
    found: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, str) and _REF_TOKEN_RE.match(o):
            found.add(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for tc in raw_calls:
        if isinstance(tc, dict):
            walk(tc.get("args"))
    return bool(found)


def _collect_ref_tokens(obj: Any, out: set[str]) -> None:
    if isinstance(obj, str) and _REF_TOKEN_RE.match(obj):
        out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_ref_tokens(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_ref_tokens(v, out)


def _is_write_tool(tool: ToolInfo | None) -> bool:
    if tool is None:
        return True
    return not tool.is_read_only


def _priority_write_evidence(state: AgentState, *, tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    if "jobs" not in str(tool_name).lower():
        return None
    target = str(args.get("priority") or "").strip().lower()
    if not target:
        return None
    cur = state.get("current_intent")
    intent_text = ""
    if isinstance(cur, dict):
        intent_text = str(cur.get("description") or "").strip()
    if not intent_text:
        intent_text = user_query_text(state)
    mutation = _infer_bulk_job_priority_mutation(intent_text)
    if not isinstance(mutation, dict) or mutation.get("action") != "update_priority":
        return None
    source = str(mutation.get("source_priority") or "").strip().lower()
    expected_target = str(mutation.get("target_priority") or "").strip().lower()
    if not source or expected_target != target:
        return None
    return {
        "previous_priority": source,
        "new_priority": target,
        "source_state_basis": str(args.get("source_state_basis") or "original").strip().lower(),
    }


def _bulk_item_count(body: Any) -> int:
    if isinstance(body, list):
        return len(body)
    if not isinstance(body, dict):
        return 0
    for key in ("data", "items", "results"):
        v = body.get(key)
        if isinstance(v, list):
            return len(v)
    return 0


def _deterministic_useful(
    *,
    tool: ToolInfo | None,
    http_status: int | None,
    body: Any,
    infrastructure_error: bool,
) -> tuple[bool, str]:
    if infrastructure_error or (http_status is not None and http_status >= 500):
        return False, "infrastructure_error"
    if http_status == 404:
        return False, "not_found"
    # Successful read-only GETs must win before empty-body checks: several diagnostic/report
    # endpoints return `{}` or `{success:true}` with no list payload; treating that as
    # "empty" caused relevance_filter to loop planner→tool until LangGraph recursion_limit.
    if (
        tool
        and tool.method == "GET"
        and tool.is_read_only
        and http_status is not None
        and 200 <= http_status < 300
    ):
        return True, "direct_lookup_pass_through"
    if body == [] or body == {}:
        return False, "empty_body"
    if isinstance(body, dict):
        if body.get("not_found"):
            return False, "soft_not_found"
        for key in ("data", "items", "results", "value"):
            v = body.get(key)
            if v == []:
                return False, "empty_list"
    n = _bulk_item_count(body)
    if n > 100:
        return True, f"bulk_data_ranked_cap(n={n})"
    return True, "default_pass_through"


async def _semantic_useful(settings: Settings, *, tool_name: str, user_query: str, body: dict[str, Any]) -> tuple[bool, str]:
    if not (settings.planner_openai_base_url or settings.openai_api_key):
        return False, "semantic_filter_required_but_llm_unconfigured"
    model = build_planner_chat_model(settings, json_mode=True)
    prompt = (
        "You judge whether tool output is useful for the user's question. Reply JSON only: "
        '{"useful":true|false,"reason":"short"}\n'
        f"User: {user_query}\nTool: {tool_name}\nOutput JSON: {stable_json(body)[:8000]}\n"
    )
    try:
        msg = await model.ainvoke(prompt)
        text = _message_content_text(msg)
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("useful"), bool):
            return data["useful"], str(data.get("reason") or "llm")
    except Exception as exc:
        return False, f"semantic_filter_error:{exc}"
    return False, "semantic_filter_unparseable"


def make_tool_execution_node(settings: Settings):
    async def tool_execution_node(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending_decision")
        if not isinstance(pending, dict):
            return {"next_route": "continue_planner"}
        raw_calls = pending.get("tool_calls") or []
        if not isinstance(raw_calls, list) or not raw_calls:
            return {"pending_decision": None, "next_route": "continue_planner"}

        scoped = state.get("scoped_tools") or []
        tools_by_name = {t.name: t for t in scoped if getattr(t, "name", None)}
        session_id = str(state.get("session_id") or "session-local")
        intent_id = str(pending.get("intent_id") or "unknown")
        decision_id = str(pending.get("decision_id") or "decision-local")
        wg = int(state.get("write_generation") or 0)

        outs: list[dict[str, Any]] = []
        done: list[dict[str, Any]] = []
        staged: list[dict[str, Any]] = []
        audit: list[dict[str, Any]] = []
        ri = dict(state.get("retrieved_info") or {})
        fatal: str | None = None
        new_wg = wg

        tail = planner_tool_output_tail(state)
        tail_len = len(tail)
        ref_registry: dict[str, Any] = {}
        for j, row in enumerate(tail):
            if isinstance(row, dict):
                slot_val = _scalar_from_tool_output_row(row)
                if slot_val is not None:
                    ref_registry[f"$ref:{j}"] = slot_val
        batch_read_idx = 0

        async def run_one(tc: dict[str, Any]) -> None:
            nonlocal fatal, new_wg, batch_read_idx
            if not isinstance(tc, dict):
                return
            name = tc.get("tool_name")
            raw_args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            args = _deep_resolve_ref_args(dict(raw_args), ref_registry)
            tcid = str(tc.get("tool_call_id") or "")
            tool = tools_by_name.get(name) if isinstance(name, str) else None

            if fatal:
                return

            if tool is None:
                outs.append(
                    {
                        "tool_name": name,
                        "tool_call_id": tcid,
                        "args": args,
                        "result": {"error": "unknown_tool"},
                        "http_status": None,
                        "useful": False,
                    }
                )
                done.append({"phase": "tool_execution", "tool_name": name, "status": "unknown_tool"})
                return

            if _is_write_tool(tool):
                new_wg += 1
                out_ref = tc.get("output_ref") if isinstance(tc.get("output_ref"), str) else None
                if not out_ref or not out_ref.startswith("$ref:"):
                    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(name))[:40]
                    out_ref = f"$ref:{safe}_{tcid[-6:]}"
                idem = compute_planner_write_idempotency_key(
                    session_id=session_id,
                    intent_id=intent_id,
                    action_id=tcid or out_ref,
                    tool_name=str(name),
                    args=args,
                    write_generation=new_wg,
                )
                audit.append(
                    {
                        "phase": "staging",
                        "intent_id": intent_id,
                        "decision_id": decision_id,
                        "tool_name": str(name),
                        "idempotency_key": idem,
                        "output_ref": out_ref,
                    }
                )
                staged_write = {
                    "intent_id": intent_id,
                    "decision_id": decision_id,
                    "tool_call_id": tcid,
                    "tool_name": str(name),
                    "args": dict(args),
                    "output_ref": out_ref,
                    "write_generation": new_wg,
                    "idempotency_key": idem,
                    "status": "staged",
                }
                evidence = _priority_write_evidence(state, tool_name=str(name), args=dict(args))
                if evidence:
                    staged_write["evidence"] = evidence
                staged.append(staged_write)
                done.append(
                    {
                        "phase": "tool_execution",
                        "tool_name": name,
                        "args": args,
                        "status": "staged",
                        "output_ref": out_ref,
                    }
                )
                return

            idem = compute_planner_write_idempotency_key(
                session_id=session_id,
                intent_id=intent_id,
                action_id=tcid or str(name),
                tool_name=str(name),
                args=args,
                write_generation=wg,
            )
            env = await execute_tool_http(settings, tool, args, idempotency_key=idem)
            if env.get("infrastructure_error"):
                fatal = f"FATAL_SYSTEM_ERROR:{name}:{env.get('body')}"
                outs.append(
                    {
                        "tool_name": name,
                        "tool_call_id": tcid,
                        "args": args,
                        "result": env.get("body"),
                        "http_status": env.get("http_status"),
                        "useful": False,
                        "infrastructure_error": True,
                    }
                )
                done.append({"phase": "tool_execution", "tool_name": name, "status": "infrastructure_error"})
                return

            body = env.get("body") if isinstance(env.get("body"), dict) else {"value": env.get("body")}
            outs.append(
                {
                    "tool_name": name,
                    "tool_call_id": tcid,
                    "args": args,
                    "result": body,
                    "http_status": env.get("http_status"),
                    "latency_ms": env.get("latency_ms"),
                }
            )
            done.append(
                {
                    "phase": "tool_execution",
                    "tool_name": name,
                    "args": args,
                    "status": "http_ok" if env.get("ok") else "http_client_error",
                    "http_status": env.get("http_status"),
                }
            )
            key = f"read:{name}:{tcid}"
            ri[key] = {"summary": f"status={env.get('http_status')}", "tool_call_id": tcid}

            slot_val = _scalar_from_tool_result_body(body)
            if slot_val is not None:
                ref_registry[f"$ref:{tail_len + batch_read_idx}"] = slot_val
            batch_read_idx += 1

        all_read = True
        for tc in raw_calls:
            if not isinstance(tc, dict):
                continue
            tn = tc.get("tool_name")
            tinfo = tools_by_name.get(str(tn)) if isinstance(tn, str) else None
            if tinfo is None or not tinfo.is_read_only:
                all_read = False
                break

        refs_in_batch = _batch_contains_ref_placeholders(raw_calls)
        if (
            pending.get("kind") == "parallel_read_tools"
            and settings.enable_parallel_execution
            and all_read
            and not refs_in_batch
        ):
            await asyncio.gather(*[run_one(tc) for tc in raw_calls if isinstance(tc, dict)])
        else:
            for tc in raw_calls:
                await run_one(tc)

        out_state: dict[str, Any] = {
            "completed_actions": done,
            "staged_writes": staged,
            "idempotency_audit": audit,
            "retrieved_info": ri,
            "write_generation": new_wg,
            "pending_decision": None,
            "pending_relevance_batch": outs,
            "next_route": "fatal_end" if fatal else "relevance_filter",
            "status": "planning",
        }
        if fatal:
            out_state["fatal_system_error"] = fatal
            out_state["errors"] = [fatal]
        return out_state

    return tool_execution_node


def make_relevance_filter_node(settings: Settings):
    async def relevance_filter_node(state: AgentState) -> dict[str, Any]:
        if state.get("fatal_system_error"):
            return {"next_route": "fatal_end"}
        batch = state.get("pending_relevance_batch") or []
        if not batch:
            return {"pending_relevance_batch": None, "next_route": "continue_planner"}
        scoped = state.get("scoped_tools") or []
        tools_by_name = {t.name: t for t in scoped if getattr(t, "name", None)}
        uq = user_query_text(state)
        enriched: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []

        for row in batch:
            if not isinstance(row, dict):
                continue
            name = row.get("tool_name")
            tool = tools_by_name.get(str(name)) if isinstance(name, str) else None
            if row.get("infrastructure_error"):
                enriched.append({**row, "useful": False, "relevance_reason": "infrastructure_bypass"})
                actions.append({"phase": "relevance_filter", "tool_name": name, "useful": False, "reason": "infrastructure"})
                continue
            http_status = row.get("http_status")
            body = row.get("result") if isinstance(row.get("result"), dict) else {}
            is_staged = isinstance(body, dict) and bool(body.get("staged"))
            infra = bool(row.get("infrastructure_error"))
            useful, reason = _deterministic_useful(
                tool=tool, http_status=http_status, body=body, infrastructure_error=infra
            )
            if tool and tool.requires_semantic_filter and useful and not is_staged:
                useful, reason = await _semantic_useful(settings, tool_name=str(name), user_query=uq, body=body)
            if _bulk_item_count(body) > 50 and useful and not (tool and tool.requires_semantic_filter):
                reason = f"{reason};bulk_trim"
            enriched.append({**row, "useful": useful, "relevance_reason": reason})
            actions.append({"phase": "relevance_filter", "tool_name": name, "useful": useful, "reason": reason})

        ri = dict(state.get("retrieved_info") or {})
        ri["relevance_trace"] = (ri.get("relevance_trace") or []) + actions

        return {
            "tool_outputs": enriched,
            "completed_actions": actions,
            "retrieved_info": ri,
            "pending_relevance_batch": None,
            "next_route": "continue_planner",
            "status": "planning",
        }

    return relevance_filter_node


def fatal_end_node(state: AgentState) -> dict[str, Any]:
    return {"status": "failed", "next_route": "fatal_end"}


async def bundle_dry_run_node(state: AgentState, *, settings: Settings) -> dict[str, Any]:
    staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
    if not staged:
        return {"bundle_dry_run_result": {"skipped": True, "reason": "no_staged_writes"}}
    url = f"{settings.go_api_base_url}{settings.agent_transaction_bundle_dry_run_path}"
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            resp = await client.post(url, json={"staged_writes": staged})
        body: Any = None
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw": resp.text}
        ok = resp.status_code < 400
        return {
            "bundle_dry_run_result": {
                "http_status": resp.status_code,
                "ok": ok,
                "body": body,
            }
        }
    except Exception as exc:
        return {
            "bundle_dry_run_result": {
                "skipped": True,
                "reason": "request_failed",
                "error": str(exc),
            }
        }


def make_bundle_dry_run_node(settings: Settings):
    async def node(state: AgentState) -> dict[str, Any]:
        return await bundle_dry_run_node(state, settings=settings)

    return node


async def commit_node_impl(state: AgentState, *, settings: Settings) -> dict[str, Any]:
    staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
    if not staged:
        return {"last_commit_result": {"skipped": True, "reason": "no_staged_writes"}}
    dry = state.get("bundle_dry_run_result")
    if not isinstance(dry, dict) or dry.get("ok") is not True:
        return {
            "last_commit_result": {
                "ok": False,
                "http_status": 428,
                "error": "commit_precondition_failed:bundle_dry_run_required",
            }
        }
    validations = state.get("validation_results") or []
    if not any(isinstance(v, dict) and v.get("ok") is True for v in validations):
        return {
            "last_commit_result": {
                "ok": False,
                "http_status": 428,
                "error": "commit_precondition_failed:final_validation_required",
            }
        }
    approvals = state.get("approval_requests") or []
    if not any(isinstance(a, dict) and a.get("status") == "approved" for a in approvals):
        return {
            "last_commit_result": {
                "ok": False,
                "http_status": 428,
                "error": "commit_precondition_failed:approval_required",
            }
        }
    keys = [x.get("idempotency_key") for x in staged if isinstance(x.get("idempotency_key"), str)]
    bundle_key_source = "|".join(keys) if keys else stable_json(staged)
    bundle_key = hashlib.sha256(f"bundle|{bundle_key_source}".encode("utf-8")).hexdigest()
    headers = {
        "Idempotency-Key": bundle_key,
        "X-Bundle-Idempotency-Key": bundle_key,
    }
    url = f"{settings.go_api_base_url}{settings.agent_transaction_commit_path}"
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            resp = await client.post(
                url,
                json={"staged_writes": staged, "bundle_idempotency_key": bundle_key},
                headers=headers,
            )
        body: Any = None
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw": resp.text}
        return {
            "last_commit_result": {"http_status": resp.status_code, "ok": resp.status_code < 400, "body": body},
            "completed_actions": [
                {
                    "phase": "commit",
                    "http_status": resp.status_code,
                    "bundle_idempotency_key": bundle_key,
                    "idempotency_keys": keys[:5],
                    "count": len(staged),
                }
            ],
        }
    except Exception as exc:
        return {
            "last_commit_result": {"ok": False, "error": str(exc), "infrastructure": True},
            "errors": [f"FATAL_SYSTEM_ERROR:commit:{exc}"],
            "fatal_system_error": f"FATAL_SYSTEM_ERROR:commit:{exc}",
        }


def make_commit_node(settings: Settings):
    async def node(state: AgentState) -> dict[str, Any]:
        return await commit_node_impl(state, settings=settings)

    return node


def route_after_tool(state: AgentState) -> str:
    if state.get("fatal_system_error"):
        return "fatal_end"
    return "relevance_filter"


def route_after_relevance(state: AgentState) -> str:
    if state.get("fatal_system_error"):
        return "fatal_end"
    # Writes are staged without HTTP rows in `pending_relevance_batch`, so the relevance
    # node sees an empty batch. Usually we go straight to synthesis when we already have
    # staged work; the exception is another complete write intent that can be safely
    # appended to the same approval bundle.
    staged = [x for x in (state.get("staged_writes") or []) if isinstance(x, dict)]
    if staged:
        from .planner_loop import _next_bundleable_write_intent_index

        if _next_bundleable_write_intent_index(state) is not None:
            return "continue_planner"
        return "synthesize_plan"
    return "continue_planner"


def route_after_validate(state: AgentState) -> str:
    if state.get("fatal_system_error"):
        return "fatal_end"
    route = state.get("next_route")
    if route == "continue_planner":
        return "continue_planner"
    if route == "fatal_end":
        return "fatal_end"
    if route == "commit":
        return "commit"
    if route == "end":
        return "end"
    return "bundle_dry_run"


def route_after_bundle(state: AgentState) -> str:
    if state.get("fatal_system_error"):
        return "fatal_end"
    return "final_validator"


def route_after_commit(state: AgentState) -> str:
    if state.get("fatal_system_error"):
        return "fatal_end"
    commit = state.get("last_commit_result")
    if isinstance(commit, dict):
        return "final_validator"
    return "end"
