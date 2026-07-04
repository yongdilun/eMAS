from types import SimpleNamespace

from factory_agent.schemas import PresentationResponse, ResponseDocument
from factory_agent.services import session_snapshot_service
from factory_agent.services.response_document_service import compose_response_document


def test_response_document_accepts_file_download_block():
    doc = ResponseDocument(
        id="rd-file-1",
        document_id="rd-file-1",
        revision=1,
        revision_source="test",
        state="completed",
        status="completed",
        blocks=[
            {
                "id": "file:report",
                "type": "file_download",
                "title": "PDF report ready",
                "filename": "machine-utilization-2026-07-03.pdf",
                "content_type": "application/pdf",
                "download_url": "http://testserver/api/v1/reports/machine-utilization",
                "view_url": "http://testserver/api/v1/reports/machine-utilization",
                "summary": "The report is ready.",
            }
        ],
    )

    block = doc.blocks[0]
    assert block.type == "file_download"
    assert block.content_type == "application/pdf"


def test_nested_file_download_result_is_detected():
    result = {
        "entity": "report",
        "status": "file_ready",
        "file_download": {
            "title": "PDF report ready",
            "filename": "machine-utilization-2026-07-03.pdf",
            "content_type": "application/pdf",
            "download_url": "http://testserver/api/v1/reports/machine-utilization",
            "view_url": "http://testserver/api/v1/reports/machine-utilization",
        },
    }

    file_download = session_snapshot_service._file_download_from_result(result)

    assert file_download is not None
    assert file_download["content_type"] == "application/pdf"
    assert file_download["download_url"].endswith("/api/v1/reports/machine-utilization")


def test_composed_response_document_renders_pdf_download_card_not_record_preview():
    file_download = {
        "title": "PDF report ready",
        "filename": "machine-utilization-2026-07-03.pdf",
        "content_type": "application/pdf",
        "download_url": "http://testserver/api/v1/reports/machine-utilization",
        "view_url": "http://testserver/api/v1/reports/machine-utilization",
        "summary": "machine-utilization-2026-07-03.pdf is ready to view or download.",
    }
    presentation = PresentationResponse(
        kind="answer",
        state="completed",
        operation_id="plan-report-1",
        summary=file_download["summary"],
        diagnostics={"reason": "file_download", "file_download": file_download},
    )

    doc = compose_response_document(
        session=SimpleNamespace(
            session_id="session-report-1",
            status="COMPLETED",
            current_intent="generate machine utilization report",
            event_seq=4,
        ),
        plan=None,
        steps=[],
        pending_approval=None,
        approvals=[],
        timeline=[],
        activity_steps=[],
        presentation=presentation,
        cursor=4,
    )

    block_types = [block.type for block in doc.blocks]
    assert "file_download" in block_types
    assert "record_preview" not in block_types
    assert doc.diagnostics["reason"] == "file_download"
    file_block = next(block for block in doc.blocks if block.type == "file_download")
    assert file_block.filename == "machine-utilization-2026-07-03.pdf"
