from __future__ import annotations

import re
from dataclasses import dataclass

from .intent import assess_intent
from ..schemas import ToolInfo
from .tool_intent_profile import ToolIntentVocabulary, profile_match_score, vocabulary_for_tools


@dataclass(frozen=True)
class ScopedTools:
    tool_names: list[str]

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
_ACTION_TOKENS = {
    "create": {"add", "create", "new", "open"},
    "update": {"apply", "assign", "change", "move", "record", "reschedule", "run", "set", "update"},
    "delete": {"delete", "remove"},
    "read": {"check", "find", "get", "inspect", "list", "lookup", "preview", "read", "report", "show", "view"},
    "approval": {"approval", "approve", "pending", "reject"},
}
_METHOD_HINTS = {
    "GET": {"read"},
    "POST": {"create"},
    "PUT": {"update"},
    "PATCH": {"update"},
    "DELETE": {"delete"},
}
_COMPOUND_SEPARATOR_RE = re.compile(
    r"\b(?:and then|then|next(?!\s+\d)|after that|afterwards|finally)\b|[;\n.]+",
    re.IGNORECASE,
)


def _tokenize(text: str) -> set[str]:
    tokens = {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}
    normalized: set[str] = set()
    for token in tokens:
        if token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 4:
            token = token[:-2]
        normalized.add(token)
        if token.endswith("ies") and len(token) > 3:
            normalized.add(token[:-3] + "y")
        elif token.endswith("s") and len(token) > 3:
            normalized.add(token[:-1])
    return normalized


def _tool_search_tokens(tool: ToolInfo) -> set[str]:
    parts = [
        tool.name,
        tool.description,
        tool.endpoint,
        " ".join(tool.capability_tags or []),
        " ".join(tool.path_params or []),
        " ".join(tool.query_params or []),
        " ".join(tool.body_fields or []),
    ]
    return _tokenize(" ".join(part for part in parts if part))


def _split_intent_clauses(intent: str) -> list[str]:
    parts = [part.strip(" ,") for part in _COMPOUND_SEPARATOR_RE.split(intent or "") if part and part.strip(" ,")]
    return parts or [intent]


def _ranked_tools(intent: str, tools_by_name: dict[str, ToolInfo], *, vocabulary: ToolIntentVocabulary) -> list[tuple[str, int]]:
    scores = {name: score_tool(intent, tool, vocabulary=vocabulary) for name, tool in tools_by_name.items()}
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def score_tool(intent: str, tool: ToolInfo, *, vocabulary: ToolIntentVocabulary | None = None) -> int:
    intent_tokens = _tokenize(intent)
    if not intent_tokens:
        return 0

    assessment = assess_intent(intent)
    tool_tokens = _tool_search_tokens(tool)
    score = profile_match_score(intent, tool, vocabulary=vocabulary)
    for tag in tool.capability_tags:
        if tag.lower() in intent_tokens:
            score += 10

    overlap = intent_tokens & tool_tokens
    for tok in overlap:
        if tok in (tool.capability_tags or []):
            score += 6
        elif tok in set(tool.body_fields or []):
            score += 5
        else:
            score += 2

    # Bias toward read-only tools for early discovery
    if tool.is_read_only:
        score += 1

    if assessment.entity and assessment.entity in tool.capability_tags:
        score += 12
        if tool.endpoint.lower().startswith(f"/{assessment.entity}"):
            score += 8
        elif tool.endpoint.lower().startswith(f"/{assessment.entity}s"):
            score += 8
    if assessment.action == "create" and tool.method == "POST":
        score += 12
    elif assessment.action == "update" and tool.method in {"PUT", "PATCH"}:
        score += 12
    elif assessment.action == "approval" and "approval" in tool.capability_tags:
        score += 16
    elif assessment.action == "delete" and tool.method == "DELETE":
        score += 12
    elif assessment.action == "read" and tool.method == "GET":
        score += 12

    hinted_actions = {action for action, words in _ACTION_TOKENS.items() if intent_tokens & words}
    if hinted_actions & _METHOD_HINTS.get(tool.method, set()):
        score += 8
    if "approval" in hinted_actions and "approval" in tool.capability_tags:
        score += 10

    if tool.path_params and any(token.isdigit() or "-" in token for token in intent_tokens):
        score += 3

    return score


def filter_tools_for_intent(
    *,
    intent: str,
    tools_by_name: dict[str, ToolInfo],
    max_tools: int = 30,
) -> ScopedTools:
    assessment = assess_intent(intent)
    if assessment.kind != "operations":
        return ScopedTools(tool_names=[])

    picked: list[str] = []
    seen: set[str] = set()
    clauses = _split_intent_clauses(intent)
    vocabulary = vocabulary_for_tools(list(tools_by_name.values()))
    for clause in clauses:
        ranked = _ranked_tools(clause, tools_by_name, vocabulary=vocabulary)
        top_score = ranked[0][1] if ranked else 0
        if top_score <= 2:
            continue
        clause_limit = max(3, min(8, max_tools))
        for name, score in ranked:
            if len(picked) >= max_tools or len([x for x in picked if x in seen]) >= max_tools:
                break
            if score <= 0:
                break
            if picked and score < max(2, top_score - 18) and name not in seen:
                break
            if name not in seen:
                picked.append(name)
                seen.add(name)
            if len(seen) >= clause_limit:
                break

    if not picked:
        return ScopedTools(tool_names=[])
    return ScopedTools(tool_names=picked)

