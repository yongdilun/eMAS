from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal


HistoricalLegacyRagRouteGeneratedBy = Literal["legacy_rag_route"]
HistoricalLegacyRagRouteSourceType = Literal["legacy_rag_route"]
HistoricalLegacyRagShortcutDetectorName = Literal["legacy_rag_shortcut"]

HISTORICAL_LEGACY_RAG_ROUTE_GENERATED_BY: HistoricalLegacyRagRouteGeneratedBy = "legacy_rag_route"
HISTORICAL_LEGACY_RAG_ROUTE_SOURCE_TYPE: HistoricalLegacyRagRouteSourceType = "legacy_rag_route"
HISTORICAL_LEGACY_RAG_SHORTCUT_DETECTOR_NAME: HistoricalLegacyRagShortcutDetectorName = "legacy_rag_shortcut"
HISTORICAL_LEGACY_RAG_ROUTE_CANNOT_SATISFY_ISSUE = "legacy_rag_route_cannot_satisfy_v2"


def historical_legacy_rag_route_generated_by() -> HistoricalLegacyRagRouteGeneratedBy:
    return HISTORICAL_LEGACY_RAG_ROUTE_GENERATED_BY


def historical_legacy_rag_route_source_type() -> HistoricalLegacyRagRouteSourceType:
    return HISTORICAL_LEGACY_RAG_ROUTE_SOURCE_TYPE


def historical_legacy_rag_shortcut_detector_name() -> HistoricalLegacyRagShortcutDetectorName:
    return HISTORICAL_LEGACY_RAG_SHORTCUT_DETECTOR_NAME


def historical_legacy_rag_route_cannot_satisfy_issue() -> str:
    return HISTORICAL_LEGACY_RAG_ROUTE_CANNOT_SATISFY_ISSUE


def is_historical_legacy_rag_route_generated_by(value: Any) -> bool:
    return _normalized_historical_legacy_rag_route_value(value) == HISTORICAL_LEGACY_RAG_ROUTE_GENERATED_BY


def is_historical_legacy_rag_route_source_type(value: Any) -> bool:
    return _normalized_historical_legacy_rag_route_value(value) == HISTORICAL_LEGACY_RAG_ROUTE_SOURCE_TYPE


def is_historical_legacy_rag_route_evidence(value: Any) -> bool:
    source_type = getattr(value, "source_type", value)
    return is_historical_legacy_rag_route_source_type(source_type)


def historical_legacy_rag_shortcut_detector_used(detectors: Any) -> bool:
    shortcut = _detector_value(detectors, HISTORICAL_LEGACY_RAG_SHORTCUT_DETECTOR_NAME)
    if isinstance(shortcut, Mapping):
        return bool(shortcut.get("used"))
    return bool(getattr(shortcut, "used", False))


def _detector_value(detectors: Any, name: str) -> Any:
    if isinstance(detectors, Mapping):
        return detectors.get(name)
    return getattr(detectors, name, None)


def _normalized_historical_legacy_rag_route_value(value: Any) -> str:
    return str(value or "").strip().lower()
