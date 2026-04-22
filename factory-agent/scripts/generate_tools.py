
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

OPENAPI_URL = 'http://localhost:8080/swagger/doc.json'
TOOLS_MD_PATH = 'tools.md'

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
    # Fetch OpenAPI spec
    print(f'Fetching OpenAPI spec from {OPENAPI_URL}...')
    try:
        response = requests.get(OPENAPI_URL)
        response.raise_for_status()
        spec = response.json()
    except Exception as e:
        print(f'Failed to fetch OpenAPI spec: {e}')
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

    # Save to database
    print('Saving tools to database...')
    async with AsyncSessionLocal() as db_session:
        # Clear old tools for simplicity in this script
        await db_session.execute(text('DELETE FROM tools'))
        db_session.add_all(tools_to_save)
        await db_session.commit()

    # Generate tools.md
    print(f'Generating {TOOLS_MD_PATH}...')
    with open(TOOLS_MD_PATH, 'w') as f:
        f.write('# Available Tools\n\n')
        for t in tools_to_save:
            f.write(build_tool_markdown(t))
            
    print('Generation complete!')

if __name__ == '__main__':
    asyncio.run(generate())

