from __future__ import annotations

from typing import Any, Protocol

from factory_agent.rag.schemas import AgentResponse


class RouterProtocol(Protocol):
    async def route(self, query: str) -> dict[str, Any]:
        ...


class ExecutionRunnerProtocol(Protocol):
    async def execute(self, *, query: str, session_id: str | None = None, guidance_context: str | None = None) -> Any:
        ...


class RAGRunnerProtocol(Protocol):
    async def run(
        self,
        *,
        query: str,
        session_id: str | None = None,
        route: str = "RAG_ONLY",
        api_data: dict[str, Any] | None = None,
    ) -> Any:
        ...


class SessionAdapterProtocol(Protocol):
    def build_answer_from_execution(self, execution_result: Any) -> str:
        ...

    def summarize_execution(self, execution_result: Any) -> str:
        ...

    def serialize_rag_context(self, rag_result: Any) -> str:
        ...


class Phase5Agent:
    """Deprecated route-score compatibility orchestrator.

    Graph-native execution does not use this module; it remains for legacy RAG
    evaluation and compatibility tests that still exercise route decisions.
    """

    ROUTES = {"API_ONLY", "RAG_ONLY", "API_THEN_RAG", "RAG_THEN_API", "CLARIFY"}

    def __init__(
        self,
        *,
        router: RouterProtocol,
        execution_runner: ExecutionRunnerProtocol,
        rag_pipeline: RAGRunnerProtocol,
        session_adapter: SessionAdapterProtocol,
    ) -> None:
        self._router = router
        self._execution_runner = execution_runner
        self._rag_pipeline = rag_pipeline
        self._session_adapter = session_adapter

    async def run(self, *, query: str, session_id: str | None = None) -> AgentResponse:
        decision = await self._router.route(query)
        route = str(decision.get("route") or "")
        metadata: dict[str, Any] = {"route_decision": decision}

        if route not in self.ROUTES:
            return self._safe_error_response(
                route=route or "UNSUPPORTED",
                message="The request could not be routed safely.",
                metadata=metadata,
            )

        try:
            if route == "CLARIFY":
                prompt = (
                    decision.get("clarification_prompt")
                    or decision.get("clarify_reason")
                    or "Please provide more specific details (target entity, metric, and intent)."
                )
                return AgentResponse(answer=str(prompt), sources=[], route=route, metadata=metadata)

            if route == "RAG_ONLY":
                rag = await self._rag_pipeline.run(query=query, session_id=session_id, route=route)
                return AgentResponse(
                    answer=self._normalize_answer(getattr(rag, "answer", None)),
                    sources=list(getattr(rag, "sources", []) or []),
                    route=route,
                    safety_warning=bool(getattr(rag, "safety_warning", False)),
                    metadata=metadata,
                )

            if route == "API_ONLY":
                exec_result = await self._execution_runner.execute(query=query, session_id=session_id)
                return AgentResponse(
                    answer=self._normalize_answer(self._session_adapter.build_answer_from_execution(exec_result)),
                    sources=[],
                    route=route,
                    metadata=metadata | {"execution_status": getattr(exec_result, "status", None)},
                )

            if route == "API_THEN_RAG":
                exec_result = await self._execution_runner.execute(query=query, session_id=session_id)
                execution_summary = self._session_adapter.summarize_execution(exec_result)
                enriched_query = f"{query}\n\nExecution context:\n{execution_summary}"
                rag = await self._rag_pipeline.run(
                    query=enriched_query,
                    session_id=session_id,
                    route=route,
                )
                return AgentResponse(
                    answer=self._normalize_answer(getattr(rag, "answer", None)),
                    sources=list(getattr(rag, "sources", []) or []),
                    route=route,
                    safety_warning=bool(getattr(rag, "safety_warning", False)),
                    metadata=metadata | {"execution_status": getattr(exec_result, "status", None)},
                )

            # RAG_THEN_API
            rag = await self._rag_pipeline.run(query=query, session_id=session_id, route=route)
            guidance_context = self._session_adapter.serialize_rag_context(rag)
            exec_result = await self._execution_runner.execute(
                query=query,
                session_id=session_id,
                guidance_context=guidance_context,
            )
            return AgentResponse(
                answer=self._normalize_answer(self._session_adapter.build_answer_from_execution(exec_result)),
                sources=list(getattr(rag, "sources", []) or []),
                route=route,
                safety_warning=bool(getattr(rag, "safety_warning", False)),
                metadata=metadata | {"execution_status": getattr(exec_result, "status", None)},
            )
        except Exception:
            return self._safe_error_response(
                route=route,
                message="The request could not be completed safely. Please retry with more specific context.",
                metadata=metadata,
            )

    @staticmethod
    def _normalize_answer(answer: Any) -> str:
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
        return "Execution completed, but no readable summary was produced."

    @staticmethod
    def _safe_error_response(*, route: str, message: str, metadata: dict[str, Any]) -> AgentResponse:
        return AgentResponse(
            answer=message,
            sources=[],
            route=route,
            safety_warning=False,
            metadata=metadata,
        )
