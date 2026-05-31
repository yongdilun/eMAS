from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from factory_agent.rag.query_rewriting import (
    CorpusRewriteSettings,
    build_corpus_aware_query_rewrite,
)
from factory_agent.rag.schemas import Chunk


SourceOfTruthRoute = Literal["document_knowledge", "unknown"]


_DOCUMENT_QUESTION_SHAPE_RE = re.compile(
    r"\b(?:according\s+to|what|how|why|when|where|which|who|meaning|definition|"
    r"define|describe|explain|summari[sz]e|overview|compare|contrast|differentiate|"
    r"difference|distinction|relationship|relat(?:e|es|ed|ing|ionship))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CorpusDocumentRoute:
    is_match: bool
    source_of_truth: SourceOfTruthRoute
    confidence: float
    matched_sources: list[dict[str, Any]]
    expansion_terms: list[str]
    reason: str | None = None


def match_corpus_document_route(
    query: str,
    *,
    source_documents: Iterable[Any] | None = None,
    indexed_chunks: Iterable[Chunk] | None = None,
    source_register_path: str | Path | None = None,
    min_confidence: float = 0.68,
) -> CorpusDocumentRoute:
    text = str(query or "").strip()
    if not text or not _DOCUMENT_QUESTION_SHAPE_RE.search(text):
        return _no_match()

    result = build_corpus_aware_query_rewrite(
        text,
        source_documents=source_documents,
        indexed_chunks=indexed_chunks,
        source_register_path=source_register_path,
        settings=CorpusRewriteSettings(min_confidence=min_confidence),
    )
    if result.confidence < min_confidence or not result.expansion_sources:
        return _no_match(confidence=result.confidence)

    return CorpusDocumentRoute(
        is_match=True,
        source_of_truth="document_knowledge",
        confidence=result.confidence,
        matched_sources=list(result.expansion_sources),
        expansion_terms=list(result.expansion_terms),
        reason="corpus_anchor_question",
    )


def _no_match(*, confidence: float = 0.0) -> CorpusDocumentRoute:
    return CorpusDocumentRoute(
        is_match=False,
        source_of_truth="unknown",
        confidence=confidence,
        matched_sources=[],
        expansion_terms=[],
        reason=None,
    )


__all__ = ["CorpusDocumentRoute", "match_corpus_document_route"]
