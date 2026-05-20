from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from factory_agent.rag.source_metadata import (
    insufficient_context_answer,
    is_insufficient_context_answer,
    sanitize_rag_answer_text,
)


_CITATION_MARKER_RE = re.compile(r"\[(?:\^)?(\d+)\]")
_NUMBERED_PROCEDURE_LINE_RE = re.compile(r"^\s*(?:\d+[\.)]|[-*]\s*\d+[\.)])\s+")
_NUMBERED_PROCEDURE_STEP_RE = re.compile(r"(?<!\w)(?:[-*]\s*)?\d+[\.)]\s+")
_INCOMPLETE_NUMBERED_ITEM_RE = re.compile(r"^\s*(?:[-*]\s*)?\d+[\.)]?\s*$")
_INCOMPLETE_NUMBERED_AFTER_CITATION_TAIL_RE = re.compile(r"\[(?:\^)?\d+\][\s;]+(?:[-*]\s*)?\d+[\.)]?\s*$")
_WORD_RE = re.compile(r"[A-Za-z0-9]")


@dataclass(frozen=True)
class KnowledgeAnswerValidation:
    valid: bool
    answer: str
    reason: str | None = None
    insufficient_context: bool = False
    cited_source_numbers: tuple[int, ...] = ()


def validate_knowledge_answer(answer: Any, sources: Sequence[Any]) -> KnowledgeAnswerValidation:
    clean_answer = sanitize_rag_answer_text(answer)
    if is_insufficient_context_answer(clean_answer):
        return KnowledgeAnswerValidation(valid=True, answer=clean_answer, insufficient_context=True)
    if not clean_answer:
        return KnowledgeAnswerValidation(valid=False, answer=clean_answer, reason="empty_answer")

    source_numbers = _available_source_numbers(sources)
    if not source_numbers:
        return KnowledgeAnswerValidation(valid=False, answer=clean_answer, reason="missing_sources")

    cited_numbers = _citation_numbers(clean_answer)
    if not cited_numbers:
        return KnowledgeAnswerValidation(valid=False, answer=clean_answer, reason="missing_citations")

    unknown_numbers = cited_numbers.difference(source_numbers)
    if unknown_numbers:
        return KnowledgeAnswerValidation(
            valid=False,
            answer=clean_answer,
            reason="unknown_citation",
            cited_source_numbers=tuple(sorted(cited_numbers)),
        )

    if _has_incomplete_numbered_item(clean_answer):
        return KnowledgeAnswerValidation(
            valid=False,
            answer=clean_answer,
            reason="incomplete_numbered_item",
            cited_source_numbers=tuple(sorted(cited_numbers)),
        )

    if _has_uncited_procedure_step(clean_answer):
        return KnowledgeAnswerValidation(
            valid=False,
            answer=clean_answer,
            reason="uncited_procedure_step",
            cited_source_numbers=tuple(sorted(cited_numbers)),
        )

    if _has_uncited_claim_line(clean_answer):
        return KnowledgeAnswerValidation(
            valid=False,
            answer=clean_answer,
            reason="uncited_claim",
            cited_source_numbers=tuple(sorted(cited_numbers)),
        )

    return KnowledgeAnswerValidation(
        valid=True,
        answer=clean_answer,
        cited_source_numbers=tuple(sorted(cited_numbers)),
    )


def answer_or_insufficient_context(answer: Any, sources: Sequence[Any]) -> tuple[str, KnowledgeAnswerValidation]:
    validation = validate_knowledge_answer(answer, sources)
    if validation.valid:
        return validation.answer, validation
    return insufficient_context_answer(has_sources=bool(sources)), validation


def _available_source_numbers(sources: Sequence[Any]) -> set[int]:
    numbers: set[int] = set()
    for index, source in enumerate(sources, start=1):
        value = _source_value(source, "source_number")
        try:
            numbers.add(int(value))
        except (TypeError, ValueError):
            numbers.add(index)
    return numbers


def _citation_numbers(answer: str) -> set[int]:
    numbers: set[int] = set()
    for match in _CITATION_MARKER_RE.finditer(answer or ""):
        raw = match.group(1)
        try:
            numbers.add(int(raw))
        except (TypeError, ValueError):
            continue
    return numbers


def _has_uncited_claim_line(answer: str) -> bool:
    if _has_uncited_tail_after_last_citation(answer):
        return True
    lines = [line.strip() for line in re.split(r"[\r\n]+", answer or "") if line.strip()]
    if not lines:
        return False
    has_cited_line = any(_CITATION_MARKER_RE.search(line) for line in lines)
    for index, line in enumerate(lines):
        if _CITATION_MARKER_RE.search(line):
            continue
        if _is_citation_framing_line(line, index=index, has_cited_line=has_cited_line):
            continue
        if _looks_like_claim_line(line):
            return True
    return False


def _has_incomplete_numbered_item(answer: str) -> bool:
    lines = [line.strip() for line in re.split(r"[\r\n]+", answer or "") if line.strip()]
    if any(_INCOMPLETE_NUMBERED_ITEM_RE.fullmatch(line) for line in lines):
        return True
    if _INCOMPLETE_NUMBERED_AFTER_CITATION_TAIL_RE.search(answer or ""):
        return True

    matches = list(_NUMBERED_PROCEDURE_STEP_RE.finditer(answer or ""))
    if not matches:
        return False
    for index, match in enumerate(matches):
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(answer)
        segment = answer[match.start() : segment_end].strip()
        if _INCOMPLETE_NUMBERED_ITEM_RE.fullmatch(segment):
            return True
    return False


def _has_uncited_procedure_step(answer: str) -> bool:
    matches = list(_NUMBERED_PROCEDURE_STEP_RE.finditer(answer or ""))
    if not matches:
        return False
    for index, match in enumerate(matches):
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(answer)
        segment = answer[match.start() : segment_end]
        if _looks_like_claim_line(segment) and not _CITATION_MARKER_RE.search(segment):
            return True
    return False


def _has_uncited_tail_after_last_citation(answer: str) -> bool:
    matches = list(_CITATION_MARKER_RE.finditer(answer or ""))
    if not matches:
        return False
    tail = answer[matches[-1].end() :].strip()
    tail = tail.lstrip(" \t\r\n.,;:!?")
    return _looks_like_claim_line(tail)


def _is_citation_framing_line(line: str, *, index: int, has_cited_line: bool) -> bool:
    return index == 0 and has_cited_line and len(line) <= 160 and line.endswith(":")


def _looks_like_claim_line(line: str) -> bool:
    if not _WORD_RE.search(line):
        return False
    if _NUMBERED_PROCEDURE_LINE_RE.search(line):
        return True
    words = re.findall(r"[A-Za-z0-9]+", line)
    return len(words) >= 4


def _source_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)
