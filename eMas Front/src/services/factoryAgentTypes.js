/**
 * @typedef {Object} SessionResponse
 * @property {string} session_id
 * @property {string} user_id
 * @property {string|null} [name]
 * @property {'IDLE'|'PLANNING'|'WAITING_APPROVAL'|'WAITING_CONFIRMATION'|'EXECUTING'|'BLOCKED'|'FAILED'|'COMPLETED'} status
 * @property {string|null} [current_intent]
 * @property {string|null} [plan_id]
 * @property {string|null} [operation_id] Logical operation scope (plan_id) for grouping activity across turns and approval resumes.
 * @property {number} [plan_version]
 * @property {string|null} [plan_hash]
 * @property {number} [current_step_index]
 * @property {number} [step_count]
 * @property {number} [replan_count]
 * @property {number} [llm_call_count]
 * @property {Object|null} [replan_context]
 * @property {string|null} [pending_user_message]
 * @property {string|null} [error]
 */

/**
 * @typedef {Object} MessageResponse
 * @property {string} message_id
 * @property {string} session_id
 * @property {'user'|'assistant'|'system'|'tool_result'} role
 * @property {string} content
 * @property {'normal'|'plan'} [mode]
 * @property {string} created_at
 */

/**
 * @typedef {Object} PlanResponse
 * @property {string} plan_id
 * @property {string} session_id
 * @property {number} version
 * @property {'execution'|'discovery'} [kind]
 * @property {'DRAFT'|'PENDING_APPROVAL'|'APPROVED'|'REJECTED'|'COMPLETED'|'INVALIDATED'} [status]
 * @property {string} plan_hash
 * @property {string|null} [approved_plan_hash]
 * @property {string|null} [derived_from_plan_id]
 * @property {string|null} [plan_explanation]
 * @property {string|null} [risk_summary]
 */

/**
 * @typedef {Object} ApprovalResponse
 * @property {string} approval_id
 * @property {string} session_id
 * @property {'step'|'plan'|'graph'} [subject_type]
 * @property {string|null} [plan_id]
 * @property {string|null} [step_id]
 * @property {string} tool_name
 * @property {Object} args
 * @property {string} risk_summary
 * @property {'NONE'|'LOW'|'MEDIUM'|'HIGH'|'CRITICAL'} side_effect_level
 * @property {'PENDING'|'APPROVED'|'REJECTED'|'EXPIRED'} status
 * @property {string} expires_at
 * @property {string|null} [rejection_reason]
 */

/**
 * @typedef {Object} PlanStepResponse
 * @property {string} step_id
 * @property {string} session_id
 * @property {number} step_index
 * @property {string} tool_name
 * @property {Object} args
 * @property {'NOT_STARTED'|'IN_PROGRESS'|'DONE'|'FAILED'|'SKIPPED'|'AMBIGUOUS'} status
 * @property {Object|null} [result]
 * @property {string|null} [result_summary]
 * @property {string|null} [last_error]
 */

/**
 * @typedef {Object} TimelineEventResponse
 * @property {string} event_id
 * @property {'user_message'|'plan_created'|'execution_started'|'tool_started'|'tool_result'|'approval_required'|'approval_decided'|'confirmation_required'|'confirmation_decided'|'replan_requested'|'session_blocked'|'session_failed'|'session_completed'} event_type
 * @property {string} content
 * @property {string} created_at
 * @property {'user'|'assistant'|'system'} role
 * @property {'normal'|'plan'|null} [mode]
 * @property {string|null} [turn_id]
 * @property {string|null} [operation_id] Same as plan scope once known; used for activity grouping (not message turn_id).
 * @property {string|null} [step_id]
 * @property {string|null} [approval_id]
 * @property {string|null} [tool_name]
 * @property {string|null} [status]
 * @property {Object|null} [details]
 */

/**
 * @typedef {Object} SessionSnapshotResponse
 * @property {SessionResponse} session
 * @property {PlanResponse|null} [plan]
 * @property {PlanStepResponse[]} steps
 * @property {ApprovalResponse|null} [pending_approval]
 * @property {TimelineEventResponse[]} timeline
 */

/**
 * @typedef {Object} ActivityStep
 * @property {string} id
 * @property {number} timestamp
 * @property {'planning'|'research'|'approval'|'response'|'system'} group
 * @property {string} label
 * @property {string|null} [detail]
 * @property {'running'|'success'|'retry'|'waiting'|'error'|'complete'} state
 */

export {}
