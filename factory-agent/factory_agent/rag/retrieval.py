import os
import json
import pickle
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

from factory_agent.rag.schemas import Chunk, ScoredChunk

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HybridRetriever:
    """
    Implements Phase 2 — Hybrid Retrieval.
    Combines Vector Search (ChromaDB) with Keyword Search (BM25) and applies 
    industrial-specific metadata filtering and boosting.
    """
    
    BOOST_RULES = {
        "entity_match": 0.25,          # related_entities overlap with query tokens
        "use_for_match": 0.20,         # query intent matches a use_for phrase
        "subdomain_match": 0.15,       # subdomain keyword appears in query
        "authority_mandatory": 0.15,   # authority_level == "mandatory_procedure"
        "authority_official": 0.08,    # authority_level == "official_public_guidance"
        "high_risk_safety": 0.10,      # risk_level == "high" for safety queries
    }

    def _clean_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Deserializes JSON strings in metadata back to lists/dicts."""
        clean = {}
        for k, v in metadata.items():
            if isinstance(v, str) and (v.startswith('[') or v.startswith('{')):
                try:
                    clean[k] = json.loads(v)
                except:
                    clean[k] = v
            else:
                clean[k] = v
        return clean

    QUERY_TYPE_TO_DO_NOT_USE = {
        "API_ONLY": [
            "live factory status lookup", "live job scheduling decision",
            "machine availability lookup", "inventory quantity lookup",
            "live machine lock status lookup", "real-time permit approval"
        ],
        "RAG_ONLY": [],   # No exclusions; documents are the source
        "API_THEN_RAG": [
            "legal or compliance certification",
            "automatic schedule approval"
        ]
    }

    def __init__(
        self, 
        db_path: str = "factory_agent/rag/vector_db", 
        bm25_path: str = "factory_agent/rag/bm25_index.pkl"
    ):
        self.db_path = db_path
        self.bm25_path = bm25_path
        
        # Initialize ChromaDB
        if not os.path.exists(db_path):
            logger.warning(f"Vector DB path not found: {db_path}")
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(name="emas_knowledge")
        
        # Initialize Embedding Function
        self.embed_fn = embedding_functions.DefaultEmbeddingFunction()
        
        # Load BM25 Index
        self.bm25_index = None
        self.bm25_chunks = []
        if os.path.exists(bm25_path):
            try:
                with open(bm25_path, "rb") as f:
                    data = pickle.load(f)
                    self.bm25_index = data["index"]
                    self.bm25_chunks = data["chunks"]
                logger.info(f"Loaded BM25 index from {bm25_path}")
            except Exception as e:
                logger.error(f"Failed to load BM25 index: {e}")
        else:
            logger.warning(f"BM25 index path not found: {bm25_path}")

    def vector_search(self, query: str, top_k: int = 8) -> List[ScoredChunk]:
        """Performs semantic search using ChromaDB."""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )
            
            scored_chunks = []
            if results['ids'] and results['ids'][0]:
                for i in range(len(results['ids'][0])):
                    chunk = Chunk(
                        chunk_id=results['ids'][0][i],
                        text=results['documents'][0][i],
                        metadata=self._clean_metadata(results['metadatas'][0][i])
                    )
                    # Convert distance to a similarity score (approximate)
                    # ChromaDB cosine distance is 1 - similarity, so 1 - distance = similarity
                    distance = results['distances'][0][i]
                    vector_score = max(0.0, 1.0 - distance)
                    
                    scored_chunks.append(ScoredChunk(
                        chunk=chunk,
                        vector_score=vector_score
                    ))
            return scored_chunks
        except Exception as e:
            logger.error(f"Vector search error: {e}")
            return []

    def keyword_search(self, query: str, top_k: int = 8) -> List[ScoredChunk]:
        """Performs keyword search using BM25."""
        if not self.bm25_index or not self.bm25_chunks:
            return []
            
        try:
            tokenized_query = query.lower().split()
            scores = self.bm25_index.get_scores(tokenized_query)
            
            # Sort chunks by BM25 score
            chunk_scores = list(zip(self.bm25_chunks, scores))
            chunk_scores.sort(key=lambda x: x[1], reverse=True)
            
            top_results = chunk_scores[:top_k]
            
            # Normalize BM25 scores (simple linear scaling for now)
            max_score = max(scores) if any(scores) else 1.0
            
            scored_chunks = []
            for chunk, score in top_results:
                if score <= 0: continue
                scored_chunks.append(ScoredChunk(
                    chunk=chunk,
                    keyword_score=score / max_score
                ))
            return scored_chunks
        except Exception as e:
            logger.error(f"Keyword search error: {e}")
            return []

    def reciprocal_rank_fusion(
        self,
        vector_results: List[ScoredChunk],
        keyword_results: List[ScoredChunk],
        k: int = 60,
        top_k: int = 8
    ) -> List[ScoredChunk]:
        """Combines results using Reciprocal Rank Fusion."""
        scores = {}
        all_chunks = {}
        vector_scores = {}
        keyword_scores = {}
        
        # Process vector results
        for rank, item in enumerate(vector_results):
            cid = item.chunk.chunk_id
            all_chunks[cid] = item.chunk
            vector_scores[cid] = item.vector_score
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            
        # Process keyword results
        for rank, item in enumerate(keyword_results):
            cid = item.chunk.chunk_id
            all_chunks[cid] = item.chunk
            keyword_scores[cid] = item.keyword_score
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            
        # Sort by RRF score
        sorted_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
        
        return [
            ScoredChunk(
                chunk=all_chunks[cid],
                vector_score=vector_scores.get(cid),
                keyword_score=keyword_scores.get(cid),
                fusion_score=scores[cid],
            )
            for cid in sorted_ids
        ]

    def get_neighbor_chunks(self, chunk_id: str, doc_id: str, direction: int = 1) -> Optional[Chunk]:
        """
        Fetches the immediate neighbor chunk (direction: -1 for previous, 1 for next).
        """
        try:
            # Parse current index
            base_id, current_idx_str = chunk_id.rsplit("_c", 1)
            current_idx = int(current_idx_str)
            neighbor_idx = current_idx + direction
            
            if neighbor_idx < 0:
                return None
                
            neighbor_id = f"{base_id}_c{neighbor_idx:04d}"
            
            result = self.collection.get(ids=[neighbor_id], include=["documents", "metadatas"])
            
            if result['ids'] and len(result['ids']) > 0:
                return Chunk(
                    chunk_id=result['ids'][0],
                    text=result['documents'][0],
                    metadata=self._clean_metadata(result['metadatas'][0])
                )
            return None
        except Exception as e:
            logger.debug(f"Neighbor fetch error for {chunk_id}: {e}")
            return None

    def apply_metadata_filter_and_boost(
        self,
        chunks: List[ScoredChunk],
        query: str,
        route: str
    ) -> List[ScoredChunk]:
        """Applies hard exclusions and boosts scores based on industrial metadata."""
        q_lower = query.lower()
        q_tokens = set(q_lower.split())
        blocked_phrases = self.QUERY_TYPE_TO_DO_NOT_USE.get(route, [])
        
        filtered = []
        for sc in chunks:
            meta = self._clean_metadata(sc.chunk.metadata)
            doc_do_not_use = [phrase.lower() for phrase in meta.get("do_not_use_for", [])]
            
            # Hard exclusion
            if any(blocked in doc_do_not_use for blocked in blocked_phrases):
                logger.info(f"Filtering out chunk {sc.chunk.chunk_id} due to do_not_use_for match")
                continue
            
            filtered.append(sc)
            
        # If filtering removed everything, keep the top fusion result as fallback
        if not filtered and chunks:
            logger.warning("All chunks filtered out! Falling back to top fusion result.")
            filtered = [chunks[0]]
            
        # Apply boosts
        for sc in filtered:
            boost = 0.0
            meta = self._clean_metadata(sc.chunk.metadata)
            
            # related_entities overlap
            entities = [e.lower().replace("_", " ") for e in meta.get("related_entities", [])]
            if any(entity in q_lower for entity in entities):
                boost += self.BOOST_RULES["entity_match"]
                
            # use_for semantic match (simple keyword overlap for now)
            use_for_terms = " ".join(meta.get("use_for", [])).lower()
            overlap = len(q_tokens & set(use_for_terms.split()))
            if overlap >= 2:
                boost += self.BOOST_RULES["use_for_match"]
                
            # subdomain keyword
            subdomain = meta.get("subdomain", "").replace("_", " ").lower()
            if subdomain and subdomain in q_lower:
                boost += self.BOOST_RULES["subdomain_match"]
                
            # Authority level
            authority = meta.get("authority_level", "")
            if authority == "mandatory_procedure":
                boost += self.BOOST_RULES["authority_mandatory"]
            elif authority == "official_public_guidance":
                boost += self.BOOST_RULES["authority_official"]
                
            # Safety query + high risk doc
            if meta.get("risk_level") == "high" and any(
                term in q_lower for term in ["safe", "loto", "guarding", "confined", "hazard"]
            ):
                boost += self.BOOST_RULES["high_risk_safety"]
                
            sc.boosted_score = (sc.fusion_score or 0.0) + boost
            
        return sorted(filtered, key=lambda x: x.boosted_score or 0.0, reverse=True)

    def retrieve(
        self, 
        query: str, 
        route: str = "RAG_ONLY",
        vector_top_k: int = 8,
        keyword_top_k: int = 8,
        fusion_top_k: int = 8,
        expand_neighbors: bool = True,
        retrieval_mode: str = "hybrid",
    ) -> List[ScoredChunk]:
        """Main entry point for retrieval.

        ``retrieval_mode="hybrid"`` preserves the existing vector + BM25 path.
        ``retrieval_mode="vector"`` skips BM25/RRF for clean vector-only evals.
        """
        mode = retrieval_mode.lower().replace("_", "-")
        if mode in {"vector", "vector-only"}:
            f_results = self.vector_search(query, top_k=vector_top_k)
            for result in f_results:
                if result.fusion_score is None:
                    result.fusion_score = result.vector_score
        elif mode == "hybrid":
            v_results = self.vector_search(query, top_k=vector_top_k)
            k_results = self.keyword_search(query, top_k=keyword_top_k)
            f_results = self.reciprocal_rank_fusion(v_results, k_results, top_k=fusion_top_k)
        else:
            raise ValueError(
                f"Unsupported retrieval_mode={retrieval_mode!r}; expected 'hybrid' or 'vector'"
            )

        final_results = self.apply_metadata_filter_and_boost(f_results, query, route)
        
        if not expand_neighbors:
            return final_results
            
        # Expand neighbors for top results to ensure continuity
        expanded_results = []
        seen_ids = {res.chunk.chunk_id for res in final_results}
        
        for res in final_results:
            expanded_results.append(res)
            
            # For the very top chunks, try to pull previous and next
            # (Limit expansion to avoid context bloat)
            if final_results.index(res) < 3: 
                doc_id = res.chunk.metadata.get("doc_id")
                if not doc_id: continue
                
                for direction in [-1, 1]:
                    neighbor = self.get_neighbor_chunks(res.chunk.chunk_id, doc_id, direction)
                    if neighbor and neighbor.chunk_id not in seen_ids:
                        # Add neighbor as a scored chunk with slightly lower score than parent
                        expanded_results.append(ScoredChunk(
                            chunk=neighbor,
                            boosted_score=(res.boosted_score or 0) * 0.9,
                            fusion_score=(res.fusion_score or 0) * 0.9
                        ))
                        seen_ids.add(neighbor.chunk_id)
                        
        return expanded_results

if __name__ == "__main__":
    # Quick test if run directly
    retriever = HybridRetriever()
    results = retriever.retrieve("What is the LOTO procedure?")
    for res in results:
        print(f"ID: {res.chunk.chunk_id}, Score: {res.boosted_score:.4f}, Text: {res.chunk.text[:100]}...")
