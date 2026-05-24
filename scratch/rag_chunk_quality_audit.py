from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
import fitz


SECTION_PREFIX_RE = re.compile(r"^\[Section: [^\]]+\]\s*")
WORD_RE = re.compile(r"\b\w+(?:[-']\w+)?\b")
SENTENCE_RE = re.compile(r"[^.!?]+[.!?](?=\s|$)")


@dataclass(frozen=True)
class StoredChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _clean_text(text: str) -> str:
    return SECTION_PREFIX_RE.sub("", text or "").strip()


def _jsonish(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"[", "{"}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: _jsonish(value) for key, value in metadata.items()}


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def _sentence_count(text: str) -> int:
    return len(SENTENCE_RE.findall(text))


def _starts_mid_sentence(text: str) -> bool:
    stripped = _clean_text(text)
    if not stripped:
        return False
    if re.match(r"^(\(?\d+[.)]|[A-Z][A-Z0-9]{1,8}\b|[A-Z][a-z]+\b|[-*])", stripped):
        return False
    return bool(re.match(r"^[a-z,;:)\]]", stripped))


def _ends_without_terminal(text: str) -> bool:
    stripped = _clean_text(text)
    if not stripped:
        return False
    return not bool(re.search(r"[.!?:;\])\"']$", stripped))


def _header_footer_noise_ratio(text: str) -> float:
    lines = [line.strip() for line in _clean_text(text).splitlines() if line.strip()]
    if not lines:
        return 0.0
    noisy = 0
    for line in lines:
        lowered = line.lower()
        if (
            "this publication is available free" in lowered
            or "nist." in lowered
            or "occupational safety and health" in lowered
            or re.fullmatch(r"\d+", lowered)
        ):
            noisy += 1
    return noisy / len(lines)


def _front_matter_or_boilerplate(text: str, metadata: dict[str, Any]) -> bool:
    cleaned = _clean_text(text).lower()
    page = int(metadata.get("page", 0) or 0)
    return page <= 5 or any(
        marker in cleaned
        for marker in (
            "abstract",
            "table of contents",
            "contents",
            "disclaimer",
            "this publication is available free",
        )
    )


def _quantiles(values: list[int]) -> tuple[int, int, int, int, int]:
    if not values:
        return 0, 0, 0, 0, 0
    if len(values) < 4:
        median = int(statistics.median(values))
        return min(values), median, median, median, max(values)
    q = statistics.quantiles(values, n=4)
    return min(values), int(q[0]), int(statistics.median(values)), int(q[2]), max(values)


def _exact_suffix_prefix_overlap(left: str, right: str, max_chars: int = 300) -> int:
    limit = min(max_chars, len(left), len(right))
    best = 0
    for width in range(1, limit + 1):
        if left[-width:] == right[:width]:
            best = width
    return best


def _load_chunks(db_path: Path, collection_name: str) -> list[StoredChunk]:
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_collection(name=collection_name)
    result = collection.get(include=["documents", "metadatas"])
    chunks = [
        StoredChunk(chunk_id=chunk_id, text=text, metadata=_clean_metadata(metadata))
        for chunk_id, text, metadata in zip(
            result["ids"], result["documents"], result["metadatas"]
        )
    ]
    return chunks


def _load_register(register_path: Path) -> dict[str, dict[str, Any]]:
    with register_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    root = register_path.parent.parent
    docs: dict[str, dict[str, Any]] = {}
    for entry in data.get("documents", []):
        raw_path = Path(entry["file_path"])
        file_path = raw_path if raw_path.is_absolute() else root / raw_path
        docs[entry["doc_id"]] = {**entry, "resolved_file_path": file_path}
    return docs


def _pdf_toc(doc_path: Path) -> list[tuple[int, str, int]]:
    if not doc_path.exists() or doc_path.suffix.lower() != ".pdf":
        return []
    with fitz.open(doc_path) as pdf:
        return [(int(level), str(title).strip(), int(page)) for level, title, page in pdf.get_toc(simple=True)]


def _build_doc_stats(chunks: list[StoredChunk]) -> dict[str, Any]:
    pages: Counter[Any] = Counter()
    sections: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    char_lengths: list[int] = []
    word_lengths: list[int] = []
    sentence_counts: list[int] = []

    for chunk in chunks:
        cleaned = _clean_text(chunk.text)
        meta = chunk.metadata
        pages[meta.get("page")] += 1
        sections[str(meta.get("section_title", "<missing>"))] += 1
        char_lengths.append(len(cleaned))
        word_lengths.append(_word_count(cleaned))
        sentence_counts.append(_sentence_count(cleaned))

        if _starts_mid_sentence(chunk.text):
            flags["starts_mid_sentence_heuristic"] += 1
        if _ends_without_terminal(chunk.text):
            flags["ends_without_terminal_heuristic"] += 1
        if len(cleaned) < 120:
            flags["very_short"] += 1
        if len(cleaned) > 1100:
            flags["oversize"] += 1
        if _header_footer_noise_ratio(chunk.text) >= 0.20:
            flags["header_footer_noise_high"] += 1
        if _front_matter_or_boilerplate(chunk.text, meta):
            flags["front_matter_or_boilerplate"] += 1

    return {
        "chunk_count": len(chunks),
        "page_count": len(pages),
        "chunks_per_page_avg": len(chunks) / max(1, len(pages)),
        "chunks_per_page_max": max(pages.values()) if pages else 0,
        "top_split_pages": pages.most_common(5),
        "section_titles": sections,
        "char_quantiles": _quantiles(char_lengths),
        "word_median": int(statistics.median(word_lengths)) if word_lengths else 0,
        "word_max": max(word_lengths) if word_lengths else 0,
        "sentence_median": int(statistics.median(sentence_counts)) if sentence_counts else 0,
        "sentence_max": max(sentence_counts) if sentence_counts else 0,
        "flags": flags,
    }


def _adjacency_stats(chunks: list[StoredChunk]) -> dict[str, Any]:
    by_page: dict[Any, list[StoredChunk]] = defaultdict(list)
    for chunk in chunks:
        by_page[chunk.metadata.get("page")].append(chunk)

    overlaps: list[int] = []
    examples: list[dict[str, Any]] = []
    for page, rows in by_page.items():
        rows.sort(key=lambda c: int(c.metadata.get("chunk_index", 0) or 0))
        for left, right in zip(rows, rows[1:]):
            left_text = _clean_text(left.text)
            right_text = _clean_text(right.text)
            overlap = _exact_suffix_prefix_overlap(left_text, right_text)
            overlaps.append(overlap)
            if len(examples) < 4 and (_starts_mid_sentence(right.text) or _ends_without_terminal(left.text)):
                examples.append(
                    {
                        "page": page,
                        "left_id": left.chunk_id,
                        "right_id": right.chunk_id,
                        "overlap_chars": overlap,
                        "left_tail": _ascii(left_text[-280:].replace("\n", " | ")),
                        "right_head": _ascii(right_text[:280].replace("\n", " | ")),
                    }
                )

    return {
        "pair_count": len(overlaps),
        "overlap_min": min(overlaps) if overlaps else 0,
        "overlap_median": int(statistics.median(overlaps)) if overlaps else 0,
        "overlap_max": max(overlaps) if overlaps else 0,
        "examples": examples,
    }


def _sample_chunks(chunks: list[StoredChunk], limit: int) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for chunk in sorted(chunks, key=lambda c: int(c.metadata.get("chunk_index", 0) or 0)):
        if _starts_mid_sentence(chunk.text) or _ends_without_terminal(chunk.text):
            samples.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "page": chunk.metadata.get("page"),
                    "starts_mid_sentence": _starts_mid_sentence(chunk.text),
                    "ends_without_terminal": _ends_without_terminal(chunk.text),
                    "section_title": chunk.metadata.get("section_title"),
                    "text": _ascii(_clean_text(chunk.text)[:500].replace("\n", " | ")),
                }
            )
        if len(samples) >= limit:
            break
    return samples


def build_report(
    db_path: Path,
    register_path: Path,
    collection_name: str,
    sample_limit: int,
) -> str:
    chunks = _load_chunks(db_path, collection_name)
    register = _load_register(register_path)

    by_doc: dict[str, list[StoredChunk]] = defaultdict(list)
    source_formats: Counter[str] = Counter()
    for chunk in chunks:
        by_doc[str(chunk.metadata.get("doc_id", "<missing>"))].append(chunk)
        source_formats[str(chunk.metadata.get("source_format", "<missing>"))] += 1

    lines: list[str] = []
    lines.append("# RAG Chunk Quality Audit")
    lines.append("")
    lines.append(f"- Collection: `{collection_name}`")
    lines.append(f"- Vector DB path: `{db_path}`")
    lines.append(f"- Total stored chunks: {len(chunks)}")
    lines.append(f"- Source formats: {dict(source_formats)}")
    lines.append("")

    lines.append("## Executive Findings")
    lines.append("")
    lines.append("- Current chunks are accessible from ChromaDB with `collection.get(include=[\"documents\", \"metadatas\"])`.")
    lines.append("- All stored chunks are PDF chunks. The Markdown/internal docs in `rag_sources/01_emas_internal_docs` are not in the current source register.")
    lines.append("- PDF ingestion is page-first, then recursive character splitting is applied inside each page.")
    lines.append("- Stored section metadata does not preserve real PDF sections today. Every chunk uses `section_title = General`.")
    lines.append("- Adjacent same-page chunks intentionally overlap by roughly 130-199 characters, which helps retrieval continuity but means chunks are not clean paragraph or sentence units.")
    lines.append("")

    lines.append("## Document Summary")
    lines.append("")
    lines.append("| doc_id | chunks | PDF pages seen | PDF TOC entries | stored section titles | median chars | median words | boundary flags |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    all_flags: Counter[str] = Counter()
    doc_stats: dict[str, dict[str, Any]] = {}
    adjacency: dict[str, dict[str, Any]] = {}
    toc_by_doc: dict[str, list[tuple[int, str, int]]] = {}

    for doc_id, rows in sorted(by_doc.items()):
        rows.sort(key=lambda c: int(c.metadata.get("chunk_index", 0) or 0))
        stats = _build_doc_stats(rows)
        adj = _adjacency_stats(rows)
        doc_stats[doc_id] = stats
        adjacency[doc_id] = adj
        all_flags.update(stats["flags"])

        doc_path = register.get(doc_id, {}).get("resolved_file_path")
        toc = _pdf_toc(Path(doc_path)) if doc_path else []
        toc_by_doc[doc_id] = toc
        _, _, median_chars, _, _ = stats["char_quantiles"]
        boundary_flags = stats["flags"]["starts_mid_sentence_heuristic"] + stats["flags"]["ends_without_terminal_heuristic"]
        lines.append(
            f"| `{doc_id}` | {stats['chunk_count']} | {stats['page_count']} | {len(toc)} | "
            f"{len(stats['section_titles'])} | {median_chars} | {stats['word_median']} | {boundary_flags} |"
        )

    lines.append("")
    lines.append("## Per-Document Metrics")
    lines.append("")

    for doc_id, stats in doc_stats.items():
        q_min, q25, q50, q75, q_max = stats["char_quantiles"]
        section_preview = ", ".join(
            f"{title}: {count}" for title, count in stats["section_titles"].most_common(5)
        )
        toc_preview = "; ".join(
            _ascii(f"L{level} p{page} {title}")
            for level, title, page in toc_by_doc.get(doc_id, [])[:8]
        )
        adj = adjacency[doc_id]
        lines.append(f"### {doc_id}")
        lines.append("")
        lines.append(f"- Chunks/pages: {stats['chunk_count']} chunks across {stats['page_count']} pages, avg {stats['chunks_per_page_avg']:.2f} chunks/page, max {stats['chunks_per_page_max']}.")
        lines.append(f"- Character length min/p25/median/p75/max: {q_min}/{q25}/{q50}/{q75}/{q_max}.")
        lines.append(f"- Word median/max: {stats['word_median']}/{stats['word_max']}; rough sentence median/max: {stats['sentence_median']}/{stats['sentence_max']}.")
        lines.append(f"- Stored section titles: {section_preview or 'none'}.")
        lines.append(f"- PDF TOC sample: {toc_preview or 'No PDF bookmark TOC detected'}")
        lines.append(f"- Flags: {dict(stats['flags'])}.")
        lines.append(f"- Adjacent same-page splits: {adj['pair_count']} pairs, exact overlap min/median/max {adj['overlap_min']}/{adj['overlap_median']}/{adj['overlap_max']} chars.")
        lines.append("")

    lines.append("## Boundary Examples")
    lines.append("")
    for doc_id, rows in sorted(by_doc.items()):
        lines.append(f"### {doc_id}")
        lines.append("")
        for example in _sample_chunks(rows, sample_limit):
            lines.append(
                f"- `{example['chunk_id']}` page {example['page']}, section `{example['section_title']}`, "
                f"starts_mid={example['starts_mid_sentence']}, ends_mid={example['ends_without_terminal']}"
            )
            lines.append(f"  - {example['text']}")
        for example in adjacency[doc_id]["examples"][:2]:
            lines.append(
                f"- Adjacent overlap `{example['left_id']}` -> `{example['right_id']}` page {example['page']} "
                f"({example['overlap_chars']} exact chars)"
            )
            lines.append(f"  - left tail: {example['left_tail']}")
            lines.append(f"  - right head: {example['right_head']}")
        lines.append("")

    lines.append("## Gap Against Section -> Paragraph -> Sentence Chunking")
    lines.append("")
    lines.append("1. Section gap: PDF bookmark TOCs exist for four of the five PDFs, but the ingestion code does not use them. The Markdown header splitter only recognizes `#`, `##`, and `###`, which are not present in plain PDF-extracted text, so all PDF chunks become `General`.")
    lines.append("2. Paragraph gap: PyMuPDF `page.get_text(\"text\")` preserves visual line breaks more than semantic paragraphs. The recursive splitter sees many line breaks, so it often splits by visual lines rather than true paragraphs.")
    lines.append("3. Sentence gap: `. ` is only the third fallback separator after double-newline and newline. Many chunk boundaries are created by size and overlap, so chunks frequently start or end inside a sentence or repeated paragraph tail.")
    lines.append("4. Page gap: The pipeline splits each page independently. A section or paragraph that crosses pages cannot be reconstructed before chunking.")
    lines.append("5. Noise gap: Front matter, table-of-contents text, repeated publication headers, page numbers, and checklist table columns are embedded as normal chunks.")
    lines.append("6. Traceability gap: Metadata has page and char ranges, but not `section_id`, `section_path` from real PDF structure, `paragraph_index`, `sentence_start`, or `sentence_end`.")
    lines.append("")

    lines.append("## Recommended Fix Order")
    lines.append("")
    lines.append("1. Use PDF TOC/bookmarks as the first section map where available, and fall back to font-size heading detection where no TOC exists.")
    lines.append("2. Extract pages into section blocks before chunking, allowing sections to continue across page boundaries while retaining page spans.")
    lines.append("3. Normalize PDF text into paragraphs by joining visual line wraps and preserving blank-line or heading breaks.")
    lines.append("4. Split paragraphs into sentences, then pack adjacent sentences into chunks under a token budget with small sentence-level overlap.")
    lines.append("5. Store richer metadata: `section_title`, `section_path`, `section_level`, `page_start`, `page_end`, `paragraph_index`, `sentence_start`, `sentence_end`, and `chunk_strategy_version`.")
    lines.append("6. Rebuild both Chroma and BM25 from the same source manifest, and keep one canonical vector DB path to avoid stale duplicate stores.")
    lines.append("")

    lines.append("## Aggregate Flags")
    lines.append("")
    lines.append(f"- {dict(all_flags)}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit current RAG chunk quality.")
    parser.add_argument("--db-path", default="factory-agent/factory_agent/rag/vector_db")
    parser.add_argument("--register", default="rag_sources/00_metadata_templates/source_register.json")
    parser.add_argument("--collection", default="emas_knowledge")
    parser.add_argument("--out", default="docs/qa/RAG_CHUNK_QUALITY_AUDIT_2026-05-24.md")
    parser.add_argument("--sample-limit", type=int, default=2)
    args = parser.parse_args()

    report = build_report(
        db_path=Path(args.db_path),
        register_path=Path(args.register),
        collection_name=args.collection,
        sample_limit=args.sample_limit,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
