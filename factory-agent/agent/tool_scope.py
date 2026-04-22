from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import ToolInfo


@dataclass(frozen=True)
class ScopedTools:
    tool_names: list[str]


_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")


def _tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}


def score_tool(intent: str, tool: ToolInfo) -> int:
    intent_tokens = _tokenize(intent)
    if not intent_tokens:
        return 0

    score = 0
    for tag in tool.capability_tags:
        if tag.lower() in intent_tokens:
            score += 10

    # Lightweight text overlap
    for tok in intent_tokens:
        if tok in (tool.name.lower() or ""):
            score += 3
        if tok in (tool.endpoint.lower() or ""):
            score += 2
        if tok in (tool.description.lower() or ""):
            score += 1

    # Bias toward read-only tools for early discovery
    if tool.is_read_only:
        score += 1

    return score


def filter_tools_for_intent(
    *,
    intent: str,
    tools_by_name: dict[str, ToolInfo],
    max_tools: int = 40,
) -> ScopedTools:
    ranked = sorted(
        tools_by_name.values(),
        key=lambda t: score_tool(intent, t),
        reverse=True,
    )

    # Always include approval tools if present (helps LLM reason about gating/resume)
    forced_prefixes = ("get__chatbot_approval", "post__chatbot_approval")
    forced = [t.name for t in tools_by_name.values() if t.name.startswith(forced_prefixes)]

    picked: list[str] = []
    for t in ranked:
        if len(picked) >= max_tools:
            break
        if score_tool(intent, t) <= 0 and len(picked) >= 8:
            break
        picked.append(t.name)

    merged = []
    seen = set()
    for name in forced + picked:
        if name in tools_by_name and name not in seen:
            merged.append(name)
            seen.add(name)

    return ScopedTools(tool_names=merged)

