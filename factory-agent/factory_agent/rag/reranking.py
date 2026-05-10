import json
import logging
import time
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from factory_agent.config import Settings, get_settings
from factory_agent.llm import build_rag_reranker_chat_model
from factory_agent.rag.schemas import Chunk, ScoredChunk

logger = logging.getLogger(__name__)

RERANKER_PROMPT = """
You are an expert reranker for an industrial maintenance knowledge base (eMAS).

User query: {query}
Query route: {route}

Below are {n} retrieved document chunks. Select the {top_k} chunks most relevant
to answering the query. Apply these rules strictly:

Selection criteria (in priority order):
1. HARD RULE: Never select a chunk if the query matches any of its "do_not_use_for" items.
2. Prefer chunks whose "use_for" list matches the query intent.
3. Prefer higher authority_level: mandatory_procedure > official_public_guidance > reference_only.
4. Prefer specificity: specific procedure > general background knowledge.
5. Always retain safety-relevant chunks (risk_level: high) for safety queries.

Chunks:
{chunks_formatted}

Return ONLY a JSON array of selected chunk IDs, ordered by relevance (best first):
["chunk_id_1", "chunk_id_2", ...]
Do not include any other text.
"""

class LLMReranker:
    """
    Implements Phase 3 — Reranking.
    Uses an LLM to select the most relevant chunks from hybrid retrieval candidates.
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
        self.llm = build_rag_reranker_chat_model(self.settings, json_mode=True)

    def rerank(
        self, 
        query: str, 
        candidates: List[ScoredChunk], 
        route: str, 
        top_k: Optional[int] = None
    ) -> List[Chunk]:
        """
        Main entry point for reranking.
        Returns a list of selected Chunks in order of relevance.
        """
        if not candidates:
            return []
            
        top_k = top_k or self.settings.rag_reranker_top_k
        start_time = time.time()
        
        try:
            # 1. Format candidates for prompt
            chunks_formatted = self._format_candidates(candidates)
            
            # 2. Build prompt
            prompt = RERANKER_PROMPT.format(
                query=query,
                route=route,
                n=len(candidates),
                top_k=top_k,
                chunks_formatted=chunks_formatted
            )
            
            # 3. Call LLM
            messages = [
                SystemMessage(content="You are an industrial documentation expert."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            content = response.content
            
            # 4. Parse selected IDs
            if isinstance(content, str):
                selected_ids = json.loads(content)
            else:
                selected_ids = content # Assume it's already a dict if invoke returned a structured object
                
            if not isinstance(selected_ids, list):
                if isinstance(selected_ids, dict) and "selected_ids" in selected_ids:
                    selected_ids = selected_ids["selected_ids"]
                elif isinstance(selected_ids, dict) and any(isinstance(v, list) for v in selected_ids.values()):
                    # Find the first list value
                    selected_ids = next(v for v in selected_ids.values() if isinstance(v, list))
                else:
                    raise ValueError(f"Invalid LLM response format: {content}")
            
            # 5. Build final list and enforce strict safety rules
            selected_chunks = self._process_selected_ids(query, route, selected_ids, candidates, top_k)
            
            duration = time.time() - start_time
            logger.info(f"Reranking completed in {duration:.2f}s. Selected {len(selected_chunks)} chunks.")
            
            return selected_chunks

        except Exception as e:
            logger.error(f"Reranker failed: {e}. Falling back to boosted scores.")
            return self._fallback_rerank(candidates, top_k)

    def _format_candidates(self, candidates: List[ScoredChunk]) -> str:
        formatted = []
        for i, sc in enumerate(candidates):
            meta = sc.chunk.metadata
            formatted.append(
                f"[{i+1}] ID: {sc.chunk.chunk_id}\n"
                f"Source: {meta.get('title', 'Unknown')} ({meta.get('organization', 'Unknown')})\n"
                f"Domain: {meta.get('domain', 'Unknown')} / {meta.get('subdomain', 'Unknown')}\n"
                f"Authority: {meta.get('authority_level', 'Unknown')}\n"
                f"Use for: {'; '.join(meta.get('use_for', [])[:2])}\n"
                f"Do NOT use for: {'; '.join(meta.get('do_not_use_for', [])[:2])}\n"
                f"Risk: {meta.get('risk_level', 'Unknown')}\n"
                f"Text: {sc.chunk.text[:350]}..."
            )
        return "\n\n".join(formatted)

    def _process_selected_ids(
        self, 
        query: str, 
        route: str,
        selected_ids: List[str], 
        candidates: List[ScoredChunk],
        top_k: int
    ) -> List[Chunk]:
        """Validates and enforces strict rules on LLM-selected IDs."""
        id_to_chunk = {sc.chunk.chunk_id: sc.chunk for sc in candidates}
        blocked_phrases = self.QUERY_TYPE_TO_DO_NOT_USE.get(route, [])
        final_chunks = []
        
        # RR2: No hallucinated IDs
        valid_ids = [cid for cid in selected_ids if cid in id_to_chunk]
        
        for cid in valid_ids:
            chunk = id_to_chunk[cid]
            meta = chunk.metadata
            
            # RR3: Strict do_not_use_for enforcement
            doc_do_not_use = [phrase.lower() for phrase in meta.get("do_not_use_for", [])]
            if any(blocked in doc_do_not_use for blocked in blocked_phrases):
                logger.warning(f"Reranker: Filtering out LLM-selected chunk {cid} due to strict do_not_use_for violation")
                continue
            
            final_chunks.append(chunk)
            if len(final_chunks) >= top_k:
                break
                
        # RR4: Safety retention fallback
        # If a high-risk safety chunk was in candidates but missed by LLM, and query is safety-related
        is_safety_query = any(term in query.lower() for term in ["safe", "loto", "guarding", "confined", "hazard"])
        if is_safety_query:
            high_risk_candidates = [sc.chunk for sc in candidates if sc.chunk.metadata.get("risk_level") == "high"]
            for hr_chunk in high_risk_candidates:
                if hr_chunk not in final_chunks:
                    logger.warning(f"Retaining safety chunk {hr_chunk.chunk_id} missed by LLM reranker")
                    final_chunks.insert(0, hr_chunk) # Prioritize safety
                    if len(final_chunks) > top_k + 1: # Allow one extra for safety
                        final_chunks.pop()

        return final_chunks[:top_k+1] # Slightly flexible for safety

    def _fallback_rerank(self, candidates: List[ScoredChunk], top_k: int) -> List[Chunk]:
        """Fall back to top boosted scores (RR5)."""
        logger.info(f"Using fallback reranking (reranker_fallback: true)")
        # Sort by boosted_score if available, else fusion_score
        sorted_candidates = sorted(
            candidates, 
            key=lambda x: x.boosted_score or x.fusion_score or 0.0, 
            reverse=True
        )
        return [sc.chunk for sc in sorted_candidates[:top_k]]
