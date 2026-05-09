
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio

from factory_agent.registry.toolgen import fetch_openapi_spec, render_tools_md, tools_from_openapi, write_id_pattern_catalog, write_tools_md_and_meta
from factory_agent.persistence.database import AsyncSessionLocal

DEFAULT_OPENAPI_URL = 'http://localhost:8080/swagger/doc.json'
OPENAPI_URL = os.environ.get('OPENAPI_URL', DEFAULT_OPENAPI_URL)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOCAL_SWAGGER_JSON_PATH = os.path.join(REPO_ROOT, 'emas', 'docs', 'swagger.json')
TOOLS_MD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tools.md'))
ID_PATTERNS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'agent', 'generated', 'id_patterns.json'))

SKIP_DB = ('--no-db' in sys.argv) or (os.environ.get('SKIP_DB', '').strip() == '1')
FORCE_LOCAL = ('--local' in sys.argv) or (os.environ.get('OPENAPI_LOCAL', '').strip() == '1')

async def generate():
    print(f'Loading OpenAPI spec from {OPENAPI_URL} (force_local={FORCE_LOCAL})...')
    try:
        spec = fetch_openapi_spec(openapi_url=OPENAPI_URL, local_swagger_json_path=LOCAL_SWAGGER_JSON_PATH, force_local=FORCE_LOCAL)
    except Exception as e:
        print(f'Failed to load OpenAPI spec: {e}')
        return

    tools = tools_from_openapi(spec)

    if SKIP_DB:
        # Still generate tools.md, but do not write DB/meta.
        print(f'Generating {TOOLS_MD_PATH} (no DB)...')
        with open(TOOLS_MD_PATH, 'w', encoding='utf-8') as f:
            f.write(render_tools_md(tools))
        write_id_pattern_catalog(tools, path=ID_PATTERNS_PATH)
        print('Generation complete (no DB).')
        return

    print('Saving tools to database + generating tools.md...')
    async with AsyncSessionLocal() as db_session:
        result = await write_tools_md_and_meta(
            db_session,
            tools=tools,
            tools_md_path=TOOLS_MD_PATH,
            id_patterns_path=ID_PATTERNS_PATH,
            replace_db=True,
        )
        print(f'Generated {result.tool_count} tools. tools.md hash={result.tools_md_hash}')

    print('Generation complete!')

if __name__ == '__main__':
    asyncio.run(generate())



