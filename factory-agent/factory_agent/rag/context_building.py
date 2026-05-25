from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from factory_agent.rag.document_registry import resolve_source_pdf_path
from factory_agent.rag.schemas import Chunk, ScoredChunk


VALID_CONTEXT_BUILDERS = {"none", "small_to_big", "rse"}
VALID_COMPRESSION_MODES = {"none", "light_extractive"}

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
            "segment_chunk_ids": [chunk.chunk_id for chunk in self.chunks_in_segment],
            "token_estimate_before_expansion": self.token_estimate_before_expansion,
            "token_estimate_after_expansion": self.token_estimate_after_expansion,
            "token_estimate_after_compression": self.token_estimate_after_compression,
            "compression_ran": self.compression_ran,
        }
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
    ) -> None:
        self.retriever = retriever
        self.small_to_big_max_tokens = small_to_big_max_tokens
        self.rse_max_window = rse_max_window
        self.rse_max_segment_tokens = rse_max_segment_tokens
        self.compression_max_tokens = compression_max_tokens
        self.compression_target_ratio = compression_target_ratio

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
            )
            drafts = self._build_rse_segments(
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
        return _context_result_from_drafts(
            builder=builder,
            compression=compression_mode,
            drafts=drafts,
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
    query_terms = _support_tokens(query)
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

    query_terms = _support_tokens(query)
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
) -> ContextBuildResult:
    before = sum(draft.token_estimate_before_expansion for draft in drafts)
    after_expansion = sum(draft.token_estimate_after_expansion for draft in drafts)
    after_compression = sum(draft.token_estimate_after_compression for draft in drafts)
    return ContextBuildResult(
        chunks=[draft.to_chunk() for draft in drafts],
        metadata={
            "context_builder": builder,
            "compression": compression,
            "compression_ran": any(draft.compression_ran for draft in drafts),
            "token_estimates": {
                "before_expansion": before,
                "after_expansion": after_expansion,
                "after_compression": after_compression,
            },
            "segments": [draft.to_metadata() for draft in drafts],
        },
    )


def _candidate_info(candidates: Iterable[ScoredChunk]) -> dict[str, _CandidateInfo]:
    info: dict[str, _CandidateInfo] = {}
    for rank, scored in enumerate(candidates, start=1):
        score = _best_score(scored)
        info[scored.chunk.chunk_id] = _CandidateInfo(
            score=score if score is not None else 1.0 / rank,
            rank=rank,
        )
    return info


def _preserve_top_related_candidates(
    *,
    query: str,
    selected_chunks: list[Chunk],
    candidates: list[ScoredChunk],
    max_rank: int = 5,
) -> list[Chunk]:
    if not selected_chunks or not candidates or not _query_needs_related_sections(query):
        return selected_chunks

    query_terms = _support_tokens(query)
    if not query_terms:
        return selected_chunks

    preserved = list(selected_chunks)
    preserved_ids = {chunk.chunk_id for chunk in preserved}
    selected_terms = _support_tokens(" ".join(_chunk_text_with_metadata(chunk) for chunk in selected_chunks))

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
        if overlap - selected_terms or rank <= max_rank:
            chunk.metadata = {
                **_clean_metadata(chunk.metadata),
                "context_candidate_supplement": True,
                "context_candidate_rank": rank,
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


def _score_segment(
    *,
    query: str,
    child_chunks: list[Chunk],
    chunks_in_segment: list[Chunk],
    candidate_info: dict[str, _CandidateInfo],
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
    return max_child_score + coverage_bonus + metadata_bonus


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
    tokens: set[str] = set()
    for raw in WORD_RE.findall((text or "").lower()):
        token = _stem(raw)
        if len(token) < 3 or token in CONTEXT_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _stem(token: str) -> str:
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
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": metadata.get("doc_id"),
        "page": metadata.get("page"),
        "page_start": metadata.get("page_start"),
        "page_end": metadata.get("page_end"),
        "section_title": metadata.get("section_title"),
        "section_path": _jsonable_section_path(metadata.get("section_path")),
        "snippet": _snippet(_strip_section_prefix(chunk.text), limit=360),
    }


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
