import re
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from langchain_core.messages import HumanMessage, SystemMessage

@dataclass
class RouteDecision:
    route: str                          # "API_ONLY" | "RAG_ONLY" | "API_THEN_RAG" | "RAG_THEN_API" | "CLARIFY"
    route_source: str                   # "score" | "llm" | "fallback_default"
    confidence: float                   # 0.0 - 1.0
    scores: Dict[str, float]            = field(default_factory=dict)
    matched_entities: List[str]         = field(default_factory=list)
    matched_entity_types: List[str]     = field(default_factory=list)
    matched_tools: List[str]            = field(default_factory=list)
    signals: List[str]                  = field(default_factory=list)
    clarify_reason: Optional[str]       = None

class QueryRouter:
    """
    Enterprise-grade Query Router that classifies queries using a weighted 
    multi-signal scoring system based on project metadata.
    """

    # Routes
    API_ONLY = "API_ONLY"
    RAG_ONLY = "RAG_ONLY"
    API_THEN_RAG = "API_THEN_RAG"
    RAG_THEN_API = "RAG_THEN_API"
    CLARIFY = "CLARIFY"

    # Static keyword lists (fallbacks/supplemental)
    API_ACTION_VERBS = {"show", "list", "fetch", "get", "display", "create", "update", "set", "add", "change", "delete", "remove"}
    TEMPORAL_MARKERS = {"current", "today", "now", "live", "recent", "latest"}
    RAG_INTENT_VERBS = {"explain", "procedure", "steps", "definition", "standard", "policy", "guideline", "describe", "meaning", "how to"}
    DIAGNOSE_SIGNALS = {"why", "is this normal", "recommend", "troubleshoot", "fault", "error", "problem", "issue", "acceptable", "threshold"}
    SAFETY_TERMS = {"loto", "csf", "guarding", "confined", "ppe", "sop"}
    
    RAG_THEN_API_PATTERNS = [
        r"(?:based on|following|according to|per|as per)\s+(?:the\s+)?(?:[\w-]+\s+)?(?:standard|procedure|policy|guideline|sop|process|safety)",
    ]

    # Loose entity patterns for common factory terms not in id_patterns.json
    LOOSE_ENTITY_PATTERNS = [
        r"\bLine\s+\d+\b",
        r"\bStation\s+\d+\b",
        r"\bUnit\s+\d+\b",
        r"\bMachine\s+[A-Z0-9-]*\d[A-Z0-9-]*\b"
    ]

    def __init__(self, llm: Any | None = None, tool_registry: Any | None = None):
        """
        :param llm: A LangChain chat model for fallback classification.
        :param tool_registry: Optional ToolRegistry or snapshot for tool matching.
        """
        self.llm = llm
        self.tool_registry = tool_registry
        
        # Load project artifacts
        base_path = Path(__file__).resolve().parents[1]
        self.id_patterns_path = base_path / "generated" / "id_patterns.json"
        self.vocab_path = base_path / "generated" / "tool_intent_vocabulary.json"
        self.config_path = base_path / "ai_domain_config.json"
        
        self.id_patterns = self._load_json(self.id_patterns_path)
        self.vocab = self._load_json(self.vocab_path)
        self.config = self._load_json(self.config_path)
        
        # Extract dynamic signals
        self.entity_tokens = set(self.vocab.get("entity_tokens", []))
        self.weights = self.config.get("router", {}).get("weights", {})
        self.thresholds = self.config.get("router", {}).get("thresholds", {"clarify": 5, "ambiguity_margin": 3})

    def _load_json(self, path: Path) -> Dict[str, Any]:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _detect_entities(self, query: str) -> Dict[str, List[str]]:
        """Detects entity IDs (e.g. M-001) using patterns from id_patterns.json and loose patterns."""
        results = {"ids": [], "types": []}
        
        # 1. Official ID patterns
        if self.id_patterns:
            for item in self.id_patterns.get("prefixes", []):
                prefix = item.get("prefix")
                entity_type = item.get("entity")
                if not prefix or not entity_type:
                    continue
                pattern = rf"\b({re.escape(prefix)}[A-Z0-9-]+)\b"
                matches = re.findall(pattern, query, re.IGNORECASE)
                for m in matches:
                    if m.upper() not in results["ids"]:
                        results["ids"].append(m.upper())
                        if entity_type not in results["types"]:
                            results["types"].append(entity_type)
                            
        # 2. Loose patterns (Line 3, Station 5, etc.)
        for pattern in self.LOOSE_ENTITY_PATTERNS:
            matches = re.findall(pattern, query, re.IGNORECASE)
            for m in matches:
                if m not in results["ids"]:
                    results["ids"].append(m)
                    # Infer type from pattern
                    lowered = m.lower()
                    if "line" in lowered: results["types"].append("line")
                    elif "station" in lowered: results["types"].append("station")
                    elif "unit" in lowered: results["types"].append("unit")
                    elif "machine" in lowered: results["types"].append("machine")
                    
        return results

    def _get_tool_matches(self, query: str) -> List[str]:
        """Checks if any tools in the registry match the query intent."""
        if not self.tool_registry:
            return []
            
        matched_tools = []
        q = query.lower()
        
        tools = []
        if hasattr(self.tool_registry, 'tools'):
            tools = self.tool_registry.tools
        elif isinstance(self.tool_registry, list):
            tools = self.tool_registry
            
        for tool in tools:
            tool_name = getattr(tool, 'name', '').lower()
            if not tool_name: continue
            
            # High confidence: name match (e.g. "get_oee" matches query "show oee")
            core_name = tool_name.replace("get__", "").replace("post__", "").replace("put__", "").replace("patch__", "").replace("delete__", "")
            core_name = core_name.replace("_", " ")
            
            if core_name in q:
                matched_tools.append(tool_name)
                continue
                
            # Medium confidence: capability tags
            tags = []
            if hasattr(tool, 'capability_tags'):
                if isinstance(tool.capability_tags, str):
                    try:
                        tags = json.loads(tool.capability_tags)
                    except: pass
                else:
                    tags = tool.capability_tags
            
            for tag in tags:
                # Allow 3+ char tags for common factory acronyms (OEE, SOP, PPE)
                if tag.lower() in q and len(tag) >= 3 and tag.lower() not in {"get", "set", "api"}:
                    matched_tools.append(tool_name)
                    break
                    
        return matched_tools[:5]

    async def route(self, query: str) -> Dict[str, Any]:
        """
        Calculates scores for all routes and returns the best decision.
        """
        q = query.lower()
        
        # 1. Detect signals
        entities = self._detect_entities(query)
        matched_ids = entities["ids"]
        matched_types = entities["types"]
        matched_tools = self._get_tool_matches(query)
        
        has_id = len(matched_ids) > 0
        has_api_verb = any(v in q for v in self.API_ACTION_VERBS)
        has_temporal = any(t in q for t in self.TEMPORAL_MARKERS)
        has_entity_token = any(t in q for t in self.entity_tokens)
        has_rag_verb = any(v in q for v in self.RAG_INTENT_VERBS)
        has_safety_term = any(t in q for t in self.SAFETY_TERMS)
        has_diagnose = any(s in q for s in self.DIAGNOSE_SIGNALS)
        has_rag_ref = any(re.search(p, q, re.IGNORECASE) for p in self.RAG_THEN_API_PATTERNS)
        has_question = any(w in q for w in {"why", "how", "what", "where", "when"})
        
        # 2. Calculate scores
        scores = {
            self.API_ONLY: 0.0,
            self.RAG_ONLY: 0.0,
            self.API_THEN_RAG: 0.0,
            self.RAG_THEN_API: 0.0
        }
        signals = []
        w = self.weights

        # ID detection - Contextual boosting
        if has_id:
            if has_rag_ref:
                scores[self.RAG_THEN_API] += w.get("entity_id_detected", 12)
                signals.append("entity_id_detected_rag_then_api")
            elif has_diagnose or has_rag_verb or has_safety_term:
                scores[self.API_THEN_RAG] += w.get("entity_id_detected", 12)
                signals.append("entity_id_detected_api_then_rag")
            else:
                scores[self.API_ONLY] += w.get("entity_id_detected", 12)
                signals.append("entity_id_detected_api")
            
            if has_question:
                scores[self.API_THEN_RAG] += w.get("entity_id_plus_question_word", 6)
                signals.append("entity_id_plus_question_word")
            if has_rag_verb:
                scores[self.API_THEN_RAG] += w.get("entity_id_plus_rag_verb", 10)
                signals.append("entity_id_plus_rag_verb")
            if has_safety_term:
                scores[self.API_THEN_RAG] += w.get("safety_term_plus_entity_id", 8)
                signals.append("safety_term_plus_entity_id")

        # Tool Registry Match
        if matched_tools:
            is_vague = len(q.split()) <= 3 and not has_id and not has_api_verb
            if not is_vague:
                if has_rag_ref:
                    scores[self.RAG_THEN_API] += w.get("tool_registry_match", 10)
                elif has_diagnose or has_rag_verb or has_safety_term:
                    scores[self.API_THEN_RAG] += w.get("tool_registry_match", 10)
                else:
                    scores[self.API_ONLY] += w.get("tool_registry_match", 10)
                signals.append("tool_registry_match")

        if has_api_verb:
            if has_rag_ref:
                scores[self.RAG_THEN_API] += w.get("api_action_verb", 5)
            else:
                scores[self.API_ONLY] += w.get("api_action_verb", 5)
            signals.append("api_action_verb")

        if has_temporal:
            scores[self.API_ONLY] += w.get("temporal_marker", 4)
            signals.append("temporal_marker")

        if has_entity_token and not has_id:
            if has_rag_verb:
                scores[self.RAG_ONLY] += w.get("entity_token_match", 3)
            elif has_api_verb:
                scores[self.API_ONLY] += w.get("entity_token_match", 3)
            else:
                scores[self.API_ONLY] += w.get("entity_token_match", 3)
                scores[self.RAG_ONLY] += w.get("entity_token_match", 3)
            signals.append("entity_token_match")

        if has_rag_verb:
            if has_api_verb or has_id:
                scores[self.API_THEN_RAG] += w.get("rag_intent_verb", 8)
            else:
                scores[self.RAG_ONLY] += w.get("rag_intent_verb", 8)
            signals.append("rag_intent_verb")

        if has_safety_term and not has_id:
            if has_api_verb:
                scores[self.API_THEN_RAG] += w.get("safety_term", 7)
            else:
                scores[self.RAG_ONLY] += w.get("safety_term", 7)
            signals.append("safety_term")

        if has_diagnose:
            scores[self.API_THEN_RAG] += w.get("diagnose_signal", 8)
            signals.append("diagnose_signal")

        if has_api_verb and (has_rag_verb or has_safety_term):
            # Hybrid query: "Show me X and explain Y"
            scores[self.API_THEN_RAG] += 10
            signals.append("api_verb_plus_rag_signal")

        if has_rag_ref:
            if has_id or has_api_verb:
                scores[self.RAG_THEN_API] += w.get("rag_reference_then_action", 10)
                signals.append("rag_reference_then_action")
            else:
                scores[self.RAG_ONLY] += 5
                signals.append("rag_reference_only")

        # Explicit overrides
        if "check the document" in q or "look it up in system" in q:
            scores[self.RAG_ONLY] += w.get("explicit_override", 20)
            signals.append("explicit_override_rag")
        if "query the database" in q or "search the api" in q:
            scores[self.API_ONLY] += w.get("explicit_override", 20)
            signals.append("explicit_override_api")

        # 3. Decision Logic
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_route, top_score = sorted_scores[0]
        second_score = sorted_scores[1][1]
        
        decision = RouteDecision(
            route=top_route,
            route_source="score",
            confidence=min(top_score / 20.0, 1.0),
            scores=scores,
            matched_entities=matched_ids,
            matched_entity_types=matched_types,
            matched_tools=matched_tools,
            signals=signals
        )

        # 4. CLARIFY Check (Safe valve for vague queries)
        # Hybrid routes (API_THEN_RAG, RAG_THEN_API) usually require an ID or higher signal strength
        is_hybrid = top_route in {self.API_THEN_RAG, self.RAG_THEN_API}
        clarify_threshold = self.thresholds.get("clarify", 5)
        if is_hybrid:
            clarify_threshold = 10 # Stricter for hybrid
            
        if top_score < clarify_threshold and not has_id:
            # Even if it matched a tool tag, low score + no ID = clarify
            decision.route = self.CLARIFY
            decision.clarify_reason = "Query is too vague or missing specific entity IDs for hybrid routing."
            return self._to_dict(decision)

        # 5. Ambiguity Check -> LLM Fallback
        if (top_score - second_score) < self.thresholds.get("ambiguity_margin", 3):
            return await self._llm_classify(query, decision)

        return self._to_dict(decision)

    def _to_dict(self, decision: RouteDecision) -> Dict[str, Any]:
        return {
            "route": decision.route,
            "route_source": decision.route_source,
            "confidence": decision.confidence,
            "scores": decision.scores,
            "matched_entities": decision.matched_entities,
            "matched_entity_types": decision.matched_entity_types,
            "matched_tools": decision.matched_tools,
            "signals": decision.signals,
            "clarify_reason": decision.clarify_reason
        }

    async def _llm_classify(self, query: str, score_decision: RouteDecision) -> Dict[str, Any]:
        if not self.llm:
            return self._to_dict(score_decision)

        system_prompt = f"""You are a query router for an industrial maintenance system (eMAS).
Classify this query into exactly one route:

- API_ONLY: live data, metrics, or records only (e.g. "Show OEE", "List jobs")
- RAG_ONLY: explanations, procedures, standards, definitions (e.g. "What is LOTO?")
- API_THEN_RAG: live data first, then explanation/diagnosis (e.g. "OEE is 60% — why?")
- RAG_THEN_API: read procedure first, then perform API action (e.g. "Based on SOP, create job")
- CLARIFY: query is too vague or missing context (e.g. "Fix problem")

Detected Context:
- Entities: {", ".join(score_decision.matched_entities)} ({", ".join(score_decision.matched_entity_types)})
- Potential Tools: {", ".join(score_decision.matched_tools)}
- Fired Signals: {", ".join(score_decision.signals)}

Output your decision as a JSON object: {{"route": "API_ONLY", "reason": "..."}}"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = str(response.content).strip()
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            parsed = json.loads(content)
            route = parsed.get("route", score_decision.route)
            
            if route not in (self.API_ONLY, self.RAG_ONLY, self.API_THEN_RAG, self.RAG_THEN_API, self.CLARIFY):
                route = score_decision.route
                
            score_decision.route = route
            score_decision.route_source = "llm"
            score_decision.clarify_reason = parsed.get("reason")
            return self._to_dict(score_decision)
        except Exception:
            return self._to_dict(score_decision)
