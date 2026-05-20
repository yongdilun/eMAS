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
class SourceIdentityRequirement:
    query_evidence: tuple[str, ...]
    identity_evidence: tuple[str, ...]

    def applies_to(self, query: str) -> bool:
        return _matches_any_pattern(query, self.query_evidence)


@dataclass(frozen=True)
class EvidenceSupportProfile:
    profile_id: str
    required_query_evidence: tuple[str, ...] = ()
    required_answer_evidence: tuple[str, ...] = ()
    required_answer_any_evidence: tuple[tuple[str, ...], ...] = ()
    required_source_evidence: tuple[str, ...] = ()
    required_source_any_evidence: tuple[tuple[str, ...], ...] = ()

    def applies_to(self, query: str) -> bool:
        return not self.required_query_evidence or _matches_any_pattern(query, self.required_query_evidence)


@dataclass(frozen=True)
class KnowledgePolicy:
    policy_id: str
    route_families: tuple[str, ...]
    required_topics: tuple[str, ...] = ()
    required_query_evidence: tuple[str, ...] = ()
    safety_content: str | None = None
    required_answer_evidence: tuple[str, ...] = ()
    source_identity_requirements: tuple[SourceIdentityRequirement, ...] = ()
    support_profiles: tuple[EvidenceSupportProfile, ...] = ()

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
        if self.required_query_evidence and not _matches_any_pattern(query, self.required_query_evidence):
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
            or not _policy_answer_has_required_evidence(
                policy=policy,
                query=query,
                answer=merged_answer,
                sources=merged_sources,
            )
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
                source_identity_requirements=(
                    SourceIdentityRequirement(
                        query_evidence=(r"\bosha\b",),
                        identity_evidence=("osha",),
                    ),
                ),
                support_profiles=(
                    EvidenceSupportProfile(
                        profile_id="reenergizing_notification",
                        required_query_evidence=(r"\bre-?energiz",),
                        required_answer_evidence=("employee",),
                        required_answer_any_evidence=(
                            ("know", "notify", "notification", "informed", "aware", "assure"),
                            ("reenerg", "removed", "device"),
                        ),
                        required_source_evidence=("reenerg", "employee"),
                        required_source_any_evidence=(
                            ("know", "assure", "notify", "informed", "aware"),
                            ("remov", "device"),
                        ),
                    ),
                ),
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
                support_profiles=(
                    EvidenceSupportProfile(
                        profile_id="osha_loto_standard_source_backed",
                        required_query_evidence=(
                            r"\bosha\b",
                            r"\b1910\.147\b",
                            r"\bhazardous\s+energy\b",
                            r"\bcontrol\s+of\s+hazardous\s+energy\b",
                        ),
                        required_answer_evidence=("29 cfr 1910.147",),
                        required_source_evidence=("29 cfr 1910.147",),
                        required_source_any_evidence=(("hazardous energy", "lockout", "tagout", "loto"),),
                    ),
                ),
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


def _matches_any_pattern(value: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, value or "", re.IGNORECASE) for pattern in patterns)


def _answer_has_required_evidence(answer: str, required_evidence: Sequence[str]) -> bool:
    if not required_evidence:
        return True
    lowered = (answer or "").lower()
    return all(evidence.lower() in lowered for evidence in required_evidence)


def _text_has_evidence(
    text: str,
    *,
    required_evidence: Sequence[str] = (),
    required_any_evidence: Sequence[Sequence[str]] = (),
) -> bool:
    lowered = (text or "").lower()
    if any(evidence.lower() not in lowered for evidence in required_evidence):
        return False
    for evidence_group in required_any_evidence:
        if not any(evidence.lower() in lowered for evidence in evidence_group):
            return False
    return True


def _policy_support_profile(policy: KnowledgePolicy, query: str) -> EvidenceSupportProfile | None:
    for profile in policy.support_profiles:
        if profile.applies_to(query):
            return profile
    return None


def _source_identity_requirements_are_met(
    *,
    policy: KnowledgePolicy,
    query: str,
    sources: Sequence[Any],
) -> bool:
    for requirement in policy.source_identity_requirements:
        if requirement.applies_to(query) and not _has_source_identity(sources, requirement.identity_evidence):
            return False
    return True


def _source_supports_profile(source: Any, profile: EvidenceSupportProfile) -> bool:
    return _text_has_evidence(
        _source_item_text(source),
        required_evidence=profile.required_source_evidence,
        required_any_evidence=profile.required_source_any_evidence,
    )


def _first_source_supporting_profile(
    sources: Sequence[Any],
    profile: EvidenceSupportProfile,
) -> Any | None:
    for source in sources:
        if _source_supports_profile(source, profile):
            return source
    return None


def _sources_support_profile(sources: Sequence[Any], profile: EvidenceSupportProfile) -> bool:
    return _first_source_supporting_profile(sources, profile) is not None


def _policy_answer_has_required_evidence(
    *,
    policy: KnowledgePolicy,
    query: str,
    answer: str,
    sources: Sequence[Any],
) -> bool:
    if not _source_identity_requirements_are_met(policy=policy, query=query, sources=sources):
        return False
    profile = _policy_support_profile(policy, query)
    if profile is not None:
        return _text_has_evidence(
            answer,
            required_evidence=profile.required_answer_evidence,
            required_any_evidence=profile.required_answer_any_evidence,
        ) and _sources_support_profile(sources, profile)
    return _answer_has_required_evidence(answer, policy.required_answer_evidence)


def _has_source_identity(sources: Sequence[Any], identity_evidence: Sequence[str]) -> bool:
    for source in sources:
        identity = _source_item_identity(source)
        if all(evidence.lower() in identity for evidence in identity_evidence):
            return True
    return False


def _source_item_text(source: Any) -> str:
    parts: list[str] = []
    for key in ("snippet", "text_search", "text", "title", "organization", "doc_id"):
        value = _source_value(source, key)
        if value:
            parts.append(str(value))
    return " ".join(parts).lower()


def _source_item_identity(source: Any) -> str:
    return " ".join(
        str(_source_value(source, key) or "")
        for key in ("doc_id", "title", "organization", "source_id")
    ).lower()


def _source_value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)
