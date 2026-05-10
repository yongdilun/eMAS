# eMAS RAG System — Implementation-Ready Plan

> **Version:** 1.2  
> **Scope:** Full RAG pipeline + router strategy for eMAS agent  
> **Audience:** Developer implementing from scratch

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Router: Decision Strategy](#2-router-decision-strategy)
   - [2.6 Exit Requirements — Router](#26-exit-requirements--router)
3. [Phase 1 — Document Ingestion](#3-phase-1--document-ingestion)
   - [3.7 Exit Requirements — Phase 1](#37-exit-requirements--phase-1-document-ingestion)
4. [Phase 2 — Hybrid Retrieval](#4-phase-2--hybrid-retrieval)
   - [4.6 Exit Requirements — Phase 2](#46-exit-requirements--phase-2-hybrid-retrieval)
5. [Phase 3 — Reranking](#5-phase-3--reranking)
   - [5.5 Exit Requirements — Phase 3](#55-exit-requirements--phase-3-reranking)
6. [Phase 4 — Answer Generation](#6-phase-4--answer-generation)
   - [6.5 Exit Requirements — Phase 4](#65-exit-requirements--phase-4-answer-generation)
7. [Phase 5 — Agent Integration](#7-phase-5--agent-integration)
   - [7.5 Exit Requirements — Phase 5](#75-exit-requirements--phase-5-agent-integration)
8. [Data Structures & Contracts](#8-data-structures--contracts)
9. [Configuration Reference](#9-configuration-reference)
10. [Error Handling & Fallbacks](#10-error-handling--fallbacks)
11. [Testing Checklist](#11-testing-checklist)

---

## 1. System Architecture Overview

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│              ROUTER                 │
│  Classifies intent + data needs     │
└────────┬────────────┬───────────────┘
         │            │            │
    API_ONLY    RAG_ONLY    API_THEN_RAG
         │            │            │
         ▼            ▼            ▼
    Tool Agent   RAG Pipeline   Tool Agent
                      │          then RAG
                      │
              ┌───────┴───────┐
              │  Hybrid Search │
              │ Vector + BM25  │
              └───────┬───────┘
                      │
              Score Fusion (RRF)
                      │
              LLM Reranker (top 3–4)
                      │
              Context Builder
                      │
              Answer Generator
                      │
              Answer + Sources [+ Safety Warning]
```

---

## 2. Router: Decision Strategy

This is the most critical component. A wrong routing decision wastes tokens (over-routing to RAG) or gives incomplete answers (under-routing).

### 2.1 Routing Categories

| Route | When to Use | Examples |
|---|---|---|
| `API_ONLY` | Query needs live/structured data only. No explanation or document context needed. | "What is the OEE for Line 3 today?", "List open work orders for machine M-007", "Show me LOTO status for station 4" |
| `RAG_ONLY` | Query asks for explanations, procedures, standards, definitions, or policy. No live data needed. | "What is the LOTO procedure?", "Explain OEE calculation", "What does CSF stand for in machine guarding?", "What are the steps for confined space entry?" |
| `API_THEN_RAG` | Query needs live data AND context/explanation. Answer is incomplete without both. | "OEE for Line 3 is 72% — is that acceptable?", "Show me the downtime for M-007 and explain what to check", "Machine is in fault state — what should I do?" |

### 2.2 Router Decision Logic (Detailed)

The router must evaluate **three signals** before deciding:

#### Signal A — Intent Type

| Keyword / Pattern | Intent | Notes |
|---|---|---|
| "show", "list", "get", "fetch", "what is the [metric]" | Lookup | → API |
| "explain", "what does", "how to", "procedure", "steps", "definition" | Explain | → RAG |
| "why is", "what should I do", "is this normal", "recommend" | Diagnose/Advise | → API_THEN_RAG |
| "status", "current", "live", "today", "now" | Real-time | → API |
| Compound: lookup + explain in same query | Both | → API_THEN_RAG |

#### Signal B — Entity Type

| Entity Present | Likely Route |
|---|---|
| Machine ID (M-007, Line 3) + numeric metric | API |
| Safety term (LOTO, guarding, CSF, confined space) without a machine ID | RAG |
| Machine ID + a question word ("why", "how") | API_THEN_RAG |
| Named procedure, standard, or policy | RAG |

#### Signal C — Temporal Marker

| Marker | Likely Route |
|---|---|
| "today", "current", "now", "real-time", "live" | API |
| No temporal marker in a how/what query | RAG |
| Past tense + diagnosis ("last week it failed") | API_THEN_RAG |

### 2.3 Router Decision Flowchart

```
START
  │
  ├─ Does the query need live/structured machine or operational data?
  │     YES ──────────────────────────────────────────────┐
  │     NO                                                 │
  │      │                                                 │
  │      ├─ Does it ask for explanation/procedure/policy?  │
  │      │     YES → RAG_ONLY                              │
  │      │     NO  → default RAG_ONLY (safety fallback)    │
  │                                                        │
  └──────────────────────────────────────────────────────► │
         Does the query ALSO need explanation/procedure?   │
               YES → API_THEN_RAG  ◄─────────────────────┘
               NO  → API_ONLY
```

### 2.4 Router Implementation

```python
class QueryRouter:
    """
    Classifies a user query into one of three routes.
    Uses rule-based signals first; falls back to LLM classification.
    """

    API_KEYWORDS = [
        "show", "list", "fetch", "get", "display", "current", "today",
        "now", "live", "status", "count", "total", "value", "reading"
    ]

    RAG_KEYWORDS = [
        "explain", "what is", "what does", "how to", "procedure",
        "steps", "definition", "standard", "policy", "guideline",
        "what are the", "describe", "meaning of"
    ]

    DIAGNOSE_KEYWORDS = [
        "why", "should i", "is this normal", "what should", "recommend",
        "troubleshoot", "fault", "error", "problem", "issue", "concern",
        "acceptable", "threshold", "too high", "too low"
    ]

    MACHINE_ID_PATTERN = r"\b(M-\d+|Line \d+|Station \d+|Unit \d+)\b"
    SAFETY_TERMS = {"loto", "oee", "csf", "guarding", "confined", "ppe", "sop"}

    def route(self, query: str) -> str:
        """
        Returns: "API_ONLY" | "RAG_ONLY" | "API_THEN_RAG"
        """
        q = query.lower()
        has_machine_id = bool(re.search(self.MACHINE_ID_PATTERN, query, re.IGNORECASE))
        has_safety_term = any(term in q for term in self.SAFETY_TERMS)
        has_api_signal = any(kw in q for kw in self.API_KEYWORDS)
        has_rag_signal = any(kw in q for kw in self.RAG_KEYWORDS)
        has_diagnose_signal = any(kw in q for kw in self.DIAGNOSE_KEYWORDS)

        # Rule 1: Live data only, no need for explanation
        if has_api_signal and not has_rag_signal and not has_diagnose_signal:
            return "API_ONLY"

        # Rule 2: Pure explanation/procedure, no live data markers
        if has_rag_signal and not has_api_signal and not has_machine_id:
            return "RAG_ONLY"

        # Rule 3: Diagnose signal always means both
        if has_diagnose_signal:
            return "API_THEN_RAG"

        # Rule 4: Machine ID + explanation = both
        if has_machine_id and (has_rag_signal or has_safety_term):
            return "API_THEN_RAG"

        # Rule 5: Safety term alone = RAG
        if has_safety_term and not has_api_signal:
            return "RAG_ONLY"

        # Fallback: LLM-based classification
        return self._llm_classify(query)

    def _llm_classify(self, query: str) -> str:
        """
        Used when rule-based signals are ambiguous.
        Prompt the LLM to classify. Expect JSON: {"route": "RAG_ONLY"}
        """
        prompt = f"""
        You are a query router for an industrial maintenance system (eMAS).
        Classify this query into exactly one route:

        - API_ONLY: needs live machine data, metrics, or operational records only
        - RAG_ONLY: needs explanations, procedures, standards, or definitions from documents
        - API_THEN_RAG: needs both live data AND document-based explanation

        Query: "{query}"

        Respond in JSON only: {{"route": "<route>"}}
        """
        # Call LLM and parse response
        result = call_llm(prompt, max_tokens=50)
        return json.loads(result).get("route", "RAG_ONLY")
```

### 2.5 Router Confidence & Override Rules

| Situation | Action |
|---|---|
| Rule-based match is confident (2+ matching signals) | Use rule directly, skip LLM |
| Only 1 rule fires | Use LLM classification |
| LLM returns invalid route | Default to `RAG_ONLY` (safe fallback) |
| User explicitly says "check the document" or "look it up in the system" | Force `RAG_ONLY` or `API_ONLY` respectively |
| Query is a single word with no context | Default to `RAG_ONLY` |

### 2.6 Exit Requirements — Router

The router phase is complete and the next phase may begin only when **all** of the following are true:

| # | Exit Condition | How to Verify |
|---|---|---|
| R1 | Every query produces exactly one of `API_ONLY`, `RAG_ONLY`, `API_THEN_RAG` — never `None` or an unknown string | Unit test all rule paths; assert return type |
| R2 | Rule-based classification fires for ≥ 80 % of test queries (LLM fallback used for ≤ 20 %) | Log `route_source: "rule"` vs `"llm"` in test run |
| R3 | LLM fallback always returns a valid route or defaults to `RAG_ONLY` — never raises an unhandled exception | Test with mocked LLM timeout and malformed JSON |
| R4 | All 7 router test cases in §11 pass | Run test suite |
| R5 | Route decision is logged with `query`, `route`, and `route_source` for every call | Inspect logs after 10 test queries |

**Blocking issues (do not proceed if any apply):**
- Router returns `API_ONLY` for a query containing a safety term without a temporal marker
- Router raises an unhandled exception on any input
- LLM fallback is called more than 30 % of the time on the representative test set

---

## 3. Phase 1 — Document Ingestion

### 3.1 Prerequisites

- `source_register.json` must exist and be current before ingestion runs
- Vector DB must be initialized (e.g., ChromaDB, Qdrant, Weaviate)
- BM25 index directory must be writable

### 3.2 `source_register.json` Schema

Each document entry uses the following structure. Every field has a defined role in retrieval, routing, boosting, or citation.

```json
{
  "documents": [
    {
      "doc_id": "SOP-LOTO-001",
      "title": "LOTO Procedure Standard",
      "file_path": "docs/loto_procedure.pdf",
      "source_type": "internal_sop",
      "organization": "eMAS Site Safety",
      "domain": "safety",
      "subdomain": "lockout_tagout",
      "authority_level": "mandatory_procedure",
      "use_for": [
        "explain LOTO procedure steps",
        "explain energy isolation requirements",
        "explain lockout tagout compliance",
        "support safety audits and SOP references"
      ],
      "do_not_use_for": [
        "live machine lock status lookup",
        "real-time permit approval",
        "vendor-specific equipment instruction",
        "legal or regulatory certification"
      ],
      "related_entities": [
        "energy_isolation",
        "lockout_device",
        "tagout_device",
        "authorized_employee",
        "affected_employee",
        "energy_control_program"
      ],
      "risk_level": "high",
      "license": "internal",
      "version": "2.1",
      "retrieved_date": "2026-05-10",
      "notes": "Mandatory SOP. Always include safety warning when chunks from this doc are used."
    }
  ]
}
```

**Field reference:**

| Field | Required | Role in System |
|---|---|---|
| `doc_id` | ✅ | Unique key; used for re-ingestion checks and chunk IDs |
| `title` | ✅ | Shown in source citations |
| `file_path` | ✅ | Path to the document file for ingestion |
| `source_type` | ✅ | Classifies origin: `internal_sop`, `official_public_pdf`, `vendor_manual`, `internal_report` |
| `organization` | ✅ | Used in citations and authority-level boost |
| `domain` | ✅ | Broad category: `safety`, `maintenance`, `quality`, `operations`, `equipment`, `smart_manufacturing` |
| `subdomain` | ✅ | Fine-grained topic; used for targeted metadata boost |
| `authority_level` | ✅ | Used for trust ranking: `mandatory_procedure` > `official_public_guidance` > `reference_only` |
| `use_for` | ✅ | **Router + reranker filter**: only use this doc when query intent matches one of these |
| `do_not_use_for` | ✅ | **Hard exclusion**: never surface this doc for these query types, even if it scores high |
| `related_entities` | ✅ | Expands BM25 matching beyond raw chunk text; supplements keyword search |
| `risk_level` | ✅ | Triggers automatic safety warning: `"low"` | `"medium"` | `"high"` |
| `license` | ✅ | Controls citation display: `"public"`, `"internal"`, `"restricted"` |
| `version` | ✅ | Used for re-ingestion comparison; shown in citations |
| `retrieved_date` | ✅ | Date the document was acquired; used in staleness checks |
| `notes` | ➖ | Free-text for developer guidance; not used in retrieval logic |

### 3.3 Ingestion Pipeline Steps

```
source_register.json
        │
        ▼
Load & Validate Entries
        │
        ▼
For each document:
    │
    ├─ Load PDF / DOCX / TXT
    ├─ Clean text (remove headers/footers/page numbers)
    ├─ Split into chunks (500–800 tokens, 80–120 overlap)
    ├─ Attach metadata to each chunk
    ├─ Generate embedding (each chunk)
    ├─ Store chunk + embedding in Vector DB
    └─ Add chunk to BM25 index
        │
        ▼
Save BM25 index to disk
        │
        ▼
Log ingestion summary
```

### 3.4 Chunking Strategy — Section-Aware Recursive

To preserve semantic context, we use a **section-aware recursive splitter**. This ensures chunks don't bridge unrelated sections and are prefixed with their structural context.

**Logic:**
1.  **Detect Headings**: Identify `#`, `##`, `###` (Markdown) or bold/numbered lines (PDF/DOCX).
2.  **Split by Section**: Divide the document into top-level sections first.
3.  **Recursive Sub-splitting**: For each section:
    -   If text > `CHUNK_SIZE`, split by paragraphs (`\n\n`).
    -   If still > `CHUNK_SIZE`, split by sentences (`. `).
    -   If still > `CHUNK_SIZE`, split by word boundaries.
4.  **Context Prefixing**: Each chunk's text is prefixed with: `[Section: {section_title}] `.

```python
CHUNK_SIZE = 700        # tokens
CHUNK_OVERLAP = 100     # tokens

def section_aware_split(text: str, metadata: dict) -> list[Chunk]:
    """
    1. Splits by Markdown headers.
    2. Recursively splits large sections into overlapping chunks.
    3. Prefixes text with section context.
    """
    # implementation using MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    sections = markdown_splitter.split_text(text)
    
    final_chunks = []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    
    for section in sections:
        section_title = section.metadata.get("Header 3") or section.metadata.get("Header 2") or section.metadata.get("Header 1") or "General"
        section_path = " > ".join([v for k, v in section.metadata.items() if k.startswith("Header")])
        
        # Split the section content
        sub_chunks = text_splitter.split_text(section.page_content)
        
        for i, sub_text in enumerate(sub_chunks):
            prefixed_text = f"[Section: {section_title}] {sub_text}"
            final_chunks.append(Chunk(
                chunk_id=f"{metadata['doc_id']}_c{len(final_chunks):04d}",
                text=prefixed_text,
                metadata={
                    **metadata,
                    **section.metadata,
                    "section_title": section_title,
                    "section_path": section_path,
                    "chunk_index": i
                }
            ))
    return final_chunks
```

### 3.5 Metadata Attached to Each Chunk

All fields from `source_register.json` are copied onto every chunk, plus ingestion-generated fields. This means the reranker and answer generator always have the full document context available at the chunk level — no secondary lookup needed.

```python
chunk_metadata = {
    # ── Copied from source_register.json ──────────────────────────────────
    "doc_id": "SOP-LOTO-001",
    "title": "LOTO Procedure Standard",
    "source_type": "internal_sop",
    "organization": "eMAS Site Safety",
    "domain": "safety",
    "subdomain": "lockout_tagout",
    "authority_level": "mandatory_procedure",
    "use_for": [
        "explain LOTO procedure steps",
        "explain energy isolation requirements"
    ],
    "do_not_use_for": [
        "live machine lock status lookup",
        "real-time permit approval"
    ],
    "related_entities": [
        "energy_isolation", "lockout_device", "authorized_employee"
    ],
    "risk_level": "high",
    "license": "internal",
    "version": "2.1",
    "retrieved_date": "2026-05-10",

    # ── Generated during ingestion ─────────────────────────────────────────
    "chunk_index": 3,
    "total_chunks": 12,
    "chunk_id": "SOP-LOTO-001_chunk_0003",
    "section_title": "Lockout Procedure Steps",
    "section_path": "Energy Isolation > Lockout Procedure Steps",
    "ingested_at": "2026-05-10T08:00:00Z"
}
```

**Important:** `use_for` and `do_not_use_for` are used at two points:
1. **Post-fusion filter** (§4.5): chunks whose `do_not_use_for` matches the query type are demoted before reranking.
2. **Reranker prompt** (§5.3): the reranker is told the document's intended use to prevent misuse.

### 3.6 Re-ingestion Rules

| Condition | Action |
|---|---|
| `doc_id` already exists in DB AND `version` unchanged | Skip (do not re-ingest) |
| `doc_id` exists AND `version` changed | Delete old chunks, re-ingest |
| `doc_id` is new | Ingest |
| File missing from disk | Log warning, skip |
| `retrieved_date` is older than 180 days AND `source_type` is `official_public_pdf` | Log staleness warning; do not auto-delete, but flag for human review |

### 3.7 Exit Requirements — Phase 1 (Document Ingestion)

Ingestion is complete and Phase 2 may begin only when **all** of the following are true:

| # | Exit Condition | How to Verify |
|---|---|---|
| I1 | All entries in `source_register.json` are ingested with no unhandled errors | Check ingestion summary log: `status: success` for every `doc_id` |
| I2 | Vector DB chunk count matches expected total (sum of chunks across all docs) | Query `vector_db.count()` and compare to ingestion log |
| I3 | BM25 index file exists on disk and loads without error | `bm25_index = load_bm25(BM25_INDEX_PATH)` raises no exception |
| I4 | Every chunk in the vector DB has all required metadata fields present (including `section_title` and `section_path`) | Spot-check 10 random chunks; assert all keys exist |
| I5 | `use_for`, `do_not_use_for`, and `related_entities` are stored as lists, not strings | Assert `isinstance(chunk.metadata["use_for"], list)` |
| I6 | Re-ingestion of an unchanged doc results in zero new chunks added | Run ingestion twice; confirm chunk count is identical |
| I7 | A doc with a changed `version` replaces old chunks entirely (no duplicate chunk IDs) | Modify version, re-ingest, assert old chunk IDs are gone |
| I8 | Failed files are recorded in `failed_ingestion.log` and do not crash the pipeline | Test with a missing PDF path |
| I9 | Chunks are correctly prefixed with `[Section: {title}]` | Assert `chunk.text.startswith("[Section:")` |

**Blocking issues (do not proceed if any apply):**
- Any `doc_id` from `source_register.json` is missing from the vector DB
- BM25 index cannot be loaded
- Any chunk is missing `use_for`, `do_not_use_for`, `authority_level`, or `risk_level`
- Duplicate chunk IDs exist in the vector DB

---

## 4. Phase 2 — Hybrid Retrieval

### 4.1 Retrieval Parameters

```
vector_top_k   = 8   (candidates from vector search)
keyword_top_k  = 8   (candidates from BM25 search)
fusion_top_k   = 8   (candidates after merging and deduplication)
```

### 4.2 Vector Search

```python
def vector_search(query: str, top_k: int = 8) -> list[ScoredChunk]:
    query_embedding = embed(query)
    results = vector_db.similarity_search(
        embedding=query_embedding,
        top_k=top_k
    )
    # Normalize scores to [0, 1]
    return [ScoredChunk(chunk=r.chunk, vector_score=normalize(r.score))
            for r in results]
```

### 4.3 BM25 Keyword Search

BM25 is critical for exact eMAS terms: `LOTO`, `OEE`, `CSF`, `guarding`, machine IDs.

```python
def keyword_search(query: str, top_k: int = 8) -> list[ScoredChunk]:
    tokens = tokenize(query)  # lowercase, remove stopwords
    results = bm25_index.search(tokens, top_k=top_k)
    # Normalize BM25 scores to [0, 1]
    return [ScoredChunk(chunk=r.chunk, keyword_score=normalize(r.score))
            for r in results]
```

### 4.4 Score Fusion (Reciprocal Rank Fusion)

RRF is preferred over weighted sum because it is robust to score scale differences between vector and BM25.

```python
def reciprocal_rank_fusion(
    vector_results: list[ScoredChunk],
    keyword_results: list[ScoredChunk],
    k: int = 60,           # RRF constant (standard = 60)
    top_k: int = 8
) -> list[ScoredChunk]:
    """
    RRF score = 1/(k + rank_in_vector) + 1/(k + rank_in_keyword)
    Higher score = better combined rank.
    """
    scores = {}

    for rank, item in enumerate(vector_results):
        cid = item.chunk.chunk_id
        scores[cid] = scores.get(cid, 0) + 1 / (k + rank + 1)

    for rank, item in enumerate(keyword_results):
        cid = item.chunk.chunk_id
        scores[cid] = scores.get(cid, 0) + 1 / (k + rank + 1)

    # Build unified result list
    all_chunks = {item.chunk.chunk_id: item.chunk
                  for item in vector_results + keyword_results}

    sorted_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]

    return [ScoredChunk(chunk=all_chunks[cid], fusion_score=scores[cid])
            for cid in sorted_ids]
```

### 4.5 Metadata Boost + `do_not_use_for` Filter (Applied After Fusion)

Two operations happen here in order:

1. **Hard exclusion** — chunks whose `do_not_use_for` matches the current query type are removed entirely before reranking. This prevents high-scoring background-knowledge documents from contaminating live-data answers.
2. **Score boost** — remaining chunks get score adjustments based on metadata signals.

```python
BOOST_RULES = {
    "entity_match": 0.25,          # related_entities overlap with query tokens
    "use_for_match": 0.20,         # query intent matches a use_for phrase
    "subdomain_match": 0.15,       # subdomain keyword appears in query
    "authority_mandatory": 0.15,   # authority_level == "mandatory_procedure"
    "authority_official": 0.08,    # authority_level == "official_public_guidance"
    "high_risk_safety": 0.10,      # risk_level == "high" for safety queries
}

QUERY_TYPE_TO_DO_NOT_USE = {
    # Maps detected query route/intent → do_not_use_for phrases to block
    "API_ONLY": [
        "live factory status lookup", "live job scheduling decision",
        "machine availability lookup", "inventory quantity lookup",
        "live machine lock status lookup", "real-time permit approval"
    ],
    "RAG_ONLY": [],   # No exclusions; documents are the source
    "API_THEN_RAG": [
        "legal or compliance certification",
        "automatic schedule approval"
    ]
}

def apply_metadata_filter_and_boost(
    chunks: list[ScoredChunk],
    query: str,
    route: str           # "API_ONLY" | "RAG_ONLY" | "API_THEN_RAG"
) -> list[ScoredChunk]:
    q_lower = query.lower()
    q_tokens = set(q_lower.split())
    blocked_phrases = QUERY_TYPE_TO_DO_NOT_USE.get(route, [])

    filtered = []
    for sc in chunks:
        meta = sc.chunk.metadata
        doc_do_not_use = [phrase.lower() for phrase in meta.get("do_not_use_for", [])]

        # Hard exclusion: remove chunk if any do_not_use_for phrase matches route blocks
        if any(blocked in doc_do_not_use for blocked in blocked_phrases):
            continue  # drop this chunk entirely

        filtered.append(sc)

    # Apply boosts to surviving chunks
    for sc in filtered:
        boost = 0.0
        meta = sc.chunk.metadata

        # related_entities overlap with query tokens
        entities = [e.lower().replace("_", " ") for e in meta.get("related_entities", [])]
        if any(entity in q_lower for entity in entities):
            boost += BOOST_RULES["entity_match"]

        # use_for semantic match (check if any use_for phrase words overlap with query)
        use_for_terms = " ".join(meta.get("use_for", [])).lower()
        overlap = len(q_tokens & set(use_for_terms.split()))
        if overlap >= 2:
            boost += BOOST_RULES["use_for_match"]

        # subdomain keyword in query
        subdomain = meta.get("subdomain", "").replace("_", " ").lower()
        if subdomain and subdomain in q_lower:
            boost += BOOST_RULES["subdomain_match"]

        # Authority level
        authority = meta.get("authority_level", "")
        if authority == "mandatory_procedure":
            boost += BOOST_RULES["authority_mandatory"]
        elif authority == "official_public_guidance":
            boost += BOOST_RULES["authority_official"]

        # Safety query + high risk doc
        if meta.get("risk_level") == "high" and any(
            term in q_lower for term in ["safe", "loto", "guarding", "confined", "hazard"]
        ):
            boost += BOOST_RULES["high_risk_safety"]

        sc.boosted_score = sc.fusion_score + boost

    return sorted(filtered, key=lambda x: x.boosted_score, reverse=True)
```

> **Note:** If filtering removes too many chunks (fewer than `reranker_top_k` remain), log a warning and proceed with what is available rather than failing. The reranker will still select the best from the reduced set.

### 4.6 Exit Requirements — Phase 2 (Hybrid Retrieval)

Retrieval is complete and Phase 3 may begin only when **all** of the following are true:

| # | Exit Condition | How to Verify |
|---|---|---|
| H1 | Vector search returns ≤ `vector_top_k` results and never errors on a valid query | Run 10 test queries; assert `len(results) <= 8` |
| H2 | BM25 search returns results for queries containing exact eMAS terms (LOTO, OEE, CSF) | Assert top-1 BM25 result contains the queried term |
| H3 | RRF fusion output contains no duplicate `chunk_id` values | Assert `len(set(ids)) == len(ids)` after fusion |
| H4 | Fusion output is sorted by descending `fusion_score` before boosting | Assert `scores[i] >= scores[i+1]` for all i |
| H5 | `do_not_use_for` filter removes at least one chunk in a controlled test (route=`API_ONLY`, background-knowledge doc in candidates) | Inject known background-knowledge chunk; assert it is absent after filter |
| H6 | `boosted_score` is always ≥ `fusion_score` for every surviving chunk | Assert no chunk has `boosted_score < fusion_score` |
| H7 | Filter never removes all chunks (minimum 1 chunk must survive to reranker) | Test with a set of candidates that all have matching `do_not_use_for`; assert fallback behaviour |
| H8 | Retrieval completes in under 2 seconds for a standard query (vector + BM25 + fusion + boost) | Time 10 queries; assert p95 < 2 s |

**Blocking issues (do not proceed if any apply):**
- Vector search or BM25 search throws an unhandled exception on any test query
- RRF output contains duplicate chunk IDs
- `do_not_use_for` filter is not applied (background-knowledge chunks pass through to reranker)
- All chunks are removed by the filter with no fallback

---

## 5. Phase 3 — Reranking

### 5.1 Purpose

The reranker takes the top-8 fusion candidates and selects the best 3–4 chunks using an LLM judge. This removes irrelevant chunks that scored high due to keyword overlap but lack semantic relevance.

### 5.2 Reranker Parameters

```
reranker_top_k = 3   (default)
reranker_top_k = 4   (for complex/multi-step queries)
```

Use `reranker_top_k = 4` when:
- Query contains "steps", "procedure", "process" (likely multi-chunk answer)
- Query spans two topic areas (e.g., "LOTO and OEE")
- Query is a follow-up on a previous multi-part answer

### 5.3 Reranker Prompt

The reranker prompt now includes `use_for` and `do_not_use_for` from each chunk's metadata. This gives the LLM explicit guidance about each document's intended scope — preventing, for example, a smart manufacturing reference architecture doc from being selected to answer a live OEE lookup.

```python
RERANKER_PROMPT = """
You are an expert reranker for an industrial maintenance knowledge base (eMAS).

User query: {query}
Query route: {route}

Below are {n} retrieved document chunks. Select the {top_k} chunks most relevant
to answering the query. Apply these rules strictly:

Selection criteria (in priority order):
1. HARD RULE: Never select a chunk if the query matches any of its "do_not_use_for" items.
2. Prefer chunks whose "use_for" list matches the query intent.
3. Prefer higher authority_level: mandatory_procedure > official_public_guidance > reference_only.
4. Prefer specificity: specific procedure > general background knowledge.
5. Always retain safety-relevant chunks (risk_level: high) for safety queries.

Chunks:
{chunks_formatted}

Return ONLY a JSON array of selected chunk IDs, ordered by relevance (best first):
["chunk_id_1", "chunk_id_2", ...]
Do not include any other text.
"""

def llm_rerank(
    query: str,
    candidates: list[ScoredChunk],
    route: str,
    top_k: int = 3
) -> list[Chunk]:
    chunks_formatted = "\n\n".join([
        f"[{i+1}] ID: {sc.chunk.chunk_id}\n"
        f"Source: {sc.chunk.metadata['title']} ({sc.chunk.metadata['organization']})\n"
        f"Domain: {sc.chunk.metadata['domain']} / {sc.chunk.metadata['subdomain']}\n"
        f"Authority: {sc.chunk.metadata['authority_level']}\n"
        f"Use for: {'; '.join(sc.chunk.metadata.get('use_for', [])[:2])}\n"
        f"Do NOT use for: {'; '.join(sc.chunk.metadata.get('do_not_use_for', [])[:2])}\n"
        f"Risk: {sc.chunk.metadata['risk_level']}\n"
        f"Text: {sc.chunk.text[:350]}..."
        for i, sc in enumerate(candidates)
    ])

    prompt = RERANKER_PROMPT.format(
        query=query,
        route=route,
        n=len(candidates),
        top_k=top_k,
        chunks_formatted=chunks_formatted
    )

    response = call_llm(prompt, max_tokens=200)
    selected_ids = json.loads(response)

    # Return chunks in selected order
    id_to_chunk = {sc.chunk.chunk_id: sc.chunk for sc in candidates}
    return [id_to_chunk[cid] for cid in selected_ids if cid in id_to_chunk]
```

### 5.4 Reranker Fallback

If LLM reranker fails (timeout, parse error, rate limit):
- Fall back to top-3 by `boosted_score` without LLM reranking
- Log the fallback occurrence for monitoring
- Do not surface the error to the user

### 5.5 Exit Requirements — Phase 3 (Reranking)

Reranking is complete and Phase 4 may begin only when **all** of the following are true:

| # | Exit Condition | How to Verify |
|---|---|---|
| RR1 | Reranker returns exactly `reranker_top_k` chunks (or fewer if candidates < top_k) | Assert `len(result) <= reranker_top_k` |
| RR2 | All returned chunk IDs exist in the input candidate set (no hallucinated IDs) | Assert every returned ID is in `{sc.chunk.chunk_id for sc in candidates}` |
| RR3 | A `do_not_use_for` violating chunk is NOT present in the reranker output, even if the LLM selects it | Post-rerank validation step removes any chunk still violating `do_not_use_for` |
| RR4 | A `risk_level == "high"` chunk is retained for a safety-related query even if ranked lower in fusion | Test with a safety query; assert high-risk chunk is in final output |
| RR5 | LLM reranker timeout triggers fallback to `boosted_score` top-k without surfacing an error | Mock LLM timeout; assert result is non-empty and no exception raised |
| RR6 | Reranker fallback is logged (`reranker_fallback: true`) when triggered | Check logs after mocked timeout test |
| RR7 | Reranker completes in under 3 seconds (LLM call included) | Time 10 rerank calls; assert p95 < 3 s |

**Blocking issues (do not proceed if any apply):**
- Reranker returns chunk IDs not in the candidate set
- A `do_not_use_for` violating chunk appears in the final output passed to the answer generator
- Reranker raises an unhandled exception (fallback must always catch)

---

## 6. Phase 4 — Answer Generation

### 6.1 Context Builder

```python
def build_context(chunks: list[Chunk]) -> str:
    """
    Format selected chunks into a structured context block for the answer LLM.
    Includes authority_level and organization so the answer LLM can calibrate
    how strongly to weight each source.
    """
    context_parts = []
    for i, chunk in enumerate(chunks):
        context_parts.append(
            f"[SOURCE {i+1}: {chunk.metadata['title']}\n"
            f" Organization: {chunk.metadata['organization']}\n"
            f" Authority: {chunk.metadata['authority_level']}\n"
            f" Domain: {chunk.metadata['domain']} / {chunk.metadata['subdomain']}\n"
            f" Risk Level: {chunk.metadata['risk_level']}\n"
            f" License: {chunk.metadata['license']}]\n"
            f"{chunk.text}"
        )
    return "\n\n---\n\n".join(context_parts)
```

### 6.2 Answer Generation Prompt

```python
ANSWER_PROMPT = """
You are eMAS Assistant, an expert in industrial maintenance, safety, and operations.

Answer the user's question using ONLY the provided context. Do not use prior knowledge.
If the context does not contain enough information to answer, say so clearly.

Rules:
- Be concise and direct
- Use numbered steps for procedures
- Cite source numbers like [SOURCE 1] after each claim
- If risk_level is "high" in any source, add a safety warning at the end
- Do not speculate beyond the context

Context:
{context}

{api_data_section}

User question: {query}

Answer:
"""

API_DATA_SECTION_TEMPLATE = """
Live system data (from API):
{api_data}

Use this live data together with the document context to give a complete answer.
"""

def generate_answer(
    query: str,
    chunks: list[Chunk],
    api_data: dict | None = None
) -> AnswerResult:
    context = build_context(chunks)

    api_section = ""
    if api_data:
        api_section = API_DATA_SECTION_TEMPLATE.format(
            api_data=json.dumps(api_data, indent=2)
        )

    prompt = ANSWER_PROMPT.format(
        context=context,
        api_data_section=api_section,
        query=query
    )

    answer_text = call_llm(prompt, max_tokens=600)
    has_high_risk = any(c.metadata.get("risk_level") == "high" for c in chunks)

    return AnswerResult(
        answer=answer_text,
        sources=[build_source_citation(c) for c in chunks],
        safety_warning=has_high_risk,
        route_used="RAG_ONLY" if not api_data else "API_THEN_RAG"
    )
```

### 6.3 Safety Warning

Append this block automatically when any chunk has `risk_level == "high"`:

```
⚠️ SAFETY WARNING: This topic involves high-risk procedures.
Always follow your site's approved SOP, obtain required permits,
and consult your safety officer before proceeding.
```

### 6.4 Source Citation Format

```python
def build_source_citation(chunk: Chunk, source_number: int) -> SourceCitation:
    return SourceCitation(
        source_number=source_number,
        doc_id=chunk.metadata["doc_id"],
        title=chunk.metadata["title"],
        organization=chunk.metadata["organization"],
        authority_level=chunk.metadata["authority_level"],
        domain=chunk.metadata["domain"],
        version=chunk.metadata.get("version", "N/A"),
        license=chunk.metadata.get("license", "internal"),
        retrieved_date=chunk.metadata.get("retrieved_date", "")
    )
```

Output format shown to user:

```
📄 Sources:
[1] LOTO Procedure Standard v2.1 — eMAS Site Safety (mandatory_procedure) — Safety [internal]
[2] Reference Architecture for Smart Manufacturing — NIST (official_public_guidance) — Smart Manufacturing [public]
```

> **License display rule:** If `license == "restricted"`, show the source title but append `[restricted — internal use only]`. Do not display `file_path` to the user under any license type.

### 6.5 Exit Requirements — Phase 4 (Answer Generation)

Answer generation is complete and the response may be returned to the caller only when **all** of the following are true:

| # | Exit Condition | How to Verify |
|---|---|---|
| A1 | Answer text is non-empty and does not contain raw prompt artefacts (e.g. `{query}`, `{context}`) | Assert answer length > 0 and no `{` / `}` template tokens remain |
| A2 | Every `[SOURCE N]` citation in the answer body has a matching entry in the `sources` list | Parse citations from answer text; assert each N maps to a source |
| A3 | Safety warning is appended when any selected chunk has `risk_level == "high"` | Test with a high-risk chunk; assert warning block is present |
| A4 | Safety warning is absent when no selected chunk has `risk_level == "high"` | Test with only low-risk chunks; assert warning block is absent |
| A5 | Source citation includes `organization`, `authority_level`, and `license` fields | Assert all three fields are non-empty strings in each `SourceCitation` |
| A6 | `file_path` does not appear anywhere in the answer text or source citations | Assert `file_path` not in answer string; not in any citation field |
| A7 | `license == "restricted"` source shows `[restricted — internal use only]` in citation display | Test with a restricted-license chunk; assert tag is present |
| A8 | `API_THEN_RAG` answer references both live API data and at least one document source | Assert answer contains content from `api_data` and at least one `[SOURCE N]` |
| A9 | Answer LLM failure returns a user-facing fallback message, not a stack trace | Mock LLM failure; assert response is the defined fallback string |

**Blocking issues (do not proceed if any apply):**
- Answer is empty or contains raw prompt template tokens
- `file_path` is exposed to the user in any field
- Safety warning is missing for a `risk_level == "high"` query result
- Answer LLM exception is unhandled and propagates to the user

---

## 7. Phase 5 — Agent Integration

### 7.1 Before vs After

**Before (existing):**
```
User Query → Planner → Tool Agent → Answer
```

**After:**
```
User Query → Router → [API_ONLY: Tool Agent]
                    → [RAG_ONLY: RAG Pipeline]
                    → [API_THEN_RAG: Tool Agent → RAG Pipeline → Merged Answer]
```

### 7.2 API_THEN_RAG Execution Order

```
1. Run Tool Agent (API call)
   └─ Returns: structured data (metrics, records, status)

2. Pass API result as context to RAG pipeline
   └─ Query is enriched: "Given [API result], explain/advise..."

3. Run RAG pipeline
   └─ Returns: explanation chunks with citations

4. Merge both results in Answer Generator
   └─ Returns: grounded answer using live data + document context
```

### 7.3 API_THEN_RAG Query Enrichment

Before sending to RAG, enrich the query with the API result:

```python
def enrich_query_with_api_result(
    original_query: str,
    api_result: dict
) -> str:
    """
    Augment the query so the RAG pipeline has the live context it needs.
    """
    api_summary = json.dumps(api_result, indent=2)
    return (
        f"Original question: {original_query}\n\n"
        f"Live system data already retrieved:\n{api_summary}\n\n"
        f"Now explain or advise based on this data and relevant procedures."
    )
```

### 7.4 Integration Code Skeleton

```python
class eMASAgent:

    def __init__(self):
        self.router = QueryRouter()
        self.tool_agent = ToolAgent()       # existing
        self.rag_pipeline = RAGPipeline()   # new

    def run(self, query: str) -> AgentResponse:
        route = self.router.route(query)

        if route == "API_ONLY":
            result = self.tool_agent.run(query)
            return AgentResponse(answer=result, sources=[], route=route)

        elif route == "RAG_ONLY":
            result = self.rag_pipeline.run(query)
            return AgentResponse(
                answer=result.answer,
                sources=result.sources,
                safety_warning=result.safety_warning,
                route=route
            )

        elif route == "API_THEN_RAG":
            api_result = self.tool_agent.run(query)
            enriched_query = enrich_query_with_api_result(query, api_result)
            rag_result = self.rag_pipeline.run(
                query=enriched_query,
                api_data=api_result
            )
            return AgentResponse(
                answer=rag_result.answer,
                sources=rag_result.sources,
                safety_warning=rag_result.safety_warning,
                route=route
            )
```

### 7.5 Exit Requirements — Phase 5 (Agent Integration)

The full eMAS RAG agent is ready for use / production deployment only when **all** of the following are true:

| # | Exit Condition | How to Verify |
|---|---|---|
| AG1 | All three routes (`API_ONLY`, `RAG_ONLY`, `API_THEN_RAG`) return an `AgentResponse` with no unhandled exceptions | Run one representative query per route; assert `AgentResponse` is returned |
| AG2 | `API_ONLY` route never calls the RAG pipeline | Mock RAG pipeline to raise if called; run API_ONLY query; assert no exception |
| AG3 | `RAG_ONLY` route never calls the tool agent | Mock tool agent to raise if called; run RAG_ONLY query; assert no exception |
| AG4 | `API_THEN_RAG` calls tool agent first, then RAG — never in reverse order | Add timestamps to mocks; assert `api_call_time < rag_call_time` |
| AG5 | Tool agent failure in `API_THEN_RAG` falls back to `RAG_ONLY` and notes missing live data in the answer | Mock tool agent to raise; assert response still contains RAG answer with fallback note |
| AG6 | `AgentResponse.route` field always matches the router's decision | Assert `response.route == router.route(query)` for all test queries |
| AG7 | End-to-end latency (query in → answer out) is under 10 seconds for `RAG_ONLY` queries | Time 5 end-to-end RAG_ONLY calls; assert p95 < 10 s |
| AG8 | All exit requirements for Phases 1–4 have been individually verified before running Phase 5 integration tests | Confirm phase exit checklists are signed off |

**Blocking issues (do not proceed if any apply):**
- Any route returns an unhandled exception on a valid query
- `API_THEN_RAG` calls RAG before the tool agent
- Tool agent failure in `API_THEN_RAG` propagates to the user as an unhandled error
- Any Phase 1–4 exit requirement is unmet

---

## 8. Data Structures & Contracts

```python
@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict
    # metadata keys (all from source_register.json + ingestion — see §3.5):
    # doc_id, title, source_type, organization, domain, subdomain,
    # authority_level, use_for, do_not_use_for, related_entities,
    # risk_level, license, version, retrieved_date,
    # chunk_index, total_chunks, chunk_id, ingested_at

@dataclass
class ScoredChunk:
    chunk: Chunk
    vector_score: float = 0.0
    keyword_score: float = 0.0
    fusion_score: float = 0.0
    boosted_score: float = 0.0
    excluded: bool = False      # True if removed by do_not_use_for filter

@dataclass
class SourceCitation:
    source_number: int
    doc_id: str
    title: str
    organization: str
    authority_level: str
    domain: str
    version: str
    license: str
    retrieved_date: str

@dataclass
class AnswerResult:
    answer: str
    sources: list[SourceCitation]
    safety_warning: bool
    route_used: str

@dataclass
class AgentResponse:
    answer: str
    sources: list[SourceCitation]
    route: str
    safety_warning: bool = False
```

---

## 9. Configuration Reference

All values in one place. Change here only.

```python
# config.py

# Retrieval
VECTOR_TOP_K = 8
KEYWORD_TOP_K = 8
FUSION_TOP_K = 8
RERANKER_TOP_K_DEFAULT = 3
RERANKER_TOP_K_COMPLEX = 4   # used for procedure/multi-step queries

# Chunking
CHUNK_SIZE_TOKENS = 700
CHUNK_OVERLAP_TOKENS = 100

# Fusion
RRF_K_CONSTANT = 60

# Metadata boost weights (§4.5)
BOOST_ENTITY_MATCH = 0.25
BOOST_USE_FOR_MATCH = 0.20
BOOST_SUBDOMAIN_MATCH = 0.15
BOOST_AUTHORITY_MANDATORY = 0.15
BOOST_AUTHORITY_OFFICIAL = 0.08
BOOST_HIGH_RISK_SAFETY = 0.10

# do_not_use_for filter: minimum token overlap to count a use_for phrase match
USE_FOR_MIN_OVERLAP_TOKENS = 2

# LLM
ANSWER_MAX_TOKENS = 600
RERANKER_MAX_TOKENS = 200
ROUTER_MAX_TOKENS = 50

# Vector DB
VECTOR_DB_COLLECTION = "emas_docs"
EMBEDDING_MODEL = "text-embedding-3-small"   # replace with your model

# BM25 index
BM25_INDEX_PATH = "./data/bm25_index.pkl"

# Source register
SOURCE_REGISTER_PATH = "./data/source_register.json"
```

---

## 10. Error Handling & Fallbacks

| Failure Point | Detection | Fallback Action |
|---|---|---|
| Router LLM fails | Exception / empty response | Default to `RAG_ONLY` |
| Vector DB unreachable | Connection error | Run keyword-only search, log alert |
| BM25 index missing | File not found | Run vector-only search, log alert |
| Reranker LLM fails | Exception / parse error | Use top-3 by `boosted_score` |
| Answer LLM fails | Exception / timeout | Return "Unable to generate answer. Please try again." with raw source titles |
| API tool agent fails (API_THEN_RAG) | Exception | Fall back to `RAG_ONLY`, note that live data was unavailable in response |
| No chunks retrieved | Empty results list | Return "No relevant documents found for this query." |
| PDF load fails during ingestion | File error | Log and skip, add to failed_ingestion.log |

---

## 11. Testing Checklist

### Router Tests

- [ ] "What is the OEE for Line 3?" → `API_ONLY`
- [ ] "Explain the LOTO procedure" → `RAG_ONLY`
- [ ] "OEE is 65%, is that acceptable?" → `API_THEN_RAG`
- [ ] "Show me open work orders and the guarding standard" → `API_THEN_RAG`
- [ ] "What does CSF stand for?" → `RAG_ONLY`
- [ ] Single-word query "LOTO" → `RAG_ONLY`
- [ ] Ambiguous query triggers LLM fallback, returns valid route

### Retrieval Tests

- [ ] Exact eMAS term (LOTO, OEE) retrieves relevant chunks via BM25
- [ ] `related_entities` terms retrieve correct chunk even if those words are not in chunk text
- [ ] Semantic paraphrase retrieves correct chunk via vector
- [ ] Duplicate chunks from both searches are deduplicated after fusion
- [ ] `do_not_use_for` filter removes background-knowledge doc when route is `API_ONLY`
- [ ] `use_for` overlap boost raises rank of intent-matched chunk
- [ ] `authority_level == "mandatory_procedure"` chunk ranks above `reference_only` chunk with similar fusion score
- [ ] Staleness warning logged for `official_public_pdf` with `retrieved_date` > 180 days old

### Reranker Tests

- [ ] Top-3 selected from 8 candidates
- [ ] Safety chunk retained even if ranked 6th before reranking
- [ ] Reranker prompt includes `use_for`, `do_not_use_for`, `authority_level` for each chunk
- [ ] Background-knowledge doc (e.g. NIST smart manufacturing) is NOT selected for a live OEE query
- [ ] `mandatory_procedure` doc is preferred over `reference_only` doc when content is equivalent
- [ ] Fallback to `boosted_score` top-3 on LLM timeout

### Answer Tests

- [ ] Safety warning appears when `risk_level == "high"` chunk is used
- [ ] Source citations include `organization`, `authority_level`, and `license`
- [ ] `license == "restricted"` citation shows `[restricted — internal use only]`
- [ ] `file_path` is never shown to the user in any citation
- [ ] API_THEN_RAG answer references both live data and document
- [ ] Answer does not hallucinate beyond provided context
- [ ] Context block passed to LLM includes `authority_level` and `organization` per source

### Ingestion Tests

- [ ] All docs in `source_register.json` are ingested
- [ ] All new schema fields (`use_for`, `do_not_use_for`, `related_entities`, `authority_level`, etc.) are copied onto every chunk
- [ ] Re-ingestion skips unchanged versions (matched by `doc_id` + `version`)
- [ ] Re-ingestion replaces changed versions (deletes old chunks, re-ingests)
- [ ] Missing file is logged and skipped without crashing
- [ ] `official_public_pdf` with `retrieved_date` > 180 days triggers staleness warning in logs
- [ ] Entry missing a required field raises validation error before ingestion begins

---

*End of eMAS RAG Implementation Plan v1.2*
