# Available Tools

## post__ai_command
**Description**: Parse a command
**Method**: POST
**Endpoint**: /ai/command
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_metrics
**Description**: Metrics
**Method**: GET
**Endpoint**: /ai/metrics
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_apply-replenishment-batch
**Description**: Apply replenishment batch
**Method**: POST
**Endpoint**: /ai/scheduling/apply-replenishment-batch
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_batch-proposals
**Description**: Generate batch proposals
**Method**: POST
**Endpoint**: /ai/scheduling/batch-proposals
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_bottleneck-forecast
**Description**: Bottleneck forecast
**Method**: GET
**Endpoint**: /ai/scheduling/bottleneck-forecast
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_job-steps_{id}_machine-ranking
**Description**: Machine ranking
**Method**: GET
**Endpoint**: /ai/scheduling/job-steps/{id}/machine-ranking
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_job-steps_{id}_split-suggestion
**Description**: Split suggestion
**Method**: GET
**Endpoint**: /ai/scheduling/job-steps/{id}/split-suggestion
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_jobs_{id}_apply-proposal
**Description**: Apply a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/apply-proposal
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_jobs_{id}_apply-replenishment
**Description**: Apply replenishment
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/apply-replenishment
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_jobs_{id}_assist
**Description**: Assist a job
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/assist
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_jobs_{id}_delay-risk
**Description**: Delay risk
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/delay-risk
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_jobs_{id}_explanation
**Description**: Explanation
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/explanation
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_jobs_{id}_proposal
**Description**: Generate a proposal
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/proposal
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_jobs_{id}_proposal
**Description**: Generate a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/proposal
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_jobs_{id}_proposals
**Description**: List proposals
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/proposals
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_jobs_{id}_replenish-and-replan
**Description**: Replenish and replan
**Method**: POST
**Endpoint**: /ai/scheduling/jobs/{id}/replenish-and-replan
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_jobs_{id}_shortage-analysis
**Description**: Shortage analysis
**Method**: GET
**Endpoint**: /ai/scheduling/jobs/{id}/shortage-analysis
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__ai_scheduling_proposals_{id}
**Description**: Get a proposal
**Method**: GET
**Endpoint**: /ai/scheduling/proposals/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_proposals_{id}_apply
**Description**: Apply a proposal by ID
**Method**: POST
**Endpoint**: /ai/scheduling/proposals/{id}/apply
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_proposals_{id}_approve
**Description**: Approve a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/proposals/{id}/approve
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_proposals_{id}_reject
**Description**: Reject a proposal
**Method**: POST
**Endpoint**: /ai/scheduling/proposals/{id}/reject
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_reschedule-all
**Description**: Reschedule all
**Method**: POST
**Endpoint**: /ai/scheduling/reschedule-all
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__ai_scheduling_verify-overlaps
**Description**: Verify overlaps
**Method**: POST
**Endpoint**: /ai/scheduling/verify-overlaps
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__chatbot_approval_pending
**Description**: List pending approvals
**Method**: GET
**Endpoint**: /chatbot/approval/pending
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__chatbot_approval_{id}
**Description**: Get an approval by ID
**Method**: GET
**Endpoint**: /chatbot/approval/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__chatbot_approval_{id}_approve
**Description**: Approve an approval
**Method**: POST
**Endpoint**: /chatbot/approval/{id}/approve
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__chatbot_approval_{id}_reject
**Description**: Reject an approval
**Method**: POST
**Endpoint**: /chatbot/approval/{id}/reject
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__dashboard_alerts
**Description**: Get alerts
**Method**: GET
**Endpoint**: /dashboard/alerts
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__dashboard_kpis
**Description**: Get KPIs
**Method**: GET
**Endpoint**: /dashboard/kpis
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__formula
**Description**: List all formulas
**Method**: GET
**Endpoint**: /formula
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__formula
**Description**: Create a formula
**Method**: POST
**Endpoint**: /formula
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__formula_{id}
**Description**: Get a formula by ID
**Method**: GET
**Endpoint**: /formula/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__formula_{id}
**Description**: Delete a formula
**Method**: DELETE
**Endpoint**: /formula/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__formula_{id}_ingredients
**Description**: List ingredients for a formula
**Method**: GET
**Endpoint**: /formula/{id}/ingredients
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__formula_{id}_ingredients
**Description**: Add an ingredient to a formula
**Method**: POST
**Endpoint**: /formula/{id}/ingredients
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
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__inventory_consume
**Description**: Consume a material
**Method**: POST
**Endpoint**: /inventory/consume
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__inventory_expected-arrivals
**Description**: List expected arrivals
**Method**: GET
**Endpoint**: /inventory/expected-arrivals
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__inventory_expected-arrivals
**Description**: Schedule an expected arrival
**Method**: POST
**Endpoint**: /inventory/expected-arrivals
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__inventory_materials
**Description**: List materials
**Method**: GET
**Endpoint**: /inventory/materials
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__inventory_materials
**Description**: Create a material
**Method**: POST
**Endpoint**: /inventory/materials
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__inventory_materials_{id}
**Description**: Get a material by ID
**Method**: GET
**Endpoint**: /inventory/materials/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__inventory_product-stock
**Description**: List product inventory
**Method**: GET
**Endpoint**: /inventory/product-stock
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__inventory_product-stock
**Description**: Create a product inventory
**Method**: POST
**Endpoint**: /inventory/product-stock
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__inventory_receive
**Description**: Receive a material
**Method**: POST
**Endpoint**: /inventory/receive
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__inventory_reservations
**Description**: Create a reservation
**Method**: POST
**Endpoint**: /inventory/reservations
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__job-steps
**Description**: Create job steps from routing
**Method**: POST
**Endpoint**: /job-steps
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__job-steps_split
**Description**: Split a step
**Method**: POST
**Endpoint**: /job-steps/split
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__job-steps_{id}_slots
**Description**: List slots by job step ID
**Method**: GET
**Endpoint**: /job-steps/{id}/slots
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__jobs
**Description**: Create a job
**Method**: POST
**Endpoint**: /jobs
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__jobs_{id}
**Description**: Get a job by ID
**Method**: GET
**Endpoint**: /jobs/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__jobs_{id}_slots
**Description**: List slots by job ID
**Method**: GET
**Endpoint**: /jobs/{id}/slots
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__machines
**Description**: List all machines
**Method**: GET
**Endpoint**: /machines
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__machines
**Description**: Create a machine
**Method**: POST
**Endpoint**: /machines
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__machines_downtime
**Description**: Record downtime
**Method**: POST
**Endpoint**: /machines/downtime
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__machines_maintenance-alerts
**Description**: Get maintenance alerts
**Method**: GET
**Endpoint**: /machines/maintenance-alerts
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__machines_reroute-recommendations
**Description**: Get reroute recommendations
**Method**: GET
**Endpoint**: /machines/reroute-recommendations
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__machines_utilization
**Description**: Get utilization
**Method**: GET
**Endpoint**: /machines/utilization
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__machines_{id}
**Description**: Get machine by ID
**Method**: GET
**Endpoint**: /machines/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## put__machines_{id}
**Description**: Update a machine
**Method**: PUT
**Endpoint**: /machines/{id}
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
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__machines_{id}_capabilities
**Description**: Assign a capability to a machine
**Method**: POST
**Endpoint**: /machines/{id}/capabilities
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
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__maintenance
**Description**: Record maintenance
**Method**: POST
**Endpoint**: /maintenance
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__predictive_confidence
**Description**: Confidence
**Method**: GET
**Endpoint**: /predictive/confidence
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__predictive_forecast
**Description**: Forecast
**Method**: GET
**Endpoint**: /predictive/forecast
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__predictive_high-risk-jobs
**Description**: List high-risk jobs
**Method**: GET
**Endpoint**: /predictive/high-risk-jobs
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__predictive_recommendations
**Description**: List recommendations
**Method**: GET
**Endpoint**: /predictive/recommendations
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__process-steps_{step_id}_materials
**Description**: List materials for a step
**Method**: GET
**Endpoint**: /process-steps/{step_id}/materials
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__process-steps_{step_id}_materials
**Description**: Add a material to a step
**Method**: POST
**Endpoint**: /process-steps/{step_id}/materials
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
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__process-steps_{step_id}_materials_{id}
**Description**: Delete a material from a step
**Method**: DELETE
**Endpoint**: /process-steps/{step_id}/materials/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__processes
**Description**: List processes
**Method**: GET
**Endpoint**: /processes
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__processes
**Description**: Create a process
**Method**: POST
**Endpoint**: /processes
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__processes_product_{id}
**Description**: Get a process by product ID
**Method**: GET
**Endpoint**: /processes/product/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__processes_{id}
**Description**: Get a process by ID
**Method**: GET
**Endpoint**: /processes/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__processes_{id}
**Description**: Delete a process
**Method**: DELETE
**Endpoint**: /processes/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__processes_{id}_steps
**Description**: List steps by process ID
**Method**: GET
**Endpoint**: /processes/{id}/steps
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__processes_{id}_steps
**Description**: Add a step to a process
**Method**: POST
**Endpoint**: /processes/{id}/steps
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
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__production-log
**Description**: Log production
**Method**: POST
**Endpoint**: /production-log
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__quality_inspections
**Description**: Record an inspection
**Method**: POST
**Endpoint**: /quality/inspections
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reference_locations
**Description**: List locations
**Method**: GET
**Endpoint**: /reference/locations
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__reference_locations
**Description**: Create a location
**Method**: POST
**Endpoint**: /reference/locations
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__reference_locations_{id}
**Description**: Delete a location
**Method**: DELETE
**Endpoint**: /reference/locations/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reference_machine-types
**Description**: List machine types
**Method**: GET
**Endpoint**: /reference/machine-types
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__reference_machine-types
**Description**: Create a machine type
**Method**: POST
**Endpoint**: /reference/machine-types
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## put__reference_machine-types_{id}
**Description**: Update a machine type
**Method**: PUT
**Endpoint**: /reference/machine-types/{id}
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
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__reference_machine-types_{id}
**Description**: Delete a machine type
**Method**: DELETE
**Endpoint**: /reference/machine-types/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reference_product-types
**Description**: List product types
**Method**: GET
**Endpoint**: /reference/product-types
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__reference_product-types
**Description**: Create a product type
**Method**: POST
**Endpoint**: /reference/product-types
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__reference_product-types_{id}
**Description**: Delete a product type
**Method**: DELETE
**Endpoint**: /reference/product-types/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__reference_step-types
**Description**: Create a step type
**Method**: POST
**Endpoint**: /reference/step-types
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__reference_step-types_{id}
**Description**: Delete a step type
**Method**: DELETE
**Endpoint**: /reference/step-types/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reference_storage-locations
**Description**: List storage locations
**Method**: GET
**Endpoint**: /reference/storage-locations
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__reference_storage-locations
**Description**: Create a storage location
**Method**: POST
**Endpoint**: /reference/storage-locations
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## delete__reference_storage-locations_{id}
**Description**: Delete a storage location
**Method**: DELETE
**Endpoint**: /reference/storage-locations/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_bottleneck-forecast
**Description**: Bottleneck forecast
**Method**: GET
**Endpoint**: /reports/bottleneck-forecast
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_inventory-trends
**Description**: Inventory trends
**Method**: GET
**Endpoint**: /reports/inventory-trends
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_job-completion
**Description**: Job completion
**Method**: GET
**Endpoint**: /reports/job-completion
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_machine-utilization
**Description**: Machine utilization
**Method**: GET
**Endpoint**: /reports/machine-utilization
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_maintenance-efficiency
**Description**: Maintenance efficiency
**Method**: GET
**Endpoint**: /reports/maintenance-efficiency
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_oee-trends
**Description**: OEE trends
**Method**: GET
**Endpoint**: /reports/oee-trends
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_parse-date-range
**Description**: Parse date range
**Method**: GET
**Endpoint**: /reports/parse-date-range
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_production-output-per-slot
**Description**: Production output per slot
**Method**: GET
**Endpoint**: /reports/production-output-per-slot
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__reports_quality-trends
**Description**: Quality trends
**Method**: GET
**Endpoint**: /reports/quality-trends
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_backfill-training-dataset
**Description**: Backfill training dataset
**Method**: GET
**Endpoint**: /scheduling/backfill-training-dataset
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_candidate-machines
**Description**: Candidate machines
**Method**: GET
**Endpoint**: /scheduling/candidate-machines
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_estimate-job-completion
**Description**: Estimate job completion
**Method**: GET
**Endpoint**: /scheduling/estimate-job-completion
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__scheduling_events
**Description**: Emit scheduling event
**Method**: POST
**Endpoint**: /scheduling/events
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_explosion
**Description**: Explode demand
**Method**: GET
**Endpoint**: /scheduling/explosion
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_is-time-before
**Description**: Is time before
**Method**: GET
**Endpoint**: /scheduling/is-time-before
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_is-valid-iso-date
**Description**: Is valid ISO date
**Method**: GET
**Endpoint**: /scheduling/is-valid-iso-date
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_readiness
**Description**: Check readiness
**Method**: GET
**Endpoint**: /scheduling/readiness
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_refresh-work-calendars
**Description**: Refresh work calendars
**Method**: GET
**Endpoint**: /scheduling/refresh-work-calendars
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## put__scheduling_settings
**Description**: Update scheduling settings
**Method**: PUT
**Endpoint**: /scheduling/settings
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_solver-preview
**Description**: Solver preview
**Method**: GET
**Endpoint**: /scheduling/solver-preview
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_training-dataset
**Description**: Export training dataset
**Method**: GET
**Endpoint**: /scheduling/training-dataset
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_training-dataset-stats
**Description**: Training dataset stats
**Method**: GET
**Endpoint**: /scheduling/training-dataset-stats
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## post__scheduling_validate-slot
**Description**: Validate slot
**Method**: POST
**Endpoint**: /scheduling/validate-slot
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__scheduling_validate-work-days
**Description**: Validate work days
**Method**: GET
**Endpoint**: /scheduling/validate-work-days
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__settings_get
**Description**: Get settings
**Method**: GET
**Endpoint**: /settings/get
**Requires Approval**: false
**Side Effect Level**: NONE
**Read Only**: true
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## put__settings_update
**Description**: Update settings
**Method**: PUT
**Endpoint**: /settings/update
**Requires Approval**: true
**Side Effect Level**: HIGH
**Read Only**: false
**Input Schema**:
`json
{
  "type": "object",
  "properties": {}
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## get__slots_{id}
**Description**: Get a slot by ID
**Method**: GET
**Endpoint**: /slots/{id}
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
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
## put__slots_{id}
**Description**: Update a slot
**Method**: PUT
**Endpoint**: /slots/{id}
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
    "request": {
      "type": "string"
    }
  }
}
`
**Output Schema**:
`json
{
  "type": "object"
}
`
---
