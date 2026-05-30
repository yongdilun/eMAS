from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PromptContractStatus = Literal["active", "optional", "legacy", "retired"]


@dataclass(frozen=True)
class PromptContract:
    name: str
    version: str
    status: PromptContractStatus
    purpose: str
    inputs: tuple[str, ...]
    output_contract: str
    validator: str
    fallback: str
    owner_module: str


def validate_prompt_contract(contract: PromptContract) -> None:
    required_text_fields = {
        "name": contract.name,
        "version": contract.version,
        "status": contract.status,
        "purpose": contract.purpose,
        "output_contract": contract.output_contract,
        "validator": contract.validator,
        "fallback": contract.fallback,
        "owner_module": contract.owner_module,
    }
    empty = [field for field, value in required_text_fields.items() if not str(value or "").strip()]
    if empty:
        raise ValueError(f"Prompt contract {contract.name or '<unnamed>'} has empty required fields: {empty}")
    if contract.status not in {"active", "optional", "legacy", "retired"}:
        raise ValueError(f"Prompt contract {contract.name} has unsupported status {contract.status!r}")
    if not contract.inputs:
        raise ValueError(f"Prompt contract {contract.name} must declare at least one input")
    if len(set(contract.inputs)) != len(contract.inputs):
        raise ValueError(f"Prompt contract {contract.name} has duplicate input names")


PROMPT_CONTRACTS: tuple[PromptContract, ...] = (
    PromptContract(
        name="planner_decision_v2",
        version="v2",
        status="active",
        purpose="Propose one planner-owned graph decision from bounded state and candidate tool windows.",
        inputs=("decision_state", "candidate_tool_windows", "hydrated_tool_cards"),
        output_contract="planner_decision_v2_json",
        validator="factory_agent.planning.v2_planner_decisions.validate_planner_decision",
        fallback="deterministic planner-owned graph guards reject invalid decisions",
        owner_module="factory_agent.planning.v2_planner_proposer",
    ),
    PromptContract(
        name="rag_answer_v1",
        version="v1",
        status="active",
        purpose="Generate a source-grounded maintenance answer with explicit citation markers.",
        inputs=("question", "api_data_section", "context", "sources"),
        output_contract="knowledge_answer_v1",
        validator="factory_agent.rag.answer_contract.validate_knowledge_answer",
        fallback="insufficient_context_answer",
        owner_module="factory_agent.rag.generation",
    ),
    PromptContract(
        name="rag_answer_repair_v1",
        version="v1",
        status="active",
        purpose="Repair a RAG answer that failed citation or completeness validation.",
        inputs=("question", "draft_answer", "validation_errors", "context", "sources"),
        output_contract="knowledge_answer_v1",
        validator="factory_agent.rag.answer_contract.validate_knowledge_answer",
        fallback="insufficient_context_answer",
        owner_module="factory_agent.rag.generation",
    ),
    PromptContract(
        name="tool_selector_rerank_v1",
        version="v1",
        status="active",
        purpose="Rerank deterministic tool candidates for a user intent using strict JSON output.",
        inputs=("intent", "candidates"),
        output_contract="tool_selector_rerank_json",
        validator="factory_agent.planning.tool_selector.ToolSelector._parse_rerank_response",
        fallback="retrieval-ranked candidates",
        owner_module="factory_agent.planning.tool_selector",
    ),
    PromptContract(
        name="semantic_intake_v1",
        version="v1",
        status="active",
        purpose="Label already-prepared user clauses for deterministic requirement compilation.",
        inputs=("text", "prepared_clauses"),
        output_contract="semantic_intake_json",
        validator="factory_agent.planning.semantic_intake.SemanticIntakeResult.model_validate",
        fallback="deterministic semantic intake",
        owner_module="factory_agent.planning.semantic_intake",
    ),
)


def prompt_contracts_by_name() -> dict[str, PromptContract]:
    return {contract.name: contract for contract in PROMPT_CONTRACTS}


__all__ = [
    "PROMPT_CONTRACTS",
    "PromptContract",
    "PromptContractStatus",
    "prompt_contracts_by_name",
    "validate_prompt_contract",
]
