import unittest
from unittest.mock import MagicMock, patch
import json
import time

from factory_agent.rag.reranking import LLMReranker
from factory_agent.rag.schemas import Chunk, ScoredChunk

class TestLLMReranker(unittest.TestCase):
    
    def setUp(self):
        with patch('factory_agent.rag.reranking.build_rag_reranker_chat_model'):
            self.reranker = LLMReranker()
            self.reranker.llm = MagicMock()

    def test_rr1_returns_top_k(self):
        """RR1: Reranker returns exactly reranker_top_k chunks (or candidates count)."""
        candidates = [
            ScoredChunk(chunk=Chunk(chunk_id=f"id{i}", text=f"text{i}", metadata={}))
            for i in range(5)
        ]
        
        # Mock LLM to return 2 IDs
        mock_response = MagicMock()
        mock_response.content = json.dumps(["id0", "id1"])
        self.reranker.llm.invoke = MagicMock(return_value=mock_response)
        
        result = self.reranker.rerank("query", candidates, "RAG_ONLY", top_k=2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].chunk_id, "id0")
        self.assertEqual(result[1].chunk_id, "id1")

    def test_rr2_no_hallucination(self):
        """RR2: All returned chunk IDs exist in candidate set."""
        candidates = [
            ScoredChunk(chunk=Chunk(chunk_id="real_id", text="text", metadata={}))
        ]
        
        # Mock LLM to return a hallucinated ID
        mock_response = MagicMock()
        mock_response.content = json.dumps(["hallucinated_id", "real_id"])
        self.reranker.llm.invoke = MagicMock(return_value=mock_response)
        
        result = self.reranker.rerank("query", candidates, "RAG_ONLY", top_k=2)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].chunk_id, "real_id")

    def test_rr3_strict_do_not_use_for_enforcement(self):
        """RR3: Post-rerank validation step removes any chunk still violating do_not_use_for."""
        blocked_chunk = Chunk(
            chunk_id="blocked_id", 
            text="background", 
            metadata={"do_not_use_for": ["live factory status lookup"]}
        )
        safe_chunk = Chunk(
            chunk_id="safe_id", 
            text="procedure", 
            metadata={"do_not_use_for": []}
        )
        
        candidates = [
            ScoredChunk(chunk=blocked_chunk, fusion_score=0.9),
            ScoredChunk(chunk=safe_chunk, fusion_score=0.8)
        ]
        
        # Mock LLM to return both, but RR3 should filter blocked_id for API_ONLY route
        mock_response = MagicMock()
        mock_response.content = json.dumps(["blocked_id", "safe_id"])
        self.reranker.llm.invoke = MagicMock(return_value=mock_response)
        
        result = self.reranker.rerank("status check", candidates, "API_ONLY", top_k=2)
        ids = [c.chunk_id for c in result]
        self.assertNotIn("blocked_id", ids)
        self.assertIn("safe_id", ids)

    def test_rr4_safety_retention(self):
        """RR4: A high-risk safety chunk is retained for safety queries."""
        hr_chunk = Chunk(chunk_id="safety_id", text="danger", metadata={"risk_level": "high"})
        other_chunk = Chunk(chunk_id="other_id", text="info", metadata={"risk_level": "low"})
        
        candidates = [
            ScoredChunk(chunk=hr_chunk, fusion_score=0.1), # Low score
            ScoredChunk(chunk=other_chunk, fusion_score=0.9)
        ]
        
        # Mock LLM to only return other_id
        mock_response = MagicMock()
        mock_response.content = json.dumps(["other_id"])
        self.reranker.llm.invoke = MagicMock(return_value=mock_response)
        
        # Safety query
        result = self.reranker.rerank("LOTO hazard", candidates, "RAG_ONLY", top_k=1)
        ids = [c.chunk_id for c in result]
        self.assertIn("safety_id", ids)
        self.assertIn("other_id", ids)

    def test_rr6_safety_retention_does_not_reorder_already_safe_ranked_results(self):
        """RR6: Safety retention must not rotate same-risk OSHA chunks after reranking."""
        candidates = [
            ScoredChunk(
                chunk=Chunk(
                    chunk_id="osha_3120_lockout_tagout_c0029",
                    text="After removing devices but before reenergizing, employees must know.",
                    metadata={"risk_level": "high"},
                ),
                boosted_score=10.0,
            ),
            ScoredChunk(
                chunk=Chunk(
                    chunk_id="osha_3120_lockout_tagout_c0036",
                    text="Tagout devices are warning devices.",
                    metadata={"risk_level": "high"},
                ),
                boosted_score=9.0,
            ),
            ScoredChunk(
                chunk=Chunk(
                    chunk_id="osha_3120_lockout_tagout_c0028",
                    text="Workers can be injured if devices are removed without knowledge.",
                    metadata={"risk_level": "high"},
                ),
                boosted_score=8.0,
            ),
            ScoredChunk(
                chunk=Chunk(
                    chunk_id="osha_3120_lockout_tagout_c0027",
                    text="Appendix A contains a typical minimal lockout procedure.",
                    metadata={"risk_level": "high"},
                ),
                boosted_score=7.0,
            ),
        ]

        result = self.reranker._process_candidates(
            "LOTO hazard before reenergizing",
            "RAG_ONLY",
            candidates,
            top_k=3,
        )

        self.assertEqual([chunk.chunk_id for chunk in result], [
            "osha_3120_lockout_tagout_c0029",
            "osha_3120_lockout_tagout_c0036",
            "osha_3120_lockout_tagout_c0028",
        ])

    def test_rr5_fallback_on_timeout(self):
        """RR5: Timeout triggers fallback to boosted scores."""
        chunk1 = Chunk(chunk_id="id1", text="t1", metadata={})
        chunk2 = Chunk(chunk_id="id2", text="t2", metadata={})
        
        candidates = [
            ScoredChunk(chunk=chunk1, boosted_score=0.9),
            ScoredChunk(chunk=chunk2, boosted_score=0.8)
        ]
        
        # Mock LLM to raise timeout
        self.reranker.llm.invoke = MagicMock(side_effect=Exception("Timeout"))
        
        result = self.reranker.rerank("query", candidates, "RAG_ONLY", top_k=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].chunk_id, "id1")

    def test_rr7_latency(self):
        """RR7: Reranker completes in reasonable time (mocked)."""
        candidates = [ScoredChunk(chunk=Chunk(chunk_id="id", text="text", metadata={}))]
        mock_response = MagicMock()
        mock_response.content = json.dumps(["id"])
        self.reranker.llm.invoke = MagicMock(return_value=mock_response)
        
        start_time = time.time()
        self.reranker.rerank("query", candidates, "RAG_ONLY")
        duration = time.time() - start_time
        self.assertLess(duration, 3.0)

if __name__ == "__main__":
    unittest.main()
