"""Index-time document augmentation for RAG retrieval.

The augmentation in this module is deterministic and source-grounded. It only
uses chunk text plus source metadata supplied by ingestion, and it keeps the
synthetic retrieval text separate from the original evidence text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from factory_agent.rag.schemas import Chunk


DOCUMENT_AUGMENTATION_STRATEGY_VERSION = "document_augmentation_v1"
DEFAULT_VECTOR_DB_PATH = "factory_agent/rag/vector_db"
DEFAULT_BM25_PATH = "factory_agent/rag/bm25_index.pkl"
AUGMENTED_VECTOR_DB_PATH = "factory_agent/rag/vector_db_augmented"
AUGMENTED_BM25_PATH = "factory_agent/rag/bm25_index_augmented.pkl"

SECTION_PREFIX_RE = re.compile(r"^\[Section:\s*[^\]]+\]\s*", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(]?[A-Z0-9])")

STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "also",
    "among",
    "and",
    "are",
    "before",
    "between",
    "but",
    "can",
    "could",
    "does",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "may",
    "must",
    "not",
    "only",
    "other",
    "shall",
    "should",
    "such",
    "that",
    "the",
    "their",
    "these",
    "this",
    "through",
    "under",
    "using",
    "when",
    "where",
    "which",
    "with",
    "within",
}


@dataclass(frozen=True)
class DocumentAugmentation:
    original_text: str
    synthetic_text: str
    retrieval_text: str
    fields: dict[str, Any]


def build_document_augmentation(chunk: Chunk) -> DocumentAugmentation:
    """Build retrieval-only augmentation for one chunk.

    No file reads happen here. The caller supplies source text and source
    metadata, which keeps augmentation isolated from eval cases and gold data.
    """

    metadata = _clean_metadata(chunk.metadata)
    original_text = chunk.text or ""
    body_text = _strip_section_prefix(original_text)
    sentences = _sentences(body_text)
    key_terms = _key_terms(body_text)
    aliases = _aliases_from_text(body_text)
    section_title = str(metadata.get("section_title") or "Unknown section").strip()
    section_path = _section_path_label(metadata.get("section_path"))
    title = str(metadata.get("title") or metadata.get("doc_id") or "Untitled source").strip()

    summary = " ".join(sentences[:2]).strip()
    generated_questions = _generated_questions(
        title=title,
        section_title=section_title,
        key_terms=key_terms,
    )

    fields: dict[str, Any] = {
        "document_title": title,
        "doc_id": metadata.get("doc_id"),
        "organization": metadata.get("organization"),
        "domain": metadata.get("domain"),
        "subdomain": metadata.get("subdomain"),
        "authority_level": metadata.get("authority_level"),
        "risk_level": metadata.get("risk_level"),
        "section_title": section_title,
        "section_path": section_path,
        "use_for": _as_list(metadata.get("use_for")),
        "related_entities": _as_list(metadata.get("related_entities")),
        "key_terms": key_terms,
        "aliases": aliases,
        "source_grounded_summary": summary,
        "generated_retrieval_questions": generated_questions,
    }

    synthetic_text = _format_synthetic_text(fields)
    retrieval_text = (
        f"{original_text.strip()}\n\n"
        "[Retrieval augmentation - synthetic, not citation evidence]\n"
        f"{synthetic_text}"
    ).strip()
    return DocumentAugmentation(
        original_text=original_text,
        synthetic_text=synthetic_text,
        retrieval_text=retrieval_text,
        fields=fields,
    )


def augmentation_metadata(augmentation: DocumentAugmentation) -> dict[str, Any]:
    """Metadata fields persisted beside an augmented chunk."""

    return {
        "document_augmentation_enabled": True,
        "document_augmentation_strategy_version": DOCUMENT_AUGMENTATION_STRATEGY_VERSION,
        "document_augmentation_fields": augmentation.fields,
        "synthetic_augmentation_text": augmentation.synthetic_text,
        "original_evidence_text": augmentation.original_text,
    }


def _format_synthetic_text(fields: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"Document title: {fields.get('document_title') or ''}")
    if fields.get("organization"):
        lines.append(f"Source organization: {fields['organization']}")
    if fields.get("domain") or fields.get("subdomain"):
        lines.append(f"Source domain: {fields.get('domain') or ''} / {fields.get('subdomain') or ''}")
    if fields.get("authority_level"):
        lines.append(f"Authority level: {fields['authority_level']}")
    if fields.get("risk_level"):
        lines.append(f"Risk level: {fields['risk_level']}")
    lines.append(f"Section title: {fields.get('section_title') or ''}")
    if fields.get("section_path"):
        lines.append(f"Section path: {fields['section_path']}")
    if fields.get("use_for"):
        lines.append("Use for: " + ", ".join(str(item) for item in fields["use_for"]))
    if fields.get("related_entities"):
        lines.append("Related entities: " + ", ".join(str(item) for item in fields["related_entities"]))
    if fields.get("source_grounded_summary"):
        lines.append("Source-grounded summary: " + str(fields["source_grounded_summary"]))
    if fields.get("key_terms"):
        lines.append("Key terms from source text: " + ", ".join(fields["key_terms"]))
    if fields.get("aliases"):
        lines.append("Aliases from source text: " + ", ".join(fields["aliases"]))
    questions = fields.get("generated_retrieval_questions") or []
    if questions:
        lines.append("Generated retrieval questions from this chunk:")
        lines.extend(f"- {question}" for question in questions)
    return "\n".join(line for line in lines if str(line).strip())


def _generated_questions(
    *,
    title: str,
    section_title: str,
    key_terms: list[str],
    limit: int = 4,
) -> list[str]:
    terms = key_terms[:limit]
    questions: list[str] = []
    for term in terms:
        questions.append(f"What does {section_title} say about {term}?")
    if terms:
        questions.append(f"How does {title} describe {terms[0]}?")
    return list(dict.fromkeys(questions))[:limit]


def _key_terms(text: str, *, limit: int = 16) -> list[str]:
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for index, raw in enumerate(WORD_RE.findall(text or "")):
        term = raw.lower().replace("_", " ")
        if term in STOPWORDS or len(term) < 3:
            continue
        counts[term] = counts.get(term, 0) + 1
        first_seen.setdefault(term, index)
    ranked = sorted(
        counts,
        key=lambda term: (-counts[term], -min(len(term), 18), first_seen[term], term),
    )
    return ranked[:limit]


def _aliases_from_text(text: str, *, limit: int = 12) -> list[str]:
    aliases: list[str] = []
    for acronym in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", text or ""):
        aliases.append(acronym)
    for left, right in re.findall(r"\b([A-Za-z][A-Za-z -]{3,80})\s+\(([A-Z][A-Z0-9]{1,12})\)", text or ""):
        aliases.append(right.strip())
        aliases.append(left.strip())
    return list(dict.fromkeys(alias for alias in aliases if alias))[:limit]


def _sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    parts = [part.strip() for part in SENTENCE_RE.split(normalized) if part.strip()]
    return parts or [normalized]


def _strip_section_prefix(text: str) -> str:
    return SECTION_PREFIX_RE.sub("", text or "").strip()


def _section_path_label(value: Any) -> str:
    if isinstance(value, str) and value[:1] in {"[", "{"}:
        try:
            value = json.loads(value)
        except Exception:
            pass
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if item)
    return str(value or "").strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str) and value[:1] in {"[", "{"}:
        try:
            value = json.loads(value)
        except Exception:
            pass
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [value]
    return [value]


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
