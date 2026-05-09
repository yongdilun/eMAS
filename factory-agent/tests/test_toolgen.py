from factory_agent.registry.toolgen import tools_from_openapi


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

