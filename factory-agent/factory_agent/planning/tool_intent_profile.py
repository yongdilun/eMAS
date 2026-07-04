from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Literal

from ..schemas import ToolInfo


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_PATH_PARAM_RE = re.compile(r"^\{[^}]+\}$")
_ID_LIKE_RE = re.compile(r"\b[A-Z]{1,10}[-_][A-Z0-9]+(?:[-_][A-Z0-9]+)*\b|\b\d+\b", re.IGNORECASE)
_GENERATED_VOCAB_PATH = Path(__file__).resolve().parents[1] / "generated" / "tool_intent_vocabulary.json"

EndpointShape = Literal["collection", "item", "mutation"]


@dataclass(frozen=True)
class ToolIntentProfile:
    name: str
    endpoint_root: str
    endpoint_segments: tuple[str, ...]
    endpoint_shape: EndpointShape
    action: str
    identity_tokens: frozenset[str]
    feature_tokens: frozenset[str]
    field_tokens: frozenset[str]
    has_path_id: bool
    parent_endpoint: str | None


@dataclass(frozen=True)
class ToolIntentVocabulary:
    generic_tokens: frozenset[str]
    entity_tokens: frozenset[str]
    operator_tokens: frozenset[str]
    known_tool_tokens: frozenset[str]


EMPTY_VOCABULARY = ToolIntentVocabulary(
    generic_tokens=frozenset(),
    entity_tokens=frozenset(),
    operator_tokens=frozenset(),
    known_tool_tokens=frozenset(),
)


def normalize_token(token: str) -> str:
    lowered = (token or "").strip().lower()
    if lowered == "status":
        return lowered
    if lowered.endswith("ing") and len(lowered) > 5:
        lowered = lowered[:-3]
    elif lowered.endswith("ed") and len(lowered) > 4:
        lowered = lowered[:-2]
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith("sses") and len(lowered) > 5:
        return lowered[:-2]
    if lowered.endswith("ss"):
        return lowered
    if lowered.endswith("s") and len(lowered) > 3:
        return lowered[:-1]
    return lowered


def tokenize(text: str) -> set[str]:
    raw = {normalize_token(match.group(0)) for match in _TOKEN_RE.finditer(text or "")}
    return {token for token in raw if token}


def _tool_metadata_tokens(tool: ToolInfo) -> set[str]:
    schema_text = " ".join([_schema_text(tool.input_schema), _schema_text(tool.output_schema), _schema_text(tool.body_schema)])
    return tokenize(
        " ".join(
            [
                tool.name.replace("__", " ").replace("_", " "),
                tool.description,
                tool.endpoint.replace("/", " "),
                tool.method,
                " ".join(tool.capability_tags or []),
                " ".join(tool.path_params or []),
                " ".join(tool.query_params or []),
                " ".join(tool.body_fields or []),
                " ".join(tool.required_body_fields or []),
                schema_text,
            ]
        )
    )


def _collection_entity_tokens(tools: list[ToolInfo]) -> set[str]:
    by_endpoint = {(tool.method, (tool.endpoint or "").rstrip("/")) for tool in tools}
    entities: set[str] = set()
    first_segment_counts: dict[str, int] = {}

    for tool in tools:
        parts = [part for part in (tool.endpoint or "").strip("/").split("/") if part]
        if parts and not _PATH_PARAM_RE.match(parts[0]):
            root = normalize_token(parts[0])
            if root:
                first_segment_counts[root] = first_segment_counts.get(root, 0) + 1
        for index, part in enumerate(parts[:-1]):
            if _PATH_PARAM_RE.match(parts[index + 1]):
                entities.update(tokenize(part))

        if not parts:
            continue
        collection = f"/{parts[0]}"
        has_collection_read = ("GET", collection) in by_endpoint
        has_collection_write = ("POST", collection) in by_endpoint
        has_member_read = ("GET", f"{collection}/{{id}}") in by_endpoint
        has_member_write = any(
            (method, f"{collection}/{{id}}") in by_endpoint
            for method in ("PUT", "PATCH", "DELETE")
        )
        if has_collection_read and (has_collection_write or has_member_read or has_member_write):
            entities.update(tokenize(parts[0]))

    for root, count in first_segment_counts.items():
        if count >= 3:
            entities.add(root)

    return entities


def _schema_ai_entity_tokens(schema: dict | None) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    entities: set[str] = set()
    entity = schema.get("x-ai-entity")
    if isinstance(entity, str) and entity.strip():
        entities.update(tokenize(entity))
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for child in properties.values():
            entities.update(_schema_ai_entity_tokens(child if isinstance(child, dict) else None))
    items = schema.get("items")
    if isinstance(items, dict):
        entities.update(_schema_ai_entity_tokens(items))
    for key in ("allOf", "oneOf", "anyOf"):
        parts = schema.get(key)
        if isinstance(parts, list):
            for part in parts:
                entities.update(_schema_ai_entity_tokens(part if isinstance(part, dict) else None))
    return entities


def _explicit_ai_entity_tokens(tools: list[ToolInfo]) -> set[str]:
    entities: set[str] = set()
    for tool in tools:
        entities.update(_schema_ai_entity_tokens(tool.input_schema))
        entities.update(_schema_ai_entity_tokens(tool.output_schema))
        entities.update(_schema_ai_entity_tokens(tool.body_schema))
    return entities


def build_tool_intent_vocabulary(
    tools: list[ToolInfo],
    *,
    generic_threshold: float = 0.60,
    operator_tokens: set[str] | None = None,
) -> ToolIntentVocabulary:
    tool_count = len(tools)
    if tool_count <= 0:
        return EMPTY_VOCABULARY

    document_frequency: dict[str, int] = {}
    known_tokens: set[str] = set()
    for tool in tools:
        tokens = _tool_metadata_tokens(tool)
        known_tokens.update(tokens)
        for token in tokens:
            document_frequency[token] = document_frequency.get(token, 0) + 1

    min_count = max(3, int(round(tool_count * generic_threshold)))
    generic_tokens = {
        token
        for token, count in document_frequency.items()
        if count >= min_count and count / tool_count >= generic_threshold
    }
    entity_tokens = _collection_entity_tokens(tools) | _explicit_ai_entity_tokens(tools)
    normalized_operator_tokens = {
        token
        for token in tokenize(" ".join(operator_tokens or set()))
        if token not in entity_tokens
    }
    return ToolIntentVocabulary(
        generic_tokens=frozenset(generic_tokens),
        entity_tokens=frozenset(entity_tokens),
        operator_tokens=frozenset(normalized_operator_tokens),
        known_tool_tokens=frozenset(known_tokens),
    )


def vocabulary_for_tools(tools: list[ToolInfo]) -> ToolIntentVocabulary:
    generated = load_generated_vocabulary()
    scoped = build_tool_intent_vocabulary(tools, operator_tokens=set(generated.operator_tokens))
    entity_tokens = set(generated.entity_tokens) | set(scoped.entity_tokens)
    return ToolIntentVocabulary(
        generic_tokens=frozenset((set(generated.generic_tokens) | set(scoped.generic_tokens)) - entity_tokens),
        entity_tokens=frozenset(entity_tokens),
        operator_tokens=frozenset(set(generated.operator_tokens) | set(scoped.operator_tokens)),
        known_tool_tokens=frozenset(set(generated.known_tool_tokens) | set(scoped.known_tool_tokens)),
    )


@lru_cache(maxsize=1)
def load_generated_vocabulary() -> ToolIntentVocabulary:
    try:
        payload = json.loads(_GENERATED_VOCAB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return EMPTY_VOCABULARY
    return ToolIntentVocabulary(
        generic_tokens=frozenset(str(token) for token in payload.get("generic_tokens", []) if str(token)),
        entity_tokens=frozenset(str(token) for token in payload.get("entity_tokens", []) if str(token)),
        operator_tokens=frozenset(str(token) for token in payload.get("operator_tokens", []) if str(token)),
        known_tool_tokens=frozenset(str(token) for token in payload.get("known_tool_tokens", []) if str(token)),
    )


def _effective_vocabulary(vocabulary: ToolIntentVocabulary | None) -> ToolIntentVocabulary:
    if vocabulary is not None:
        return vocabulary
    return load_generated_vocabulary()


def _known_or_soft_known(token: str, known_tokens: frozenset[str]) -> bool:
    return not known_tokens or token in known_tokens or bool(_soft_overlap({token}, set(known_tokens)))


def _has_identifier(text: str) -> bool:
    return bool(_ID_LIKE_RE.search(text or ""))


def _strip_identifiers(text: str) -> str:
    return _ID_LIKE_RE.sub(" ", text or "")


def _soft_token_matches(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) < 4 or len(right) < 4:
        return False
    if left.startswith(right) or right.startswith(left):
        return True
    return len(left) >= 5 and len(right) >= 5 and left[:5] == right[:5]


def _soft_overlap(left: set[str], right: set[str]) -> set[str]:
    return {
        token
        for token in left
        if any(_soft_token_matches(token, candidate) for candidate in right)
    }


def _endpoint_segments(endpoint: str) -> tuple[str, ...]:
    parts: list[str] = []
    for raw in (endpoint or "").strip("/").split("/"):
        if not raw or _PATH_PARAM_RE.match(raw):
            continue
        parts.extend(sorted(tokenize(raw)))
    return tuple(parts)


def _endpoint_root(endpoint: str) -> str:
    for raw in (endpoint or "").strip("/").split("/"):
        if raw and not _PATH_PARAM_RE.match(raw):
            return normalize_token(raw)
    return ""


def _schema_text(schema: dict | None) -> str:
    if not isinstance(schema, dict):
        return ""
    parts: list[str] = []
    for key in ("title", "description"):
        value = schema.get(key)
        if isinstance(value, str):
            parts.append(value)
    enum_values = schema.get("enum")
    if isinstance(enum_values, list):
        parts.extend(str(value) for value in enum_values if str(value))
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, subschema in properties.items():
            parts.append(str(name))
            parts.append(_schema_text(subschema if isinstance(subschema, dict) else {}))
    items = schema.get("items")
    if isinstance(items, dict):
        parts.append(_schema_text(items))
    return " ".join(part for part in parts if part)


def _action_for_method(method: str) -> str:
    method = (method or "").upper()
    if method == "GET":
        return "read"
    if method == "POST":
        return "create"
    if method in {"PUT", "PATCH"}:
        return "update"
    if method == "DELETE":
        return "delete"
    return ""


def _endpoint_shape(endpoint: str, method: str) -> EndpointShape:
    parts = [part for part in (endpoint or "").strip("/").split("/") if part]
    if not parts:
        return "collection"
    param_indexes = [idx for idx, part in enumerate(parts) if _PATH_PARAM_RE.match(part)]
    if not param_indexes:
        return "collection"
    if param_indexes[-1] == len(parts) - 1:
        return "item"
    if (method or "").upper() != "GET":
        return "mutation"
    tail = (parts[-1] or "").strip().lower()
    return "collection" if tail.endswith("s") and not tail.endswith("ss") else "item"


def _parent_endpoint(endpoint: str) -> str | None:
    parts = [part for part in (endpoint or "").strip("/").split("/") if part]
    if len(parts) <= 2:
        return None
    if not _PATH_PARAM_RE.match(parts[-1]):
        parent = parts[:-1]
    else:
        parent = parts[:-2]
    if not parent:
        return None
    return "/" + "/".join(parent)


def build_tool_intent_profile(tool: ToolInfo, *, vocabulary: ToolIntentVocabulary | None = None) -> ToolIntentProfile:
    vocab = _effective_vocabulary(vocabulary)
    endpoint_segments = _endpoint_segments(tool.endpoint)
    field_text = " ".join(
        [
            " ".join(tool.path_params or []),
            " ".join(tool.query_params or []),
            " ".join(tool.body_fields or []),
            " ".join(tool.required_body_fields or []),
            _schema_text(tool.input_schema),
        ]
    )
    identity_tokens = frozenset(
        tokenize(
            " ".join(
                [
                    tool.name.replace("__", " ").replace("_", " "),
                    tool.description,
                    tool.endpoint.replace("/", " "),
                    " ".join(tool.capability_tags or []),
                ]
            )
        )
    )
    field_tokens = frozenset(tokenize(field_text))
    feature_tokens = frozenset(
        token
        for token in identity_tokens
        if token not in vocab.generic_tokens and token not in vocab.operator_tokens and not token.isdigit()
    )
    return ToolIntentProfile(
        name=tool.name,
        endpoint_root=_endpoint_root(tool.endpoint),
        endpoint_segments=endpoint_segments,
        endpoint_shape=_endpoint_shape(tool.endpoint, tool.method),
        action=_action_for_method(tool.method),
        identity_tokens=identity_tokens,
        feature_tokens=feature_tokens,
        field_tokens=field_tokens,
        has_path_id=bool(tool.path_params or "{" in (tool.endpoint or "")),
        parent_endpoint=_parent_endpoint(tool.endpoint),
    )


def intent_feature_tokens(intent: str, *, vocabulary: ToolIntentVocabulary | None = None) -> set[str]:
    vocab = _effective_vocabulary(vocabulary)
    tokens = tokenize(_strip_identifiers(intent))
    return {
        token
        for token in tokens
        if token not in vocab.generic_tokens
        and token not in vocab.operator_tokens
        and not token.isdigit()
        and _known_or_soft_known(token, vocab.known_tool_tokens)
    }


def profile_match_score(intent: str, tool: ToolInfo, *, vocabulary: ToolIntentVocabulary | None = None) -> int:
    intent_tokens = tokenize(intent)
    if not intent_tokens:
        return 0
    vocab = _effective_vocabulary(vocabulary)
    profile = build_tool_intent_profile(tool, vocabulary=vocab)
    feature_tokens = intent_feature_tokens(intent, vocabulary=vocab)
    score = 0

    identity_overlap = intent_tokens & set(profile.identity_tokens)
    identity_soft_overlap = _soft_overlap(intent_tokens, set(profile.identity_tokens)) - identity_overlap
    feature_overlap = feature_tokens & set(profile.feature_tokens)
    soft_feature_overlap = _soft_overlap(feature_tokens, set(profile.feature_tokens)) - feature_overlap
    endpoint_overlap = intent_tokens & set(profile.endpoint_segments)
    field_overlap = intent_tokens & set(profile.field_tokens)
    field_feature_overlap = feature_tokens & set(profile.field_tokens)
    endpoint_feature_overlap = feature_tokens & set(profile.endpoint_segments)
    non_entity_features = feature_tokens - set(vocab.entity_tokens)
    covered_features = feature_overlap | soft_feature_overlap | field_feature_overlap
    uncovered_discriminators = feature_tokens - covered_features - set(vocab.entity_tokens)

    score += len(identity_overlap) * 3
    score += len(identity_soft_overlap) * 4
    score += len(endpoint_overlap) * 5
    score += len(endpoint_feature_overlap) * 8
    score += len(feature_overlap) * 9
    score += len(soft_feature_overlap) * 7
    score += len(field_overlap) * 2
    score += len(field_feature_overlap) * 6

    if feature_tokens and endpoint_feature_overlap == feature_tokens:
        score += 30
    elif non_entity_features and non_entity_features <= endpoint_feature_overlap:
        score += 28
    elif non_entity_features and not (non_entity_features & set(profile.endpoint_segments)):
        score -= 24

    unrequested_endpoint_segments = (
        set(profile.endpoint_segments)
        - intent_tokens
        - set(vocab.generic_tokens)
        - set(vocab.operator_tokens)
        - {"api"}
    )
    if feature_tokens and unrequested_endpoint_segments:
        score -= min(18, 6 * len(unrequested_endpoint_segments))

    if feature_tokens and not uncovered_discriminators:
        score += 12
    if feature_tokens and not covered_features:
        score -= 12
    elif feature_tokens and profile.feature_tokens and uncovered_discriminators:
        score -= min(10, 2 * len(profile.feature_tokens))

    root = profile.endpoint_root
    if root and root in intent_tokens:
        score += 8
    if root and root not in intent_tokens and feature_tokens and not feature_overlap and not soft_feature_overlap:
        score -= 3

    if profile.has_path_id:
        if _has_identifier(intent):
            score += 2
        else:
            score -= 24
    elif profile.action == "read":
        if {"all", "list"} & intent_tokens:
            score += 6
        if not _has_identifier(intent):
            score += 3

    return score


def tool_covers_descriptive_terms(intent: str, tool: ToolInfo, *, vocabulary: ToolIntentVocabulary | None = None) -> bool:
    vocab = _effective_vocabulary(vocabulary)
    features = intent_feature_tokens(intent, vocabulary=vocab)
    if not features:
        return False
    profile = build_tool_intent_profile(tool, vocabulary=vocab)
    covered = _soft_overlap(features, set(profile.identity_tokens))
    if not covered:
        return False
    uncovered = features - covered
    if not uncovered:
        return True
    return bool(covered - set(vocab.entity_tokens)) and uncovered <= set(vocab.entity_tokens)


def child_tools_for_parent(parent: ToolInfo, tools: list[ToolInfo]) -> list[ToolInfo]:
    parent_endpoint = parent.endpoint
    return [
        tool
        for tool in tools
        if tool is not parent
        and tool.method == "GET"
        and tool.endpoint.startswith(parent_endpoint.rstrip("/") + "/")
    ]

