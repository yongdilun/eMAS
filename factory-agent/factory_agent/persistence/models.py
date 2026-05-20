import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, Index
from factory_agent.persistence.database import Base

# We'll use String(36) for UUIDs to remain compatible with MySQL/SQLite
def generate_uuid():
    return str(uuid.uuid4())

class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_user_updated_at", "user_id", "updated_at"),
        Index("idx_sessions_updated_at", "updated_at"),
        Index("idx_sessions_status", "status"),
    )
    session_id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="IDLE")
    current_intent = Column(Text, nullable=True)
    plan_id = Column(String(36), nullable=True)
    plan_version = Column(Integer, default=0)
    plan_hash = Column(String(255), nullable=True)
    current_step_index = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    step_count = Column(Integer, default=0)
    replan_count = Column(Integer, default=0)
    llm_call_count = Column(Integer, default=0)
    session_started_at = Column(DateTime, default=datetime.utcnow)
    replan_context = Column(JSON, nullable=True)
    pending_user_message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    version = Column(Integer, default=1)
    event_seq = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_session_id", "session_id"),)
    message_id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("sessions.session_id"), nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    mode = Column(String(20), nullable=False, default="normal")
    step_id = Column(String(36), nullable=True)
    tool_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Plan(Base):
    __tablename__ = "plans"
    plan_id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("sessions.session_id"), nullable=False)
    version = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False, default="execution")
    status = Column(String(30), nullable=False, default="DRAFT")
    dependency_graph = Column(JSON, nullable=True)
    parallel_groups = Column(JSON, nullable=True)
    plan_hash = Column(String(255), nullable=False)
    plan_explanation = Column(Text, nullable=True)
    risk_summary = Column(Text, nullable=True)
    sources = Column(JSON, nullable=True)
    safety_content = Column(Text, nullable=True)
    approved_plan_hash = Column(String(255), nullable=True)
    derived_from_plan_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(50), default="llm")
    invalidated_at = Column(DateTime, nullable=True)
    invalidated_reason = Column(Text, nullable=True)

class PlanStep(Base):
    __tablename__ = "plan_steps"
    __table_args__ = (
        Index("idx_plan_steps_session_id", "session_id"),
        Index("idx_plan_steps_status", "status"),
        Index("idx_plan_steps_idempotency", "idempotency_key"),
    )
    step_id = Column(String(36), primary_key=True, default=generate_uuid)
    plan_id = Column(String(36), ForeignKey("plans.plan_id"), nullable=False)
    session_id = Column(String(36), nullable=False)
    step_index = Column(Integer, nullable=False)
    tool_name = Column(String(255), nullable=False)
    args = Column(JSON, nullable=False)
    bindings = Column(JSON, nullable=True)
    execution_mode = Column(String(20), nullable=False, default="single")
    bulk_state = Column(JSON, nullable=True)
    status = Column(String(50), nullable=False, default="NOT_STARTED")
    idempotency_key = Column(String(255), nullable=False, unique=True)
    requires_approval = Column(Boolean, default=False)
    approval_id = Column(String(36), nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    last_error = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    result_summary = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

class Tool(Base):
    __tablename__ = "tools"
    tool_id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=False)
    endpoint = Column(String(255), nullable=False)
    method = Column(String(50), nullable=False)
    version = Column(Integer, default=1)
    schema_version = Column(Integer, default=1)
    input_schema = Column(JSON, nullable=False)
    output_schema = Column(JSON, nullable=True)
    is_read_only = Column(Boolean, default=False)
    requires_approval = Column(Boolean, default=False)
    side_effect_level = Column(String(50), default="NONE")
    is_concurrency_safe = Column(Boolean, default=True)
    is_idempotent = Column(Boolean, default=False)
    is_strongly_idempotent = Column(Boolean, default=False)
    # JSON list of tag strings; rich OpenAPI-derived tags can exceed 1k chars (MySQL VARCHAR limit caused 1406).
    capability_tags = Column(Text, nullable=False, default="[]")
    deprecated_at = Column(DateTime, nullable=True)
    replacement_tool = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ToolRegistryMeta(Base):
    __tablename__ = "tool_registry_meta"
    meta_id = Column(Integer, primary_key=True, default=1)
    tools_md_hash = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("idx_approvals_session_id", "session_id"),
        Index("idx_approvals_status", "status"),
    )
    approval_id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), nullable=False)
    subject_type = Column(String(20), nullable=False, default="step")
    plan_id = Column(String(36), nullable=True)
    step_id = Column(String(36), nullable=True)
    tool_name = Column(String(255), nullable=False)
    args = Column(JSON, nullable=False)
    risk_summary = Column(Text, nullable=False)
    side_effect_level = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    expires_at = Column(DateTime, nullable=False)
    decided_by = Column(String(255), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ExecutionSnapshot(Base):
    __tablename__ = "execution_snapshots"
    __table_args__ = (Index("idx_snapshots_session_id", "session_id"),)
    snapshot_id = Column(String(36), primary_key=True, default=generate_uuid)
    step_id = Column(String(36), nullable=False)
    session_id = Column(String(36), nullable=False)
    tool_name = Column(String(255), nullable=False)
    tool_version = Column(Integer, nullable=False)
    schema_version = Column(Integer, nullable=False)
    input_args = Column(JSON, nullable=False)
    plan_hash = Column(String(255), nullable=False)
    plan_version = Column(Integer, nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    http_status = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    executed_at = Column(DateTime, default=datetime.utcnow)

class DeadLetter(Base):
    __tablename__ = "dead_letters"
    __table_args__ = (
        Index("idx_dlq_status", "status"),
        Index("idx_dlq_session_id", "session_id"),
    )
    dlq_id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), nullable=False)
    step_id = Column(String(36), nullable=True)
    failure_type = Column(String(255), nullable=False)
    reason = Column(Text, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(50), nullable=False, default="PENDING")
    replayed_at = Column(DateTime, nullable=True)
    replayed_by = Column(String(255), nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
    dismissed_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkflowCheckpoint(Base):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        Index("idx_checkpoints_thread_id", "thread_id", unique=True),
        Index("idx_checkpoints_session_id", "session_id"),
        Index("idx_checkpoints_user_id", "user_id"),
        Index("idx_checkpoints_updated_at", "updated_at"),
    )
    checkpoint_id = Column(String(36), primary_key=True, default=generate_uuid)
    thread_id = Column(String(255), nullable=False)
    session_id = Column(String(36), nullable=True)
    user_id = Column(String(255), nullable=True)
    state = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class VectorMemory(Base):
    __tablename__ = "vector_memories"
    __table_args__ = (
        Index("idx_vector_memories_session_id", "session_id"),
        Index("idx_vector_memories_user_id", "user_id"),
        Index("idx_vector_memories_created_at", "created_at"),
        Index("idx_vector_memories_scope", "reusable_scope"),
        Index("idx_vector_memories_source_message_id", "source_message_id"),
    )
    memory_id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), nullable=True)
    user_id = Column(String(255), nullable=True)
    memory_type = Column(String(50), nullable=False, default="conversation")
    content = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=False, default=list)
    source_message_id = Column(String(36), nullable=True)
    memory_metadata = Column(JSON, nullable=False, default=dict)
    reusable_scope = Column(String(20), nullable=False, default="session")
    pii_redacted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
