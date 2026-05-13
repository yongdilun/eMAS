"""
Regenerate factory-agent tool definitions from the Go API OpenAPI spec.

Do not edit factory_agent/tools.md by hand — it is overwritten here and by
POST /admin/regenerate-tools (same pipeline as ToolRegistry.regenerate_from_openapi).

Prerequisites:
  - Prefer committed spec: emas/docs/swagger.json (run swag init / your backend swagger export).
  - Or a running API at OPENAPI_URL (default http://localhost:8080/swagger/doc.json).

Usage:
  python scripts/generate_tools.py              # DB + tools.md + id_patterns.json
  python scripts/generate_tools.py --no-db      # markdown + id patterns only
  python scripts/generate_tools.py --local      # use emas/docs/swagger.json (OPENAPI_LOCAL=1)

Env:
  OPENAPI_URL, OPENAPI_LOCAL, SKIP_DB
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from factory_agent.persistence.database import AsyncSessionLocal
from factory_agent.registry import default_id_patterns_path, default_tools_md_path
from factory_agent.registry.toolgen import (
    fetch_openapi_spec,
    render_tools_md,
    tools_from_openapi,
    write_id_pattern_catalog,
    write_tools_md_and_meta,
)

DEFAULT_OPENAPI_URL = "http://localhost:8080/swagger/doc.json"
OPENAPI_URL = os.environ.get("OPENAPI_URL", DEFAULT_OPENAPI_URL)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOCAL_SWAGGER_JSON_PATH = os.path.join(REPO_ROOT, "emas", "docs", "swagger.json")
TOOLS_MD_PATH = default_tools_md_path()
ID_PATTERNS_PATH = default_id_patterns_path()

SKIP_DB = ("--no-db" in sys.argv) or (os.environ.get("SKIP_DB", "").strip() == "1")
FORCE_LOCAL = ("--local" in sys.argv) or (os.environ.get("OPENAPI_LOCAL", "").strip() == "1")


async def generate() -> None:
    print(f"OpenAPI: {OPENAPI_URL}  (force_local={FORCE_LOCAL})")
    print(f"tools.md -> {TOOLS_MD_PATH}")
    print(f"id_patterns -> {ID_PATTERNS_PATH}")
    try:
        spec = fetch_openapi_spec(
            openapi_url=OPENAPI_URL,
            local_swagger_json_path=LOCAL_SWAGGER_JSON_PATH,
            force_local=FORCE_LOCAL,
        )
    except Exception as e:
        print(f"Failed to load OpenAPI spec: {e}")
        return

    tools = tools_from_openapi(spec)

    if SKIP_DB:
        print("Writing tools.md and id_patterns (no DB)...")
        with open(TOOLS_MD_PATH, "w", encoding="utf-8") as f:
            f.write(render_tools_md(tools))
        write_id_pattern_catalog(tools, path=ID_PATTERNS_PATH)
        print("Done (no DB).")
        return

    print("Saving tools to database + tools.md + id_patterns...")
    async with AsyncSessionLocal() as db_session:
        result = await write_tools_md_and_meta(
            db_session,
            tools=tools,
            tools_md_path=TOOLS_MD_PATH,
            id_patterns_path=ID_PATTERNS_PATH,
            replace_db=True,
        )
        print(f"Generated {result.tool_count} tools. tools.md hash={result.tools_md_hash}")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(generate())
