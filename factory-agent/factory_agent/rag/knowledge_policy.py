from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from factory_agent.rag.source_metadata import (
    insufficient_context_answer,
    normalize_source_locators,
    sanitize_rag_answer_text,
)


UNABLE_ANSWER_PREFIXES = (
    "no relevant documents",
    "unable to generate",
)


@dataclass(frozen=True)
class KnowledgePolicy:
    policy_id: str
    route_families: tuple[str, ...]
    required_topics: tuple[str, ...] = ()
    required_query_evidence: tuple[str, ...] = ()
    safety_content: str | None = None
    required_answer_evidence: tuple[str, ...] = ()

    def applies_to(
        self,
        *,
        route_family: str,
        query: str,
        semantic_frame: Any | None = None,
    ) -> bool:
        if route_family not in self.route_families:
            return False
        topics = set(_semantic_topics(semantic_frame))
        if self.required_topics and not topics.intersection(self.required_topics):
            return False
        if self.required_query_evidence and not any(
            re.search(pattern, query or "", re.IGNORECASE)
            for pattern in self.required_query_evidence
        ):
            return False
        return True


@dataclass(frozen=True)
class KnowledgePolicyApplication:
    policy_id: str | None = None
    answer: str | None = None
    sources: list[Any] = field(default_factory=list)
    safety_content: str | None = None

    @property
    def applies(self) -> bool:
        return self.policy_id is not None


class KnowledgePolicyRegistry:
    def __init__(self, policies: Sequence[KnowledgePolicy] | None = None) -> None:
        self._policies = tuple(policies or ())

    def select(
        self,
        *,
        route_family: str,
        query: str,
        semantic_frame: Any | None = None,
    ) -> KnowledgePolicy | None:
        for policy in self._policies:
            if policy.applies_to(route_family=route_family, query=query, semantic_frame=semantic_frame):
                return policy
        return None

    def apply(
        self,
        *,
        route_family: str,
        query: str,
        answer: str,
        sources: Sequence[Any],
        safety_content: str | None,
        semantic_frame: Any | None = None,
    ) -> KnowledgePolicyApplication:
        policy = self.select(route_family=route_family, query=query, semantic_frame=semantic_frame)
        if policy is None:
            merged_answer = sanitize_rag_answer_text(answer)
            if route_family in {"rag.procedure", "rag.loto_procedure", "rag.safety_policy"} and _is_empty_or_unusable_answer(
                merged_answer
            ):
                merged_answer = insufficient_context_answer(has_sources=bool(sources))
            return KnowledgePolicyApplication(answer=merged_answer, sources=list(sources), safety_content=safety_content)

        merged_answer = (answer or "").strip()
        merged_sources = list(sources)
        merged_safety = safety_content
        if (
            _is_empty_or_unusable_answer(merged_answer)
            or not merged_sources
            or not _answer_has_required_evidence(merged_answer, policy.required_answer_evidence)
        ):
            merged_answer = insufficient_context_answer(has_sources=bool(merged_sources))
        merged_safety = merged_safety or policy.safety_content
        merged_answer = sanitize_rag_answer_text(merged_answer)
        merged_sources = normalize_source_locators(
            merged_sources,
            fallback_snippet=merged_answer,
            policy_id=policy.policy_id,
        )

        return KnowledgePolicyApplication(
            policy_id=policy.policy_id,
            answer=merged_answer,
            sources=merged_sources,
            safety_content=merged_safety,
        )


def default_knowledge_policy_registry() -> KnowledgePolicyRegistry:
    return KnowledgePolicyRegistry(
        policies=[
            KnowledgePolicy(
                policy_id="loto_notification_document_content",
                route_families=("rag.procedure", "rag.loto_procedure", "rag.safety_policy"),
                required_topics=("loto",),
                required_query_evidence=(
                    r"\bnotif(?:y|ying|ied|ication|ications)\b",
                    r"\baffected\s+employees?\b",
                    r"\bbefore\s+lockout\b",
                    r"\bbefore\s+lockout\s*/?\s*tagout\b",
                ),
                safety_content=(
                    "LOTO is safety-critical. Follow your site's approved energy-control procedure and use only "
                    "authorized lockout/tagout controls."
                ),
                required_answer_evidence=("notify", "affected employee"),
            ),
            KnowledgePolicy(
                policy_id="osha_loto_control_of_hazardous_energy",
                route_families=("rag.safety_policy", "rag.loto_procedure"),
                required_topics=("loto",),
                required_query_evidence=(
                    r"\bosha\b",
                    r"\b1910\.147\b",
                    r"\bhazardous\s+energy\b",
                    r"\bcontrol\s+of\s+hazardous\s+energy\b",
                ),
                safety_content=(
                    "This topic involves high-risk industrial procedures. Always follow your site's approved SOP, "
                    "obtain required permits, and consult your safety officer before proceeding."
                ),
                required_answer_evidence=("29 cfr 1910.147",),
            )
        ]
    )


def _semantic_topics(semantic_frame: Any | None) -> list[str]:
    if semantic_frame is None:
        return []
    normalized = getattr(semantic_frame, "normalized_entities", None)
    if not isinstance(normalized, dict):
        return []
    topics = normalized.get("topic") or []
    if isinstance(topics, str):
        topics = [topics]
    return [str(topic).strip().lower() for topic in topics if str(topic).strip()]


def _is_empty_or_unusable_answer(answer: str) -> bool:
    lowered = (answer or "").strip().lower()
    return not lowered or any(lowered.startswith(prefix) for prefix in UNABLE_ANSWER_PREFIXES)


def _answer_has_required_evidence(answer: str, required_evidence: Sequence[str]) -> bool:
    if not required_evidence:
        return True
    lowered = (answer or "").lower()
    return all(evidence.lower() in lowered for evidence in required_evidence)
