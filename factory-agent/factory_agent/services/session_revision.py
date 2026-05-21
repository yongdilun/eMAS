from __future__ import annotations

from typing import Any


def bump_session_revision(sess: Any) -> None:
    """Advance DB and response-document revisions for state-changing writes."""
    sess.version = (getattr(sess, "version", None) or 0) + 1
    sess.event_seq = (getattr(sess, "event_seq", None) or 0) + 1
