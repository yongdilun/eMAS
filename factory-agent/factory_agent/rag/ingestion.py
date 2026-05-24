import os
import json
import re
import pickle
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import datetime

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
import fitz  # PyMuPDF

from factory_agent.rag.document_registry import source_pdf_url
from factory_agent.rag.schemas import DocumentEntry, SourceRegister, Chunk
from factory_agent.rag.source_metadata import snippet_from_text

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class _PdfSectionState:
    title: str
    path: str
    level: int


@dataclass
class _PdfParagraph:
    text: str
    page_start: int
    page_end: int
    paragraph_index: int
    section: _PdfSectionState


@dataclass
class _PdfSentenceUnit:
    text: str
    token_estimate: int
    page_start: int
    page_end: int
    paragraph_index: int
    sentence_index: int
    section: _PdfSectionState


def _find_text_range(text: str, needle: str, start: int = 0) -> tuple[int, int] | None:
    """Locate chunk text in extracted page text while tolerating whitespace normalization."""
    if not needle:
        return None

    exact_start = text.find(needle, start)
    if exact_start < 0 and start:
        exact_start = text.find(needle)
    if exact_start >= 0:
        return exact_start, exact_start + len(needle)

    tokens = [token for token in re.split(r"\s+", needle.strip()) if token]
    if not tokens:
        return None

    pattern = r"\s+".join(re.escape(token) for token in tokens)
    for lookup_start in (start, 0):
        match = re.search(pattern, text[lookup_start:])
        if match:
            return lookup_start + match.start(), lookup_start + match.end()
    return None


class IngestionEngine:
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200
    PDF_CHUNK_STRATEGY_VERSION = "pdf_struct_sentence_v1"
    PDF_TARGET_TOKENS = 450
    PDF_MAX_TOKENS = 650
    PDF_MIN_TOKENS = 80
    
    def __init__(self, db_path: str = "factory_agent/rag/vector_db", bm25_path: str = "factory_agent/rag/bm25_index.pkl"):
        self.db_path = db_path
        self.bm25_path = bm25_path
        
        # Initialize ChromaDB
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name="emas_knowledge",
            metadata={"hnsw:space": "cosine"}
        )
        
        # Initialize Embedding Function (using default SentenceTransformers)
        self.embed_fn = embedding_functions.DefaultEmbeddingFunction()
        
        # BM25 Index (loaded on demand or during full ingestion)
        self.bm25_index = None
        self.bm25_chunks = [] # Store Chunk objects for BM25

    def _estimate_tokens(self, text: str) -> int:
        """Deterministic token estimate for chunk budgeting without a tokenizer dependency."""
        word_count = len(re.findall(r"\b\w+(?:[-']\w+)?\b", text or ""))
        if word_count <= 0:
            return 0
        return max(1, int(round(word_count * 1.33)))

    def _normalize_line_key(self, line: str) -> str:
        return re.sub(r"\s+", " ", line or "").strip().lower()

    def _normalize_heading_key(self, line: str) -> str:
        normalized = self._normalize_line_key(line)
        normalized = normalized.replace("•", "")
        normalized = normalized.replace("’", "'")
        return re.sub(r"[^a-z0-9]+", "", normalized)

    def _is_pdf_noise_line(self, line: str, line_counts: Counter[str]) -> bool:
        stripped = re.sub(r"\s+", " ", line or "").strip()
        if not stripped:
            return False
        lowered = stripped.lower()
        if re.fullmatch(r"\d+|[ivxlcdm]+", lowered):
            return True
        if re.search(r"\bpage\s+\d+\s+of\s+\d+\b", lowered):
            return True
        if re.search(r"\.{4,}\s*\d+\s*$", stripped):
            return True
        if set(stripped) <= {"_", "-", "."}:
            return True
        repeat_count = line_counts.get(self._normalize_line_key(stripped), 0)
        if repeat_count >= 2 and len(stripped) <= 90:
            return True
        if repeat_count >= 2 and any(
            marker in lowered
            for marker in (
                "this publication is available free",
                "national institute of standards",
                "occupational safety and health administration",
            )
        ):
            return True
        return False

    def _clean_pdf_line(self, line: str) -> str:
        cleaned = re.sub(r"\s+", " ", line or "").strip()
        cleaned = cleaned.replace("\u2022", "-")
        return cleaned

    def _looks_like_pdf_heading(self, line: str) -> tuple[str, int] | None:
        text = self._clean_pdf_line(line)
        if not text or len(text) > 120:
            return None
        lowered = text.lower()
        if lowered in {"yes", "no", "yes no", "questions", "page", "contents"}:
            return None
        if any(
            marker in lowered
            for marker in (
                "secretary",
                "director",
                "department of commerce",
                "u.s. department",
            )
        ):
            return None
        if re.fullmatch(
            r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}",
            lowered,
        ):
            return None
        if text.endswith((".", "?", "!")):
            return None
        numbered = re.match(r"^(\d+(?:\.\d+)*\.?)\s+([A-Z].+)$", text)
        if numbered:
            rest = numbered.group(2)
            first_word = rest.split(maxsplit=1)[0].lower().strip(".,:;!?")
            if first_word in {
                "do",
                "does",
                "is",
                "are",
                "have",
                "has",
                "can",
                "could",
                "should",
                "what",
                "when",
                "how",
                "why",
                "who",
                "where",
            }:
                return None
            if len(rest) > 90:
                return None
            level = numbered.group(1).count(".") + 1
            return text, max(1, min(level, 4))
        if re.match(r"^(appendix\s+[A-Z0-9]+|[A-Z]\d{1,3}:)\b", text, re.IGNORECASE):
            return text, 1
        words = re.findall(r"[A-Za-z0-9]+", text)
        if not 1 <= len(words) <= 9:
            return None
        if "," in text:
            return None
        uppercase_ratio = sum(1 for char in text if char.isupper()) / max(1, sum(1 for char in text if char.isalpha()))
        title_case_words = sum(1 for word in words if word[:1].isupper() or word.isupper())
        if uppercase_ratio > 0.55 or title_case_words >= max(1, len(words) - 1):
            return text, 1 if len(words) <= 4 else 2
        return None

    def _pdf_toc_sections(self, pdf: fitz.Document) -> dict[int, list[_PdfSectionState]]:
        sections_by_page: dict[int, list[_PdfSectionState]] = defaultdict(list)
        stack: list[str] = []
        try:
            toc = pdf.get_toc(simple=True)
        except Exception:
            toc = []
        for level, title, page in toc:
            if page < 1:
                continue
            clean_title = self._clean_pdf_line(str(title))
            if not clean_title or clean_title.lower() == "structure bookmarks":
                continue
            if level <= 0:
                level = 1
            stack = stack[: level - 1]
            stack.append(clean_title)
            sections_by_page[int(page)].append(
                _PdfSectionState(
                    title=clean_title,
                    path=" > ".join(stack),
                    level=int(level),
                )
            )
        return sections_by_page

    def _pdf_toc_maps(
        self,
        pdf: fitz.Document,
    ) -> tuple[dict[int, list[_PdfSectionState]], dict[str, _PdfSectionState]]:
        sections_by_page = self._pdf_toc_sections(pdf)
        sections_by_title: dict[str, _PdfSectionState] = {}
        for sections in sections_by_page.values():
            for section in sections:
                sections_by_title.setdefault(self._normalize_heading_key(section.title), section)
        return sections_by_page, sections_by_title

    def _append_pdf_line(
        self,
        current_parts: list[str],
        current_page_end: int,
        line: str,
        page_number: int,
    ) -> tuple[list[str], int]:
        if current_parts and current_parts[-1].endswith("-") and line[:1].islower():
            current_parts[-1] = current_parts[-1][:-1] + line
        else:
            current_parts.append(line)
        return current_parts, page_number

    def _pdf_paragraphs(
        self,
        pdf: fitz.Document,
    ) -> tuple[list[_PdfParagraph], dict[int, str], dict[int, str]]:
        page_texts: dict[int, str] = {}
        page_labels: dict[int, str] = {}
        page_lines: dict[int, list[str]] = {}
        all_lines: list[str] = []

        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
            page_text = page.get_text("text")
            page_texts[page_number] = page_text
            get_page_label = getattr(page, "get_label", None)
            page_label = get_page_label() if callable(get_page_label) else str(page_number)
            page_labels[page_number] = page_label or str(page_number)
            lines = [line for line in page_text.splitlines()]
            page_lines[page_number] = lines
            all_lines.extend(self._clean_pdf_line(line) for line in lines if self._clean_pdf_line(line))

        line_counts = Counter(self._normalize_line_key(line) for line in all_lines)
        toc_sections, toc_sections_by_title = self._pdf_toc_maps(pdf)
        paragraphs: list[_PdfParagraph] = []
        current_section = _PdfSectionState(title="General", path="General", level=0)
        current_parts: list[str] = []
        current_page_start = 1
        current_page_end = 1

        def flush_paragraph() -> None:
            nonlocal current_parts, current_page_start, current_page_end
            text = re.sub(r"\s+", " ", " ".join(current_parts)).strip()
            if text:
                paragraphs.append(
                    _PdfParagraph(
                        text=text,
                        page_start=current_page_start,
                        page_end=current_page_end,
                        paragraph_index=len(paragraphs),
                        section=current_section,
                    )
                )
            current_parts = []
            current_page_start = current_page_end

        for page_number in sorted(page_lines):
            for section in toc_sections.get(page_number, []):
                if current_parts:
                    flush_paragraph()
                current_section = section

            line_index = 0
            lines = page_lines[page_number]
            while line_index < len(lines):
                line = self._clean_pdf_line(lines[line_index])
                line_index += 1
                if not line:
                    if current_parts:
                        flush_paragraph()
                    continue
                if self._is_pdf_noise_line(line, line_counts):
                    continue

                toc_heading = toc_sections_by_title.get(self._normalize_heading_key(line))
                if not toc_heading and not line.endswith((".", "?", "!")):
                    lookahead_parts = [line]
                    probe_index = line_index
                    while probe_index < len(lines) and len(lookahead_parts) < 3:
                        probe = self._clean_pdf_line(lines[probe_index])
                        if not probe or self._is_pdf_noise_line(probe, line_counts):
                            break
                        lookahead_parts.append(probe)
                        combined = " ".join(lookahead_parts)
                        toc_heading = toc_sections_by_title.get(self._normalize_heading_key(combined))
                        if toc_heading:
                            line = combined
                            line_index = probe_index + 1
                            break
                        if probe.endswith((".", "?", "!")):
                            break
                        probe_index += 1
                if toc_heading:
                    if current_parts:
                        flush_paragraph()
                    path_parts = toc_heading.path.split(" > ")
                    if path_parts:
                        path_parts[-1] = line
                    current_section = _PdfSectionState(
                        title=line,
                        path=" > ".join(path_parts) if path_parts else line,
                        level=toc_heading.level,
                    )
                    continue

                heading = self._looks_like_pdf_heading(line)
                if heading:
                    if current_parts:
                        flush_paragraph()
                    title, level = heading
                    current_section = _PdfSectionState(
                        title=title,
                        path=title,
                        level=level,
                    )
                    continue

                starts_list_item = bool(re.match(r"^([-*]|\(?\d+[.)])\s+", line))
                if starts_list_item and current_parts:
                    flush_paragraph()

                if not current_parts:
                    current_page_start = page_number
                current_parts, current_page_end = self._append_pdf_line(
                    current_parts,
                    current_page_end,
                    line,
                    page_number,
                )

        if current_parts:
            flush_paragraph()

        return paragraphs, page_texts, page_labels

    def _split_pdf_paragraph_sentences(self, paragraph: str) -> list[str]:
        text = re.sub(r"\s+", " ", paragraph or "").strip()
        if not text:
            return []
        if re.match(r"^([-*]|\(?\d+[.)])\s+", text):
            return [text]
        parts = re.split(r"(?<=[.!?])\s+(?=[\"'(]?[A-Z0-9])", text)
        return [part.strip() for part in parts if part.strip()]

    def _pdf_sentence_units(self, paragraphs: list[_PdfParagraph]) -> list[_PdfSentenceUnit]:
        units: list[_PdfSentenceUnit] = []
        for paragraph in paragraphs:
            for sentence in self._split_pdf_paragraph_sentences(paragraph.text):
                units.append(
                    _PdfSentenceUnit(
                        text=sentence,
                        token_estimate=self._estimate_tokens(sentence),
                        page_start=paragraph.page_start,
                        page_end=paragraph.page_end,
                        paragraph_index=paragraph.paragraph_index,
                        sentence_index=len(units),
                        section=paragraph.section,
                    )
                )
        return units

    def _split_oversize_sentence(self, unit: _PdfSentenceUnit) -> list[_PdfSentenceUnit]:
        words = unit.text.split()
        max_words = max(1, int(self.PDF_MAX_TOKENS / 1.33))
        pieces = []
        for start in range(0, len(words), max_words):
            piece_text = " ".join(words[start : start + max_words]).strip()
            if piece_text and start + max_words < len(words) and piece_text[-1] not in ".?!":
                piece_text = f"{piece_text}"
            pieces.append(
                _PdfSentenceUnit(
                    text=piece_text,
                    token_estimate=self._estimate_tokens(piece_text),
                    page_start=unit.page_start,
                    page_end=unit.page_end,
                    paragraph_index=unit.paragraph_index,
                    sentence_index=unit.sentence_index,
                    section=unit.section,
                )
            )
        return pieces

    def _make_pdf_chunk(
        self,
        units: list[_PdfSentenceUnit],
        doc_metadata: Dict[str, Any],
        chunk_index: int,
        split_reason: str,
        page_texts: dict[int, str],
        page_labels: dict[int, str],
    ) -> Chunk:
        section = units[0].section
        body = " ".join(unit.text for unit in units).strip()
        prefixed_text = f"[Section: {section.title}] {body}"
        chunk_id = f"{doc_metadata['doc_id']}_c{chunk_index:04d}"
        page_start = min(unit.page_start for unit in units)
        page_end = max(unit.page_end for unit in units)
        paragraph_start = min(unit.paragraph_index for unit in units)
        paragraph_end = max(unit.paragraph_index for unit in units)
        sentence_start = min(unit.sentence_index for unit in units)
        sentence_end = max(unit.sentence_index for unit in units)
        token_estimate = self._estimate_tokens(body)
        text_search = snippet_from_text(body, limit=240)

        chunk_metadata: dict[str, Any] = {
            **doc_metadata,
            "source_id": f"{doc_metadata['doc_id']}#{chunk_id}",
            "chunk_id": chunk_id,
            "snippet": snippet_from_text(prefixed_text),
            "section_title": section.title,
            "section_path": section.path,
            "section_level": section.level,
            "chunk_index": chunk_index,
            "ingested_at": datetime.now().isoformat(),
            "pdf_url": source_pdf_url(doc_metadata["doc_id"]),
            "source_format": "pdf",
            "chunk_strategy_version": self.PDF_CHUNK_STRATEGY_VERSION,
            "page": page_start,
            "page_index": page_start - 1,
            "page_label": page_labels.get(page_start, str(page_start)),
            "page_start": page_start,
            "page_end": page_end,
            "page_labels": [page_labels.get(page, str(page)) for page in range(page_start, page_end + 1)],
            "paragraph_start": paragraph_start,
            "paragraph_end": paragraph_end,
            "sentence_start": sentence_start,
            "sentence_end": sentence_end,
            "split_reason": split_reason,
            "chunk_token_estimate": token_estimate,
            "text_search": text_search,
        }

        first_page_text = page_texts.get(page_start, "")
        lookup_needle = units[0].text if units else body
        text_range = _find_text_range(first_page_text, lookup_needle)
        if text_range is not None:
            chunk_metadata["char_range"] = [text_range[0], text_range[1]]

        return Chunk(chunk_id=chunk_id, text=prefixed_text, metadata=chunk_metadata)

    def pdf_structure_aware_split(self, pdf: fitz.Document, doc_metadata: Dict[str, Any]) -> list[Chunk]:
        paragraphs, page_texts, page_labels = self._pdf_paragraphs(pdf)
        units = self._pdf_sentence_units(paragraphs)
        chunks: list[Chunk] = []
        current: list[_PdfSentenceUnit] = []
        current_tokens = 0
        current_section_key: tuple[str, str] | None = None

        def flush(split_reason: str) -> None:
            nonlocal current, current_tokens, current_section_key
            if not current:
                return
            chunks.append(
                self._make_pdf_chunk(
                    current,
                    doc_metadata,
                    len(chunks),
                    split_reason,
                    page_texts,
                    page_labels,
                )
            )
            current = []
            current_tokens = 0
            current_section_key = None

        for unit in units:
            section_key = (unit.section.path, unit.section.title)
            if current and current_section_key != section_key:
                flush("section_boundary")

            if unit.token_estimate > self.PDF_MAX_TOKENS:
                flush("oversize_sentence")
                for piece in self._split_oversize_sentence(unit):
                    chunks.append(
                        self._make_pdf_chunk(
                            [piece],
                            doc_metadata,
                            len(chunks),
                            "oversize_sentence",
                            page_texts,
                            page_labels,
                        )
                    )
                continue

            if current and current_tokens + unit.token_estimate > self.PDF_MAX_TOKENS:
                flush("max_token_budget")

            current.append(unit)
            current_tokens += unit.token_estimate
            current_section_key = section_key

            if current_tokens >= self.PDF_TARGET_TOKENS:
                flush("target_token_budget")

        flush("document_end")
        return chunks
        
    def section_aware_split(
        self,
        text: str,
        doc_metadata: Dict[str, Any],
        *,
        chunk_start_index: int = 0,
        preserve_char_range: bool = False,
    ) -> List[Chunk]:
        """
        Splits text by Markdown headers, then recursively splits sections.
        Prefixes each chunk with its section context.
        """
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ]
        
        markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        sections = markdown_splitter.split_text(text)
        
        final_chunks = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.CHUNK_SIZE,
            chunk_overlap=self.CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        search_cursor = 0
        
        for section in sections:
            # Determine section title and path
            h3 = section.metadata.get("Header 3")
            h2 = section.metadata.get("Header 2")
            h1 = section.metadata.get("Header 1")
            
            section_title = h3 or h2 or h1 or "General"
            path_parts = [v for k, v in section.metadata.items() if k.startswith("Header")]
            section_path = " > ".join(path_parts) if path_parts else section_title
            
            # Split the section content
            sub_chunks = text_splitter.split_text(section.page_content)
            
            for i, sub_text in enumerate(sub_chunks):
                prefixed_text = f"[Section: {section_title}] {sub_text}"
                chunk_index = chunk_start_index + len(final_chunks)
                chunk_id = f"{doc_metadata['doc_id']}_c{chunk_index:04d}"
                snippet = snippet_from_text(prefixed_text)
                chunk_metadata = {
                    **doc_metadata,
                    **section.metadata,
                    "source_id": f"{doc_metadata['doc_id']}#{chunk_id}",
                    "chunk_id": chunk_id,
                    "snippet": snippet,
                    "section_title": section_title,
                    "section_path": section_path,
                    "chunk_index": chunk_index,
                    "ingested_at": datetime.now().isoformat()
                }
                if preserve_char_range:
                    needle = sub_text.strip()
                    if needle:
                        chunk_metadata["text_search"] = snippet_from_text(needle, limit=240)
                    lookup_start = max(0, search_cursor - self.CHUNK_OVERLAP - 50)
                    text_range = _find_text_range(text, needle, lookup_start)
                    if text_range is not None:
                        char_start, char_end = text_range
                        chunk_metadata["char_range"] = [char_start, char_end]
                        search_cursor = char_start + 1
                
                final_chunks.append(Chunk(
                    chunk_id=chunk_id,
                    text=prefixed_text,
                    metadata=chunk_metadata,
                ))
        return final_chunks

    def ingest_document(self, doc: DocumentEntry):
        """Processes a single document into Vector DB and updates local chunk list for BM25."""
        if not os.path.exists(doc.file_path):
            error_msg = f"File not found: {doc.file_path}"
            logger.warning(error_msg)
            with open("failed_ingestion.log", "a") as log:
                log.write(f"{datetime.now().isoformat()} - {doc.doc_id} - {error_msg}\n")
            return False
            
        try:
            file_ext = os.path.splitext(doc.file_path)[1].lower()
            doc_metadata = doc.model_dump()
            doc_metadata.pop("file_path", None)
            
            if file_ext == ".pdf":
                logger.info(f"Extracting text from PDF: {doc.doc_id}")
                with fitz.open(doc.file_path) as pdf:
                    chunks = self.pdf_structure_aware_split(pdf, doc_metadata)
            else:
                with open(doc.file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                chunks = self.section_aware_split(text, doc_metadata)
            
            if not chunks:
                logger.warning(f"No text extracted from {doc.doc_id}")
                return False
                
            # Check version and skip if unchanged
            existing = self.collection.get(where={"doc_id": doc.doc_id}, limit=1)
            if existing and existing['ids']:
                stored_version = existing['metadatas'][0].get('version')
                stored_strategy = existing['metadatas'][0].get("chunk_strategy_version")
                current_strategy = chunks[0].metadata.get("chunk_strategy_version")
                strategy_unchanged = not current_strategy or stored_strategy == current_strategy
                if stored_version == doc.version and strategy_unchanged:
                    logger.info(f"Skipping {doc.doc_id} (version {doc.version} already ingested)")
                    return True
                else:
                    logger.info(
                        "Updating %s from version=%s strategy=%s to version=%s strategy=%s",
                        doc.doc_id,
                        stored_version,
                        stored_strategy,
                        doc.version,
                        current_strategy,
                    )
                    self.collection.delete(where={"doc_id": doc.doc_id})
            
            # Prepare for ChromaDB
            ids = [c.chunk_id for c in chunks]
            texts = [c.text for c in chunks]
            metadatas = []
            for c in chunks:
                # ChromaDB only supports str, int, float, bool. 
                # Serialize lists/dicts to JSON strings.
                clean_meta = {}
                for k, v in c.metadata.items():
                    if isinstance(v, (list, dict)):
                        clean_meta[k] = json.dumps(v)
                    else:
                        clean_meta[k] = v
                metadatas.append(clean_meta)
            
            # ChromaDB upsert
            self.collection.upsert(
                ids=ids,
                documents=texts,
                metadatas=metadatas
            )
            
            # Add to local list for BM25 (will be indexed at the end)
            self.bm25_chunks.extend(chunks)
            
            logger.info(f"Successfully ingested {doc.doc_id} ({len(chunks)} chunks)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to ingest {doc.doc_id}: {str(e)}")
            with open("failed_ingestion.log", "a") as log:
                log.write(f"{datetime.now().isoformat()} - {doc.doc_id} - {str(e)}\n")
            return False

    def build_bm25_index(self):
        """Builds and serializes the BM25 index from all ingested chunks."""
        if not self.bm25_chunks:
            # Try to load existing chunks from Vector DB if local list is empty
            all_stored = self.collection.get()
            if not all_stored['ids']:
                logger.warning("No chunks found to build BM25 index.")
                return
            
            self.bm25_chunks = [
                Chunk(chunk_id=id, text=text, metadata=meta)
                for id, text, meta in zip(all_stored['ids'], all_stored['documents'], all_stored['metadatas'])
            ]
            
        # Tokenize for BM25
        tokenized_corpus = [c.text.lower().split() for c in self.bm25_chunks]
        self.bm25_index = BM25Okapi(tokenized_corpus)
        
        # Save to disk
        data = {
            "index": self.bm25_index,
            "chunks": self.bm25_chunks
        }
        os.makedirs(os.path.dirname(self.bm25_path), exist_ok=True)
        with open(self.bm25_path, "wb") as f:
            pickle.dump(data, f)
            
        logger.info(f"BM25 index built and saved to {self.bm25_path}")

    def run_full_ingestion(self, register_path: str):
        """Runs the complete ingestion pipeline from a source register."""
        if not os.path.exists(register_path):
            logger.error(f"Source register not found: {register_path}")
            return
            
        register_dir = os.path.dirname(os.path.abspath(register_path))
            
        with open(register_path, 'r') as f:
            data = json.load(f)
            register = SourceRegister(**data)
            
        success_count = 0
        for doc in register.documents:
            # Resolve file_path relative to register_path if it's not absolute
            if not os.path.isabs(doc.file_path):
                original_path = doc.file_path
                doc.file_path = os.path.normpath(os.path.join(register_dir, "..", original_path))
            
            if self.ingest_document(doc):
                success_count += 1
                
        if success_count > 0:
            self.build_bm25_index()
            
        logger.info(f"Full ingestion complete. {success_count}/{len(register.documents)} documents successful.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest documents into the RAG system.")
    parser.add_argument("--register", type=str, default="rag_sources/00_metadata_templates/source_register.json", help="Path to the source register JSON file.")
    args = parser.parse_args()
    
    engine = IngestionEngine()
    engine.run_full_ingestion(args.register)
