from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from factory_agent.rag.document_registry import default_source_register_path
from factory_agent.rag.schemas import Chunk, SourceRegister


TOKEN_RE = re.compile(r"\b[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*\b")
WORD_RE = re.compile(r"[a-z0-9]+")
SOURCE_PREFIX_RE = re.compile(
    r"^(?:explain|support|use(?:d)? for|describe|summarize|provide|answer)\s+",
    re.IGNORECASE,
)
STOPWORDS = {
    "a",
    "about",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "or",
    "such",
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
    "why",
    "with",
}
COMPOUND_PARTICLES = ("out", "in", "up", "down", "off", "on", "over", "under")


@dataclass(frozen=True)
class CorpusRewriteSettings:
    max_expansion_terms: int = 18
    max_terms_per_source: int = 10
    min_overlap_terms: int = 2
    min_overlap_ratio: float = 0.24
    min_confidence: float = 0.34
    section_anchor_min_confidence: float = 0.50
    section_anchor_fields: tuple[str, ...] = ("section_title", "section_path", "text_alias")
    broad_expansion_fields: tuple[str, ...] = (
        "use_for",
        "related_entities",
        "domain",
        "subdomain",
        "organization",
        "source_type",
    )
    low_specificity_single_token_alias_fields: tuple[str, ...] = (
        "related_entities",
        "domain",
        "subdomain",
        "organization",
        "source_type",
    )


@dataclass(frozen=True)
class CorpusRewriteResult:
    original_query: str
    normalized_query: str
    expanded_query: str
    expansion_terms: list[str]
    expansion_sources: list[dict[str, Any]]
    confidence: float
    mode: str = "corpus_aware"


@dataclass(frozen=True)
class _LexiconTerm:
    term: str
    tokens: frozenset[str]
    aliases: frozenset[str]
    source: dict[str, Any]
    priority: float


@dataclass
class _CandidateDoc:
    doc_id: str
    terms: list[_LexiconTerm] = field(default_factory=list)
    confidence: float = 0.0
    matched_sources: list[dict[str, Any]] = field(default_factory=list)


def build_corpus_aware_query_rewrite(
    query: str,
    *,
    source_documents: Iterable[Any] | None = None,
    indexed_chunks: Iterable[Chunk] | None = None,
    source_register_path: str | Path | None = None,
    settings: CorpusRewriteSettings | None = None,
) -> CorpusRewriteResult:
    """Build a retrieval-only query expansion from source and indexed metadata.

    This function deliberately adds only corpus vocabulary. It does not add
    procedural answer steps, expected facts, benchmark case labels, or source
    filters.
    """

    settings = settings or CorpusRewriteSettings()
    original = str(query or "")
    normalized = _normalize_space(original)
    if not normalized:
        return CorpusRewriteResult(
            original_query=original,
            normalized_query="",
            expanded_query="",
            expansion_terms=[],
            expansion_sources=[],
            confidence=0.0,
        )

    lexicon = _build_lexicon(
        source_documents=source_documents,
        indexed_chunks=indexed_chunks,
        source_register_path=source_register_path,
    )
    if not lexicon:
        return CorpusRewriteResult(
            original_query=original,
            normalized_query=normalized,
            expanded_query=normalized,
            expansion_terms=[],
            expansion_sources=[],
            confidence=0.0,
        )

    query_terms = _support_tokens(normalized)
    query_forms = _query_forms(normalized)
    candidates = _candidate_docs_for_query(
        lexicon,
        query_terms=query_terms,
        query_forms=query_forms,
        settings=settings,
    )
    selected_terms, sources, confidence = _select_expansion_terms(
        candidates,
        query_terms=query_terms,
        query_forms=query_forms,
        settings=settings,
    )
    if not selected_terms or confidence < settings.min_confidence:
        return CorpusRewriteResult(
            original_query=original,
            normalized_query=normalized,
            expanded_query=normalized,
            expansion_terms=[],
            expansion_sources=[],
            confidence=0.0,
        )

    retrieval_focus = "; ".join(selected_terms)
    return CorpusRewriteResult(
        original_query=original,
        normalized_query=normalized,
        expanded_query=f"{normalized}\nCorpus retrieval focus: {retrieval_focus}",
        expansion_terms=selected_terms,
        expansion_sources=sources,
        confidence=round(confidence, 6),
    )


def build_corpus_aware_query_rewrite_for_retriever(
    query: str,
    retriever: Any,
    *,
    source_register_path: str | Path | None = None,
    settings: CorpusRewriteSettings | None = None,
) -> CorpusRewriteResult:
    chunks = _indexed_chunks_from_retriever(retriever)
    return build_corpus_aware_query_rewrite(
        query,
        indexed_chunks=chunks,
        source_register_path=source_register_path,
        settings=settings,
    )


def _indexed_chunks_from_retriever(retriever: Any) -> list[Chunk]:
    chunks = getattr(retriever, "bm25_chunks", None)
    if chunks:
        return [chunk for chunk in chunks if isinstance(chunk, Chunk)]

    fallback_chunks = getattr(retriever, "chunks", None)
    if fallback_chunks:
        return [chunk for chunk in fallback_chunks if isinstance(chunk, Chunk)]

    collection = getattr(retriever, "collection", None)
    if collection is None:
        return []
    try:
        result = collection.get(include=["documents", "metadatas"])
    except Exception:
        return []

    return [
        Chunk(chunk_id=chunk_id, text=document or "", metadata=_clean_metadata(metadata or {}))
        for chunk_id, document, metadata in zip(
            result.get("ids") or [],
            result.get("documents") or [],
            result.get("metadatas") or [],
        )
    ]


def _build_lexicon(
    *,
    source_documents: Iterable[Any] | None,
    indexed_chunks: Iterable[Chunk] | None,
    source_register_path: str | Path | None,
) -> list[_LexiconTerm]:
    docs = list(source_documents or [])
    if source_documents is None:
        docs.extend(_load_source_register_documents(source_register_path))

    terms: list[_LexiconTerm] = []
    for doc in docs:
        doc_data = _document_mapping(doc)
        terms.extend(_terms_from_document(doc_data))

    for chunk in indexed_chunks or []:
        terms.extend(_terms_from_chunk(chunk))

    deduped: dict[tuple[str, str, str], _LexiconTerm] = {}
    for term in terms:
        if not term.term or not term.tokens:
            continue
        source = term.source
        key = (
            str(source.get("doc_id") or ""),
            str(source.get("field") or ""),
            term.term.lower(),
        )
        previous = deduped.get(key)
        if previous is None or term.priority > previous.priority:
            deduped[key] = term
    return list(deduped.values())


@lru_cache(maxsize=8)
def _load_source_register_documents_cached(path_text: str) -> tuple[dict[str, Any], ...]:
    path = Path(path_text)
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        register = SourceRegister(**data)
    except Exception:
        return ()
    return tuple(doc.model_dump() for doc in register.documents)


def _load_source_register_documents(path: str | Path | None) -> list[dict[str, Any]]:
    resolved = Path(path) if path is not None else default_source_register_path()
    return [dict(item) for item in _load_source_register_documents_cached(str(resolved.resolve()))]


def _document_mapping(doc: Any) -> dict[str, Any]:
    if hasattr(doc, "model_dump"):
        data = doc.model_dump()
    elif isinstance(doc, dict):
        data = dict(doc)
    else:
        data = {
            key: getattr(doc, key)
            for key in dir(doc)
            if not key.startswith("_") and not callable(getattr(doc, key))
        }
    return _clean_metadata(data)


def _terms_from_document(doc: dict[str, Any]) -> list[_LexiconTerm]:
    doc_id = str(doc.get("doc_id") or "")
    rows: list[tuple[str, Any, float]] = [
        ("title", doc.get("title"), 1.0),
        ("domain", doc.get("domain"), 0.58),
        ("subdomain", doc.get("subdomain"), 0.72),
        ("organization", doc.get("organization"), 0.35),
        ("source_type", doc.get("source_type"), 0.40),
    ]
    for field in ("use_for", "related_entities", "aliases", "acronyms"):
        for value in _as_list(doc.get(field)):
            priority = 0.92 if field == "use_for" else 0.78
            rows.append((field, value, priority))
    return [
        term
        for field, value, priority in rows
        for term in _terms_from_value(
            value,
            source={"doc_id": doc_id, "field": field, "source_type": "source_register"},
            priority=priority,
        )
    ]


def _terms_from_chunk(chunk: Chunk) -> list[_LexiconTerm]:
    metadata = _clean_metadata(chunk.metadata or {})
    doc_id = str(metadata.get("doc_id") or "")
    rows: list[tuple[str, Any, float]] = [
        ("title", metadata.get("title"), 0.92),
        ("section_title", metadata.get("section_title"), 0.95),
        ("section_path", metadata.get("section_path"), 0.90),
        ("domain", metadata.get("domain"), 0.56),
        ("subdomain", metadata.get("subdomain"), 0.70),
    ]
    for field in ("use_for", "related_entities", "aliases", "acronyms"):
        for value in _as_list(metadata.get(field)):
            priority = 0.88 if field == "use_for" else 0.74
            rows.append((field, value, priority))
    terms: list[_LexiconTerm] = []
    for field, value, priority in rows:
        terms.extend(
            _terms_from_value(
                value,
                source={
                    "doc_id": doc_id,
                    "chunk_id": chunk.chunk_id,
                    "field": field,
                    "source_type": "indexed_metadata",
                },
                priority=priority,
            )
        )
    terms.extend(_alias_terms_from_text(chunk.text, doc_id=doc_id, chunk_id=chunk.chunk_id))
    return terms


def _terms_from_value(value: Any, *, source: dict[str, Any], priority: float) -> list[_LexiconTerm]:
    values = _as_list(value)
    if not values and value not in (None, "", [], {}):
        values = [value]
    terms: list[_LexiconTerm] = []
    for row in values:
        phrase = _clean_phrase(row)
        if not phrase:
            continue
        terms.append(_make_term(phrase, source=source, priority=priority))
        for subphrase in _meaningful_subphrases(phrase):
            if subphrase != phrase:
                terms.append(_make_term(subphrase, source=source, priority=priority * 0.92))
    return terms


def _alias_terms_from_text(text: str, *, doc_id: str, chunk_id: str) -> list[_LexiconTerm]:
    terms: list[_LexiconTerm] = []
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9 /-]{4,80}?)\s*\(([A-Z][A-Z0-9]{1,12})\)", text or ""):
        phrase = _clean_phrase(match.group(1))
        acronym = match.group(2).strip()
        if phrase and acronym:
            terms.append(
                _make_term(
                    phrase,
                    source={
                        "doc_id": doc_id,
                        "chunk_id": chunk_id,
                        "field": "text_alias",
                        "source_type": "indexed_metadata",
                        "alias": acronym,
                    },
                    priority=0.82,
                    extra_aliases={acronym.lower()},
                )
            )
    return terms


def _make_term(
    phrase: str,
    *,
    source: dict[str, Any],
    priority: float,
    extra_aliases: set[str] | None = None,
) -> _LexiconTerm:
    tokens = frozenset(_support_tokens(phrase))
    aliases = set(_phrase_aliases(phrase))
    aliases.update(extra_aliases or set())
    return _LexiconTerm(
        term=phrase,
        tokens=tokens,
        aliases=frozenset(alias for alias in aliases if alias),
        source=dict(source),
        priority=priority,
    )


def _candidate_docs_for_query(
    lexicon: list[_LexiconTerm],
    *,
    query_terms: set[str],
    query_forms: set[str],
    settings: CorpusRewriteSettings,
) -> dict[str, _CandidateDoc]:
    terms_by_doc: dict[str, list[_LexiconTerm]] = {}
    for term in lexicon:
        doc_id = str(term.source.get("doc_id") or "")
        if doc_id:
            terms_by_doc.setdefault(doc_id, []).append(term)

    candidates: dict[str, _CandidateDoc] = {}
    for term in lexicon:
        confidence, matched_by = _term_confidence(
            term,
            query_terms=query_terms,
            query_forms=query_forms,
            settings=settings,
        )
        if confidence <= 0:
            continue
        doc_id = str(term.source.get("doc_id") or "")
        if not doc_id:
            continue
        candidate = candidates.setdefault(doc_id, _CandidateDoc(doc_id=doc_id))
        candidate.confidence = max(candidate.confidence, confidence)
        candidate.matched_sources.append(
            {
                **term.source,
                "term": term.term,
                "matched_by": matched_by,
                "confidence": round(confidence, 6),
            }
        )
    for doc_id, candidate in candidates.items():
        candidate.terms = terms_by_doc.get(doc_id, [])
    return candidates


def _term_confidence(
    term: _LexiconTerm,
    *,
    query_terms: set[str],
    query_forms: set[str],
    settings: CorpusRewriteSettings,
) -> tuple[float, str]:
    alias_hit = sorted(term.aliases & query_forms)
    if alias_hit:
        field = str(term.source.get("field") or "")
        if len(term.tokens) <= 1 and field in set(settings.low_specificity_single_token_alias_fields):
            return 0.0, ""
        return min(0.95, 0.70 + (0.20 * term.priority)), f"alias:{alias_hit[0]}"

    overlap = query_terms & set(term.tokens)
    if len(overlap) < settings.min_overlap_terms:
        return 0.0, ""
    ratio = len(overlap) / max(1, min(len(query_terms), len(term.tokens)))
    if ratio < settings.min_overlap_ratio:
        return 0.0, ""
    confidence = min(0.88, (ratio * 0.55) + (0.30 * term.priority))
    return confidence, "token_overlap"


def _select_expansion_terms(
    candidates: dict[str, _CandidateDoc],
    *,
    query_terms: set[str],
    query_forms: set[str],
    settings: CorpusRewriteSettings,
) -> tuple[list[str], list[dict[str, Any]], float]:
    if not candidates:
        return [], [], 0.0

    ordered_candidates = sorted(
        candidates.values(),
        key=lambda item: (item.confidence, len(item.matched_sources)),
        reverse=True,
    )
    selected: list[str] = []
    sources: list[dict[str, Any]] = []
    confidences: list[float] = []
    seen: set[str] = set()

    for candidate in ordered_candidates:
        if candidate.confidence < settings.min_confidence:
            continue
        doc_terms = sorted(
            _doc_expansion_terms(
                candidate.terms,
                query_terms=query_terms,
                query_forms=query_forms,
                settings=settings,
            ),
            key=lambda term: (_term_selection_score(term, query_terms), term.priority, -len(term.term)),
            reverse=True,
        )
        per_source_count = 0
        for term in doc_terms:
            key = term.term.lower()
            if key in seen or _query_already_contains_term(term.term, query_forms):
                continue
            selected.append(term.term)
            seen.add(key)
            confidences.append(candidate.confidence)
            sources.append(
                {
                    **term.source,
                    "term": term.term,
                    "confidence": round(candidate.confidence, 6),
                    "reason": "matched_corpus_metadata",
                }
            )
            per_source_count += 1
            if len(selected) >= settings.max_expansion_terms or per_source_count >= settings.max_terms_per_source:
                break
        if len(selected) >= settings.max_expansion_terms:
            break

    confidence = max(confidences) if confidences else 0.0
    return selected, sources, confidence


def _doc_expansion_terms(
    terms: list[_LexiconTerm],
    *,
    query_terms: set[str],
    query_forms: set[str],
    settings: CorpusRewriteSettings,
) -> list[_LexiconTerm]:
    doc_id = ""
    for term in terms:
        doc_id = str(term.source.get("doc_id") or "")
        if doc_id:
            break
    if not doc_id:
        return []

    related = [
        term
        for term in terms
        if term.source.get("field") in {"title", "section_title", "section_path", "use_for", "related_entities", "domain", "subdomain", "aliases", "acronyms", "text_alias"}
    ]
    if not related:
        return terms

    anchor_tokens = _section_anchor_tokens(
        related,
        query_terms=query_terms,
        query_forms=query_forms,
        settings=settings,
    )
    matched = [
        term
        for term in related
        if (set(term.tokens) & query_terms) or (set(term.aliases) & query_forms)
    ]
    expansion_pool: list[_LexiconTerm] = []
    seen: set[tuple[str, str, str]] = set()
    for term in [*matched, *related]:
        key = (
            str(term.source.get("field") or ""),
            str(term.source.get("chunk_id") or ""),
            term.term.lower(),
        )
        if key in seen:
            continue
        if anchor_tokens and not _is_term_allowed_after_section_anchor(
            term,
            anchor_tokens=anchor_tokens,
            query_terms=query_terms,
            query_forms=query_forms,
            settings=settings,
        ):
            continue
        seen.add(key)
        expansion_pool.append(term)
    return expansion_pool


def _section_anchor_tokens(
    terms: list[_LexiconTerm],
    *,
    query_terms: set[str],
    query_forms: set[str],
    settings: CorpusRewriteSettings,
) -> set[str]:
    anchor_fields = set(settings.section_anchor_fields)
    anchors: set[str] = set()
    for term in terms:
        if term.source.get("field") not in anchor_fields:
            continue
        confidence, _matched_by = _term_confidence(
            term,
            query_terms=query_terms,
            query_forms=query_forms,
            settings=settings,
        )
        if confidence < settings.section_anchor_min_confidence:
            continue
        anchors.update(term.tokens)
    return anchors


def _is_term_allowed_after_section_anchor(
    term: _LexiconTerm,
    *,
    anchor_tokens: set[str],
    query_terms: set[str],
    query_forms: set[str],
    settings: CorpusRewriteSettings,
) -> bool:
    field = str(term.source.get("field") or "")
    if field in set(settings.section_anchor_fields):
        confidence, _matched_by = _term_confidence(
            term,
            query_terms=query_terms,
            query_forms=query_forms,
            settings=settings,
        )
        if confidence >= settings.section_anchor_min_confidence:
            return True
        return set(term.tokens).issubset(anchor_tokens | query_terms)
    if field not in set(settings.broad_expansion_fields):
        return True
    if set(term.aliases) & query_forms:
        return True
    return set(term.tokens).issubset(anchor_tokens | query_terms)


def _term_selection_score(term: _LexiconTerm, query_terms: set[str]) -> float:
    overlap = len(set(term.tokens) & query_terms)
    novelty = len(set(term.tokens) - query_terms) / max(1, len(term.tokens))
    field = str(term.source.get("field") or "")
    field_bonus = {
        "use_for": 0.30,
        "section_title": 0.28,
        "title": 0.24,
        "section_path": 0.18,
        "related_entities": 0.12,
        "subdomain": 0.10,
        "domain": 0.04,
    }.get(field, 0.0)
    return (0.35 * overlap) + (0.25 * novelty) + (0.30 * term.priority) + field_bonus


def _query_already_contains_term(term: str, query_forms: set[str]) -> bool:
    cleaned = _clean_phrase(term)
    return bool(cleaned and cleaned in query_forms)


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


def _as_list(value: Any) -> list[Any]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def _clean_phrase(value: Any) -> str:
    text = _normalize_space(str(value or "").replace("_", " "))
    text = SOURCE_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -/:;,.")
    words = WORD_RE.findall(text.lower())
    if not words:
        return ""
    if len(words) > 10:
        return " ".join(words[:10])
    return " ".join(words)


def _meaningful_subphrases(phrase: str) -> list[str]:
    words = [word for word in WORD_RE.findall(phrase.lower()) if word not in STOPWORDS]
    subphrases: list[str] = []
    if 2 <= len(words) <= 6:
        subphrases.append(" ".join(words))
    if len(words) > 3:
        for size in (2, 3, 4):
            for start in range(0, len(words) - size + 1):
                piece = words[start : start + size]
                if len(set(piece)) < 2:
                    continue
                subphrases.append(" ".join(piece))
    return list(dict.fromkeys(subphrases))


def _phrase_aliases(phrase: str) -> set[str]:
    cleaned = _clean_phrase(phrase)
    if not cleaned:
        return set()
    words = WORD_RE.findall(cleaned.lower())
    aliases = {
        cleaned,
        " ".join(words),
        "".join(words),
        "-".join(words),
        "/".join(words),
    }
    split_words: list[str] = []
    for word in words:
        split_words.extend(_split_compound_word(word))
    if split_words != words:
        aliases.update(
            {
                " ".join(split_words),
                "".join(split_words),
                "-".join(split_words),
                "/".join(split_words),
            }
        )
    acronym = _acronym(split_words or words)
    if len(acronym) >= 3:
        aliases.add(acronym.lower())
    simple_acronym = _acronym(words)
    if len(simple_acronym) >= 3:
        aliases.add(simple_acronym.lower())
    return {alias for alias in aliases if alias}


def _split_compound_word(word: str) -> list[str]:
    lowered = (word or "").lower()
    for particle in COMPOUND_PARTICLES:
        if lowered.endswith(particle) and len(lowered) > len(particle) + 2:
            return [lowered[: -len(particle)], particle]
    return [lowered] if lowered else []


def _acronym(words: list[str]) -> str:
    return "".join(word[0] for word in words if word and word not in STOPWORDS)


def _support_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall(text or ""):
        for word in WORD_RE.findall(raw.lower().replace("_", " ")):
            if len(word) < 2 or word in STOPWORDS:
                continue
            tokens.add(_stem(word))
    return tokens


def _stem(word: str) -> str:
    token = word.lower()
    if len(token) > 5 and token.endswith("ical"):
        return token[:-2]
    if len(token) > 5 and token.endswith("al"):
        return token[:-2]
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _query_forms(query: str) -> set[str]:
    normalized = _normalize_space(query).lower()
    words = WORD_RE.findall(normalized)
    forms = {
        normalized,
        " ".join(words),
        "".join(words),
        "-".join(words),
        "/".join(words),
    }
    for token in TOKEN_RE.findall(query or ""):
        forms.update(_phrase_aliases(token))
    for size in range(2, min(7, len(words)) + 1):
        for start in range(0, len(words) - size + 1):
            piece = " ".join(words[start : start + size])
            forms.add(piece)
            forms.add("".join(words[start : start + size]))
            forms.add("-".join(words[start : start + size]))
            forms.add("/".join(words[start : start + size]))
    return {form for form in forms if form}


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
