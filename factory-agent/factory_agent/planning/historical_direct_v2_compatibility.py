from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal


HistoricalDirectV2CreatedBy = Literal["v2_planner_loop"]
HistoricalDirectV2GeneratedBy = Literal["v2_planner_loop"]

HISTORICAL_DIRECT_V2_CREATED_BY: HistoricalDirectV2CreatedBy = "v2_planner_loop"
HISTORICAL_DIRECT_V2_GENERATED_BY: HistoricalDirectV2GeneratedBy = "v2_planner_loop"
HISTORICAL_DIRECT_V2_APPROVAL_PAYLOAD_KIND = "v2_planner_owned_approval_preview"


def historical_direct_v2_created_by() -> HistoricalDirectV2CreatedBy:
    return HISTORICAL_DIRECT_V2_CREATED_BY


def historical_direct_v2_generated_by() -> HistoricalDirectV2GeneratedBy:
    return HISTORICAL_DIRECT_V2_GENERATED_BY


def is_historical_direct_v2_created_by(value: Any) -> bool:
    return _normalized_historical_direct_v2_value(value) == HISTORICAL_DIRECT_V2_CREATED_BY


def is_historical_direct_v2_generated_by(value: Any) -> bool:
    return _normalized_historical_direct_v2_value(value) == HISTORICAL_DIRECT_V2_GENERATED_BY


def is_historical_direct_v2_approval_payload(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    bundle_ui = payload.get("bundle_ui")
    if not isinstance(bundle_ui, Mapping):
        return False
    return bundle_ui.get("kind") == HISTORICAL_DIRECT_V2_APPROVAL_PAYLOAD_KIND


def _normalized_historical_direct_v2_value(value: Any) -> str:
    return str(value or "").strip().lower()
