import json
import logging
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from factory_agent.config import Settings, get_settings
from factory_agent.llm import build_rag_answer_chat_model
from factory_agent.rag.schemas import Chunk, SourceCitation, AnswerResult

logger = logging.getLogger(__name__)

ANSWER_PROMPT = """
You are eMAS Assistant, an expert in industrial maintenance, safety, and operations.

Answer the user's question using ONLY the provided context. Do not use prior knowledge.
If the context does not contain enough information to answer, say so clearly.

Rules:
- Be concise and direct
- Use numbered steps for procedures
- Cite source numbers like [SOURCE 1] after each claim
- If risk_level is "high" in any source, add a safety warning at the end
- Do not speculate beyond the context

Context:
{context}

{api_data_section}

User question: {query}

Answer:
"""

API_DATA_SECTION_TEMPLATE = """
Live system data (from API):
{api_data}

Use this live data together with the document context to give a complete answer.
"""

SAFETY_WARNING_BLOCK = """
⚠️ SAFETY WARNING: This topic involves high-risk procedures.
Always follow your site's approved SOP, obtain required permits,
and consult your safety officer before proceeding.
"""

class AnswerGenerator:
    """
    Implements Phase 4 — Answer Generation.
    Builds context, calls LLM to generate answer, and formats citations/safety warnings.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.llm = build_rag_answer_chat_model(self.settings)

    def generate(
        self, 
        query: str, 
        chunks: List[Chunk], 
        api_data: Optional[Dict[str, Any]] = None,
        route: str = "RAG_ONLY"
    ) -> AnswerResult:
        """
        Generates an answer based on retrieved chunks and optional API data.
        """
        if not chunks and not api_data:
            return AnswerResult(
                answer="No relevant documents or data found for this query.",
                sources=[],
                safety_warning=False,
                route_used=route
            )

        try:
            # 1. Build context
            context = self.build_context(chunks)

            # 2. Build API section
            api_section = ""
            if api_data:
                api_section = API_DATA_SECTION_TEMPLATE.format(
                    api_data=json.dumps(api_data, indent=2)
                )

            # 3. Format prompt
            prompt = ANSWER_PROMPT.format(
                context=context,
                api_data_section=api_section,
                query=query
            )

            # 4. Call LLM
            messages = [
                SystemMessage(content="You are an industrial maintenance assistant."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            answer_text = response.content

            # 5. Check for high risk
            has_high_risk = any(c.metadata.get("risk_level") == "high" for c in chunks)
            
            # A3: Append safety warning if high risk
            if has_high_risk and SAFETY_WARNING_BLOCK.strip() not in answer_text:
                answer_text = answer_text.strip() + "\n\n" + SAFETY_WARNING_BLOCK.strip()

            # 6. Build citations
            sources = [self.build_source_citation(c, i + 1) for i, c in enumerate(chunks)]

            return AnswerResult(
                answer=answer_text,
                sources=sources,
                safety_warning=has_high_risk,
                route_used=route
            )

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            # A9: Fallback message
            fallback_answer = "Unable to generate a detailed answer. Please check the following sources directly."
            sources = [self.build_source_citation(c, i + 1) for i, c in enumerate(chunks)]
            return AnswerResult(
                answer=fallback_answer,
                sources=sources,
                safety_warning=any(c.metadata.get("risk_level") == "high" for c in chunks),
                route_used=route
            )

    def build_context(self, chunks: List[Chunk]) -> str:
        """
        Format selected chunks into a structured context block (6.1).
        """
        context_parts = []
        for i, chunk in enumerate(chunks):
            meta = chunk.metadata
            license_tag = f" [{meta.get('license', 'internal')}]"
            if meta.get("license") == "restricted":
                license_tag = " [restricted — internal use only]"
            
            context_parts.append(
                f"[SOURCE {i+1}: {meta.get('title', 'Unknown')}\n"
                f" Organization: {meta.get('organization', 'Unknown')}\n"
                f" Authority: {meta.get('authority_level', 'Unknown')}\n"
                f" Domain: {meta.get('domain', 'Unknown')} / {meta.get('subdomain', 'Unknown')}\n"
                f" Risk Level: {meta.get('risk_level', 'Unknown')}\n"
                f" License:{license_tag}]\n"
                f"{chunk.text}"
            )
        return "\n\n---\n\n".join(context_parts)

    def build_source_citation(self, chunk: Chunk, source_number: int) -> SourceCitation:
        """
        Creates a formatted SourceCitation from chunk metadata (6.4).
        """
        meta = chunk.metadata
        return SourceCitation(
            source_number=source_number,
            doc_id=meta.get("doc_id", "Unknown"),
            title=meta.get("title", "Unknown"),
            organization=meta.get("organization", "Unknown"),
            authority_level=meta.get("authority_level", "Unknown"),
            domain=meta.get("domain", "Unknown"),
            version=meta.get("version", "N/A"),
            license=meta.get("license", "internal"),
            retrieved_date=meta.get("retrieved_date", "")
        )
