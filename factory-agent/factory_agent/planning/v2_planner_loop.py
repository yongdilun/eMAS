from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..schemas import PlanDraft, ToolInfo
from .tool_selector import ToolSelector
from .v2_contracts import (
    EvidenceLedgerEntry,
    PlannerOwnedLoopV2State,
)
from .v2_trace_compatibility import (
    attach_direct_v2_trace_to_intent_contract,
    build_direct_v2_compatibility_run,
)


@dataclass(frozen=True)
class PlannerOwnedV2LoopRun:
    state: PlannerOwnedLoopV2State
    draft: PlanDraft | None = None
    tool_outputs: list[dict[str, Any]] | None = None


class PlannerOwnedV2Loop:
    """Public compatibility wrapper for historical PlannerOwnedV2Loop imports.

    Normal runtime enters the planner-owned graph through PlanCreationService.
    This wrapper is retained only for out-of-tree callers that still import the
    old loop class to build direct-v2 compatibility traces and read-only drafts.
    Removal requires an explicit public-compatibility decision and a guard that
    no in-repo runtime imports or constructs this class.
    """

    def __init__(self, tool_selector: ToolSelector) -> None:
        self._tool_selector = tool_selector

    async def run(
        self,
        *,
        intent: str,
        tools_by_name: Mapping[str, ToolInfo],
        engine_mode: str | None,
        mode: str = "normal",
        direct_test_evidence: Sequence[EvidenceLedgerEntry | Mapping[str, Any]] | None = None,
    ) -> PlannerOwnedV2LoopRun:
        compatibility_run = await build_direct_v2_compatibility_run(
            tool_selector=self._tool_selector,
            intent=intent,
            tools_by_name=tools_by_name,
            engine_mode=engine_mode,
            mode=mode,
            direct_test_evidence=direct_test_evidence,
        )
        return PlannerOwnedV2LoopRun(
            state=compatibility_run.state,
            draft=compatibility_run.draft,
            tool_outputs=compatibility_run.tool_outputs,
        )
