from __future__ import annotations

import os
import pickle
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal

from factory_agent.rag.document_augmentation import DEFAULT_BM25_PATH, DEFAULT_VECTOR_DB_PATH
from factory_agent.rag.document_registry import default_source_register_path
from factory_agent.rag.query_rewriting import (
    CorpusRewriteSettings,
    build_corpus_aware_query_rewrite,
)
from factory_agent.rag.schemas import Chunk, SourceRegister


SourceOfTruthRoute = Literal["document_knowledge", "unknown"]
ROUTING_BM25_PATH_ENV = "RAG_ROUTING_BM25_PATH"
ROUTING_VECTOR_DB_PATH_ENV = "RAG_ROUTING_VECTOR_DB_PATH"
ROUTING_CHROMA_COLLECTION_ENV = "RAG_ROUTING_CHROMA_COLLECTION"
DEFAULT_ROUTING_CHROMA_COLLECTION = "emas_knowledge"


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


@dataclass(frozen=True)
class CorpusRoutingAnchors:
    source_documents: tuple[dict[str, Any], ...]
    indexed_chunks: tuple[Chunk, ...]
    diagnostics: dict[str, Any]


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


def match_runtime_corpus_document_route(
    query: str,
    *,
    min_confidence: float = 0.68,
) -> CorpusDocumentRoute:
    anchors = default_runtime_corpus_routing_anchors()
    return match_corpus_document_route(
        query,
        source_documents=anchors.source_documents,
        indexed_chunks=anchors.indexed_chunks,
        min_confidence=min_confidence,
    )


def default_runtime_corpus_routing_anchors() -> CorpusRoutingAnchors:
    source_register_path = _resolved_path_text(default_source_register_path())
    bm25_path = _env_path_text(ROUTING_BM25_PATH_ENV, DEFAULT_BM25_PATH)
    vector_db_path = _env_path_text(ROUTING_VECTOR_DB_PATH_ENV, DEFAULT_VECTOR_DB_PATH)
    collection_name = os.getenv(ROUTING_CHROMA_COLLECTION_ENV, DEFAULT_ROUTING_CHROMA_COLLECTION)
    return _load_runtime_corpus_routing_anchors_cached(
        source_register_path,
        bm25_path,
        vector_db_path,
        collection_name,
    )


def clear_runtime_corpus_routing_anchor_cache() -> None:
    _load_runtime_corpus_routing_anchors_cached.cache_clear()


@lru_cache(maxsize=8)
def _load_runtime_corpus_routing_anchors_cached(
    source_register_path: str,
    bm25_path: str,
    vector_db_path: str,
    collection_name: str,
) -> CorpusRoutingAnchors:
    source_documents = tuple(_load_source_register_documents(Path(source_register_path)))
    indexed_chunks = tuple(_load_indexed_chunks_from_bm25(Path(bm25_path)))
    index_source = "bm25" if indexed_chunks else "none"
    if not indexed_chunks:
        indexed_chunks = tuple(
            _load_indexed_chunks_from_chroma(
                Path(vector_db_path),
                collection_name=collection_name,
            )
        )
        index_source = "chroma" if indexed_chunks else "none"

    return CorpusRoutingAnchors(
        source_documents=source_documents,
        indexed_chunks=indexed_chunks,
        diagnostics={
            "source_register_path": source_register_path,
            "source_document_count": len(source_documents),
            "bm25_path": bm25_path,
            "vector_db_path": vector_db_path,
            "chroma_collection": collection_name,
            "indexed_chunk_count": len(indexed_chunks),
            "indexed_chunk_source": index_source,
        },
    )


def _load_source_register_documents(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        register = SourceRegister.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [doc.model_dump() for doc in register.documents]


def _load_indexed_chunks_from_bm25(path: Path) -> list[Chunk]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
    except Exception:
        return []
    raw_chunks = payload.get("chunks") if isinstance(payload, dict) else getattr(payload, "chunks", None)
    return _coerce_chunks(raw_chunks or [])


def _load_indexed_chunks_from_chroma(path: Path, *, collection_name: str) -> list[Chunk]:
    if not path.exists():
        return []
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(path))
        collection = client.get_collection(name=collection_name)
        result = collection.get(include=["documents", "metadatas"])
    except Exception:
        return []
    return [
        Chunk(
            chunk_id=str(chunk_id),
            text=str(document or ""),
            metadata=dict(metadata or {}),
        )
        for chunk_id, document, metadata in zip(
            result.get("ids") or [],
            result.get("documents") or [],
            result.get("metadatas") or [],
        )
        if str(chunk_id or "").strip()
    ]


def _coerce_chunks(raw_chunks: Iterable[Any]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for raw in raw_chunks:
        if isinstance(raw, Chunk):
            chunks.append(raw)
            continue
        if hasattr(raw, "model_dump"):
            data = raw.model_dump()
        elif isinstance(raw, dict):
            data = dict(raw)
        else:
            data = {
                "chunk_id": getattr(raw, "chunk_id", ""),
                "text": getattr(raw, "text", ""),
                "metadata": getattr(raw, "metadata", {}),
            }
        try:
            chunks.append(
                Chunk(
                    chunk_id=str(data.get("chunk_id") or ""),
                    text=str(data.get("text") or ""),
                    metadata=dict(data.get("metadata") or {}),
                )
            )
        except Exception:
            continue
    return [chunk for chunk in chunks if chunk.chunk_id]


def _env_path_text(env_name: str, default_path: str | Path) -> str:
    return _resolved_path_text(os.getenv(env_name) or default_path)


def _resolved_path_text(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def _no_match(*, confidence: float = 0.0) -> CorpusDocumentRoute:
    return CorpusDocumentRoute(
        is_match=False,
        source_of_truth="unknown",
        confidence=confidence,
        matched_sources=[],
        expansion_terms=[],
        reason=None,
    )


__all__ = [
    "CorpusDocumentRoute",
    "CorpusRoutingAnchors",
    "clear_runtime_corpus_routing_anchor_cache",
    "default_runtime_corpus_routing_anchors",
    "match_corpus_document_route",
    "match_runtime_corpus_document_route",
]
