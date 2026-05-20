from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from factory_agent.rag.document_registry import resolve_source_pdf_path


def build_documents_router(*, require_jwt: Callable[..., dict[str, Any]]) -> APIRouter:
    router = APIRouter()

    @router.get("/documents/{doc_id}/pdf")
    async def get_source_pdf(doc_id: str, _claims: dict[str, Any] = Depends(require_jwt)) -> FileResponse:
        pdf_path = resolve_source_pdf_path(doc_id)
        if pdf_path is None:
            raise HTTPException(status_code=404, detail="document not found")
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=pdf_path.name,
            content_disposition_type="inline",
        )

    return router
