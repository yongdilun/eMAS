from __future__ import annotations

from factory_agent.rag.schemas import Chunk, DocumentEntry, ScoredChunk, SourceRegister

__all__ = [
    "Chunk",
    "DocumentEntry",
    "IngestionEngine",
    "RAGPipeline",
    "ScoredChunk",
    "SourceRegister",
]


def __getattr__(name: str):
    if name == "IngestionEngine":
        from factory_agent.rag.ingestion import IngestionEngine

        return IngestionEngine
    if name == "RAGPipeline":
        from factory_agent.rag.pipeline import RAGPipeline

        return RAGPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
