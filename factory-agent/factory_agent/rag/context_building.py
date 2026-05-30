from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from factory_agent.rag.document_registry import resolve_source_pdf_path
from factory_agent.rag.schemas import Chunk, ScoredChunk


VALID_CONTEXT_BUILDERS = {"none", "small_to_big", "rse", "budgeted_rse"}
VALID_COMPRESSION_MODES = {"none", "light_extractive"}
SOURCE_CHUNK_EVIDENCE_SNIPPET_LIMIT = 1200

QUERY_REWRITE_EXPANSIONS = {
    "loto": "lockout tagout hazardous energy control",
    "csf": "cybersecurity framework core profile tier govern identify protect detect respond recover",
    "ams": "advanced manufacturing series smart manufacturing reference architecture",
    "mtconnect": "machine tool equipment data exchange standard",
    "qif": "quality information framework inspection metrology XML",
    "oee": "overall equipment effectiveness performance availability quality",
    "ppe": "personal protective equipment",
}

QUERY_REWRITE_INTENT_CUES = (
    {
        "min_matches": 2,
        "trigger_terms": {
            "example",
            "guide",
            "implementation",
            "material",
            "online",
            "quick",
            "readable",
            "reference",
            "resource",
            "supplement",
            "supplemental",
            "updated",
            "web",
        },
        "cue": "supplemental resources references examples implementation guides machine-readable web PDF publication",
    },
    {
        "min_matches": 1,
        "trigger_terms": {
            "consensus",
            "format",
            "interoperability",
            "international",
            "model",
            "open",
            "protocol",
            "standard",
        },
        "cue": "standards open consensus international data formats models interoperability inputs outputs scope",
    },
    {
        "min_matches": 2,
        "trigger_terms": {
            "exclude",
            "include",
            "included",
            "limitation",
            "out",
            "process",
            "proprietary",
            "recommendation",
            "scope",
            "within",
        },
        "cue": "in scope out of scope recommendations limitations processes data formats proprietary open consensus",
    },
)

TOKEN_WORD_RE = re.compile(r"\b\w+(?:[-']\w+)?\b")
WORD_RE = re.compile(r"[a-z0-9]+")
SECTION_PREFIX_RE = re.compile(r"^\[Section:\s*[^\]]+\]\s*", re.IGNORECASE)

CONTEXT_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "does",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "or",
    "that",
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

QUERY_ACTION_TERMS = {
    "basic",
    "describe",
    "explain",
    "handle",
    "list",
    "overview",
    "summarize",
    "summary",
    "tell",
    "under",
}

RELATED_SECTION_QUERY_TERMS = {
    "compare",
    "comparison",
    "complete",
    "difference",
    "differences",
    "differ",
    "check",
    "checklist",
    "detect",
    "dimensions",
    "dimension",
    "elements",
    "element",
    "fit",
    "functions",
    "function",
    "group",
    "include",
    "includes",
    "including",
    "incident",
    "list",
    "listed",
    "multi",
    "nearby",
    "part",
    "parts",
    "procedure",
    "procedures",
    "recover",
    "recovery",
    "respond",
    "relationship",
    "related",
    "resource",
    "resources",
    "section",
    "sections",
    "scope",
    "standard",
    "standards",
    "subactivities",
    "subactivity",
    "summary",
    "summarize",
    "under",
}


@dataclass(frozen=True)
class CompressionResult:
    text: str
    before_tokens: int
    after_tokens: int
    compression_ran: bool
    selected_sentence_indices: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ContextBuildResult:
    chunks: list[Chunk]
    metadata: dict[str, Any]


@dataclass
class _CandidateInfo:
    score: float
    rank: int


@dataclass(frozen=True)
class BudgetedRSESettings:
    max_neighbor_window: int = 2
    max_segment_tokens: int = 1500
    max_context_tokens: int = 3200
    min_neighbor_gain: float = 0.28
    min_relevance: float = 0.12
    min_missing_facet_gain: float = 0.08
    sufficient_facet_coverage: float = 0.86
    min_anchor_query_coverage: float = 0.40
    min_global_segment_gain: float = 0.08
    require_cross_doc_query_term_gain_for_preservation: bool = True
    same_section_bonus: float = 0.22
    related_section_bonus: float = 0.12
    heading_match_weight: float = 0.18
    authority_risk_bonus: float = 0.06
    redundancy_penalty_weight: float = 0.24
    token_cost_penalty_weight: float = 0.20
    retrieval_score_weight: float = 0.08
    structured_sequence_bonus: float = 0.08
    structured_keyword_bonus: float = 0.04
    structured_short_bullet_bonus: float = 0.08
    short_bullet_max_tokens: int = 48
    segment_metadata_query_coverage_weight: float = 0.60
    segment_top_rank_metadata_bonus: float = 0.65
    segment_top_rank_metadata_max_rank: int = 3
    segment_top_rank_metadata_min_coverage: float = 0.45
    use_evidence_cards: bool = False
    evidence_card_context_mode: str = "contextual"
    max_evidence_cards: int = 8
    max_card_tokens: int = 180
    evidence_card_token_budget: int = 2200
    min_card_score: float = 0.05
    min_evidence_query_term_coverage: float = 0.55
    broad_context_intent_threshold: float = 0.45
    procedure_card_context_threshold: float = 0.55
    direct_card_context_threshold: float = 0.50
    card_facet_gain_weight: float = 1.35
    card_anchor_gain_weight: float = 1.65
    card_query_term_gain_weight: float = 1.45
    card_query_overlap_weight: float = 0.82
    card_bigram_overlap_weight: float = 2.20
    card_heading_overlap_weight: float = 1.25
    card_intent_weight: float = 0.72
    card_exact_locator_bonus: float = 0.20
    card_authority_bonus: float = 0.08
    card_checklist_priority_bonus: float = 0.65
    card_top_rank_bonus: float = 0.70
    card_redundancy_penalty: float = 0.32
    card_resource_listing_penalty: float = 0.75
    card_front_matter_penalty: float = 1.25
    card_max_token_penalty: float = 0.25


LEGACY_RSE_PRESERVATION_SETTINGS = BudgetedRSESettings(
    require_cross_doc_query_term_gain_for_preservation=False,
)


@dataclass
class _SegmentDraft:
    segment_id: str
    context_builder: str
    text: str
    chunks_in_segment: list[Chunk]
    child_chunks: list[Chunk]
    seed_chunk_id: str | None
    token_estimate_before_expansion: int
    token_estimate_after_expansion: int
    token_estimate_after_compression: int
    compression_ran: bool
    score: float
    compression_selected_sentence_indices: list[int] = field(default_factory=list)
    neighbor_decisions: list[dict[str, Any]] = field(default_factory=list)

    def to_chunk(self) -> Chunk:
        first_meta = self.chunks_in_segment[0].metadata if self.chunks_in_segment else {}
        metadata = {
            **first_meta,
            "chunk_id": self.segment_id,
            "source_id": f"{first_meta.get('doc_id', 'unknown')}#{self.segment_id}",
            "context_builder": self.context_builder,
            "context_segment_id": self.segment_id,
            "context_segment_score": self.score,
            "seed_chunk_id": self.seed_chunk_id,
            "child_chunk_ids": [chunk.chunk_id for chunk in self.child_chunks],
            "included_child_chunk_ids": [chunk.chunk_id for chunk in self.chunks_in_segment],
            "segment_chunk_ids": [chunk.chunk_id for chunk in self.chunks_in_segment],
            "token_estimate_before_expansion": self.token_estimate_before_expansion,
            "token_estimate_after_expansion": self.token_estimate_after_expansion,
            "token_estimate_after_compression": self.token_estimate_after_compression,
            "compression_ran": self.compression_ran,
            "source_chunk_evidence": [_chunk_evidence(chunk) for chunk in self.chunks_in_segment],
        }
        if self.neighbor_decisions:
            metadata["neighbor_decisions"] = self.neighbor_decisions
        metadata.update(_segment_locator_metadata(self.chunks_in_segment))
        return Chunk(chunk_id=self.segment_id, text=self.text, metadata=metadata)

    def to_metadata(self) -> dict[str, Any]:
        first_meta = self.chunks_in_segment[0].metadata if self.chunks_in_segment else {}
        locator = _segment_locator_metadata(self.chunks_in_segment)
        return {
            "segment_id": self.segment_id,
            "context_builder": self.context_builder,
            "segment_score": round(self.score, 6),
            "seed_chunk_id": self.seed_chunk_id,
            "child_chunk_ids": [chunk.chunk_id for chunk in self.child_chunks],
            "included_child_chunk_ids": [chunk.chunk_id for chunk in self.chunks_in_segment],
            "segment_chunk_ids": [chunk.chunk_id for chunk in self.chunks_in_segment],
            "doc_id": first_meta.get("doc_id"),
            "section_title": first_meta.get("section_title"),
            "section_path": _jsonable_section_path(first_meta.get("section_path")),
            "page": locator.get("page"),
            "page_start": locator.get("page_start"),
            "page_end": locator.get("page_end"),
            "token_estimate_before_expansion": self.token_estimate_before_expansion,
            "token_estimate_after_expansion": self.token_estimate_after_expansion,
            "token_estimate_after_compression": self.token_estimate_after_compression,
            "compression_ran": self.compression_ran,
            "compression_selected_sentence_indices": self.compression_selected_sentence_indices,
            "segment_text_snippet": _snippet(self.text, limit=420),
            "source_chunk_evidence": [_chunk_evidence(chunk) for chunk in self.chunks_in_segment],
            "neighbor_decisions": self.neighbor_decisions,
        }


class RAGContextBuilder:
    """Build post-retrieval context segments for RAG eval variants."""

    def __init__(
        self,
        retriever: Any,
        *,
        small_to_big_max_tokens: int = 3000,
        rse_max_window: int = 2,
        rse_max_segment_tokens: int = 2000,
        compression_max_tokens: int = 1500,
        compression_target_ratio: float = 0.55,
        budgeted_rse_settings: BudgetedRSESettings | None = None,
    ) -> None:
        self.retriever = retriever
        self.small_to_big_max_tokens = small_to_big_max_tokens
        self.rse_max_window = rse_max_window
        self.rse_max_segment_tokens = rse_max_segment_tokens
        self.compression_max_tokens = compression_max_tokens
        self.compression_target_ratio = compression_target_ratio
        self.budgeted_rse_settings = budgeted_rse_settings or BudgetedRSESettings()

    def build(
        self,
        *,
        query: str,
        selected_chunks: list[Chunk],
        candidates: list[ScoredChunk],
        context_builder: str,
        compression: str,
    ) -> ContextBuildResult:
        builder = normalize_context_builder(context_builder)
        compression_mode = normalize_compression(compression)

        if builder == "none":
            return self._no_context_builder_result(
                selected_chunks=selected_chunks,
                compression=compression_mode,
            )

        candidate_info = _candidate_info(candidates)
        if builder == "small_to_big":
            drafts = self._build_small_to_big_segments(
                query=query,
                selected_chunks=selected_chunks,
                candidate_info=candidate_info,
            )
        elif builder == "rse":
            selected_chunks = _preserve_top_related_candidates(
                query=query,
                selected_chunks=selected_chunks,
                candidates=candidates,
                settings=LEGACY_RSE_PRESERVATION_SETTINGS,
            )
            drafts = self._build_rse_segments(
                query=query,
                selected_chunks=selected_chunks,
                candidate_info=candidate_info,
            )
        elif builder == "budgeted_rse":
            selected_chunks = _preserve_top_related_candidates(
                query=query,
                selected_chunks=selected_chunks,
                candidates=candidates,
                settings=self.budgeted_rse_settings,
            )
            evidence_card_mode = str(self.budgeted_rse_settings.evidence_card_context_mode or "").lower()
            if self.budgeted_rse_settings.use_evidence_cards and evidence_card_mode not in {"metadata_only", "off"}:
                selected_chunks = _preserve_top_evidence_card_candidates(
                    query=query,
                    selected_chunks=selected_chunks,
                    candidates=candidates,
                )
            drafts = self._build_budgeted_rse_segments(
                query=query,
                selected_chunks=selected_chunks,
                candidate_info=candidate_info,
            )
        else:  # pragma: no cover - normalize_context_builder guards this.
            raise ValueError(f"Unsupported context_builder={context_builder!r}")

        drafts = self._apply_optional_compression(
            query=query,
            drafts=drafts,
            compression=compression_mode,
        )
        drafts = sorted(drafts, key=lambda draft: draft.score, reverse=True)
        extra_metadata: dict[str, Any] = {}
        if builder == "budgeted_rse":
            drafts, global_budget = _apply_global_context_budget(
                drafts,
                settings=self.budgeted_rse_settings,
                query=query,
            )
            extra_metadata["global_budget"] = global_budget
            if self.budgeted_rse_settings.use_evidence_cards:
                return _context_result_from_evidence_cards(
                    builder=builder,
                    compression=compression_mode,
                    drafts=drafts,
                    query=query,
                    settings=self.budgeted_rse_settings,
                    extra_metadata=extra_metadata,
                )
        return _context_result_from_drafts(
            builder=builder,
            compression=compression_mode,
            drafts=drafts,
            extra_metadata=extra_metadata,
        )

    def _no_context_builder_result(
        self,
        *,
        selected_chunks: list[Chunk],
        compression: str,
    ) -> ContextBuildResult:
        token_estimate = sum(estimate_tokens(chunk.text) for chunk in selected_chunks)
        return ContextBuildResult(
            chunks=selected_chunks,
            metadata={
                "context_builder": "none",
                "compression": compression,
                "compression_ran": False,
                "token_estimates": {
                    "before_expansion": token_estimate,
                    "after_expansion": token_estimate,
                    "after_compression": token_estimate,
                },
                "segments": [],
            },
        )

    def _build_small_to_big_segments(
        self,
        *,
        query: str,
        selected_chunks: list[Chunk],
        candidate_info: dict[str, _CandidateInfo],
    ) -> list[_SegmentDraft]:
        grouped: dict[tuple[str, str], list[Chunk]] = {}
        group_order: list[tuple[str, str]] = []
        for chunk in selected_chunks:
            meta = _clean_metadata(chunk.metadata)
            chunk.metadata = meta
            doc_id = str(meta.get("doc_id") or "")
            section_key = _section_key(meta) or f"chunk:{chunk.chunk_id}"
            key = (doc_id, section_key)
            if key not in grouped:
                grouped[key] = []
                group_order.append(key)
            grouped[key].append(chunk)

        drafts: list[_SegmentDraft] = []
        for group_index, key in enumerate(group_order, start=1):
            child_chunks = grouped[key]
            seed = child_chunks[0]
            parent_chunks = self._parent_section_chunks(seed)
            if not parent_chunks:
                parent_chunks = child_chunks
            parent_chunks = _sort_chunks(parent_chunks)
            section_text = _format_segment_text(
                parent_chunks,
                supplemental_text=self._source_page_text_for_segment(query=query, chunks=parent_chunks),
            )
            before_tokens = sum(estimate_tokens(chunk.text) for chunk in child_chunks)
            after_tokens = estimate_tokens(section_text)
            if after_tokens > self.small_to_big_max_tokens:
                section_text = trim_to_matching_spans(
                    section_text,
                    query=query,
                    max_tokens=self.small_to_big_max_tokens,
                    extra_text=" ".join(chunk.text for chunk in child_chunks),
                )
                after_tokens = estimate_tokens(section_text)
            score = _score_segment(
                query=query,
                child_chunks=child_chunks,
                chunks_in_segment=parent_chunks,
                candidate_info=candidate_info,
            )
            doc_id = seed.metadata.get("doc_id") or "unknown"
            segment_id = _segment_id("stb", doc_id, group_index, child_chunks)
            drafts.append(
                _SegmentDraft(
                    segment_id=segment_id,
                    context_builder="small_to_big",
                    text=section_text,
                    chunks_in_segment=parent_chunks,
                    child_chunks=child_chunks,
                    seed_chunk_id=seed.chunk_id,
                    token_estimate_before_expansion=before_tokens,
                    token_estimate_after_expansion=after_tokens,
                    token_estimate_after_compression=after_tokens,
                    compression_ran=False,
                    score=score,
                )
            )
        return drafts

    def _build_budgeted_rse_segments(
        self,
        *,
        query: str,
        selected_chunks: list[Chunk],
        candidate_info: dict[str, _CandidateInfo],
    ) -> list[_SegmentDraft]:
        settings = self.budgeted_rse_settings
        drafts: list[_SegmentDraft] = []
        consumed_seed_ids: set[str] = set()
        for segment_index, seed in enumerate(selected_chunks, start=1):
            seed.metadata = _clean_metadata(seed.metadata)
            if seed.chunk_id in consumed_seed_ids:
                continue
            segment_chunks, neighbor_decisions = self._budgeted_rse_window_chunks(
                seed,
                query=query,
                candidate_info=candidate_info,
                settings=settings,
            )
            segment_chunks = _sort_chunks(segment_chunks or [seed])
            if settings.use_evidence_cards:
                _annotate_evidence_card_candidate_ranks(segment_chunks, candidate_info)
            consumed_seed_ids.update(chunk.chunk_id for chunk in segment_chunks)

            segment_text = _format_segment_text(segment_chunks)
            before_tokens = estimate_tokens(seed.text)
            after_tokens = estimate_tokens(segment_text)
            if after_tokens > settings.max_segment_tokens:
                segment_text = trim_to_matching_spans(
                    segment_text,
                    query=query,
                    max_tokens=settings.max_segment_tokens,
                    extra_text=seed.text,
                )
                after_tokens = estimate_tokens(segment_text)
            score = _score_segment(
                query=query,
                child_chunks=segment_chunks,
                chunks_in_segment=segment_chunks,
                candidate_info=candidate_info,
                settings=settings,
            )
            doc_id = seed.metadata.get("doc_id") or "unknown"
            drafts.append(
                _SegmentDraft(
                    segment_id=_segment_id("brse", doc_id, segment_index, [seed]),
                    context_builder="budgeted_rse",
                    text=segment_text,
                    chunks_in_segment=segment_chunks,
                    child_chunks=segment_chunks,
                    seed_chunk_id=seed.chunk_id,
                    token_estimate_before_expansion=before_tokens,
                    token_estimate_after_expansion=after_tokens,
                    token_estimate_after_compression=after_tokens,
                    compression_ran=False,
                    score=score,
                    neighbor_decisions=neighbor_decisions,
                )
            )
        return drafts

    def _build_rse_segments(
        self,
        *,
        query: str,
        selected_chunks: list[Chunk],
        candidate_info: dict[str, _CandidateInfo],
    ) -> list[_SegmentDraft]:
        drafts: list[_SegmentDraft] = []
        consumed_seed_ids: set[str] = set()
        for segment_index, seed in enumerate(selected_chunks, start=1):
            seed.metadata = _clean_metadata(seed.metadata)
            if seed.chunk_id in consumed_seed_ids:
                continue
            segment_chunks = self._rse_window_chunks(seed, query=query)
            if not segment_chunks:
                segment_chunks = [seed]
            segment_chunks = _sort_chunks(segment_chunks)
            consumed_seed_ids.update(chunk.chunk_id for chunk in segment_chunks)

            segment_text = _format_segment_text(
                segment_chunks,
                supplemental_text=self._source_page_text_for_segment(query=query, chunks=segment_chunks),
            )
            before_tokens = estimate_tokens(seed.text)
            after_tokens = estimate_tokens(segment_text)
            if after_tokens > self.rse_max_segment_tokens:
                segment_text = trim_to_matching_spans(
                    segment_text,
                    query=query,
                    max_tokens=self.rse_max_segment_tokens,
                    extra_text=seed.text,
                )
                after_tokens = estimate_tokens(segment_text)
            score = _score_segment(
                query=query,
                child_chunks=[seed],
                chunks_in_segment=segment_chunks,
                candidate_info=candidate_info,
            )
            doc_id = seed.metadata.get("doc_id") or "unknown"
            drafts.append(
                _SegmentDraft(
                    segment_id=_segment_id("rse", doc_id, segment_index, [seed]),
                    context_builder="rse",
                    text=segment_text,
                    chunks_in_segment=segment_chunks,
                    child_chunks=[seed],
                    seed_chunk_id=seed.chunk_id,
                    token_estimate_before_expansion=before_tokens,
                    token_estimate_after_expansion=after_tokens,
                    token_estimate_after_compression=after_tokens,
                    compression_ran=False,
                    score=score,
                )
            )
        return drafts

    def _apply_optional_compression(
        self,
        *,
        query: str,
        drafts: list[_SegmentDraft],
        compression: str,
    ) -> list[_SegmentDraft]:
        if compression == "none":
            return drafts
        if compression != "light_extractive":
            raise ValueError(f"Unsupported compression={compression!r}")
        compressed: list[_SegmentDraft] = []
        for draft in drafts:
            result = light_extractive_compress(
                draft.text,
                query=query,
                max_tokens=self.compression_max_tokens,
                target_ratio=self.compression_target_ratio,
                extra_text=" ".join(chunk.text for chunk in draft.child_chunks),
            )
            compressed.append(
                _SegmentDraft(
                    segment_id=draft.segment_id,
                    context_builder=draft.context_builder,
                    text=result.text,
                    chunks_in_segment=draft.chunks_in_segment,
                    child_chunks=draft.child_chunks,
                    seed_chunk_id=draft.seed_chunk_id,
                    token_estimate_before_expansion=draft.token_estimate_before_expansion,
                    token_estimate_after_expansion=draft.token_estimate_after_expansion,
                    token_estimate_after_compression=result.after_tokens,
                    compression_ran=result.compression_ran,
                    score=draft.score,
                    compression_selected_sentence_indices=result.selected_sentence_indices,
                    neighbor_decisions=draft.neighbor_decisions,
                )
            )
        return compressed

    def _parent_section_chunks(self, seed: Chunk) -> list[Chunk]:
        doc_id = seed.metadata.get("doc_id")
        if not doc_id:
            return [seed]
        section_key = _section_key(seed.metadata)
        doc_chunks = self._document_chunks(str(doc_id))
        if not doc_chunks:
            return [seed]
        if not section_key:
            return [seed]
        parent = [
            chunk
            for chunk in doc_chunks
            if str(_clean_metadata(chunk.metadata).get("doc_id") or "") == str(doc_id)
            and _section_key(chunk.metadata) == section_key
        ]
        return parent or [seed]

    def _rse_window_chunks(self, seed: Chunk, *, query: str = "") -> list[Chunk]:
        doc_id = seed.metadata.get("doc_id")
        if not doc_id:
            return [seed]
        doc_chunks = self._document_chunks(str(doc_id))
        if not doc_chunks:
            return [seed]

        seed_index = _chunk_index(seed)
        if seed_index is None:
            return [seed]

        by_index = {
            index: chunk
            for chunk in doc_chunks
            if (index := _chunk_index(chunk)) is not None
        }
        by_index[seed_index] = seed
        seed_key = _section_key(seed.metadata)
        include_related_sections = _query_needs_related_sections(query)
        selected: list[Chunk] = []
        running_tokens = 0
        for index in range(seed_index - self.rse_max_window, seed_index + self.rse_max_window + 1):
            chunk = by_index.get(index)
            if chunk is None:
                continue
            chunk.metadata = _clean_metadata(chunk.metadata)
            if str(chunk.metadata.get("doc_id") or "") != str(doc_id):
                continue
            chunk_key = _section_key(chunk.metadata)
            if seed_key and chunk_key and chunk_key != seed_key:
                if not (
                    include_related_sections
                    and _is_related_section_neighbor(seed.metadata, chunk.metadata)
                ):
                    continue
            candidate_tokens = estimate_tokens(_strip_section_prefix(chunk.text))
            if selected and running_tokens + candidate_tokens > self.rse_max_segment_tokens:
                continue
            if not selected and candidate_tokens > self.rse_max_segment_tokens:
                selected.append(chunk)
                break
            selected.append(chunk)
            running_tokens += candidate_tokens
        return selected or [seed]

    def _budgeted_rse_window_chunks(
        self,
        seed: Chunk,
        *,
        query: str,
        candidate_info: dict[str, _CandidateInfo],
        settings: BudgetedRSESettings,
    ) -> tuple[list[Chunk], list[dict[str, Any]]]:
        doc_id = seed.metadata.get("doc_id")
        if not doc_id:
            return [seed], []
        doc_chunks = self._document_chunks(str(doc_id))
        if not doc_chunks:
            return [seed], []

        seed_index = _chunk_index(seed)
        if seed_index is None:
            return [seed], []

        by_index = {
            index: chunk
            for chunk in doc_chunks
            if (index := _chunk_index(chunk)) is not None
        }
        by_index[seed_index] = seed
        selected_by_index: dict[int, Chunk] = {seed_index: seed}
        decisions: list[dict[str, Any]] = []
        recorded_exclusions: set[int] = set()
        running_tokens = estimate_tokens(_strip_section_prefix(seed.text))
        query_terms = _support_tokens(query)

        while True:
            if query_terms:
                segment_terms = _support_tokens(
                    " ".join(_chunk_text_with_metadata(chunk) for chunk in selected_by_index.values())
                )
                coverage = len(query_terms & segment_terms) / max(1, len(query_terms))
                if coverage >= settings.sufficient_facet_coverage and len(selected_by_index) > 1:
                    break

            current_indices = sorted(selected_by_index)
            candidate_evaluations = []
            for side, index in (("left", current_indices[0] - 1), ("right", current_indices[-1] + 1)):
                if abs(index - seed_index) > settings.max_neighbor_window:
                    continue
                if index in selected_by_index or index in recorded_exclusions:
                    continue
                chunk = by_index.get(index)
                if chunk is None:
                    continue
                evaluation = _evaluate_budgeted_neighbor(
                    query=query,
                    seed=seed,
                    neighbor=chunk,
                    segment_chunks=list(selected_by_index.values()),
                    candidate_info=candidate_info,
                    running_tokens=running_tokens,
                    settings=settings,
                    side=side,
                )
                candidate_evaluations.append((index, chunk, evaluation))

            if not candidate_evaluations:
                break

            includable = [
                (index, chunk, evaluation)
                for index, chunk, evaluation in candidate_evaluations
                if evaluation["decision"] == "candidate"
            ]
            for index, _chunk, evaluation in candidate_evaluations:
                if evaluation["decision"] == "exclude":
                    decisions.append(evaluation)
                    recorded_exclusions.add(index)

            if not includable:
                break

            best_index, best_chunk, best_evaluation = max(
                includable,
                key=lambda item: (item[2]["marginal_gain"], -abs(item[0] - seed_index)),
            )
            if best_evaluation["marginal_gain"] < settings.min_neighbor_gain:
                for index, _chunk, evaluation in includable:
                    exclude = {
                        **evaluation,
                        "decision": "exclude",
                        "reason": "low_marginal_gain",
                    }
                    decisions.append(exclude)
                    recorded_exclusions.add(index)
                break

            selected_by_index[best_index] = best_chunk
            running_tokens += int(best_evaluation["token_estimate"])
            decisions.append(
                {
                    **best_evaluation,
                    "decision": "include",
                    "reason": "positive_marginal_gain",
                    "running_token_estimate": running_tokens,
                }
            )

        return list(selected_by_index.values()), decisions

    def _source_page_text_for_segment(self, *, query: str, chunks: list[Chunk]) -> str:
        if not chunks or not _query_needs_related_sections(query):
            return ""

        existing_text = " ".join(_strip_section_prefix(chunk.text) for chunk in chunks)
        query_terms = _support_tokens(query)
        pages_by_doc: dict[str, list[int]] = {}
        for chunk in chunks:
            metadata = _clean_metadata(chunk.metadata)
            doc_id = str(metadata.get("doc_id") or "").strip()
            if not doc_id:
                continue
            page_values = [
                _metadata_int(metadata, "page"),
                _metadata_int(metadata, "page_start"),
                _metadata_int(metadata, "page_end"),
            ]
            pages = [page for page in page_values if page is not None]
            if not pages:
                continue
            pages_by_doc.setdefault(doc_id, [])
            for page in pages:
                if page not in pages_by_doc[doc_id]:
                    pages_by_doc[doc_id].append(page)

        supplemental: list[str] = []
        for doc_id, pages in pages_by_doc.items():
            for page in sorted(pages)[:3]:
                page_text = _pdf_page_text(doc_id, page)
                if not page_text:
                    continue
                if _page_text_is_redundant(existing_text, page_text):
                    continue
                if query_terms and not (_support_tokens(page_text) & query_terms):
                    continue
                supplemental.append(f"[Source page {page} text]\n{page_text}")
        return "\n\n".join(supplemental)

    def _document_chunks(self, doc_id: str) -> list[Chunk]:
        if hasattr(self.retriever, "get_chunks_for_doc"):
            chunks = self.retriever.get_chunks_for_doc(doc_id)
            return [_clean_chunk(chunk) for chunk in chunks or []]

        bm25_chunks = getattr(self.retriever, "bm25_chunks", None) or []
        if bm25_chunks:
            chunks = [
                _clean_chunk(chunk)
                for chunk in bm25_chunks
                if str(_clean_metadata(getattr(chunk, "metadata", {}) or {}).get("doc_id") or "") == doc_id
            ]
            if chunks:
                return chunks

        collection = getattr(self.retriever, "collection", None)
        if collection is None:
            return []
        try:
            result = collection.get(
                where={"doc_id": doc_id},
                include=["documents", "metadatas"],
            )
        except Exception:
            return []
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        chunks = [
            Chunk(
                chunk_id=chunk_id,
                text=document or "",
                metadata=_clean_metadata(metadata or {}),
            )
            for chunk_id, document, metadata in zip(ids, documents, metadatas)
        ]
        return _sort_chunks(chunks)


def normalize_context_builder(value: str | None) -> str:
    raw = (value or "none").strip().lower().replace("-", "_")
    pieces = {piece for piece in re.split(r"[,+\s]+", raw) if piece and piece != "none"}
    if "small_to_big" in pieces and "rse" in pieces:
        raise ValueError("Small-to-Big and RSE are mutually exclusive context builders")
    if raw in VALID_CONTEXT_BUILDERS:
        return raw
    if pieces == {"small_to_big"}:
        return "small_to_big"
    if pieces == {"rse"}:
        return "rse"
    raise ValueError(
        f"Unsupported context_builder={value!r}; expected one of {sorted(VALID_CONTEXT_BUILDERS)}"
    )


def normalize_compression(value: str | None) -> str:
    raw = (value or "none").strip().lower().replace("-", "_")
    if raw not in VALID_COMPRESSION_MODES:
        raise ValueError(
            f"Unsupported compression={value!r}; expected one of {sorted(VALID_COMPRESSION_MODES)}"
        )
    return raw


def rewrite_query_for_retrieval(query: str) -> str:
    """Deterministically rewrite a query for retrieval without changing generation text."""

    normalized = re.sub(r"\s+", " ", query or "").strip()
    if not normalized:
        return normalized
    lower = normalized.lower()
    additions: list[str] = []
    for trigger, expansion in QUERY_REWRITE_EXPANSIONS.items():
        if trigger in lower and expansion not in lower:
            additions.append(expansion)
    additions.extend(_intent_cues_for_query(normalized))
    key_terms = " ".join(sorted(_support_tokens(normalized)))[:240]
    focus_parts = [*additions]
    if key_terms:
        focus_parts.append(key_terms)
    retrieval_focus = "; ".join(dict.fromkeys(part for part in focus_parts if part))
    return f"{normalized}\nRetrieval focus: {retrieval_focus or normalized}"


def _intent_cues_for_query(query: str) -> list[str]:
    query_terms = _support_tokens(query) | _query_anchor_terms(query)
    cues: list[str] = []
    for rule in QUERY_REWRITE_INTENT_CUES:
        trigger_terms = set(rule["trigger_terms"])
        if len(query_terms & trigger_terms) < int(rule["min_matches"]):
            continue
        cue = str(rule["cue"])
        if cue.lower() not in (query or "").lower():
            cues.append(cue)
    return cues


def estimate_tokens(text: str) -> int:
    words = TOKEN_WORD_RE.findall(text or "")
    if not words:
        return 0
    return max(1, int(round(len(words) * 1.33)))


def trim_to_matching_spans(
    text: str,
    *,
    query: str,
    max_tokens: int,
    extra_text: str = "",
) -> str:
    result = light_extractive_compress(
        text,
        query=query,
        max_tokens=max_tokens,
        target_ratio=1.0,
        extra_text=extra_text,
    )
    return result.text


def light_extractive_compress(
    text: str,
    *,
    query: str,
    max_tokens: int = 1500,
    target_ratio: float = 0.55,
    extra_text: str = "",
) -> CompressionResult:
    before_tokens = estimate_tokens(text)
    if before_tokens == 0:
        return CompressionResult(
            text="",
            before_tokens=0,
            after_tokens=0,
            compression_ran=False,
            selected_sentence_indices=[],
        )

    heading, body = _split_heading_and_body(text)
    heading_tokens = estimate_tokens(heading)
    body_budget = max(1, max_tokens - heading_tokens)
    target_tokens = min(body_budget, max(1, int(round((before_tokens - heading_tokens) * target_ratio))))

    sentences = _split_sentences(body)
    if not sentences:
        after_tokens = min(before_tokens, max_tokens)
        return CompressionResult(
            text=_cap_words(text, max_tokens),
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            compression_ran=after_tokens < before_tokens,
            selected_sentence_indices=[],
        )

    if before_tokens <= max_tokens and before_tokens <= 120:
        return CompressionResult(
            text=text,
            before_tokens=before_tokens,
            after_tokens=before_tokens,
            compression_ran=False,
            selected_sentence_indices=list(range(len(sentences))),
        )

    query_terms = _support_tokens(query) | _query_anchor_terms(query)
    extra_terms = _support_tokens(extra_text)

    scored = [
        (index, _sentence_score(sentence, query_terms=query_terms, extra_terms=extra_terms))
        for index, sentence in enumerate(sentences)
    ]
    scored.sort(key=lambda item: (item[1], -item[0]), reverse=True)

    selected: set[int] = set()
    running_tokens = 0
    evidence_indices: list[int] = []

    def try_add(index: int, *, limit: int = target_tokens) -> bool:
        nonlocal running_tokens
        if index < 0 or index >= len(sentences) or index in selected:
            return False
        sentence_tokens = estimate_tokens(sentences[index])
        if selected and running_tokens + sentence_tokens > limit:
            return False
        selected.add(index)
        running_tokens += sentence_tokens
        return True

    required_indices = _required_evidence_indices(
        sentences,
        query_terms=query_terms,
        extra_terms=extra_terms,
    )
    for index in required_indices:
        if try_add(index, limit=body_budget):
            evidence_indices.append(index)

    for index, score in scored:
        if running_tokens >= target_tokens:
            break
        if score <= 0 and selected:
            continue
        if try_add(index):
            evidence_indices.append(index)

    for index in sorted(evidence_indices):
        if running_tokens >= target_tokens:
            break
        try_add(index - 1)
        try_add(index + 1)

    if not selected:
        for index in range(len(sentences)):
            if not try_add(index):
                break

    ordered_indices = sorted(selected)
    compressed_body = " ".join(sentences[index] for index in ordered_indices).strip()
    compressed_text = _combine_heading_body(heading, compressed_body)

    while estimate_tokens(compressed_text) > max_tokens and ordered_indices:
        ordered_indices.pop()
        compressed_body = " ".join(sentences[index] for index in ordered_indices).strip()
        compressed_text = _combine_heading_body(heading, compressed_body)

    after_tokens = estimate_tokens(compressed_text)
    return CompressionResult(
        text=compressed_text,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        compression_ran=after_tokens < before_tokens,
        selected_sentence_indices=ordered_indices,
    )


def _context_result_from_drafts(
    *,
    builder: str,
    compression: str,
    drafts: list[_SegmentDraft],
    extra_metadata: dict[str, Any] | None = None,
) -> ContextBuildResult:
    before = sum(draft.token_estimate_before_expansion for draft in drafts)
    after_expansion = sum(draft.token_estimate_after_expansion for draft in drafts)
    after_compression = sum(draft.token_estimate_after_compression for draft in drafts)
    metadata = {
        "context_builder": builder,
        "compression": compression,
        "compression_ran": any(draft.compression_ran for draft in drafts),
        "token_estimates": {
            "before_expansion": before,
            "after_expansion": after_expansion,
            "after_compression": after_compression,
        },
        "segments": [draft.to_metadata() for draft in drafts],
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ContextBuildResult(
        chunks=[draft.to_chunk() for draft in drafts],
        metadata=metadata,
    )


def _context_result_from_evidence_cards(
    *,
    builder: str,
    compression: str,
    drafts: list[_SegmentDraft],
    query: str,
    settings: BudgetedRSESettings,
    extra_metadata: dict[str, Any] | None = None,
) -> ContextBuildResult:
    query_intents = _query_intent_scores(query)
    candidate_cards = _evidence_cards_from_drafts(
        drafts,
        query=query,
        query_intents=query_intents,
        settings=settings,
    )
    selected_cards, selection = _select_evidence_cards(
        candidate_cards,
        query=query,
        query_intents=query_intents,
        settings=settings,
    )
    context_policy = _evidence_card_context_policy(query_intents=query_intents, settings=settings)
    evidence_card_metadata = {
        "candidate_count": len(candidate_cards),
        "selected_count": len(selected_cards),
        "query_intent_scores": query_intents,
        "context_policy": context_policy,
        "selected_cards": [_public_evidence_card(card) for card in selected_cards],
        "selection": selection,
    }
    if not selected_cards:
        draft_metadata = dict(extra_metadata or {})
        draft_metadata["evidence_cards"] = evidence_card_metadata
        return _context_result_from_drafts(builder=builder, compression=compression, drafts=drafts, extra_metadata=draft_metadata)

    if not context_policy["uses_card_context"]:
        draft_metadata = dict(extra_metadata or {})
        draft_metadata["evidence_cards"] = evidence_card_metadata
        return _context_result_from_drafts(builder=builder, compression=compression, drafts=drafts, extra_metadata=draft_metadata)

    chunks = [_chunk_from_evidence_card(card, builder=builder) for card in selected_cards]
    before = sum(draft.token_estimate_before_expansion for draft in drafts)
    after_expansion = sum(draft.token_estimate_after_expansion for draft in drafts)
    after_cards = sum(estimate_tokens(chunk.text) for chunk in chunks)
    metadata = {
        "context_builder": builder,
        "compression": compression,
        "compression_ran": any(draft.compression_ran for draft in drafts),
        "token_estimates": {
            "before_expansion": before,
            "after_expansion": after_expansion,
            "after_compression": after_cards,
        },
        "segments": [draft.to_metadata() for draft in drafts],
        "evidence_cards": evidence_card_metadata,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ContextBuildResult(chunks=chunks, metadata=metadata)


def _evidence_card_context_policy(
    *,
    query_intents: dict[str, float],
    settings: BudgetedRSESettings,
) -> dict[str, Any]:
    mode = (settings.evidence_card_context_mode or "contextual").strip().lower()
    if mode in {"off", "metadata", "metadata_only"}:
        return {
            "mode": "metadata_only",
            "uses_card_context": False,
            "reason": "configured_metadata_only",
        }
    if mode in {"context", "contextual", "compact", "compact_cards"}:
        return {
            "mode": "compact_cards",
            "uses_card_context": True,
            "reason": "configured_compact_cards",
        }
    if mode == "mode_aware":
        broad_intent = max(
            query_intents.get("summary", 0.0),
            query_intents.get("comparison", 0.0),
            query_intents.get("checklist", 0.0),
        )
        procedure_intent = query_intents.get("procedure", 0.0)
        direct_intent = query_intents.get("definition", 0.0)
        if broad_intent >= settings.broad_context_intent_threshold:
            return {
                "mode": "broad_context",
                "uses_card_context": False,
                "reason": "summary_comparison_or_checklist_requires_broader_context",
            }
        if procedure_intent >= settings.procedure_card_context_threshold:
            reason = "procedure_intent_allows_compact_cards"
        elif direct_intent >= settings.direct_card_context_threshold or broad_intent < settings.broad_context_intent_threshold:
            reason = "direct_or_narrow_query_allows_compact_cards"
        else:
            reason = "mode_aware_default_compact_cards"
        return {
            "mode": "compact_cards",
            "uses_card_context": True,
            "reason": reason,
        }
    return {
        "mode": "metadata_only",
        "uses_card_context": False,
        "reason": f"unknown_evidence_card_context_mode:{mode}",
    }


def _evidence_cards_from_drafts(
    drafts: list[_SegmentDraft],
    *,
    query: str,
    query_intents: dict[str, float],
    settings: BudgetedRSESettings,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for draft in drafts:
        for chunk in draft.chunks_in_segment:
            cards.extend(
                _evidence_cards_from_chunk(
                    chunk,
                    query=query,
                    query_intents=query_intents,
                    settings=settings,
                    parent_segment_id=draft.segment_id,
                )
            )
    return _dedupe_evidence_cards(cards)


def _evidence_cards_from_chunk(
    chunk: Chunk,
    *,
    query: str,
    query_intents: dict[str, float],
    settings: BudgetedRSESettings,
    parent_segment_id: str,
) -> list[dict[str, Any]]:
    metadata = _clean_metadata(chunk.metadata or {})
    child_evidence = metadata.get("source_chunk_evidence")
    if isinstance(child_evidence, list) and child_evidence:
        cards = []
        for index, evidence in enumerate(child_evidence):
            if not isinstance(evidence, dict):
                continue
            cards.append(
                _evidence_card_from_payload(
                    parent_chunk=chunk,
                    payload=evidence,
                    query=query,
                    query_intents=query_intents,
                    settings=settings,
                    parent_segment_id=parent_segment_id,
                    ordinal=index,
                )
            )
        if cards:
            return cards

    return [
        _evidence_card_from_payload(
            parent_chunk=chunk,
            payload={},
            query=query,
            query_intents=query_intents,
            settings=settings,
            parent_segment_id=parent_segment_id,
            ordinal=0,
        )
    ]


def _evidence_card_from_payload(
    *,
    parent_chunk: Chunk,
    payload: dict[str, Any],
    query: str,
    query_intents: dict[str, float],
    settings: BudgetedRSESettings,
    parent_segment_id: str,
    ordinal: int,
) -> dict[str, Any]:
    parent_metadata = _clean_metadata(parent_chunk.metadata or {})
    payload_metadata = _clean_metadata(payload or {})
    metadata = {**parent_metadata, **{key: value for key, value in payload_metadata.items() if value not in (None, "", [], {})}}
    chunk_id = str(payload_metadata.get("chunk_id") or parent_chunk.chunk_id)
    doc_id = str(metadata.get("doc_id") or "")
    raw_text = str(payload_metadata.get("snippet") or payload_metadata.get("text_span") or parent_chunk.text or "")
    text_span = _compact_card_span(raw_text, query=query, settings=settings)
    section_type_scores = _section_type_scores(metadata=metadata, text=text_span)
    intent_match_scores = _card_intent_match_scores(
        query=query,
        text=text_span,
        metadata=metadata,
        query_intents=query_intents,
        section_type_scores=section_type_scores,
    )
    facets = _facets_for_card(text=text_span, metadata=metadata)
    token_cost = estimate_tokens(text_span)
    exact_evidence = _source_evidence_from_card_payload(
        chunk_id=chunk_id,
        doc_id=doc_id,
        metadata=metadata,
        text_span=text_span,
    )
    return {
        "card_id": f"ecard:{chunk_id}:{ordinal}",
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "source_id": f"{doc_id}#{chunk_id}" if doc_id else chunk_id,
        "page": metadata.get("page"),
        "page_label": metadata.get("page_label"),
        "section_title": metadata.get("section_title"),
        "section_path": _jsonable_section_path(metadata.get("section_path")),
        "text_span": text_span,
        "text_search": metadata.get("text_search"),
        "char_range": metadata.get("char_range"),
        "bbox": metadata.get("bbox"),
        "pdf_url": metadata.get("pdf_url"),
        "section_type_scores": section_type_scores,
        "intent_match_scores": intent_match_scores,
        "facets_covered": facets,
        "authority_risk_flags": _authority_risk_flags(metadata),
        "token_cost": token_cost,
        "redundancy_key": _card_redundancy_key(doc_id=doc_id, metadata=metadata, text=text_span),
        "parent_segment_id": parent_segment_id,
        "parent_chunk_id": parent_chunk.chunk_id,
        "metadata": metadata,
        "source_chunk_evidence": [exact_evidence],
    }


def _compact_card_span(text: str, *, query: str, settings: BudgetedRSESettings) -> str:
    stripped = _strip_section_prefix(text or "").strip()
    if estimate_tokens(stripped) <= settings.max_card_tokens:
        return stripped
    return trim_to_matching_spans(
        stripped,
        query=query,
        max_tokens=settings.max_card_tokens,
        extra_text=query,
    )


def _query_intent_scores(query: str) -> dict[str, float]:
    lower = (query or "").lower()
    scores = {
        "definition": 0.0,
        "procedure": 0.0,
        "checklist": 0.0,
        "summary": 0.0,
        "comparison": 0.0,
        "evidence_basis": 0.0,
    }
    if re.search(r"\b(define|definition|meaning|what is|what are|refers? to)\b", lower):
        scores["definition"] = 0.72
    if re.search(r"\b(procedure|step|steps|sequence|before|after|follow|how do|how should)\b", lower):
        scores["procedure"] = 0.72
    if re.search(r"\b(checklist|check|review|inspect|inspection|areas?|items?|readiness)\b", lower):
        scores["checklist"] = 0.76
    if re.search(r"\b(summary|summarize|overview|explain|describe|cover|covers)\b", lower):
        scores["summary"] = 0.70
    if re.search(r"\b(compare|comparison|differ|difference|versus|vs|relationship|fit together|relate)\b", lower):
        scores["comparison"] = 0.78
    if re.search(r"\b(evidence|basis|cite|citation|source|according)\b", lower):
        scores["evidence_basis"] = 0.70
    if not any(scores.values()):
        scores["summary"] = 0.30
    return scores


def _section_type_scores(*, metadata: dict[str, Any], text: str) -> dict[str, float]:
    structural = " ".join(
        str(part or "")
        for part in (
            metadata.get("section_title"),
            _section_path_label(metadata.get("section_path")),
            metadata.get("source_type"),
        )
    ).lower()
    body = (text or "").lower()
    scores = {
        "definition": 0.0,
        "procedure": 0.0,
        "checklist": 0.0,
        "summary": 0.0,
        "comparison": 0.0,
        "table_or_list": 0.0,
    }
    if re.search(r"\b(definition|glossary|terms?)\b", structural) or re.search(r"\b(is defined as|means|refers to)\b", body):
        scores["definition"] = 0.72
    if re.search(r"\b(procedure|process|steps?|sequence)\b", structural) or re.search(r"(?<![A-Za-z0-9])(?:\(\d{1,2}\)|\d{1,2}[\.)])\s+", text or ""):
        scores["procedure"] = 0.82
    if re.search(r"\b(checklist|inspection|review|readiness)\b", structural) or _looks_like_checklist_text(text):
        scores["checklist"] = 0.84
    if re.search(r"\b(summary|overview|purpose|scope|introduction|about)\b", structural):
        scores["summary"] = 0.62
    if re.search(r"\b(compare|comparison|relationship|versus|interoperab|connect)\b", structural + " " + body):
        scores["comparison"] = 0.62
    if _looks_like_checklist_text(text) or "\n-" in (text or ""):
        scores["table_or_list"] = 0.76
    return scores


def _looks_like_checklist_text(text: str) -> bool:
    stripped = text or ""
    bullet_count = len(re.findall(r"(?m)^\s*(?:[-*+]|\u2022)\s+\S", stripped))
    question_count = stripped.count("?")
    return bullet_count >= 2 or question_count >= 2


def _card_intent_match_scores(
    *,
    query: str,
    text: str,
    metadata: dict[str, Any],
    query_intents: dict[str, float],
    section_type_scores: dict[str, float],
) -> dict[str, float]:
    query_terms = _support_tokens(query)
    card_terms = _support_tokens(f"{text} {metadata.get('section_title', '')} {_section_path_label(metadata.get('section_path'))}")
    overlap = len(query_terms & card_terms) / max(1, len(query_terms)) if query_terms else 0.0
    scores: dict[str, float] = {}
    for intent in ("definition", "procedure", "checklist", "summary", "comparison", "evidence_basis"):
        structure = section_type_scores.get(intent, 0.0)
        if intent == "evidence_basis" and metadata.get("text_search"):
            structure = max(structure, 0.65)
        scores[intent] = round(min(1.0, (0.66 * query_intents.get(intent, 0.0)) + (0.32 * structure) + (0.18 * overlap)), 6)
    return scores


def _facets_for_card(*, text: str, metadata: dict[str, Any]) -> list[str]:
    structural = f"{metadata.get('section_title', '')} {_section_path_label(metadata.get('section_path'))}".lower()
    lower = f"{structural} {text or ''}".lower()
    facets: list[str] = []
    if re.search(r"\b(is defined as|means|refers to|definition|what is|specifies|characterizes|represents|defines)\b", lower):
        facets.append("definition")
    if re.search(r"\b(purpose|objective|used to|intended to|goal)\b", lower) or re.search(
        r"\bthis\s+(?:document|report|publication|standard|guide)\s+(?:describes|provides|presents|explains)\b",
        lower,
    ):
        facets.append("purpose")
    if re.search(r"\b(scope|in scope|out of scope|includes?|included|excludes?|excluded|covers?)\b", lower):
        facets.append("scope")
    if re.search(r"\b(includes?|included|including|contains|consists of|areas?|items?|sources?|types?|kinds?|categories)\b", lower):
        facets.append("included items")
    if re.search(r"\b(excludes?|excluded|out of scope|not included|does not)\b", lower):
        facets.append("excluded items")
    if re.search(r"\b(must|shall|should|required|requirement|requirements|need to)\b", lower):
        facets.append("requirements")
    if re.search(r"(?<![A-Za-z0-9])(?:\(\d{1,2}\)|\d{1,2}[\.)])\s+", text or "") or re.search(r"\b(steps?|procedure|sequence|follow)\b", lower):
        facets.append("steps")
    if re.search(r"\b(checklist|check|inspection|review|areas?|readiness)\b", lower) or _looks_like_checklist_text(text):
        facets.append("checklist areas")
    if re.search(r"\b(limitations?|limited|cannot|not current|not proof|out of scope)\b", lower):
        facets.append("limitations")
    if re.search(r"\b(compare|relationship|relate|connect|fit together|concurrent|interoperab|versus)\b", lower):
        facets.append("relationships")
    if re.search(r"\b(example|for example|such as)\b", lower):
        facets.append("examples")
    if metadata.get("text_search") or metadata.get("char_range") or metadata.get("bbox") or metadata.get("page"):
        facets.append("evidence basis")
    return list(dict.fromkeys(facets))


def _authority_risk_flags(metadata: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if metadata.get("authority_level") in {"mandatory_procedure", "official_public_guidance"}:
        flags.append(str(metadata.get("authority_level")))
    if metadata.get("risk_level") in {"high", "medium"}:
        flags.append(f"risk:{metadata.get('risk_level')}")
    return flags


def _source_evidence_from_card_payload(
    *,
    chunk_id: str,
    doc_id: str,
    metadata: dict[str, Any],
    text_span: str,
) -> dict[str, Any]:
    evidence = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "page": metadata.get("page"),
        "page_label": metadata.get("page_label"),
        "section_title": metadata.get("section_title"),
        "section_path": _jsonable_section_path(metadata.get("section_path")),
        "snippet": _snippet(text_span, limit=SOURCE_CHUNK_EVIDENCE_SNIPPET_LIMIT),
    }
    for key in ("pdf_url", "bbox", "char_range", "text_search"):
        if metadata.get(key) not in (None, "", [], {}):
            evidence[key] = metadata.get(key)
    return {key: value for key, value in evidence.items() if value not in (None, "", [], {})}


def _card_redundancy_key(*, doc_id: str, metadata: dict[str, Any], text: str) -> str:
    section = _section_path_label(metadata.get("section_path")) or str(metadata.get("section_title") or "")
    text_key = " ".join(sorted(_support_tokens(text)))[:120]
    return f"{doc_id}|{section}|{text_key}"


def _dedupe_evidence_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for card in cards:
        key = (
            str(card.get("doc_id") or ""),
            str(card.get("chunk_id") or ""),
            str(card.get("text_search") or card.get("text_span") or "")[:240],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(card)
    return deduped


def _select_evidence_cards(
    cards: list[dict[str, Any]],
    *,
    query: str,
    query_intents: dict[str, float],
    settings: BudgetedRSESettings,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    remaining = list(cards)
    selected: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    target_facets = _target_facets_for_query(query=query, query_intents=query_intents)
    query_terms = _evidence_query_terms(query)
    query_bigrams = _support_bigrams(query)
    query_requests_resources = _query_requests_resource_listing(query)
    anchor_terms = _query_anchor_terms(query)
    required_heading_terms = _required_heading_query_terms(
        cards,
        query_terms=query_terms,
        max_rank=max(5, settings.max_evidence_cards),
    )
    covered_facets: set[str] = set()
    covered_anchors: set[str] = set()
    covered_query_terms: set[str] = set()
    redundancy_keys: set[str] = set()
    running_tokens = 0

    while remaining and len(selected) < settings.max_evidence_cards:
        best = max(
            remaining,
            key=lambda card: _evidence_card_selection_score(
                card,
                query_terms=query_terms,
                query_bigrams=query_bigrams,
                query_requests_resources=query_requests_resources,
                anchor_terms=anchor_terms,
                target_facets=target_facets,
                covered_facets=covered_facets,
                covered_anchors=covered_anchors,
                covered_query_terms=covered_query_terms,
                redundancy_keys=redundancy_keys,
                settings=settings,
            ),
        )
        best_score = _evidence_card_selection_score(
            best,
            query_terms=query_terms,
            query_bigrams=query_bigrams,
            query_requests_resources=query_requests_resources,
            anchor_terms=anchor_terms,
            target_facets=target_facets,
            covered_facets=covered_facets,
            covered_anchors=covered_anchors,
            covered_query_terms=covered_query_terms,
            redundancy_keys=redundancy_keys,
            settings=settings,
        )
        best_breakdown = _evidence_card_score_breakdown(
            best,
            query_terms=query_terms,
            query_bigrams=query_bigrams,
            query_requests_resources=query_requests_resources,
            anchor_terms=anchor_terms,
            target_facets=target_facets,
            covered_facets=covered_facets,
            covered_anchors=covered_anchors,
            covered_query_terms=covered_query_terms,
            redundancy_keys=redundancy_keys,
            settings=settings,
        )
        best["score_breakdown"] = best_breakdown
        remaining.remove(best)
        best_terms = _evidence_card_terms(best)
        best_facets = set(str(facet) for facet in best.get("facets_covered") or [])
        new_target_facets = (best_facets & target_facets) - covered_facets
        selected_definition_count = sum(
            1 for card in selected if "definition" in set(str(facet) for facet in card.get("facets_covered") or [])
        )
        comparison_definition_needed = (
            "relationships" in target_facets
            and "definition" in target_facets
            and "definition" in best_facets
            and selected_definition_count < 2
        )
        if (
            selected
            and query_terms
            and not ((best_terms & query_terms) - covered_query_terms)
            and not ((best_terms & anchor_terms) - covered_anchors)
            and not new_target_facets
            and not comparison_definition_needed
        ):
            dropped.append(_dropped_card_metadata(best, reason="no_new_query_support", score=best_score))
            continue
        if selected and best_score < settings.min_card_score:
            dropped.append(_dropped_card_metadata(best, reason="low_card_score", score=best_score))
            continue
        if selected and running_tokens + int(best.get("token_cost") or 0) > settings.evidence_card_token_budget:
            dropped.append(_dropped_card_metadata(best, reason="evidence_card_budget", score=best_score))
            continue

        selected.append(best)
        running_tokens += int(best.get("token_cost") or 0)
        covered_facets.update(str(facet) for facet in best.get("facets_covered") or [])
        card_terms = best_terms
        covered_anchors.update(card_terms & anchor_terms)
        covered_query_terms.update(card_terms & query_terms)
        redundancy_keys.add(str(best.get("redundancy_key") or ""))

        if _evidence_card_selection_sufficient(
            selected=selected,
            target_facets=target_facets,
            covered_facets=covered_facets,
            anchor_terms=anchor_terms,
            covered_anchors=covered_anchors,
            required_heading_terms=required_heading_terms,
            query_terms=query_terms,
            covered_query_terms=covered_query_terms,
            settings=settings,
        ):
            break

    for card in remaining:
        dropped.append(_dropped_card_metadata(card, reason="not_selected", score=0.0))

    return selected, {
        "target_facets": sorted(target_facets),
        "covered_facets": sorted(covered_facets),
        "target_anchors": sorted(anchor_terms),
        "covered_anchors": sorted(covered_anchors),
        "required_heading_terms": sorted(required_heading_terms),
        "query_term_coverage": round(len(covered_query_terms & query_terms) / max(1, len(query_terms)), 6) if query_terms else 0.0,
        "token_estimate": running_tokens,
        "dropped_cards": dropped,
    }


def _target_facets_for_query(*, query: str, query_intents: dict[str, float]) -> set[str]:
    lower = (query or "").lower()
    facets: set[str] = {"evidence basis"}
    if re.search(r"\b(purpose|objective|goal|why)\b", lower):
        facets.add("purpose")
    if query_intents.get("definition", 0.0) > 0:
        facets.add("definition")
    if query_intents.get("procedure", 0.0) > 0:
        facets.update({"steps", "requirements"})
    if query_intents.get("checklist", 0.0) > 0:
        facets.update({"checklist areas", "requirements"})
    if query_intents.get("summary", 0.0) > 0:
        if re.search(r"\b(purpose|objective|goal|why)\b", lower):
            facets.add("purpose")
        if re.search(r"\b(scope|scoped|coverage|within|exclude|excluded|out of scope)\b", lower):
            facets.add("scope")
        if re.search(r"\b(include|included|including|items?|areas?|sources?|types?|kinds?|categories|list|lists|which|cover|covers)\b", lower):
            facets.add("included items")
        if re.search(r"\b(limit|limits|limitation|limitations|limited|cannot|constraint|constraints)\b", lower):
            facets.add("limitations")
        if re.search(r"\b(need|needs|required|require|requires|requirement|requirements|must|shall|should|when)\b", lower):
            facets.add("requirements")
    if query_intents.get("comparison", 0.0) > 0:
        facets.update({"relationships", "included items", "definition"})
    return facets


def _evidence_card_selection_score(
    card: dict[str, Any],
    *,
    query_terms: set[str],
    query_bigrams: set[tuple[str, str]],
    query_requests_resources: bool,
    anchor_terms: set[str],
    target_facets: set[str],
    covered_facets: set[str],
    covered_anchors: set[str],
    covered_query_terms: set[str],
    redundancy_keys: set[str],
    settings: BudgetedRSESettings,
) -> float:
    return _evidence_card_score_breakdown(
        card,
        query_terms=query_terms,
        query_bigrams=query_bigrams,
        query_requests_resources=query_requests_resources,
        anchor_terms=anchor_terms,
        target_facets=target_facets,
        covered_facets=covered_facets,
        covered_anchors=covered_anchors,
        covered_query_terms=covered_query_terms,
        redundancy_keys=redundancy_keys,
        settings=settings,
    )["total"]


def _evidence_card_score_breakdown(
    card: dict[str, Any],
    *,
    query_terms: set[str],
    query_bigrams: set[tuple[str, str]],
    query_requests_resources: bool,
    anchor_terms: set[str],
    target_facets: set[str],
    covered_facets: set[str],
    covered_anchors: set[str],
    covered_query_terms: set[str],
    redundancy_keys: set[str],
    settings: BudgetedRSESettings,
) -> dict[str, float]:
    card_terms = _evidence_card_terms(card)
    heading_terms = _support_tokens(
        f"{card.get('section_title', '')} {_section_path_label(card.get('section_path'))}"
    )
    facets = set(str(facet) for facet in card.get("facets_covered") or [])
    facet_gain = len((facets & target_facets) - covered_facets)
    anchor_overlap = card_terms & anchor_terms
    anchor_gain = len(anchor_overlap - covered_anchors)
    query_term_gain = len((card_terms & query_terms) - covered_query_terms) / max(1, len(query_terms)) if query_terms else 0.0
    query_overlap = len(card_terms & query_terms) / max(1, len(query_terms)) if query_terms else 0.0
    card_search_text = _card_search_text(card)
    bigram_overlap = len(_support_bigrams(card_search_text) & query_bigrams) / max(1, len(query_bigrams)) if query_bigrams else 0.0
    heading_overlap = len(heading_terms & query_terms) / max(1, min(len(query_terms), len(heading_terms))) if heading_terms and query_terms else 0.0
    if covered_query_terms and query_term_gain == 0 and anchor_gain == 0:
        facet_gain = min(facet_gain, 1)
    intent_score = max((card.get("intent_match_scores") or {}).values() or [0.0])
    exact_locator_bonus = settings.card_exact_locator_bonus if card.get("text_search") or card.get("char_range") or card.get("bbox") else 0.0
    authority_bonus = settings.card_authority_bonus if card.get("authority_risk_flags") else 0.0
    checklist_priority = settings.card_checklist_priority_bonus if "checklist areas" in facets and "checklist areas" not in covered_facets else 0.0
    rank_bonus = 0.0
    candidate_rank = _card_candidate_rank(card)
    if candidate_rank is not None and candidate_rank <= 5 and (heading_overlap >= 0.28 or query_overlap >= 0.45):
        rank_bonus = settings.card_top_rank_bonus * ((6 - candidate_rank) / 5)
    redundancy_penalty = settings.card_redundancy_penalty if str(card.get("redundancy_key") or "") in redundancy_keys else 0.0
    resource_listing_penalty = settings.card_resource_listing_penalty if _looks_like_resource_listing(card_search_text) and not query_requests_resources else 0.0
    front_matter_penalty = settings.card_front_matter_penalty if _looks_like_front_matter_boilerplate(card_search_text) else 0.0
    token_penalty = min(settings.card_max_token_penalty, float(card.get("token_cost") or 0) / max(1, settings.evidence_card_token_budget))
    score = (
        (settings.card_facet_gain_weight * facet_gain)
        + (settings.card_anchor_gain_weight * anchor_gain)
        + (settings.card_query_term_gain_weight * query_term_gain)
        + (settings.card_query_overlap_weight * query_overlap)
        + (settings.card_bigram_overlap_weight * bigram_overlap)
        + (settings.card_heading_overlap_weight * heading_overlap)
        + (settings.card_intent_weight * intent_score)
        + exact_locator_bonus
        + authority_bonus
        + checklist_priority
        + rank_bonus
        - redundancy_penalty
        - resource_listing_penalty
        - front_matter_penalty
        - token_penalty
    )
    return {
        "facet_gain": round(settings.card_facet_gain_weight * facet_gain, 6),
        "anchor_gain": round(settings.card_anchor_gain_weight * anchor_gain, 6),
        "query_term_gain": round(settings.card_query_term_gain_weight * query_term_gain, 6),
        "query_overlap": round(settings.card_query_overlap_weight * query_overlap, 6),
        "bigram_overlap": round(settings.card_bigram_overlap_weight * bigram_overlap, 6),
        "heading_overlap": round(settings.card_heading_overlap_weight * heading_overlap, 6),
        "intent_match": round(settings.card_intent_weight * intent_score, 6),
        "exact_locator_bonus": round(exact_locator_bonus, 6),
        "authority_bonus": round(authority_bonus, 6),
        "checklist_priority_bonus": round(checklist_priority, 6),
        "rank_bonus": round(rank_bonus, 6),
        "redundancy_penalty": round(redundancy_penalty, 6),
        "resource_listing_penalty": round(resource_listing_penalty, 6),
        "front_matter_penalty": round(front_matter_penalty, 6),
        "token_penalty": round(token_penalty, 6),
        "total": round(score, 6),
    }


def _card_search_text(card: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in (
            card.get("text_span"),
            card.get("section_title"),
            _section_path_label(card.get("section_path")),
        )
    )


def _evidence_card_terms(card: dict[str, Any]) -> set[str]:
    text = _card_search_text(card)
    return _support_tokens(text) | _query_anchor_terms(text)


def _query_requests_resource_listing(query: str) -> bool:
    return bool(
        re.search(
            r"\b(resource|resources|tool|tools|website|web site|web-based|guidance|guide|references?|materials?|available|supplemental)\b",
            (query or "").lower(),
        )
    )


def _looks_like_resource_listing(text: str) -> bool:
    lower = (text or "").lower()
    resource_hits = len(
        re.findall(
            r"\b(resource|resources|tool|tools|website|web site|web-based|guidance|guide|references?|materials?|available|supplemental|interpretive)\b",
            lower,
        )
    )
    return resource_hits >= 2


def _looks_like_front_matter_boilerplate(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        re.search(
            r"\b(?:publication is available|available free of charge|commercial systems? (?:are )?identified|"
            r"describe an experimental procedure or concept adequately|copyright|disclaimer)\b",
            lower,
        )
    )


def _card_candidate_rank(card: dict[str, Any]) -> int | None:
    raw_rank = (card.get("metadata") or {}).get("context_candidate_rank")
    if isinstance(raw_rank, int):
        return raw_rank
    if isinstance(raw_rank, str):
        try:
            return int(raw_rank)
        except ValueError:
            return None
    return None


def _required_heading_query_terms(
    cards: list[dict[str, Any]],
    *,
    query_terms: set[str],
    max_rank: int,
) -> set[str]:
    required: set[str] = set()
    if not query_terms:
        return required
    for card in cards:
        rank = _card_candidate_rank(card)
        if rank is None or rank > max_rank:
            continue
        heading_text = f"{card.get('section_title', '')} {_section_path_label(card.get('section_path'))}"
        heading_terms = _support_tokens(heading_text) | _query_anchor_terms(heading_text)
        required.update(heading_terms & query_terms)
    return required


def _evidence_card_selection_sufficient(
    *,
    selected: list[dict[str, Any]],
    target_facets: set[str],
    covered_facets: set[str],
    anchor_terms: set[str],
    covered_anchors: set[str],
    required_heading_terms: set[str],
    query_terms: set[str],
    covered_query_terms: set[str],
    settings: BudgetedRSESettings,
) -> bool:
    if not selected:
        return False
    anchor_ok = not anchor_terms or anchor_terms <= covered_anchors
    if target_facets:
        required = set(target_facets)
        if "included items" in required and "checklist areas" in covered_facets:
            required.discard("included items")
        facet_ok = required <= covered_facets
    else:
        facet_ok = True
    query_coverage = len(covered_query_terms & query_terms) / max(1, len(query_terms)) if query_terms else 1.0
    query_ok = query_coverage >= settings.min_evidence_query_term_coverage
    heading_topic_ok = not required_heading_terms or required_heading_terms <= covered_query_terms
    return anchor_ok and facet_ok and query_ok and heading_topic_ok


def _dropped_card_metadata(card: dict[str, Any], *, reason: str, score: float) -> dict[str, Any]:
    return {
        "card_id": card.get("card_id"),
        "chunk_id": card.get("chunk_id"),
        "reason": reason,
        "score": round(score, 6),
        "score_breakdown": card.get("score_breakdown") or {"total": round(score, 6)},
        "token_cost": card.get("token_cost"),
    }


def _chunk_from_evidence_card(card: dict[str, Any], *, builder: str) -> Chunk:
    metadata = dict(card.get("metadata") or {})
    evidence = card.get("source_chunk_evidence") or []
    public_card = _public_evidence_card(card)
    metadata.update(
        {
            "context_builder": builder,
            "context_segment_id": card.get("parent_segment_id"),
            "seed_chunk_id": card.get("parent_chunk_id"),
            "child_chunk_ids": [card.get("chunk_id")],
            "segment_chunk_ids": [card.get("chunk_id")],
            "source_chunk_evidence": evidence,
            "evidence_card": public_card,
            "page": card.get("page"),
            "page_label": card.get("page_label"),
            "section_title": card.get("section_title"),
            "section_path": card.get("section_path"),
        }
    )
    for key in ("pdf_url", "bbox", "char_range", "text_search"):
        if card.get(key) not in (None, "", [], {}):
            metadata[key] = card.get(key)
    heading = str(card.get("section_title") or "").strip()
    text = str(card.get("text_span") or "").strip()
    if heading and not text.lower().startswith("[section:"):
        text = f"[Section: {heading}] {text}"
    return Chunk(chunk_id=str(card.get("chunk_id") or card.get("card_id")), text=text, metadata=metadata)


def _public_evidence_card(card: dict[str, Any]) -> dict[str, Any]:
    public_keys = (
        "card_id",
        "doc_id",
        "chunk_id",
        "source_id",
        "page",
        "page_label",
        "section_title",
        "section_path",
        "text_span",
        "text_search",
        "char_range",
        "bbox",
        "pdf_url",
        "section_type_scores",
        "intent_match_scores",
        "facets_covered",
        "authority_risk_flags",
        "token_cost",
        "score_breakdown",
        "redundancy_key",
        "parent_segment_id",
        "parent_chunk_id",
    )
    return {key: card.get(key) for key in public_keys if card.get(key) not in (None, "", [], {})}


def _apply_global_context_budget(
    drafts: list[_SegmentDraft],
    *,
    settings: BudgetedRSESettings,
    query: str = "",
) -> tuple[list[_SegmentDraft], dict[str, Any]]:
    kept: list[_SegmentDraft] = []
    kept_metadata: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    running_tokens = 0
    query_terms = _support_tokens(query)
    anchor_terms = _query_anchor_terms(query)
    coverage_limited = bool(query_terms and len(anchor_terms) >= 2 and _query_uses_comparison(query))
    ordered_drafts = (
        _order_budgeted_drafts_for_global_support(
            drafts,
            query_terms=query_terms,
            anchor_terms=anchor_terms,
        )
        if anchor_terms
        else list(drafts)
    )
    covered_terms: set[str] = set()
    covered_anchors: set[str] = set()

    for draft in ordered_drafts:
        draft_terms = _support_tokens(draft.text)
        anchor_overlap = draft_terms & anchor_terms
        anchor_gain = anchor_overlap - covered_anchors
        term_gain = (draft_terms & query_terms) - covered_terms

        if coverage_limited and kept and _global_support_sufficient(
            query_terms=query_terms,
            anchor_terms=anchor_terms,
            covered_terms=covered_terms,
            covered_anchors=covered_anchors,
            kept_count=len(kept),
            settings=settings,
        ):
            dropped.append(_dropped_segment_metadata(draft, reason="support_sufficient"))
            continue

        if (
            coverage_limited
            and kept
            and not anchor_overlap
            and len(term_gain) / max(1, len(query_terms)) < settings.min_global_segment_gain
        ):
            dropped.append(_dropped_segment_metadata(draft, reason="low_global_marginal_gain"))
            continue

        draft_tokens = draft.token_estimate_after_compression
        if kept and running_tokens + draft_tokens > settings.max_context_tokens:
            dropped.append(_dropped_segment_metadata(draft, reason="global_context_budget"))
            continue
        if not kept and draft_tokens > settings.max_context_tokens:
            kept.append(draft)
            kept_metadata.append(_kept_segment_metadata(draft, reason="kept_as_best_available_over_budget"))
            running_tokens += draft_tokens
            covered_terms.update(draft_terms & query_terms)
            covered_anchors.update(anchor_overlap)
            continue
        kept.append(draft)
        kept_metadata.append(_kept_segment_metadata(draft, reason="selected_for_context_budget"))
        running_tokens += draft_tokens
        covered_terms.update(draft_terms & query_terms)
        covered_anchors.update(anchor_overlap)

    return kept, {
        "max_context_tokens": settings.max_context_tokens,
        "token_estimate": running_tokens,
        "kept_segment_ids": [draft.segment_id for draft in kept],
        "kept_segments": kept_metadata,
        "dropped_segments": dropped,
    }


def _order_budgeted_drafts_for_global_support(
    drafts: list[_SegmentDraft],
    *,
    query_terms: set[str],
    anchor_terms: set[str],
) -> list[_SegmentDraft]:
    remaining = list(drafts)
    ordered: list[_SegmentDraft] = []
    covered_terms: set[str] = set()
    covered_anchors: set[str] = set()
    while remaining:
        best = max(
            remaining,
            key=lambda draft: _global_support_sort_key(
                draft,
                query_terms=query_terms,
                anchor_terms=anchor_terms,
                covered_terms=covered_terms,
                covered_anchors=covered_anchors,
            ),
        )
        remaining.remove(best)
        ordered.append(best)
        best_terms = _support_tokens(best.text)
        covered_terms.update(best_terms & query_terms)
        covered_anchors.update(best_terms & anchor_terms)
    return ordered


def _global_support_sort_key(
    draft: _SegmentDraft,
    *,
    query_terms: set[str],
    anchor_terms: set[str],
    covered_terms: set[str],
    covered_anchors: set[str],
) -> tuple[int, int, int, float, float]:
    draft_terms = _support_tokens(draft.text)
    anchor_overlap = draft_terms & anchor_terms
    anchor_gain = anchor_overlap - covered_anchors
    term_gain = (draft_terms & query_terms) - covered_terms
    return (
        len(anchor_gain),
        len(anchor_overlap),
        len(term_gain),
        draft.score,
        -float(draft.token_estimate_after_compression),
    )


def _global_support_sufficient(
    *,
    query_terms: set[str],
    anchor_terms: set[str],
    covered_terms: set[str],
    covered_anchors: set[str],
    kept_count: int,
    settings: BudgetedRSESettings,
) -> bool:
    if not query_terms or kept_count <= 0:
        return False
    coverage = len(query_terms & covered_terms) / max(1, len(query_terms))
    return (
        bool(anchor_terms)
        and kept_count >= 2
        and anchor_terms <= covered_anchors
        and coverage >= settings.min_anchor_query_coverage
    )


def _dropped_segment_metadata(draft: _SegmentDraft, *, reason: str) -> dict[str, Any]:
    return {
        "segment_id": draft.segment_id,
        "seed_chunk_id": draft.seed_chunk_id,
        "reason": reason,
        "segment_score": round(draft.score, 6),
        "token_estimate_after_compression": draft.token_estimate_after_compression,
    }


def _kept_segment_metadata(draft: _SegmentDraft, *, reason: str) -> dict[str, Any]:
    return {
        "segment_id": draft.segment_id,
        "seed_chunk_id": draft.seed_chunk_id,
        "reason": reason,
        "segment_score": round(draft.score, 6),
        "token_estimate_after_compression": draft.token_estimate_after_compression,
    }


def _candidate_info(candidates: Iterable[ScoredChunk]) -> dict[str, _CandidateInfo]:
    info: dict[str, _CandidateInfo] = {}
    for rank, scored in enumerate(candidates, start=1):
        score = _best_score(scored)
        info[scored.chunk.chunk_id] = _CandidateInfo(
            score=score if score is not None else 1.0 / rank,
            rank=rank,
        )
    return info


def _annotate_evidence_card_candidate_ranks(
    chunks: Iterable[Chunk],
    candidate_info: dict[str, _CandidateInfo],
) -> None:
    for chunk in chunks:
        info = candidate_info.get(chunk.chunk_id)
        if info is None:
            continue
        chunk.metadata = {
            **_clean_metadata(chunk.metadata),
            "context_candidate_rank": info.rank,
            "context_candidate_score": info.score,
        }


def _preserve_top_related_candidates(
    *,
    query: str,
    selected_chunks: list[Chunk],
    candidates: list[ScoredChunk],
    settings: BudgetedRSESettings,
    max_rank: int = 5,
) -> list[Chunk]:
    if not selected_chunks or not candidates or not _query_needs_related_sections(query):
        return selected_chunks

    query_terms = _support_tokens(query)
    if not query_terms:
        return selected_chunks

    preserved = list(selected_chunks)
    preserved_ids = {chunk.chunk_id for chunk in preserved}
    selected_doc_ids = {
        str((_clean_metadata(chunk.metadata).get("doc_id") or ""))
        for chunk in selected_chunks
    }
    selected_doc_ids.discard("")
    selected_text = " ".join(_chunk_text_with_metadata(chunk) for chunk in selected_chunks)
    selected_terms = _support_tokens(selected_text) | _query_anchor_terms(selected_text)

    for rank, scored in enumerate(candidates, start=1):
        if rank > max_rank:
            break
        chunk = scored.chunk
        if chunk.chunk_id in preserved_ids:
            continue
        candidate_terms = _support_tokens(_chunk_text_with_metadata(chunk))
        overlap = query_terms & candidate_terms
        if len(overlap) < 2:
            continue
        candidate_doc_id = str(_clean_metadata(chunk.metadata).get("doc_id") or "")
        cross_doc_without_gain = (
            settings.require_cross_doc_query_term_gain_for_preservation
            and selected_doc_ids
            and candidate_doc_id
            and candidate_doc_id not in selected_doc_ids
            and not (overlap - selected_terms)
        )
        if cross_doc_without_gain:
            continue
        if overlap - selected_terms or rank <= max_rank:
            chunk.metadata = {
                **_clean_metadata(chunk.metadata),
                "context_candidate_supplement": True,
                "context_candidate_rank": rank,
            }
            preserved.append(chunk)
            preserved_ids.add(chunk.chunk_id)

    return preserved


def _preserve_top_evidence_card_candidates(
    *,
    query: str,
    selected_chunks: list[Chunk],
    candidates: list[ScoredChunk],
    max_rank: int = 5,
) -> list[Chunk]:
    if not selected_chunks or not candidates:
        return selected_chunks

    query_terms = _support_tokens(query) | _query_anchor_terms(query)
    if not query_terms:
        return selected_chunks
    query_intents = _query_intent_scores(query)
    target_facets = _target_facets_for_query(query=query, query_intents=query_intents)

    preserved = list(selected_chunks)
    preserved_ids = {chunk.chunk_id for chunk in preserved}
    selected_text = " ".join(_chunk_text_with_metadata(chunk) for chunk in selected_chunks)
    selected_terms = _support_tokens(selected_text) | _query_anchor_terms(selected_text)

    for rank, scored in enumerate(candidates, start=1):
        if rank > max_rank:
            break
        chunk = scored.chunk
        if chunk.chunk_id in preserved_ids:
            continue
        metadata = _clean_metadata(chunk.metadata)
        heading_text = f"{metadata.get('section_title', '')} {_section_path_label(metadata.get('section_path'))}"
        heading_terms = _support_tokens(heading_text) | _query_anchor_terms(heading_text)
        chunk_text = _chunk_text_with_metadata(chunk)
        body_terms = _support_tokens(chunk_text) | _query_anchor_terms(chunk_text)
        heading_overlap = query_terms & heading_terms
        body_overlap = query_terms & body_terms
        new_terms = body_overlap - selected_terms
        candidate_facets = set(_facets_for_card(text=chunk.text, metadata=metadata))

        heading_ratio = len(heading_overlap) / max(1, min(len(query_terms), len(heading_terms)))
        strong_heading_match = len(heading_overlap) >= 2 and heading_ratio >= 0.34
        high_rank_novel_support = rank <= 3 and len(new_terms) >= 2 and len(body_overlap) >= 2
        target_facet_support = rank <= max_rank and bool(candidate_facets & target_facets) and bool(body_overlap or heading_overlap)
        if not (strong_heading_match or high_rank_novel_support or target_facet_support):
            continue

        chunk.metadata = {
            **metadata,
            "context_candidate_supplement": True,
            "context_candidate_rank": rank,
            "context_candidate_reason": "top_retrieval_evidence_card_support",
        }
        preserved.append(chunk)
        preserved_ids.add(chunk.chunk_id)

    return preserved


def _chunk_text_with_metadata(chunk: Chunk) -> str:
    metadata = _clean_metadata(chunk.metadata)
    section_path = metadata.get("section_path")
    if isinstance(section_path, list):
        section_path = " > ".join(str(part) for part in section_path if part)
    return (
        f"{chunk.text} {metadata.get('section_title', '')} {section_path or ''} "
        f"{metadata.get('snippet', '')} {metadata.get('text_search', '')}"
    )


def _best_score(scored: ScoredChunk) -> float | None:
    for value in (
        scored.boosted_score,
        scored.fusion_score,
        scored.vector_score,
        scored.keyword_score,
    ):
        if value is not None:
            return float(value)
    return None


def _evaluate_budgeted_neighbor(
    *,
    query: str,
    seed: Chunk,
    neighbor: Chunk,
    segment_chunks: list[Chunk],
    candidate_info: dict[str, _CandidateInfo],
    running_tokens: int,
    settings: BudgetedRSESettings,
    side: str,
) -> dict[str, Any]:
    neighbor.metadata = _clean_metadata(neighbor.metadata)
    seed_doc_id = str(seed.metadata.get("doc_id") or "")
    neighbor_doc_id = str(neighbor.metadata.get("doc_id") or "")
    token_estimate = estimate_tokens(_strip_section_prefix(neighbor.text))
    base_payload: dict[str, Any] = {
        "side": side,
        "chunk_id": neighbor.chunk_id,
        "chunk_index": _chunk_index(neighbor),
        "token_estimate": token_estimate,
    }
    if seed_doc_id and neighbor_doc_id and seed_doc_id != neighbor_doc_id:
        return {
            **base_payload,
            "decision": "exclude",
            "reason": "different_document",
            "marginal_gain": 0.0,
        }

    if running_tokens + token_estimate > settings.max_segment_tokens:
        return {
            **base_payload,
            "decision": "exclude",
            "reason": "segment_budget",
            "marginal_gain": 0.0,
        }

    continuity, continuity_bonus = _budgeted_continuity(
        query=query,
        seed_metadata=seed.metadata,
        neighbor_metadata=neighbor.metadata,
        settings=settings,
    )
    if continuity == "break":
        return {
            **base_payload,
            "decision": "exclude",
            "reason": "continuity_break",
            "marginal_gain": 0.0,
        }
    if _starts_new_ordered_sequence_after_segment(side=side, segment_chunks=segment_chunks, neighbor=neighbor):
        return {
            **base_payload,
            "decision": "exclude",
            "reason": "ordered_sequence_restart",
            "marginal_gain": 0.0,
            "continuity": continuity,
        }

    query_terms = _support_tokens(query)
    neighbor_terms = _support_tokens(_chunk_text_with_metadata(neighbor))
    segment_terms = _support_tokens(" ".join(_chunk_text_with_metadata(chunk) for chunk in segment_chunks))
    matching_terms = sorted(query_terms & neighbor_terms)
    missing_terms = sorted((query_terms & neighbor_terms) - segment_terms)
    relevance = len(matching_terms) / max(1, len(query_terms)) if query_terms else 0.0
    missing_gain = len(missing_terms) / max(1, len(query_terms)) if query_terms else 0.0

    structured_bonus = _structured_neighbor_bonus(
        query=query,
        neighbor=neighbor,
        matching_terms=matching_terms,
        settings=settings,
    )
    if (
        relevance < settings.min_relevance
        and missing_gain < settings.min_missing_facet_gain
        and structured_bonus <= 0
    ):
        return {
            **base_payload,
            "decision": "exclude",
            "reason": "low_relevance",
            "marginal_gain": 0.0,
            "relevance": round(relevance, 6),
            "missing_facet_gain": round(missing_gain, 6),
            "matching_query_terms": matching_terms,
            "missing_query_terms": missing_terms,
            "continuity": continuity,
        }

    redundancy = 0.0
    if neighbor_terms:
        redundancy = len(neighbor_terms & segment_terms) / len(neighbor_terms)
    heading_match = _heading_match_score(query_terms=query_terms, metadata=neighbor.metadata)
    authority_bonus = _authority_risk_bonus(neighbor.metadata, settings=settings)
    token_cost = token_estimate / max(1, settings.max_segment_tokens)
    candidate_score = candidate_info.get(neighbor.chunk_id, _CandidateInfo(0.0, 9999)).score
    marginal_gain = (
        (0.70 * relevance)
        + (1.00 * missing_gain)
        + continuity_bonus
        + structured_bonus
        + (settings.heading_match_weight * heading_match)
        + authority_bonus
        + (settings.retrieval_score_weight * min(1.0, max(0.0, candidate_score)))
        - (settings.redundancy_penalty_weight * redundancy)
        - (settings.token_cost_penalty_weight * token_cost)
    )

    return {
        **base_payload,
        "decision": "candidate",
        "reason": "scored",
        "marginal_gain": round(marginal_gain, 6),
        "relevance": round(relevance, 6),
        "missing_facet_gain": round(missing_gain, 6),
        "matching_query_terms": matching_terms,
        "missing_query_terms": missing_terms,
        "continuity": continuity,
        "redundancy": round(redundancy, 6),
        "heading_match": round(heading_match, 6),
        "authority_risk_bonus": round(authority_bonus, 6),
        "token_cost": round(token_cost, 6),
        "retrieval_score": round(candidate_score, 6),
    }


def _budgeted_continuity(
    *,
    query: str,
    seed_metadata: dict[str, Any],
    neighbor_metadata: dict[str, Any],
    settings: BudgetedRSESettings,
) -> tuple[str, float]:
    seed_key = _section_key(seed_metadata)
    neighbor_key = _section_key(neighbor_metadata)
    if seed_key and neighbor_key and seed_key == neighbor_key:
        return "same_section", settings.same_section_bonus
    if _query_needs_related_sections(query) and _is_related_section_neighbor(seed_metadata, neighbor_metadata):
        return "related_section", settings.related_section_bonus
    if not seed_key or not neighbor_key:
        seed_page = _metadata_int(seed_metadata, "page")
        neighbor_page = _metadata_int(neighbor_metadata, "page")
        if seed_page is not None and neighbor_page is not None and abs(seed_page - neighbor_page) <= 1:
            return "adjacent_page", settings.related_section_bonus / 2.0
    return "break", 0.0


def _heading_match_score(*, query_terms: set[str], metadata: dict[str, Any]) -> float:
    if not query_terms:
        return 0.0
    heading_terms = _support_tokens(
        f"{metadata.get('section_title', '')} {_section_path_label(metadata.get('section_path'))}"
    )
    return len(query_terms & heading_terms) / max(1, len(query_terms))


def _authority_risk_bonus(metadata: dict[str, Any], *, settings: BudgetedRSESettings) -> float:
    if metadata.get("authority_level") in {"mandatory_procedure", "official_public_guidance"}:
        return settings.authority_risk_bonus
    if metadata.get("risk_level") == "high":
        return settings.authority_risk_bonus / 2.0
    return 0.0


def _structured_neighbor_bonus(
    *,
    query: str,
    neighbor: Chunk,
    matching_terms: list[str],
    settings: BudgetedRSESettings,
) -> float:
    if not _query_needs_related_sections(query):
        return 0.0
    text = _strip_section_prefix(neighbor.text)
    if re.search(r"(?<![A-Za-z0-9])(?:\(\d{1,2}\)|\d{1,2}[\.)])\s+", text):
        return settings.structured_sequence_bonus
    if _is_short_bullet_continuation(text, max_tokens=settings.short_bullet_max_tokens) and (
        matching_terms or _query_anchor_terms(query)
    ):
        return settings.structured_short_bullet_bonus
    if re.search(r"\b(step|procedure|checklist|function|category|subcategory|section|requirement)s?\b", text, re.I):
        return settings.structured_keyword_bonus
    return 0.0


def _is_short_bullet_continuation(text: str, *, max_tokens: int = 48) -> bool:
    stripped = (text or "").strip()
    if not re.match(r"^(?:[-*+]|\u2022)\s+\S", stripped):
        return False
    return estimate_tokens(stripped) <= max_tokens


def _starts_new_ordered_sequence_after_segment(
    *,
    side: str,
    segment_chunks: list[Chunk],
    neighbor: Chunk,
) -> bool:
    if side != "right":
        return False
    segment_text = " ".join(_strip_section_prefix(chunk.text) for chunk in segment_chunks)
    if not re.search(r"(?<![A-Za-z0-9])(?:\(\d{1,2}\)|\d{1,2}[\.)])\s+", segment_text):
        return False
    neighbor_text = _strip_section_prefix(neighbor.text).lstrip()
    return bool(re.match(r"(?<![A-Za-z0-9])(?:\(1\)|1[\.)])\s+", neighbor_text))


def _score_segment(
    *,
    query: str,
    child_chunks: list[Chunk],
    chunks_in_segment: list[Chunk],
    candidate_info: dict[str, _CandidateInfo],
    settings: BudgetedRSESettings | None = None,
) -> float:
    max_child_score = max(
        (candidate_info.get(chunk.chunk_id, _CandidateInfo(0.0, 9999)).score for chunk in child_chunks),
        default=0.0,
    )
    query_terms = _support_tokens(query)
    segment_terms = _support_tokens(" ".join(chunk.text for chunk in chunks_in_segment))
    coverage_bonus = 0.0
    if query_terms:
        coverage_bonus = 0.15 * (len(query_terms & segment_terms) / len(query_terms))

    metadata_bonus = 0.0
    first_meta = chunks_in_segment[0].metadata if chunks_in_segment else {}
    if first_meta.get("section_path") or first_meta.get("section_title"):
        metadata_bonus += 0.03
    if first_meta.get("page") or first_meta.get("page_start"):
        metadata_bonus += 0.02
    if first_meta.get("authority_level") in {"mandatory_procedure", "official_public_guidance"}:
        metadata_bonus += 0.05
    if settings and query_terms:
        metadata_text = " ".join(_chunk_metadata_search_text(chunk) for chunk in chunks_in_segment)
        metadata_terms = _support_tokens(metadata_text) | _query_anchor_terms(metadata_text)
        metadata_coverage = len(query_terms & metadata_terms) / max(1, len(query_terms))
        metadata_bonus += settings.segment_metadata_query_coverage_weight * metadata_coverage
        best_rank = min(
            (candidate_info.get(chunk.chunk_id, _CandidateInfo(0.0, 9999)).rank for chunk in child_chunks),
            default=9999,
        )
        max_rank = max(1, int(settings.segment_top_rank_metadata_max_rank))
        if best_rank <= max_rank and metadata_coverage >= settings.segment_top_rank_metadata_min_coverage:
            metadata_bonus += settings.segment_top_rank_metadata_bonus * ((max_rank + 1 - best_rank) / max_rank)
    return max_child_score + coverage_bonus + metadata_bonus


def _chunk_metadata_search_text(chunk: Chunk) -> str:
    metadata = _clean_metadata(chunk.metadata)
    section_path = metadata.get("section_path")
    if isinstance(section_path, list):
        section_path = " > ".join(str(part) for part in section_path if part)
    return " ".join(
        str(part or "")
        for part in (
            metadata.get("title"),
            metadata.get("section_title"),
            section_path,
            metadata.get("snippet"),
            metadata.get("text_search"),
        )
    )


def _format_segment_text(chunks: list[Chunk], *, supplemental_text: str = "") -> str:
    if not chunks:
        return ""
    first_meta = chunks[0].metadata
    heading = _format_section_heading(first_meta)
    body = "\n\n".join(_strip_section_prefix(chunk.text).strip() for chunk in chunks if chunk.text)
    if supplemental_text:
        body = f"{body}\n\n{supplemental_text}" if body else supplemental_text
    return _combine_heading_body(heading, body)


def _format_section_heading(metadata: dict[str, Any]) -> str:
    section_title = metadata.get("section_title") or "Unknown section"
    section_path = _section_path_label(metadata.get("section_path"))
    if section_path and section_path != section_title:
        return f"[Section: {section_title}]\n[Section path: {section_path}]"
    return f"[Section: {section_title}]"


def _split_heading_and_body(text: str) -> tuple[str, str]:
    lines = (text or "").splitlines()
    heading_lines: list[str] = []
    body_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[Section:") or stripped.startswith("[Section path:"):
            heading_lines.append(stripped)
            body_start = index + 1
            continue
        if not stripped and heading_lines:
            body_start = index + 1
            continue
        break
    if not heading_lines:
        return "", text or ""
    return "\n".join(heading_lines), "\n".join(lines[body_start:]).strip()


def _combine_heading_body(heading: str, body: str) -> str:
    if heading and body:
        return f"{heading}\n{body.strip()}"
    return heading or body.strip()


def _strip_section_prefix(text: str) -> str:
    return SECTION_PREFIX_RE.sub("", text or "").strip()


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    sentences = [
        sentence.strip(" ;")
        for sentence in re.split(r"(?<=[.!?])\s+|(?<=\))\s+(?=[A-Z])", normalized)
        if sentence.strip(" ;")
    ]
    return sentences or [normalized]


def _sentence_score(
    sentence: str,
    *,
    query_terms: set[str],
    extra_terms: set[str],
) -> float:
    sentence_terms = _support_tokens(sentence)
    score = 2.0 * len(sentence_terms & query_terms)
    score += 0.75 * len(sentence_terms & extra_terms)
    return score


def _required_evidence_indices(
    sentences: list[str],
    *,
    query_terms: set[str],
    extra_terms: set[str],
) -> list[int]:
    required: list[int] = []
    for terms in (query_terms, extra_terms):
        if not terms:
            continue
        best_index = None
        best_overlap = 0
        for index, sentence in enumerate(sentences):
            overlap = len(_support_tokens(sentence) & terms)
            if overlap > best_overlap:
                best_index = index
                best_overlap = overlap
        if best_index is not None and best_overlap > 0 and best_index not in required:
            required.append(best_index)
    return required


def _support_tokens(text: str) -> set[str]:
    return set(_support_token_sequence(text))


def _support_token_sequence(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in WORD_RE.findall((text or "").lower()):
        token = _stem(raw)
        if len(token) < 3 or token in CONTEXT_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _support_bigrams(text: str) -> set[tuple[str, str]]:
    tokens = _support_token_sequence(text)
    return set(zip(tokens, tokens[1:]))


def _evidence_query_terms(text: str) -> set[str]:
    return _support_tokens(text) - QUERY_ACTION_TERMS


def _query_anchor_terms(text: str) -> set[str]:
    anchors: set[str] = set()
    for raw in TOKEN_WORD_RE.findall(text or ""):
        if not _looks_like_query_anchor(raw):
            continue
        for part in WORD_RE.findall(raw.lower()):
            token = _stem(part)
            if (len(token) < 3 and not _looks_like_short_code_token(token)) or token in CONTEXT_STOPWORDS:
                continue
            anchors.add(token)
    return anchors


def _looks_like_query_anchor(raw: str) -> bool:
    token = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", raw or "")
    if _looks_like_short_code_token(token.lower()):
        return True
    if any(char.isdigit() for char in token):
        return True
    if len(token) < 3:
        return False
    if token.isupper() and len(token) > 1:
        return True
    return any(char.isupper() for char in token[1:])


def _looks_like_short_code_token(token: str) -> bool:
    return 2 <= len(token or "") < 3 and any(char.isalpha() for char in token) and any(char.isdigit() for char in token)


def _stem(token: str) -> str:
    if token.startswith("reenerg"):
        return "reenerg"
    if token.startswith("notif"):
        return "notif"
    if token.startswith("remov"):
        return "remov"
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
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


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if isinstance(value, str) and value[:1] in {"[", "{"}:
            try:
                clean[key] = json.loads(value)
                continue
            except Exception:
                pass
        clean[key] = value
    return clean


def _clean_chunk(chunk: Chunk) -> Chunk:
    chunk.metadata = _clean_metadata(chunk.metadata)
    return chunk


def _sort_chunks(chunks: list[Chunk]) -> list[Chunk]:
    return sorted(chunks, key=lambda chunk: (_chunk_index(chunk) if _chunk_index(chunk) is not None else 10**9))


def _chunk_index(chunk: Chunk) -> int | None:
    metadata_index = _clean_metadata(chunk.metadata).get("chunk_index")
    if isinstance(metadata_index, int):
        return metadata_index
    if isinstance(metadata_index, str):
        try:
            return int(metadata_index)
        except ValueError:
            pass
    match = re.search(r"_c(\d+)$", chunk.chunk_id or "")
    if match:
        return int(match.group(1))
    return None


def _section_key(metadata: dict[str, Any]) -> str | None:
    clean = _clean_metadata(metadata)
    section_path = clean.get("section_path")
    if section_path:
        return f"path:{_section_path_label(section_path).lower()}"
    section_title = clean.get("section_title")
    if section_title:
        return f"title:{str(section_title).strip().lower()}"
    return None


def _parent_section_key(metadata: dict[str, Any]) -> str | None:
    clean = _clean_metadata(metadata)
    section_path = _jsonable_section_path(clean.get("section_path"))
    if isinstance(section_path, list) and len(section_path) > 1:
        return " > ".join(str(part).strip().lower() for part in section_path[:-1] if str(part).strip())
    if isinstance(section_path, str) and ">" in section_path:
        parts = [part.strip().lower() for part in section_path.split(">") if part.strip()]
        if len(parts) > 1:
            return " > ".join(parts[:-1])
    return None


def _is_related_section_neighbor(seed_metadata: dict[str, Any], chunk_metadata: dict[str, Any]) -> bool:
    seed_parent = _parent_section_key(seed_metadata)
    chunk_parent = _parent_section_key(chunk_metadata)
    if seed_parent and chunk_parent and seed_parent == chunk_parent:
        return True

    seed_page = _metadata_int(seed_metadata, "page")
    chunk_page = _metadata_int(chunk_metadata, "page")
    if seed_page is not None and chunk_page is not None and abs(seed_page - chunk_page) <= 1:
        return True
    return False


def _query_needs_related_sections(query: str) -> bool:
    lower = (query or "").lower()
    if re.search(r"\b[A-Z]?\d{2,}[A-Z]?(?:\s*[-–]\s*[A-Z]?\d{2,}[A-Z]?)\b", query or ""):
        return True
    tokens = _support_tokens(lower)
    if tokens & RELATED_SECTION_QUERY_TERMS:
        return True
    return bool(re.search(r"\b(?:multi[- ]?chunk|section[- ]?summary|multi[- ]?part)\b", lower))


def _query_uses_comparison(query: str) -> bool:
    lower = (query or "").lower()
    return bool(
        re.search(
            r"\b(?:compare|comparison|difference|differences|differ|versus|vs|relate|relationship|connect|fit together)\b",
            lower,
        )
    )


def _section_path_label(value: Any) -> str:
    value = _jsonable_section_path(value)
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if item)
    return str(value or "").strip()


def _jsonable_section_path(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"[", "{"}:
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _segment_locator_metadata(chunks: list[Chunk]) -> dict[str, Any]:
    if not chunks:
        return {}
    first_meta = chunks[0].metadata
    pages = [
        page
        for chunk in chunks
        for page in (_metadata_int(chunk.metadata, "page_start"), _metadata_int(chunk.metadata, "page_end"))
        if page is not None
    ]
    page_start = min(pages) if pages else _metadata_int(first_meta, "page")
    page_end = max(pages) if pages else page_start
    return {
        "doc_id": first_meta.get("doc_id"),
        "section_title": first_meta.get("section_title"),
        "section_path": _jsonable_section_path(first_meta.get("section_path")),
        "page": page_start,
        "page_start": page_start,
        "page_end": page_end,
    }


def _chunk_evidence(chunk: Chunk) -> dict[str, Any]:
    metadata = _clean_metadata(chunk.metadata)
    evidence = {
        "chunk_id": chunk.chunk_id,
        "doc_id": metadata.get("doc_id"),
        "page": metadata.get("page"),
        "page_start": metadata.get("page_start"),
        "page_end": metadata.get("page_end"),
        "section_title": metadata.get("section_title"),
        "section_path": _jsonable_section_path(metadata.get("section_path")),
        "snippet": _snippet(_strip_section_prefix(chunk.text), limit=SOURCE_CHUNK_EVIDENCE_SNIPPET_LIMIT),
    }
    for key in ("pdf_url", "page_label", "bbox", "char_range", "text_search"):
        if metadata.get(key) not in (None, "", [], {}):
            evidence[key] = metadata.get(key)
    return evidence


def _snippet(text: str, *, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}..."


def _metadata_int(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


@lru_cache(maxsize=128)
def _pdf_page_text(doc_id: str, page: int) -> str:
    if page <= 0:
        return ""
    pdf_path = resolve_source_pdf_path(doc_id)
    if pdf_path is None:
        return ""
    try:
        import fitz  # type: ignore

        with fitz.open(pdf_path) as document:
            page_index = page - 1
            if page_index < 0 or page_index >= len(document):
                return ""
            text = document[page_index].get_text("text") or ""
    except Exception:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return _cap_words(text, 900)


def _page_text_is_redundant(existing_text: str, page_text: str) -> bool:
    existing = re.sub(r"\s+", " ", existing_text or "").strip().lower()
    page = re.sub(r"\s+", " ", page_text or "").strip().lower()
    if not existing or not page:
        return False
    if page in existing:
        return True
    existing_terms = _support_tokens(existing)
    page_terms = _support_tokens(page)
    if not page_terms:
        return True
    return len(page_terms - existing_terms) <= 3


def _segment_id(prefix: str, doc_id: Any, index: int, child_chunks: list[Chunk]) -> str:
    child_part = "-".join(_safe_id(chunk.chunk_id) for chunk in child_chunks[:2])
    return f"{prefix}:{_safe_id(str(doc_id))}:{index:02d}:{child_part}"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value or "unknown").strip("-") or "unknown"


def _cap_words(text: str, max_tokens: int) -> str:
    words = (text or "").split()
    max_words = max(1, int(max_tokens / 1.33))
    return " ".join(words[:max_words])
