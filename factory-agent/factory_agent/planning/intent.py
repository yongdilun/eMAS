from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from hashlib import sha1
from typing import Any, Literal, Sequence

from ..schemas import ExplicitConstraint, Intent, IntentCategory

IntentKind = Literal["conversation", "unsupported", "operations"]
IntentAction = Literal["create", "update", "approval", "read", "delete"] | None
SemanticRoute = Literal[
    "rag.loto_procedure",
    "rag.procedure",
    "rag.safety_policy",
    "tool.read.machine_status",
    "tool.read.jobs",
    "tool.write.jobs",
    "approval_action",
    "cancel_run",
    "unsupported_dangerous_action",
    "clarification.machine_id_missing",
    "clarification.job_mutation_incomplete",
    "unknown",
]
QuestionType = Literal[
    "document_content_question",
    "machine_specific_procedure_selection",
    "safety_policy_question",
    "live_operational_status",
]

_GREETING_RE = re.compile(
    r"^\s*(?:hi|hello|hey|yo|good morning|good afternoon|good evening|thanks|thank you)\b",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"\b(?:what|how|why|when|where|which|who|meaning|definition|describe|explain|functions|framework|standard|policy|procedure|sop|loto|csf|ppe)\b",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE = re.compile(
    r"\s*\b(?:and then|then|next(?!\s+\d)|after that|afterwards|finally)\b\s*|\s+;\s*|\n+|(?<=[.!?])\s+(?=[A-Z])",
    re.IGNORECASE,
)
_PLAIN_AND_RE = re.compile(r"\s+\band\s+", re.IGNORECASE)
_RELATIONSHIP_COMPARISON_RE = re.compile(
    r"\b(?:compare|contrast|differentiate)\b|"
    r"\b(?:difference|differences|distinction)\s+between\b|"
    r"\b(?:relationship|relation)\s+between\b|"
    r"\brelat(?:e|es|ed|ing|ionship)\b|"
    r"\bversus\b|\bvs\.?\b",
    re.IGNORECASE,
)
_ANSWER_INSTRUCTION_START_RE = re.compile(
    r"^\s*(?:explain|summari[sz]e|describe)\b",
    re.IGNORECASE,
)
_APPROVAL_MODIFIER_RE = re.compile(
    r"^\s*(?:ask|request|require)\b.*\bapproval\b",
    re.IGNORECASE,
)
_ROUTABLE_OBJECT_HINT_RE = re.compile(
    r"\b(?:approvals?|change|changes|condition|deadline|fields?|health|inventory|jobs?|"
    r"machines?|materials?|priority|products?|reports?|schedule|slots?|status|tasks?|"
    r"work\s*orders?)\b",
    re.IGNORECASE,
)
_MACHINE_ID_PATTERN = r"(?:M-[A-Z0-9]+(?:-[A-Z0-9]+)*\d[A-Z0-9-]*|[A-Z]{1,3}-\d{2,})"
_MACHINE_ID_RE = re.compile(rf"\b({_MACHINE_ID_PATTERN})\b", re.IGNORECASE)
_JOB_TOKEN_RE = re.compile(
    r"\b(?:job|work\s*orders?|wo|task)\b\s*(?:id|#)?\s*((?:[A-Z]{1,6}-)?\d{2,}|[A-Z]{1,6}-[A-Z0-9-]*\d[A-Z0-9-]*)\b",
    re.IGNORECASE,
)
_BARE_JOB_ID_RE = re.compile(r"\b(JOB-[A-Z0-9-]+)\b", re.IGNORECASE)
_USE_MACHINE_RE = re.compile(
    rf"\b(?:use|with|for|on|at)\s+(?:machine\s+|equipment\s+|asset\s+)?({_MACHINE_ID_PATTERN})\b",
    re.IGNORECASE,
)
_MACHINE_NAME_RE = re.compile(r"\bmachine\s+([A-Z0-9][A-Z0-9-]*)\b", re.IGNORECASE)
_PRODUCT_RE = re.compile(r"\bproduct\s+([A-Z0-9][A-Z0-9-]*)\b", re.IGNORECASE)
_UNBOUND_REFERENT_ID_TOKENS = {
    "A",
    "AN",
    "APPLICABLE",
    "IF",
    "IT",
    "ITS",
    "ON",
    "ONE",
    "PRESENT",
    "RELATED",
    "THAT",
    "THE",
    "THIS",
    "TOO",
}
_MATERIAL_REF_RE = re.compile(
    r"\bmaterial\s+(?:id\s+)?([A-Z0-9][A-Z0-9-]*)\b",
    re.IGNORECASE,
)
_DATE_WITH_PREPOSITION_RE = re.compile(
    r"\b(?P<op>on|for|by|before|after|from|until|date)\s+"
    r"(?P<value>\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
    re.IGNORECASE,
)
_NATURAL_DATE_RE = re.compile(
    r"\b(today|tomorrow|tonight|next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week)|"
    r"this\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week))\b",
    re.IGNORECASE,
)
_OPERATOR_RE = re.compile(
    r"(?i:\b(?:operator|op)\s*(?:id|#|name)?\s*)"
    r"(?P<value>[A-Z][A-Za-z0-9-]{1,31}(?:\s+[A-Z][A-Za-z0-9-]{1,31})?)\b",
)
_SOFT_CONSTRAINT_HINT_RE = re.compile(r"\b(?:prefer|preferably|ideally|if possible|nice to have|try to)\b", re.IGNORECASE)

_ACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("approval", re.compile(r"\b(?:approve|reject|approval|approvals|pending approval|pending approvals)\b", re.IGNORECASE)),
    ("create", re.compile(r"\b(?:create|new|add|open)\b", re.IGNORECASE)),
    ("update", re.compile(r"\b(?:update|set|change|assign|record|apply|reschedule|move|schedule)\b", re.IGNORECASE)),
    ("delete", re.compile(r"\b(?:delete|remove)\b", re.IGNORECASE)),
    (
        "read",
        re.compile(
            r"\b(?:assist|candidate|check|delay|describe|explain|explosion|forecast|get|find|inspect|list|lookup|preview|rank|read|readiness|report|reports|risk|show|shortage|slots?|status|suggestion|timeout|view|available)\b",
            re.IGNORECASE,
        ),
    ),
]

_SCHEDULING_HINT = re.compile(
    r"\b(?:schedule|scheduling|assign|book|slot|calendar|dispatch)\b",
    re.IGNORECASE,
)
_INVENTORY_HINT = re.compile(
    r"\b(?:inventory|stock|parts?|shortage|warehouse|sku|material)\b",
    re.IGNORECASE,
)
_MACHINE_HINT = re.compile(
    r"\b(?:machine|machines|cnc|equipment|asset|assets|line|station|unit|oee|availability|available)\b",
    re.IGNORECASE,
)
_JOB_HINT = re.compile(r"\b(?:jobs?|work\s*orders?|wo\b|tasks?)\b", re.IGNORECASE)
_REPORT_HINT = re.compile(r"\b(?:report|export|csv|pdf|dashboard)\b", re.IGNORECASE)
# M-prefixed compound machine ids (e.g. M-LTH-02): used to suppress inner XXX-NN matches from _MACHINE_ID_RE.
_COMPOUND_M_MACHINE_RE = re.compile(rf"\b{_MACHINE_ID_PATTERN}\b", re.IGNORECASE)
_JOB_CREATE_RE = re.compile(r"\b(?:create|new|add|open)\s+job\s+", re.IGNORECASE)
_RESCHEDULE_ALL_JOBS_RE = re.compile(
    r"\b(?:reschedule|replan)\s+(?:all|every)\s+(?:jobs?|work\s*orders?)\b|"
    r"\b(?:all|every)\s+(?:jobs?|work\s*orders?)\s+(?:reschedule|replan)\b",
    re.IGNORECASE,
)
_LOTO_HINT_RE = re.compile(
    r"\b(?:loto|lock\s*out\s*/?\s*tag\s*out|lockout\s*/?\s*tagout|lockout|tagout|energy\s+isolation|hazardous\s+energy)\b",
    re.IGNORECASE,
)
_LOTO_PROCEDURE_CONTEXT_RE = re.compile(
    r"\b(?:procedure|sop|steps?|instructions?|appl(?:y|ies)|before\s+(?:working|servicing|maintenance|touching)|working\s+on|service|servicing|maintenance)\b",
    re.IGNORECASE,
)
_CONTEXTUAL_MACHINE_REF_RE = re.compile(
    r"\b(?:it|that\s+(?:machine|equipment|asset)|the\s+(?:machine|equipment|asset))\b",
    re.IGNORECASE,
)
_STATUS_MACHINE_REQUEST_RE = re.compile(
    r"\b(?:show|check|get|view|inspect|read)\b(?:(?!\b(?:and then|then|next|after that|afterwards|finally)\b).){0,120}\bstatus\b|\bstatus\b(?:(?!\b(?:and then|then|next|after that|afterwards|finally)\b).){0,120}\b(?:machine|equipment|asset|cnc|line|station|unit)\b",
    re.IGNORECASE | re.DOTALL,
)
_LIVE_STATE_REQUEST_RE = re.compile(
    r"\b(?:status|state|condition|health|running|idle|available|availability|oee|currently|current)\b",
    re.IGNORECASE,
)
_DETAILS_REQUEST_RE = re.compile(
    r"\b(?:details?|full|complete|technical|raw|all\s+fields?|every\s+field)\b",
    re.IGNORECASE,
)
_DOCUMENT_PROCEDURE_HINT_RE = re.compile(
    r"\b(?:procedure|procedures|sop|steps?|instructions?|guidance|standard|policy|manual|source|appl(?:y|ies)|before\s+(?:working|servicing|maintenance|cleaning|touching)|working\s+on|service|servicing|maintenance)\b",
    re.IGNORECASE,
)
_SAFETY_POLICY_HINT_RE = re.compile(
    r"\b(?:safety|ppe|osha|regulation|standard|policy|hazard(?:ous)?|permit|compliance|control\s+of\s+hazardous\s+energy)\b",
    re.IGNORECASE,
)
_LOTO_GENERAL_POLICY_RE = re.compile(
    r"\b(?:purpose|meaning|definition|define[sd]?|according\s+to|osha|regulation|standard|overview|general\s+guidance)\b",
    re.IGNORECASE,
)
_DOCUMENT_CONTENT_QUESTION_RE = re.compile(
    r"\b(?:according\s+to|what\s+(?:does|do|is|are)|who\s+(?:needs?|must|should)\s+(?:be\s+)?(?:to\s+)?|"
    r"when\s+(?:do|does|should|must|is|are)|how\s+(?:do|does|should|must)|why\s+|"
    r"say(?:s)?\s+about|requires?|required|requirements?|notification|notify|notifying|notified|"
    r"affected\s+employees?|purpose|meaning|definition|overview|summari[sz]e|describe|explain)\b",
    re.IGNORECASE,
)
_PROCEDURE_SELECTION_HINT_RE = re.compile(
    r"\b(?:which|what)\s+(?:[\w/()-]+\s+){0,8}?(?:procedure|procedures|sop|steps?|instructions?)\s+"
    r"(?:appl(?:y|ies)|should\s+i\s+follow|do\s+i\s+need|is\s+required|to\s+use)\b|"
    r"\b(?:procedure|procedures|sop|steps?|instructions?)\s+"
    r"(?:for|to\s+use|before\s+(?:working|servicing|service|maintenance|touching))\b",
    re.IGNORECASE,
)
_MACHINE_SPECIFIC_PROCEDURE_CONTEXT_RE = re.compile(
    r"\b(?:machine|equipment|asset|cnc|spindle|enclosure)\b|"
    r"\bworking\s+on\b|"
    r"\bbefore\s+(?:working|servicing|service|maintenance|touching)\b",
    re.IGNORECASE,
)
_LINE_REF_RE = re.compile(r"\bline\s+([A-Z0-9-]+|\d+)\b", re.IGNORECASE)
_PRIORITY_WORD_RE = re.compile(r"\b(low|medium|high|urgent)[\s-]+(?:priority\b|jobs?\b)|\bpriority\s+(?:is\s+|=|to\s+|as\s+)?(low|medium|high|urgent)\b", re.IGNORECASE)
_PRIORITY_TO_RE = re.compile(r"\bpriority\s+(?:to|as|=|is)\s+(low|medium|high|urgent)\b", re.IGNORECASE)
_JOB_PRIORITY_CHANGE_RE = re.compile(
    r"\b(?:change|set|update|mark|make)\b(?:(?!\b(?:and then|then|next|after that|afterwards|finally)\b).){0,160}?"
    r"\b(low|medium|high|urgent)[\s-]+(?:priority[\s-]+)?jobs?\b"
    r"(?:(?!\b(?:and then|then|next|after that|afterwards|finally)\b).){0,160}?"
    r"\b(?:to|into|as)\s+(low|medium|high|urgent)\b",
    re.IGNORECASE | re.DOTALL,
)
_JOB_UPDATE_MUTATION_RE = re.compile(
    r"\b(?:update|set|change|assign|record|apply|reschedule|move)\b",
    re.IGNORECASE,
)
_JOB_STATUS_WORD_RE = re.compile(r"\b(delayed|overdue|late|planned|ready|running|active|completed|cancelled)\b", re.IGNORECASE)
_APPROVAL_ACTION_RE = re.compile(
    r"\b(?:approve|reject|decline|show|list|view|get|check)\b(?:(?!\b(?:and then|then|next|after that|afterwards|finally)\b).){0,80}\b(?:approval|approvals|request|requests)\b|\bpending\s+approvals?\b",
    re.IGNORECASE | re.DOTALL,
)
_CANCEL_RUN_RE = re.compile(
    r"^\s*(?:stop\b.*|cancel(?:\s+(?:the\s+)?(?:current\s+)?(?:run|request|session|operation|job|it|this))?\b.*|don't\s+do\s+this\b.*|do\s+not\s+do\s+this\b.*)$",
    re.IGNORECASE,
)
_DANGEROUS_UNSUPPORTED_RE = re.compile(
    r"\b(?:delete|remove|purge|drop|wipe|destroy)\b(?:(?!\b(?:and then|then|next|after that|afterwards|finally)\b).){0,120}\b(?:all\s+(?:production\s+)?jobs?|production\s+jobs?)\b|"
    r"\b(?:bypass|without|skip)\s+approvals?\b|"
    r"\bapply\b(?:(?!\b(?:and then|then|next|after that|afterwards|finally)\b).){0,80}\bdirectly\b",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class IntentAssessment:
    kind: IntentKind
    action: IntentAction
    entity: str | None
    confidence: float
    reply: str | None = None


@dataclass(frozen=True)
class SemanticFrame:
    domain_intent: str | None
    action: str | None
    entity: str | None
    entities: dict[str, Any]
    normalized_entities: dict[str, list[str]]
    missing_required_entities: list[str]
    route: SemanticRoute
    confidence: float
    question_type: QuestionType | None = None
    clarification_reason: str | None = None
    negative_route_assertions: list[str] | None = None
    requires_approval: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["negative_route_assertions"] = list(self.negative_route_assertions or [])
        return payload


def _intent_id(idx: int) -> str:
    return f"intent-{idx:03d}"


def _stable_intent_id(idx: int, clause: str) -> str:
    digest = sha1(clause.strip().lower().encode("utf-8")).hexdigest()[:8]
    return f"{_intent_id(idx)}-{digest}"


def _split_clauses(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    hard_parts = [p.strip(" \t,;") for p in _CLAUSE_SPLIT_RE.split(raw) if p and p.strip(" \t,;")]
    parts = [
        part
        for hard_part in hard_parts
        for part in _split_plain_and_clauses(hard_part)
        if part
    ]
    if not parts:
        return [raw]
    merged: list[str] = []
    for part in parts:
        if merged and _is_entity_id_continuation_clause(part):
            merged[-1] = f"{merged[-1]} and {part}"
        else:
            merged.append(part)
    return merged


def _split_plain_and_clauses(clause: str) -> list[str]:
    text = (clause or "").strip(" \t,;")
    if not text or not _PLAIN_AND_RE.search(text):
        return [text] if text else []
    if _blocks_plain_and_split(text):
        return [text]

    for match in _PLAIN_AND_RE.finditer(text):
        left = text[: match.start()].strip(" \t,;")
        right = text[match.end() :].strip(" \t,;")
        if not left or not right:
            continue
        if _should_split_plain_and(left, right):
            return [
                *_split_plain_and_clauses(left),
                *_split_plain_and_clauses(right),
            ]
    return [text]


def _blocks_plain_and_split(clause: str) -> bool:
    if not _RELATIONSHIP_COMPARISON_RE.search(clause):
        return False
    if _ANSWER_INSTRUCTION_START_RE.match(clause):
        return False
    return True


def _should_split_plain_and(left: str, right: str) -> bool:
    if _blocks_plain_and_split(left) or _blocks_plain_and_split(right):
        return False
    if _is_bare_concept_continuation_clause(right):
        return False
    return _clause_side_looks_executable(left) and _clause_side_looks_executable(right)


def _clause_side_looks_executable(clause: str) -> bool:
    text = (clause or "").strip(" \t,;.?!")
    if not text:
        return False
    if _ANSWER_INSTRUCTION_START_RE.match(text):
        return True
    if _APPROVAL_MODIFIER_RE.match(text):
        return True
    action_names = {name for name, pattern in _ACTION_PATTERNS if pattern.search(text)}
    if not action_names:
        return False
    if action_names & {"create", "update", "delete", "approval"}:
        return True
    return bool(
        _ROUTABLE_OBJECT_HINT_RE.search(text)
        or _MACHINE_ID_RE.search(text)
        or _BARE_JOB_ID_RE.search(text)
        or _JOB_TOKEN_RE.search(text)
        or _MATERIAL_REF_RE.search(text)
        or _PRODUCT_RE.search(text)
    )


def _is_bare_concept_continuation_clause(clause: str) -> bool:
    text = (clause or "").strip(" \t,;.?!")
    if not text:
        return True
    if _ANSWER_INSTRUCTION_START_RE.match(text) or _APPROVAL_MODIFIER_RE.match(text):
        return False
    if any(pattern.search(text) for _name, pattern in _ACTION_PATTERNS):
        return False
    if re.search(r"\b(?:for|with|if|when|where|sorted|limit|only|fields?)\b", text, re.IGNORECASE):
        return False
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", text)
    return 1 <= len(words) <= 6


def _is_entity_id_continuation_clause(clause: str) -> bool:
    text = (clause or "").strip(" \t,;.?!")
    if not text:
        return False
    if any(pattern.search(text) for _name, pattern in _ACTION_PATTERNS):
        return False
    stripped = _BARE_JOB_ID_RE.sub(" ", text)
    stripped = _MATERIAL_REF_RE.sub(" ", stripped)
    stripped = _PRODUCT_RE.sub(" ", stripped)
    stripped = _MACHINE_ID_RE.sub(" ", stripped)
    stripped = re.sub(r"\b(?:and|or|with|id|ids|job|jobs|machine|machines|product|material)\b", " ", stripped, flags=re.I)
    stripped = re.sub(r"[\s,;#.!?-]+", "", stripped)
    return not stripped


def _constraint_strength(clause: str, match: re.Match[str]) -> Literal["hard", "soft"]:
    prefix = clause[max(0, match.start() - 32) : match.start()]
    return "soft" if _SOFT_CONSTRAINT_HINT_RE.search(prefix) else "hard"


def _date_operator(token: str) -> Literal["=", "before", "after"]:
    op = token.lower()
    if op in {"by", "before", "until"}:
        return "before"
    if op in {"after", "from"}:
        return "after"
    return "="


def _compound_m_machine_spans(clause: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _COMPOUND_M_MACHINE_RE.finditer(clause)]


def _machine_id_is_inner_fragment_of_compound(
    _clause: str, m: re.Match[str], compound_spans: list[tuple[int, int]]
) -> bool:
    start, end = m.start(), m.end()
    for fs, fe in compound_spans:
        if fs < start and end <= fe and (start, end) != (fs, fe):
            return True
    return False


def _machine_id_is_inner_fragment_of_hyphenated_token(clause: str, m: re.Match[str]) -> bool:
    start, end = m.start(), m.end()
    return (start > 0 and clause[start - 1] == "-") or (end < len(clause) and clause[end] == "-")


def _token_looks_like_machine_code(token: str) -> bool:
    """M1 hybrid: allow M-… codes without digits (e.g. M-CNC); otherwise require a digit."""
    t = token.strip()
    if not t:
        return False
    if re.match(r"^M-", t, re.IGNORECASE):
        return True
    return bool(re.search(r"\d", t))


def _extract_constraints(clause: str) -> list[ExplicitConstraint]:
    out: list[ExplicitConstraint] = []
    compound_spans = _compound_m_machine_spans(clause)
    for m in _MATERIAL_REF_RE.finditer(clause):
        cap = m.group(1).upper()
        out.append(
            ExplicitConstraint(
                field="material_id",
                operator="=",
                value=cap,
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _MACHINE_ID_RE.finditer(clause):
        local_prefix = clause[max(0, m.start() - 48) : m.start()].lower()
        if re.search(r"\b(?:job|product|operator|op|material)\s*(?:id|#)?\s*$", local_prefix):
            continue
        if _machine_id_is_inner_fragment_of_hyphenated_token(clause, m):
            continue
        if _machine_id_is_inner_fragment_of_compound(clause, m, compound_spans):
            continue
        out.append(
            ExplicitConstraint(
                field="machine_id",
                operator="=",
                value=m.group(1).upper(),
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _USE_MACHINE_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="machine_id",
                operator="=",
                value=m.group(1).upper(),
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _MACHINE_NAME_RE.finditer(clause):
        token = m.group(1)
        if not _token_looks_like_machine_code(token):
            continue
        out.append(
            ExplicitConstraint(
                field="machine_ref",
                operator="=",
                value=token,
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _JOB_TOKEN_RE.finditer(clause):
        raw_val = str(m.group(1)).upper() if m.group(1) else m.group(0)
        if re.match(r"^P-\d+$", raw_val) and _JOB_CREATE_RE.search(clause):
            left = clause[max(0, m.start() - 48) : m.start()].lower()
            if "product" not in left:
                out.append(
                    ExplicitConstraint(
                        field="product_id",
                        operator="=",
                        value=raw_val,
                        source_text=m.group(0),
                        strength=_constraint_strength(clause, m),
                        mutable=False,
                    )
                )
                continue
        out.append(
            ExplicitConstraint(
                field="job_id",
                operator="=",
                value=raw_val,
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    existing_job_ids = {str(c.value).strip().upper() for c in out if c.field == "job_id"}
    for m in _BARE_JOB_ID_RE.finditer(clause):
        raw_val = str(m.group(1)).upper()
        if raw_val in existing_job_ids:
            continue
        out.append(
            ExplicitConstraint(
                field="job_id",
                operator="=",
                value=raw_val,
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _PRODUCT_RE.finditer(clause):
        cap = m.group(1).upper()
        if cap in _UNBOUND_REFERENT_ID_TOKENS:
            continue
        if cap in {"TYPE", "TYPES"} and re.search(r"\bproduct\s+types?\b", clause, re.IGNORECASE):
            continue
        out.append(
            ExplicitConstraint(
                field="product_id",
                operator="=",
                value=cap,
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _DATE_WITH_PREPOSITION_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="date",
                operator=_date_operator(m.group("op")),
                value=m.group("value"),
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _NATURAL_DATE_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="date",
                operator="=",
                value=m.group(1).lower(),
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    for m in _OPERATOR_RE.finditer(clause):
        out.append(
            ExplicitConstraint(
                field="operator",
                operator="=",
                value=m.group("value").strip(),
                source_text=m.group(0),
                strength=_constraint_strength(clause, m),
                mutable=False,
            )
        )
    machine_ids = {str(c.value).strip().upper() for c in out if c.field == "machine_id"}
    out = [
        c
        for c in out
        if not (c.field == "machine_ref" and str(c.value).strip().upper() in machine_ids)
    ]
    # De-dupe identical field+value
    seen: set[tuple[str, str]] = set()
    deduped: list[ExplicitConstraint] = []
    for c in out:
        key = (c.field, json.dumps(c.value, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


def _classify_clause(clause: str) -> IntentCategory:
    if not clause.strip():
        return "unknown"
    if _REPORT_HINT.search(clause):
        return "reporting"
    if _SCHEDULING_HINT.search(clause) or _JOB_HINT.search(clause):
        if _SCHEDULING_HINT.search(clause):
            return "scheduling"
        if re.search(r"\b(?:create|new|add|schedule|assign)\b", clause, re.I):
            return "scheduling"
        return "job"
    if _INVENTORY_HINT.search(clause):
        return "inventory"
    if _MACHINE_HINT.search(clause):
        return "machine"
    if _QUESTION_RE.search(clause) and not _JOB_HINT.search(clause) and not _MACHINE_HINT.search(clause):
        return "general"
    return "unknown"


def _infer_depends_on(intents: list[Intent]) -> list[Intent]:
    """Order-based heuristic: scheduling/job actions may depend on prior discovery intents."""
    out: list[Intent] = []
    for i, it in enumerate(intents):
        deps = list(it.depends_on)
        if i > 0 and it.category in ("scheduling", "job"):
            prev = intents[i - 1]
            prev_desc = prev.description.lower()
            if prev.category in ("machine", "inventory") and any(
                w in prev_desc for w in ("find", "list", "show", "available", "lookup", "search")
            ):
                if prev.intent_id not in deps:
                    deps.append(prev.intent_id)
        out.append(it.model_copy(update={"depends_on": deps}))
    return out


def split_user_intents(query: str, *, llm: Any | None = None) -> list[Intent]:
    """
    Dumb intent splitter (Phase 2): extracts structured intents without tool execution
    or completeness checks. Rule-based by default; optional LLM JSON path when ``llm`` is set.
    """
    del llm  # Reserved for Phase 2+ LLM-backed split; wire in planner settings when ready.
    raw = (query or "").strip()
    if not raw:
        return [
            Intent(
                intent_id=_intent_id(0),
                description="(empty user request)",
                category="unknown",
            )
        ]

    clauses = _split_clauses(raw)
    intents: list[Intent] = []
    for idx, clause in enumerate(clauses):
        if not clause:
            continue
        cat = _classify_clause(clause)
        intents.append(
            Intent(
                intent_id=_stable_intent_id(idx, clause),
                description=clause.strip(),
                explicit_constraints=_extract_constraints(clause),
                category=cat,
            )
        )

    if not intents:
        return [
            Intent(
                intent_id=_stable_intent_id(0, raw),
                description=raw,
                explicit_constraints=_extract_constraints(raw),
                category=_classify_clause(raw),
            )
        ]

    return _infer_depends_on(intents)


def intent_constraint_values(text: str, field: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for intent in split_user_intents(text):
        for constraint in intent.explicit_constraints:
            if constraint.field != field:
                continue
            value = str(constraint.value or "").strip().upper()
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(value)
    return values


def _normalized_constraint_entities(intents: Sequence[Intent]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}

    def add(field: str, value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        if field.endswith("_id") or field in {"machine_ref", "line_id"}:
            text = text.upper()
        elif field in {"priority", "from_priority", "to_priority", "status", "topic"}:
            text = text.lower()
        values = normalized.setdefault(field, [])
        if text not in values:
            values.append(text)

    for intent in intents:
        for constraint in intent.explicit_constraints:
            add(constraint.field, constraint.value)
    return normalized


def _add_regex_entities(raw: str, normalized: dict[str, list[str]]) -> None:
    def add(field: str, value: str) -> None:
        text = value.strip()
        if not text:
            return
        if field == "line_id":
            text = text.upper()
            if text.isdigit():
                text = f"LINE-{text}"
            elif not text.startswith("LINE-"):
                text = f"LINE-{text}"
        elif field in {"priority", "from_priority", "to_priority", "status", "topic"}:
            text = text.lower()
        values = normalized.setdefault(field, [])
        if text not in values:
            values.append(text)

    for match in _LINE_REF_RE.finditer(raw):
        add("line_id", match.group(1))
    for match in _PRIORITY_WORD_RE.finditer(raw):
        add("priority", match.group(1) or match.group(2) or "")
    for match in _PRIORITY_TO_RE.finditer(raw):
        add("to_priority", match.group(1))
    for match in _JOB_PRIORITY_CHANGE_RE.finditer(raw):
        add("from_priority", match.group(1))
        add("to_priority", match.group(2))
    for match in _JOB_STATUS_WORD_RE.finditer(raw):
        add("status", match.group(1))
    if re.search(r"\bppe\b", raw, re.IGNORECASE):
        add("topic", "ppe")
    if is_loto_query(raw):
        add("topic", "loto")


def _entities_payload(normalized: dict[str, list[str]]) -> dict[str, Any]:
    return {
        field: values[0] if len(values) == 1 else list(values)
        for field, values in normalized.items()
        if values
    }


def _semantic_action_entity(raw: str, intents: Sequence[Intent], normalized: dict[str, list[str]]) -> tuple[str | None, str | None]:
    lowered = raw.lower()
    matched_actions: set[str] = {c for c, p in _ACTION_PATTERNS if p.search(raw)}
    action: str | None = None
    if _CANCEL_RUN_RE.match(raw):
        action = "cancel"
    elif _DANGEROUS_UNSUPPORTED_RE.search(raw) and re.search(r"\b(?:delete|remove|purge|drop|wipe|destroy)\b", raw, re.I):
        action = "delete"
    elif _JOB_PRIORITY_CHANGE_RE.search(raw):
        action = "update"
    elif matched_actions:
        if {"create", "update", "delete"} & matched_actions:
            if matched_actions == {"update", "read"} and not _JOB_UPDATE_MUTATION_RE.search(raw):
                action = "read"
            else:
                for candidate in ("create", "update", "delete", "read"):
                    if candidate in matched_actions:
                        action = candidate
                        break
        else:
            for candidate in ("approval", "read"):
                if candidate in matched_actions:
                    action = candidate
                    break

    entity: str | None = None
    if _APPROVAL_ACTION_RE.search(raw):
        entity = "approval"
    elif _JOB_HINT.search(raw) or normalized.get("job_id"):
        entity = "job"
    elif normalized.get("machine_id") or normalized.get("machine_ref") or _MACHINE_HINT.search(raw):
        entity = "machine"
    elif re.search(r"\bproduct\b", lowered) or normalized.get("product_id"):
        entity = "product"
    elif _INVENTORY_HINT.search(raw) or normalized.get("material_id"):
        entity = "inventory"
    else:
        for intent in intents:
            if intent.category in {"machine", "job", "inventory", "reporting", "scheduling"}:
                entity = "job" if intent.category == "scheduling" else intent.category
                break
    return action, entity


def _first_machine_id_from_previous(previous_texts: Sequence[str] | None) -> str | None:
    for previous in previous_texts or []:
        machine_ids = intent_constraint_values(previous or "", "machine_id")
        if machine_ids:
            return machine_ids[0]
    return None


def _is_live_operational_status_question(
    raw: str,
    *,
    entity: str | None,
    normalized: dict[str, list[str]],
) -> bool:
    return bool(
        _LIVE_STATE_REQUEST_RE.search(raw)
        and (
            entity == "machine"
            or normalized.get("machine_id")
            or normalized.get("machine_ref")
            or _MACHINE_HINT.search(raw)
        )
    )


def _is_document_content_question(raw: str) -> bool:
    if _LIVE_STATE_REQUEST_RE.search(raw) and not _DOCUMENT_PROCEDURE_HINT_RE.search(raw):
        return False
    if is_loto_query(raw) and _DOCUMENT_CONTENT_QUESTION_RE.search(raw):
        return True
    return bool(
        _DOCUMENT_PROCEDURE_HINT_RE.search(raw)
        and _QUESTION_RE.search(raw)
        and _DOCUMENT_CONTENT_QUESTION_RE.search(raw)
    )


def _is_machine_specific_procedure_selection(
    raw: str,
    *,
    normalized: dict[str, list[str]],
) -> bool:
    if _STATUS_MACHINE_REQUEST_RE.search(raw) and not _LOTO_PROCEDURE_CONTEXT_RE.search(raw):
        return False
    if not (_PROCEDURE_SELECTION_HINT_RE.search(raw) or (is_loto_query(raw) and normalized.get("machine_id"))):
        return False
    return bool(
        normalized.get("machine_id")
        or normalized.get("machine_ref")
        or _CONTEXTUAL_MACHINE_REF_RE.search(raw)
        or _MACHINE_SPECIFIC_PROCEDURE_CONTEXT_RE.search(raw)
    )


def _question_type_for_text(
    raw: str,
    *,
    entity: str | None,
    normalized: dict[str, list[str]],
) -> QuestionType | None:
    if _is_machine_specific_procedure_selection(raw, normalized=normalized):
        return "machine_specific_procedure_selection"
    if _is_live_operational_status_question(raw, entity=entity, normalized=normalized):
        return "live_operational_status"
    if _is_safety_policy_request(raw):
        return "safety_policy_question"
    if _is_document_content_question(raw) or _is_document_procedure_request(raw):
        return "document_content_question"
    return None


def _is_document_procedure_request(raw: str) -> bool:
    if _LIVE_STATE_REQUEST_RE.search(raw) and not _DOCUMENT_PROCEDURE_HINT_RE.search(raw):
        return False
    return bool(_DOCUMENT_PROCEDURE_HINT_RE.search(raw) and _QUESTION_RE.search(raw))


def _is_safety_policy_request(raw: str) -> bool:
    return bool(_SAFETY_POLICY_HINT_RE.search(raw) and (_QUESTION_RE.search(raw) or _DOCUMENT_PROCEDURE_HINT_RE.search(raw)))


def _is_job_mutation_request(raw: str, action: str | None) -> bool:
    if not _JOB_HINT.search(raw):
        return False
    if _DANGEROUS_UNSUPPORTED_RE.search(raw):
        return False
    if action in {"create", "delete"}:
        return True
    if action == "update":
        return bool(_JOB_UPDATE_MUTATION_RE.search(raw) or _JOB_PRIORITY_CHANGE_RE.search(raw))
    return bool(_JOB_PRIORITY_CHANGE_RE.search(raw))


def _job_mutation_missing_entities(normalized: dict[str, list[str]], *, action: str | None) -> list[str]:
    if action == "create":
        return [] if (normalized.get("product_id") or normalized.get("material_id")) else ["job_spec"]
    if action == "delete":
        return [] if (normalized.get("job_id") or normalized.get("from_priority") or normalized.get("status")) else ["job_filter"]
    missing: list[str] = []
    if not (normalized.get("job_id") or normalized.get("from_priority") or normalized.get("status")):
        missing.append("job_filter")
    if not (normalized.get("to_priority") or normalized.get("product_id")):
        missing.append("mutation_value")
    return missing


def semantic_frame_for_text(text: str, *, previous_texts: Sequence[str] | None = None) -> SemanticFrame:
    raw = (text or "").strip()
    if not raw:
        return SemanticFrame(
            domain_intent=None,
            action=None,
            entity=None,
            entities={},
            normalized_entities={},
            missing_required_entities=[],
            route="unknown",
            confidence=0.0,
            clarification_reason=None,
            negative_route_assertions=[],
        )

    intents = split_user_intents(raw)
    normalized = _normalized_constraint_entities(intents)
    _add_regex_entities(raw, normalized)
    action, entity = _semantic_action_entity(raw, intents, normalized)
    entities = _entities_payload(normalized)
    question_type = _question_type_for_text(raw, entity=entity, normalized=normalized)

    if _DANGEROUS_UNSUPPORTED_RE.search(raw) and (
        re.search(r"\b(?:delete|remove|purge|drop|wipe|destroy)\b", raw, re.I)
        or re.search(r"\b(?:bypass|without|skip)\s+approvals?\b", raw, re.I)
    ):
        return SemanticFrame(
            domain_intent="unsupported_dangerous_action",
            action=action or "delete",
            entity="job" if _JOB_HINT.search(raw) else entity,
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="unsupported_dangerous_action",
            confidence=0.97,
            clarification_reason=None,
            negative_route_assertions=["tool.write.production_jobs.delete", "approval_bypass", "fake_success"],
            requires_approval=False,
        )

    if _CANCEL_RUN_RE.match(raw):
        return SemanticFrame(
            domain_intent="cancel_run",
            action="cancel",
            entity="session",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="cancel_run",
            confidence=0.95,
            clarification_reason=None,
            negative_route_assertions=["tool.write.jobs", "rag.procedure"],
        )

    if _APPROVAL_ACTION_RE.search(raw):
        return SemanticFrame(
            domain_intent="approval_action",
            action="approval",
            entity="approval",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="approval_action",
            confidence=0.9,
            clarification_reason=None,
            negative_route_assertions=["tool.write.jobs", "approval_bypass"],
        )

    machine_ids = normalized.get("machine_id") or []
    if question_type == "machine_specific_procedure_selection":
        contextual_machine = None
        if not machine_ids and _CONTEXTUAL_MACHINE_REF_RE.search(raw):
            contextual_machine = _first_machine_id_from_previous(previous_texts)
            if contextual_machine:
                normalized["machine_id"] = [contextual_machine]
                entities = _entities_payload(normalized)
                machine_ids = [contextual_machine]
        if not machine_ids:
            domain_intent = "loto_procedure" if is_loto_query(raw) else "document_procedure"
            return SemanticFrame(
                domain_intent=domain_intent,
                action="read",
                entity="machine",
                entities=entities,
                normalized_entities=normalized,
                missing_required_entities=["machine_id"],
                route="clarification.machine_id_missing",
                confidence=0.88,
                question_type=question_type,
                clarification_reason="machine_id is required for a machine-specific procedure selection",
                negative_route_assertions=["rag.loto_procedure", "rag.procedure", "tool.read.machine_status"],
            )
        route: SemanticRoute = "rag.loto_procedure" if is_loto_query(raw) else "rag.procedure"
        return SemanticFrame(
            domain_intent="loto_procedure" if is_loto_query(raw) else "document_procedure",
            action="read",
            entity="machine",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route=route,
            confidence=0.93 if contextual_machine is None else 0.9,
            question_type=question_type,
            clarification_reason=None,
            negative_route_assertions=["tool.read.machine_status"],
        )

    if question_type == "live_operational_status":
        if not machine_ids and not normalized.get("machine_ref"):
            return SemanticFrame(
                domain_intent="machine_status",
                action="read",
                entity="machine",
                entities=entities,
                normalized_entities=normalized,
                missing_required_entities=["machine_id"],
                route="clarification.machine_id_missing",
                confidence=0.82,
                question_type=question_type,
                clarification_reason="machine_id is required for live machine status",
                negative_route_assertions=["tool.read.machine_status", "rag.loto_procedure"],
            )
        return SemanticFrame(
            domain_intent="machine_status",
            action="read",
            entity="machine",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="tool.read.machine_status",
            confidence=0.91,
            question_type=question_type,
            clarification_reason=None,
            negative_route_assertions=["rag.loto_procedure", "rag.procedure", "rag.safety_policy"],
        )

    if entity == "machine" and action in {None, "read"} and _DETAILS_REQUEST_RE.search(raw):
        if not machine_ids and not normalized.get("machine_ref"):
            return SemanticFrame(
                domain_intent="machine_query",
                action="read",
                entity="machine",
                entities=entities,
                normalized_entities=normalized,
                missing_required_entities=["machine_id"],
                route="clarification.machine_id_missing",
                confidence=0.8,
                question_type=None,
                clarification_reason="machine_id is required for machine details",
                negative_route_assertions=["rag.loto_procedure", "rag.procedure"],
            )
        return SemanticFrame(
            domain_intent="machine_query",
            action="read",
            entity="machine",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="tool.read.machine_status",
            confidence=0.86,
            question_type=None,
            clarification_reason=None,
            negative_route_assertions=["rag.loto_procedure", "rag.procedure", "rag.safety_policy"],
        )

    if question_type == "safety_policy_question":
        return SemanticFrame(
            domain_intent="safety_policy",
            action="read",
            entity=None if is_loto_query(raw) else entity,
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="rag.safety_policy",
            confidence=0.84,
            question_type=question_type,
            clarification_reason=None,
            negative_route_assertions=["tool.read.machine_status"] if is_loto_query(raw) else ["tool.write.jobs"],
        )

    if question_type == "document_content_question":
        return SemanticFrame(
            domain_intent="document_procedure",
            action="read",
            entity=entity,
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="rag.procedure",
            confidence=0.82,
            question_type=question_type,
            clarification_reason=None,
            negative_route_assertions=["tool.read.machine_status"],
        )

    if _RESCHEDULE_ALL_JOBS_RE.search(raw):
        return SemanticFrame(
            domain_intent="job_reschedule_all",
            action="update",
            entity="job",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="tool.write.scheduling_reschedule_all",
            confidence=0.93,
            clarification_reason=None,
            negative_route_assertions=["tool.read.jobs_only", "approval_bypass"],
            requires_approval=True,
        )

    if _is_job_mutation_request(raw, action):
        missing = _job_mutation_missing_entities(normalized, action=action)
        return SemanticFrame(
            domain_intent="job_mutation",
            action=action or "update",
            entity="job",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=missing,
            route="clarification.job_mutation_incomplete" if missing else "tool.write.jobs",
            confidence=0.86 if missing else 0.91,
            clarification_reason="job mutation requires a target/filter and a new value" if missing else None,
            negative_route_assertions=["tool.read.jobs_only", "approval_bypass"],
            requires_approval=not missing,
        )

    if entity == "job" and (action in {None, "read"} or _JOB_HINT.search(raw)):
        return SemanticFrame(
            domain_intent="job_query",
            action="read",
            entity="job",
            entities=entities,
            normalized_entities=normalized,
            missing_required_entities=[],
            route="tool.read.jobs",
            confidence=0.89,
            clarification_reason=None,
            negative_route_assertions=["tool.write.jobs"],
        )

    return SemanticFrame(
        domain_intent=None,
        action=action,
        entity=entity,
        entities=entities,
        normalized_entities=normalized,
        missing_required_entities=[],
        route="unknown",
        confidence=0.55 if action or entity else 0.35,
        clarification_reason=None,
        negative_route_assertions=[],
    )


def is_loto_query(text: str) -> bool:
    return bool(_LOTO_HINT_RE.search(text or ""))


def should_clarify_loto_machine(text: str) -> bool:
    frame = semantic_frame_for_text(text)
    return frame.domain_intent == "loto_procedure" and "machine_id" in frame.missing_required_entities


def should_route_loto_to_rag(text: str) -> bool:
    frame = semantic_frame_for_text(text)
    return is_loto_query(text) and frame.route in {"rag.loto_procedure", "rag.procedure", "rag.safety_policy"}


def resolve_contextual_loto_machine_id(text: str, previous_texts: Sequence[str]) -> str | None:
    raw = text or ""
    if not should_clarify_loto_machine(raw) or not _CONTEXTUAL_MACHINE_REF_RE.search(raw):
        return None
    return _first_machine_id_from_previous(previous_texts)


def loto_query_with_resolved_machine_context(text: str, machine_id: str | None) -> str:
    raw = text or ""
    normalized_machine_id = (machine_id or "").strip().upper()
    if not normalized_machine_id:
        return raw
    return f"{raw.rstrip()} (resolved context from the immediately previous turn: machine {normalized_machine_id})"


def rag_query_with_required_machine_context(
    query: str,
    *,
    intent: str,
    semantic_frame: SemanticFrame | None = None,
) -> str:
    frame_entities = getattr(semantic_frame, "normalized_entities", None)
    machine_ids: list[str] = []
    if isinstance(frame_entities, dict):
        raw_values = frame_entities.get("machine_id") or []
        if isinstance(raw_values, str):
            raw_values = [raw_values]
        machine_ids = [str(value).strip().upper() for value in raw_values if str(value or "").strip()]
    if not machine_ids:
        machine_ids = intent_constraint_values(intent, "machine_id")
    if not machine_ids:
        return query
    query_text = str(query or intent or "")
    upper_query = query_text.upper()
    if any(machine_id in upper_query for machine_id in machine_ids):
        return query_text
    return (
        f"{query_text.rstrip()}\n\n"
        f"Required machine context from the routed request: machine {machine_ids[0]}."
    )


def assess_intent(text: str) -> IntentAssessment:
    """
    Legacy API for tool scoping and API gating. Delegates to :func:`split_user_intents`
    instead of standalone regex classification (Phase 2).
    """
    raw = (text or "").strip()
    lower = raw.lower()
    if not raw:
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.99,
            reply="Hi - tell me what factory operations request you want to run, and I will map it to the available tools.",
        )

    if _GREETING_RE.search(raw):
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.98,
            reply="Hi - tell me what factory operations request you want to run, and I will map it to the available tools.",
        )

    if _CANCEL_RUN_RE.match(raw):
        return IntentAssessment(kind="operations", action="update", entity=None, confidence=0.93, reply=None)

    intents = split_user_intents(raw)
    has_action_hint = any(p.search(raw) for _, p in _ACTION_PATTERNS)
    if (
        len(intents) == 1
        and intents[0].category == "unknown"
        and len(lower.split()) <= 3
        and not _QUESTION_RE.search(raw)
        and not has_action_hint
    ):
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.7,
            reply="Tell me the factory operations request you want to run, including the resource and any identifier or filter.",
        )

    matched_actions: set[str] = {c for c, p in _ACTION_PATTERNS if p.search(raw)}
    action: IntentAction = None
    if matched_actions:
        if {"create", "update", "delete"} & matched_actions:
            for candidate in ("create", "update", "delete", "read"):
                if candidate in matched_actions:
                    action = candidate  # type: ignore[assignment]
                    break
        else:
            for candidate in ("approval", "read"):
                if candidate in matched_actions:
                    action = candidate  # type: ignore[assignment]
                    break

    entity: str | None = None
    lower_raw = raw.lower()
    if _JOB_HINT.search(raw):
        entity = "job"
    elif re.search(r"\bproduct\b", lower_raw):
        entity = "product"
    elif _MACHINE_HINT.search(raw):
        entity = "machine"
    elif _INVENTORY_HINT.search(raw):
        entity = "inventory"
    else:
        for it in intents:
            for c in it.explicit_constraints:
                if c.field == "job_id":
                    entity = "job"
                    break
                if c.field == "product_id":
                    entity = "product"
                    break
                if c.field in ("machine_id", "machine_ref"):
                    entity = "machine"
                    break
            if entity:
                break

    operational_categories = {"reporting", "scheduling", "job", "inventory", "machine"}
    has_operational_category = any(it.category in operational_categories for it in intents)
    is_pure_knowledge_question = (
        bool(_QUESTION_RE.search(raw))
        and not entity
        and not has_operational_category
        and not ({"create", "update", "delete", "approval"} & matched_actions)
    )
    if is_pure_knowledge_question:
        return IntentAssessment(kind="conversation", action=action, entity=None, confidence=0.86, reply=None)

    if action or entity or _QUESTION_RE.search(raw) or any(it.category != "unknown" for it in intents):
        confidence = 0.92 if (action and entity) else 0.78
        return IntentAssessment(kind="operations", action=action, entity=entity, confidence=confidence, reply=None)

    token_count = len([tok for tok in re.split(r"\s+", lower) if tok])
    if token_count <= 4:
        return IntentAssessment(
            kind="conversation",
            action=None,
            entity=None,
            confidence=0.7,
            reply="Tell me the factory operations request you want to run, including the resource and any identifier or filter.",
        )

    return IntentAssessment(
        kind="operations",
        action=None,
        entity=entity,
        confidence=0.55,
        reply=None,
    )


def intents_to_state_payload(intents: Sequence[Intent]) -> list[dict[str, Any]]:
    """Serialize intents for ``AgentState['intents']`` (append reducer)."""
    return [i.model_dump(mode="json") for i in intents]
