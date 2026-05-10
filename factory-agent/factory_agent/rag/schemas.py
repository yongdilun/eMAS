from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class DocumentEntry(BaseModel):
    doc_id: str
    title: str
    file_path: str
    source_type: str
    organization: str
    domain: str
    subdomain: str
    authority_level: str
    use_for: List[str]
    do_not_use_for: List[str]
    related_entities: List[str]
    risk_level: str
    license: str
    version: str
    retrieved_date: str
    notes: Optional[str] = None

class SourceRegister(BaseModel):
    documents: List[DocumentEntry]

class Chunk(BaseModel):
    chunk_id: str
    text: str
    metadata: Dict[str, Any]

class ScoredChunk(BaseModel):
    chunk: Chunk
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None
    fusion_score: Optional[float] = None
    boosted_score: Optional[float] = None

class SourceCitation(BaseModel):
    source_number: int
    doc_id: str
    title: str
    organization: str
    authority_level: str
    domain: str
    version: str
    license: str
    retrieved_date: str

class AnswerResult(BaseModel):
    answer: str
    sources: List[SourceCitation]
    safety_warning: bool
    route_used: str

class AgentResponse(BaseModel):
    answer: str
    sources: List[SourceCitation]
    route: str
    safety_warning: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
