import re
import json
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage

class QueryRouter:
    """
    Classifies a user query into one of three routes.
    Uses rule-based signals first; falls back to LLM classification.
    """

    API_KEYWORDS = [
        "show", "list", "fetch", "get", "display", "current", "today",
        "now", "live", "status", "count", "total", "value", "reading", "oee"
    ]

    RAG_KEYWORDS = [
        "explain", "procedure",
        "steps", "definition", "standard", "policy", "guideline",
        "describe", "meaning of"
    ]

    DIAGNOSE_KEYWORDS = [
        "why", "should i", "is this normal", "what should", "recommend",
        "troubleshoot", "fault", "error", "problem", "issue", "concern",
        "acceptable", "threshold", "too high", "too low"
    ]

    MACHINE_ID_PATTERN = r"\b(M-\d+|Line \d+|Station \d+|Unit \d+)\b"
    SAFETY_TERMS = {"loto", "csf", "guarding", "confined", "ppe", "sop"}

    def __init__(self, llm: Any | None = None):
        """
        :param llm: A LangChain chat model to use for fallback classification.
        """
        self.llm = llm

    async def route(self, query: str) -> dict[str, Any]:
        """
        Returns: {"route": "API_ONLY" | "RAG_ONLY" | "API_THEN_RAG", "route_source": "rule" | "llm"}
        """
        q = query.lower()
        has_machine_id = bool(re.search(self.MACHINE_ID_PATTERN, query, re.IGNORECASE))
        has_safety_term = any(term in q for term in self.SAFETY_TERMS)
        has_api_signal = any(kw in q for kw in self.API_KEYWORDS)
        has_rag_signal = any(kw in q for kw in self.RAG_KEYWORDS)
        has_diagnose_signal = any(kw in q for kw in self.DIAGNOSE_KEYWORDS)

        # Rule 1: Live data only, no need for explanation
        if has_api_signal and not has_rag_signal and not has_diagnose_signal:
            return {"route": "API_ONLY", "route_source": "rule"}

        # Rule 2: Pure explanation/procedure, no live data markers
        if has_rag_signal and not has_api_signal and not has_machine_id:
            return {"route": "RAG_ONLY", "route_source": "rule"}

        # Rule 3: Diagnose signal always means both
        if has_diagnose_signal:
            return {"route": "API_THEN_RAG", "route_source": "rule"}

        # Rule 4: Machine ID + explanation = both
        if has_machine_id and (has_rag_signal or has_safety_term):
            return {"route": "API_THEN_RAG", "route_source": "rule"}

        # Rule 5: Safety term alone = RAG
        if has_safety_term and not has_api_signal:
            return {"route": "RAG_ONLY", "route_source": "rule"}

        # Fallback: LLM-based classification
        return await self._llm_classify(query)

    async def _llm_classify(self, query: str) -> dict[str, Any]:
        """
        Used when rule-based signals are ambiguous.
        Prompt the LLM to classify. Expect JSON: {"route": "RAG_ONLY"}
        """
        if not self.llm:
            # Safe default if no LLM is configured
            return {"route": "RAG_ONLY", "route_source": "fallback_default"}

        system_prompt = """You are a query router for an industrial maintenance system (eMAS).
Classify this query into exactly one route:

- API_ONLY: needs live machine data, metrics, or operational records only
- RAG_ONLY: asks for explanations, procedures, standards, definitions, or policy without needing live data
- API_THEN_RAG: needs live data AND context/explanation, or asks for a diagnosis/recommendation

Output your decision as a JSON object with a single key "route" mapped to the route name."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ]

        try:
            # We assume self.llm is a ChatOpenAI with json_mode enabled
            response = await self.llm.ainvoke(messages)
            content = str(response.content).strip()
            
            # Simple cleanup in case the LLM wrapped it in markdown
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()

            parsed = json.loads(content)
            route = parsed.get("route", "RAG_ONLY")
            
            # Validate route
            if route not in ("API_ONLY", "RAG_ONLY", "API_THEN_RAG"):
                route = "RAG_ONLY"
                
            return {"route": route, "route_source": "llm"}
        except Exception:
            # Never raise an unhandled exception per R3
            return {"route": "RAG_ONLY", "route_source": "llm_error"}
