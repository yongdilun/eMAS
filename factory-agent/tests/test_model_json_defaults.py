import pytest

from factory_agent.persistence.models import DeadLetter, VectorMemory, WorkflowCheckpoint


def _default_for(model, column_name):
    return getattr(model, column_name).property.columns[0].default


def test_json_mutable_defaults_are_callable():
    defaults = [
        _default_for(DeadLetter, "payload"),
        _default_for(WorkflowCheckpoint, "state"),
        _default_for(VectorMemory, "embedding"),
        _default_for(VectorMemory, "memory_metadata"),
    ]

    assert all(default is not None for default in defaults)
    assert all(default.is_callable for default in defaults)


@pytest.mark.asyncio
async def test_json_defaults_are_isolated_between_rows(db_session):
    first = DeadLetter(
        session_id="session-a",
        failure_type="tool_error",
        reason="first",
    )
    second = DeadLetter(
        session_id="session-b",
        failure_type="tool_error",
        reason="second",
    )
    checkpoint_a = WorkflowCheckpoint(thread_id="thread-a")
    checkpoint_b = WorkflowCheckpoint(thread_id="thread-b")
    memory_a = VectorMemory(content="alpha")
    memory_b = VectorMemory(content="beta")

    db_session.add_all([first, second, checkpoint_a, checkpoint_b, memory_a, memory_b])
    await db_session.flush()

    first.payload["changed"] = True
    checkpoint_a.state["changed"] = True
    memory_a.embedding.append(1.0)
    memory_a.memory_metadata["changed"] = True

    assert second.payload == {}
    assert checkpoint_b.state == {}
    assert memory_b.embedding == []
    assert memory_b.memory_metadata == {}
