from __future__ import annotations

from typing import Any

USER_CANCELLED_REASON = "cancelled_by_user"
USER_CANCELLED_MESSAGE = "Cancelled by user message"
USER_CANCELLED_TIMELINE_CONTENT = "Run cancelled by operator request."
USER_CANCELLED_ACTIVITY_LABEL = "Run cancelled"
USER_CANCELLED_ACTIVITY_DETAIL = "Cancelled by operator request"


def session_error_indicates_user_cancelled(error: Any) -> bool:
    return str(error or "").strip().lower().startswith("cancelled")


def is_user_cancelled_session(session: Any) -> bool:
    return (
        str(getattr(session, "status", "") or "").upper() == "IDLE"
        and session_error_indicates_user_cancelled(getattr(session, "error", None))
    )


def timeline_details_indicate_user_cancelled(details: Any) -> bool:
    if not isinstance(details, dict):
        return False
    return str(details.get("reason") or "").lower() == USER_CANCELLED_REASON
