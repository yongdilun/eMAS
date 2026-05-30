import json
import logging
import re
from dataclasses import dataclass
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
EXTRACTIVE_RECALL_STOPWORDS = {
    "according",
    "answer",
    "area",
    "check",
    "checked",
    "checklist",
    "document",
    "evidence",
    "information",
    "item",
    "list",
    "listed",
    "mention",
    "pull",
    "question",
    "readiness",
    "review",
    "source",
    "specific",
    "static",
}

LIVE_SAFETY_BOUNDARY_RE = re.compile(
    r"\b(live|current|right now|today|safe to start|start now|operate now|energiz(?:e|ing)? now|"
    r"reenergiz(?:e|ing)?|locked[- ]out|permission|permit)\b",
    re.IGNORECASE,
)
SAFETY_DOMAIN_RE = re.compile(r"\b(osha|lockout|tagout|loto|guard|machine|press|hazard|energy|safety)\b", re.IGNORECASE)
COMPLIANCE_BOUNDARY_RE = re.compile(
    r"\b(certif|compliant|compliance proof|approved|approval|secure|security proof|vendor|buy|purchase)\b",
    re.IGNORECASE,
)
CERTIFICATION_ACTION_RE = re.compile(
    r"\b(certif(?:y|ies|ied)|attest|approve|sign[- ]?off)\b",
    re.IGNORECASE,
)
COMPLIANCE_VERDICT_ACTION_RE = re.compile(
    r"\b(declare|confirm|prove)\b",
    re.IGNORECASE,
)
COMPLIANCE_STATEMENT_ACTION_RE = re.compile(
    r"\b(draft|write|produce|generate|say)\b",
    re.IGNORECASE,
)
COMPLIANCE_DECISION_TARGET_RE = re.compile(
    r"\b(compliant|compliance|meets? (?:osha|requirements?|standards?)|passed? (?:the )?"
    r"(?:checklist|audit)|secure|security|safe|approved|sign[- ]?off)\b",
    re.IGNORECASE,
)
COMPLIANCE_STATEMENT_OUTPUT_RE = re.compile(
    r"\b(compliance statement|certification statement|certification sentence|attestation|"
    r"declaration|sign[- ]?off(?: language| statement)?|approval (?:language|statement|sentence)|audit sign[- ]?off|"
    r"(?:statement|sentence|language)\b.{0,60}\b(?:compliant|compliance|approved|"
    r"passed?|meets?|secure|safe))\b",
    re.IGNORECASE,
)
CURRENT_STATE_PROOF_RE = re.compile(
    r"\b(today|current(?:ly)?|right now|live|this (?:machine|deployment|system|site|equipment)|"
    r"our|we|audit|passed)\b",
    re.IGNORECASE,
)
NEGATES_RETRIEVED_EVIDENCE_RE = re.compile(
    r"\b(?:no|none|not|does(?:n['’]?t| not)|do(?:n['’]?t| not)|lacks?|without)\b.{0,120}"
    r"\b(?:mention|listed?|questions?|items?|evidence|information|specific|support|prove)\b|"
    r"\bthere (?:is|are) no\b",
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
- Cite coherent non-procedure answer groups, not every sentence.
- For procedures, output a flat numbered list with one visible action per numbered step.
- For procedures, cite each numbered step with the source marker that proves that step, even when several steps use the same source.
- Do not nest a numbered list inside another numbered item.
- Start procedure answers directly at step 1 when possible. Omit broad lead-in text when the numbered steps already answer the question.
- Do not output an incomplete numbered item such as a bare "3" or "3.".
- Do not scatter the same citation after every sentence in non-procedure paragraphs when one grouped citation covers the paragraph.
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
- If the user asks you to certify, attest, declare, approve, sign off, confirm compliance, write compliance/sign-off language, say the user passed, or prove a current compliant/secure/safe state from static retrieved text, refuse that certification boundary. You may summarize what the retrieved checklist/manual evidence says, but clearly state that the answer cannot certify current compliance or replace qualified safety/compliance review.

### Output Format
For procedures:
1. <step proven by context>.[^N]
2. <step proven by context>.[^N]
3. <step proven by context>.[^N]

For non-procedures:
<direct answer paragraph with grouped citation>.[^N]

### Context
{context}

{api_data_section}

### User Question
{query}

### Final Checks Before Answering
 - Every factual paragraph has a valid [^N] citation.
- Every numbered procedure step has its own valid [^N] citation.
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
- Preserve the citation contract: every factual paragraph and every procedure step must cite a valid marker like [^1].
- Use only source numbers shown in the context.
- Do not add uncited safety warnings, conclusions, source titles, footnote definitions, or bibliographies.
- If evidence is split across chunks from the same source, synthesize it into a complete cited answer.
- For section summaries, list/group questions, comparisons, and procedures, include all supported dimensions and required categories.
- For procedures, output a flat numbered list and cite each step.
- If the user asks for a specific number of listed items, include that many supported items and preserve item labels or headings.
- For OSHA or other static checklist questions, answer the listed checks descriptively from the document. Keep live-action permission, machine status, compliance certification, and unsupported current-state claims out of the answer.
- If the user asks for certification, attestation, sign-off, approval, compliance language, or proof of a current compliant/secure/safe state, refuse that boundary instead of drafting the requested statement. It is acceptable to summarize retrieved evidence, but the final answer must say it cannot certify compliance or replace qualified review.

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

            has_high_risk = any(c.metadata.get("risk_level") == "high" for c in chunks)
            safety_text = None
            if has_high_risk:
                safety_text = "This topic involves high-risk industrial procedures. Always follow your site's approved SOP, obtain required permits, and consult your safety officer before proceeding."

            if not api_data and _requires_certification_boundary(query):
                answer_text = _certification_boundary_answer(query)
                sources = self._build_sources_for_answer(
                    query=query,
                    answer=answer_text,
                    doc_order=doc_order,
                    doc_chunks=doc_chunks,
                )
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
                        "generation_validation": {
                            "initial_valid": True,
                            "initial_reason": "certification_boundary_enforced",
                            "initial_insufficient_context": True,
                            "repair_attempted": False,
                            "repair_reason": None,
                            "repair_valid": False,
                            "repair_failure_reason": None,
                        },
                    },
                )

            procedure_evidence = None
            if not api_data:
                procedure_evidence = extract_explicit_procedure_evidence(
                    query=query,
                    doc_order=doc_order,
                    doc_chunks=doc_chunks,
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
            normalized_answer = _normalize_procedure_answer_format(query=query, answer=answer_text)
            if normalized_answer != answer_text:
                normalized_sources = self._build_sources_for_answer(
                    query=query,
                    answer=normalized_answer,
                    doc_order=doc_order,
                    doc_chunks=doc_chunks,
                )
                normalized_validation = validate_knowledge_answer(normalized_answer, normalized_sources)
                if normalized_validation.valid and not normalized_validation.insufficient_context:
                    answer_text = normalized_validation.answer
                    sources = normalized_sources
                    generation_validation["procedure_format_normalized"] = True
                else:
                    generation_validation["procedure_format_normalized"] = False
                    generation_validation["procedure_format_normalization_reason"] = normalized_validation.reason

            if procedure_evidence:
                if _procedure_answer_needs_evidence_repair(
                    query=query,
                    answer=answer_text,
                    procedure_evidence=procedure_evidence,
                ):
                    repaired_answer = procedure_evidence.to_answer()
                    repaired_sources = self._build_sources_for_answer(
                        query=query,
                        answer=repaired_answer,
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                        procedure_evidence=procedure_evidence,
                    )
                    repaired_validation = validate_knowledge_answer(repaired_answer, repaired_sources)
                    if repaired_validation.valid and not repaired_validation.insufficient_context:
                        answer_text = repaired_validation.answer
                        sources = repaired_sources
                        generation_validation["procedure_evidence_repaired"] = True
                        generation_validation["procedure_evidence_repair_reason"] = "llm_procedure_step_mismatch"
                        generation_validation["deterministic_procedure_answer"] = True
                        generation_validation["deterministic_procedure_reason"] = procedure_evidence.reason
                        generation_validation["deterministic_procedure_step_count"] = len(procedure_evidence.steps)
                    else:
                        generation_validation["procedure_evidence_repaired"] = False
                        generation_validation["procedure_evidence_repair_reason"] = repaired_validation.reason
                else:
                    sources = self._build_sources_for_answer(
                        query=query,
                        answer=answer_text,
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                        procedure_evidence=procedure_evidence,
                    )
                    generation_validation["procedure_evidence_attached"] = True
            
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
        procedure_evidence: "ProcedureEvidenceSet | None" = None,
    ) -> list[SourceCitation]:
        source_chunks = [
            self._select_representative_source_chunk(
                query=query,
                answer=answer,
                chunks=doc_chunks[d_id],
            )
            for d_id in doc_order
        ]
        sources = [
            self.build_source_citation(
                c,
                i + 1,
                query=query,
                answer=answer,
                support_chunks=doc_chunks[doc_order[i]],
            )
            for i, c in enumerate(source_chunks)
        ]
        if procedure_evidence:
            _attach_procedure_evidence_to_sources(sources, procedure_evidence)
        return sources

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
        completeness_reason = self._supported_answer_completeness_issue(
            query=query,
            answer=validation.answer or answer,
            doc_chunks=doc_chunks,
        )
        if validation.valid and not validation.insufficient_context:
            if not completeness_reason:
                return validation.answer, sources, metadata

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
                repaired_completeness_reason = self._supported_answer_completeness_issue(
                    query=query,
                    answer=repaired_validation.answer,
                    doc_chunks=doc_chunks,
                )
                if not repaired_completeness_reason:
                    if repair_reason == "answer_negates_matching_retrieved_evidence":
                        extractive_answer = _extractive_supported_recall_answer(
                            query=query,
                            doc_order=doc_order,
                            doc_chunks=doc_chunks,
                        )
                        if extractive_answer:
                            extractive_sources = self._build_sources_for_answer(
                                query=query,
                                answer=extractive_answer,
                                doc_order=doc_order,
                                doc_chunks=doc_chunks,
                            )
                            extractive_validation = validate_knowledge_answer(extractive_answer, extractive_sources)
                            if extractive_validation.valid and not extractive_validation.insufficient_context:
                                metadata["extractive_supported_answer"] = True
                                return extractive_validation.answer, extractive_sources, metadata
                    return repaired_validation.answer, repaired_sources, metadata
                metadata["repair_valid"] = False
                metadata["repair_failure_reason"] = repaired_completeness_reason
                augmented_answer = _augment_summary_answer_with_supported_facets(
                    query=query,
                    answer=repaired_validation.answer,
                    doc_order=doc_order,
                    doc_chunks=doc_chunks,
                )
                if augmented_answer:
                    augmented_sources = self._build_sources_for_answer(
                        query=query,
                        answer=augmented_answer,
                        doc_order=doc_order,
                        doc_chunks=doc_chunks,
                    )
                    augmented_validation = validate_knowledge_answer(augmented_answer, augmented_sources)
                    augmented_completeness_reason = self._supported_answer_completeness_issue(
                        query=query,
                        answer=augmented_validation.answer,
                        doc_chunks=doc_chunks,
                    )
                    if (
                        augmented_validation.valid
                        and not augmented_validation.insufficient_context
                        and not augmented_completeness_reason
                    ):
                        metadata["summary_facet_extract_augmented"] = True
                        metadata["repair_valid"] = True
                        metadata["repair_failure_reason"] = None
                        return augmented_validation.answer, augmented_sources, metadata

        if not _is_boundary_query(query):
            relationship_answer = _extractive_supported_relationship_answer(
                query=query,
                doc_order=doc_order,
                doc_chunks=doc_chunks,
            )
            if relationship_answer:
                relationship_sources = self._build_sources_for_answer(
                    query=query,
                    answer=relationship_answer,
                    doc_order=doc_order,
                    doc_chunks=doc_chunks,
                )
                relationship_validation = validate_knowledge_answer(relationship_answer, relationship_sources)
                if relationship_validation.valid and not relationship_validation.insufficient_context:
                    metadata["extractive_relationship_answer"] = True
                    return relationship_validation.answer, relationship_sources, metadata

            extractive_answer = _extractive_supported_recall_answer(
                query=query,
                doc_order=doc_order,
                doc_chunks=doc_chunks,
            )
            if extractive_answer:
                extractive_sources = self._build_sources_for_answer(
                    query=query,
                    answer=extractive_answer,
                    doc_order=doc_order,
                    doc_chunks=doc_chunks,
                )
                extractive_validation = validate_knowledge_answer(extractive_answer, extractive_sources)
                if extractive_validation.valid and not extractive_validation.insufficient_context:
                    metadata["extractive_supported_answer"] = True
                    return extractive_validation.answer, extractive_sources, metadata

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
        negated_evidence_reason = _negates_available_evidence_issue(
            query=query,
            answer=answer,
            doc_chunks=doc_chunks,
        )
        if negated_evidence_reason:
            return negated_evidence_reason

        summary_reason = _summary_breadth_completeness_issue(
            query=query,
            answer=answer,
            doc_chunks=doc_chunks,
        )
        if summary_reason:
            return summary_reason

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
            if default_marker and re.match(r"^\s*(?:[-*]\s+|\d+[\.)]\s+)", stripped):
                if not has_valid_citation(stripped):
                    repaired_lines.append(f"{stripped} {default_marker}")
                    changed = True
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
        answer_terms = _support_tokens(answer)
        if answer_terms:
            best_answer_item = max(
                enumerate(chunks),
                key=lambda item: (
                    self._answer_support_score(answer=answer, chunk=item[1]),
                    self._source_support_score(query=query, answer=answer, chunk=item[1]),
                    -item[0],
                ),
            )
            best_answer_chunk = best_answer_item[1]
            best_answer_score = self._answer_support_score(answer=answer, chunk=best_answer_chunk)
            if best_answer_score >= max(1, min(2, len(answer_terms))):
                return best_answer_chunk
        return max(
            enumerate(chunks),
            key=lambda item: (
                self._source_support_score(query=query, answer=answer, chunk=item[1]),
                -item[0],
            ),
        )[1]

    def _answer_support_score(self, *, answer: str, chunk: Chunk) -> float:
        text = (
            f"{chunk.text} {chunk.metadata.get('snippet', '')} {chunk.metadata.get('text_search', '')} "
            f"{chunk.metadata.get('section_title', '')}"
        ).lower()
        answer_terms = _support_tokens(answer)
        if not answer_terms:
            return 0.0
        text_terms = set(_support_tokens(text))
        score = float(len(answer_terms & text_terms))
        answer_phrases = _support_phrases(answer)
        for phrase in answer_phrases:
            if phrase in text:
                score += 3.0
        return score

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
        evidence = {
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
            "snippet": snippet_from_text(chunk.text, limit=1200),
        }
        for key in ("pdf_url", "page_label", "bbox", "char_range", "text_search"):
            if metadata.get(key) not in (None, "", [], {}):
                evidence[key] = metadata.get(key)
        if metadata.get("source_chunk_evidence") not in (None, "", [], {}):
            evidence["source_chunk_evidence"] = metadata.get("source_chunk_evidence")
        return {key: value for key, value in evidence.items() if value not in (None, "", [], {})}

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


def _requires_certification_boundary(query: str) -> bool:
    text = query or ""
    lowered = text.lower()
    has_target = bool(COMPLIANCE_DECISION_TARGET_RE.search(text))
    has_current_state_target = bool(
        CURRENT_STATE_PROOF_RE.search(text)
        and re.search(
            r"\b(osha|checklist|audit|safety|compliance|machine|deployment|system|site|equipment|secure|security)\b",
            lowered,
        )
    )
    has_statement_output = bool(COMPLIANCE_STATEMENT_OUTPUT_RE.search(text))
    has_passed_claim = bool(
        re.search(
            r"\b(?:passed? (?:the )?(?:checklist|audit)|meets? (?:osha|requirements?|standards?)|"
            r"(?:is|are) (?:compliant|approved|secure|safe))\b",
            lowered,
        )
    )

    if CERTIFICATION_ACTION_RE.search(text) and (
        has_target
        or has_current_state_target
        or re.search(r"\b(osha|checklist|audit|safety|compliance|machine|deployment|system|site|equipment)\b", lowered)
    ):
        return True
    if COMPLIANCE_VERDICT_ACTION_RE.search(text) and (has_target or has_current_state_target):
        return True
    if COMPLIANCE_STATEMENT_ACTION_RE.search(text) and (
        (has_target and (has_statement_output or has_passed_claim))
        or (has_current_state_target and (has_target or has_statement_output or has_passed_claim))
    ):
        return True
    return bool(
        re.search(r"\bsign[- ]?off\b", lowered)
        and re.search(r"\b(osha|checklist|audit|safety|compliance|machine|secure|security)\b", lowered)
    )


def _certification_boundary_answer(query: str) -> str:
    safety_domain = bool(SAFETY_DOMAIN_RE.search(query or ""))
    review_owner = (
        "a qualified safety or compliance reviewer"
        if safety_domain
        else "the responsible compliance owner or qualified reviewer"
    )
    current_record = (
        "current site conditions, applicable requirements, and the site safety/compliance process"
        if safety_domain
        else "current system evidence, applicable requirements, and the responsible review process"
    )
    return (
        "I cannot certify, attest, approve, sign off on, or confirm current compliance from retrieved "
        "checklist or manual text. Do not use this document-only answer as a compliance statement, "
        "audit sign-off, or proof that the current machine, system, or deployment is compliant, secure, "
        "or safe. The retrieved evidence can support a checklist-style review, but it does not replace "
        f"{review_owner} evaluating {current_record}."
    )


def _negates_available_evidence_issue(
    *,
    query: str,
    answer: str,
    doc_chunks: dict[str, list[Chunk]],
) -> str | None:
    if not NEGATES_RETRIEVED_EVIDENCE_RE.search(answer or ""):
        return None
    if not _has_matching_retrieved_evidence(query=query, doc_chunks=doc_chunks):
        return None
    if _negated_answer_claims_are_supported(answer=answer, doc_chunks=doc_chunks):
        return None

    query_terms = _support_tokens(query) - {
        "answer",
        "check",
        "checked",
        "checklist",
        "evidence",
        "information",
        "item",
        "listed",
        "mention",
        "question",
        "specific",
        "summarize",
        "summary",
    }
    if not query_terms:
        return None

    evidence_terms = set()
    for chunks in doc_chunks.values():
        for chunk in chunks:
            evidence_terms.update(_support_tokens(_chunk_text_with_metadata_for_support(chunk)))

    overlap = query_terms & evidence_terms
    if len(overlap) >= max(2, min(4, len(query_terms) // 2)):
        return "answer_negates_matching_retrieved_evidence"
    return None


def _negated_answer_claims_are_supported(*, answer: str, doc_chunks: dict[str, list[Chunk]]) -> bool:
    negated_sentences = [
        _clean_extractive_sentence(sentence)
        for sentence in _evidence_sentences(answer)
        if NEGATES_RETRIEVED_EVIDENCE_RE.search(sentence)
    ]
    if not negated_sentences:
        return False

    evidence_sentences = [
        _clean_extractive_sentence(sentence)
        for chunks in doc_chunks.values()
        for chunk in chunks
        for sentence in _evidence_sentences(_chunk_text_with_metadata_for_support(chunk))
    ]
    evidence_blob = " ".join(
        re.sub(r"\s+", " ", sentence).strip().lower()
        for sentence in evidence_sentences
    )
    for sentence in negated_sentences:
        normalized = re.sub(r"\s+", " ", _strip_inline_citation_markers(sentence)).strip().lower()
        if not normalized:
            continue
        if normalized in evidence_blob:
            continue
        sentence_terms = _support_tokens(normalized)
        if not sentence_terms:
            return False
        best_coverage = 0.0
        best_overlap = 0
        for evidence_sentence in evidence_sentences:
            evidence_terms = _support_tokens(evidence_sentence)
            overlap = len(sentence_terms & evidence_terms)
            coverage = overlap / max(1, len(sentence_terms))
            best_overlap = max(best_overlap, overlap)
            best_coverage = max(best_coverage, coverage)
        if best_overlap < 4 or best_coverage < 0.72:
            return False
    return True


@dataclass(frozen=True)
class ProcedureEvidenceStep:
    index: int
    text: str
    source_number: int
    doc_id: str
    chunk_id: str
    title: str | None = None
    organization: str | None = None
    page: int | None = None
    page_label: str | None = None
    pdf_url: str | None = None
    text_search: str | None = None
    snippet: str | None = None

    def to_evidence_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_number": self.source_number,
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "organization": self.organization,
            "page": self.page,
            "page_label": self.page_label,
            "pdf_url": self.pdf_url,
            "snippet": self.snippet or self.text,
            "text_search": self.text_search,
        }
        return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


@dataclass(frozen=True)
class SummaryCompletenessFacet:
    name: str
    evidence_patterns: tuple[str, ...]
    answer_patterns: tuple[str, ...]


@dataclass(frozen=True)
class SummaryCompletenessSettings:
    facets: tuple[SummaryCompletenessFacet, ...]
    max_sentences_per_facet: int = 2
    max_augmented_sentences: int = 5


SUMMARY_COMPLETENESS_SETTINGS = SummaryCompletenessSettings(
    facets=(
        SummaryCompletenessFacet(
            name="limitations",
            evidence_patterns=(
                r"\bnot\s+(?:a\s+|an\s+)?(?:checklist|procedure|sequence|ordered?\s+list)\b",
                r"\bdoes\s+not\b.{0,120}\b(?:checklist|sequence|order|procedure|replace|imply)\b",
                r"\bno\s+(?:fixed\s+)?(?:sequence|order)\b",
                r"\blimitations?\b",
                r"\bcaveats?\b",
            ),
            answer_patterns=(
                r"\bnot\s+(?:a\s+|an\s+)?(?:checklist|procedure|sequence|ordered?\s+list)\b",
                r"\bdoes\s+not\b.{0,120}\b(?:checklist|sequence|order|procedure|replace|imply)\b",
                r"\bno\s+(?:fixed\s+)?(?:sequence|order)\b",
                r"\blimitations?\b",
                r"\bcaveats?\b",
            ),
        ),
        SummaryCompletenessFacet(
            name="scope",
            evidence_patterns=(
                r"\b(?:applies|apply|applicable)\b",
                r"\bcurrent\s+and\s+future\b",
                r"\bacross\b.{0,120}\b(?:environment|environments|systems?|teams?|organizations?|partners?)\b",
                r"\bto\b.{0,80}\b(?:teams?|partners?|organizations?|environments|systems?)\b",
            ),
            answer_patterns=(
                r"\b(?:applies|apply|applicable)\b",
                r"\bcurrent\s+and\s+future\b",
                r"\bacross\b.{0,120}\b(?:environment|environments|systems?|teams?|organizations?|partners?)\b",
                r"\bto\b.{0,80}\b(?:teams?|partners?|organizations?|environments|systems?)\b",
            ),
        ),
        SummaryCompletenessFacet(
            name="cadence",
            evidence_patterns=(
                r"\bconcurrent(?:ly)?\b",
                r"\bcontinu(?:e|es|ed|ing|ous(?:ly)?)\b",
                r"\bongoing\b",
                r"\bat\s+all\s+times\b",
                r"\bin\s+parallel\b",
            ),
            answer_patterns=(
                r"\bconcurrent(?:ly)?\b",
                r"\bcontinu(?:e|es|ed|ing|ous(?:ly)?)\b",
                r"\bongoing\b",
                r"\bat\s+all\s+times\b",
                r"\bin\s+parallel\b",
            ),
        ),
    )
)


@dataclass(frozen=True)
class ExtractiveRelationshipSettings:
    cue_patterns: tuple[str, ...]
    stopwords: tuple[str, ...]
    max_sentences: int = 6
    neighbor_window: int = 2
    min_sentence_tokens: int = 4
    min_query_overlap: int = 1


EXTRACTIVE_RELATIONSHIP_SETTINGS = ExtractiveRelationshipSettings(
    cue_patterns=(
        r"\bconnect(?:s|ed|ing|ion)?\b",
        r"\brelat(?:e|es|ing)\b",
        r"\brelated\s+to\b",
        r"\brelationship\b",
        r"\bcompar(?:e|es|ed|ing|ison)\b",
        r"\bcontrast(?:s|ed|ing)?\b",
        r"\bdiffer(?:s|ed|ence|ent)?\b",
        r"\bversus\b|\bvs\.?\b",
    ),
    stopwords=(
        "area",
        "audit",
        "between",
        "compare",
        "comparison",
        "connect",
        "connection",
        "contrast",
        "differ",
        "difference",
        "different",
        "relate",
        "relationship",
        "review",
        "section",
        "versus",
    ),
)


@dataclass(frozen=True)
class ProcedureEvidenceSet:
    steps: tuple[ProcedureEvidenceStep, ...]
    confidence: str = "high"
    reason: str = "explicit_ordered_procedure"

    def to_answer(self) -> str:
        return "\n".join(
            f"{index}. {step.text} [^{step.source_number}]"
            for index, step in enumerate(self.steps, start=1)
        )


def extract_explicit_procedure_evidence(
    *,
    query: str,
    doc_order: list[str],
    doc_chunks: dict[str, list[Chunk]],
) -> ProcedureEvidenceSet | None:
    """Extract high-confidence explicit ordered procedure recall from retrieved source text."""
    if not _is_static_procedure_recall_query(query):
        return None

    candidates: list[tuple[float, int, ProcedureEvidenceSet]] = []
    sequence = 0
    for doc_id in doc_order:
        source_number = doc_order.index(doc_id) + 1
        for chunk in doc_chunks.get(doc_id, []):
            for item in _procedure_extraction_text_items(chunk, source_number=source_number):
                item_text = str(item.get("text") or "")
                for candidate in _ordered_procedure_candidates_from_text(
                    query=query,
                    text=item_text,
                    item=item,
                    chunk=chunk,
                ):
                    score = _procedure_candidate_score(query=query, evidence=candidate, item=item)
                    if score >= 8.0:
                        candidates.append((score, sequence, candidate))
                        sequence += 1

    if not candidates:
        return None
    candidates.sort(key=lambda value: (value[0], -value[1]), reverse=True)
    return candidates[0][2]


def _procedure_answer_needs_evidence_repair(
    *,
    query: str,
    answer: str,
    procedure_evidence: ProcedureEvidenceSet,
) -> bool:
    if not procedure_evidence.steps:
        return False
    if is_insufficient_context_answer(answer):
        return True
    answer_steps, _skipped_intro = _procedure_step_texts_from_answer(answer)
    if len(answer_steps) != len(procedure_evidence.steps):
        return True
    evidence_step_tokens = [
        _support_tokens(step.text) - {"energy", "machine", "procedure", "service", "maintenance"}
        for step in procedure_evidence.steps
    ]
    answer_step_tokens = [
        _support_tokens(step) - {"energy", "machine", "procedure", "service", "maintenance"}
        for step in answer_steps
    ]
    for expected_tokens, evidence_step in zip(evidence_step_tokens, procedure_evidence.steps):
        if not expected_tokens:
            continue
        best_overlap = max((len(expected_tokens & observed_tokens) for observed_tokens in answer_step_tokens), default=0)
        best_coverage = best_overlap / max(1, len(expected_tokens))
        if best_overlap <= 0 or best_coverage < 0.45:
            return True
        for sentence in _procedure_support_sentences(evidence_step.text):
            sentence_tokens = _support_tokens(sentence) - {"energy", "machine", "procedure", "service", "maintenance"}
            if len(sentence_tokens) < 3:
                continue
            sentence_overlap = max((len(sentence_tokens & observed_tokens) for observed_tokens in answer_step_tokens), default=0)
            if sentence_overlap / max(1, len(sentence_tokens)) < 0.5:
                return True
    return False


def _procedure_support_sentences(step_text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", step_text or "")
        if sentence.strip()
    ]


def _is_static_procedure_recall_query(query: str) -> bool:
    text = query or ""
    lowered = text.lower()
    if _requires_certification_boundary(text):
        return False
    if _is_static_checklist_or_item_recall_query(text):
        return False
    if not _PROCEDURE_CONTEXT_RE.search(text):
        return False
    if re.search(r"\b(can|may|should)\s+i\b", lowered) and re.search(
        r"\b(start|operate|energiz|reenergiz|proceed|perform)\b",
        lowered,
    ):
        return False
    return bool(
        re.search(r"\b(what|which|list|identify|according|steps?|procedure|complete|accomplished)\b", lowered)
        or re.search(r"\bbefore\b.{0,80}\b(service|maintenance|shutdown|remov|reenerg)", lowered)
    )


def _is_static_checklist_or_item_recall_query(query: str) -> bool:
    lowered = (query or "").lower()
    if not re.search(
        r"\b(what|which|list|listed|identify|mention|mentions|pull\s+out|extract|show)\b",
        lowered,
    ):
        return False
    if not re.search(
        r"\b(check|checks|checklist|question|questions|item|items|criteria|areas?|requirements?)\b",
        lowered,
    ):
        return False
    return not bool(
        re.search(
            r"\b(steps?|sequence|ordered|procedure|procedures|how\s+to|complete|completed|accomplished)\b",
            lowered,
        )
    )


def _procedure_extraction_text_items(chunk: Chunk, *, source_number: int) -> list[dict[str, Any]]:
    metadata = chunk.metadata or {}
    base_item = {
        "source_number": source_number,
        "doc_id": metadata.get("doc_id"),
        "chunk_id": chunk.chunk_id,
        "title": metadata.get("title"),
        "organization": metadata.get("organization"),
        "page": metadata.get("page"),
        "page_label": metadata.get("page_label"),
        "pdf_url": metadata.get("pdf_url"),
        "text": chunk.text,
        "nested": False,
    }
    items = [base_item]

    def add_nested(raw: dict[str, Any], parent: dict[str, Any]) -> None:
        text = raw.get("text") or raw.get("snippet") or raw.get("text_search")
        if not text:
            return
        item = {
            "source_number": parent.get("source_number"),
            "doc_id": raw.get("doc_id") or parent.get("doc_id"),
            "chunk_id": raw.get("chunk_id") or parent.get("chunk_id"),
            "title": raw.get("title") or parent.get("title"),
            "organization": raw.get("organization") or parent.get("organization"),
            "page": raw.get("page") or parent.get("page"),
            "page_label": raw.get("page_label") or parent.get("page_label"),
            "pdf_url": raw.get("pdf_url") or parent.get("pdf_url"),
            "text": text,
            "nested": True,
        }
        items.append(item)
        for key in ("source_chunk_evidence", "evidence", "evidence_snippets"):
            nested = raw.get(key)
            if not isinstance(nested, list):
                continue
            for child in nested:
                if isinstance(child, dict):
                    add_nested(child, item)

    for key in ("source_chunk_evidence", "evidence", "evidence_snippets"):
        nested_items = metadata.get(key)
        if not isinstance(nested_items, list):
            continue
        for raw_item in nested_items:
            if isinstance(raw_item, dict):
                add_nested(raw_item, base_item)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("doc_id") or ""),
            str(item.get("chunk_id") or ""),
            _compact_procedure_text(item.get("text"))[:240],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    return deduped


_ORDERED_SOURCE_STEP_RE = re.compile(r"(?<![A-Za-z0-9])(?:\((\d{1,2})\)|(\d{1,2})[\.)])\s+")


def _ordered_procedure_candidates_from_text(
    *,
    query: str,
    text: str,
    item: dict[str, Any],
    chunk: Chunk,
) -> list[ProcedureEvidenceSet]:
    matches = [
        (int(match.group(1) or match.group(2)), match)
        for match in _ORDERED_SOURCE_STEP_RE.finditer(text or "")
    ]
    candidates: list[ProcedureEvidenceSet] = []
    if len(matches) < 2:
        return candidates

    for start_index, (number, first_match) in enumerate(matches):
        if number != 1:
            continue
        intro = text[max(0, first_match.start() - 320) : first_match.start()]
        if (
            not _PROCEDURE_INTRO_RE.search(intro)
            and "procedure" not in intro.lower()
            and not re.search(r"\bbefore\b.{0,120}\b(service|maintenance)\b", intro, flags=re.IGNORECASE)
        ):
            continue

        raw_steps: list[str] = []
        expected = 1
        current_index = start_index
        sequence_complete = True
        while current_index < len(matches):
            current_number, current_match = matches[current_index]
            if current_number != expected:
                sequence_complete = False
                break
            next_match = matches[current_index + 1][1] if current_index + 1 < len(matches) else None
            next_number = matches[current_index + 1][0] if current_index + 1 < len(matches) else None
            raw_end = next_match.start() if next_match else len(text)
            is_final = next_number != expected + 1
            step_text = _clean_source_procedure_step(text[current_match.end() : raw_end], is_final=is_final)
            if not _is_complete_source_procedure_step(step_text):
                sequence_complete = False
                break
            raw_steps.append(step_text)
            expected += 1
            current_index += 1
            if is_final:
                break

        if not sequence_complete or len(raw_steps) < 2:
            continue
        action_hits = sum(1 for step in raw_steps if _PROCEDURE_ACTION_TERMS_RE.search(step))
        if action_hits < max(2, len(raw_steps) // 2):
            continue

        source_number = int(item.get("source_number") or 1)
        steps = tuple(
            ProcedureEvidenceStep(
                index=index,
                text=step_text,
                source_number=source_number,
                doc_id=str(item.get("doc_id") or chunk.metadata.get("doc_id") or chunk.metadata.get("title") or "Unknown"),
                chunk_id=str(item.get("chunk_id") or chunk.chunk_id),
                title=item.get("title") or chunk.metadata.get("title"),
                organization=item.get("organization") or chunk.metadata.get("organization"),
                page=_metadata_int(item.get("page") or chunk.metadata.get("page")),
                page_label=item.get("page_label") or chunk.metadata.get("page_label"),
                pdf_url=item.get("pdf_url") or chunk.metadata.get("pdf_url"),
                text_search=_source_step_text_search(step_text),
                snippet=step_text,
            )
            for index, step_text in enumerate(raw_steps, start=1)
        )
        candidate = ProcedureEvidenceSet(steps=steps)
        if _procedure_query_anchor_mismatch(query=query, evidence=candidate, item_text=text):
            continue
        candidates.append(candidate)
    return candidates


def _clean_source_procedure_step(raw: str, *, is_final: bool) -> str:
    text = raw or ""
    if is_final:
        text = re.split(r"(?:\r?\n\s*){2,}|\[Source page \d+ text\]", text, maxsplit=1)[0]
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:and|or)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:and|or)\s*$", "", text, flags=re.IGNORECASE)
    text = text.strip(" \t\r\n;:")
    if is_final:
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
            if sentence.strip()
        ]
        if sentences:
            kept = [sentences[0]]
            for sentence in sentences[1:]:
                if re.match(r"^(?:If|When|After|Before|Once)\b", sentence) and _PROCEDURE_ACTION_TERMS_RE.search(sentence):
                    kept.append(sentence)
                    continue
                break
            text = " ".join(kept)
    return _normalize_step_punctuation(text)


def _is_complete_source_procedure_step(text: str) -> bool:
    if re.search(r"(?:\.\.\.|…)", text or ""):
        return False
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    if len(words) < 2:
        return False
    if words[-1].lower() in {"a", "an", "and", "or", "the", "of", "to", "from", "with", "by", "for", "in", "on"}:
        return False
    return True


def _source_step_text_search(step_text: str) -> str:
    return re.sub(r"\s+", " ", step_text or "").strip(" \t\r\n.;:")


def _procedure_query_anchor_mismatch(*, query: str, evidence: ProcedureEvidenceSet, item_text: str) -> bool:
    query_lower = (query or "").lower()
    evidence_lower = f"{item_text} {' '.join(step.text for step in evidence.steps)}".lower()
    if "before beginning" in query_lower or ("beginning" in query_lower and {"service", "maintenance"} & _support_tokens(query_lower)):
        return "before beginning" not in evidence_lower and "beginning service" not in evidence_lower
    if re.search(r"\bbefore\b.{0,80}\bremov", query_lower):
        return "remov" not in evidence_lower
    if "reenerg" in query_lower:
        return "reenerg" not in evidence_lower
    return False


def _procedure_candidate_score(*, query: str, evidence: ProcedureEvidenceSet, item: dict[str, Any]) -> float:
    item_text = str(item.get("text") or "")
    query_terms = _support_tokens(query) - EXTRACTIVE_RECALL_STOPWORDS
    evidence_text = f"{item_text} {' '.join(step.text for step in evidence.steps)}"
    evidence_terms = _support_tokens(evidence_text)
    overlap = len(query_terms & evidence_terms)
    score = float(overlap)
    if _PROCEDURE_INTRO_RE.search(item_text):
        score += 5.0
    if len(evidence.steps) >= 3:
        score += 2.0
    if all(step.index == index for index, step in enumerate(evidence.steps, start=1)):
        score += 1.0
    if item.get("nested"):
        score += 8.0
    return score


def _compact_procedure_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _attach_procedure_evidence_to_sources(
    sources: list[SourceCitation],
    procedure_evidence: ProcedureEvidenceSet,
) -> None:
    evidence_by_source: dict[int, list[dict[str, Any]]] = {}
    for step in procedure_evidence.steps:
        evidence_by_source.setdefault(step.source_number, []).append(step.to_evidence_payload())

    for source in sources:
        step_evidence = evidence_by_source.get(int(source.source_number or 0))
        if not step_evidence:
            continue
        existing = source.evidence_snippets or []
        source.evidence_snippets = _dedupe_procedure_evidence_items(step_evidence + existing)
        primary = step_evidence[0]
        for key, value in primary.items():
            if key in {"doc_id", "chunk_id", "page", "page_label", "pdf_url", "snippet", "text_search"} and value not in (
                None,
                "",
                [],
                {},
            ):
                setattr(source, key, value)


def _dedupe_procedure_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("doc_id") or ""),
            str(item.get("chunk_id") or ""),
            str(item.get("page") or ""),
            _compact_procedure_text(item.get("text_search") or item.get("snippet"))[:200],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _extractive_supported_relationship_answer(
    *,
    query: str,
    doc_order: list[str],
    doc_chunks: dict[str, list[Chunk]],
    settings: ExtractiveRelationshipSettings = EXTRACTIVE_RELATIONSHIP_SETTINGS,
) -> str | None:
    if not _is_extractive_relationship_query(query, settings=settings):
        return None

    focus_terms = _support_tokens(query) - EXTRACTIVE_RECALL_STOPWORDS - set(settings.stopwords)
    if not focus_terms:
        return None

    candidates: list[tuple[float, int, frozenset[str], str, str]] = []
    sequence = 0

    for doc_id in doc_order:
        marker = _source_marker_for_doc(doc_order, doc_id)
        if not marker:
            continue
        for chunk in doc_chunks.get(doc_id, []):
            for item_text, metadata_text in _relationship_extraction_text_items(chunk):
                chunk_sentences = [
                    _clean_extractive_sentence(sentence)
                    for sentence in _evidence_sentences(item_text)
                ]
                match_details = _relationship_sentence_matches(
                    query_terms=focus_terms,
                    sentences=chunk_sentences,
                    metadata_text=metadata_text,
                    settings=settings,
                )
                if not match_details:
                    continue
                for index in _expand_neighbor_indexes(
                    list(match_details.keys()),
                    sentence_count=len(chunk_sentences),
                    window=settings.neighbor_window,
                ):
                    clean_sentence = chunk_sentences[index]
                    if len(re.findall(r"[A-Za-z0-9]+", clean_sentence)) < settings.min_sentence_tokens:
                        continue
                    score, matched_terms = _relationship_sentence_score(
                        query_terms=focus_terms,
                        sentence=clean_sentence,
                        metadata_text=metadata_text,
                        settings=settings,
                    )
                    if index not in match_details:
                        nearest_index = min(match_details, key=lambda matched_index: abs(matched_index - index))
                        nearest_score, nearest_terms = match_details[nearest_index]
                        distance = abs(nearest_index - index)
                        score = max(score, nearest_score - (0.45 * distance))
                        if not matched_terms:
                            matched_terms = nearest_terms
                    if score <= 0:
                        continue
                    candidates.append((score, sequence, frozenset(matched_terms), clean_sentence, marker))
                    sequence += 1

    selected = _select_relationship_sentences(candidates, max_sentences=settings.max_sentences)
    if len(selected) < 2:
        return None
    return "\n".join(f"- {sentence} {marker}" for sentence, marker in selected)


def _is_extractive_relationship_query(
    query: str,
    *,
    settings: ExtractiveRelationshipSettings = EXTRACTIVE_RELATIONSHIP_SETTINGS,
) -> bool:
    text = (query or "").lower()
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in settings.cue_patterns)


def _relationship_sentence_matches(
    *,
    query_terms: set[str],
    sentences: list[str],
    metadata_text: str,
    settings: ExtractiveRelationshipSettings,
) -> dict[int, tuple[float, set[str]]]:
    matched: dict[int, tuple[float, set[str]]] = {}
    for index, sentence in enumerate(sentences):
        score, matched_terms = _relationship_sentence_score(
            query_terms=query_terms,
            sentence=sentence,
            metadata_text=metadata_text,
            settings=settings,
        )
        if score > 0:
            matched[index] = (score, matched_terms)
    return matched


def _relationship_sentence_score(
    *,
    query_terms: set[str],
    sentence: str,
    metadata_text: str,
    settings: ExtractiveRelationshipSettings,
) -> tuple[float, set[str]]:
    sentence_terms = _support_tokens(sentence)
    if not sentence_terms:
        return 0.0, set()

    metadata_terms = _support_tokens(metadata_text)
    metadata_query_terms = query_terms & metadata_terms
    query_overlap = query_terms & sentence_terms
    metadata_overlap = sentence_terms & metadata_terms if metadata_query_terms else set()
    if len(query_overlap) < settings.min_query_overlap and not metadata_overlap:
        return 0.0, set()

    matched_terms = set(query_overlap or metadata_query_terms)
    score = (2.0 * len(query_overlap)) + (1.0 * len(metadata_query_terms & sentence_terms))
    if metadata_overlap:
        score += min(1.0, 0.25 * len(metadata_overlap))
    return score, matched_terms


def _select_relationship_sentences(
    candidates: list[tuple[float, int, frozenset[str], str, str]],
    *,
    max_sentences: int,
) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    deferred: list[tuple[float, int, frozenset[str], str, str]] = []
    covered_terms: set[str] = set()
    seen: set[str] = set()

    for candidate in sorted(candidates, key=lambda item: (-item[0], item[1])):
        score, sequence, matched_terms, sentence, marker = candidate
        normalized = re.sub(r"\s+", " ", sentence).strip().lower()
        if not normalized or normalized in seen:
            continue
        if set(matched_terms) - covered_terms:
            selected.append((sentence, marker))
            covered_terms.update(matched_terms)
            seen.add(normalized)
            if len(selected) >= max_sentences:
                return selected
            continue
        deferred.append((score, sequence, matched_terms, sentence, marker))

    for _score, _sequence, _matched_terms, sentence, marker in sorted(deferred, key=lambda item: (-item[0], item[1])):
        normalized = re.sub(r"\s+", " ", sentence).strip().lower()
        if not normalized or normalized in seen:
            continue
        selected.append((sentence, marker))
        seen.add(normalized)
        if len(selected) >= max_sentences:
            break
    return selected


def _expand_neighbor_indexes(indexes: list[int], *, sentence_count: int, window: int) -> list[int]:
    expanded: list[int] = []
    seen: set[int] = set()
    for index in indexes:
        start = max(0, index - window)
        end = min(sentence_count, index + window + 1)
        for neighbor_index in range(start, end):
            if neighbor_index in seen:
                continue
            seen.add(neighbor_index)
            expanded.append(neighbor_index)
    return expanded


def _chunk_relationship_metadata_text(chunk: Chunk) -> str:
    metadata = chunk.metadata or {}
    section_path = metadata.get("section_path")
    if isinstance(section_path, list):
        section_path = " > ".join(str(part) for part in section_path if part)
    return f"{metadata.get('section_title', '')} {section_path or ''}"


def _relationship_extraction_text_items(chunk: Chunk) -> list[tuple[str, str]]:
    items = [(chunk.text or "", _chunk_relationship_metadata_text(chunk))]
    for evidence_item in _source_chunk_evidence_items(chunk):
        text = _source_chunk_evidence_item_text(evidence_item)
        if not text:
            continue
        section_path = evidence_item.get("section_path")
        if isinstance(section_path, list):
            section_path = " > ".join(str(part) for part in section_path if part)
        metadata_text = f"{evidence_item.get('section_title', '')} {section_path or ''}"
        items.append((text, metadata_text))
    return items


def _extractive_supported_recall_answer(
    *,
    query: str,
    doc_order: list[str],
    doc_chunks: dict[str, list[Chunk]],
) -> str | None:
    if not _is_extractive_recall_query(query):
        return None

    focus_terms = _support_tokens(query) - EXTRACTIVE_RECALL_STOPWORDS
    if not focus_terms:
        return None

    selected: list[tuple[str, str]] = []
    seen: set[str] = set()
    threshold = 1 if len(focus_terms) <= 3 else 2

    for doc_id in doc_order:
        marker = _source_marker_for_doc(doc_order, doc_id)
        if not marker:
            continue
        for chunk in doc_chunks.get(doc_id, []):
            for sentence in _evidence_sentences(chunk.text):
                clean_sentence = _clean_extractive_sentence(sentence)
                if len(re.findall(r"[A-Za-z0-9]+", clean_sentence)) < 4:
                    continue
                sentence_terms = _support_tokens(clean_sentence)
                overlap = focus_terms & sentence_terms
                if len(overlap) < threshold:
                    continue
                normalized = re.sub(r"\s+", " ", clean_sentence).lower()
                if normalized in seen:
                    continue
                selected.append((clean_sentence, marker))
                seen.add(normalized)
                if len(selected) >= 6:
                    break
            if len(selected) >= 6:
                break
        if len(selected) >= 6:
            break

    if not selected:
        return None
    return "\n".join(f"- {sentence} {marker}" for sentence, marker in selected)


_NUMBERED_ANSWER_LINE_RE = re.compile(r"^\s*(\d+)[\.)]\s+(.+?)\s*$")
_NUMBERED_ANSWER_STEP_RE = re.compile(r"(?<!\w)(\d+)[\.)]\s+")
_CITATION_MARKER_RE = re.compile(r"\[\^?(\d+)\]")
_PROCEDURE_ACTION_TERMS_RE = re.compile(
    r"\b(apply|block|check|complete|confirm|disconnect|deenergiz|energiz|isolate|lockout|lock\s+out|"
    r"notify|prepare|release|remove|restrain|service|shut\s+down|shutdown|tagout|tag\s+out|verify)\b",
    re.IGNORECASE,
)
_PROCEDURE_CONTEXT_RE = re.compile(
    r"\b(before|during|after|procedure|steps?|sequence|service|maintenance|shutdown|lockout|tagout|loto|"
    r"energy[- ]control|machine|safety)\b",
    re.IGNORECASE,
)
_PROCEDURE_INTRO_RE = re.compile(
    r"\b(?:following|these)\b.{0,160}\b(?:steps?|sequence|procedure)\b|"
    r"\b(?:before|prior to)\b.{0,160}\b(?:service|maintenance|shutdown)\b.{0,160}"
    r"\b(?:steps?|complete|accomplished)\b",
    re.IGNORECASE,
)
_PROCEDURE_TRAILING_SUMMARY_RE = re.compile(
    r"\b(?:these|the)\s+steps?\s+must\s+be\s+accomplished\b|"
    r"\b(?:these|the)\s+steps?\s+must\b",
    re.IGNORECASE,
)
_CONDITIONAL_STEP_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=(?:If|When|After|Before|Once)\b)")


def _normalize_procedure_answer_format(*, query: str, answer: str) -> str:
    clean_answer = sanitize_rag_answer_text(answer)
    if is_insufficient_context_answer(clean_answer):
        return clean_answer

    raw_lines = [line.strip() for line in clean_answer.splitlines() if line.strip()]
    step_texts, skipped_intro = _procedure_step_texts_from_answer(clean_answer)
    if len(step_texts) < 2:
        return clean_answer
    if not _is_procedure_numbered_answer(query=query, lines=raw_lines, step_texts=step_texts):
        return clean_answer

    default_marker = _last_citation_marker(clean_answer)
    normalized_steps: list[str] = []
    for step_text in step_texts:
        if len(re.findall(r"[A-Za-z0-9]+", step_text)) < 2:
            return clean_answer

        marker = _last_citation_marker(step_text) or default_marker
        step_text = _strip_inline_citation_markers(step_text)
        step_text = _normalize_step_punctuation(step_text)
        if not marker:
            return clean_answer
        normalized_steps.append(f"{len(normalized_steps) + 1}. {step_text} {marker}")

    if len(normalized_steps) < 2:
        return clean_answer

    normalized = "\n".join(normalized_steps)
    if not skipped_intro and normalized == clean_answer:
        return clean_answer
    return normalized


def _procedure_step_texts_from_answer(answer: str) -> tuple[list[str], bool]:
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    line_matches = [(line, _NUMBERED_ANSWER_LINE_RE.match(line)) for line in lines]
    numbered_line_count = sum(1 for _line, match in line_matches if match)
    if numbered_line_count >= 2:
        steps: list[str] = []
        skipped_intro = False
        for line, match in line_matches:
            if _is_procedure_intro_text(line) or _is_procedure_summary_text(line):
                skipped_intro = True
                continue
            if not match:
                return [], skipped_intro
            step_text = match.group(2).strip()
            if _is_procedure_intro_text(step_text):
                skipped_intro = True
                continue
            split_steps = _split_procedure_step_text(step_text)
            if not split_steps:
                return [], skipped_intro
            steps.extend(split_steps)
        return steps, skipped_intro

    matches = list(_NUMBERED_ANSWER_STEP_RE.finditer(answer or ""))
    if len(matches) < 2:
        return [], False

    prefix = answer[: matches[0].start()].strip()
    skipped_intro = False
    if prefix:
        if not _is_procedure_intro_text(prefix):
            return [], False
        skipped_intro = True

    steps: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(answer)
        step_text = answer[match.end() : end].strip()
        if _is_procedure_intro_text(step_text):
            skipped_intro = True
            continue
        split_steps = _split_procedure_step_text(step_text)
        if not split_steps:
            return [], skipped_intro
        steps.extend(split_steps)
    return steps, skipped_intro


def _split_procedure_step_text(text: str) -> list[str]:
    trimmed = _drop_trailing_procedure_summary(text)
    trimmed = _strip_inline_citation_markers(trimmed).strip()
    if not trimmed:
        return []
    pieces = [piece.strip() for piece in _CONDITIONAL_STEP_BOUNDARY_RE.split(trimmed) if piece.strip()]
    if len(pieces) <= 1:
        return [trimmed]
    split_steps: list[str] = [pieces[0]]
    for piece in pieces[1:]:
        if _PROCEDURE_ACTION_TERMS_RE.search(piece):
            split_steps.append(piece)
        else:
            split_steps[-1] = f"{split_steps[-1]} {piece}".strip()
    return split_steps


def _drop_trailing_procedure_summary(text: str) -> str:
    match = _PROCEDURE_TRAILING_SUMMARY_RE.search(text or "")
    if not match:
        return text
    return text[: match.start()].strip()


def _is_procedure_numbered_answer(*, query: str, lines: list[str], step_texts: list[str] | None = None) -> bool:
    combined = " ".join(lines)
    if not _PROCEDURE_CONTEXT_RE.search(f"{query} {combined}"):
        return False
    numbered_step_texts = list(step_texts or [])
    numbered_values = []
    if not numbered_step_texts:
        for line in lines:
            match = _NUMBERED_ANSWER_LINE_RE.match(line)
            if match:
                numbered_values.append(match.group(1))
                numbered_step_texts.append(match.group(2))
    else:
        numbered_values = [match.group(1) for match in _NUMBERED_ANSWER_STEP_RE.finditer(combined)]
    action_hits = sum(1 for text in numbered_step_texts if _PROCEDURE_ACTION_TERMS_RE.search(text))
    has_intro = any(_is_procedure_intro_text(line) for line in lines)
    repeated_numbering = len(set(numbered_values)) < len(numbered_values)
    return action_hits >= 2 and (has_intro or repeated_numbering or "procedure" in (query or "").lower())


def _is_procedure_intro_text(text: str) -> bool:
    stripped = _strip_inline_citation_markers(text).strip()
    return bool(_PROCEDURE_INTRO_RE.search(stripped) and stripped.endswith(":"))


def _is_procedure_summary_text(text: str) -> bool:
    stripped = _strip_inline_citation_markers(text).strip()
    return bool(_PROCEDURE_TRAILING_SUMMARY_RE.search(stripped))


def _last_citation_marker(text: str) -> str | None:
    markers = list(_CITATION_MARKER_RE.finditer(text or ""))
    if not markers:
        return None
    return f"[^{markers[-1].group(1)}]"


def _strip_inline_citation_markers(text: str) -> str:
    return _CITATION_MARKER_RE.sub("", text or "").strip()


def _normalize_step_punctuation(text: str) -> str:
    stripped = re.sub(r"\s+", " ", text or "").strip(" \t\r\n;:")
    if not stripped:
        return stripped
    if stripped[-1] not in ".!?":
        stripped = f"{stripped}."
    return stripped


def _is_extractive_recall_query(query: str) -> bool:
    text = (query or "").lower()
    if _requested_item_count(query) is not None:
        return True
    return bool(
        re.search(r"\b(what|which|list|listed|name|identify|pull out|extract|show|summarize)\b", text)
        and re.search(r"\b(check|checks|checklist|question|questions|item|items|requirements?|topics?|areas?)\b", text)
    )


def _clean_extractive_sentence(sentence: str) -> str:
    text = re.sub(r"^\[Section:[^\]]+\]\s*", "", sentence or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -;")


def _source_marker_for_doc(doc_order: list[str], doc_id: str) -> str | None:
    for index, current_doc_id in enumerate(doc_order, start=1):
        if current_doc_id == doc_id:
            return f"[^{index}]"
    return None


def _support_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    normalized = re.sub(r"\block\s+out\b", "lockout", (text or "").lower())
    normalized = re.sub(r"\btag\s+out\b", "tagout", normalized)
    for raw in re.findall(r"[a-z0-9]+", normalized):
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
        evidence_text = _chunk_text_with_metadata_for_support(chunk)
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


def _summary_breadth_completeness_issue(
    *,
    query: str,
    answer: str,
    doc_chunks: dict[str, list[Chunk]],
    settings: SummaryCompletenessSettings = SUMMARY_COMPLETENESS_SETTINGS,
) -> str | None:
    missing_facets = _missing_summary_facets(
        query=query,
        answer=answer,
        doc_chunks=doc_chunks,
        settings=settings,
    )
    if missing_facets:
        return f"summary_omits_supported_{missing_facets[0].name}"
    return None


def _missing_summary_facets(
    *,
    query: str,
    answer: str,
    doc_chunks: dict[str, list[Chunk]],
    settings: SummaryCompletenessSettings = SUMMARY_COMPLETENESS_SETTINGS,
) -> list[SummaryCompletenessFacet]:
    if not _is_summary_breadth_query(query):
        return []

    evidence_text = " ".join(
        _chunk_text_with_metadata_for_support(chunk)
        for chunks in doc_chunks.values()
        for chunk in chunks
    ).lower()
    answer_text = (answer or "").lower()
    if not evidence_text.strip() or not answer_text.strip():
        return []

    missing: list[SummaryCompletenessFacet] = []
    for facet in settings.facets:
        if not _matches_any_pattern(evidence_text, facet.evidence_patterns):
            continue
        if _matches_any_pattern(answer_text, facet.answer_patterns):
            continue
        missing.append(facet)
    return missing


def _augment_summary_answer_with_supported_facets(
    *,
    query: str,
    answer: str,
    doc_order: list[str],
    doc_chunks: dict[str, list[Chunk]],
    settings: SummaryCompletenessSettings = SUMMARY_COMPLETENESS_SETTINGS,
) -> str | None:
    missing_facets = _missing_summary_facets(
        query=query,
        answer=answer,
        doc_chunks=doc_chunks,
        settings=settings,
    )
    if not missing_facets:
        return None

    missing_by_name = {facet.name: facet for facet in missing_facets}
    selected: list[str] = []
    selected_counts: dict[str, int] = {facet.name: 0 for facet in missing_facets}
    seen_sentences = {
        re.sub(r"\s+", " ", sentence).strip().lower()
        for sentence in _evidence_sentences(answer)
    }
    answer_lower = (answer or "").lower()

    for doc_id in doc_order:
        marker = _source_marker_for_doc(doc_order, doc_id)
        if not marker:
            continue
        for chunk in doc_chunks.get(doc_id, []):
            for sentence in _evidence_sentences(chunk.text):
                clean_sentence = _clean_extractive_sentence(sentence)
                if len(re.findall(r"[A-Za-z0-9]+", clean_sentence)) < 5:
                    continue
                normalized = re.sub(r"\s+", " ", clean_sentence).strip().lower()
                if not normalized or normalized in seen_sentences or normalized in answer_lower:
                    continue
                for facet_name, facet in missing_by_name.items():
                    if selected_counts[facet_name] >= settings.max_sentences_per_facet:
                        continue
                    if not _matches_any_pattern(normalized, facet.evidence_patterns):
                        continue
                    selected.append(f"- {clean_sentence} {marker}")
                    selected_counts[facet_name] += 1
                    seen_sentences.add(normalized)
                    break
                if len(selected) >= settings.max_augmented_sentences:
                    break
            if len(selected) >= settings.max_augmented_sentences:
                break
        if len(selected) >= settings.max_augmented_sentences:
            break

    if not selected:
        return None
    base = sanitize_rag_answer_text(answer).strip()
    if not base:
        return "\n".join(selected)
    return f"{base}\n" + "\n".join(selected)


def _is_summary_breadth_query(query: str) -> bool:
    return bool(
        re.search(
            r"\b(summary|summarize|summarise|overview|explain|describe)\b",
            (query or "").lower(),
        )
    )


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _chunk_text_with_metadata_for_support(chunk: Chunk) -> str:
    metadata = chunk.metadata or {}
    section_path = metadata.get("section_path")
    if isinstance(section_path, list):
        section_path = " > ".join(str(part) for part in section_path if part)
    source_evidence_text = " ".join(
        _source_chunk_evidence_item_text(item)
        for item in _source_chunk_evidence_items(chunk)
    )
    return (
        f"{chunk.text} {metadata.get('snippet', '')} {metadata.get('text_search', '')} "
        f"{metadata.get('section_title', '')} {section_path or ''} {source_evidence_text}"
    )


def _source_chunk_evidence_items(chunk: Chunk) -> list[dict[str, Any]]:
    metadata = chunk.metadata or {}
    raw_items = metadata.get("source_chunk_evidence") or metadata.get("evidence_snippets") or []
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _source_chunk_evidence_item_text(item: dict[str, Any]) -> str:
    return str(item.get("snippet") or item.get("text_search") or item.get("text") or "").strip()


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
