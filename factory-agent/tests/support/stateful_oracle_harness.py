from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
ORACLE_DIR = REPO_ROOT / "tests" / "e2e" / "scenarios" / "stateful_oracles"


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _copy(value: Any) -> Any:
    return deepcopy(value)


def _row_id(row: dict[str, Any]) -> str:
    value = row.get("id") or row.get("job_id") or row.get("machine_id")
    if value in (None, ""):
        raise ValueError(f"Seed row is missing a stable id: {row!r}")
    return str(value)


def _normalise_job(row: dict[str, Any]) -> dict[str, Any]:
    out = _copy(row)
    job_id = _row_id(out)
    out["id"] = job_id
    out["job_id"] = job_id
    return out


def _normalise_machine(row: dict[str, Any]) -> dict[str, Any]:
    out = _copy(row)
    machine_id = _row_id(out)
    out["id"] = machine_id
    out["machine_id"] = machine_id
    return out


def load_oracle(oracle_id: str) -> dict[str, Any]:
    wanted = oracle_id.lower()
    for path in sorted(ORACLE_DIR.glob("*.json")):
        if path.stem.startswith(wanted):
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
    raise FileNotFoundError(f"No stateful oracle JSON found for {oracle_id!r} in {ORACLE_DIR}")


@dataclass(frozen=True)
class ApprovalResult:
    approval_id: str
    ok: bool
    http_status: int
    status: str
    per_row_results: list[dict[str, Any]] = field(default_factory=list)
    replay: bool = False
    error: str | None = None

    def to_commit_update(self) -> dict[str, Any]:
        body = {
            "approval_id": self.approval_id,
            "status": self.status,
            "per_row_results": _copy(self.per_row_results),
            "replay": self.replay,
        }
        if self.error:
            body["error"] = self.error
        return {
            "last_commit_result": {
                "ok": self.ok,
                "http_status": self.http_status,
                "body": body,
                **({"error": self.error} if self.error else {}),
            },
            "completed_actions": [
                {
                    "phase": "commit",
                    "approval_id": self.approval_id,
                    "status": self.status,
                    "ok": self.ok,
                    "row_count": len(self.per_row_results),
                }
            ],
        }


class StatefulOracleHarness:
    """Small mutable fake backend for stateful oracle tests.

    The harness deliberately models only the contract surface needed by Phase 2:
    job/machine/RAG seeds, original-vs-current reads, approval lifecycle,
    idempotent commits, audit evidence, and timeline/SSE-style events.
    """

    def __init__(
        self,
        *,
        oracle: dict[str, Any] | None = None,
        session_id: str = "stateful-oracle-session",
    ) -> None:
        self.oracle = oracle or {}
        self.session_id = session_id
        self.jobs: dict[str, dict[str, Any]] = {}
        self.original_jobs: dict[str, dict[str, Any]] = {}
        self.job_order: list[str] = []
        self.machines: dict[str, dict[str, Any]] = {}
        self.original_machines: dict[str, dict[str, Any]] = {}
        self.rag_entities: dict[str, dict[str, Any]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.audit_rows: list[dict[str, Any]] = []
        self.timeline: list[dict[str, Any]] = []
        self.sse_events: list[dict[str, Any]] = []
        self.read_requests: list[dict[str, Any]] = []
        self.dry_runs: list[dict[str, Any]] = []
        self.commit_count_by_approval: dict[str, int] = {}
        self.session_phase = "INIT"
        self.pending_approval_id: str | None = None
        self.sequence_number = 0
        self._approval_counter = 0
        self._terminal_recorded = False

        initial = self.oracle.get("initial_state") if isinstance(self.oracle, dict) else {}
        if isinstance(initial, dict):
            self.seed_jobs(initial.get("jobs") or [])
            self.seed_machines(initial.get("machines") or [])
            self.seed_rag_entities(initial.get("rag_entities") or initial.get("rag") or [])

    @classmethod
    def from_oracle_id(
        cls,
        oracle_id: str,
        *,
        session_id: str | None = None,
    ) -> "StatefulOracleHarness":
        oracle = load_oracle(oracle_id)
        return cls(oracle=oracle, session_id=session_id or oracle_id.lower())

    def seed_jobs(self, rows: list[dict[str, Any]]) -> None:
        self.jobs.clear()
        self.original_jobs.clear()
        self.job_order.clear()
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalised = _normalise_job(row)
            job_id = normalised["id"]
            self.jobs[job_id] = normalised
            self.original_jobs[job_id] = _copy(normalised)
            self.job_order.append(job_id)

    def seed_machines(self, rows: list[dict[str, Any]]) -> None:
        self.machines.clear()
        self.original_machines.clear()
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalised = _normalise_machine(row)
            machine_id = normalised["id"]
            self.machines[machine_id] = normalised
            self.original_machines[machine_id] = _copy(normalised)

    def seed_rag_entities(self, rows: list[dict[str, Any]]) -> None:
        self.rag_entities.clear()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            entity_id = str(row.get("id") or row.get("doc_id") or f"rag-{index}")
            self.rag_entities[entity_id] = _copy({**row, "id": entity_id})

    def start_operation(
        self,
        *,
        intent_count: int = 1,
        turn_id: str | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> None:
        self.session_phase = "PLANNING"
        payload: dict[str, Any] = dict(event_payload or {})
        if turn_id:
            payload["turn_id"] = turn_id
        self.record_event("operation_started", **payload)
        if intent_count > 1:
            self.record_event("intent_split", intent_count=intent_count)

    def record_event(self, event: str, **payload: Any) -> dict[str, Any]:
        self.sequence_number += 1
        row = {
            "sequence_number": self.sequence_number,
            "sequence": self.sequence_number,
            "session_id": self.session_id,
            "event": event,
            **payload,
        }
        self.timeline.append(row)
        self.sse_events.append(
            {
                "id": str(self.sequence_number),
                "event": event,
                "data": _copy(row),
            }
        )
        return row

    def select_jobs(
        self,
        filters: dict[str, Any] | None = None,
        *,
        state_basis: str = "current",
    ) -> list[dict[str, Any]]:
        filters = filters or {}
        source = self.original_jobs if state_basis == "original" else self.jobs
        rows: list[dict[str, Any]] = []
        for job_id in self.job_order:
            row = source.get(job_id)
            if not row:
                continue
            if self._matches_filters(row, filters):
                rows.append(_copy(row))
        return rows

    def select_job_ids(
        self,
        filters: dict[str, Any] | None = None,
        *,
        state_basis: str = "current",
    ) -> list[str]:
        return [str(row["id"]) for row in self.select_jobs(filters, state_basis=state_basis)]

    def read_jobs(
        self,
        args: dict[str, Any] | None = None,
        *,
        state_basis: str = "current",
    ) -> dict[str, Any]:
        args = args or {}
        requested_basis = str(args.get("state_basis") or state_basis or "current")
        filters = {k: v for k, v in args.items() if k not in {"fields", "limit", "state_basis"}}
        rows = self.select_jobs(filters, state_basis=requested_basis)
        limit = args.get("limit")
        if isinstance(limit, int) and limit >= 0:
            rows = rows[:limit]
        fields = str(args.get("fields") or "").strip()
        if fields:
            wanted = [part.strip() for part in fields.split(",") if part.strip()]
            projected: list[dict[str, Any]] = []
            for row in rows:
                out = {key: row[key] for key in wanted if key in row}
                if "job_id" in wanted and "job_id" not in out:
                    out["job_id"] = row["id"]
                if "id" in wanted and "id" not in out:
                    out["id"] = row["id"]
                projected.append(out)
            rows = projected
        self.read_requests.append(
            {
                "tool_name": "get__jobs",
                "args": _copy(args),
                "state_basis": requested_basis,
                "row_ids": [str(row.get("id") or row.get("job_id")) for row in rows],
            }
        )
        self.record_event(
            "tool_read_completed",
            tool_name="get__jobs",
            state_basis=requested_basis,
            row_count=len(rows),
            args=_copy(args),
        )
        return {"data": rows}

    def read_machines(
        self,
        args: dict[str, Any] | None = None,
        *,
        state_basis: str = "current",
    ) -> dict[str, Any]:
        args = args or {}
        source = self.original_machines if state_basis == "original" else self.machines
        filters = {k: v for k, v in args.items() if k not in {"fields", "limit", "state_basis"}}
        rows = [_copy(row) for row in source.values() if self._matches_filters(row, filters)]
        self.read_requests.append(
            {
                "tool_name": "get__machines",
                "args": _copy(args),
                "state_basis": state_basis,
                "row_ids": [str(row.get("id") or row.get("machine_id")) for row in rows],
            }
        )
        self.record_event("tool_read_completed", tool_name="get__machines", row_count=len(rows), args=_copy(args))
        return {"data": rows}

    def rag_search(self, query: str) -> dict[str, Any]:
        lowered = query.lower()
        sources = [
            _copy(row)
            for row in self.rag_entities.values()
            if lowered in _stable_json(row).lower()
        ]
        self.record_event("rag_search_completed", query=query, source_count=len(sources))
        return {"answer": "Seeded fake RAG answer.", "sources": sources}

    async def execute_tool_http(
        self,
        settings: Any,
        tool: Any,
        args: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del settings, idempotency_key
        tool_name = str(getattr(tool, "name", "") or "")
        self.record_event("tool_read_started", tool_name=tool_name, args=_copy(args))
        if tool_name == "get__jobs":
            body = self.read_jobs(args)
        elif tool_name in {"get__machines", "get__machines_{id}"}:
            body = self.read_machines(args)
        else:
            body = {"data": []}
        return {
            "ok": True,
            "http_status": 200,
            "body": body,
            "latency_ms": 1,
            "infrastructure_error": False,
        }

    def dry_run_oracle_intent(
        self,
        intent_index: int,
        *,
        request_approval: bool = True,
    ) -> dict[str, Any]:
        intents = self.oracle.get("expected_intents") or []
        approvals = self.oracle.get("expected_approvals") or []
        intent = intents[intent_index]
        approval = approvals[intent_index] if intent_index < len(approvals) else {}
        filter_args = dict(intent.get("filter") or {})
        state_basis = str(filter_args.pop("state_basis", "current"))
        source_priority = filter_args.get("priority")
        target_priority = (intent.get("new_values") or {}).get("priority")
        if not source_priority or not target_priority:
            raise ValueError(f"Oracle intent {intent.get('intent_id')} is not a priority update intent")
        staged = self.build_priority_update_writes(
            source_priority=str(source_priority),
            target_priority=str(target_priority),
            intent_id=str(intent.get("intent_id") or f"intent-{intent_index}"),
            state_basis=state_basis,
        )
        dry = self.dry_run(staged)
        if request_approval:
            self.request_approval(
                approval_id=str(approval.get("approval_id") or self.next_approval_id()),
                intent_id=str(intent.get("intent_id") or ""),
                staged_writes=staged,
                summary=f"{len(staged)} row(s) pending approval.",
            )
        return dry

    def build_priority_update_writes(
        self,
        *,
        source_priority: str,
        target_priority: str,
        intent_id: str,
        state_basis: str = "current",
    ) -> list[dict[str, Any]]:
        rows = self.select_jobs({"priority": source_priority}, state_basis=state_basis)
        writes: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            job_id = str(row["id"])
            args = {"id": job_id, "priority": target_priority}
            writes.append(
                {
                    "intent_id": intent_id,
                    "decision_id": f"{intent_id}-decision",
                    "tool_call_id": f"{intent_id}-write-{index}",
                    "tool_name": "put__jobs_{id}",
                    "args": args,
                    "output_ref": f"$ref:{job_id}",
                    "idempotency_key": self.idempotency_key(intent_id, "put__jobs_{id}", args),
                    "status": "staged",
                }
            )
        return writes

    def dry_run(self, staged_writes: list[dict[str, Any]]) -> dict[str, Any]:
        row_results = []
        for write in staged_writes:
            args = write.get("args") if isinstance(write.get("args"), dict) else {}
            job_id = str(args.get("id") or args.get("job_id") or "")
            row_results.append(
                {
                    "row_id": job_id,
                    "tool_name": write.get("tool_name"),
                    "would_commit": job_id in self.jobs or write.get("tool_name") == "post__jobs",
                }
            )
        dry = {
            "ok": True,
            "http_status": 200,
            "body": {
                "validated": True,
                "row_count": len(staged_writes),
                "row_results": row_results,
            },
            "staged_writes": _copy(staged_writes),
        }
        self.dry_runs.append(dry)
        self.record_event("dry_run_completed", row_count=len(staged_writes))
        return dry

    async def bundle_dry_run_node(self, state: dict[str, Any], *, settings: Any = None) -> dict[str, Any]:
        del settings
        staged = [row for row in state.get("staged_writes") or [] if isinstance(row, dict)]
        dry = self.dry_run(staged)
        approval_id = self.next_approval_id()
        intent_id = str((staged[0] if staged else {}).get("intent_id") or "")
        self.request_approval(
            approval_id=approval_id,
            intent_id=intent_id,
            staged_writes=staged,
            summary=f"{len(staged)} row(s) pending approval.",
        )
        return {"bundle_dry_run_result": {k: _copy(v) for k, v in dry.items() if k != "staged_writes"}}

    async def commit_node(self, state: dict[str, Any], *, settings: Any = None) -> dict[str, Any]:
        del settings
        approval_id = self.pending_approval_id or self._latest_pending_or_accepted_approval_id()
        if not approval_id:
            return {
                "last_commit_result": {
                    "ok": False,
                    "http_status": 428,
                    "error": "approval_required",
                }
            }
        key_source = state.get("staged_writes") or self.approvals[approval_id].get("staged_writes") or []
        result = self.approve(
            approval_id,
            idempotency_key=self.idempotency_key("commit", "bundle", key_source),
        )
        return result.to_commit_update()

    def next_approval_id(self) -> str:
        for approval in self.oracle.get("expected_approvals") or []:
            approval_id = str(approval.get("approval_id") or "")
            if approval_id and approval_id not in self.approvals:
                return approval_id
        self._approval_counter += 1
        return f"approval-{self._approval_counter}"

    def request_approval(
        self,
        *,
        approval_id: str,
        intent_id: str,
        staged_writes: list[dict[str, Any]],
        summary: str = "",
        expires_in_seconds: int | None = None,
    ) -> dict[str, Any]:
        if approval_id in self.approvals:
            approval = self.approvals[approval_id]
            if approval.get("status") == "pending":
                self.pending_approval_id = approval_id
            return approval
        row_ids = self._row_ids_from_staged(staged_writes)
        approval = {
            "approval_id": approval_id,
            "intent_id": intent_id,
            "status": "pending",
            "summary": summary,
            "staged_writes": _copy(staged_writes),
            "row_ids": row_ids,
            "requested_sequence_number": self.sequence_number + 1,
            "expires_in_seconds": expires_in_seconds,
            "idempotency_keys": set(),
            "commit_result": None,
        }
        self.approvals[approval_id] = approval
        self.pending_approval_id = approval_id
        self.session_phase = "WAITING_APPROVAL"
        self.record_event("approval_requested", approval_id=approval_id, intent_id=intent_id, row_count=len(row_ids))
        return approval

    def supersede_pending_approvals(self, *, reason: str, turn_id: str | None = None) -> list[str]:
        if turn_id:
            self.record_event("user_revision_received", turn_id=turn_id)
        invalidated: list[str] = []
        for approval_id, approval in list(self.approvals.items()):
            if approval.get("status") != "pending":
                continue
            approval["status"] = "superseded"
            approval["superseded_reason"] = reason
            invalidated.append(approval_id)
            self.record_event("approval_invalidated", approval_id=approval_id, reason=reason)
        if self.pending_approval_id in invalidated:
            self.pending_approval_id = None
        return invalidated

    def expire_approval(self, approval_id: str) -> ApprovalResult:
        approval = self.approvals[approval_id]
        if approval.get("status") == "expired":
            return ApprovalResult(approval_id, False, 409, "expired", error="expired_approval")
        if approval.get("status") != "pending":
            return ApprovalResult(approval_id, False, 409, "not_pending", error=str(approval.get("status")))
        approval["status"] = "expired"
        self.pending_approval_id = None
        self.session_phase = "EXPIRED"
        self.record_event("approval_expired", approval_id=approval_id)
        self.record_event("operation_expired", reason="approval_timeout")
        return ApprovalResult(approval_id, False, 409, "expired", error="expired_approval")

    def approve(
        self,
        approval_id: str,
        *,
        idempotency_key: str | None = None,
        source: str = "approve",
        auto_complete: bool | None = None,
    ) -> ApprovalResult:
        if approval_id not in self.approvals:
            self.record_event("stale_approval_rejected", approval_id=approval_id, source=source)
            return ApprovalResult(approval_id, False, 404, "missing", error="approval_not_found")

        approval = self.approvals[approval_id]
        status = str(approval.get("status") or "")
        if status == "superseded":
            self.record_event("stale_approval_rejected", approval_id=approval_id, source=source)
            return ApprovalResult(approval_id, False, 409, "superseded", error="stale_approval")
        if status == "expired":
            self.record_event("expired_approval_rejected", approval_id=approval_id, source=source)
            return ApprovalResult(approval_id, False, 409, "expired", error="expired_approval")
        if self.commit_count_by_approval.get(approval_id, 0) > 0:
            self.record_event("approval_replay_ignored", approval_id=approval_id, source=source)
            existing = approval.get("commit_result") or {}
            rows = existing.get("per_row_results") if isinstance(existing, dict) else []
            return ApprovalResult(approval_id, True, 200, "already_processed_noop", _copy(rows or []), replay=True)

        if status != "pending":
            self.record_event("stale_approval_rejected", approval_id=approval_id, source=source)
            return ApprovalResult(approval_id, False, 409, status or "not_pending", error="approval_not_pending")

        if idempotency_key:
            approval["idempotency_keys"].add(idempotency_key)
        approval["status"] = "accepted"
        self.pending_approval_id = None
        self.session_phase = "EXECUTING"
        self.record_event("approval_decided", approval_id=approval_id, decision="accepted")
        result = self._commit_approval(approval)
        if auto_complete is None:
            auto_complete = self._should_complete_after(approval_id)
        if auto_complete:
            terminal = "COMPLETED_WITH_ERRORS" if result.status == "partial_failure" else "COMPLETED"
            self.complete_operation(status=terminal)
        return result

    def complete_operation(self, *, status: str = "COMPLETED") -> None:
        if self._terminal_recorded:
            self.session_phase = status
            return
        self.session_phase = status
        self.pending_approval_id = None
        self.record_event("final_response_created")
        terminal_event = "operation_completed_with_errors" if status == "COMPLETED_WITH_ERRORS" else "operation_completed"
        self.record_event(terminal_event)
        self._terminal_recorded = True

    def idempotency_key(self, *parts: Any) -> str:
        return hashlib.sha256(_stable_json(parts).encode("utf-8")).hexdigest()

    def job_snapshot(self) -> list[dict[str, Any]]:
        return [_copy(self.jobs[job_id]) for job_id in self.job_order if job_id in self.jobs]

    def audit_rows_for(self, approval_id: str) -> list[dict[str, Any]]:
        return [row for row in self.audit_rows if row.get("approval_id") == approval_id]

    def _commit_approval(self, approval: dict[str, Any]) -> ApprovalResult:
        approval_id = str(approval["approval_id"])
        staged = [row for row in approval.get("staged_writes") or [] if isinstance(row, dict)]
        self.commit_count_by_approval[approval_id] = self.commit_count_by_approval.get(approval_id, 0) + 1
        self.record_event("commit_started", approval_id=approval_id)

        per_row: list[dict[str, Any]] = []
        for write in staged:
            tool_name = str(write.get("tool_name") or "")
            args = write.get("args") if isinstance(write.get("args"), dict) else {}
            if tool_name == "put__jobs_{id}":
                per_row.append(self._commit_job_update(args))
            elif tool_name == "delete__jobs_{id}":
                per_row.append(self._commit_job_delete(args))
            elif tool_name == "post__jobs":
                per_row.append(self._commit_job_create(args))
            else:
                per_row.append(
                    {
                        "row_id": str(args.get("id") or args.get("job_id") or tool_name),
                        "status": "failed",
                        "error": "unsupported_tool",
                    }
                )

        successes = [row for row in per_row if row.get("status") == "succeeded"]
        failures = [row for row in per_row if row.get("status") != "succeeded"]
        if successes:
            self._append_audit_row(approval_id, successes, status="success")
        if failures:
            self._append_audit_row(approval_id, failures, status="failed")

        if failures and successes:
            self.record_event(
                "commit_partial_failure",
                approval_id=approval_id,
                succeeded_count=len(successes),
                failed_count=len(failures),
            )
            self.record_event("audit_recorded", approval_id=approval_id, status="partial_failure")
            status = "partial_failure"
            ok = False
            http_status = 207
        elif failures:
            self.record_event("commit_failed", approval_id=approval_id, failed_count=len(failures))
            self.record_event("audit_recorded", approval_id=approval_id, status="failed")
            status = "failed"
            ok = False
            http_status = 422
        else:
            self.record_event("commit_completed", approval_id=approval_id)
            self.record_event("audit_recorded", approval_id=approval_id, status="success")
            status = "success"
            ok = True
            http_status = 200

        approval["commit_result"] = {
            "status": status,
            "per_row_results": _copy(per_row),
        }
        return ApprovalResult(approval_id, ok, http_status, status, _copy(per_row))

    def _commit_job_update(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = str(args.get("id") or args.get("job_id") or "")
        target_priority = args.get("priority")
        row = self.jobs.get(job_id)
        if row is None:
            return {
                "row_id": job_id,
                "status": "failed",
                "error": "not_found",
                "to": target_priority,
            }
        before_priority = row.get("priority")
        behavior = str(row.get("commit_behavior") or "success")
        if behavior == "conflict_on_commit":
            return {
                "row_id": job_id,
                "status": "failed",
                "error": "version_conflict",
                "from": before_priority,
                "to": target_priority,
            }
        row["priority"] = target_priority
        if "updated_version" in row:
            row["updated_version"] = int(row.get("updated_version") or 0) + 1
        return {
            "row_id": job_id,
            "status": "succeeded",
            "from": before_priority,
            "to": target_priority,
        }

    def _commit_job_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = str(args.get("id") or args.get("job_id") or "")
        row = self.jobs.get(job_id)
        if row is None:
            return {"row_id": job_id, "status": "failed", "error": "not_found"}
        before_priority = row.get("priority")
        del self.jobs[job_id]
        return {
            "row_id": job_id,
            "status": "succeeded",
            "action": "delete",
            "from": before_priority,
            "to": None,
        }

    def _commit_job_create(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = str(args.get("id") or args.get("job_id") or f"JOB-CREATED-{len(self.jobs) + 1:03d}")
        if job_id in self.jobs:
            return {"row_id": job_id, "status": "failed", "error": "already_exists"}
        row = _normalise_job({"id": job_id, **args})
        self.jobs[job_id] = row
        self.job_order.append(job_id)
        return {
            "row_id": job_id,
            "status": "succeeded",
            "action": "create",
            "from": None,
            "to": row.get("priority"),
        }

    def _append_audit_row(self, approval_id: str, rows: list[dict[str, Any]], *, status: str) -> None:
        row_ids = [str(row.get("row_id")) for row in rows]
        from_values = {row.get("from") for row in rows if "from" in row}
        to_values = {row.get("to") for row in rows if "to" in row}
        errors = {str(row.get("error")) for row in rows if row.get("error")}
        idempotency_keys = sorted(self.approvals.get(approval_id, {}).get("idempotency_keys") or [])
        audit = {
            "approval_id": approval_id,
            "action": "bulk_update_job_priority",
            "row_ids": row_ids,
            "from": from_values.pop() if len(from_values) == 1 else None,
            "to": to_values.pop() if len(to_values) == 1 else None,
            "status": status,
        }
        if len(idempotency_keys) == 1:
            audit["idempotency_key"] = idempotency_keys[0]
        if errors:
            audit["error"] = sorted(errors)[0]
        self.audit_rows.append(audit)

    def _row_ids_from_staged(self, staged_writes: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        for write in staged_writes:
            args = write.get("args") if isinstance(write.get("args"), dict) else {}
            value = args.get("id") or args.get("job_id")
            if value not in (None, ""):
                ids.append(str(value))
        return ids

    def _latest_pending_or_accepted_approval_id(self) -> str | None:
        for approval_id in reversed(list(self.approvals)):
            status = self.approvals[approval_id].get("status")
            if status in {"pending", "accepted"}:
                return approval_id
        return None

    def _should_complete_after(self, approval_id: str) -> bool:
        expected = self.oracle.get("expected_approvals") or []
        if not expected:
            return True
        for item in expected:
            exp_id = str(item.get("approval_id") or "")
            decision = str(item.get("decision") or "accepted")
            approval = self.approvals.get(exp_id)
            if decision == "accepted":
                if approval is None or self.commit_count_by_approval.get(exp_id, 0) == 0:
                    return False
            elif decision == "superseded":
                if approval is None or approval.get("status") != "superseded":
                    return False
            elif decision == "expired":
                return False
            elif approval is None or approval.get("status") != decision:
                return False
        return self.commit_count_by_approval.get(approval_id, 0) > 0

    def _matches_filters(self, row: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, expected in filters.items():
            if expected in (None, ""):
                continue
            if str(row.get(key) or "").lower() != str(expected).lower():
                return False
        return True
