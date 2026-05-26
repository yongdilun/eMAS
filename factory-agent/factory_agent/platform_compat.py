from __future__ import annotations

import os
import platform
import sys


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def guard_blocking_windows_platform_queries() -> bool:
    """Avoid blocking Windows WMI during early dependency imports.

    Python 3.13 can ask WMI for platform details inside platform.machine().
    Some dependencies call that during import, so a wedged WMI provider can
    stop the server before uvicorn binds a port. Disabling platform._wmi keeps
    platform.win32_ver() on its stdlib fallback path.
    """

    if not sys.platform.startswith("win"):
        return False
    if _env_truthy("FACTORY_AGENT_ALLOW_WINDOWS_WMI_PLATFORM_QUERIES"):
        return False
    if getattr(platform, "_wmi", None) is None:
        return False
    platform._wmi = None
    return True
