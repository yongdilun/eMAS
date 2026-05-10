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

from factory_agent.rag.schemas import DocumentEntry, SourceRegister, Chunk

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IngestionEngine:
    CHUNK_SIZE = 700
    CHUNK_OVERLAP = 100
    
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
        
    def section_aware_split(self, text: str, doc_metadata: Dict[str, Any]) -> List[Chunk]:
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
                chunk_id = f"{doc_metadata['doc_id']}_c{len(final_chunks):04d}"
                
                final_chunks.append(Chunk(
                    chunk_id=chunk_id,
                    text=prefixed_text,
                    metadata={
                        **doc_metadata,
                        **section.metadata,
                        "section_title": section_title,
                        "section_path": section_path,
                        "chunk_index": i,
                        "ingested_at": datetime.utcnow().isoformat()
                    }
                ))
        return final_chunks

    def ingest_document(self, doc: DocumentEntry):
        """Processes a single document into Vector DB and updates local chunk list for BM25."""
        if not os.path.exists(doc.file_path):
            error_msg = f"File not found: {doc.file_path}"
            logger.warning(error_msg)
            with open("failed_ingestion.log", "a") as log:
                log.write(f"{datetime.utcnow().isoformat()} - {doc.doc_id} - {error_msg}\n")
            return False
            
        try:
            with open(doc.file_path, 'r', encoding='utf-8') as f:
                text = f.read()
                
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
            
            chunks = self.section_aware_split(text, doc.dict())
            
            # Prepare for ChromaDB
            ids = [c.chunk_id for c in chunks]
            texts = [c.text for c in chunks]
            metadatas = [c.metadata for c in chunks]
            
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
                log.write(f"{datetime.utcnow().isoformat()} - {doc.doc_id} - {str(e)}\n")
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
    engine = IngestionEngine()
    engine.run_full_ingestion("rag_sources/source_register.json")
