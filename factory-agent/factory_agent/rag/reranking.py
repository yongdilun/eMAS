import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from factory_agent.config import Settings, get_settings
from factory_agent.llm.models import build_bge_reranker
from factory_agent.rag.schemas import Chunk, ScoredChunk

logger = logging.getLogger(__name__)
LEGACY_RAG_RERANK_PROMPT_CONTRACT = "legacy_rag_rerank_v1"


class RerankerError(RuntimeError):
    """Base error for reranker failures that must not silently degrade evals."""


class RerankerUnavailableError(RerankerError):
    """Raised when rerank is requested but the reranker backend is unavailable."""


class RerankerExecutionError(RerankerError):
    """Raised when rerank is attempted and fails with fallback disabled."""


@dataclass(frozen=True)
class RerankTrace:
    enabled: bool
    backend: str
    model: str | None
    attempted: bool = False
    succeeded: bool = False
    fallback_used: bool = False
    fallback_allowed: bool = False
    error: str | None = None
    duration_s: float = 0.0
    candidate_count: int = 0
    selected_count: int = 0
    input_chunk_ids: list[str] = field(default_factory=list)
    output_chunk_ids: list[str] = field(default_factory=list)
    scores_by_chunk_id: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "model": self.model,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "fallback_used": self.fallback_used,
            "fallback_allowed": self.fallback_allowed,
            "error": self.error,
            "duration_s": round(self.duration_s, 4),
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "input_chunk_ids": list(self.input_chunk_ids),
            "output_chunk_ids": list(self.output_chunk_ids),
            "scores_by_chunk_id": dict(self.scores_by_chunk_id),
        }


class LLMReranker:
    """
    Implements Phase 3 — Reranking using BGE-Reranker-v2-m3.
    Replaces general LLM reasoning with a high-performance semantic model.
    """

    QUERY_TYPE_TO_DO_NOT_USE = {
        "API_ONLY": [
            "live factory status lookup", "live job scheduling decision",
            "machine availability lookup", "inventory quantity lookup",
            "live machine lock status lookup", "real-time permit approval"
        ],
        "RAG_ONLY": [],
        "API_THEN_RAG": [
            "legal or compliance certification",
            "automatic schedule approval"
        ]
    }

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.model_error: str | None = None
        try:
            self.model = build_bge_reranker(self.settings)
        except Exception as exc:
            self.model = None
            self.model_error = f"{type(exc).__name__}: {exc}"
        self.llm = None
        self.last_trace = RerankTrace(
            enabled=False,
            backend=self._backend_name(),
            model=self.settings.bge_reranker_model,
        ).to_dict()

    def rerank(
        self, 
        query: str, 
        candidates: List[ScoredChunk], 
        route: str, 
        top_k: Optional[int] = None,
        *,
        allow_fallback: bool = False,
    ) -> List[Chunk]:
        """
        Main entry point for reranking using BGE Cross-Encoder.
        """
        self._set_trace(
            enabled=True,
            attempted=False,
            succeeded=False,
            fallback_used=False,
            fallback_allowed=allow_fallback,
            error=None,
            duration_s=0.0,
            candidates=candidates,
            selected=[],
            scores_by_chunk_id={},
        )
        if not candidates:
            return []
            
        top_k = top_k or self.settings.rag_reranker_top_k
        start_time = time.time()
        
        try:
            legacy_llm = getattr(self, "llm", None)
            if legacy_llm is not None:
                return self._rerank_with_legacy_llm(
                    query,
                    candidates,
                    route,
                    top_k,
                    allow_fallback=allow_fallback,
                    start_time=start_time,
                )
            if self.model is None:
                message = self.model_error or "BGE reranker backend is unavailable"
                if allow_fallback:
                    selected = self._fallback_rerank(candidates, top_k)
                    self._set_trace(
                        enabled=True,
                        attempted=False,
                        succeeded=False,
                        fallback_used=True,
                        fallback_allowed=True,
                        error=message,
                        duration_s=time.time() - start_time,
                        candidates=candidates,
                        selected=selected,
                        scores_by_chunk_id={},
                    )
                    logger.warning("BGE Reranker unavailable: %s. Fallback was explicitly allowed.", message)
                    return selected
                self._set_trace(
                    enabled=True,
                    attempted=False,
                    succeeded=False,
                    fallback_used=False,
                    fallback_allowed=False,
                    error=message,
                    duration_s=time.time() - start_time,
                    candidates=candidates,
                    selected=[],
                    scores_by_chunk_id={},
                )
                raise RerankerUnavailableError(message)

            # 1. Prepare pairs for BGE
            # We include metadata summary in the doc text to help BGE understand context
            pairs = []
            for sc in candidates:
                meta = sc.chunk.metadata
                context_text = f"Source: {meta.get('title')} Authority: {meta.get('authority_level')} {sc.chunk.text}"
                pairs.append([query, context_text])
            
            # 2. Compute semantic scores
            scores = self.model.compute_score(pairs, max_length=1024)
            if not isinstance(scores, (list, tuple)):
                scores = [scores]
            if len(scores) != len(candidates):
                raise RerankerExecutionError(
                    f"BGE returned {len(scores)} scores for {len(candidates)} candidates"
                )
            
            # 3. Apply industrial boosts (Authority and Safety)
            # We combine the semantic BGE score with our rule-based boosts
            scored_candidates = []
            scores_by_chunk_id: dict[str, float] = {}
            for idx, sc in enumerate(candidates):
                # BGE scores are typically unbounded; we use them as the base
                base_score = float(scores[idx])
                
                # Apply rules similar to HybridRetriever to maintain safety alignment
                boost = 0.0
                meta = sc.chunk.metadata
                
                # Rule: High Authority boost
                auth = meta.get("authority_level")
                if auth == "mandatory_procedure":
                    boost += 2.0 # Significant boost for BGE scale
                elif auth == "official_public_guidance":
                    boost += 0.8
                
                # Rule: Safety boost
                if meta.get("risk_level") == "high" and any(t in query.lower() for t in ["safe", "loto", "hazard"]):
                    boost += 1.5
                
                sc.boosted_score = base_score + boost
                scores_by_chunk_id[sc.chunk.chunk_id] = sc.boosted_score
                scored_candidates.append(sc)

            # 4. Sort and filter based on hard rules
            # We sort by our combined BGE + Boost score
            sorted_candidates = sorted(scored_candidates, key=lambda x: x.boosted_score, reverse=True)
            
            # 5. Enforce strict safety rules and filter
            final_chunks = self._process_candidates(query, route, sorted_candidates, top_k)
            
            duration = time.time() - start_time
            logger.info(f"BGE Reranking completed in {duration:.2f}s. Selected {len(final_chunks)} chunks.")
            self._set_trace(
                enabled=True,
                attempted=True,
                succeeded=True,
                fallback_used=False,
                fallback_allowed=allow_fallback,
                error=None,
                duration_s=duration,
                candidates=candidates,
                selected=final_chunks,
                scores_by_chunk_id=scores_by_chunk_id,
            )
            
            return final_chunks

        except Exception as e:
            if isinstance(e, RerankerError) and not allow_fallback:
                raise
            if not allow_fallback:
                self._set_trace(
                    enabled=True,
                    attempted=True,
                    succeeded=False,
                    fallback_used=False,
                    fallback_allowed=False,
                    error=f"{type(e).__name__}: {e}",
                    duration_s=time.time() - start_time,
                    candidates=candidates,
                    selected=[],
                    scores_by_chunk_id={},
                )
                raise RerankerExecutionError(f"BGE reranker failed: {e}") from e
            logger.error(f"BGE Reranker failed: {e}. Fallback was explicitly allowed.")
            selected = self._fallback_rerank(candidates, top_k)
            self._set_trace(
                enabled=True,
                attempted=True,
                succeeded=False,
                fallback_used=True,
                fallback_allowed=True,
                error=f"{type(e).__name__}: {e}",
                duration_s=time.time() - start_time,
                candidates=candidates,
                selected=selected,
                scores_by_chunk_id={},
            )
            return selected

    def _rerank_with_legacy_llm(
        self,
        query: str,
        candidates: List[ScoredChunk],
        route: str,
        top_k: int,
        *,
        allow_fallback: bool,
        start_time: float,
    ) -> List[Chunk]:
        """Legacy compatibility path for older tests and deployments that inject an LLM reranker."""
        try:
            prompt = json.dumps(
                {
                    "query": query,
                    "route": route,
                    "candidate_ids": [sc.chunk.chunk_id for sc in candidates],
                }
            )
            response = self.llm.invoke(prompt)
            content = getattr(response, "content", response)
            ranked_ids = json.loads(content)
            if not isinstance(ranked_ids, list):
                raise ValueError("reranker response must be a JSON list")
            by_id = {sc.chunk.chunk_id: sc.chunk for sc in candidates}
            ordered = [by_id[str(chunk_id)] for chunk_id in ranked_ids if str(chunk_id) in by_id]
            seen = {chunk.chunk_id for chunk in ordered}
            ordered.extend(sc.chunk for sc in candidates if sc.chunk.chunk_id not in seen)
            scored = [
                ScoredChunk(chunk=chunk, boosted_score=float(len(ordered) - idx))
                for idx, chunk in enumerate(ordered)
            ]
            selected = self._process_candidates(query, route, scored, top_k)
            self._set_trace(
                enabled=True,
                attempted=True,
                succeeded=True,
                fallback_used=False,
                fallback_allowed=allow_fallback,
                error=None,
                duration_s=time.time() - start_time,
                candidates=candidates,
                selected=selected,
                scores_by_chunk_id={sc.chunk.chunk_id: float(sc.boosted_score or 0.0) for sc in scored},
                backend="legacy_llm",
            )
            return selected
        except Exception as e:
            if not allow_fallback:
                self._set_trace(
                    enabled=True,
                    attempted=True,
                    succeeded=False,
                    fallback_used=False,
                    fallback_allowed=False,
                    error=f"{type(e).__name__}: {e}",
                    duration_s=time.time() - start_time,
                    candidates=candidates,
                    selected=[],
                    scores_by_chunk_id={},
                    backend="legacy_llm",
                )
                raise RerankerExecutionError(f"LLM reranker failed: {e}") from e
            logger.error(f"LLM Reranker failed: {e}. Fallback was explicitly allowed.")
            selected = self._fallback_rerank(candidates, top_k)
            self._set_trace(
                enabled=True,
                attempted=True,
                succeeded=False,
                fallback_used=True,
                fallback_allowed=True,
                error=f"{type(e).__name__}: {e}",
                duration_s=time.time() - start_time,
                candidates=candidates,
                selected=selected,
                scores_by_chunk_id={},
                backend="legacy_llm",
            )
            return selected

    def _process_candidates(
        self, 
        query: str, 
        route: str,
        candidates: List[ScoredChunk],
        top_k: int
    ) -> List[Chunk]:
        """Validates and enforces strict rules on ranked candidates."""
        blocked_phrases = self.QUERY_TYPE_TO_DO_NOT_USE.get(route, [])
        final_chunks = []
        
        for sc in candidates:
            meta = sc.chunk.metadata
            
            # Strict do_not_use_for enforcement
            doc_do_not_use = [phrase.lower() for phrase in meta.get("do_not_use_for", [])]
            if any(blocked in doc_do_not_use for blocked in blocked_phrases):
                continue
            
            final_chunks.append(sc.chunk)
            if len(final_chunks) >= top_k:
                break
                
        # Safety retention fallback
        is_safety_query = any(term in query.lower() for term in ["safe", "loto", "guarding", "confined", "hazard"])
        if is_safety_query and not any(chunk.metadata.get("risk_level") == "high" for chunk in final_chunks):
            high_risk_chunk = next(
                (sc.chunk for sc in candidates if sc.chunk.metadata.get("risk_level") == "high"),
                None,
            )
            if high_risk_chunk is not None:
                final_chunks.insert(0, high_risk_chunk)
                if len(final_chunks) > top_k + 1:
                    final_chunks.pop()

        return final_chunks[:top_k+1]

    def _fallback_rerank(self, candidates: List[ScoredChunk], top_k: int) -> List[Chunk]:
        sorted_candidates = sorted(
            candidates, 
            key=lambda x: x.boosted_score or x.fusion_score or 0.0, 
            reverse=True
        )
        return [sc.chunk for sc in sorted_candidates[:top_k]]

    def _backend_name(self) -> str:
        if getattr(self, "llm", None) is not None:
            return "legacy_llm"
        if self.model is None:
            return "bge_transformers_unavailable"
        return type(self.model).__name__

    def _set_trace(
        self,
        *,
        enabled: bool,
        attempted: bool,
        succeeded: bool,
        fallback_used: bool,
        fallback_allowed: bool,
        error: str | None,
        duration_s: float,
        candidates: List[ScoredChunk],
        selected: List[Chunk],
        scores_by_chunk_id: dict[str, float],
        backend: str | None = None,
    ) -> None:
        self.last_trace = RerankTrace(
            enabled=enabled,
            backend=backend or self._backend_name(),
            model=self.settings.bge_reranker_model,
            attempted=attempted,
            succeeded=succeeded,
            fallback_used=fallback_used,
            fallback_allowed=fallback_allowed,
            error=error,
            duration_s=duration_s,
            candidate_count=len(candidates),
            selected_count=len(selected),
            input_chunk_ids=[sc.chunk.chunk_id for sc in candidates],
            output_chunk_ids=[chunk.chunk_id for chunk in selected],
            scores_by_chunk_id=scores_by_chunk_id,
        ).to_dict()
