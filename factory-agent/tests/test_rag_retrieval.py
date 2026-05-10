import unittest
from unittest.mock import MagicMock, patch
import time
import numpy as np

from factory_agent.rag.retrieval import HybridRetriever
from factory_agent.rag.schemas import Chunk, ScoredChunk

class TestHybridRetriever(unittest.TestCase):
    
    def setUp(self):
        # Mock ChromaDB and BM25 initialization
        with patch('chromadb.PersistentClient'), \
             patch('chromadb.utils.embedding_functions.DefaultEmbeddingFunction'), \
             patch('os.path.exists', return_value=True), \
             patch('pickle.load', return_value={"index": MagicMock(), "chunks": [MagicMock()]}):
            self.retriever = HybridRetriever(db_path="mock_db", bm25_path="mock_bm25.pkl")

    def test_h1_vector_search_top_k(self):
        """H1: Vector search returns <= vector_top_k results."""
        mock_results = {
            'ids': [['id1', 'id2', 'id3']],
            'documents': [['doc1', 'doc2', 'doc3']],
            'metadatas': [[{}, {}, {}]],
            'distances': [[0.1, 0.2, 0.3]]
        }
        self.retriever.collection.query = MagicMock(return_value=mock_results)
        
        results = self.retriever.vector_search("test query", top_k=2)
        self.retriever.collection.query.assert_called_with(
            query_texts=["test query"],
            n_results=2,
            include=["documents", "metadatas", "distances"]
        )

    def test_h2_bm25_exact_match(self):
        """H2: BM25 search returns results for queries containing exact eMAS terms."""
        chunk = Chunk(chunk_id="c1", text="LOTO procedure", metadata={})
        self.retriever.bm25_chunks = [chunk]
        self.retriever.bm25_index = MagicMock()
        self.retriever.bm25_index.get_scores = MagicMock(return_value=np.array([10.0]))
        
        results = self.retriever.keyword_search("LOTO")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.chunk_id, "c1")
        self.assertEqual(results[0].keyword_score, 1.0)

    def test_h3_rrf_no_duplicates(self):
        """H3: RRF fusion output contains no duplicate chunk_id values."""
        chunk1 = Chunk(chunk_id="c1", text="text1", metadata={})
        chunk2 = Chunk(chunk_id="c2", text="text2", metadata={})
        
        v_results = [ScoredChunk(chunk=chunk1, vector_score=0.9)]
        k_results = [ScoredChunk(chunk=chunk1, keyword_score=0.8), ScoredChunk(chunk=chunk2, keyword_score=0.7)]
        
        fusion_results = self.retriever.reciprocal_rank_fusion(v_results, k_results)
        
        ids = [res.chunk.chunk_id for res in fusion_results]
        self.assertEqual(len(ids), len(set(ids)), "Fusion output contains duplicates")
        self.assertIn("c1", ids)
        self.assertIn("c2", ids)

    def test_h4_rrf_sorting(self):
        """H4: Fusion output is sorted by descending fusion_score."""
        chunk1 = Chunk(chunk_id="c1", text="text1", metadata={})
        chunk2 = Chunk(chunk_id="c2", text="text2", metadata={})
        
        v_results = [ScoredChunk(chunk=chunk1, vector_score=0.9), ScoredChunk(chunk=chunk2, vector_score=0.8)]
        k_results = [ScoredChunk(chunk=chunk1, keyword_score=0.7)]
        
        fusion_results = self.retriever.reciprocal_rank_fusion(v_results, k_results)
        
        for i in range(len(fusion_results) - 1):
            self.assertGreaterEqual(fusion_results[i].fusion_score, fusion_results[i+1].fusion_score)

    def test_h5_do_not_use_for_filter(self):
        """H5: do_not_use_for filter removes chunks based on route."""
        blocked_chunk = Chunk(
            chunk_id="blocked", 
            text="background", 
            metadata={"do_not_use_for": ["live factory status lookup"]}
        )
        safe_chunk = Chunk(
            chunk_id="safe", 
            text="procedure", 
            metadata={"do_not_use_for": []}
        )
        
        candidates = [
            ScoredChunk(chunk=blocked_chunk, fusion_score=0.5),
            ScoredChunk(chunk=safe_chunk, fusion_score=0.4)
        ]
        
        results = self.retriever.apply_metadata_filter_and_boost(candidates, "query", "API_ONLY")
        ids = [res.chunk.chunk_id for res in results]
        self.assertNotIn("blocked", ids)
        self.assertIn("safe", ids)
        
        results = self.retriever.apply_metadata_filter_and_boost(candidates, "query", "RAG_ONLY")
        ids = [res.chunk.chunk_id for res in results]
        self.assertIn("blocked", ids)
        self.assertIn("safe", ids)

    def test_h6_boost_score_increase(self):
        """H6: boosted_score is always >= fusion_score."""
        chunk = Chunk(
            chunk_id="c1", 
            text="LOTO procedure", 
            metadata={
                "authority_level": "mandatory_procedure",
                "risk_level": "high"
            }
        )
        candidates = [ScoredChunk(chunk=chunk, fusion_score=0.5)]
        
        results = self.retriever.apply_metadata_filter_and_boost(candidates, "LOTO safety", "RAG_ONLY")
        self.assertGreater(results[0].boosted_score, results[0].fusion_score)

    def test_h7_filter_fallback(self):
        """H7: Filter never removes all chunks (fallback to top fusion)."""
        blocked_chunk = Chunk(
            chunk_id="blocked", 
            text="background", 
            metadata={"do_not_use_for": ["live factory status lookup"]}
        )
        candidates = [ScoredChunk(chunk=blocked_chunk, fusion_score=0.5)]
        
        results = self.retriever.apply_metadata_filter_and_boost(candidates, "query", "API_ONLY")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.chunk_id, "blocked")

    def test_h8_latency(self):
        """H8: Retrieval completes in under 2 seconds."""
        start_time = time.time()
        self.retriever.vector_search = MagicMock(return_value=[])
        self.retriever.keyword_search = MagicMock(return_value=[])
        
        self.retriever.retrieve("test query")
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 2.0)

if __name__ == "__main__":
    unittest.main()
