from __future__ import annotations

from typing import Any, Mapping

from factory_agent.rag.answer_contract import answer_or_insufficient_context
from factory_agent.rag.source_metadata import normalize_source_locators, sanitize_rag_answer_text
from factory_agent.schemas import ToolInfo

from .v2_contracts import EvidenceCitation, EvidenceLedgerEntry, RequirementLedgerEntry


V2_RAG_TOOL_NAME = "rag_search_documents"


def v2_rag_tool_info() -> ToolInfo:
    """Virtual v2 document-search tool advertised through normal tool retrieval."""

    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
        "x-ai-response-contracts": ["knowledge_answer_v1"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object"}},
        },
        "x-ai-response-contracts": ["knowledge_answer_v1"],
    }
    return ToolInfo(
        name=V2_RAG_TOOL_NAME,
        description="Search document knowledge sources and return a cited answer.",
        endpoint="/rag/documents/search",
        method="GET",
        input_schema=input_schema,
        output_schema=output_schema,
        path_params=[],
        query_params=["query", "limit"],
        param_sources={"query": "query", "limit": "query"},
        is_read_only=True,
        requires_approval=False,
        side_effect_level="NONE",
        capability_tags=[
            "rag",
            "document",
            "document_knowledge",
            "knowledge",
            "search",
            "citation",
            "procedure",
            "policy",
        ],
    )


def ensure_v2_rag_tool(tools_by_name: Mapping[str, ToolInfo]) -> dict[str, ToolInfo]:
    tools = dict(tools_by_name)
    tools.setdefault(V2_RAG_TOOL_NAME, v2_rag_tool_info())
    return tools


def open_document_requirements(state: Any) -> list[RequirementLedgerEntry]:
    ledger = getattr(state, "requirement_ledger", None)
    if ledger is None:
        return []
    return [
        requirement
        for requirement in ledger.requirements
        if requirement.requirement_type == "document_answer"
        and requirement.source_of_truth == "document_knowledge"
        and requirement.status in {"open", "blocked"}
    ]


def build_v2_rag_evidence(
    *,
    requirement: RequirementLedgerEntry,
    query: str,
    result: Any,
    evidence_id: str,
) -> tuple[EvidenceLedgerEntry | None, str, list[dict[str, Any]], str | None]:
    answer = sanitize_rag_answer_text(str(getattr(result, "answer", "") or ""))
    raw_sources = list(getattr(result, "sources", []) or [])
    sources = normalize_source_locators(raw_sources, fallback_snippet=answer)
    safety_content = getattr(result, "safety_content", None)
    answer, _validation = answer_or_insufficient_context(answer, sources)
    citations: list[EvidenceCitation] = []
    for source in sources:
        citation = _citation_from_source(source)
        if citation is not None:
            citations.append(citation)
    if not answer:
        answer = "I could not find enough relevant knowledge-base material to answer that safely."

    if not citations:
        return None, answer, sources, safety_content

    evidence = EvidenceLedgerEntry(
        id=evidence_id,
        requirement_id=requirement.id,
        source_type="rag_tool",
        source_of_truth="document_knowledge",
        confidence="deterministic",
        tool_name=V2_RAG_TOOL_NAME,
        args={"query": query},
        result_ref=evidence_id,
        normalized_result={"answer": answer},
        citations=citations,
        satisfies=["source_citation", "document_answer"],
    )
    return evidence, answer, sources, safety_content


def _citation_from_source(source: dict[str, Any]) -> EvidenceCitation | None:
    source_id = str(source.get("source_id") or source.get("doc_id") or "").strip()
    if not source_id:
        return None
    return EvidenceCitation(
        source_id=source_id,
        title=str(source.get("title") or "").strip() or None,
        doc_id=str(source.get("doc_id") or source.get("procedure_id") or "").strip() or None,
        chunk_id=str(source.get("chunk_id") or "").strip() or None,
        page=source.get("page") if isinstance(source.get("page"), int) else None,
        locator={
            key: value
            for key, value in source.items()
            if key
            in {
                "pdf_url",
                "page_label",
                "bbox",
                "char_range",
                "text_search",
                "source_number",
            }
            and value not in (None, "", [], {})
        },
        snippet=str(source.get("snippet") or "").strip() or None,
    )
