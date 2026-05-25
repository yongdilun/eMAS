import json
import logging
import re
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage
from factory_agent.config import Settings, get_settings
from factory_agent.llm import build_rag_answer_chat_model
from factory_agent.rag.answer_contract import (
    validate_knowledge_answer,
)
from factory_agent.rag.schemas import Chunk, SourceCitation, AnswerResult
from factory_agent.rag.source_metadata import (
    insufficient_context_answer,
    is_insufficient_context_answer,
    normalize_source_locator,
    sanitize_rag_answer_text,
    snippet_from_text,
)

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

LIVE_SAFETY_BOUNDARY_RE = re.compile(
    r"\b(live|current|right now|today|safe to start|start now|operate now|energiz(?:e|ing)? now|"
    r"reenergiz(?:e|ing)?|locked[- ]out|permission|permit)\b",
    re.IGNORECASE,
)
SAFETY_DOMAIN_RE = re.compile(r"\b(osha|lockout|tagout|loto|guard|machine|press|hazard|energy)\b", re.IGNORECASE)
COMPLIANCE_BOUNDARY_RE = re.compile(
    r"\b(certif|compliant|compliance proof|approved|approval|secure|security proof|vendor|buy|purchase)\b",
    re.IGNORECASE,
)

ANSWER_PROMPT = """
You are eMAS Assistant, an expert in industrial maintenance, safety, and operations.

### Task
Answer the user's question using ONLY the provided context and source numbers.
Do not use prior knowledge. Do not infer beyond what the context states.
If the context does not prove the answer, respond exactly with:
{insufficient_answer}

### Citation Contract
- Use citation markers exactly like [^1], [^2], etc.
- Use only source numbers that appear in the context.
- Cite coherent answer groups, not every sentence.
- Group adjacent sentences or related procedure steps under one citation marker when the same source supports them.
- Prefer 1 citation marker per paragraph or per 2-4 related procedure steps; repeat a marker only when the support source changes or a separate critical claim needs its own evidence.
- For procedures, output a numbered list and keep grouped citations at natural breakpoints.
- Start procedure answers directly at step 1 when possible. If a brief lead-in is necessary, make it introduce the numbered list and cite the whole lead-in plus list as one grouped procedure block.
- Do not output an incomplete numbered item such as a bare "3" or "3.".
- Do not scatter the same citation after every sentence when one grouped citation covers the paragraph or step group.
- Do not output [SOURCE 1], source titles, footnote definitions, or a bibliography.
- Do not include uncited introductions, summaries, conclusions, or safety warnings.

### Evidence Use
- If relevant evidence is split across multiple source chunks, synthesize the chunks into one cited answer instead of refusing.
- If a source section title, page, or heading directly matches the question, treat that as strong evidence and answer from the supporting body text.
- For section summaries or multi-part questions, cover every major dimension that the retrieved evidence supports, including purpose, scope, hierarchy, relationships, limitations, and named items.
- For list questions that ask for a specific number of items, include all supported items and preserve visible item labels or headings when the context provides them.
- For comparison questions, define each named concept separately before explaining the difference or relationship.
- For safety procedures, answer from the retrieved procedure evidence when it exists, include every required procedural category the evidence states, and rely on the structured safety warning outside the answer.
- For OSHA or other static safety checklist questions that ask what checks, areas, items, or training requirements are listed, treat the question as descriptive document recall. Answer from the checklist evidence with citations; do not refuse unless the user asks for live permission, live machine status, current compliance certification, or operational authorization.

### Output Format
For procedures:
1. <step proven by context>.
2. <step proven by context>.
3. <step proven by context>.[^N]

For non-procedures:
<direct answer paragraph with grouped citation>.[^N]

### Context
{context}

{api_data_section}

### User Question
{query}

### Final Checks Before Answering
- Every factual paragraph or procedure group has a valid [^N] citation.
- Adjacent facts supported by the same source are grouped under one marker.
- No numbered item is left blank or cut off.
- Unsupported or partially supported claims are omitted.
- If no supported answer remains, output exactly the insufficient-context sentence.

### Answer
"""

ANSWER_REPAIR_PROMPT = """
You are eMAS Assistant, an expert in industrial maintenance, safety, and operations.

The previous draft could not be accepted.
Validation reason: {validation_reason}

Rewrite the answer using ONLY the provided context and source numbers.
The retrieved context has relevant evidence for the user's question, so do not output the insufficient-context sentence unless no cited, supported answer can be produced.

### Repair Rules
- Preserve the citation contract: every factual paragraph or grouped procedure block must cite a valid marker like [^1].
- Use only source numbers shown in the context.
- Do not add uncited safety warnings, conclusions, source titles, footnote definitions, or bibliographies.
- If evidence is split across chunks from the same source, synthesize it into a complete cited answer.
- For section summaries, list/group questions, comparisons, and procedures, include all supported dimensions and required categories.
- If the user asks for a specific number of listed items, include that many supported items and preserve item labels or headings.
- For OSHA or other static checklist questions, answer the listed checks descriptively from the document. Keep live-action permission, machine status, compliance certification, and unsupported current-state claims out of the answer.

### Context
{context}

{api_data_section}

### User Question
{query}

### Previous Draft
{answer}

### Final Answer
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
                answer=insufficient_context_answer(has_sources=False, query=query),
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
                query=query,
                insufficient_answer=insufficient_context_answer(has_sources=bool(chunks), query=query),
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
            sources = self._build_sources_for_answer(
                query=query,
                answer=answer_text,
                doc_order=doc_order,
                doc_chunks=doc_chunks,
            )
            answer_text, sources, generation_validation = self._validate_answer(
                query=query,
                context=context,
                api_data_section=api_section,
                answer=answer_text,
                sources=sources,
                doc_order=doc_order,
                doc_chunks=doc_chunks,
            )
            
            logger.info(f"Generated {len(sources)} sources for query. Top source: {sources[0].title if sources else 'None'}")
            if sources:
                logger.debug(f"Source 1 details: {sources[0].model_dump()}")

            return AnswerResult(
                answer=answer_text,
                sources=sources,
                safety_warning=has_high_risk,
                safety_content=safety_text,
                route_used=route,
                metadata={
                    "citation_support": self._build_citation_support_metadata(
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                    ),
                    "evidence_chunks": self._build_evidence_chunk_metadata(
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                    ),
                    "generation_validation": generation_validation,
                },
            )

        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            fallback_answer = insufficient_context_answer(has_sources=bool(chunks), query=query)
            
            # Recalculate unique docs for fallback
            doc_order = []
            doc_chunks: dict[str, list[Chunk]] = {}
            for chunk in chunks:
                d_id = chunk.metadata.get("doc_id") or chunk.metadata.get("title") or "Unknown"
                if d_id not in doc_chunks:
                    doc_order.append(d_id)
                    doc_chunks[d_id] = []
                doc_chunks[d_id].append(chunk)

            sources = self._build_sources_for_answer(
                query=query,
                answer=fallback_answer,
                doc_order=doc_order,
                doc_chunks=doc_chunks,
            )
            has_high_risk = any(c.metadata.get("risk_level") == "high" for c in chunks)
            return AnswerResult(
                answer=fallback_answer,
                sources=sources,
                safety_warning=has_high_risk,
                safety_content="Safety data may be relevant but could not be fully processed." if has_high_risk else None,
                route_used=route,
                metadata={
                    "citation_support": self._build_citation_support_metadata(
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                    ),
                    "evidence_chunks": self._build_evidence_chunk_metadata(
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                    ),
                    "generation_validation": {
                        "initial_valid": False,
                        "initial_reason": "generation_exception",
                        "initial_insufficient_context": False,
                        "repair_attempted": False,
                        "repair_reason": None,
                        "repair_valid": False,
                        "repair_failure_reason": str(e),
                    },
                },
            )

    def _build_sources_for_answer(
        self,
        *,
        query: str,
        answer: str,
        doc_order: list[str],
        doc_chunks: dict[str, list[Chunk]],
    ) -> list[SourceCitation]:
        source_chunks = [
            self._select_representative_source_chunk(
                query=query,
                answer=answer,
                chunks=doc_chunks[d_id],
            )
            for d_id in doc_order
        ]
        return [
            self.build_source_citation(
                c,
                i + 1,
                query=query,
                answer=answer,
                support_chunks=doc_chunks[doc_order[i]],
            )
            for i, c in enumerate(source_chunks)
        ]

    def _validate_answer(
        self,
        *,
        query: str,
        context: str,
        api_data_section: str,
        answer: str,
        sources: list[SourceCitation],
        doc_order: list[str],
        doc_chunks: dict[str, list[Chunk]],
    ) -> tuple[str, list[SourceCitation], dict[str, Any]]:
        if api_data_section.strip():
            # Mixed live-data answers can contain operational facts that are not document source claims.
            return sanitize_rag_answer_text(answer), sources, {
                "initial_valid": True,
                "initial_reason": "api_data_skip",
                "initial_insufficient_context": False,
                "repair_attempted": False,
                "repair_reason": None,
                "repair_valid": False,
                "repair_failure_reason": None,
            }
        validation = validate_knowledge_answer(answer, sources)
        metadata = {
            "initial_valid": validation.valid,
            "initial_reason": validation.reason,
            "initial_insufficient_context": validation.insufficient_context,
            "repair_attempted": False,
            "repair_reason": None,
            "repair_valid": False,
            "repair_failure_reason": None,
        }
        if validation.valid and not validation.insufficient_context:
            completeness_reason = self._supported_answer_completeness_issue(
                query=query,
                answer=validation.answer,
                doc_chunks=doc_chunks,
            )
            if not completeness_reason:
                return validation.answer, sources, metadata
        else:
            completeness_reason = None

        repair_reason = None
        if completeness_reason:
            if self._should_repair_generation(query=query, doc_chunks=doc_chunks):
                repair_reason = completeness_reason
        elif validation.insufficient_context:
            if self._should_repair_generation(query=query, doc_chunks=doc_chunks):
                repair_reason = "insufficient_context_with_matching_evidence"
        elif self._should_repair_generation(query=query, doc_chunks=doc_chunks):
            repair_reason = validation.reason or "invalid_answer_with_matching_evidence"

        if repair_reason:
            metadata["repair_attempted"] = True
            metadata["repair_reason"] = repair_reason
            repaired_answer = self._repair_answer(
                query=query,
                context=context,
                api_data_section=api_data_section,
                answer=answer,
                validation_reason=repair_reason,
            )
            repaired_sources = self._build_sources_for_answer(
                query=query,
                answer=repaired_answer,
                doc_order=doc_order,
                doc_chunks=doc_chunks,
            )
            repaired_validation = validate_knowledge_answer(repaired_answer, repaired_sources)
            if not repaired_validation.valid:
                citation_repaired_answer = self._repair_citations(
                    query=query,
                    answer=repaired_answer,
                    sources=repaired_sources,
                )
                if citation_repaired_answer != repaired_answer:
                    repaired_answer = citation_repaired_answer
                    repaired_sources = self._build_sources_for_answer(
                        query=query,
                        answer=repaired_answer,
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                    )
                    repaired_validation = validate_knowledge_answer(repaired_answer, repaired_sources)
            metadata["repair_valid"] = repaired_validation.valid and not repaired_validation.insufficient_context
            metadata["repair_failure_reason"] = repaired_validation.reason
            if repaired_validation.valid and not repaired_validation.insufficient_context:
                return repaired_validation.answer, repaired_sources, metadata

        if validation.valid:
            return validation.answer, sources, metadata
        return insufficient_context_answer(has_sources=bool(sources), query=query), sources, metadata

    def _supported_answer_completeness_issue(
        self,
        *,
        query: str,
        answer: str,
        doc_chunks: dict[str, list[Chunk]],
    ) -> str | None:
        requested_count = _requested_item_count(query)
        if requested_count is None:
            return None
        observed_count = _enumerated_answer_item_count(answer)
        if observed_count is None or observed_count >= requested_count:
            return None
        if not _has_matching_retrieved_evidence(query=query, doc_chunks=doc_chunks):
            return None
        return f"listed_answer_has_{observed_count}_of_{requested_count}_requested_items"

    def _repair_answer(
        self,
        *,
        query: str,
        context: str,
        api_data_section: str,
        answer: str,
        validation_reason: str,
    ) -> str:
        prompt = ANSWER_REPAIR_PROMPT.format(
            context=context,
            api_data_section=api_data_section,
            query=query,
            answer=sanitize_rag_answer_text(answer),
            validation_reason=validation_reason,
        )
        messages = [
            SystemMessage(content="You are an industrial maintenance assistant."),
            HumanMessage(content=prompt),
        ]
        response = self.llm.invoke(messages)
        return sanitize_rag_answer_text(response.content)

    def _should_repair_generation(self, *, query: str, doc_chunks: dict[str, list[Chunk]]) -> bool:
        if _is_boundary_query(query):
            return False
        return _has_matching_retrieved_evidence(query=query, doc_chunks=doc_chunks)

    def _repair_citations(self, *, query: str, answer: str, sources: list[SourceCitation]) -> str:
        clean_answer = sanitize_rag_answer_text(answer)
        if not sources or not clean_answer or is_insufficient_context_answer(clean_answer):
            return clean_answer
        available_numbers = {str(source.source_number or index) for index, source in enumerate(sources, start=1)}

        def marker_for(number: str) -> str:
            return f"[^{number}]"

        def normalize_marker(match: re.Match[str]) -> str:
            number = match.group(1)
            if len(sources) == 1:
                return marker_for(next(iter(available_numbers)))
            if number in available_numbers:
                return marker_for(number)
            return match.group(0)

        normalized_answer = re.sub(r"\[\^?(\d+)\]", normalize_marker, clean_answer)
        changed = normalized_answer != clean_answer
        clean_answer = normalized_answer
        cited_numbers = [
            match.group(1)
            for match in re.finditer(r"\[\^?(\d+)\]", clean_answer)
            if match.group(1) in available_numbers
        ]
        default_marker = None
        if len(sources) == 1:
            default_marker = marker_for(next(iter(available_numbers)))
        elif len(set(cited_numbers)) == 1:
            default_marker = marker_for(cited_numbers[0])
        elif not cited_numbers:
            best_number = self._best_source_number_for_uncited_answer(
                query=query,
                answer=clean_answer,
                sources=sources,
            )
            if best_number is not None:
                default_marker = marker_for(str(best_number))

        def has_valid_citation(line: str) -> bool:
            cited = re.findall(r"\[\^?(\d+)\]", line)
            return any(number in available_numbers for number in cited)

        def last_valid_marker(line: str) -> str | None:
            for number in reversed(re.findall(r"\[\^?(\d+)\]", line)):
                if number in available_numbers:
                    return marker_for(number)
            return None

        def has_uncited_tail(line: str) -> bool:
            matches = list(re.finditer(r"\[\^?\d+\]", line))
            if not matches:
                return False
            tail = line[matches[-1].end() :].strip()
            tail = tail.lstrip(" \t\r\n.,;:!?")
            return len(re.findall(r"[A-Za-z0-9]+", tail)) >= 4

        repaired_lines: list[str] = []
        for line in clean_answer.splitlines():
            stripped = line.rstrip()
            if not stripped:
                repaired_lines.append(line)
                continue
            if has_valid_citation(stripped):
                if has_uncited_tail(stripped):
                    repaired_lines.append(f"{stripped} {last_valid_marker(stripped) or default_marker or ''}".rstrip())
                    changed = True
                else:
                    repaired_lines.append(stripped)
                continue
            if len(re.findall(r"[A-Za-z0-9]+", stripped)) < 4:
                repaired_lines.append(stripped)
                continue
            if default_marker:
                repaired_lines.append(f"{stripped} {default_marker}")
                changed = True
                continue
            repaired_lines.append(stripped)
        return "\n".join(repaired_lines).strip() if changed else clean_answer

    def _best_source_number_for_uncited_answer(
        self,
        *,
        query: str,
        answer: str,
        sources: list[SourceCitation],
    ) -> int | None:
        answer_terms = _support_tokens(f"{query} {answer}")
        if not answer_terms:
            return None

        best_number: int | None = None
        best_score = 0.0
        for index, source in enumerate(sources, start=1):
            source_number = source.source_number or index
            source_text_parts = [
                source.doc_id,
                source.title,
                source.snippet,
                source.section_title,
                " ".join(source.supporting_sections or []),
            ]
            for evidence in source.evidence_snippets or []:
                if isinstance(evidence, dict):
                    source_text_parts.append(str(evidence.get("snippet") or ""))
                    source_text_parts.append(str(evidence.get("section_title") or ""))
            source_terms = _support_tokens(" ".join(str(part or "") for part in source_text_parts))
            if not source_terms:
                continue
            score = len(answer_terms & source_terms) / max(1, len(answer_terms))
            if score > best_score:
                best_score = score
                best_number = source_number

        return best_number if best_score >= 0.12 else None

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
        support_chunks: list[Chunk] | None = None,
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
            page_start=meta.get("page_start"),
            page_end=meta.get("page_end"),
            section_title=meta.get("section_title"),
            section_path=meta.get("section_path"),
            pdf_url=locator.get("pdf_url"),
            page_label=locator.get("page_label"),
            bbox=locator.get("bbox"),
            char_range=locator.get("char_range"),
            text_search=locator.get("text_search"),
            supporting_chunk_ids=self._supporting_chunk_ids(support_chunks or [chunk]),
            supporting_pages=self._supporting_pages(support_chunks or [chunk]),
            supporting_sections=self._supporting_sections(support_chunks or [chunk]),
            evidence_snippets=self._evidence_snippets(support_chunks or [chunk], source_number=source_number),
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
        section_path = chunk.metadata.get("section_path")
        if isinstance(section_path, list):
            section_path = " > ".join(str(part) for part in section_path if part)
        text = (
            f"{chunk.text} {chunk.metadata.get('snippet', '')} {chunk.metadata.get('text_search', '')} "
            f"{chunk.metadata.get('section_title', '')} {section_path or ''}"
        ).lower()
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

    def _build_citation_support_metadata(
        self,
        *,
        doc_order: list[str],
        doc_chunks: dict[str, list[Chunk]],
    ) -> list[dict[str, Any]]:
        support: list[dict[str, Any]] = []
        for index, doc_id in enumerate(doc_order, start=1):
            chunks = doc_chunks.get(doc_id) or []
            support.append(
                {
                    "source_number": index,
                    "doc_id": doc_id,
                    "supporting_chunk_ids": self._supporting_chunk_ids(chunks),
                    "supporting_pages": self._supporting_pages(chunks),
                    "supporting_sections": self._supporting_sections(chunks),
                    "evidence_snippets": self._evidence_snippets(chunks, source_number=index),
                }
            )
        return support

    def _build_evidence_chunk_metadata(
        self,
        *,
        doc_order: list[str],
        doc_chunks: dict[str, list[Chunk]],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for index, doc_id in enumerate(doc_order, start=1):
            for chunk in doc_chunks.get(doc_id) or []:
                evidence.append(self._chunk_evidence(chunk, source_number=index))
        return evidence

    def _chunk_evidence(self, chunk: Chunk, *, source_number: int) -> dict[str, Any]:
        metadata = chunk.metadata
        return {
            "source_number": source_number,
            "doc_id": metadata.get("doc_id"),
            "chunk_id": chunk.chunk_id,
            "page": metadata.get("page"),
            "page_start": metadata.get("page_start"),
            "page_end": metadata.get("page_end"),
            "section_title": metadata.get("section_title"),
            "section_path": metadata.get("section_path"),
            "context_builder": metadata.get("context_builder"),
            "context_segment_id": metadata.get("context_segment_id"),
            "seed_chunk_id": metadata.get("seed_chunk_id"),
            "child_chunk_ids": metadata.get("child_chunk_ids"),
            "segment_chunk_ids": metadata.get("segment_chunk_ids"),
            "snippet": snippet_from_text(chunk.text, limit=420),
        }

    def _supporting_chunk_ids(self, chunks: list[Chunk]) -> list[str]:
        return list(dict.fromkeys(chunk.chunk_id for chunk in chunks if chunk.chunk_id))

    def _supporting_pages(self, chunks: list[Chunk]) -> list[int]:
        pages: list[int] = []
        for chunk in chunks:
            meta = chunk.metadata
            for key in ("page", "page_start", "page_end"):
                value = _metadata_int(meta.get(key))
                if value is not None:
                    pages.append(value)
        return sorted(set(pages))

    def _supporting_sections(self, chunks: list[Chunk]) -> list[str]:
        sections: list[str] = []
        for chunk in chunks:
            meta = chunk.metadata
            title = str(meta.get("section_title") or "").strip()
            if title:
                sections.append(title)
            section_path = meta.get("section_path")
            if isinstance(section_path, list):
                section_path = " > ".join(str(part) for part in section_path if part)
            section_path = str(section_path or "").strip()
            if section_path:
                sections.append(section_path)
        return list(dict.fromkeys(sections))

    def _evidence_snippets(self, chunks: list[Chunk], *, source_number: int) -> list[dict[str, Any]]:
        return [self._chunk_evidence(chunk, source_number=source_number) for chunk in chunks]


def _support_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", (text or "").lower()):
        token = _support_stem(raw)
        if len(token) < 3 or token in SOURCE_SUPPORT_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _is_boundary_query(query: str) -> bool:
    text = query or ""
    if LIVE_SAFETY_BOUNDARY_RE.search(text) and SAFETY_DOMAIN_RE.search(text):
        return True
    return bool(COMPLIANCE_BOUNDARY_RE.search(text))


def _has_matching_retrieved_evidence(*, query: str, doc_chunks: dict[str, list[Chunk]]) -> bool:
    chunks = [chunk for chunks in doc_chunks.values() for chunk in chunks]
    if not chunks:
        return False

    query_tokens = _support_tokens(query)
    if not query_tokens:
        return True

    best_overlap = 0
    best_coverage = 0.0
    for chunk in chunks:
        metadata = chunk.metadata or {}
        section_path = metadata.get("section_path")
        if isinstance(section_path, list):
            section_path = " > ".join(str(part) for part in section_path if part)
        evidence_text = (
            f"{chunk.text} {metadata.get('snippet', '')} {metadata.get('text_search', '')} "
            f"{metadata.get('section_title', '')} {section_path or ''}"
        )
        evidence_tokens = _support_tokens(evidence_text)
        overlap = len(query_tokens & evidence_tokens)
        best_overlap = max(best_overlap, overlap)
        best_coverage = max(best_coverage, overlap / max(1, len(query_tokens)))
        if overlap >= 2 or best_coverage >= 0.5:
            return True

        evidence_lower = evidence_text.lower()
        if any(phrase in evidence_lower for phrase in _support_phrases(query)):
            return True

    return best_overlap >= 1 and len(query_tokens) <= 2


def _support_stem(token: str) -> str:
    if token.startswith("reenerg"):
        return "reenerg"
    if token.startswith("notif"):
        return "notif"
    if token.startswith("remov"):
        return "remov"
    if token.endswith("ces") and len(token) > 4:
        return token[:-1]
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


def _requested_item_count(query: str) -> int | None:
    text = (query or "").lower()
    if not re.search(r"\b(name|list|which|what|identify|enumerate)\b", text):
        return None
    word_counts = {
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    for word, count in word_counts.items():
        if re.search(rf"\b{word}\b", text):
            return count
    match = re.search(r"\b([2-9]|10)\b", text)
    if match:
        return int(match.group(1))
    return None


def _enumerated_answer_item_count(answer: str) -> int | None:
    lines = [line.strip() for line in re.split(r"[\r\n]+", answer or "") if line.strip()]
    if not lines:
        return None
    item_lines = [
        line
        for line in lines
        if re.match(r"^(?:[-*]\s+|\d+[\.)]\s+)", line)
    ]
    return len(item_lines) if item_lines else None


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


def _metadata_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
