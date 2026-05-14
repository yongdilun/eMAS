from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnswerField:
    label: str
    value: str
    key: str = ""
    primary: bool = False


@dataclass
class AnswerModel:
    answer_type: str
    entity_type: str
    entity_id: str
    title: str
    primary_status: str | None = None
    fields: list[AnswerField] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def render_answer_model_markdown(answer: AnswerModel) -> str:
    lines: list[str] = ["**Success**", ""]
    if answer.primary_status:
        lines.append(
            f"{answer.entity_type.capitalize()} **{answer.entity_id}** is currently **{answer.primary_status}**."
        )
    else:
        lines.append(f"{answer.title} for **{answer.entity_id}**.")
    if answer.fields:
        lines.append("")
        for f in answer.fields:
            if f.primary:
                continue
            lines.append(f"- **{f.label}:** {f.value}")
    return "\n".join(lines).strip()
