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
                        metadata=results['metadatas'][0][i]
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
        
        # Process vector results
        for rank, item in enumerate(vector_results):
            cid = item.chunk.chunk_id
            all_chunks[cid] = item.chunk
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            
        # Process keyword results
        for rank, item in enumerate(keyword_results):
            cid = item.chunk.chunk_id
            all_chunks[cid] = item.chunk
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            
        # Sort by RRF score
        sorted_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
        
        return [
            ScoredChunk(chunk=all_chunks[cid], fusion_score=scores[cid])
            for cid in sorted_ids
        ]

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
            meta = sc.chunk.metadata
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
            meta = sc.chunk.metadata
            
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
        fusion_top_k: int = 8
    ) -> List[ScoredChunk]:
        """Main entry point for hybrid retrieval."""
        v_results = self.vector_search(query, top_k=vector_top_k)
        k_results = self.keyword_search(query, top_k=keyword_top_k)
        
        f_results = self.reciprocal_rank_fusion(v_results, k_results, top_k=fusion_top_k)
        
        final_results = self.apply_metadata_filter_and_boost(f_results, query, route)
        
        return final_results

if __name__ == "__main__":
    # Quick test if run directly
    retriever = HybridRetriever()
    results = retriever.retrieve("What is the LOTO procedure?")
    for res in results:
        print(f"ID: {res.chunk.chunk_id}, Score: {res.boosted_score:.4f}, Text: {res.chunk.text[:100]}...")
