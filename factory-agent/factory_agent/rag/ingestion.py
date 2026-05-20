import os
import json
import re
import pickle
import logging
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
                chunks: list[Chunk] = []
                with fitz.open(doc.file_path) as pdf:
                    for page_index, page in enumerate(pdf):
                        page_text = page.get_text("text")
                        if not page_text.strip():
                            continue
                        page_number = page_index + 1
                        get_page_label = getattr(page, "get_label", None)
                        page_label = get_page_label() if callable(get_page_label) else str(page_number)
                        page_metadata = {
                            **doc_metadata,
                            "page": page_number,
                            "page_index": page_index,
                            "page_label": page_label or str(page_number),
                            "pdf_url": source_pdf_url(doc.doc_id),
                            "source_format": "pdf",
                        }
                        chunks.extend(
                            self.section_aware_split(
                                page_text,
                                page_metadata,
                                chunk_start_index=len(chunks),
                                preserve_char_range=True,
                            )
                        )
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
                if stored_version == doc.version:
                    logger.info(f"Skipping {doc.doc_id} (version {doc.version} already ingested)")
                    return True
                else:
                    logger.info(f"Updating {doc.doc_id} from {stored_version} to {doc.version}")
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
