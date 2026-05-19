import json
import logging
import re
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from factory_agent.config import Settings, get_settings
from factory_agent.llm import build_rag_answer_chat_model
from factory_agent.rag.schemas import Chunk, SourceCitation, AnswerResult
from factory_agent.rag.source_metadata import normalize_source_locator, sanitize_rag_answer_text

logger = logging.getLogger(__name__)

SOURCE_SUPPORT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "or",
    "the",
    "their",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}

ANSWER_PROMPT = """
You are eMAS Assistant, an expert in industrial maintenance, safety, and operations.

Answer the user's question using ONLY the provided context. Do not use prior knowledge.
If the context does not contain enough information to answer, say so clearly.

Rules:
- Be concise and direct
- Use numbered steps for procedures
- Cite source numbers using superscript format like [^1] after each claim
- Do not include any safety warnings or "Safety Warning:" text in this answer; a separate advisory block will be handled by the system.
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
:::safety
**SAFETY WARNING**: This topic involves high-risk procedures.
Always follow your site's approved SOP, obtain required permits, and consult your safety officer before proceeding.
:::
"""

class AnswerGenerator:
    """
    Implements Phase 4 — Answer Generation.
    Builds context, calls LLM to generate answer, and formats source metadata/safety data.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.llm = build_rag_answer_chat_model(self.settings)

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

        # Clean metadata for all chunks
        for chunk in chunks:
            chunk.metadata = self._clean_metadata(chunk.metadata)

        try:
            # Identify unique documents and map each chunk to a document-level source number
            doc_id_to_num = {}
            doc_order = []
            doc_chunks: dict[str, list[Chunk]] = {}
            chunk_source_numbers = []

            for chunk in chunks:
                # Use doc_id if available, fallback to title
                d_id = chunk.metadata.get("doc_id") or chunk.metadata.get("title") or "Unknown"
                if d_id not in doc_id_to_num:
                    new_num = len(doc_order) + 1
                    doc_id_to_num[d_id] = new_num
                    doc_order.append(d_id)
                    doc_chunks[d_id] = []
                doc_chunks[d_id].append(chunk)
                
                chunk_source_numbers.append(doc_id_to_num[d_id])

            # 1. Build context with document-level source numbers
            context = self.build_context(chunks, chunk_source_numbers)

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
            answer_text = sanitize_rag_answer_text(response.content)

            # 5. Check for high risk
            has_high_risk = any(c.metadata.get("risk_level") == "high" for c in chunks)
            
            safety_text = None
            if has_high_risk:
                safety_text = "This topic involves high-risk industrial procedures. Always follow your site's approved SOP, obtain required permits, and consult your safety officer before proceeding."

            # 6. Build citations (one per unique document)
            source_chunks = [
                self._select_representative_source_chunk(
                    query=query,
                    answer=answer_text,
                    chunks=doc_chunks[d_id],
                )
                for d_id in doc_order
            ]
            sources = [
                self.build_source_citation(c, i + 1, query=query, answer=answer_text)
                for i, c in enumerate(source_chunks)
            ]
            
            logger.info(f"Generated {len(sources)} sources for query. Top source: {sources[0].title if sources else 'None'}")
            if sources:
                logger.debug(f"Source 1 details: {sources[0].model_dump()}")

            return AnswerResult(
                answer=answer_text,
                sources=sources,
                safety_warning=has_high_risk,
                safety_content=safety_text,
                route_used=route
            )

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            # A9: Fallback message
            fallback_answer = "Unable to generate a detailed answer. Please check the following sources directly."
            
            # Recalculate unique docs for fallback
            doc_order = []
            doc_chunks: dict[str, list[Chunk]] = {}
            for chunk in chunks:
                d_id = chunk.metadata.get("doc_id") or chunk.metadata.get("title") or "Unknown"
                if d_id not in doc_chunks:
                    doc_order.append(d_id)
                    doc_chunks[d_id] = []
                doc_chunks[d_id].append(chunk)

            source_chunks = [
                self._select_representative_source_chunk(
                    query=query,
                    answer=fallback_answer,
                    chunks=doc_chunks[d_id],
                )
                for d_id in doc_order
            ]
            sources = [
                self.build_source_citation(c, i + 1, query=query, answer=fallback_answer)
                for i, c in enumerate(source_chunks)
            ]
            has_high_risk = any(c.metadata.get("risk_level") == "high" for c in chunks)
            return AnswerResult(
                answer=fallback_answer,
                sources=sources,
                safety_warning=has_high_risk,
                safety_content="Safety data may be relevant but could not be fully processed." if has_high_risk else None,
                route_used=route
            )

    def build_context(self, chunks: List[Chunk], source_numbers: Optional[List[int]] = None) -> str:
        """
        Format selected chunks into a structured context block (6.1).
        Uses provided source_numbers to ensure chunks from the same doc share a citation ID.
        """
        if source_numbers is None:
            source_numbers = list(range(1, len(chunks) + 1))
        context_parts = []
        for chunk, src_num in zip(chunks, source_numbers):
            meta = chunk.metadata
            license_tag = f" [{meta.get('license', 'internal')}]"
            if meta.get("license") == "restricted":
                license_tag = " [restricted — internal use only]"
            
            context_parts.append(
                f"[SOURCE {src_num}: {meta.get('title', 'Unknown')}\n"
                f" Organization: {meta.get('organization', 'Unknown')}\n"
                f" Authority: {meta.get('authority_level', 'Unknown')}\n"
                f" Domain: {meta.get('domain', 'Unknown')} / {meta.get('subdomain', 'Unknown')}\n"
                f" Risk Level: {meta.get('risk_level', 'Unknown')}\n"
                f" License:{license_tag}]\n"
                f"{chunk.text}"
            )
        return "\n\n---\n\n".join(context_parts)

    def build_source_citation(
        self,
        chunk: Chunk,
        source_number: int,
        *,
        query: str = "",
        answer: str = "",
    ) -> SourceCitation:
        """
        Creates a formatted SourceCitation from chunk metadata (6.4).
        """
        meta = chunk.metadata
        focused_snippet = self._focused_source_snippet(query=query, answer=answer, chunk=chunk)
        locator_payload = {
            **meta,
            "chunk_id": chunk.chunk_id,
            "snippet": focused_snippet or chunk.text,
        }
        if focused_snippet:
            locator_payload["text_search"] = focused_snippet
        locator = normalize_source_locator(
            locator_payload,
            source_number - 1,
        )
        return SourceCitation(
            source_id=locator["source_id"],
            source_number=source_number,
            doc_id=locator["doc_id"],
            chunk_id=locator["chunk_id"],
            title=locator["title"],
            organization=locator["organization"],
            snippet=locator["snippet"],
            authority_level=meta.get("authority_level", "Unknown"),
            domain=meta.get("domain", "Unknown"),
            version=meta.get("version", "N/A"),
            license=meta.get("license", "internal"),
            retrieved_date=meta.get("retrieved_date", ""),
            page=locator.get("page"),
            pdf_url=locator.get("pdf_url"),
            page_label=locator.get("page_label"),
            bbox=locator.get("bbox"),
            char_range=locator.get("char_range"),
            text_search=locator.get("text_search"),
        )

    def _select_representative_source_chunk(self, *, query: str, answer: str, chunks: List[Chunk]) -> Chunk:
        """Pick the chunk that best supports the answer for a document-level citation."""
        if not chunks:
            raise ValueError("Cannot select a source chunk from an empty chunk list")
        return max(
            enumerate(chunks),
            key=lambda item: (
                self._source_support_score(query=query, answer=answer, chunk=item[1]),
                -item[0],
            ),
        )[1]

    def _source_support_score(self, *, query: str, answer: str, chunk: Chunk) -> float:
        text = f"{chunk.text} {chunk.metadata.get('snippet', '')} {chunk.metadata.get('text_search', '')}".lower()
        query_tokens = _support_tokens(query)
        answer_tokens = _support_tokens(answer)
        text_tokens = set(_support_tokens(text))

        score = 0.0
        score += 2.0 * len(query_tokens & text_tokens)
        score += 1.0 * len(answer_tokens & text_tokens)

        query_lower = (query or "").lower()
        if "notif" in query_lower:
            if any(term in text for term in ("notify", "notification", "know", "informed", "aware", "assure")):
                score += 4.0
            if "employee" in text:
                score += 3.0
        if "reenerg" in query_lower:
            if "reenerg" in text:
                score += 8.0
            if "remov" in text and "device" in text:
                score += 5.0
            if "employee" in text and any(term in text for term in ("know", "assure", "notify", "informed", "aware")):
                score += 5.0

        for phrase in _support_phrases(query):
            if phrase in text:
                score += 3.0
        return score

    def _focused_source_snippet(self, *, query: str, answer: str, chunk: Chunk) -> str:
        sentences = _evidence_sentences(chunk.text)
        if not sentences:
            return ""
        if len(sentences) == 1:
            return sentences[0]
        query_lower = (query or "").lower()
        answer_lower = (answer or "").lower()
        query_tokens = _support_tokens(query)
        answer_tokens = _support_tokens(answer)

        def score(sentence: str) -> float:
            sentence_lower = sentence.lower()
            sentence_tokens = _support_tokens(sentence)
            value = 2.0 * len(query_tokens & sentence_tokens)
            value += len(answer_tokens & sentence_tokens)
            if "reenerg" in query_lower and "reenerg" in sentence_lower:
                value += 10.0
            if "notif" in query_lower or "employee" in answer_lower:
                if "employee" in sentence_lower:
                    value += 4.0
                if any(term in sentence_lower for term in ("know", "assure", "notify", "informed", "aware")):
                    value += 4.0
            if "remov" in sentence_lower and "device" in sentence_lower:
                value += 4.0
            return value

        best_index, best_sentence = max(
            enumerate(sentences),
            key=lambda item: (score(item[1]), -item[0]),
        )
        if score(best_sentence) <= 0:
            return sentences[0]
        excerpt = best_sentence
        next_sentence = sentences[best_index + 1] if best_index + 1 < len(sentences) else ""
        if next_sentence and len(excerpt) + len(next_sentence) + 1 <= 320:
            excerpt = f"{excerpt} {next_sentence}"
        return excerpt


def _support_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", (text or "").lower()):
        token = _support_stem(raw)
        if len(token) < 3 or token in SOURCE_SUPPORT_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _support_stem(token: str) -> str:
    if token.startswith("reenerg"):
        return "reenerg"
    if token.startswith("notif"):
        return "notif"
    if token.startswith("remov"):
        return "remov"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def _support_phrases(text: str) -> set[str]:
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if word not in SOURCE_SUPPORT_STOPWORDS
    ]
    phrases: set[str] = set()
    for size in (2, 3, 4):
        for index in range(0, max(0, len(words) - size + 1)):
            phrases.add(" ".join(words[index : index + size]))
    return phrases


def _evidence_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    normalized = re.sub(r"^\[Section:[^\]]+\]\s*", "", normalized)
    sentences = [
        sentence.strip(" ;")
        for sentence in re.split(r"(?<=[.!?])\s+|(?<=\))\s+(?=[A-Z])", normalized)
        if sentence.strip(" ;")
    ]
    return sentences or [normalized]
