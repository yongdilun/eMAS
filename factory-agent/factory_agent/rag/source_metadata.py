from __future__ import annotations

import re
from typing import Any, Iterable


SAFETY_ADMONITION_RE = re.compile(
    r"(?:^|\n)[ \t]*:::\s*safety\b[\s\S]*?(?:\n[ \t]*:::[ \t]*(?=\n|$)|$)",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")
_FOOTNOTE_DEFINITION_RE = re.compile(r"(?m)^[ \t]*\[\^[^\]\n]+\]:[^\n]*(?:\n[ \t]+[^\n]*)*")
_FOOTNOTE_MARKER_RE = re.compile(r"\[\^[^\]\n]+\]")
_LOCAL_FILE_KEYS = {"file_path", "filepath", "local_file_path", "local_path"}
_LOCATOR_ALIASES = {
    "page": ("page", "pageNumber", "page_number"),
    "page_label": ("page_label", "pageLabel"),
    "pdf_url": ("pdf_url", "pdfUrl", "pdfurl"),
    "bbox": ("bbox", "bounding_box", "boundingBox"),
    "char_range": ("char_range", "charRange", "charrange", "text_range", "textRange"),
    "text_search": ("text_search", "textSearch", "highlight_text", "highlightText"),
}
_INSUFFICIENT_CONTEXT_PREFIX = "I do not have enough retrieved evidence to answer that safely."
_LIVE_SAFETY_QUERY_RE = re.compile(
    r"\b(live|current|right now|status|start|operate|energiz|reenergiz|locked out|permission|permit)\b",
    re.IGNORECASE,
)
_COMPLIANCE_PROOF_RE = re.compile(
    r"\b(certif|compliant|compliance|approved|approval|secure|security proof|prove|vendor|buy|purchase)\b",
    re.IGNORECASE,
)
_LIVE_STATUS_RE = re.compile(r"\b(live|current|today|right now|status)\b", re.IGNORECASE)
_SAFETY_DOMAIN_RE = re.compile(r"\b(osha|lockout|tagout|loto|guard|machine|press|hazard|energy|safety)\b", re.IGNORECASE)


def sanitize_rag_answer_text(value: Any) -> str:
    text = str(value or "")
    text = SAFETY_ADMONITION_RE.sub("\n", text)
    text = _FOOTNOTE_DEFINITION_RE.sub("", text)
    text = re.sub(r"(?m)^[ \t]*\[\^[^\]\n]+\][ \t]*$", "", text)
    text = re.sub(r"(?im)^[ \t]*:::\s*safety\b[ \t]*$", "", text)
    text = re.sub(r"(?im)^[ \t]*:::[ \t]*$", "", text)
    return text.strip()


def insufficient_context_answer(*, has_sources: bool = False, query: Any = None) -> str:
    suffix = _boundary_suffix_for_query(query)
    if has_sources:
        return (
            f"{_INSUFFICIENT_CONTEXT_PREFIX}{suffix} The related sources checked are listed below, "
            "but they do not prove the requested claim."
        )
    return f"{_INSUFFICIENT_CONTEXT_PREFIX}{suffix}"


def is_insufficient_context_answer(value: Any) -> bool:
    return sanitize_rag_answer_text(value).lower().startswith(_INSUFFICIENT_CONTEXT_PREFIX.lower())


def _boundary_suffix_for_query(query: Any) -> str:
    text = str(query or "")
    if _LIVE_SAFETY_QUERY_RE.search(text) and _SAFETY_DOMAIN_RE.search(text):
        return (
            " Do not start, operate, energize, or reenergize equipment based on this document-only "
            "answer. Check the live LOTO, maintenance, or permit system and contact the authorized "
            "employee or site safety officer for current status."
        )
    if _COMPLIANCE_PROOF_RE.search(text) or (
        _LIVE_STATUS_RE.search(text) and re.search(r"\b(compliance|approval|approved|secure|security)\b", text, re.IGNORECASE)
    ):
        return (
            " Do not treat these sources as live approval, vendor, security, compliance proof, or "
            "certification. They cannot replace qualified safety/compliance review. Check the current "
            "system of record or the responsible compliance owner."
        )
    return ""


def snippet_from_text(value: Any, *, limit: int = 320) -> str:
    cleaned = sanitize_rag_answer_text(value)
    cleaned = _FOOTNOTE_DEFINITION_RE.sub("", cleaned)
    cleaned = _FOOTNOTE_MARKER_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    text = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def _source_dict(source: Any) -> dict[str, Any]:
    if hasattr(source, "model_dump"):
        data = source.model_dump()
    elif isinstance(source, dict):
        data = dict(source)
    else:
        data = {"value": str(source)}
    return {str(key): value for key, value in data.items() if str(key).lower() not in _LOCAL_FILE_KEYS}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_number(data: dict[str, Any], index: int) -> int:
    return _int_or_none(data.get("source_number") or data.get("sourceNumber")) or index + 1


def _doc_id(data: dict[str, Any], number: int) -> str:
    for key in ("doc_id", "document_id", "procedure_id", "source_id", "id"):
        value = _clean_text(data.get(key))
        if value:
            return value
    return f"source-{number}"


def _title(data: dict[str, Any], doc_id: str, number: int) -> str:
    return _clean_text(data.get("title") or data.get("name")) or doc_id or f"Source {number}"


def _organization(data: dict[str, Any]) -> str:
    return _clean_text(data.get("organization") or data.get("publisher") or data.get("authority")) or "Unknown"


def _chunk_id(data: dict[str, Any], doc_id: str, number: int, *, policy_only: bool) -> str:
    for key in ("chunk_id", "chunkId", "locator_id", "locatorId"):
        value = _clean_text(data.get(key))
        if value:
            return value
    prefix = "policy" if policy_only else "chunk"
    return f"{doc_id}:{prefix}-{number}"


def _first_locator_value(data: dict[str, Any], key: str) -> Any:
    for candidate in _LOCATOR_ALIASES.get(key, (key,)):
        if candidate in data:
            return data.get(candidate)
    return None


def normalize_source_locator(
    source: Any,
    index: int = 0,
    *,
    fallback_snippet: Any = None,
    policy_id: str | None = None,
    policy_only: bool | None = None,
) -> dict[str, Any]:
    data = _source_dict(source)
    number = _source_number(data, index)
    explicit_policy_only = bool(
        data.get("policy_only")
        or data.get("policyOnly")
        or data.get("source_kind") == "policy"
        or data.get("sourceKind") == "policy"
    )
    is_policy_only = explicit_policy_only if policy_only is None else bool(policy_only or explicit_policy_only)
    doc_id = _doc_id(data, number)
    chunk_id = _chunk_id(data, doc_id, number, policy_only=is_policy_only)
    title = _title(data, doc_id, number)
    organization = _organization(data)
    snippet = snippet_from_text(data.get("snippet") or data.get("text") or fallback_snippet)
    if not snippet:
        snippet = f"Source locator for {title}."

    normalized: dict[str, Any] = {
        "contract": "source_locator_v1",
        "source_id": _clean_text(data.get("source_id") or data.get("sourceId")) or f"{doc_id}#{chunk_id}",
        "source_number": number,
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "title": title,
        "organization": organization,
        "snippet": snippet,
    }

    passthrough_keys = (
        "procedure_id",
        "machine_id",
        "job_id",
        "authority_level",
        "domain",
        "subdomain",
        "version",
        "license",
        "retrieved_date",
        "source_index",
        "policy_id",
    )
    for key in passthrough_keys:
        if key in data and data[key] not in (None, ""):
            normalized[key] = data[key]

    if policy_id and "policy_id" not in normalized:
        normalized["policy_id"] = policy_id
    if is_policy_only:
        normalized["policy_only"] = True
        normalized.setdefault("source_kind", "policy")

    for key in ("page", "page_label", "pdf_url", "bbox", "char_range", "text_search"):
        value = _first_locator_value(data, key)
        if value not in (None, "", [], {}):
            normalized[key] = value

    if "text_search" not in normalized and normalized.get("page") and snippet:
        normalized["text_search"] = snippet_from_text(snippet, limit=240)

    return normalized


def normalize_source_locators(
    sources: Iterable[Any],
    *,
    fallback_snippet: Any = None,
    policy_id: str | None = None,
    policy_only: bool | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, source in enumerate(sources or []):
        row = normalize_source_locator(
            source,
            index,
            fallback_snippet=fallback_snippet,
            policy_id=policy_id,
            policy_only=policy_only,
        )
        key = (str(row.get("source_id") or ""), str(row.get("doc_id") or ""), str(row.get("chunk_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        row["source_index"] = len(normalized)
        row["source_number"] = len(normalized) + 1
        normalized.append(row)
    return normalized
