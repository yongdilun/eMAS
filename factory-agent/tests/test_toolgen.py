from factory_agent.registry.toolgen import tools_from_openapi
import json
from pathlib import Path


def test_tools_from_openapi_flattens_swagger2_body_parameter_schema():
    spec = {
        "swagger": "2.0",
        "definitions": {
            "CreateMachineRequest": {
                "type": "object",
                "properties": {
                    "machine_name": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["machine_name"],
            }
        },
        "paths": {
            "/machines": {
                "post": {
                    "operationId": "post__machines",
                    "summary": "Create a machine",
                    "parameters": [
                        {
                            "name": "request",
                            "in": "body",
                            "required": True,
                            "schema": {"$ref": "#/definitions/CreateMachineRequest"},
                        }
                    ],
                }
            }
        },
    }

    tools = tools_from_openapi(spec)
    assert len(tools) == 1
    schema = tools[0].input_schema
    assert set(schema["properties"].keys()) == {"machine_name", "status"}
    assert schema["required"] == ["machine_name"]
    assert schema["x-body-fields"] == ["machine_name", "status"]
    assert schema["x-body-required"] == ["machine_name"]
    assert schema["x-param-sources"]["machine_name"] == "body"


def test_tools_from_openapi_infers_request_body_schema():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/machines/{id}": {
                "patch": {
                    "operationId": "patch_machine",
                    "summary": "Update machine",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"status": {"type": "string"}, "reason": {"type": "string"}},
                                    "required": ["status"],
                                }
                            }
                        },
                    },
                }
            }
        },
    }

    tools = tools_from_openapi(spec)
    assert len(tools) == 1
    schema = tools[0].input_schema
    assert schema["type"] == "object"
    assert set(schema["properties"].keys()) == {"id", "status", "reason"}
    assert set(schema["required"]) == {"id", "status"}
    assert schema["x-path-params"] == ["id"]
    assert schema["x-body-fields"] == ["reason", "status"]
    assert schema["x-body-required"] == ["status"]
    assert schema["x-param-sources"]["status"] == "body"


def test_tools_from_openapi_resolves_body_schema_refs():
    spec = {
        "openapi": "3.0.0",
        "components": {
            "schemas": {
                "CreateJobRequest": {
                    "type": "object",
                    "properties": {"machine_id": {"type": "integer"}, "priority": {"type": "string"}},
                    "required": ["machine_id"],
                }
            }
        },
        "paths": {
            "/jobs": {
                "post": {
                    "operationId": "create_job",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/CreateJobRequest"}}
                        },
                    },
                }
            }
        },
    }

    tools = tools_from_openapi(spec)
    schema = tools[0].input_schema
    assert "machine_id" in schema["properties"]
    assert "priority" in schema["properties"]
    assert "machine_id" in schema["required"]


def test_tools_from_openapi_marks_path_params_required_even_if_flag_missing():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/machines/{id}": {
                "get": {
                    "operationId": "get_machine",
                    "summary": "Get machine",
                    "parameters": [
                        {"name": "id", "in": "path", "schema": {"type": "string"}}
                    ],
                }
            }
        },
    }

    tools = tools_from_openapi(spec)
    assert len(tools) == 1
    schema = tools[0].input_schema
    assert schema["properties"]["id"]["type"] == "string"
    assert "id" in schema["required"]


def test_tools_from_openapi_generates_rich_capability_tags():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/chatbot/approval/pending": {
                "get": {
                    "operationId": "get_chatbot_approval_pending",
                    "summary": "List pending approvals",
                }
            }
        },
    }

    tools = tools_from_openapi(spec)
    assert len(tools) == 1
    tags = set(__import__("json").loads(tools[0].capability_tags))
    assert {"approval", "pending", "list"} <= tags


def test_tools_from_openapi_derives_capability_tags_from_arbitrary_api_shape():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/customers/{id}/invoices": {
                "get": {
                    "operationId": "list_customer_invoices",
                    "summary": "List customer invoices",
                    "tags": ["Billing"],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                }
            }
        },
    }

    tools = tools_from_openapi(spec)
    tags = set(__import__("json").loads(tools[0].capability_tags))
    assert {"customer", "invoice", "billing", "list"} <= tags


def test_tools_from_openapi_merges_path_level_parameters():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/machines/{id}/capabilities": {
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "post": {
                    "operationId": "assign_capability",
                    "summary": "Assign a capability",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"capability": {"type": "string"}},
                                    "required": ["capability"],
                                }
                            }
                        },
                    },
                },
            }
        },
    }

    tools = tools_from_openapi(spec)
    assert len(tools) == 1
    schema = tools[0].input_schema
    assert set(schema["properties"].keys()) == {"id", "capability"}
    assert set(schema["required"]) == {"id", "capability"}
    assert schema["x-path-params"] == ["id"]


def test_tools_from_openapi_preserves_enum_metadata_for_query_and_body_fields():
    spec = {
        "swagger": "2.0",
        "definitions": {
            "UpdateMachineRequest": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["idle", "running", "maintenance", "offline"],
                    }
                },
            }
        },
        "paths": {
            "/machines": {
                "get": {
                    "operationId": "get__machines",
                    "parameters": [
                        {
                            "name": "status",
                            "in": "query",
                            "type": "string",
                            "enum": ["idle", "running", "maintenance", "offline"],
                        }
                    ],
                }
            },
            "/machines/{id}": {
                "put": {
                    "operationId": "put__machines_{id}",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "type": "string"},
                        {
                            "name": "request",
                            "in": "body",
                            "required": True,
                            "schema": {"$ref": "#/definitions/UpdateMachineRequest"},
                        },
                    ],
                }
            },
        },
    }

    tools = {tool.name: tool for tool in tools_from_openapi(spec)}
    assert tools["get__machines"].input_schema["properties"]["status"]["enum"] == [
        "idle",
        "running",
        "maintenance",
        "offline",
    ]
    assert tools["put__machines_{id}"].input_schema["properties"]["status"]["enum"] == [
        "idle",
        "running",
        "maintenance",
        "offline",
    ]


def test_tools_from_openapi_preserves_response_schema_and_roles():
    spec = {
        "swagger": "2.0",
        "definitions": {
            "Response": {"type": "object", "properties": {"success": {"type": "boolean"}}},
            "Job": {"type": "object", "properties": {"job_id": {"type": "string"}}},
        },
        "paths": {
            "/jobs": {
                "get": {
                    "operationId": "get__jobs",
                    "responses": {
                        "200": {
                            "schema": {
                                "allOf": [
                                    {"$ref": "#/definitions/Response"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "type": "array",
                                                "items": {"$ref": "#/definitions/Job"},
                                            }
                                        },
                                    },
                                ]
                            }
                        }
                    },
                },
                "post": {
                    "operationId": "post__jobs",
                    "x-ai-allowed-roles": ["manager", "admin"],
                    "responses": {"201": {"schema": {"$ref": "#/definitions/Job"}}},
                },
            }
        },
    }

    tools = {tool.name: tool for tool in tools_from_openapi(spec)}
    assert tools["get__jobs"].output_schema["properties"]["data"]["items"]["properties"]["job_id"]["type"] == "string"
    assert tools["get__jobs"].input_schema["x-allowed-roles"] == ["viewer", "planner", "manager", "admin"]
    assert tools["post__jobs"].input_schema["x-allowed-roles"] == ["manager", "admin"]


def test_tools_from_openapi_records_pdf_response_content_type():
    spec = {
        "swagger": "2.0",
        "produces": ["application/json"],
        "paths": {
            "/reports/production-output": {
                "get": {
                    "operationId": "get__reports_production-output",
                    "summary": "Production output PDF",
                    "produces": ["application/pdf"],
                    "responses": {
                        "200": {"description": "PDF file", "schema": {"type": "file"}},
                        "400": {"description": "JSON error"},
                    },
                }
            }
        },
    }

    tool = tools_from_openapi(spec)[0]

    assert tool.is_read_only is True
    assert tool.requires_approval is False
    assert "application/pdf" in tool.output_schema["x-response-content-types"]


def test_tools_from_openapi_preserves_ai_contract_metadata_and_status_token():
    spec = {
        "swagger": "2.0",
        "definitions": {
            "Response": {"type": "object", "properties": {"success": {"type": "boolean"}}},
            "Machine": {
                "type": "object",
                "properties": {
                    "machine_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["idle", "running"]},
                },
            },
        },
        "paths": {
            "/machines/{id}": {
                "get": {
                    "summary": "Get machine status",
                    "x-ai-entity": "machine",
                    "x-ai-action": "read",
                    "x-ai-response-contracts": ["entity_status_v1"],
                    "x-ai-capability-tags": ["entity_status", "status", "read", "lookup"],
                    "x-ai-primary-status-field": "status",
                    "x-ai-status-fields": ["status", "machine_id"],
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "type": "string",
                            "pattern": "^M-[A-Za-z0-9-]+$",
                            "x-ai-entity": "machine",
                            "x-ai-id-field": "machine_id",
                            "x-ai-id-prefix": "M-",
                        }
                    ],
                    "responses": {
                        "200": {
                            "schema": {
                                "allOf": [
                                    {"$ref": "#/definitions/Response"},
                                    {
                                        "type": "object",
                                        "properties": {"data": {"$ref": "#/definitions/Machine"}},
                                    },
                                ]
                            }
                        }
                    },
                }
            }
        },
    }

    tool = tools_from_openapi(spec)[0]
    tags = set(json.loads(tool.capability_tags))

    assert tool.input_schema["x-ai-response-contracts"] == ["entity_status_v1"]
    assert tool.input_schema["x-ai-primary-status-field"] == "status"
    assert tool.input_schema["properties"]["id"]["x-ai-id-field"] == "machine_id"
    assert tool.input_schema["properties"]["id"]["pattern"] == "^M-[A-Za-z0-9-]+$"
    assert {"machine", "entity", "status", "read", "lookup"} <= tags
    assert "statu" not in tags


def test_tools_from_openapi_preserves_business_change_and_no_match_metadata():
    spec = {
        "swagger": "2.0",
        "paths": {
            "/jobs": {
                "get": {
                    "summary": "List jobs",
                    "x-ai-entity": "job",
                    "x-ai-action": "read",
                    "x-ai-response-contracts": ["entity_agnostic_no_matching_records_v1"],
                    "x-ai-no-match-contract": {
                        "contract": "entity_agnostic_no_matching_records_v1",
                        "data_path": "data",
                        "approval_required": False,
                    },
                    "x-ai-capability-tags": ["job", "list", "no_match", "no_matching_records"],
                    "responses": {"200": {"schema": {"type": "object", "properties": {"data": {"type": "array"}}}}},
                }
            },
            "/jobs/{id}": {
                "put": {
                    "summary": "Update job",
                    "x-ai-entity": "job",
                    "x-ai-action": "update",
                    "x-ai-response-contracts": ["business_change_v1"],
                    "x-ai-business-change-fields": {
                        "contract": "business_change_v1",
                        "entity_type": "job",
                        "entity_id_field": "job_id",
                        "display_id_field": "job_id",
                        "changed_fields": ["priority", "status"],
                        "selector_fields": ["id", "priority"],
                        "source_state_basis": ["read_collection_before_mutation"],
                    },
                    "x-ai-capability-tags": ["job", "update", "business_change", "field_change"],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "type": "string"},
                        {
                            "name": "request",
                            "in": "body",
                            "schema": {
                                "type": "object",
                                "properties": {"priority": {"type": "string"}, "status": {"type": "string"}},
                            },
                        },
                    ],
                    "responses": {"200": {"schema": {"type": "object"}}},
                }
            },
        },
    }

    tools = {tool.name: tool for tool in tools_from_openapi(spec)}
    list_tags = set(json.loads(tools["get__jobs"].capability_tags))
    update_tags = set(json.loads(tools["put__jobs_{id}"].capability_tags))

    assert tools["get__jobs"].input_schema["x-ai-no-match-contract"]["contract"] == "entity_agnostic_no_matching_records_v1"
    assert {"no", "match", "record"} <= list_tags
    assert tools["put__jobs_{id}"].input_schema["x-ai-business-change-fields"]["changed_fields"] == ["priority", "status"]
    assert {"business", "change", "field", "status"} <= update_tags


def test_current_openapi_metadata_is_ready_for_generic_response_contracts():
    swagger_path = Path(__file__).resolve().parents[2] / "emas" / "docs" / "swagger.json"
    spec = json.loads(swagger_path.read_text(encoding="utf-8"))
    tools = {tool.name: tool for tool in tools_from_openapi(spec)}

    status_tool_names = [
        "get__machines_{id}",
        "get__jobs_{id}",
        "get__products_{id}",
        "get__inventory_materials_{id}",
    ]
    for name in status_tool_names:
        schema = tools[name].input_schema
        tags = set(json.loads(tools[name].capability_tags))
        assert "entity_status_v1" in schema["x-ai-response-contracts"]
        assert schema["x-ai-primary-status-field"] == "status"
        assert schema["x-ai-entity-id-field"]
        assert schema["properties"]["id"]["x-ai-id-field"] == schema["x-ai-entity-id-field"]
        assert {"read", "lookup", "status", "entity"} <= tags

    job_change = tools["put__jobs_{id}"].input_schema
    assert "business_change_v1" in job_change["x-ai-response-contracts"]
    assert job_change["x-ai-business-change-fields"]["changed_fields"] == [
        "deadline",
        "notes",
        "priority",
        "quantity_total",
        "status",
    ]
    assert "read_collection_before_mutation" in job_change["x-ai-business-change-fields"]["source_state_basis"]

    no_match = tools["get__jobs"].input_schema
    assert "entity_agnostic_no_matching_records_v1" in no_match["x-ai-response-contracts"]
    assert no_match["x-ai-no-match-contract"]["approval_required"] is False

    transaction = tools["post__agent_transaction_bundle-dry-run"].input_schema
    assert {"business_change_v1", "entity_agnostic_no_matching_records_v1"} <= set(transaction["x-ai-response-contracts"])
    assert transaction["x-ai-business-change-fields"]["operation_results_path"] == "data.operations"

