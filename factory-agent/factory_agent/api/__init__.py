"""HTTP API router construction."""

from __future__ import annotations

from typing import Any


def build_router(*args: Any, **kwargs: Any) -> Any:
    from .routes import build_router as _build_router

    return _build_router(*args, **kwargs)

__all__ = ["build_router"]
