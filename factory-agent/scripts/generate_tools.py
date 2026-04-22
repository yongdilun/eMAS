
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import json
import asyncio
from database import AsyncSessionLocal, Base
from models import Tool, generate_uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

DEFAULT_OPENAPI_URL = 'http://localhost:8080/swagger/doc.json'
OPENAPI_URL = os.environ.get('OPENAPI_URL', DEFAULT_OPENAPI_URL)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LOCAL_SWAGGER_JSON_PATH = os.path.join(REPO_ROOT, 'emas', 'docs', 'swagger.json')
TOOLS_MD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tools.md'))

SKIP_DB = ('--no-db' in sys.argv) or (os.environ.get('SKIP_DB', '').strip() == '1')
FORCE_LOCAL = ('--local' in sys.argv) or (os.environ.get('OPENAPI_LOCAL', '').strip() == '1')

def build_tool_markdown(tool: Tool) -> str:
    input_schema_str = json.dumps(tool.input_schema, indent=2)
    output_schema_str = json.dumps(tool.output_schema, indent=2) if tool.output_schema else '{}'
    
    return f'''## {tool.name}
**Description**: {tool.description}
**Method**: {tool.method}
**Endpoint**: {tool.endpoint}
**Requires Approval**: {str(tool.requires_approval).lower()}
**Side Effect Level**: {tool.side_effect_level}
**Read Only**: {str(tool.is_read_only).lower()}
**Input Schema**:
`json
{input_schema_str}
`
**Output Schema**:
`json
{output_schema_str}
`
---
'''

async def generate():
    # Fetch OpenAPI spec (HTTP first, then local swagger.json fallback)
    spec = None
    if FORCE_LOCAL:
        if not os.path.exists(LOCAL_SWAGGER_JSON_PATH):
            print(f'No local Swagger spec found at {LOCAL_SWAGGER_JSON_PATH}')
            return
        print(f'Reading local Swagger spec at {LOCAL_SWAGGER_JSON_PATH}...')
        try:
            with open(LOCAL_SWAGGER_JSON_PATH, 'r', encoding='utf-8') as f:
                spec = json.load(f)
        except Exception as e:
            print(f'Failed to read local Swagger spec: {e}')
            return
    else:
        print(f'Fetching OpenAPI spec from {OPENAPI_URL}...')
        try:
            response = requests.get(OPENAPI_URL, timeout=10)
            response.raise_for_status()
            spec = response.json()
        except Exception as e:
            print(f'Failed to fetch OpenAPI spec from HTTP: {e}')
            if os.path.exists(LOCAL_SWAGGER_JSON_PATH):
                print(f'Falling back to local Swagger spec at {LOCAL_SWAGGER_JSON_PATH}...')
                try:
                    with open(LOCAL_SWAGGER_JSON_PATH, 'r', encoding='utf-8') as f:
                        spec = json.load(f)
                except Exception as e2:
                    print(f'Failed to read local Swagger spec: {e2}')
                    return
            else:
                print(f'No local Swagger spec found at {LOCAL_SWAGGER_JSON_PATH}')
                return

    tools_to_save = []
    
    for path, path_item in spec.get('paths', {}).items():
        for method, operation in path_item.items():
            if method.lower() not in ['get', 'post', 'put', 'patch', 'delete']:
                continue
                
            tool_name = operation.get('operationId', f'{method}_{path.replace('/', '_')}').lower()
            description = operation.get('summary', '') or operation.get('description', '')
            
            # Simple schema extraction
            input_schema = {'type': 'object', 'properties': {}}
            for param in operation.get('parameters', []):
                input_schema['properties'][param['name']] = {'type': param.get('type', 'string')}
                
            # Capability tags mapping heuristics based on path
            capability_tags = []
            if 'machine' in path:
                capability_tags.append('machine')
            if 'job' in path:
                capability_tags.append('job')
            if 'inventory' in path:
                capability_tags.append('inventory')
                
            is_read_only = method.lower() == 'get'
            requires_approval = not is_read_only
            side_effect_level = 'NONE' if is_read_only else 'HIGH'

            tool = Tool(
                tool_id=generate_uuid(),
                name=tool_name,
                description=description,
                endpoint=path,
                method=method.upper(),
                input_schema=input_schema,
                output_schema={'type': 'object'},
                is_read_only=is_read_only,
                requires_approval=requires_approval,
                side_effect_level=side_effect_level,
                capability_tags=json.dumps(capability_tags)
            )
            tools_to_save.append(tool)

    if not SKIP_DB:
        # Save to database (best-effort; still generate tools.md even if DB fails)
        print('Saving tools to database...')
        try:
            async with AsyncSessionLocal() as db_session:
                # Clear old tools for simplicity in this script
                await db_session.execute(text('DELETE FROM tools'))
                db_session.add_all(tools_to_save)
                await db_session.commit()
        except Exception as e:
            print(f'Failed to save tools to database (continuing to tools.md): {e}')

    # Generate tools.md
    print(f'Generating {TOOLS_MD_PATH}...')
    with open(TOOLS_MD_PATH, 'w') as f:
        f.write('# Available Tools\n\n')
        for t in tools_to_save:
            f.write(build_tool_markdown(t))
            
    print('Generation complete!')

if __name__ == '__main__':
    asyncio.run(generate())

