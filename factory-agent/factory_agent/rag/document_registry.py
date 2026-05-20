from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

from factory_agent.rag.schemas import SourceRegister


SOURCE_REGISTER_ENV = "RAG_SOURCE_REGISTER_PATH"
DEFAULT_SOURCE_REGISTER = Path("rag_sources/00_metadata_templates/source_register.json")


def source_pdf_url(doc_id: str) -> str:
    safe_doc_id = quote(str(doc_id or "").strip(), safe="")
    return f"/documents/{safe_doc_id}/pdf"


def default_source_register_path() -> Path:
    candidates: list[Path] = []
    env_path = os.getenv(SOURCE_REGISTER_ENV)
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.cwd() / DEFAULT_SOURCE_REGISTER)
    candidates.append(Path(__file__).resolve().parents[3] / DEFAULT_SOURCE_REGISTER)
    candidates.append(Path(__file__).resolve().parents[2] / DEFAULT_SOURCE_REGISTER)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else DEFAULT_SOURCE_REGISTER


def resolve_source_pdf_path(doc_id: str, *, register_path: str | Path | None = None) -> Path | None:
    normalized_doc_id = str(doc_id or "").strip()
    if not normalized_doc_id:
        return None
    path = Path(register_path) if register_path is not None else default_source_register_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        register = SourceRegister(**data)
    except Exception:
        return None

    source_root = path.resolve().parent.parent
    for doc in register.documents:
        if doc.doc_id != normalized_doc_id:
            continue
        candidate = Path(doc.file_path)
        if not candidate.is_absolute():
            candidate = source_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(source_root.resolve())
        except ValueError:
            return None
        if resolved.suffix.lower() != ".pdf" or not resolved.exists():
            return None
        return resolved
    return None
