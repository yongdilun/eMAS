# Available Tools

## post__ai_command
**Description**: Parse a command
**Method**: POST
**Endpoint**: /ai/command
**Capability Tags**: ["ai", "command", "create", "parse", "a", "debug", "execute", "readonly", "query", "data", "action", "ambiguou", "approval", "request", "bdi", "result", "belief", "entity", "resource", "desire", "confidence", "intent", "intention", "executable", "call", "body", "method", "path", "purpose", "require", "clarification", "payload", "executed", "ui", "display", "primary", "secondary", "hidden", "if", "card", "exist", "priority", "high", "normal", "low", "execution", "mode", "form", "guidance", "human", "message", "insight", "kind", "pending", "approve", "id", "reject", "risk", "summary", "side", "effect", "level", "tool", "name", "bullet", "metric", "label", "value", "title", "tone", "source", "description", "read", "only", "statu", "suggested", "turn", "block", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "debug": {
      "type": "boolean"
    },
    "execute_readonly": {
      "type": "boolean"
    },
    "query": {
      "type": "string"
    }
  },
  "required": [
    "query"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "debug": "body",
    "execute_readonly": "body",
    "query": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "query"
    ],
    "properties": {
      "debug": {
        "type": "boolean"
      },
      "execute_readonly": {
        "type": "boolean"
      },
      "query": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "debug",
    "execute_readonly",
    "query"
  ],
  "x-body-required": [
    "query"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "action": {
          "type": "string"
        },
        "ambiguous": {
          "type": "boolean"
        },
        "approval_request": {
          "type": "object",
          "additionalProperties": true
        },
        "bdi_result": {
          "type": "object",
          "properties": {
            "beliefs": {
              "type": "object",
              "properties": {
                "entities": {
                  "type": "object",
                  "additionalProperties": true
                },
                "resource": {
                  "type": "string"
                }
              }
            },
            "desire": {
              "type": "object",
              "properties": {
                "confidence": {
                  "type": "number"
                },
                "intent": {
                  "type": "string"
                }
              }
            },
            "intention": {
              "type": "object",
              "properties": {
                "action": {
                  "type": "string"
                },
                "executable_calls": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "body": {
                        "type": "object",
                        "additionalProperties": true
                      },
                      "method": {
                        "type": "string"
                      },
                      "path": {
                        "type": "string"
                      },
                      "purpose": {
                        "type": "string"
                      },
                      "requires_approval": {
                        "type": "boolean"
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "clarifications": {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        "confidence": {
          "type": "number"
        },
        "debug_payload": {
          "type": "object",
          "additionalProperties": true
        },
        "entities": {
          "type": "object",
          "additionalProperties": true
        },
        "executed": {
          "type": "boolean"
        },
        "executed_call": {
          "type": "object",
          "properties": {
            "body": {
              "type": "object",
              "additionalProperties": true
            },
            "method": {
              "type": "string"
            },
            "path": {
              "type": "string"
            },
            "purpose": {
              "type": "string"
            },
            "requires_approval": {
              "type": "boolean"
            },
            "ui": {
              "type": "object",
              "properties": {
                "display": {
                  "description": "primary | secondary | hidden_if_result_card_exists",
                  "type": "string"
                },
                "priority": {
                  "description": "high | normal | low",
                  "type": "string"
                }
              }
            }
          }
        },
        "executed_calls": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "body": {
                "type": "object",
                "additionalProperties": true
              },
              "method": {
                "type": "string"
              },
              "path": {
                "type": "string"
              },
              "purpose": {
                "type": "string"
              },
              "requires_approval": {
                "type": "boolean"
              },
              "ui": {
                "type": "object",
                "properties": {
                  "display": {
                    "description": "primary | secondary | hidden_if_result_card_exists",
                    "type": "string"
                  },
                  "priority": {
                    "description": "high | normal | low",
                    "type": "string"
                  }
                }
              }
            }
          }
        },
        "execution_mode": {
          "type": "string"
        },
        "form_request": {
          "type": "object",
          "additionalProperties": true
        },
        "guidance": {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        "human_message": {
          "type": "string"
        },
        "insights": {
          "type": "object",
          "properties": {}
        },
        "intent": {
          "type": "string"
        },
        "message": {
          "type": "string"
        },
        "message_kind": {
          "type": "string"
        },
        "pending_approvals": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "approve_call": {
                "type": "object",
                "properties": {
                  "body": {
                    "type": "object",
                    "additionalProperties": true
                  },
                  "method": {
                    "type": "string"
                  },
                  "path": {
                    "type": "string"
                  },
                  "purpose": {
                    "type": "string"
                  },
                  "requires_approval": {
                    "type": "boolean"
                  },
                  "ui": {
                    "type": "object",
                    "properties": {
                      "display": {
                        "description": "primary | secondary | hidden_if_result_card_exists",
                        "type": "string"
                      },
                      "priority": {
                        "description": "high | normal | low",
                        "type": "string"
                      }
                    }
                  }
                }
              },
              "id": {
                "type": "string"
              },
              "reject_call": {
                "type": "object",
                "properties": {
                  "body": {
                    "type": "object",
                    "additionalProperties": true
                  },
                  "method": {
                    "type": "string"
                  },
                  "path": {
                    "type": "string"
                  },
                  "purpose": {
                    "type": "string"
                  },
                  "requires_approval": {
                    "type": "boolean"
                  },
                  "ui": {
                    "type": "object",
                    "properties": {
                      "display": {
                        "description": "primary | secondary | hidden_if_result_card_exists",
                        "type": "string"
                      },
                      "priority": {
                        "description": "high | normal | low",
                        "type": "string"
                      }
                    }
                  }
                }
              },
              "risk_summary": {
                "type": "string"
              },
              "side_effect_level": {
                "type": "string"
              },
              "tool_name": {
                "type": "string"
              }
            }
          }
        },
        "result_cards": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "actions": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "body": {
                      "type": "object",
                      "additionalProperties": true
                    },
                    "method": {
                      "type": "string"
                    },
                    "path": {
                      "type": "string"
                    },
                    "purpose": {
                      "type": "string"
                    },
                    "requires_approval": {
                      "type": "boolean"
                    },
                    "ui": {
                      "type": "object",
                      "properties": {
                        "display": {
                          "description": "primary | secondary | hidden_if_result_card_exists",
                          "type": "string"
                        },
                        "priority": {
                          "description": "high | normal | low",
                          "type": "string"
                        }
                      }
                    }
                  }
                }
              },
              "bullets": {
                "type": "array",
                "items": {
                  "type": "string"
                }
              },
              "kind": {
                "type": "string"
              },
              "metrics": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "label": {
                      "type": "string"
                    },
                    "value": {
                      "type": "string"
                    }
                  }
                }
              },
              "summary": {
                "type": "string"
              },
              "title": {
                "type": "string"
              },
              "tone": {
                "type": "string"
              }
            }
          }
        },
        "sources": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "description": {
                "type": "string"
              },
              "kind": {
                "type": "string"
              },
              "name": {
                "type": "string"
              },
              "path": {
                "type": "string"
              },
              "read_only": {
                "type": "boolean"
              }
            }
          }
        },
        "status_label": {
          "type": "string"
        },
        "suggested_calls": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "body": {
                "type": "object",
                "additionalProperties": true
              },
              "method": {
                "type": "string"
              },
              "path": {
                "type": "string"
              },
              "purpose": {
                "type": "string"
              },
              "requires_approval": {
                "type": "boolean"
              },
              "ui": {
                "type": "object",
                "properties": {
                  "display": {
                    "description": "primary | secondary | hidden_if_result_card_exists",
                    "type": "string"
                  },
                  "priority": {
                    "description": "high | normal | low",
                    "type": "string"
                  }
                }
              }
            }
          }
        },
        "turn_id": {
          "type": "string"
        },
        "ui_blocks": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": true
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_metrics
**Description**: Metrics
**Method**: GET
**Endpoint**: /ai/metrics
**Capability Tags**: ["ai", "metric", "scheduling", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_apply-replenishment-batch
**Description**: Apply replenishment batch
**Method**: POST
**Endpoint**: /ai/scheduling/apply-replenishment-batch
**Capability Tags**: ["ai", "scheduling", "apply", "replenishment", "batch", "create", "arrival", "arrive", "at", "inventory", "snapshot", "computed", "material", "id", "version", "note", "option", "type", "optiontype", "omit", "or", "replenish", "default", "expected", "schedule", "production", "planned", "subproduct", "stock", "product", "in", "quantity", "suggestion", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "arrivals": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "arrive_at",
          "material_id",
          "quantity"
        ],
        "properties": {
          "arrive_at": {
            "type": "string"
          },
          "inventory_snapshot": {
            "type": "object",
            "required": [
              "material_id",
              "version"
            ],
            "properties": {
              "computed_at": {
                "type": "string"
              },
              "material_id": {
                "type": "string",
                "pattern": "^MAT-[A-Za-z0-9-]+$",
                "x-ai-entity": "inventory",
                "x-ai-id-prefix": "MAT-",
                "x-ai-id-field": "material_id"
              },
              "version": {
                "type": "string"
              }
            }
          },
          "material_id": {
            "type": "string",
            "pattern": "^MAT-[A-Za-z0-9-]+$",
            "x-ai-entity": "inventory",
            "x-ai-id-prefix": "MAT-",
            "x-ai-id-field": "material_id"
          },
          "notes": {
            "type": "string"
          },
          "option_type": {
            "description": "OptionType: omit or \"replenish\" (default) = material expected arrival; \"schedule_production\" = planned subproduct stock (product_id in material_id).",
            "type": "string"
          },
          "quantity": {
            "type": "number"
          }
        }
      }
    },
    "suggestions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "arrive_at",
          "material_id",
          "quantity"
        ],
        "properties": {
          "arrive_at": {
            "type": "string"
          },
          "inventory_snapshot": {
            "type": "object",
            "required": [
              "material_id",
              "version"
            ],
            "properties": {
              "computed_at": {
                "type": "string"
              },
              "material_id": {
                "type": "string",
                "pattern": "^MAT-[A-Za-z0-9-]+$",
                "x-ai-entity": "inventory",
                "x-ai-id-prefix": "MAT-",
                "x-ai-id-field": "material_id"
              },
              "version": {
                "type": "string"
              }
            }
          },
          "material_id": {
            "type": "string",
            "pattern": "^MAT-[A-Za-z0-9-]+$",
            "x-ai-entity": "inventory",
            "x-ai-id-prefix": "MAT-",
            "x-ai-id-field": "material_id"
          },
          "notes": {
            "type": "string"
          },
          "option_type": {
            "description": "OptionType: omit or \"replenish\" (default) = material expected arrival; \"schedule_production\" = planned subproduct stock (product_id in material_id).",
            "type": "string"
          },
          "quantity": {
            "type": "number"
          }
        }
      }
    }
  },
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "arrivals": "body",
    "suggestions": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "arrivals": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "arrive_at",
            "material_id",
            "quantity"
          ],
          "properties": {
            "arrive_at": {
              "type": "string"
            },
            "inventory_snapshot": {
              "type": "object",
              "required": [
                "material_id",
                "version"
              ],
              "properties": {
                "computed_at": {
                  "type": "string"
                },
                "material_id": {
                  "type": "string",
                  "pattern": "^MAT-[A-Za-z0-9-]+$",
                  "x-ai-entity": "inventory",
                  "x-ai-id-prefix": "MAT-",
                  "x-ai-id-field": "material_id"
                },
                "version": {
                  "type": "string"
                }
              }
            },
            "material_id": {
              "type": "string",
              "pattern": "^MAT-[A-Za-z0-9-]+$",
              "x-ai-entity": "inventory",
              "x-ai-id-prefix": "MAT-",
              "x-ai-id-field": "material_id"
            },
            "notes": {
              "type": "string"
            },
            "option_type": {
              "description": "OptionType: omit or \"replenish\" (default) = material expected arrival; \"schedule_production\" = planned subproduct stock (product_id in material_id).",
              "type": "string"
            },
            "quantity": {
              "type": "number"
            }
          }
        }
      },
      "suggestions": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "arrive_at",
            "material_id",
            "quantity"
          ],
          "properties": {
            "arrive_at": {
              "type": "string"
            },
            "inventory_snapshot": {
              "type": "object",
              "required": [
                "material_id",
                "version"
              ],
              "properties": {
                "computed_at": {
                  "type": "string"
                },
                "material_id": {
                  "type": "string",
                  "pattern": "^MAT-[A-Za-z0-9-]+$",
                  "x-ai-entity": "inventory",
                  "x-ai-id-prefix": "MAT-",
                  "x-ai-id-field": "material_id"
                },
                "version": {
                  "type": "string"
                }
              }
            },
            "material_id": {
              "type": "string",
              "pattern": "^MAT-[A-Za-z0-9-]+$",
              "x-ai-entity": "inventory",
              "x-ai-id-prefix": "MAT-",
              "x-ai-id-field": "material_id"
            },
            "notes": {
              "type": "string"
            },
            "option_type": {
              "description": "OptionType: omit or \"replenish\" (default) = material expected arrival; \"schedule_production\" = planned subproduct stock (product_id in material_id).",
              "type": "string"
            },
            "quantity": {
              "type": "number"
            }
          }
        }
      }
    }
  },
  "x-body-fields": [
    "arrivals",
    "suggestions"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_batch-proposals
**Description**: Generate batch proposals
**Method**: POST
**Endpoint**: /ai/scheduling/batch-proposals
**Capability Tags**: ["ai", "scheduling", "batch", "proposal", "create", "generate", "include", "inventory", "action", "job", "ids", "explicit", "if", "empty", "and", "scope", "set", "use", "order", "by", "edd", "epo", "fifo", "default", "all", "unscheduled", "with", "statu", "planned", "scheduled", "no", "active", "slot", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "include_inventory_actions": {
      "type": "boolean"
    },
    "job_ids": {
      "description": "explicit job IDs; if empty and Scope set, use scope",
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "order_by": {
      "description": "\"edd\" | \"epo\" | \"fifo\" (default: \"epo\")",
      "type": "string"
    },
    "scope": {
      "description": "\"all_unscheduled\" = all jobs with status planned/scheduled and no active slots",
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "include_inventory_actions": "body",
    "job_ids": "body",
    "order_by": "body",
    "scope": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "include_inventory_actions": {
        "type": "boolean"
      },
      "job_ids": {
        "description": "explicit job IDs; if empty and Scope set, use scope",
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "order_by": {
        "description": "\"edd\" | \"epo\" | \"fifo\" (default: \"epo\")",
        "type": "string"
      },
      "scope": {
        "description": "\"all_unscheduled\" = all jobs with status planned/scheduled and no active slots",
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "include_inventory_actions",
    "job_ids",
    "order_by",
    "scope"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_bottleneck-forecast
**Description**: Bottleneck forecast
**Method**: GET
**Endpoint**: /ai/scheduling/bottleneck-forecast
**Capability Tags**: ["ai", "scheduling", "bottleneck", "forecast", "list", "day", "ahead", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "days_ahead": {
      "type": "integer"
    }
  },
  "required": [
    "days_ahead"
  ],
  "x-path-params": [],
  "x-query-params": [
    "days_ahead"
  ],
  "x-param-sources": {
    "days_ahead": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_job-steps_{id}_machine-ranking
**Description**: Machine ranking
**Method**: GET
**Endpoint**: /ai/scheduling/job-steps/{id}/machine-ranking
**Capability Tags**: ["ai", "scheduling", "job", "step", "machine", "ranking", "lookup", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_job-steps_{id}_split-suggestion
**Description**: Split suggestion
**Method**: GET
**Endpoint**: /ai/scheduling/job-steps/{id}/split-suggestion
**Capability Tags**: ["ai", "scheduling", "job", "step", "split", "suggestion", "lookup", "support", "optional", "field", "selection", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_jobs_{id}_apply-proposal
**Description**: Apply a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/apply-proposal
**Capability Tags**: ["ai", "scheduling", "job", "apply", "proposal", "create", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_jobs_{id}_apply-replenishment
**Description**: Apply replenishment
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/apply-replenishment
**Capability Tags**: ["ai", "scheduling", "job", "apply", "replenishment", "create", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_jobs_{id}_assist
**Description**: Assist a job
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/assist
**Capability Tags**: ["ai", "scheduling", "job", "assist", "lookup", "a", "support", "optional", "field", "selection", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_jobs_{id}_delay-risk
**Description**: Delay risk
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/delay-risk
**Capability Tags**: ["ai", "scheduling", "job", "delay", "risk", "lookup", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_jobs_{id}_explanation
**Description**: Explanation
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/explanation
**Capability Tags**: ["ai", "scheduling", "job", "explanation", "lookup", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_jobs_{id}_proposal
**Description**: Generate a proposal
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/proposal
**Capability Tags**: ["ai", "scheduling", "job", "proposal", "lookup", "generate", "a", "support", "optional", "field", "selection", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_jobs_{id}_proposal
**Description**: Generate a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/proposal
**Capability Tags**: ["ai", "scheduling", "job", "proposal", "create", "generate", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_jobs_{id}_proposals
**Description**: List proposals
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/proposals
**Capability Tags**: ["ai", "scheduling", "job", "proposal", "lookup", "list", "support", "optional", "field", "selection", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_jobs_{id}_replenish-and-replan
**Description**: Replenish and replan
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/replenish-and-replan
**Capability Tags**: ["ai", "scheduling", "job", "replenish", "and", "replan", "create", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_jobs_{id}_shortage-analysis
**Description**: Shortage analysis
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/shortage-analysis
**Capability Tags**: ["ai", "scheduling", "job", "shortage", "analysi", "lookup", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__ai_scheduling_proposals_{id}
**Description**: Get a proposal
**Method**: GET
**Endpoint**: /ai/scheduling/proposals/{id}
**Capability Tags**: ["ai", "scheduling", "proposal", "lookup", "a", "support", "optional", "field", "selection", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_proposals_{id}_apply
**Description**: Apply a proposal by ID
**Method**: POST
**Endpoint**: /ai/scheduling/proposals/{id}/apply
**Capability Tags**: ["ai", "scheduling", "proposal", "apply", "create", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_proposals_{id}_approve
**Description**: Approve a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/proposals/{id}/approve
**Capability Tags**: ["ai", "scheduling", "proposal", "approve", "create", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_proposals_{id}_reject
**Description**: Reject a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/proposals/{id}/reject
**Capability Tags**: ["ai", "scheduling", "proposal", "reject", "create", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_reschedule-all
**Description**: Reschedule all
**Method**: POST
**Endpoint**: /ai/scheduling/reschedule-all
**Capability Tags**: ["ai", "scheduling", "reschedule", "all", "create", "dry", "run", "if", "true", "preview", "only", "no", "cancel", "delete", "persist", "return", "proposal", "without", "side", "effect", "order", "by", "edd", "epo", "fifo", "readiness", "default", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "dry_run": {
      "description": "if true: preview only, no cancel/delete/persist; returns proposals without side effects",
      "type": "boolean"
    },
    "order_by": {
      "description": "\"edd\" | \"epo\" | \"fifo\" | \"readiness\" (default: \"epo\")",
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "dry_run": "body",
    "order_by": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "dry_run": {
        "description": "if true: preview only, no cancel/delete/persist; returns proposals without side effects",
        "type": "boolean"
      },
      "order_by": {
        "description": "\"edd\" | \"epo\" | \"fifo\" | \"readiness\" (default: \"epo\")",
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "dry_run",
    "order_by"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__ai_scheduling_verify-overlaps
**Description**: Verify overlaps
**Method**: POST
**Endpoint**: /ai/scheduling/verify-overlaps
**Capability Tags**: ["ai", "scheduling", "verify", "overlap", "create", "job", "ids", "optional", "when", "scope", "applied", "if", "empty", "check", "all", "with", "active", "slot", "proposal", "fetch", "from", "db", "or", "pass", "inline", "e", "g", "data", "batch", "id", "proposed", "step", "machine", "scheduled", "end", "start", "default", "vs", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "job_ids": {
      "description": "optional when scope=applied; if empty, check all jobs with active slots",
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "proposal_ids": {
      "description": "fetch proposals from DB (scope=proposals)",
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "proposals": {
      "description": "or pass inline (e.g. data.proposals from batch-proposals)",
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "job_id": {
            "type": "string",
            "pattern": "^JOB-[A-Za-z0-9-]+$",
            "x-ai-entity": "job",
            "x-ai-id-prefix": "JOB-",
            "x-ai-id-field": "job_id"
          },
          "proposal_id": {
            "type": "string",
            "pattern": "^AIPROP-[A-Za-z0-9-]+$",
            "x-ai-entity": "proposal",
            "x-ai-id-prefix": "AIPROP-",
            "x-ai-id-field": "proposal_id"
          },
          "proposed_slots": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "job_step_id": {
                  "type": "string",
                  "pattern": "^JS-[A-Za-z0-9-]+$",
                  "x-ai-entity": "step",
                  "x-ai-id-prefix": "JS-",
                  "x-ai-id-field": "job_step_id"
                },
                "machine_id": {
                  "type": "string",
                  "pattern": "^M-[A-Za-z0-9-]+$",
                  "x-ai-entity": "machine",
                  "x-ai-id-prefix": "M-",
                  "x-ai-id-field": "machine_id"
                },
                "scheduled_end": {
                  "type": "string"
                },
                "scheduled_start": {
                  "type": "string"
                }
              }
            }
          }
        }
      }
    },
    "scope": {
      "description": "\"proposals\" (default) | \"applied\" - verify proposals vs applied slots",
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "job_ids": "body",
    "proposal_ids": "body",
    "proposals": "body",
    "scope": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "job_ids": {
        "description": "optional when scope=applied; if empty, check all jobs with active slots",
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "proposal_ids": {
        "description": "fetch proposals from DB (scope=proposals)",
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "proposals": {
        "description": "or pass inline (e.g. data.proposals from batch-proposals)",
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "job_id": {
              "type": "string",
              "pattern": "^JOB-[A-Za-z0-9-]+$",
              "x-ai-entity": "job",
              "x-ai-id-prefix": "JOB-",
              "x-ai-id-field": "job_id"
            },
            "proposal_id": {
              "type": "string",
              "pattern": "^AIPROP-[A-Za-z0-9-]+$",
              "x-ai-entity": "proposal",
              "x-ai-id-prefix": "AIPROP-",
              "x-ai-id-field": "proposal_id"
            },
            "proposed_slots": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "job_step_id": {
                    "type": "string",
                    "pattern": "^JS-[A-Za-z0-9-]+$",
                    "x-ai-entity": "step",
                    "x-ai-id-prefix": "JS-",
                    "x-ai-id-field": "job_step_id"
                  },
                  "machine_id": {
                    "type": "string",
                    "pattern": "^M-[A-Za-z0-9-]+$",
                    "x-ai-entity": "machine",
                    "x-ai-id-prefix": "M-",
                    "x-ai-id-field": "machine_id"
                  },
                  "scheduled_end": {
                    "type": "string"
                  },
                  "scheduled_start": {
                    "type": "string"
                  }
                }
              }
            }
          }
        }
      },
      "scope": {
        "description": "\"proposals\" (default) | \"applied\" - verify proposals vs applied slots",
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "job_ids",
    "proposal_ids",
    "proposals",
    "scope"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__alerts
**Description**: Get alerts
**Method**: GET
**Endpoint**: /alerts
**Capability Tags**: ["alert", "dashboard", "list", "statu", "type", "sort", "by", "dir", "limit", "offset", "field", "data", "machine", "id", "time", "title", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string"
    },
    "type": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    },
    "sort_dir": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "status",
    "type",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "status": "query",
    "type": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "machine_id": {
            "type": "string",
            "pattern": "^M-[A-Za-z0-9-]+$",
            "x-ai-entity": "machine",
            "x-ai-id-prefix": "M-",
            "x-ai-id-field": "machine_id"
          },
          "time": {
            "type": "string"
          },
          "title": {
            "type": "string"
          },
          "type": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__chatbot_approval_pending
**Description**: List pending approvals
**Method**: GET
**Endpoint**: /chatbot/approval/pending
**Capability Tags**: ["chatbot", "approval", "pending", "list", "id", "data", "arg", "json", "conversation", "created", "at", "decided", "by", "execution", "error", "idempotency", "key", "method", "path", "request", "requested", "result", "snapshot", "risk", "summary", "side", "effect", "level", "statu", "approved", "rejected", "executed", "expired", "failed", "tool", "name", "turn", "audit", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "args_json": {
            "type": "string"
          },
          "conversation_id": {
            "type": "string"
          },
          "created_at": {
            "type": "string"
          },
          "decided_at": {
            "type": "string"
          },
          "decided_by": {
            "type": "string"
          },
          "execution_error": {
            "type": "string"
          },
          "id": {
            "type": "string"
          },
          "idempotency_key": {
            "type": "string"
          },
          "method": {
            "type": "string"
          },
          "path": {
            "type": "string"
          },
          "request_id": {
            "type": "string"
          },
          "requested_by": {
            "type": "string"
          },
          "result_snapshot_id": {
            "type": "string"
          },
          "risk_summary": {
            "type": "string"
          },
          "side_effect_level": {
            "type": "string"
          },
          "status": {
            "description": "PENDING, APPROVED, REJECTED, EXECUTED, EXPIRED, FAILED",
            "type": "string"
          },
          "tool_name": {
            "type": "string"
          },
          "turn_audit_id": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__chatbot_approval_{id}
**Description**: Get an approval by ID
**Method**: GET
**Endpoint**: /chatbot/approval/{id}
**Capability Tags**: ["chatbot", "approval", "lookup", "an", "id", "support", "optional", "field", "selection", "data", "arg", "json", "conversation", "created", "at", "decided", "by", "execution", "error", "idempotency", "key", "method", "path", "request", "requested", "result", "snapshot", "risk", "summary", "side", "effect", "level", "statu", "pending", "approved", "rejected", "executed", "expired", "failed", "tool", "name", "turn", "audit", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "args_json": {
          "type": "string"
        },
        "conversation_id": {
          "type": "string"
        },
        "created_at": {
          "type": "string"
        },
        "decided_at": {
          "type": "string"
        },
        "decided_by": {
          "type": "string"
        },
        "execution_error": {
          "type": "string"
        },
        "id": {
          "type": "string"
        },
        "idempotency_key": {
          "type": "string"
        },
        "method": {
          "type": "string"
        },
        "path": {
          "type": "string"
        },
        "request_id": {
          "type": "string"
        },
        "requested_by": {
          "type": "string"
        },
        "result_snapshot_id": {
          "type": "string"
        },
        "risk_summary": {
          "type": "string"
        },
        "side_effect_level": {
          "type": "string"
        },
        "status": {
          "description": "PENDING, APPROVED, REJECTED, EXECUTED, EXPIRED, FAILED",
          "type": "string"
        },
        "tool_name": {
          "type": "string"
        },
        "turn_audit_id": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__chatbot_approval_{id}_approve
**Description**: Approve an approval
**Method**: POST
**Endpoint**: /chatbot/approval/{id}/approve
**Capability Tags**: ["chatbot", "approval", "approve", "create", "an", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__chatbot_approval_{id}_reject
**Description**: Reject an approval
**Method**: POST
**Endpoint**: /chatbot/approval/{id}/reject
**Capability Tags**: ["chatbot", "approval", "reject", "create", "an", "id", "data", "arg", "json", "conversation", "created", "at", "decided", "by", "execution", "error", "idempotency", "key", "method", "path", "request", "requested", "result", "snapshot", "risk", "summary", "side", "effect", "level", "statu", "pending", "approved", "rejected", "executed", "expired", "failed", "tool", "name", "turn", "audit", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "args_json": {
          "type": "string"
        },
        "conversation_id": {
          "type": "string"
        },
        "created_at": {
          "type": "string"
        },
        "decided_at": {
          "type": "string"
        },
        "decided_by": {
          "type": "string"
        },
        "execution_error": {
          "type": "string"
        },
        "id": {
          "type": "string"
        },
        "idempotency_key": {
          "type": "string"
        },
        "method": {
          "type": "string"
        },
        "path": {
          "type": "string"
        },
        "request_id": {
          "type": "string"
        },
        "requested_by": {
          "type": "string"
        },
        "result_snapshot_id": {
          "type": "string"
        },
        "risk_summary": {
          "type": "string"
        },
        "side_effect_level": {
          "type": "string"
        },
        "status": {
          "description": "PENDING, APPROVED, REJECTED, EXECUTED, EXPIRED, FAILED",
          "type": "string"
        },
        "tool_name": {
          "type": "string"
        },
        "turn_audit_id": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__dashboard_kpis
**Description**: Get KPIs
**Method**: GET
**Endpoint**: /dashboard/kpis
**Capability Tags**: ["dashboard", "kpi", "list", "data", "downtime", "change", "hrs", "oee", "pct", "production", "unit", "utilization", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "downtime_change": {
          "type": "number"
        },
        "downtime_hrs": {
          "type": "number"
        },
        "oee_change": {
          "type": "number"
        },
        "oee_pct": {
          "type": "number"
        },
        "production_change": {
          "type": "number"
        },
        "production_units": {
          "type": "integer"
        },
        "utilization_change": {
          "type": "number"
        },
        "utilization_pct": {
          "type": "number"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__formula
**Description**: List all formulas
**Method**: GET
**Endpoint**: /formula
**Capability Tags**: ["formula", "list", "all", "optional", "filter", "sorting", "and", "pagination", "q", "sort", "by", "dir", "limit", "offset", "field", "data", "createdat", "effectivefrom", "effectiveto", "formulaid", "formulaname", "instruction", "safetynote", "version", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "q": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    },
    "sort_dir": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "q",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "q": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "createdAt": {
            "type": "string"
          },
          "effectiveFrom": {
            "type": "string"
          },
          "effectiveTo": {
            "type": "string"
          },
          "formulaID": {
            "type": "string"
          },
          "formulaName": {
            "type": "string"
          },
          "instructions": {
            "type": "string"
          },
          "safetyNotes": {
            "type": "string"
          },
          "version": {
            "type": "integer"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__formula
**Description**: Create a formula
**Method**: POST
**Endpoint**: /formula
**Capability Tags**: ["formula", "create", "a", "id", "is", "generated", "the", "f", "prefix", "when", "omitted", "optional", "with", "name", "instruction", "safety", "note", "version", "data", "createdat", "effectivefrom", "effectiveto", "formulaid", "formulaname", "safetynote", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "formula_id": {
      "description": "Optional; generated with F- prefix when omitted.",
      "type": "string",
      "pattern": "^F-[A-Za-z0-9-]+$",
      "x-ai-entity": "formula",
      "x-ai-id-prefix": "F-",
      "x-ai-id-field": "formula_id",
      "x-ai-generated": true
    },
    "formula_name": {
      "type": "string"
    },
    "instructions": {
      "type": "string"
    },
    "safety_notes": {
      "type": "string"
    },
    "version": {
      "type": "integer"
    }
  },
  "required": [
    "formula_name"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "formula_id": "body",
    "formula_name": "body",
    "instructions": "body",
    "safety_notes": "body",
    "version": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "formula_name"
    ],
    "properties": {
      "formula_id": {
        "description": "Optional; generated with F- prefix when omitted.",
        "type": "string",
        "pattern": "^F-[A-Za-z0-9-]+$",
        "x-ai-entity": "formula",
        "x-ai-id-prefix": "F-",
        "x-ai-id-field": "formula_id",
        "x-ai-generated": true
      },
      "formula_name": {
        "type": "string"
      },
      "instructions": {
        "type": "string"
      },
      "safety_notes": {
        "type": "string"
      },
      "version": {
        "type": "integer"
      }
    }
  },
  "x-body-fields": [
    "formula_id",
    "formula_name",
    "instructions",
    "safety_notes",
    "version"
  ],
  "x-body-required": [
    "formula_name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "createdAt": {
          "type": "string"
        },
        "effectiveFrom": {
          "type": "string"
        },
        "effectiveTo": {
          "type": "string"
        },
        "formulaID": {
          "type": "string"
        },
        "formulaName": {
          "type": "string"
        },
        "instructions": {
          "type": "string"
        },
        "safetyNotes": {
          "type": "string"
        },
        "version": {
          "type": "integer"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__formula_{id}
**Description**: Get a formula by ID
**Method**: GET
**Endpoint**: /formula/{id}
**Capability Tags**: ["formula", "lookup", "a", "id", "support", "optional", "field", "selection", "data", "createdat", "effectivefrom", "effectiveto", "formulaid", "formulaname", "instruction", "safetynote", "version", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "createdAt": {
          "type": "string"
        },
        "effectiveFrom": {
          "type": "string"
        },
        "effectiveTo": {
          "type": "string"
        },
        "formulaID": {
          "type": "string"
        },
        "formulaName": {
          "type": "string"
        },
        "instructions": {
          "type": "string"
        },
        "safetyNotes": {
          "type": "string"
        },
        "version": {
          "type": "integer"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__formula_{id}
**Description**: Delete a formula
**Method**: DELETE
**Endpoint**: /formula/{id}
**Capability Tags**: ["formula", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__formula_{id}_ingredients
**Description**: List ingredients for a formula
**Method**: GET
**Endpoint**: /formula/{id}/ingredients
**Capability Tags**: ["formula", "ingredient", "lookup", "list", "a", "id", "data", "component", "type", "material", "name", "product", "quantity", "per", "unit", "scrap", "rate", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "component_type": {
            "type": "string"
          },
          "formula_id": {
            "type": "string",
            "pattern": "^F-[A-Za-z0-9-]+$",
            "x-ai-entity": "formula",
            "x-ai-id-prefix": "F-",
            "x-ai-id-field": "formula_id"
          },
          "ingredient_id": {
            "type": "string"
          },
          "material_id": {
            "type": "string",
            "pattern": "^MAT-[A-Za-z0-9-]+$",
            "x-ai-entity": "inventory",
            "x-ai-id-prefix": "MAT-",
            "x-ai-id-field": "material_id"
          },
          "material_name": {
            "type": "string"
          },
          "product_id": {
            "type": "string",
            "pattern": "^P-[A-Za-z0-9-]+$",
            "x-ai-entity": "product",
            "x-ai-id-prefix": "P-",
            "x-ai-id-field": "product_id"
          },
          "product_name": {
            "type": "string"
          },
          "quantity_per_unit": {
            "type": "number"
          },
          "scrap_rate": {
            "type": "number"
          },
          "unit": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__formula_{id}_ingredients
**Description**: Add an ingredient to a formula
**Method**: POST
**Endpoint**: /formula/{id}/ingredients
**Capability Tags**: ["formula", "ingredient", "create", "add", "an", "a", "id", "material", "required", "if", "product", "not", "set", "percentage", "sub", "quantity", "backward", "compat", "map", "to", "per", "unit", "qty", "1", "of", "parent", "scrap", "rate", "0", "data", "component", "type", "lead", "time", "hour", "instant", "source", "make", "buy", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "material_id": {
      "description": "required if product_id not set",
      "type": "string",
      "pattern": "^MAT-[A-Za-z0-9-]+$",
      "x-ai-entity": "inventory",
      "x-ai-id-prefix": "MAT-",
      "x-ai-id-field": "material_id"
    },
    "percentage": {
      "type": "number"
    },
    "product_id": {
      "description": "required if material_id not set (sub-product)",
      "type": "string",
      "pattern": "^P-[A-Za-z0-9-]+$",
      "x-ai-entity": "product",
      "x-ai-id-prefix": "P-",
      "x-ai-id-field": "product_id"
    },
    "quantity": {
      "description": "backward compat, maps to quantity_per_unit",
      "type": "number"
    },
    "quantity_per_unit": {
      "description": "required; qty per 1 unit of parent",
      "type": "number"
    },
    "scrap_rate": {
      "description": "0-1",
      "type": "number"
    },
    "unit": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "material_id": "body",
    "percentage": "body",
    "product_id": "body",
    "quantity": "body",
    "quantity_per_unit": "body",
    "scrap_rate": "body",
    "unit": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "material_id": {
        "description": "required if product_id not set",
        "type": "string",
        "pattern": "^MAT-[A-Za-z0-9-]+$",
        "x-ai-entity": "inventory",
        "x-ai-id-prefix": "MAT-",
        "x-ai-id-field": "material_id"
      },
      "percentage": {
        "type": "number"
      },
      "product_id": {
        "description": "required if material_id not set (sub-product)",
        "type": "string",
        "pattern": "^P-[A-Za-z0-9-]+$",
        "x-ai-entity": "product",
        "x-ai-id-prefix": "P-",
        "x-ai-id-field": "product_id"
      },
      "quantity": {
        "description": "backward compat, maps to quantity_per_unit",
        "type": "number"
      },
      "quantity_per_unit": {
        "description": "required; qty per 1 unit of parent",
        "type": "number"
      },
      "scrap_rate": {
        "description": "0-1",
        "type": "number"
      },
      "unit": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "material_id",
    "percentage",
    "product_id",
    "quantity",
    "quantity_per_unit",
    "scrap_rate",
    "unit"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "component_type": {
          "type": "string"
        },
        "formula_id": {
          "type": "string",
          "pattern": "^F-[A-Za-z0-9-]+$",
          "x-ai-entity": "formula",
          "x-ai-id-prefix": "F-",
          "x-ai-id-field": "formula_id"
        },
        "ingredient_id": {
          "type": "string"
        },
        "lead_time_hours": {
          "description": "0 = instant",
          "type": "integer"
        },
        "material_id": {
          "type": "string",
          "pattern": "^MAT-[A-Za-z0-9-]+$",
          "x-ai-entity": "inventory",
          "x-ai-id-prefix": "MAT-",
          "x-ai-id-field": "material_id"
        },
        "percentage": {
          "type": "number"
        },
        "product_id": {
          "type": "string",
          "pattern": "^P-[A-Za-z0-9-]+$",
          "x-ai-entity": "product",
          "x-ai-id-prefix": "P-",
          "x-ai-id-field": "product_id"
        },
        "quantity_per_unit": {
          "type": "number"
        },
        "scrap_rate": {
          "type": "number"
        },
        "source": {
          "description": "\"make\" | \"buy\"",
          "type": "string"
        },
        "unit": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__inventory_consume
**Description**: Consume a material
**Method**: POST
**Endpoint**: /inventory/consume
**Capability Tags**: ["inventory", "consume", "create", "a", "material", "id", "quantity", "reference", "job", "slot", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "material_id": {
      "type": "string",
      "pattern": "^MAT-[A-Za-z0-9-]+$",
      "x-ai-entity": "inventory",
      "x-ai-id-prefix": "MAT-",
      "x-ai-id-field": "material_id"
    },
    "quantity": {
      "type": "number"
    },
    "reference_job_id": {
      "type": "string"
    },
    "slot_id": {
      "type": "string",
      "pattern": "^SLOT-[A-Za-z0-9-]+$",
      "x-ai-entity": "slot",
      "x-ai-id-prefix": "SLOT-",
      "x-ai-id-field": "slot_id"
    }
  },
  "required": [
    "material_id",
    "quantity"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "material_id": "body",
    "quantity": "body",
    "reference_job_id": "body",
    "slot_id": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "material_id",
      "quantity"
    ],
    "properties": {
      "material_id": {
        "type": "string",
        "pattern": "^MAT-[A-Za-z0-9-]+$",
        "x-ai-entity": "inventory",
        "x-ai-id-prefix": "MAT-",
        "x-ai-id-field": "material_id"
      },
      "quantity": {
        "type": "number"
      },
      "reference_job_id": {
        "type": "string"
      },
      "slot_id": {
        "type": "string",
        "pattern": "^SLOT-[A-Za-z0-9-]+$",
        "x-ai-entity": "slot",
        "x-ai-id-prefix": "SLOT-",
        "x-ai-id-field": "slot_id"
      }
    }
  },
  "x-body-fields": [
    "material_id",
    "quantity",
    "reference_job_id",
    "slot_id"
  ],
  "x-body-required": [
    "material_id",
    "quantity"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__inventory_expected-arrivals
**Description**: List expected arrivals
**Method**: GET
**Endpoint**: /inventory/expected-arrivals
**Capability Tags**: ["inventory", "expected", "arrival", "list", "material", "id", "statu", "from", "to", "data", "arrivalid", "createdat", "expectedarriveat", "materialid", "note", "quantity", "receivedat", "referencejobid", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "material_id": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": [
        "pending",
        "received",
        "cancelled"
      ]
    },
    "from": {
      "type": "string"
    },
    "to": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "material_id",
    "status",
    "from",
    "to"
  ],
  "x-param-sources": {
    "material_id": "query",
    "status": "query",
    "from": "query",
    "to": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "arrivalID": {
            "type": "string"
          },
          "createdAt": {
            "type": "string"
          },
          "expectedArriveAt": {
            "type": "string"
          },
          "materialID": {
            "type": "string"
          },
          "notes": {
            "type": "string"
          },
          "quantity": {
            "type": "number"
          },
          "receivedAt": {
            "type": "string"
          },
          "referenceJobID": {
            "type": "string"
          },
          "status": {
            "type": "string",
            "enum": [
              "pending",
              "received",
              "cancelled"
            ]
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__inventory_expected-arrivals
**Description**: Schedule an expected arrival
**Method**: POST
**Endpoint**: /inventory/expected-arrivals
**Capability Tags**: ["inventory", "expected", "arrival", "create", "schedule", "an", "arrive", "at", "material", "id", "note", "quantity", "data", "arrivalid", "createdat", "expectedarriveat", "materialid", "receivedat", "referencejobid", "statu", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "expected_arrive_at": {
      "type": "string"
    },
    "material_id": {
      "type": "string",
      "pattern": "^MAT-[A-Za-z0-9-]+$",
      "x-ai-entity": "inventory",
      "x-ai-id-prefix": "MAT-",
      "x-ai-id-field": "material_id"
    },
    "notes": {
      "type": "string"
    },
    "quantity": {
      "type": "number"
    }
  },
  "required": [
    "expected_arrive_at",
    "material_id",
    "quantity"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "expected_arrive_at": "body",
    "material_id": "body",
    "notes": "body",
    "quantity": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "expected_arrive_at",
      "material_id",
      "quantity"
    ],
    "properties": {
      "expected_arrive_at": {
        "type": "string"
      },
      "material_id": {
        "type": "string",
        "pattern": "^MAT-[A-Za-z0-9-]+$",
        "x-ai-entity": "inventory",
        "x-ai-id-prefix": "MAT-",
        "x-ai-id-field": "material_id"
      },
      "notes": {
        "type": "string"
      },
      "quantity": {
        "type": "number"
      }
    }
  },
  "x-body-fields": [
    "expected_arrive_at",
    "material_id",
    "notes",
    "quantity"
  ],
  "x-body-required": [
    "expected_arrive_at",
    "material_id",
    "quantity"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "arrivalID": {
          "type": "string"
        },
        "createdAt": {
          "type": "string"
        },
        "expectedArriveAt": {
          "type": "string"
        },
        "materialID": {
          "type": "string"
        },
        "notes": {
          "type": "string"
        },
        "quantity": {
          "type": "number"
        },
        "receivedAt": {
          "type": "string"
        },
        "referenceJobID": {
          "type": "string"
        },
        "status": {
          "type": "string",
          "enum": [
            "pending",
            "received",
            "cancelled"
          ]
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__inventory_materials
**Description**: List materials
**Method**: GET
**Endpoint**: /inventory/materials
**Capability Tags**: ["inventory", "material", "list", "statu", "q", "sort", "by", "dir", "limit", "offset", "data", "currentstock", "lastupdated", "materialid", "materialname", "minstock", "reorderlevel", "storagelocation", "unit", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": [
        "in_stock",
        "low_stock",
        "out_of_stock"
      ]
    },
    "q": {
      "type": "string"
    },
    "sort_by": {
      "type": "string",
      "enum": [
        "material_name",
        "current_stock",
        "last_updated"
      ]
    },
    "sort_dir": {
      "type": "string",
      "enum": [
        "asc",
        "desc"
      ]
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "status",
    "q",
    "sort_by",
    "sort_dir",
    "limit",
    "offset"
  ],
  "x-param-sources": {
    "status": "query",
    "q": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "currentStock": {
            "type": "number"
          },
          "lastUpdated": {
            "type": "string"
          },
          "materialID": {
            "type": "string"
          },
          "materialName": {
            "type": "string"
          },
          "minStock": {
            "type": "number"
          },
          "reorderLevel": {
            "type": "number"
          },
          "status": {
            "type": "string",
            "enum": [
              "in_stock",
              "low_stock",
              "out_of_stock"
            ]
          },
          "storageLocation": {
            "type": "string"
          },
          "unit": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__inventory_materials
**Description**: Create a material
**Method**: POST
**Endpoint**: /inventory/materials
**Capability Tags**: ["inventory", "material", "create", "a", "id", "is", "generated", "the", "mat", "prefix", "when", "omitted", "current", "stock", "optional", "with", "name", "min", "reorder", "level", "storage", "location", "unit", "data", "currentstock", "lastupdated", "materialid", "materialname", "minstock", "reorderlevel", "statu", "storagelocation", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "current_stock": {
      "type": "number"
    },
    "material_id": {
      "description": "Optional; generated with MAT- prefix when omitted.",
      "type": "string",
      "pattern": "^MAT-[A-Za-z0-9-]+$",
      "x-ai-entity": "inventory",
      "x-ai-id-prefix": "MAT-",
      "x-ai-id-field": "material_id",
      "x-ai-generated": true
    },
    "material_name": {
      "type": "string"
    },
    "min_stock": {
      "type": "number"
    },
    "reorder_level": {
      "type": "number"
    },
    "storage_location": {
      "type": "string"
    },
    "unit": {
      "type": "string"
    }
  },
  "required": [
    "material_name"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "current_stock": "body",
    "material_id": "body",
    "material_name": "body",
    "min_stock": "body",
    "reorder_level": "body",
    "storage_location": "body",
    "unit": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "material_name"
    ],
    "properties": {
      "current_stock": {
        "type": "number"
      },
      "material_id": {
        "description": "Optional; generated with MAT- prefix when omitted.",
        "type": "string",
        "pattern": "^MAT-[A-Za-z0-9-]+$",
        "x-ai-entity": "inventory",
        "x-ai-id-prefix": "MAT-",
        "x-ai-id-field": "material_id",
        "x-ai-generated": true
      },
      "material_name": {
        "type": "string"
      },
      "min_stock": {
        "type": "number"
      },
      "reorder_level": {
        "type": "number"
      },
      "storage_location": {
        "type": "string"
      },
      "unit": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "current_stock",
    "material_id",
    "material_name",
    "min_stock",
    "reorder_level",
    "storage_location",
    "unit"
  ],
  "x-body-required": [
    "material_name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "currentStock": {
          "type": "number"
        },
        "lastUpdated": {
          "type": "string"
        },
        "materialID": {
          "type": "string"
        },
        "materialName": {
          "type": "string"
        },
        "minStock": {
          "type": "number"
        },
        "reorderLevel": {
          "type": "number"
        },
        "status": {
          "type": "string",
          "enum": [
            "in_stock",
            "low_stock",
            "out_of_stock"
          ]
        },
        "storageLocation": {
          "type": "string"
        },
        "unit": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__inventory_materials_{id}
**Description**: Get a material by ID
**Method**: GET
**Endpoint**: /inventory/materials/{id}
**Capability Tags**: ["inventory", "material", "lookup", "a", "id", "support", "optional", "field", "selection", "data", "currentstock", "lastupdated", "materialid", "materialname", "minstock", "reorderlevel", "statu", "storagelocation", "unit", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "currentStock": {
          "type": "number"
        },
        "lastUpdated": {
          "type": "string"
        },
        "materialID": {
          "type": "string"
        },
        "materialName": {
          "type": "string"
        },
        "minStock": {
          "type": "number"
        },
        "reorderLevel": {
          "type": "number"
        },
        "status": {
          "type": "string",
          "enum": [
            "in_stock",
            "low_stock",
            "out_of_stock"
          ]
        },
        "storageLocation": {
          "type": "string"
        },
        "unit": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__inventory_product-stock
**Description**: List product inventory
**Method**: GET
**Endpoint**: /inventory/product-stock
**Capability Tags**: ["inventory", "product", "stock", "list", "id", "statu", "sort", "by", "dir", "limit", "offset", "field", "data", "availablefrom", "inventoryid", "lastupdated", "productid", "quantityonhand", "quantityreserved", "storagelocation", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "product_id": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": [
        "available",
        "reserved",
        "blocked",
        "planned"
      ]
    },
    "sort_by": {
      "type": "string",
      "enum": [
        "product_id",
        "available_from",
        "last_updated",
        "quantity_on_hand",
        "quantity_reserved",
        "status"
      ]
    },
    "sort_dir": {
      "type": "string",
      "enum": [
        "asc",
        "desc"
      ]
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "product_id",
    "status",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "product_id": "query",
    "status": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "availableFrom": {
            "type": "string"
          },
          "inventoryID": {
            "type": "string"
          },
          "lastUpdated": {
            "type": "string"
          },
          "productID": {
            "type": "string"
          },
          "quantityOnHand": {
            "type": "number"
          },
          "quantityReserved": {
            "type": "number"
          },
          "status": {
            "type": "string",
            "enum": [
              "available",
              "reserved",
              "blocked",
              "planned"
            ]
          },
          "storageLocation": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__inventory_product-stock
**Description**: Create a product inventory
**Method**: POST
**Endpoint**: /inventory/product-stock
**Capability Tags**: ["inventory", "product", "stock", "create", "a", "available", "from", "id", "quantity", "on", "hand", "reserved", "statu", "storage", "location", "data", "availablefrom", "inventoryid", "lastupdated", "productid", "quantityonhand", "quantityreserved", "storagelocation", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "available_from": {
      "type": "string"
    },
    "product_id": {
      "type": "string",
      "pattern": "^P-[A-Za-z0-9-]+$",
      "x-ai-entity": "product",
      "x-ai-id-prefix": "P-",
      "x-ai-id-field": "product_id"
    },
    "quantity_on_hand": {
      "type": "number",
      "minimum": 0
    },
    "quantity_reserved": {
      "type": "number"
    },
    "status": {
      "type": "string",
      "enum": [
        "available",
        "reserved",
        "blocked",
        "planned"
      ]
    },
    "storage_location": {
      "type": "string"
    }
  },
  "required": [
    "product_id",
    "quantity_on_hand"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "available_from": "body",
    "product_id": "body",
    "quantity_on_hand": "body",
    "quantity_reserved": "body",
    "status": "body",
    "storage_location": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "product_id",
      "quantity_on_hand"
    ],
    "properties": {
      "available_from": {
        "type": "string"
      },
      "product_id": {
        "type": "string",
        "pattern": "^P-[A-Za-z0-9-]+$",
        "x-ai-entity": "product",
        "x-ai-id-prefix": "P-",
        "x-ai-id-field": "product_id"
      },
      "quantity_on_hand": {
        "type": "number",
        "minimum": 0
      },
      "quantity_reserved": {
        "type": "number"
      },
      "status": {
        "type": "string",
        "enum": [
          "available",
          "reserved",
          "blocked",
          "planned"
        ]
      },
      "storage_location": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "available_from",
    "product_id",
    "quantity_on_hand",
    "quantity_reserved",
    "status",
    "storage_location"
  ],
  "x-body-required": [
    "product_id",
    "quantity_on_hand"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "availableFrom": {
          "type": "string"
        },
        "inventoryID": {
          "type": "string"
        },
        "lastUpdated": {
          "type": "string"
        },
        "productID": {
          "type": "string"
        },
        "quantityOnHand": {
          "type": "number"
        },
        "quantityReserved": {
          "type": "number"
        },
        "status": {
          "type": "string",
          "enum": [
            "available",
            "reserved",
            "blocked",
            "planned"
          ]
        },
        "storageLocation": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__inventory_receive
**Description**: Receive a material
**Method**: POST
**Endpoint**: /inventory/receive
**Capability Tags**: ["inventory", "receive", "create", "a", "material", "id", "quantity", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "material_id": {
      "type": "string",
      "pattern": "^MAT-[A-Za-z0-9-]+$",
      "x-ai-entity": "inventory",
      "x-ai-id-prefix": "MAT-",
      "x-ai-id-field": "material_id"
    },
    "quantity": {
      "type": "number"
    }
  },
  "required": [
    "material_id",
    "quantity"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "material_id": "body",
    "quantity": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "material_id",
      "quantity"
    ],
    "properties": {
      "material_id": {
        "type": "string",
        "pattern": "^MAT-[A-Za-z0-9-]+$",
        "x-ai-entity": "inventory",
        "x-ai-id-prefix": "MAT-",
        "x-ai-id-field": "material_id"
      },
      "quantity": {
        "type": "number"
      }
    }
  },
  "x-body-fields": [
    "material_id",
    "quantity"
  ],
  "x-body-required": [
    "material_id",
    "quantity"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__inventory_reservations
**Description**: Create a reservation
**Method**: POST
**Endpoint**: /inventory/reservations
**Capability Tags**: ["inventory", "reservation", "create", "a", "job", "id", "step", "material", "needed", "at", "reserved", "qty", "data", "createdat", "jobid", "jobstepid", "materialid", "neededat", "reservationid", "reservedqty", "statu", "updatedat", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "job_id": {
      "type": "string",
      "pattern": "^JOB-[A-Za-z0-9-]+$",
      "x-ai-entity": "job",
      "x-ai-id-prefix": "JOB-",
      "x-ai-id-field": "job_id"
    },
    "job_step_id": {
      "type": "string",
      "pattern": "^JS-[A-Za-z0-9-]+$",
      "x-ai-entity": "step",
      "x-ai-id-prefix": "JS-",
      "x-ai-id-field": "job_step_id"
    },
    "material_id": {
      "type": "string",
      "pattern": "^MAT-[A-Za-z0-9-]+$",
      "x-ai-entity": "inventory",
      "x-ai-id-prefix": "MAT-",
      "x-ai-id-field": "material_id"
    },
    "needed_at": {
      "type": "string"
    },
    "reserved_qty": {
      "type": "number"
    }
  },
  "required": [
    "material_id",
    "reserved_qty"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "job_id": "body",
    "job_step_id": "body",
    "material_id": "body",
    "needed_at": "body",
    "reserved_qty": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "material_id",
      "reserved_qty"
    ],
    "properties": {
      "job_id": {
        "type": "string",
        "pattern": "^JOB-[A-Za-z0-9-]+$",
        "x-ai-entity": "job",
        "x-ai-id-prefix": "JOB-",
        "x-ai-id-field": "job_id"
      },
      "job_step_id": {
        "type": "string",
        "pattern": "^JS-[A-Za-z0-9-]+$",
        "x-ai-entity": "step",
        "x-ai-id-prefix": "JS-",
        "x-ai-id-field": "job_step_id"
      },
      "material_id": {
        "type": "string",
        "pattern": "^MAT-[A-Za-z0-9-]+$",
        "x-ai-entity": "inventory",
        "x-ai-id-prefix": "MAT-",
        "x-ai-id-field": "material_id"
      },
      "needed_at": {
        "type": "string"
      },
      "reserved_qty": {
        "type": "number"
      }
    }
  },
  "x-body-fields": [
    "job_id",
    "job_step_id",
    "material_id",
    "needed_at",
    "reserved_qty"
  ],
  "x-body-required": [
    "material_id",
    "reserved_qty"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "createdAt": {
          "type": "string"
        },
        "jobID": {
          "type": "string"
        },
        "jobStepID": {
          "type": "string"
        },
        "materialID": {
          "type": "string"
        },
        "neededAt": {
          "type": "string"
        },
        "reservationID": {
          "type": "string"
        },
        "reservedQty": {
          "type": "number"
        },
        "status": {
          "type": "string",
          "enum": [
            "pending",
            "consumed",
            "released"
          ]
        },
        "updatedAt": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__job-steps
**Description**: Create job steps from routing
**Method**: POST
**Endpoint**: /job-steps
**Capability Tags**: ["job", "step", "slot", "create", "routing", "id", "data", "quantity", "completed", "target", "statu", "sequence", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "job_id": {
      "type": "string",
      "pattern": "^JOB-[A-Za-z0-9-]+$",
      "x-ai-entity": "job",
      "x-ai-id-prefix": "JOB-",
      "x-ai-id-field": "job_id"
    }
  },
  "required": [
    "job_id"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "job_id": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "job_id"
    ],
    "properties": {
      "job_id": {
        "type": "string",
        "pattern": "^JOB-[A-Za-z0-9-]+$",
        "x-ai-entity": "job",
        "x-ai-id-prefix": "JOB-",
        "x-ai-id-field": "job_id"
      }
    }
  },
  "x-body-fields": [
    "job_id"
  ],
  "x-body-required": [
    "job_id"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "job_id": {
            "type": "string",
            "pattern": "^JOB-[A-Za-z0-9-]+$",
            "x-ai-entity": "job",
            "x-ai-id-prefix": "JOB-",
            "x-ai-id-field": "job_id"
          },
          "job_step_id": {
            "type": "string",
            "pattern": "^JS-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "JS-",
            "x-ai-id-field": "job_step_id"
          },
          "quantity_completed": {
            "type": "integer"
          },
          "quantity_target": {
            "type": "integer"
          },
          "status": {
            "type": "string",
            "enum": [
              "pending",
              "scheduled",
              "running",
              "blocked",
              "completed"
            ]
          },
          "step_id": {
            "type": "string",
            "pattern": "^STP-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "STP-",
            "x-ai-id-field": "step_id"
          },
          "step_sequence": {
            "type": "integer"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__job-steps_split
**Description**: Split a step
**Method**: POST
**Endpoint**: /job-steps/split
**Capability Tags**: ["job", "step", "split", "slot", "create", "a", "id", "allocation", "percent", "batch", "sequence", "buffer", "min", "cleaning", "duration", "is", "parallel", "optional", "for", "machine", "prep", "processing", "proposal", "quantity", "group", "start", "time", "rfc3339", "data", "actual", "end", "minute", "changeover", "preparation", "planned", "scheduled", "statu", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "job_step_id": {
      "type": "string",
      "pattern": "^JS-[A-Za-z0-9-]+$",
      "x-ai-entity": "step",
      "x-ai-id-prefix": "JS-",
      "x-ai-id-field": "job_step_id"
    },
    "splits": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "duration_mins",
          "machine_id",
          "quantity",
          "start_time"
        ],
        "properties": {
          "allocation_percent": {
            "type": "number"
          },
          "batch_sequence": {
            "type": "integer"
          },
          "buffer_mins": {
            "type": "integer"
          },
          "cleaning_mins": {
            "type": "integer"
          },
          "duration_mins": {
            "type": "integer"
          },
          "is_parallel": {
            "type": "boolean"
          },
          "job_step_id": {
            "description": "optional, for split",
            "type": "string",
            "pattern": "^JS-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "JS-",
            "x-ai-id-field": "job_step_id"
          },
          "machine_id": {
            "type": "string",
            "pattern": "^M-[A-Za-z0-9-]+$",
            "x-ai-entity": "machine",
            "x-ai-id-prefix": "M-",
            "x-ai-id-field": "machine_id"
          },
          "prep_mins": {
            "type": "integer"
          },
          "processing_mins": {
            "type": "integer"
          },
          "proposal_id": {
            "type": "string",
            "pattern": "^AIPROP-[A-Za-z0-9-]+$",
            "x-ai-entity": "proposal",
            "x-ai-id-prefix": "AIPROP-",
            "x-ai-id-field": "proposal_id"
          },
          "quantity": {
            "type": "integer"
          },
          "split_group_id": {
            "type": "string"
          },
          "start_time": {
            "description": "RFC3339",
            "type": "string"
          }
        }
      }
    }
  },
  "required": [
    "job_step_id",
    "splits"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "job_step_id": "body",
    "splits": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "job_step_id",
      "splits"
    ],
    "properties": {
      "job_step_id": {
        "type": "string",
        "pattern": "^JS-[A-Za-z0-9-]+$",
        "x-ai-entity": "step",
        "x-ai-id-prefix": "JS-",
        "x-ai-id-field": "job_step_id"
      },
      "splits": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "duration_mins",
            "machine_id",
            "quantity",
            "start_time"
          ],
          "properties": {
            "allocation_percent": {
              "type": "number"
            },
            "batch_sequence": {
              "type": "integer"
            },
            "buffer_mins": {
              "type": "integer"
            },
            "cleaning_mins": {
              "type": "integer"
            },
            "duration_mins": {
              "type": "integer"
            },
            "is_parallel": {
              "type": "boolean"
            },
            "job_step_id": {
              "description": "optional, for split",
              "type": "string",
              "pattern": "^JS-[A-Za-z0-9-]+$",
              "x-ai-entity": "step",
              "x-ai-id-prefix": "JS-",
              "x-ai-id-field": "job_step_id"
            },
            "machine_id": {
              "type": "string",
              "pattern": "^M-[A-Za-z0-9-]+$",
              "x-ai-entity": "machine",
              "x-ai-id-prefix": "M-",
              "x-ai-id-field": "machine_id"
            },
            "prep_mins": {
              "type": "integer"
            },
            "processing_mins": {
              "type": "integer"
            },
            "proposal_id": {
              "type": "string",
              "pattern": "^AIPROP-[A-Za-z0-9-]+$",
              "x-ai-entity": "proposal",
              "x-ai-id-prefix": "AIPROP-",
              "x-ai-id-field": "proposal_id"
            },
            "quantity": {
              "type": "integer"
            },
            "split_group_id": {
              "type": "string"
            },
            "start_time": {
              "description": "RFC3339",
              "type": "string"
            }
          }
        }
      }
    }
  },
  "x-body-fields": [
    "job_step_id",
    "splits"
  ],
  "x-body-required": [
    "job_step_id",
    "splits"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "actual_end": {
            "type": "string"
          },
          "actual_start": {
            "type": "string"
          },
          "allocation_percent": {
            "type": "number"
          },
          "batch_sequence": {
            "type": "integer"
          },
          "buffer_time_minutes": {
            "type": "integer"
          },
          "changeover_time_minutes": {
            "type": "integer"
          },
          "cleaning_time_minutes": {
            "type": "integer"
          },
          "is_parallel": {
            "type": "boolean"
          },
          "job_step_id": {
            "type": "string",
            "pattern": "^JS-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "JS-",
            "x-ai-id-field": "job_step_id"
          },
          "machine_id": {
            "type": "string",
            "pattern": "^M-[A-Za-z0-9-]+$",
            "x-ai-entity": "machine",
            "x-ai-id-prefix": "M-",
            "x-ai-id-field": "machine_id"
          },
          "preparation_time_minutes": {
            "type": "integer"
          },
          "processing_time_minutes": {
            "type": "integer"
          },
          "proposal_id": {
            "type": "string",
            "pattern": "^AIPROP-[A-Za-z0-9-]+$",
            "x-ai-entity": "proposal",
            "x-ai-id-prefix": "AIPROP-",
            "x-ai-id-field": "proposal_id"
          },
          "quantity_planned": {
            "type": "integer"
          },
          "scheduled_end": {
            "type": "string"
          },
          "scheduled_start": {
            "type": "string"
          },
          "slot_id": {
            "type": "string",
            "pattern": "^SLOT-[A-Za-z0-9-]+$",
            "x-ai-entity": "slot",
            "x-ai-id-prefix": "SLOT-",
            "x-ai-id-field": "slot_id"
          },
          "split_group_id": {
            "type": "string"
          },
          "status": {
            "type": "string",
            "enum": [
              "planned",
              "running",
              "completed",
              "cancelled",
              "paused"
            ]
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__job-steps_{id}_slots
**Description**: List slots by job step ID
**Method**: GET
**Endpoint**: /job-steps/{id}/slots
**Capability Tags**: ["job", "step", "slot", "lookup", "list", "id", "data", "actual", "end", "start", "allocation", "percent", "batch", "sequence", "buffer", "time", "minute", "changeover", "cleaning", "is", "parallel", "machine", "preparation", "processing", "proposal", "quantity", "planned", "scheduled", "split", "group", "statu", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "actual_end": {
            "type": "string"
          },
          "actual_start": {
            "type": "string"
          },
          "allocation_percent": {
            "type": "number"
          },
          "batch_sequence": {
            "type": "integer"
          },
          "buffer_time_minutes": {
            "type": "integer"
          },
          "changeover_time_minutes": {
            "type": "integer"
          },
          "cleaning_time_minutes": {
            "type": "integer"
          },
          "is_parallel": {
            "type": "boolean"
          },
          "job_step_id": {
            "type": "string",
            "pattern": "^JS-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "JS-",
            "x-ai-id-field": "job_step_id"
          },
          "machine_id": {
            "type": "string",
            "pattern": "^M-[A-Za-z0-9-]+$",
            "x-ai-entity": "machine",
            "x-ai-id-prefix": "M-",
            "x-ai-id-field": "machine_id"
          },
          "preparation_time_minutes": {
            "type": "integer"
          },
          "processing_time_minutes": {
            "type": "integer"
          },
          "proposal_id": {
            "type": "string",
            "pattern": "^AIPROP-[A-Za-z0-9-]+$",
            "x-ai-entity": "proposal",
            "x-ai-id-prefix": "AIPROP-",
            "x-ai-id-field": "proposal_id"
          },
          "quantity_planned": {
            "type": "integer"
          },
          "scheduled_end": {
            "type": "string"
          },
          "scheduled_start": {
            "type": "string"
          },
          "slot_id": {
            "type": "string",
            "pattern": "^SLOT-[A-Za-z0-9-]+$",
            "x-ai-entity": "slot",
            "x-ai-id-prefix": "SLOT-",
            "x-ai-id-field": "slot_id"
          },
          "split_group_id": {
            "type": "string"
          },
          "status": {
            "type": "string",
            "enum": [
              "planned",
              "running",
              "completed",
              "cancelled",
              "paused"
            ]
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__jobs
**Description**: List jobs
**Method**: GET
**Endpoint**: /jobs
**Capability Tags**: ["job", "list", "filter", "product", "id", "statu", "priority", "machine", "start", "end", "sort", "by", "dir", "limit", "offset", "field", "data", "created", "at", "deadline", "is", "late", "human", "readable", "2", "day", "4", "hour", "on", "time", "note", "quantity", "completed", "total", "updated", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "product_id": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": [
        "planned",
        "scheduled",
        "running",
        "blocked",
        "paused",
        "completed",
        "cancelled"
      ]
    },
    "priority": {
      "type": "string",
      "enum": [
        "low",
        "medium",
        "high",
        "urgent"
      ]
    },
    "machine_id": {
      "type": "string"
    },
    "start": {
      "type": "string"
    },
    "end": {
      "type": "string"
    },
    "sort_by": {
      "type": "string",
      "enum": [
        "created_at",
        "deadline",
        "priority",
        "quantity_total",
        "completion"
      ]
    },
    "sort_dir": {
      "type": "string",
      "enum": [
        "asc",
        "desc"
      ]
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "product_id",
    "status",
    "priority",
    "machine_id",
    "start",
    "end",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "product_id": "query",
    "status": "query",
    "priority": "query",
    "machine_id": "query",
    "start": "query",
    "end": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "created_at": {
            "type": "string"
          },
          "deadline": {
            "type": "string"
          },
          "deadline_status": {
            "type": "object",
            "properties": {
              "is_late": {
                "type": "boolean"
              },
              "late_by": {
                "description": "human-readable: \"2 days\", \"4 hours\", \"on time\"",
                "type": "string"
              }
            }
          },
          "job_id": {
            "type": "string",
            "pattern": "^JOB-[A-Za-z0-9-]+$",
            "x-ai-entity": "job",
            "x-ai-id-prefix": "JOB-",
            "x-ai-id-field": "job_id"
          },
          "notes": {
            "type": "string"
          },
          "priority": {
            "type": "string",
            "enum": [
              "low",
              "medium",
              "high",
              "urgent"
            ]
          },
          "product_id": {
            "type": "string",
            "pattern": "^P-[A-Za-z0-9-]+$",
            "x-ai-entity": "product",
            "x-ai-id-prefix": "P-",
            "x-ai-id-field": "product_id"
          },
          "quantity_completed": {
            "type": "integer"
          },
          "quantity_total": {
            "type": "integer"
          },
          "status": {
            "type": "string",
            "enum": [
              "planned",
              "scheduled",
              "running",
              "blocked",
              "paused",
              "completed",
              "cancelled"
            ]
          },
          "updated_at": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__jobs
**Description**: Create a job
**Method**: POST
**Endpoint**: /jobs
**Capability Tags**: ["job", "create", "a", "deadline", "rfc3339", "note", "priority", "product", "id", "quantity", "total", "slot", "optional", "split", "allocation", "percent", "batch", "sequence", "buffer", "min", "cleaning", "duration", "is", "parallel", "step", "for", "machine", "prep", "processing", "proposal", "group", "start", "time", "data", "created", "at", "statu", "late", "by", "human", "readable", "2", "day", "4", "hour", "on", "completed", "updated", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "deadline": {
      "description": "RFC3339",
      "type": "string"
    },
    "notes": {
      "type": "string"
    },
    "priority": {
      "type": "string",
      "enum": [
        "low",
        "medium",
        "high",
        "urgent"
      ]
    },
    "product_id": {
      "type": "string",
      "pattern": "^P-[A-Za-z0-9-]+$",
      "x-ai-entity": "product",
      "x-ai-id-prefix": "P-",
      "x-ai-id-field": "product_id"
    },
    "quantity_total": {
      "type": "integer"
    },
    "slots": {
      "description": "optional split slots",
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "duration_mins",
          "machine_id",
          "quantity",
          "start_time"
        ],
        "properties": {
          "allocation_percent": {
            "type": "number"
          },
          "batch_sequence": {
            "type": "integer"
          },
          "buffer_mins": {
            "type": "integer"
          },
          "cleaning_mins": {
            "type": "integer"
          },
          "duration_mins": {
            "type": "integer"
          },
          "is_parallel": {
            "type": "boolean"
          },
          "job_step_id": {
            "description": "optional, for split",
            "type": "string",
            "pattern": "^JS-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "JS-",
            "x-ai-id-field": "job_step_id"
          },
          "machine_id": {
            "type": "string",
            "pattern": "^M-[A-Za-z0-9-]+$",
            "x-ai-entity": "machine",
            "x-ai-id-prefix": "M-",
            "x-ai-id-field": "machine_id"
          },
          "prep_mins": {
            "type": "integer"
          },
          "processing_mins": {
            "type": "integer"
          },
          "proposal_id": {
            "type": "string",
            "pattern": "^AIPROP-[A-Za-z0-9-]+$",
            "x-ai-entity": "proposal",
            "x-ai-id-prefix": "AIPROP-",
            "x-ai-id-field": "proposal_id"
          },
          "quantity": {
            "type": "integer"
          },
          "split_group_id": {
            "type": "string"
          },
          "start_time": {
            "description": "RFC3339",
            "type": "string"
          }
        }
      }
    }
  },
  "required": [
    "product_id",
    "quantity_total"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "deadline": "body",
    "notes": "body",
    "priority": "body",
    "product_id": "body",
    "quantity_total": "body",
    "slots": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "product_id",
      "quantity_total"
    ],
    "properties": {
      "deadline": {
        "description": "RFC3339",
        "type": "string"
      },
      "notes": {
        "type": "string"
      },
      "priority": {
        "type": "string",
        "enum": [
          "low",
          "medium",
          "high",
          "urgent"
        ]
      },
      "product_id": {
        "type": "string",
        "pattern": "^P-[A-Za-z0-9-]+$",
        "x-ai-entity": "product",
        "x-ai-id-prefix": "P-",
        "x-ai-id-field": "product_id"
      },
      "quantity_total": {
        "type": "integer"
      },
      "slots": {
        "description": "optional split slots",
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "duration_mins",
            "machine_id",
            "quantity",
            "start_time"
          ],
          "properties": {
            "allocation_percent": {
              "type": "number"
            },
            "batch_sequence": {
              "type": "integer"
            },
            "buffer_mins": {
              "type": "integer"
            },
            "cleaning_mins": {
              "type": "integer"
            },
            "duration_mins": {
              "type": "integer"
            },
            "is_parallel": {
              "type": "boolean"
            },
            "job_step_id": {
              "description": "optional, for split",
              "type": "string",
              "pattern": "^JS-[A-Za-z0-9-]+$",
              "x-ai-entity": "step",
              "x-ai-id-prefix": "JS-",
              "x-ai-id-field": "job_step_id"
            },
            "machine_id": {
              "type": "string",
              "pattern": "^M-[A-Za-z0-9-]+$",
              "x-ai-entity": "machine",
              "x-ai-id-prefix": "M-",
              "x-ai-id-field": "machine_id"
            },
            "prep_mins": {
              "type": "integer"
            },
            "processing_mins": {
              "type": "integer"
            },
            "proposal_id": {
              "type": "string",
              "pattern": "^AIPROP-[A-Za-z0-9-]+$",
              "x-ai-entity": "proposal",
              "x-ai-id-prefix": "AIPROP-",
              "x-ai-id-field": "proposal_id"
            },
            "quantity": {
              "type": "integer"
            },
            "split_group_id": {
              "type": "string"
            },
            "start_time": {
              "description": "RFC3339",
              "type": "string"
            }
          }
        }
      }
    }
  },
  "x-body-fields": [
    "deadline",
    "notes",
    "priority",
    "product_id",
    "quantity_total",
    "slots"
  ],
  "x-body-required": [
    "product_id",
    "quantity_total"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "created_at": {
          "type": "string"
        },
        "deadline": {
          "type": "string"
        },
        "deadline_status": {
          "type": "object",
          "properties": {
            "is_late": {
              "type": "boolean"
            },
            "late_by": {
              "description": "human-readable: \"2 days\", \"4 hours\", \"on time\"",
              "type": "string"
            }
          }
        },
        "job_id": {
          "type": "string",
          "pattern": "^JOB-[A-Za-z0-9-]+$",
          "x-ai-entity": "job",
          "x-ai-id-prefix": "JOB-",
          "x-ai-id-field": "job_id"
        },
        "notes": {
          "type": "string"
        },
        "priority": {
          "type": "string",
          "enum": [
            "low",
            "medium",
            "high",
            "urgent"
          ]
        },
        "product_id": {
          "type": "string",
          "pattern": "^P-[A-Za-z0-9-]+$",
          "x-ai-entity": "product",
          "x-ai-id-prefix": "P-",
          "x-ai-id-field": "product_id"
        },
        "quantity_completed": {
          "type": "integer"
        },
        "quantity_total": {
          "type": "integer"
        },
        "status": {
          "type": "string",
          "enum": [
            "planned",
            "scheduled",
            "running",
            "blocked",
            "paused",
            "completed",
            "cancelled"
          ]
        },
        "updated_at": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__jobs_{id}
**Description**: Get a job by ID
**Method**: GET
**Endpoint**: /jobs/{id}
**Capability Tags**: ["job", "lookup", "a", "id", "support", "optional", "field", "selection", "data", "created", "at", "deadline", "statu", "is", "late", "by", "human", "readable", "2", "day", "4", "hour", "on", "time", "note", "priority", "product", "quantity", "completed", "total", "updated", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "created_at": {
          "type": "string"
        },
        "deadline": {
          "type": "string"
        },
        "deadline_status": {
          "type": "object",
          "properties": {
            "is_late": {
              "type": "boolean"
            },
            "late_by": {
              "description": "human-readable: \"2 days\", \"4 hours\", \"on time\"",
              "type": "string"
            }
          }
        },
        "job_id": {
          "type": "string",
          "pattern": "^JOB-[A-Za-z0-9-]+$",
          "x-ai-entity": "job",
          "x-ai-id-prefix": "JOB-",
          "x-ai-id-field": "job_id"
        },
        "notes": {
          "type": "string"
        },
        "priority": {
          "type": "string",
          "enum": [
            "low",
            "medium",
            "high",
            "urgent"
          ]
        },
        "product_id": {
          "type": "string",
          "pattern": "^P-[A-Za-z0-9-]+$",
          "x-ai-entity": "product",
          "x-ai-id-prefix": "P-",
          "x-ai-id-field": "product_id"
        },
        "quantity_completed": {
          "type": "integer"
        },
        "quantity_total": {
          "type": "integer"
        },
        "status": {
          "type": "string",
          "enum": [
            "planned",
            "scheduled",
            "running",
            "blocked",
            "paused",
            "completed",
            "cancelled"
          ]
        },
        "updated_at": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## put__jobs_{id}
**Description**: Update a job
**Method**: PUT
**Endpoint**: /jobs/{id}
**Capability Tags**: ["job", "update", "a", "mutable", "field", "id", "deadline", "note", "priority", "quantity", "total", "statu", "data", "created", "at", "is", "late", "by", "human", "readable", "2", "day", "4", "hour", "on", "time", "product", "completed", "updated", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "deadline": {
      "type": "string"
    },
    "notes": {
      "type": "string"
    },
    "priority": {
      "type": "string",
      "enum": [
        "low",
        "medium",
        "high",
        "urgent"
      ]
    },
    "quantity_total": {
      "type": "integer"
    },
    "status": {
      "type": "string",
      "enum": [
        "planned",
        "scheduled",
        "running",
        "blocked",
        "paused",
        "completed",
        "cancelled"
      ]
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "deadline": "body",
    "notes": "body",
    "priority": "body",
    "quantity_total": "body",
    "status": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "deadline": {
        "type": "string"
      },
      "notes": {
        "type": "string"
      },
      "priority": {
        "type": "string",
        "enum": [
          "low",
          "medium",
          "high",
          "urgent"
        ]
      },
      "quantity_total": {
        "type": "integer"
      },
      "status": {
        "type": "string",
        "enum": [
          "planned",
          "scheduled",
          "running",
          "blocked",
          "paused",
          "completed",
          "cancelled"
        ]
      }
    }
  },
  "x-body-fields": [
    "deadline",
    "notes",
    "priority",
    "quantity_total",
    "status"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "created_at": {
          "type": "string"
        },
        "deadline": {
          "type": "string"
        },
        "deadline_status": {
          "type": "object",
          "properties": {
            "is_late": {
              "type": "boolean"
            },
            "late_by": {
              "description": "human-readable: \"2 days\", \"4 hours\", \"on time\"",
              "type": "string"
            }
          }
        },
        "job_id": {
          "type": "string",
          "pattern": "^JOB-[A-Za-z0-9-]+$",
          "x-ai-entity": "job",
          "x-ai-id-prefix": "JOB-",
          "x-ai-id-field": "job_id"
        },
        "notes": {
          "type": "string"
        },
        "priority": {
          "type": "string",
          "enum": [
            "low",
            "medium",
            "high",
            "urgent"
          ]
        },
        "product_id": {
          "type": "string",
          "pattern": "^P-[A-Za-z0-9-]+$",
          "x-ai-entity": "product",
          "x-ai-id-prefix": "P-",
          "x-ai-id-field": "product_id"
        },
        "quantity_completed": {
          "type": "integer"
        },
        "quantity_total": {
          "type": "integer"
        },
        "status": {
          "type": "string",
          "enum": [
            "planned",
            "scheduled",
            "running",
            "blocked",
            "paused",
            "completed",
            "cancelled"
          ]
        },
        "updated_at": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__jobs_{id}
**Description**: Delete a job
**Method**: DELETE
**Endpoint**: /jobs/{id}
**Capability Tags**: ["job", "delete", "a", "and", "clear", "all", "slot", "assignment", "tied", "thi", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__jobs_{id}_slots
**Description**: List slots by job ID
**Method**: GET
**Endpoint**: /jobs/{id}/slots
**Capability Tags**: ["job", "slot", "lookup", "list", "id", "data", "actual", "end", "start", "allocation", "percent", "batch", "sequence", "buffer", "time", "minute", "changeover", "cleaning", "is", "parallel", "step", "machine", "preparation", "processing", "proposal", "quantity", "planned", "scheduled", "split", "group", "statu", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "actual_end": {
            "type": "string"
          },
          "actual_start": {
            "type": "string"
          },
          "allocation_percent": {
            "type": "number"
          },
          "batch_sequence": {
            "type": "integer"
          },
          "buffer_time_minutes": {
            "type": "integer"
          },
          "changeover_time_minutes": {
            "type": "integer"
          },
          "cleaning_time_minutes": {
            "type": "integer"
          },
          "is_parallel": {
            "type": "boolean"
          },
          "job_step_id": {
            "type": "string",
            "pattern": "^JS-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "JS-",
            "x-ai-id-field": "job_step_id"
          },
          "machine_id": {
            "type": "string",
            "pattern": "^M-[A-Za-z0-9-]+$",
            "x-ai-entity": "machine",
            "x-ai-id-prefix": "M-",
            "x-ai-id-field": "machine_id"
          },
          "preparation_time_minutes": {
            "type": "integer"
          },
          "processing_time_minutes": {
            "type": "integer"
          },
          "proposal_id": {
            "type": "string",
            "pattern": "^AIPROP-[A-Za-z0-9-]+$",
            "x-ai-entity": "proposal",
            "x-ai-id-prefix": "AIPROP-",
            "x-ai-id-field": "proposal_id"
          },
          "quantity_planned": {
            "type": "integer"
          },
          "scheduled_end": {
            "type": "string"
          },
          "scheduled_start": {
            "type": "string"
          },
          "slot_id": {
            "type": "string",
            "pattern": "^SLOT-[A-Za-z0-9-]+$",
            "x-ai-entity": "slot",
            "x-ai-id-prefix": "SLOT-",
            "x-ai-id-field": "slot_id"
          },
          "split_group_id": {
            "type": "string"
          },
          "status": {
            "type": "string",
            "enum": [
              "planned",
              "running",
              "completed",
              "cancelled",
              "paused"
            ]
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__machines
**Description**: List all machines
**Method**: GET
**Endpoint**: /machines
**Capability Tags**: ["machine", "list", "all", "retrieve", "a", "optional", "filter", "sorting", "and", "pagination", "statu", "name", "type", "location", "sort", "by", "dir", "limit", "offset", "field", "data", "capacityperhour", "defaultchangeovertime", "defaultcleaningtime", "defaultsetuptime", "lastmaintenancedate", "machineid", "machinename", "machinetype", "cnc", "press", "coating", "etc", "maintenanceintervalday", "utilizationrate", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": [
        "idle",
        "running",
        "maintenance",
        "offline"
      ]
    },
    "machine_name": {
      "type": "string"
    },
    "machine_type": {
      "type": "string"
    },
    "location": {
      "type": "string"
    },
    "sort_by": {
      "type": "string",
      "enum": [
        "machine_id",
        "machine_name",
        "machine_type",
        "status",
        "location",
        "capacity_per_hour",
        "utilization_rate",
        "last_maintenance_date",
        "created_at"
      ]
    },
    "sort_dir": {
      "type": "string",
      "enum": [
        "asc",
        "desc"
      ]
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "status",
    "machine_name",
    "machine_type",
    "location",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "status": "query",
    "machine_name": "query",
    "machine_type": "query",
    "location": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "capacityPerHour": {
            "type": "integer"
          },
          "defaultChangeoverTime": {
            "type": "integer"
          },
          "defaultCleaningTime": {
            "type": "integer"
          },
          "defaultSetupTime": {
            "type": "integer"
          },
          "lastMaintenanceDate": {
            "type": "string"
          },
          "location": {
            "type": "string"
          },
          "machineID": {
            "type": "string"
          },
          "machineName": {
            "type": "string"
          },
          "machineType": {
            "description": "CNC / Press / Coating etc",
            "type": "string"
          },
          "maintenanceIntervalDays": {
            "type": "integer"
          },
          "status": {
            "type": "string",
            "enum": [
              "idle",
              "running",
              "maintenance",
              "offline"
            ]
          },
          "utilizationRate": {
            "type": "number"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__machines
**Description**: Create a machine
**Method**: POST
**Endpoint**: /machines
**Capability Tags**: ["machine", "create", "a", "new", "the", "factory", "id", "is", "generated", "m", "prefix", "when", "omitted", "capacity", "per", "hour", "default", "changeover", "time", "cleaning", "setup", "location", "optional", "with", "name", "type", "maintenance", "interval", "day", "data", "capacityperhour", "defaultchangeovertime", "defaultcleaningtime", "defaultsetuptime", "lastmaintenancedate", "machineid", "machinename", "machinetype", "cnc", "press", "coating", "etc", "maintenanceintervalday", "statu", "utilizationrate", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "capacity_per_hour": {
      "type": "integer"
    },
    "default_changeover_time": {
      "type": "integer"
    },
    "default_cleaning_time": {
      "type": "integer"
    },
    "default_setup_time": {
      "type": "integer"
    },
    "location": {
      "type": "string"
    },
    "machine_id": {
      "description": "Optional; generated with M- prefix when omitted.",
      "type": "string",
      "pattern": "^M-[A-Za-z0-9-]+$",
      "x-ai-entity": "machine",
      "x-ai-id-prefix": "M-",
      "x-ai-id-field": "machine_id",
      "x-ai-generated": true
    },
    "machine_name": {
      "type": "string"
    },
    "machine_type": {
      "type": "string"
    },
    "maintenance_interval_days": {
      "type": "integer"
    }
  },
  "required": [
    "machine_name",
    "machine_type"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "capacity_per_hour": "body",
    "default_changeover_time": "body",
    "default_cleaning_time": "body",
    "default_setup_time": "body",
    "location": "body",
    "machine_id": "body",
    "machine_name": "body",
    "machine_type": "body",
    "maintenance_interval_days": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "machine_name",
      "machine_type"
    ],
    "properties": {
      "capacity_per_hour": {
        "type": "integer"
      },
      "default_changeover_time": {
        "type": "integer"
      },
      "default_cleaning_time": {
        "type": "integer"
      },
      "default_setup_time": {
        "type": "integer"
      },
      "location": {
        "type": "string"
      },
      "machine_id": {
        "description": "Optional; generated with M- prefix when omitted.",
        "type": "string",
        "pattern": "^M-[A-Za-z0-9-]+$",
        "x-ai-entity": "machine",
        "x-ai-id-prefix": "M-",
        "x-ai-id-field": "machine_id",
        "x-ai-generated": true
      },
      "machine_name": {
        "type": "string"
      },
      "machine_type": {
        "type": "string"
      },
      "maintenance_interval_days": {
        "type": "integer"
      }
    }
  },
  "x-body-fields": [
    "capacity_per_hour",
    "default_changeover_time",
    "default_cleaning_time",
    "default_setup_time",
    "location",
    "machine_id",
    "machine_name",
    "machine_type",
    "maintenance_interval_days"
  ],
  "x-body-required": [
    "machine_name",
    "machine_type"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "capacityPerHour": {
          "type": "integer"
        },
        "defaultChangeoverTime": {
          "type": "integer"
        },
        "defaultCleaningTime": {
          "type": "integer"
        },
        "defaultSetupTime": {
          "type": "integer"
        },
        "lastMaintenanceDate": {
          "type": "string"
        },
        "location": {
          "type": "string"
        },
        "machineID": {
          "type": "string"
        },
        "machineName": {
          "type": "string"
        },
        "machineType": {
          "description": "CNC / Press / Coating etc",
          "type": "string"
        },
        "maintenanceIntervalDays": {
          "type": "integer"
        },
        "status": {
          "type": "string",
          "enum": [
            "idle",
            "running",
            "maintenance",
            "offline"
          ]
        },
        "utilizationRate": {
          "type": "number"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__machines_downtime
**Description**: Record downtime
**Method**: POST
**Endpoint**: /machines/downtime
**Capability Tags**: ["machine", "downtime", "create", "record", "cause", "end", "time", "job", "step", "slot", "id", "start", "data", "downtimeid", "durationminute", "endtime", "jobstepslotid", "machineid", "starttime", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "cause": {
      "type": "string"
    },
    "end_time": {
      "type": "string"
    },
    "job_step_slot_id": {
      "type": "string"
    },
    "machine_id": {
      "type": "string",
      "pattern": "^M-[A-Za-z0-9-]+$",
      "x-ai-entity": "machine",
      "x-ai-id-prefix": "M-",
      "x-ai-id-field": "machine_id"
    },
    "start_time": {
      "type": "string"
    }
  },
  "required": [
    "machine_id"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "cause": "body",
    "end_time": "body",
    "job_step_slot_id": "body",
    "machine_id": "body",
    "start_time": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "machine_id"
    ],
    "properties": {
      "cause": {
        "type": "string"
      },
      "end_time": {
        "type": "string"
      },
      "job_step_slot_id": {
        "type": "string"
      },
      "machine_id": {
        "type": "string",
        "pattern": "^M-[A-Za-z0-9-]+$",
        "x-ai-entity": "machine",
        "x-ai-id-prefix": "M-",
        "x-ai-id-field": "machine_id"
      },
      "start_time": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "cause",
    "end_time",
    "job_step_slot_id",
    "machine_id",
    "start_time"
  ],
  "x-body-required": [
    "machine_id"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "cause": {
          "type": "string"
        },
        "downtimeID": {
          "type": "string"
        },
        "durationMinutes": {
          "type": "integer"
        },
        "endTime": {
          "type": "string"
        },
        "jobStepSlotID": {
          "type": "string"
        },
        "machineID": {
          "type": "string"
        },
        "startTime": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__machines_maintenance-alerts
**Description**: Get maintenance alerts
**Method**: GET
**Endpoint**: /machines/maintenance-alerts
**Capability Tags**: ["machine", "maintenance", "alert", "list", "data", "capacityperhour", "defaultchangeovertime", "defaultcleaningtime", "defaultsetuptime", "lastmaintenancedate", "location", "machineid", "machinename", "machinetype", "cnc", "press", "coating", "etc", "maintenanceintervalday", "statu", "utilizationrate", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "capacityPerHour": {
            "type": "integer"
          },
          "defaultChangeoverTime": {
            "type": "integer"
          },
          "defaultCleaningTime": {
            "type": "integer"
          },
          "defaultSetupTime": {
            "type": "integer"
          },
          "lastMaintenanceDate": {
            "type": "string"
          },
          "location": {
            "type": "string"
          },
          "machineID": {
            "type": "string"
          },
          "machineName": {
            "type": "string"
          },
          "machineType": {
            "description": "CNC / Press / Coating etc",
            "type": "string"
          },
          "maintenanceIntervalDays": {
            "type": "integer"
          },
          "status": {
            "type": "string",
            "enum": [
              "idle",
              "running",
              "maintenance",
              "offline"
            ]
          },
          "utilizationRate": {
            "type": "number"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__machines_reroute-recommendations
**Description**: Get reroute recommendations
**Method**: GET
**Endpoint**: /machines/reroute-recommendations
**Capability Tags**: ["machine", "reroute", "recommendation", "list", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "machine_id": {
      "type": "string"
    }
  },
  "required": [
    "machine_id"
  ],
  "x-path-params": [],
  "x-query-params": [
    "machine_id"
  ],
  "x-param-sources": {
    "machine_id": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": {
        "type": "array",
        "items": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__machines_utilization
**Description**: Get utilization
**Method**: GET
**Endpoint**: /machines/utilization
**Capability Tags**: ["machine", "utilization", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__machines_{id}
**Description**: Get machine by ID
**Method**: GET
**Endpoint**: /machines/{id}
**Capability Tags**: ["machine", "lookup", "id", "retrieve", "detail", "a", "specific", "support", "optional", "field", "selection", "data", "capacityperhour", "defaultchangeovertime", "defaultcleaningtime", "defaultsetuptime", "lastmaintenancedate", "location", "machineid", "machinename", "machinetype", "cnc", "press", "coating", "etc", "maintenanceintervalday", "statu", "utilizationrate", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "capacityPerHour": {
          "type": "integer"
        },
        "defaultChangeoverTime": {
          "type": "integer"
        },
        "defaultCleaningTime": {
          "type": "integer"
        },
        "defaultSetupTime": {
          "type": "integer"
        },
        "lastMaintenanceDate": {
          "type": "string"
        },
        "location": {
          "type": "string"
        },
        "machineID": {
          "type": "string"
        },
        "machineName": {
          "type": "string"
        },
        "machineType": {
          "description": "CNC / Press / Coating etc",
          "type": "string"
        },
        "maintenanceIntervalDays": {
          "type": "integer"
        },
        "status": {
          "type": "string",
          "enum": [
            "idle",
            "running",
            "maintenance",
            "offline"
          ]
        },
        "utilizationRate": {
          "type": "number"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## put__machines_{id}
**Description**: Update a machine
**Method**: PUT
**Endpoint**: /machines/{id}
**Capability Tags**: ["machine", "update", "a", "an", "existing", "s", "detail", "id", "capacity", "per", "hour", "default", "changeover", "time", "cleaning", "setup", "location", "name", "type", "maintenance", "interval", "day", "statu", "data", "capacityperhour", "defaultchangeovertime", "defaultcleaningtime", "defaultsetuptime", "lastmaintenancedate", "machineid", "machinename", "machinetype", "cnc", "press", "coating", "etc", "maintenanceintervalday", "utilizationrate", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "capacity_per_hour": {
      "type": "integer"
    },
    "default_changeover_time": {
      "type": "integer"
    },
    "default_cleaning_time": {
      "type": "integer"
    },
    "default_setup_time": {
      "type": "integer"
    },
    "location": {
      "type": "string"
    },
    "machine_name": {
      "type": "string"
    },
    "machine_type": {
      "type": "string"
    },
    "maintenance_interval_days": {
      "type": "integer"
    },
    "status": {
      "type": "string",
      "enum": [
        "idle",
        "running",
        "maintenance",
        "offline"
      ]
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "capacity_per_hour": "body",
    "default_changeover_time": "body",
    "default_cleaning_time": "body",
    "default_setup_time": "body",
    "location": "body",
    "machine_name": "body",
    "machine_type": "body",
    "maintenance_interval_days": "body",
    "status": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "capacity_per_hour": {
        "type": "integer"
      },
      "default_changeover_time": {
        "type": "integer"
      },
      "default_cleaning_time": {
        "type": "integer"
      },
      "default_setup_time": {
        "type": "integer"
      },
      "location": {
        "type": "string"
      },
      "machine_name": {
        "type": "string"
      },
      "machine_type": {
        "type": "string"
      },
      "maintenance_interval_days": {
        "type": "integer"
      },
      "status": {
        "type": "string",
        "enum": [
          "idle",
          "running",
          "maintenance",
          "offline"
        ]
      }
    }
  },
  "x-body-fields": [
    "capacity_per_hour",
    "default_changeover_time",
    "default_cleaning_time",
    "default_setup_time",
    "location",
    "machine_name",
    "machine_type",
    "maintenance_interval_days",
    "status"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "capacityPerHour": {
          "type": "integer"
        },
        "defaultChangeoverTime": {
          "type": "integer"
        },
        "defaultCleaningTime": {
          "type": "integer"
        },
        "defaultSetupTime": {
          "type": "integer"
        },
        "lastMaintenanceDate": {
          "type": "string"
        },
        "location": {
          "type": "string"
        },
        "machineID": {
          "type": "string"
        },
        "machineName": {
          "type": "string"
        },
        "machineType": {
          "description": "CNC / Press / Coating etc",
          "type": "string"
        },
        "maintenanceIntervalDays": {
          "type": "integer"
        },
        "status": {
          "type": "string",
          "enum": [
            "idle",
            "running",
            "maintenance",
            "offline"
          ]
        },
        "utilizationRate": {
          "type": "number"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__machines_{id}_capabilities
**Description**: Assign a capability to a machine
**Method**: POST
**Endpoint**: /machines/{id}/capabilities
**Capability Tags**: ["machine", "capability", "create", "assign", "a", "id", "efficiency", "factor", "step", "data", "capabilityid", "efficiencyfactor", "speed", "modifier", "for", "thi", "machineid", "stepid", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "efficiency_factor": {
      "type": "number"
    },
    "step_id": {
      "type": "string",
      "pattern": "^STP-[A-Za-z0-9-]+$",
      "x-ai-entity": "step",
      "x-ai-id-prefix": "STP-",
      "x-ai-id-field": "step_id"
    }
  },
  "required": [
    "id",
    "step_id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "efficiency_factor": "body",
    "step_id": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "step_id"
    ],
    "properties": {
      "efficiency_factor": {
        "type": "number"
      },
      "step_id": {
        "type": "string",
        "pattern": "^STP-[A-Za-z0-9-]+$",
        "x-ai-entity": "step",
        "x-ai-id-prefix": "STP-",
        "x-ai-id-field": "step_id"
      }
    }
  },
  "x-body-fields": [
    "efficiency_factor",
    "step_id"
  ],
  "x-body-required": [
    "step_id"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "capabilityID": {
          "type": "string"
        },
        "efficiencyFactor": {
          "description": "speed modifier for this step",
          "type": "number"
        },
        "machineID": {
          "type": "string"
        },
        "stepID": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__maintenance
**Description**: Record maintenance
**Method**: POST
**Endpoint**: /maintenance
**Capability Tags**: ["maintenance", "create", "record", "description", "end", "time", "machine", "id", "type", "start", "technician", "data", "endtime", "machineid", "maintenanceid", "maintenancetype", "starttime", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string"
    },
    "end_time": {
      "type": "string"
    },
    "machine_id": {
      "type": "string",
      "pattern": "^M-[A-Za-z0-9-]+$",
      "x-ai-entity": "machine",
      "x-ai-id-prefix": "M-",
      "x-ai-id-field": "machine_id"
    },
    "maintenance_type": {
      "type": "string"
    },
    "start_time": {
      "type": "string"
    },
    "technician": {
      "type": "string"
    }
  },
  "required": [
    "machine_id"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "description": "body",
    "end_time": "body",
    "machine_id": "body",
    "maintenance_type": "body",
    "start_time": "body",
    "technician": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "machine_id"
    ],
    "properties": {
      "description": {
        "type": "string"
      },
      "end_time": {
        "type": "string"
      },
      "machine_id": {
        "type": "string",
        "pattern": "^M-[A-Za-z0-9-]+$",
        "x-ai-entity": "machine",
        "x-ai-id-prefix": "M-",
        "x-ai-id-field": "machine_id"
      },
      "maintenance_type": {
        "type": "string"
      },
      "start_time": {
        "type": "string"
      },
      "technician": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "description",
    "end_time",
    "machine_id",
    "maintenance_type",
    "start_time",
    "technician"
  ],
  "x-body-required": [
    "machine_id"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "description": {
          "type": "string"
        },
        "endTime": {
          "type": "string"
        },
        "machineID": {
          "type": "string"
        },
        "maintenanceID": {
          "type": "string"
        },
        "maintenanceType": {
          "type": "string"
        },
        "startTime": {
          "type": "string"
        },
        "technician": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__predictive_confidence
**Description**: Confidence
**Method**: GET
**Endpoint**: /predictive/confidence
**Capability Tags**: ["predictive", "confidence", "list", "data", "pct", "last", "trained", "model", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "confidence_pct": {
          "type": "number"
        },
        "last_trained": {
          "type": "string"
        },
        "model": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__predictive_forecast
**Description**: Forecast
**Method**: GET
**Endpoint**: /predictive/forecast
**Capability Tags**: ["predictive", "forecast", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__predictive_high-risk-jobs
**Description**: List high-risk jobs
**Method**: GET
**Endpoint**: /predictive/high-risk-jobs
**Capability Tags**: ["predictive", "high", "risk", "job", "list", "data", "delay", "minute", "issue", "id", "machine", "name", "level", "score", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "delay_minutes": {
            "type": "integer"
          },
          "issue": {
            "type": "string"
          },
          "job_id": {
            "type": "string",
            "pattern": "^JOB-[A-Za-z0-9-]+$",
            "x-ai-entity": "job",
            "x-ai-id-prefix": "JOB-",
            "x-ai-id-field": "job_id"
          },
          "machine_name": {
            "type": "string"
          },
          "risk_level": {
            "type": "string"
          },
          "risk_score": {
            "type": "number"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__predictive_recommendations
**Description**: List recommendations
**Method**: GET
**Endpoint**: /predictive/recommendations
**Capability Tags**: ["predictive", "recommendation", "list", "data", "action", "icon", "severity", "title", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "action": {
            "type": "string"
          },
          "icon": {
            "type": "string"
          },
          "severity": {
            "type": "string"
          },
          "title": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__process-steps_{step_id}_materials
**Description**: List materials for a step
**Method**: GET
**Endpoint**: /process-steps/{step_id}/materials
**Capability Tags**: ["process", "step", "material", "lookup", "list", "a", "id", "role", "data", "materialid", "productid", "quantityperunit", "input", "output", "stepid", "unit", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "step_id": {
      "type": "string"
    },
    "role": {
      "type": "string"
    }
  },
  "required": [
    "role",
    "step_id"
  ],
  "x-path-params": [
    "step_id"
  ],
  "x-query-params": [
    "role"
  ],
  "x-param-sources": {
    "step_id": "path",
    "role": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "materialID": {
            "type": "string"
          },
          "productID": {
            "type": "string"
          },
          "quantityPerUnit": {
            "type": "number"
          },
          "role": {
            "description": "input | output",
            "type": "string"
          },
          "stepID": {
            "type": "string"
          },
          "unit": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__process-steps_{step_id}_materials
**Description**: Add a material to a step
**Method**: POST
**Endpoint**: /process-steps/{step_id}/materials
**Capability Tags**: ["process", "step", "material", "create", "add", "a", "id", "required", "if", "product", "not", "set", "quantity", "per", "unit", "role", "input", "or", "output", "data", "materialid", "productid", "quantityperunit", "stepid", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "step_id": {
      "type": "string"
    },
    "material_id": {
      "description": "required if product_id not set",
      "type": "string",
      "pattern": "^MAT-[A-Za-z0-9-]+$",
      "x-ai-entity": "inventory",
      "x-ai-id-prefix": "MAT-",
      "x-ai-id-field": "material_id"
    },
    "product_id": {
      "description": "required if material_id not set",
      "type": "string",
      "pattern": "^P-[A-Za-z0-9-]+$",
      "x-ai-entity": "product",
      "x-ai-id-prefix": "P-",
      "x-ai-id-field": "product_id"
    },
    "quantity_per_unit": {
      "description": "required",
      "type": "number"
    },
    "role": {
      "description": "\"input\" or \"output\"",
      "type": "string"
    },
    "unit": {
      "type": "string"
    }
  },
  "required": [
    "step_id"
  ],
  "x-path-params": [
    "step_id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "step_id": "path",
    "material_id": "body",
    "product_id": "body",
    "quantity_per_unit": "body",
    "role": "body",
    "unit": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "material_id": {
        "description": "required if product_id not set",
        "type": "string",
        "pattern": "^MAT-[A-Za-z0-9-]+$",
        "x-ai-entity": "inventory",
        "x-ai-id-prefix": "MAT-",
        "x-ai-id-field": "material_id"
      },
      "product_id": {
        "description": "required if material_id not set",
        "type": "string",
        "pattern": "^P-[A-Za-z0-9-]+$",
        "x-ai-entity": "product",
        "x-ai-id-prefix": "P-",
        "x-ai-id-field": "product_id"
      },
      "quantity_per_unit": {
        "description": "required",
        "type": "number"
      },
      "role": {
        "description": "\"input\" or \"output\"",
        "type": "string"
      },
      "unit": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "material_id",
    "product_id",
    "quantity_per_unit",
    "role",
    "unit"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        },
        "materialID": {
          "type": "string"
        },
        "productID": {
          "type": "string"
        },
        "quantityPerUnit": {
          "type": "number"
        },
        "role": {
          "description": "input | output",
          "type": "string"
        },
        "stepID": {
          "type": "string"
        },
        "unit": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__process-steps_{step_id}_materials_{id}
**Description**: Delete a material from a step
**Method**: DELETE
**Endpoint**: /process-steps/{step_id}/materials/{id}
**Capability Tags**: ["process", "step", "material", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "step_id": {
      "type": "string"
    },
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id",
    "step_id"
  ],
  "x-path-params": [
    "step_id",
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "step_id": "path",
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__processes
**Description**: List processes
**Method**: GET
**Endpoint**: /processes
**Capability Tags**: ["process", "list", "optional", "filter", "sorting", "and", "pagination", "product", "id", "sort", "by", "dir", "limit", "offset", "field", "data", "description", "effectivefrom", "effectiveto", "isprimary", "primary", "vs", "alternative", "routing", "processid", "processname", "productid", "sequence", "order", "when", "multiple", "0", "version", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "product_id": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    },
    "sort_dir": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "product_id",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "product_id": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "description": {
            "type": "string"
          },
          "effectiveFrom": {
            "type": "string"
          },
          "effectiveTo": {
            "type": "string"
          },
          "isPrimary": {
            "description": "primary vs alternative routing",
            "type": "boolean"
          },
          "processID": {
            "type": "string"
          },
          "processName": {
            "type": "string"
          },
          "productID": {
            "type": "string"
          },
          "sequence": {
            "description": "order when multiple (0=primary)",
            "type": "integer"
          },
          "version": {
            "type": "integer"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__processes
**Description**: Create a process
**Method**: POST
**Endpoint**: /processes
**Capability Tags**: ["process", "create", "a", "id", "is", "generated", "the", "prc", "prefix", "when", "omitted", "description", "optional", "with", "name", "product", "version", "data", "effectivefrom", "effectiveto", "isprimary", "primary", "vs", "alternative", "routing", "processid", "processname", "productid", "sequence", "order", "multiple", "0", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string"
    },
    "process_id": {
      "description": "Optional; generated with PRC- prefix when omitted.",
      "type": "string",
      "pattern": "^PRC-[A-Za-z0-9-]+$",
      "x-ai-entity": "process",
      "x-ai-id-prefix": "PRC-",
      "x-ai-id-field": "process_id",
      "x-ai-generated": true
    },
    "process_name": {
      "type": "string"
    },
    "product_id": {
      "type": "string",
      "pattern": "^P-[A-Za-z0-9-]+$",
      "x-ai-entity": "product",
      "x-ai-id-prefix": "P-",
      "x-ai-id-field": "product_id"
    },
    "version": {
      "type": "integer"
    }
  },
  "required": [
    "process_name",
    "product_id"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "description": "body",
    "process_id": "body",
    "process_name": "body",
    "product_id": "body",
    "version": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "process_name",
      "product_id"
    ],
    "properties": {
      "description": {
        "type": "string"
      },
      "process_id": {
        "description": "Optional; generated with PRC- prefix when omitted.",
        "type": "string",
        "pattern": "^PRC-[A-Za-z0-9-]+$",
        "x-ai-entity": "process",
        "x-ai-id-prefix": "PRC-",
        "x-ai-id-field": "process_id",
        "x-ai-generated": true
      },
      "process_name": {
        "type": "string"
      },
      "product_id": {
        "type": "string",
        "pattern": "^P-[A-Za-z0-9-]+$",
        "x-ai-entity": "product",
        "x-ai-id-prefix": "P-",
        "x-ai-id-field": "product_id"
      },
      "version": {
        "type": "integer"
      }
    }
  },
  "x-body-fields": [
    "description",
    "process_id",
    "process_name",
    "product_id",
    "version"
  ],
  "x-body-required": [
    "process_name",
    "product_id"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "description": {
          "type": "string"
        },
        "effectiveFrom": {
          "type": "string"
        },
        "effectiveTo": {
          "type": "string"
        },
        "isPrimary": {
          "description": "primary vs alternative routing",
          "type": "boolean"
        },
        "processID": {
          "type": "string"
        },
        "processName": {
          "type": "string"
        },
        "productID": {
          "type": "string"
        },
        "sequence": {
          "description": "order when multiple (0=primary)",
          "type": "integer"
        },
        "version": {
          "type": "integer"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__processes_product_{id}
**Description**: Get a process by product ID
**Method**: GET
**Endpoint**: /processes/product/{id}
**Capability Tags**: ["process", "product", "lookup", "a", "id", "support", "optional", "field", "selection", "data", "description", "effectivefrom", "effectiveto", "isprimary", "primary", "vs", "alternative", "routing", "processid", "processname", "productid", "sequence", "order", "when", "multiple", "0", "version", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "description": {
          "type": "string"
        },
        "effectiveFrom": {
          "type": "string"
        },
        "effectiveTo": {
          "type": "string"
        },
        "isPrimary": {
          "description": "primary vs alternative routing",
          "type": "boolean"
        },
        "processID": {
          "type": "string"
        },
        "processName": {
          "type": "string"
        },
        "productID": {
          "type": "string"
        },
        "sequence": {
          "description": "order when multiple (0=primary)",
          "type": "integer"
        },
        "version": {
          "type": "integer"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__processes_{id}
**Description**: Get a process by ID
**Method**: GET
**Endpoint**: /processes/{id}
**Capability Tags**: ["process", "lookup", "a", "id", "support", "optional", "field", "selection", "data", "description", "effectivefrom", "effectiveto", "isprimary", "primary", "vs", "alternative", "routing", "processid", "processname", "productid", "sequence", "order", "when", "multiple", "0", "version", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "description": {
          "type": "string"
        },
        "effectiveFrom": {
          "type": "string"
        },
        "effectiveTo": {
          "type": "string"
        },
        "isPrimary": {
          "description": "primary vs alternative routing",
          "type": "boolean"
        },
        "processID": {
          "type": "string"
        },
        "processName": {
          "type": "string"
        },
        "productID": {
          "type": "string"
        },
        "sequence": {
          "description": "order when multiple (0=primary)",
          "type": "integer"
        },
        "version": {
          "type": "integer"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__processes_{id}
**Description**: Delete a process
**Method**: DELETE
**Endpoint**: /processes/{id}
**Capability Tags**: ["process", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__processes_{id}_steps
**Description**: List steps by process ID
**Method**: GET
**Endpoint**: /processes/{id}/steps
**Capability Tags**: ["process", "step", "lookup", "list", "id", "support", "optional", "field", "selection", "data", "allow", "parallel", "execution", "batch", "size", "0", "no", "constraint", "default", "changeover", "time", "minute", "cleaning", "preparation", "processing", "is", "true", "if", "run", "in", "batche", "machine", "type", "required", "max", "min", "minimum", "when", "splitting", "split", "qty", "wait", "e", "g", "cooling", "before", "next", "note", "predecessor", "ids", "json", "array", "of", "empty", "infer", "from", "stepsequence", "quality", "check", "name", "sequence", "matche", "reference", "transfer", "transport", "to", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "allow_parallel_execution": {
            "type": "boolean"
          },
          "batch_size": {
            "description": "0 = no batch constraint",
            "type": "integer"
          },
          "default_changeover_time": {
            "description": "minutes",
            "type": "integer"
          },
          "default_cleaning_time": {
            "description": "minutes",
            "type": "integer"
          },
          "default_preparation_time": {
            "description": "minutes",
            "type": "integer"
          },
          "default_processing_time": {
            "description": "minutes",
            "type": "integer"
          },
          "is_batch_process": {
            "description": "true if step runs in batches",
            "type": "boolean"
          },
          "machine_type_required": {
            "type": "string"
          },
          "max_parallel_machines": {
            "type": "integer"
          },
          "min_batch_size": {
            "description": "minimum batch when splitting",
            "type": "integer"
          },
          "min_split_qty": {
            "type": "integer"
          },
          "min_wait_minutes": {
            "description": "e.g. cooling time before next step",
            "type": "integer"
          },
          "notes": {
            "type": "string"
          },
          "predecessor_step_ids": {
            "description": "JSON array of step_ids; empty = infer from StepSequence",
            "type": "string"
          },
          "process_id": {
            "type": "string",
            "pattern": "^PRC-[A-Za-z0-9-]+$",
            "x-ai-entity": "process",
            "x-ai-id-prefix": "PRC-",
            "x-ai-id-field": "process_id"
          },
          "quality_check_required": {
            "type": "boolean"
          },
          "step_id": {
            "type": "string",
            "pattern": "^STP-[A-Za-z0-9-]+$",
            "x-ai-entity": "step",
            "x-ai-id-prefix": "STP-",
            "x-ai-id-field": "step_id"
          },
          "step_name": {
            "type": "string"
          },
          "step_sequence": {
            "type": "integer"
          },
          "step_type": {
            "description": "matches reference_step_types.name",
            "type": "string"
          },
          "transfer_batch_size": {
            "type": "integer"
          },
          "transfer_minutes": {
            "description": "transport time to next step",
            "type": "integer"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__processes_{id}_steps
**Description**: Add a step to a process
**Method**: POST
**Endpoint**: /processes/{id}/steps
**Capability Tags**: ["process", "step", "create", "add", "a", "id", "allow", "parallel", "execution", "default", "changeover", "time", "cleaning", "preparation", "processing", "machine", "type", "required", "max", "min", "split", "qty", "note", "quality", "check", "name", "sequence", "transfer", "batch", "size", "data", "0", "no", "constraint", "minute", "is", "true", "if", "run", "in", "batche", "minimum", "when", "splitting", "wait", "e", "g", "cooling", "before", "next", "predecessor", "ids", "json", "array", "of", "empty", "infer", "from", "stepsequence", "matche", "reference", "transport", "to", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "allow_parallel_execution": {
      "type": "boolean"
    },
    "default_changeover_time": {
      "type": "integer"
    },
    "default_cleaning_time": {
      "type": "integer"
    },
    "default_preparation_time": {
      "type": "integer"
    },
    "default_processing_time": {
      "type": "integer"
    },
    "machine_type_required": {
      "type": "string"
    },
    "max_parallel_machines": {
      "type": "integer"
    },
    "min_split_qty": {
      "type": "integer"
    },
    "notes": {
      "type": "string"
    },
    "quality_check_required": {
      "type": "boolean"
    },
    "step_id": {
      "type": "string",
      "pattern": "^STP-[A-Za-z0-9-]+$",
      "x-ai-entity": "step",
      "x-ai-id-prefix": "STP-",
      "x-ai-id-field": "step_id"
    },
    "step_name": {
      "type": "string"
    },
    "step_sequence": {
      "type": "integer"
    },
    "step_type": {
      "type": "string"
    },
    "transfer_batch_size": {
      "type": "integer"
    }
  },
  "required": [
    "id",
    "step_name"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "allow_parallel_execution": "body",
    "default_changeover_time": "body",
    "default_cleaning_time": "body",
    "default_preparation_time": "body",
    "default_processing_time": "body",
    "machine_type_required": "body",
    "max_parallel_machines": "body",
    "min_split_qty": "body",
    "notes": "body",
    "quality_check_required": "body",
    "step_id": "body",
    "step_name": "body",
    "step_sequence": "body",
    "step_type": "body",
    "transfer_batch_size": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "step_name"
    ],
    "properties": {
      "allow_parallel_execution": {
        "type": "boolean"
      },
      "default_changeover_time": {
        "type": "integer"
      },
      "default_cleaning_time": {
        "type": "integer"
      },
      "default_preparation_time": {
        "type": "integer"
      },
      "default_processing_time": {
        "type": "integer"
      },
      "machine_type_required": {
        "type": "string"
      },
      "max_parallel_machines": {
        "type": "integer"
      },
      "min_split_qty": {
        "type": "integer"
      },
      "notes": {
        "type": "string"
      },
      "quality_check_required": {
        "type": "boolean"
      },
      "step_id": {
        "type": "string",
        "pattern": "^STP-[A-Za-z0-9-]+$",
        "x-ai-entity": "step",
        "x-ai-id-prefix": "STP-",
        "x-ai-id-field": "step_id"
      },
      "step_name": {
        "type": "string"
      },
      "step_sequence": {
        "type": "integer"
      },
      "step_type": {
        "type": "string"
      },
      "transfer_batch_size": {
        "type": "integer"
      }
    }
  },
  "x-body-fields": [
    "allow_parallel_execution",
    "default_changeover_time",
    "default_cleaning_time",
    "default_preparation_time",
    "default_processing_time",
    "machine_type_required",
    "max_parallel_machines",
    "min_split_qty",
    "notes",
    "quality_check_required",
    "step_id",
    "step_name",
    "step_sequence",
    "step_type",
    "transfer_batch_size"
  ],
  "x-body-required": [
    "step_name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "allow_parallel_execution": {
          "type": "boolean"
        },
        "batch_size": {
          "description": "0 = no batch constraint",
          "type": "integer"
        },
        "default_changeover_time": {
          "description": "minutes",
          "type": "integer"
        },
        "default_cleaning_time": {
          "description": "minutes",
          "type": "integer"
        },
        "default_preparation_time": {
          "description": "minutes",
          "type": "integer"
        },
        "default_processing_time": {
          "description": "minutes",
          "type": "integer"
        },
        "is_batch_process": {
          "description": "true if step runs in batches",
          "type": "boolean"
        },
        "machine_type_required": {
          "type": "string"
        },
        "max_parallel_machines": {
          "type": "integer"
        },
        "min_batch_size": {
          "description": "minimum batch when splitting",
          "type": "integer"
        },
        "min_split_qty": {
          "type": "integer"
        },
        "min_wait_minutes": {
          "description": "e.g. cooling time before next step",
          "type": "integer"
        },
        "notes": {
          "type": "string"
        },
        "predecessor_step_ids": {
          "description": "JSON array of step_ids; empty = infer from StepSequence",
          "type": "string"
        },
        "process_id": {
          "type": "string",
          "pattern": "^PRC-[A-Za-z0-9-]+$",
          "x-ai-entity": "process",
          "x-ai-id-prefix": "PRC-",
          "x-ai-id-field": "process_id"
        },
        "quality_check_required": {
          "type": "boolean"
        },
        "step_id": {
          "type": "string",
          "pattern": "^STP-[A-Za-z0-9-]+$",
          "x-ai-entity": "step",
          "x-ai-id-prefix": "STP-",
          "x-ai-id-field": "step_id"
        },
        "step_name": {
          "type": "string"
        },
        "step_sequence": {
          "type": "integer"
        },
        "step_type": {
          "description": "matches reference_step_types.name",
          "type": "string"
        },
        "transfer_batch_size": {
          "type": "integer"
        },
        "transfer_minutes": {
          "description": "transport time to next step",
          "type": "integer"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__production-log
**Description**: Log production
**Method**: POST
**Endpoint**: /production-log
**Capability Tags**: ["production", "log", "create", "downtime", "minute", "gap", "7", "during", "slot", "for", "oee", "end", "time", "operator", "note", "quantity", "produced", "scrap", "id", "start", "data", "downtimeminute", "endtime", "operatornote", "productionid", "quantityproduced", "quantityscrap", "slotid", "starttime", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "downtime_minutes": {
      "description": "Gap 7 - downtime during slot for OEE",
      "type": "integer"
    },
    "end_time": {
      "type": "string"
    },
    "operator_notes": {
      "type": "string"
    },
    "quantity_produced": {
      "type": "integer"
    },
    "quantity_scrap": {
      "type": "integer"
    },
    "slot_id": {
      "type": "string",
      "pattern": "^SLOT-[A-Za-z0-9-]+$",
      "x-ai-entity": "slot",
      "x-ai-id-prefix": "SLOT-",
      "x-ai-id-field": "slot_id"
    },
    "start_time": {
      "type": "string"
    }
  },
  "required": [
    "slot_id"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "downtime_minutes": "body",
    "end_time": "body",
    "operator_notes": "body",
    "quantity_produced": "body",
    "quantity_scrap": "body",
    "slot_id": "body",
    "start_time": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "slot_id"
    ],
    "properties": {
      "downtime_minutes": {
        "description": "Gap 7 - downtime during slot for OEE",
        "type": "integer"
      },
      "end_time": {
        "type": "string"
      },
      "operator_notes": {
        "type": "string"
      },
      "quantity_produced": {
        "type": "integer"
      },
      "quantity_scrap": {
        "type": "integer"
      },
      "slot_id": {
        "type": "string",
        "pattern": "^SLOT-[A-Za-z0-9-]+$",
        "x-ai-entity": "slot",
        "x-ai-id-prefix": "SLOT-",
        "x-ai-id-field": "slot_id"
      },
      "start_time": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "downtime_minutes",
    "end_time",
    "operator_notes",
    "quantity_produced",
    "quantity_scrap",
    "slot_id",
    "start_time"
  ],
  "x-body-required": [
    "slot_id"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "downtimeMinutes": {
          "description": "Gap 7 - downtime during slot for OEE",
          "type": "integer"
        },
        "endTime": {
          "type": "string"
        },
        "operatorNotes": {
          "type": "string"
        },
        "productionID": {
          "type": "string"
        },
        "quantityProduced": {
          "type": "integer"
        },
        "quantityScrap": {
          "type": "integer"
        },
        "slotID": {
          "type": "string"
        },
        "startTime": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__products
**Description**: List all products
**Method**: GET
**Endpoint**: /products
**Capability Tags**: ["product", "list", "all", "optional", "filter", "sorting", "and", "field", "selection", "statu", "type", "sort", "by", "dir", "limit", "offset", "data", "createdat", "description", "formulaid", "linked", "formula", "for", "bom", "recipe", "processid", "active", "routing", "scheduling", "productid", "productname", "producttype", "obsolete", "unitofmeasure", "pcs", "kg", "liter", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": [
        "active",
        "obsolete"
      ]
    },
    "product_type": {
      "type": "string"
    },
    "sort_by": {
      "type": "string",
      "enum": [
        "product_id",
        "product_name",
        "created_at"
      ]
    },
    "sort_dir": {
      "type": "string",
      "enum": [
        "asc",
        "desc"
      ]
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "status",
    "product_type",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "status": "query",
    "product_type": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "createdAt": {
            "type": "string"
          },
          "description": {
            "type": "string"
          },
          "formulaID": {
            "description": "linked formula for BOM/recipe",
            "type": "string"
          },
          "processID": {
            "description": "active routing for scheduling",
            "type": "string"
          },
          "productID": {
            "type": "string"
          },
          "productName": {
            "type": "string"
          },
          "productType": {
            "type": "string"
          },
          "status": {
            "description": "active, obsolete",
            "type": "string",
            "enum": [
              "active",
              "obsolete"
            ]
          },
          "unitOfMeasure": {
            "description": "pcs / kg / liter",
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__products
**Description**: Create a new product
**Method**: POST
**Endpoint**: /products
**Capability Tags**: ["product", "create", "a", "new", "the", "provided", "detail", "id", "is", "generated", "p", "prefix", "when", "omitted", "description", "formula", "process", "optional", "with", "name", "type", "unit", "of", "measure", "data", "createdat", "formulaid", "linked", "for", "bom", "recipe", "processid", "active", "routing", "scheduling", "productid", "productname", "producttype", "statu", "obsolete", "unitofmeasure", "pcs", "kg", "liter", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string"
    },
    "formula_id": {
      "type": "string",
      "pattern": "^F-[A-Za-z0-9-]+$",
      "x-ai-entity": "formula",
      "x-ai-id-prefix": "F-",
      "x-ai-id-field": "formula_id"
    },
    "process_id": {
      "type": "string",
      "pattern": "^PRC-[A-Za-z0-9-]+$",
      "x-ai-entity": "process",
      "x-ai-id-prefix": "PRC-",
      "x-ai-id-field": "process_id"
    },
    "product_id": {
      "description": "Optional; generated with P- prefix when omitted.",
      "type": "string",
      "pattern": "^P-[A-Za-z0-9-]+$",
      "x-ai-entity": "product",
      "x-ai-id-prefix": "P-",
      "x-ai-id-field": "product_id",
      "x-ai-generated": true
    },
    "product_name": {
      "type": "string"
    },
    "product_type": {
      "type": "string"
    },
    "unit_of_measure": {
      "type": "string"
    }
  },
  "required": [
    "product_name"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "description": "body",
    "formula_id": "body",
    "process_id": "body",
    "product_id": "body",
    "product_name": "body",
    "product_type": "body",
    "unit_of_measure": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "product_name"
    ],
    "properties": {
      "description": {
        "type": "string"
      },
      "formula_id": {
        "type": "string",
        "pattern": "^F-[A-Za-z0-9-]+$",
        "x-ai-entity": "formula",
        "x-ai-id-prefix": "F-",
        "x-ai-id-field": "formula_id"
      },
      "process_id": {
        "type": "string",
        "pattern": "^PRC-[A-Za-z0-9-]+$",
        "x-ai-entity": "process",
        "x-ai-id-prefix": "PRC-",
        "x-ai-id-field": "process_id"
      },
      "product_id": {
        "description": "Optional; generated with P- prefix when omitted.",
        "type": "string",
        "pattern": "^P-[A-Za-z0-9-]+$",
        "x-ai-entity": "product",
        "x-ai-id-prefix": "P-",
        "x-ai-id-field": "product_id",
        "x-ai-generated": true
      },
      "product_name": {
        "type": "string"
      },
      "product_type": {
        "type": "string"
      },
      "unit_of_measure": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "description",
    "formula_id",
    "process_id",
    "product_id",
    "product_name",
    "product_type",
    "unit_of_measure"
  ],
  "x-body-required": [
    "product_name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "createdAt": {
          "type": "string"
        },
        "description": {
          "type": "string"
        },
        "formulaID": {
          "description": "linked formula for BOM/recipe",
          "type": "string"
        },
        "processID": {
          "description": "active routing for scheduling",
          "type": "string"
        },
        "productID": {
          "type": "string"
        },
        "productName": {
          "type": "string"
        },
        "productType": {
          "type": "string"
        },
        "status": {
          "description": "active, obsolete",
          "type": "string",
          "enum": [
            "active",
            "obsolete"
          ]
        },
        "unitOfMeasure": {
          "description": "pcs / kg / liter",
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__products_{id}
**Description**: Get a product by ID
**Method**: GET
**Endpoint**: /products/{id}
**Capability Tags**: ["product", "lookup", "a", "id", "support", "optional", "field", "selection", "data", "createdat", "description", "formulaid", "linked", "formula", "for", "bom", "recipe", "processid", "active", "routing", "scheduling", "productid", "productname", "producttype", "statu", "obsolete", "unitofmeasure", "pcs", "kg", "liter", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "createdAt": {
          "type": "string"
        },
        "description": {
          "type": "string"
        },
        "formulaID": {
          "description": "linked formula for BOM/recipe",
          "type": "string"
        },
        "processID": {
          "description": "active routing for scheduling",
          "type": "string"
        },
        "productID": {
          "type": "string"
        },
        "productName": {
          "type": "string"
        },
        "productType": {
          "type": "string"
        },
        "status": {
          "description": "active, obsolete",
          "type": "string",
          "enum": [
            "active",
            "obsolete"
          ]
        },
        "unitOfMeasure": {
          "description": "pcs / kg / liter",
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## put__products_{id}_bom
**Description**: Link a BOM to a product
**Method**: PUT
**Endpoint**: /products/{id}/bom
**Capability Tags**: ["product", "bom", "update", "link", "a", "id", "item", "material", "required", "if", "not", "set", "sub", "quantity", "per", "unit", "qty", "1", "of", "parent", "backward", "compat", "scrap", "rate", "formula", "process", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "bom_items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "material_id": {
            "description": "required if product_id not set",
            "type": "string",
            "pattern": "^MAT-[A-Za-z0-9-]+$",
            "x-ai-entity": "inventory",
            "x-ai-id-prefix": "MAT-",
            "x-ai-id-field": "material_id"
          },
          "product_id": {
            "description": "sub-product, required if material_id not set",
            "type": "string",
            "pattern": "^P-[A-Za-z0-9-]+$",
            "x-ai-entity": "product",
            "x-ai-id-prefix": "P-",
            "x-ai-id-field": "product_id"
          },
          "quantity_per_unit": {
            "description": "required; qty per 1 unit of parent",
            "type": "number"
          },
          "quantity_required": {
            "description": "backward compat",
            "type": "number"
          },
          "scrap_rate": {
            "type": "number"
          },
          "unit": {
            "type": "string"
          }
        }
      }
    },
    "formula_id": {
      "type": "string",
      "pattern": "^F-[A-Za-z0-9-]+$",
      "x-ai-entity": "formula",
      "x-ai-id-prefix": "F-",
      "x-ai-id-field": "formula_id"
    },
    "process_id": {
      "type": "string",
      "pattern": "^PRC-[A-Za-z0-9-]+$",
      "x-ai-entity": "process",
      "x-ai-id-prefix": "PRC-",
      "x-ai-id-field": "process_id"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "bom_items": "body",
    "formula_id": "body",
    "process_id": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "bom_items": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "material_id": {
              "description": "required if product_id not set",
              "type": "string",
              "pattern": "^MAT-[A-Za-z0-9-]+$",
              "x-ai-entity": "inventory",
              "x-ai-id-prefix": "MAT-",
              "x-ai-id-field": "material_id"
            },
            "product_id": {
              "description": "sub-product, required if material_id not set",
              "type": "string",
              "pattern": "^P-[A-Za-z0-9-]+$",
              "x-ai-entity": "product",
              "x-ai-id-prefix": "P-",
              "x-ai-id-field": "product_id"
            },
            "quantity_per_unit": {
              "description": "required; qty per 1 unit of parent",
              "type": "number"
            },
            "quantity_required": {
              "description": "backward compat",
              "type": "number"
            },
            "scrap_rate": {
              "type": "number"
            },
            "unit": {
              "type": "string"
            }
          }
        }
      },
      "formula_id": {
        "type": "string",
        "pattern": "^F-[A-Za-z0-9-]+$",
        "x-ai-entity": "formula",
        "x-ai-id-prefix": "F-",
        "x-ai-id-field": "formula_id"
      },
      "process_id": {
        "type": "string",
        "pattern": "^PRC-[A-Za-z0-9-]+$",
        "x-ai-entity": "process",
        "x-ai-id-prefix": "PRC-",
        "x-ai-id-field": "process_id"
      }
    }
  },
  "x-body-fields": [
    "bom_items",
    "formula_id",
    "process_id"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__products_{id}_scheduling-definition
**Description**: Get a scheduling definition by product ID
**Method**: GET
**Endpoint**: /products/{id}/scheduling-definition
**Capability Tags**: ["product", "scheduling", "definition", "lookup", "a", "id", "data", "bom", "item", "bomid", "componenttype", "materialid", "productcomponentid", "sub", "productid", "quantityrequired", "qty", "per", "1", "unit", "of", "parent", "scraprate", "composition", "source", "formula", "createdat", "effectivefrom", "effectiveto", "formulaid", "formulaname", "instruction", "safetynote", "version", "ingredient", "component", "type", "material", "name", "quantity", "scrap", "rate", "process", "description", "isprimary", "primary", "vs", "alternative", "routing", "processid", "processname", "sequence", "order", "when", "multiple", "0", "linked", "for", "recipe", "active", "productname", "producttype", "statu", "obsolete", "unitofmeasure", "pcs", "kg", "liter", "step", "allow", "parallel", "execution", "batch", "size", "no", "constraint", "default", "changeover", "time", "minute", "cleaning", "preparation", "processing", "is", "true", "if", "run", "in", "batche", "machine", "required", "max", "min", "minimum", "splitting", "split", "wait", "e", "g", "cooling", "before", "next", "note", "predecessor", "ids", "json", "array", "empty", "infer", "from", "stepsequence", "quality", "check", "matche", "reference", "transfer", "transport", "to", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "bom_items": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "bomid": {
                "type": "string"
              },
              "componentType": {
                "type": "string"
              },
              "materialID": {
                "type": "string"
              },
              "productComponentID": {
                "description": "sub-product",
                "type": "string"
              },
              "productID": {
                "type": "string"
              },
              "quantityRequired": {
                "description": "qty per 1 unit of parent",
                "type": "number"
              },
              "scrapRate": {
                "type": "number"
              },
              "unit": {
                "type": "string"
              }
            }
          }
        },
        "composition_source": {
          "type": "string"
        },
        "formula": {
          "type": "object",
          "properties": {
            "createdAt": {
              "type": "string"
            },
            "effectiveFrom": {
              "type": "string"
            },
            "effectiveTo": {
              "type": "string"
            },
            "formulaID": {
              "type": "string"
            },
            "formulaName": {
              "type": "string"
            },
            "instructions": {
              "type": "string"
            },
            "safetyNotes": {
              "type": "string"
            },
            "version": {
              "type": "integer"
            }
          }
        },
        "ingredients": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "component_type": {
                "type": "string"
              },
              "formula_id": {
                "type": "string",
                "pattern": "^F-[A-Za-z0-9-]+$",
                "x-ai-entity": "formula",
                "x-ai-id-prefix": "F-",
                "x-ai-id-field": "formula_id"
              },
              "ingredient_id": {
                "type": "string"
              },
              "material_id": {
                "type": "string",
                "pattern": "^MAT-[A-Za-z0-9-]+$",
                "x-ai-entity": "inventory",
                "x-ai-id-prefix": "MAT-",
                "x-ai-id-field": "material_id"
              },
              "material_name": {
                "type": "string"
              },
              "product_id": {
                "type": "string",
                "pattern": "^P-[A-Za-z0-9-]+$",
                "x-ai-entity": "product",
                "x-ai-id-prefix": "P-",
                "x-ai-id-field": "product_id"
              },
              "product_name": {
                "type": "string"
              },
              "quantity_per_unit": {
                "type": "number"
              },
              "scrap_rate": {
                "type": "number"
              },
              "unit": {
                "type": "string"
              }
            }
          }
        },
        "process": {
          "type": "object",
          "properties": {
            "description": {
              "type": "string"
            },
            "effectiveFrom": {
              "type": "string"
            },
            "effectiveTo": {
              "type": "string"
            },
            "isPrimary": {
              "description": "primary vs alternative routing",
              "type": "boolean"
            },
            "processID": {
              "type": "string"
            },
            "processName": {
              "type": "string"
            },
            "productID": {
              "type": "string"
            },
            "sequence": {
              "description": "order when multiple (0=primary)",
              "type": "integer"
            },
            "version": {
              "type": "integer"
            }
          }
        },
        "product": {
          "type": "object",
          "properties": {
            "createdAt": {
              "type": "string"
            },
            "description": {
              "type": "string"
            },
            "formulaID": {
              "description": "linked formula for BOM/recipe",
              "type": "string"
            },
            "processID": {
              "description": "active routing for scheduling",
              "type": "string"
            },
            "productID": {
              "type": "string"
            },
            "productName": {
              "type": "string"
            },
            "productType": {
              "type": "string"
            },
            "status": {
              "description": "active, obsolete",
              "type": "string",
              "enum": [
                "active",
                "obsolete"
              ]
            },
            "unitOfMeasure": {
              "description": "pcs / kg / liter",
              "type": "string"
            }
          }
        },
        "steps": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "allow_parallel_execution": {
                "type": "boolean"
              },
              "batch_size": {
                "description": "0 = no batch constraint",
                "type": "integer"
              },
              "default_changeover_time": {
                "description": "minutes",
                "type": "integer"
              },
              "default_cleaning_time": {
                "description": "minutes",
                "type": "integer"
              },
              "default_preparation_time": {
                "description": "minutes",
                "type": "integer"
              },
              "default_processing_time": {
                "description": "minutes",
                "type": "integer"
              },
              "is_batch_process": {
                "description": "true if step runs in batches",
                "type": "boolean"
              },
              "machine_type_required": {
                "type": "string"
              },
              "max_parallel_machines": {
                "type": "integer"
              },
              "min_batch_size": {
                "description": "minimum batch when splitting",
                "type": "integer"
              },
              "min_split_qty": {
                "type": "integer"
              },
              "min_wait_minutes": {
                "description": "e.g. cooling time before next step",
                "type": "integer"
              },
              "notes": {
                "type": "string"
              },
              "predecessor_step_ids": {
                "description": "JSON array of step_ids; empty = infer from StepSequence",
                "type": "string"
              },
              "process_id": {
                "type": "string",
                "pattern": "^PRC-[A-Za-z0-9-]+$",
                "x-ai-entity": "process",
                "x-ai-id-prefix": "PRC-",
                "x-ai-id-field": "process_id"
              },
              "quality_check_required": {
                "type": "boolean"
              },
              "step_id": {
                "type": "string",
                "pattern": "^STP-[A-Za-z0-9-]+$",
                "x-ai-entity": "step",
                "x-ai-id-prefix": "STP-",
                "x-ai-id-field": "step_id"
              },
              "step_name": {
                "type": "string"
              },
              "step_sequence": {
                "type": "integer"
              },
              "step_type": {
                "description": "matches reference_step_types.name",
                "type": "string"
              },
              "transfer_batch_size": {
                "type": "integer"
              },
              "transfer_minutes": {
                "description": "transport time to next step",
                "type": "integer"
              }
            }
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__quality_inspections
**Description**: Record an inspection
**Method**: POST
**Endpoint**: /quality/inspections
**Capability Tags**: ["quality", "inspection", "create", "record", "an", "defect", "count", "inspector", "name", "job", "step", "id", "note", "result", "pass", "fail", "data", "defectcount", "inspectionid", "inspectiontime", "inspectorname", "jobstepid", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "defect_count": {
      "type": "integer"
    },
    "inspector_name": {
      "type": "string"
    },
    "job_step_id": {
      "type": "string",
      "pattern": "^JS-[A-Za-z0-9-]+$",
      "x-ai-entity": "step",
      "x-ai-id-prefix": "JS-",
      "x-ai-id-field": "job_step_id"
    },
    "notes": {
      "type": "string"
    },
    "result": {
      "description": "pass, fail",
      "type": "string"
    }
  },
  "required": [
    "job_step_id"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "defect_count": "body",
    "inspector_name": "body",
    "job_step_id": "body",
    "notes": "body",
    "result": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "job_step_id"
    ],
    "properties": {
      "defect_count": {
        "type": "integer"
      },
      "inspector_name": {
        "type": "string"
      },
      "job_step_id": {
        "type": "string",
        "pattern": "^JS-[A-Za-z0-9-]+$",
        "x-ai-entity": "step",
        "x-ai-id-prefix": "JS-",
        "x-ai-id-field": "job_step_id"
      },
      "notes": {
        "type": "string"
      },
      "result": {
        "description": "pass, fail",
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "defect_count",
    "inspector_name",
    "job_step_id",
    "notes",
    "result"
  ],
  "x-body-required": [
    "job_step_id"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "defectCount": {
          "type": "integer"
        },
        "inspectionID": {
          "type": "string"
        },
        "inspectionTime": {
          "type": "string"
        },
        "inspectorName": {
          "type": "string"
        },
        "jobStepID": {
          "type": "string"
        },
        "notes": {
          "type": "string"
        },
        "result": {
          "description": "pass, fail",
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__reference_locations
**Description**: List locations
**Method**: GET
**Endpoint**: /reference/locations
**Capability Tags**: ["reference", "location", "list", "q", "sort", "by", "dir", "limit", "offset", "field", "data", "bay", "display", "computed", "in", "app", "id", "zone", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "q": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    },
    "sort_dir": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "q",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "q": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "bay": {
            "type": "string"
          },
          "display": {
            "description": "computed in app",
            "type": "string"
          },
          "id": {
            "type": "integer"
          },
          "zone": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__reference_locations
**Description**: Create a location
**Method**: POST
**Endpoint**: /reference/locations
**Capability Tags**: ["reference", "location", "create", "a", "bay", "zone", "data", "display", "computed", "in", "app", "id", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "bay": {
      "type": "string"
    },
    "zone": {
      "type": "string"
    }
  },
  "required": [
    "zone"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "bay": "body",
    "zone": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "zone"
    ],
    "properties": {
      "bay": {
        "type": "string"
      },
      "zone": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "bay",
    "zone"
  ],
  "x-body-required": [
    "zone"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "bay": {
          "type": "string"
        },
        "display": {
          "description": "computed in app",
          "type": "string"
        },
        "id": {
          "type": "integer"
        },
        "zone": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__reference_locations_{id}
**Description**: Delete a location
**Method**: DELETE
**Endpoint**: /reference/locations/{id}
**Capability Tags**: ["reference", "location", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reference_machine-types
**Description**: List machine types
**Method**: GET
**Endpoint**: /reference/machine-types
**Capability Tags**: ["reference", "machine", "type", "list", "q", "sort", "by", "dir", "limit", "offset", "field", "data", "description", "id", "name", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "q": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    },
    "sort_dir": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "q",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "q": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "description": {
            "type": "string"
          },
          "id": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__reference_machine-types
**Description**: Create a machine type
**Method**: POST
**Endpoint**: /reference/machine-types
**Capability Tags**: ["reference", "machine", "type", "create", "a", "description", "name", "data", "id", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string"
    },
    "name": {
      "type": "string"
    }
  },
  "required": [
    "name"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "description": "body",
    "name": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "name"
    ],
    "properties": {
      "description": {
        "type": "string"
      },
      "name": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "description",
    "name"
  ],
  "x-body-required": [
    "name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "description": {
          "type": "string"
        },
        "id": {
          "type": "integer"
        },
        "name": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## put__reference_machine-types_{id}
**Description**: Update a machine type
**Method**: PUT
**Endpoint**: /reference/machine-types/{id}
**Capability Tags**: ["reference", "machine", "type", "update", "a", "id", "description", "name", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "description": {
      "type": "string"
    },
    "name": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "description": "body",
    "name": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "description": {
        "type": "string"
      },
      "name": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "description",
    "name"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "description": {
          "type": "string"
        },
        "id": {
          "type": "integer"
        },
        "name": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__reference_machine-types_{id}
**Description**: Delete a machine type
**Method**: DELETE
**Endpoint**: /reference/machine-types/{id}
**Capability Tags**: ["reference", "machine", "type", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reference_product-types
**Description**: List product types
**Method**: GET
**Endpoint**: /reference/product-types
**Capability Tags**: ["reference", "product", "type", "list", "q", "sort", "by", "dir", "limit", "offset", "field", "data", "id", "name", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "q": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    },
    "sort_dir": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "q",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "q": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__reference_product-types
**Description**: Create a product type
**Method**: POST
**Endpoint**: /reference/product-types
**Capability Tags**: ["reference", "product", "type", "create", "a", "name", "data", "id", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    }
  },
  "required": [
    "name"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "name": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "name"
    ],
    "properties": {
      "name": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "name"
  ],
  "x-body-required": [
    "name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "id": {
          "type": "integer"
        },
        "name": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__reference_product-types_{id}
**Description**: Delete a product type
**Method**: DELETE
**Endpoint**: /reference/product-types/{id}
**Capability Tags**: ["reference", "product", "type", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## post__reference_step-types
**Description**: Create a step type
**Method**: POST
**Endpoint**: /reference/step-types
**Capability Tags**: ["reference", "step", "type", "create", "a", "default", "machine", "name", "data", "id", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "default_machine_type": {
      "type": "string"
    },
    "name": {
      "type": "string"
    }
  },
  "required": [
    "name"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "default_machine_type": "body",
    "name": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "name"
    ],
    "properties": {
      "default_machine_type": {
        "type": "string"
      },
      "name": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "default_machine_type",
    "name"
  ],
  "x-body-required": [
    "name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "default_machine_type": {
          "type": "string"
        },
        "id": {
          "type": "integer"
        },
        "name": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__reference_step-types_{id}
**Description**: Delete a step type
**Method**: DELETE
**Endpoint**: /reference/step-types/{id}
**Capability Tags**: ["reference", "step", "type", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reference_storage-locations
**Description**: List storage locations
**Method**: GET
**Endpoint**: /reference/storage-locations
**Capability Tags**: ["reference", "storage", "location", "list", "q", "type", "sort", "by", "dir", "limit", "offset", "field", "data", "id", "name", "shelf", "rack", "cold", "hazardou", "floor", "dock", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "q": {
      "type": "string"
    },
    "type": {
      "type": "string"
    },
    "sort_by": {
      "type": "string"
    },
    "sort_dir": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    },
    "offset": {
      "type": "integer"
    },
    "fields": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [
    "q",
    "type",
    "sort_by",
    "sort_dir",
    "limit",
    "offset",
    "fields"
  ],
  "x-param-sources": {
    "q": "query",
    "type": "query",
    "sort_by": "query",
    "sort_dir": "query",
    "limit": "query",
    "offset": "query",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          },
          "type": {
            "description": "shelf, rack, cold, hazardous, floor, dock",
            "type": "string"
          }
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## post__reference_storage-locations
**Description**: Create a storage location
**Method**: POST
**Endpoint**: /reference/storage-locations
**Capability Tags**: ["reference", "storage", "location", "create", "a", "name", "type", "data", "id", "shelf", "rack", "cold", "hazardou", "floor", "dock", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "type": {
      "type": "string"
    }
  },
  "required": [
    "name"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "name": "body",
    "type": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "name"
    ],
    "properties": {
      "name": {
        "type": "string"
      },
      "type": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "name",
    "type"
  ],
  "x-body-required": [
    "name"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "id": {
          "type": "integer"
        },
        "name": {
          "type": "string"
        },
        "type": {
          "description": "shelf, rack, cold, hazardous, floor, dock",
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## delete__reference_storage-locations_{id}
**Description**: Delete a storage location
**Method**: DELETE
**Endpoint**: /reference/storage-locations/{id}
**Capability Tags**: ["reference", "storage", "location", "delete", "a", "id", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_bottleneck-forecast
**Description**: Bottleneck forecast
**Method**: GET
**Endpoint**: /reports/bottleneck-forecast
**Capability Tags**: ["report", "bottleneck", "forecast", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_inventory-trends
**Description**: Inventory trends
**Method**: GET
**Endpoint**: /reports/inventory-trends
**Capability Tags**: ["report", "inventory", "trend", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_job-completion
**Description**: Job completion
**Method**: GET
**Endpoint**: /reports/job-completion
**Capability Tags**: ["report", "job", "completion", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_machine-utilization
**Description**: Machine utilization
**Method**: GET
**Endpoint**: /reports/machine-utilization
**Capability Tags**: ["report", "machine", "utilization", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_maintenance-efficiency
**Description**: Maintenance efficiency
**Method**: GET
**Endpoint**: /reports/maintenance-efficiency
**Capability Tags**: ["report", "maintenance", "efficiency", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_oee-trends
**Description**: OEE trends
**Method**: GET
**Endpoint**: /reports/oee-trends
**Capability Tags**: ["report", "oee", "trend", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_parse-date-range
**Description**: Parse date range
**Method**: GET
**Endpoint**: /reports/parse-date-range
**Capability Tags**: ["report", "parse", "date", "range", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "string"
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__reports_production-output
**Description**: Production output per slot
**Method**: GET
**Endpoint**: /reports/production-output
**Capability Tags**: ["report", "production", "output", "list", "per", "slot", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__reports_quality-trends
**Description**: Quality trends
**Method**: GET
**Endpoint**: /reports/quality-trends
**Capability Tags**: ["report", "quality", "trend", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_backfill-training-dataset
**Description**: Backfill training dataset
**Method**: GET
**Endpoint**: /scheduling/backfill-training-dataset
**Capability Tags**: ["scheduling", "backfill", "training", "dataset", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_candidate-machines
**Description**: Candidate machines
**Method**: GET
**Endpoint**: /scheduling/steps/{id}/candidate-machines
**Capability Tags**: ["scheduling", "step", "candidate", "machine", "lookup", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_estimate-job-completion
**Description**: Estimate job completion
**Method**: GET
**Endpoint**: /scheduling/estimate-job-completion
**Capability Tags**: ["scheduling", "estimate", "job", "completion", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## post__scheduling_events
**Description**: Emit scheduling event
**Method**: POST
**Endpoint**: /scheduling/events
**Capability Tags**: ["scheduling", "event", "ai", "create", "emit", "payload", "type", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "payload": {
      "type": "string"
    },
    "type": {
      "type": "string"
    }
  },
  "required": [
    "payload",
    "type"
  ],
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "payload": "body",
    "type": "body"
  },
  "x-body-schema": {
    "type": "object",
    "required": [
      "payload",
      "type"
    ],
    "properties": {
      "payload": {
        "type": "string"
      },
      "type": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "payload",
    "type"
  ],
  "x-body-required": [
    "payload",
    "type"
  ],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "additionalProperties": true
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__scheduling_is-time-before
**Description**: Is time before
**Method**: GET
**Endpoint**: /scheduling/is-time-before
**Capability Tags**: ["scheduling", "is", "time", "before", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "boolean"
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__scheduling_is-valid-iso-date
**Description**: Is valid ISO date
**Method**: GET
**Endpoint**: /scheduling/is-valid-iso-date
**Capability Tags**: ["scheduling", "is", "valid", "iso", "date", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "boolean"
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__scheduling_solver-preview
**Description**: Solver preview
**Method**: GET
**Endpoint**: /scheduling/jobs/{id}/solver-preview
**Capability Tags**: ["scheduling", "job", "solver", "preview", "lookup", "id", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_explosion
**Description**: Explode demand
**Method**: GET
**Endpoint**: /scheduling/products/{id}/explosion
**Capability Tags**: ["scheduling", "product", "explosion", "lookup", "explode", "demand", "id", "quantity", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "quantity": {
      "type": "number"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "quantity"
  ],
  "x-param-sources": {
    "id": "path",
    "quantity": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_readiness
**Description**: Check readiness
**Method**: GET
**Endpoint**: /scheduling/products/{id}/readiness
**Capability Tags**: ["scheduling", "product", "readiness", "lookup", "check", "id", "quantity", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "quantity": {
      "type": "number"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "quantity"
  ],
  "x-param-sources": {
    "id": "path",
    "quantity": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_refresh-work-calendars
**Description**: Refresh work calendars
**Method**: GET
**Endpoint**: /scheduling/refresh-work-calendars
**Capability Tags**: ["scheduling", "refresh", "work", "calendar", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## put__scheduling_settings
**Description**: Update scheduling settings
**Method**: PUT
**Endpoint**: /scheduling/settings
**Capability Tags**: ["scheduling", "setting", "update", "auto", "reschedule", "on", "event", "deviation", "penalty", "weight", "lateness", "lock", "in", "window", "minute", "objective", "public", "holiday", "setup", "slack", "split", "strategy", "work", "day", "end", "time", "start", "data", "updated", "at", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "auto_reschedule_on_event": {
      "type": "boolean"
    },
    "deviation_penalty_weight": {
      "type": "number"
    },
    "lateness_weight": {
      "type": "number"
    },
    "lock_in_window_minutes": {
      "type": "integer"
    },
    "objective": {
      "type": "string"
    },
    "public_holidays": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "setup_weight": {
      "type": "number"
    },
    "slack_weight": {
      "type": "number"
    },
    "split_strategy": {
      "type": "string"
    },
    "work_days": {
      "type": "string"
    },
    "work_end_time": {
      "type": "string"
    },
    "work_start_time": {
      "type": "string"
    }
  },
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {
    "auto_reschedule_on_event": "body",
    "deviation_penalty_weight": "body",
    "lateness_weight": "body",
    "lock_in_window_minutes": "body",
    "objective": "body",
    "public_holidays": "body",
    "setup_weight": "body",
    "slack_weight": "body",
    "split_strategy": "body",
    "work_days": "body",
    "work_end_time": "body",
    "work_start_time": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "auto_reschedule_on_event": {
        "type": "boolean"
      },
      "deviation_penalty_weight": {
        "type": "number"
      },
      "lateness_weight": {
        "type": "number"
      },
      "lock_in_window_minutes": {
        "type": "integer"
      },
      "objective": {
        "type": "string"
      },
      "public_holidays": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "setup_weight": {
        "type": "number"
      },
      "slack_weight": {
        "type": "number"
      },
      "split_strategy": {
        "type": "string"
      },
      "work_days": {
        "type": "string"
      },
      "work_end_time": {
        "type": "string"
      },
      "work_start_time": {
        "type": "string"
      }
    }
  },
  "x-body-fields": [
    "auto_reschedule_on_event",
    "deviation_penalty_weight",
    "lateness_weight",
    "lock_in_window_minutes",
    "objective",
    "public_holidays",
    "setup_weight",
    "slack_weight",
    "split_strategy",
    "work_days",
    "work_end_time",
    "work_start_time"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "auto_reschedule_on_event": {
          "type": "boolean"
        },
        "deviation_penalty_weight": {
          "type": "number"
        },
        "lateness_weight": {
          "type": "number"
        },
        "lock_in_window_minutes": {
          "type": "integer"
        },
        "objective": {
          "type": "string"
        },
        "public_holidays": {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        "setup_weight": {
          "type": "number"
        },
        "slack_weight": {
          "type": "number"
        },
        "split_strategy": {
          "type": "string"
        },
        "updated_at": {
          "type": "string"
        },
        "work_days": {
          "type": "string"
        },
        "work_end_time": {
          "type": "string"
        },
        "work_start_time": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__scheduling_training-dataset
**Description**: Export training dataset
**Method**: GET
**Endpoint**: /scheduling/training-dataset
**Capability Tags**: ["scheduling", "training", "dataset", "list", "export", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_training-dataset-stats
**Description**: Training dataset stats
**Method**: GET
**Endpoint**: /scheduling/training-dataset-stats
**Capability Tags**: ["scheduling", "training", "dataset", "stat", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## post__scheduling_validate-slot
**Description**: Validate slot
**Method**: POST
**Endpoint**: /scheduling/validate-slot
**Capability Tags**: ["scheduling", "validate", "slot", "create", "data", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  }
}
`
---
## get__scheduling_validate-work-days
**Description**: Validate work days
**Method**: GET
**Endpoint**: /scheduling/validate-work-days
**Capability Tags**: ["scheduling", "validate", "work", "day", "list", "data", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {}
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__settings_get
**Description**: Get settings
**Method**: GET
**Endpoint**: /settings/get
**Capability Tags**: ["setting", "get", "list", "data", "ai", "enabled", "integration", "language", "notification", "theme", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "ai_enabled": {
          "type": "boolean"
        },
        "integrations": {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        "language": {
          "type": "string"
        },
        "notifications": {
          "type": "boolean"
        },
        "theme": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## put__settings_update
**Description**: Update settings
**Method**: PUT
**Endpoint**: /settings/update
**Capability Tags**: ["setting", "update", "data", "ai", "enabled", "integration", "language", "notification", "theme", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {},
  "x-path-params": [],
  "x-query-params": [],
  "x-param-sources": {},
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "ai_enabled": {
          "type": "boolean"
        },
        "integrations": {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        "language": {
          "type": "string"
        },
        "notifications": {
          "type": "boolean"
        },
        "theme": {
          "type": "string"
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## get__slots_{id}
**Description**: Get a slot by ID
**Method**: GET
**Endpoint**: /slots/{id}
**Capability Tags**: ["slot", "job", "lookup", "a", "id", "support", "optional", "field", "selection", "data", "actual", "end", "start", "allocation", "percent", "batch", "sequence", "buffer", "time", "minute", "changeover", "cleaning", "is", "parallel", "step", "machine", "preparation", "processing", "proposal", "quantity", "planned", "scheduled", "split", "group", "statu", "error", "success"]
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "fields": {
      "type": "string"
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [
    "fields"
  ],
  "x-param-sources": {
    "id": "path",
    "fields": "query"
  },
  "x-allowed-roles": [
    "viewer",
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "actual_end": {
          "type": "string"
        },
        "actual_start": {
          "type": "string"
        },
        "allocation_percent": {
          "type": "number"
        },
        "batch_sequence": {
          "type": "integer"
        },
        "buffer_time_minutes": {
          "type": "integer"
        },
        "changeover_time_minutes": {
          "type": "integer"
        },
        "cleaning_time_minutes": {
          "type": "integer"
        },
        "is_parallel": {
          "type": "boolean"
        },
        "job_step_id": {
          "type": "string",
          "pattern": "^JS-[A-Za-z0-9-]+$",
          "x-ai-entity": "step",
          "x-ai-id-prefix": "JS-",
          "x-ai-id-field": "job_step_id"
        },
        "machine_id": {
          "type": "string",
          "pattern": "^M-[A-Za-z0-9-]+$",
          "x-ai-entity": "machine",
          "x-ai-id-prefix": "M-",
          "x-ai-id-field": "machine_id"
        },
        "preparation_time_minutes": {
          "type": "integer"
        },
        "processing_time_minutes": {
          "type": "integer"
        },
        "proposal_id": {
          "type": "string",
          "pattern": "^AIPROP-[A-Za-z0-9-]+$",
          "x-ai-entity": "proposal",
          "x-ai-id-prefix": "AIPROP-",
          "x-ai-id-field": "proposal_id"
        },
        "quantity_planned": {
          "type": "integer"
        },
        "scheduled_end": {
          "type": "string"
        },
        "scheduled_start": {
          "type": "string"
        },
        "slot_id": {
          "type": "string",
          "pattern": "^SLOT-[A-Za-z0-9-]+$",
          "x-ai-entity": "slot",
          "x-ai-id-prefix": "SLOT-",
          "x-ai-id-field": "slot_id"
        },
        "split_group_id": {
          "type": "string"
        },
        "status": {
          "type": "string",
          "enum": [
            "planned",
            "running",
            "completed",
            "cancelled",
            "paused"
          ]
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
## put__slots_{id}
**Description**: Update a slot
**Method**: PUT
**Endpoint**: /slots/{id}
**Capability Tags**: ["slot", "job", "update", "a", "id", "actual", "end", "start", "production", "execution", "gap", "2", "pause", "resume", "complete", "allocation", "percent", "batch", "sequence", "is", "parallel", "machine", "quantity", "planned", "scheduled", "statu", "data", "buffer", "time", "minute", "changeover", "cleaning", "step", "preparation", "processing", "proposal", "split", "group", "error", "success"]
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "id": {
      "type": "string"
    },
    "actual_end": {
      "type": "string"
    },
    "actual_start": {
      "description": "Production / execution (Gap 2 - Start, Pause, Resume, Complete)",
      "type": "string"
    },
    "allocation_percent": {
      "type": "number"
    },
    "batch_sequence": {
      "type": "integer"
    },
    "is_parallel": {
      "type": "boolean"
    },
    "machine_id": {
      "type": "string",
      "pattern": "^M-[A-Za-z0-9-]+$",
      "x-ai-entity": "machine",
      "x-ai-id-prefix": "M-",
      "x-ai-id-field": "machine_id"
    },
    "quantity_planned": {
      "type": "integer"
    },
    "scheduled_end": {
      "type": "string"
    },
    "scheduled_start": {
      "type": "string"
    },
    "status": {
      "type": "string",
      "enum": [
        "planned",
        "running",
        "paused",
        "completed",
        "cancelled"
      ]
    }
  },
  "required": [
    "id"
  ],
  "x-path-params": [
    "id"
  ],
  "x-query-params": [],
  "x-param-sources": {
    "id": "path",
    "actual_end": "body",
    "actual_start": "body",
    "allocation_percent": "body",
    "batch_sequence": "body",
    "is_parallel": "body",
    "machine_id": "body",
    "quantity_planned": "body",
    "scheduled_end": "body",
    "scheduled_start": "body",
    "status": "body"
  },
  "x-body-schema": {
    "type": "object",
    "properties": {
      "actual_end": {
        "type": "string"
      },
      "actual_start": {
        "description": "Production / execution (Gap 2 - Start, Pause, Resume, Complete)",
        "type": "string"
      },
      "allocation_percent": {
        "type": "number"
      },
      "batch_sequence": {
        "type": "integer"
      },
      "is_parallel": {
        "type": "boolean"
      },
      "machine_id": {
        "type": "string",
        "pattern": "^M-[A-Za-z0-9-]+$",
        "x-ai-entity": "machine",
        "x-ai-id-prefix": "M-",
        "x-ai-id-field": "machine_id"
      },
      "quantity_planned": {
        "type": "integer"
      },
      "scheduled_end": {
        "type": "string"
      },
      "scheduled_start": {
        "type": "string"
      },
      "status": {
        "type": "string",
        "enum": [
          "planned",
          "running",
          "paused",
          "completed",
          "cancelled"
        ]
      }
    }
  },
  "x-body-fields": [
    "actual_end",
    "actual_start",
    "allocation_percent",
    "batch_sequence",
    "is_parallel",
    "machine_id",
    "quantity_planned",
    "scheduled_end",
    "scheduled_start",
    "status"
  ],
  "x-body-required": [],
  "x-allowed-roles": [
    "planner",
    "manager",
    "admin"
  ]
}
`
**Output Schema**:
`json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "actual_end": {
          "type": "string"
        },
        "actual_start": {
          "type": "string"
        },
        "allocation_percent": {
          "type": "number"
        },
        "batch_sequence": {
          "type": "integer"
        },
        "buffer_time_minutes": {
          "type": "integer"
        },
        "changeover_time_minutes": {
          "type": "integer"
        },
        "cleaning_time_minutes": {
          "type": "integer"
        },
        "is_parallel": {
          "type": "boolean"
        },
        "job_step_id": {
          "type": "string",
          "pattern": "^JS-[A-Za-z0-9-]+$",
          "x-ai-entity": "step",
          "x-ai-id-prefix": "JS-",
          "x-ai-id-field": "job_step_id"
        },
        "machine_id": {
          "type": "string",
          "pattern": "^M-[A-Za-z0-9-]+$",
          "x-ai-entity": "machine",
          "x-ai-id-prefix": "M-",
          "x-ai-id-field": "machine_id"
        },
        "preparation_time_minutes": {
          "type": "integer"
        },
        "processing_time_minutes": {
          "type": "integer"
        },
        "proposal_id": {
          "type": "string",
          "pattern": "^AIPROP-[A-Za-z0-9-]+$",
          "x-ai-entity": "proposal",
          "x-ai-id-prefix": "AIPROP-",
          "x-ai-id-field": "proposal_id"
        },
        "quantity_planned": {
          "type": "integer"
        },
        "scheduled_end": {
          "type": "string"
        },
        "scheduled_start": {
          "type": "string"
        },
        "slot_id": {
          "type": "string",
          "pattern": "^SLOT-[A-Za-z0-9-]+$",
          "x-ai-entity": "slot",
          "x-ai-id-prefix": "SLOT-",
          "x-ai-id-field": "slot_id"
        },
        "split_group_id": {
          "type": "string"
        },
        "status": {
          "type": "string",
          "enum": [
            "planned",
            "running",
            "completed",
            "cancelled",
            "paused"
          ]
        }
      }
    },
    "error": {
      "type": "string"
    },
    "success": {
      "type": "boolean"
    }
  },
  "required": []
}
`
---
