from factory_agent.rag.answer_contract import answer_or_insufficient_context, validate_knowledge_answer
from factory_agent.rag.source_metadata import insufficient_context_answer


def _source(number=1):
    return {
        "source_number": number,
        "source_id": f"doc-{number}#chunk-{number}",
        "doc_id": f"doc-{number}",
        "chunk_id": f"chunk-{number}",
        "title": f"Document {number}",
        "organization": "Test Org",
        "snippet": "Supporting text.",
    }


def test_validate_knowledge_answer_accepts_cited_procedure_steps():
    result = validate_knowledge_answer(
        "1. Prepare for shutdown.[^1]\n2. Shut down the machine.[^1]",
        [_source(1)],
    )

    assert result.valid
    assert result.cited_source_numbers == (1,)


def test_validate_knowledge_answer_rejects_uncited_procedure_steps():
    answer, result = answer_or_insufficient_context(
        "1. Prepare for shutdown.\n2. Shut down the machine.",
        [_source(1)],
    )

    assert not result.valid
    assert result.reason == "missing_citations"
    assert answer == insufficient_context_answer(has_sources=True)


def test_validate_knowledge_answer_rejects_inline_step_list_with_only_trailing_citation():
    answer, result = answer_or_insufficient_context(
        "1. Prepare for shutdown; 2. Shut down the machine; 3. Disconnect energy sources.[^1]",
        [_source(1)],
    )

    assert not result.valid
    assert result.reason == "uncited_procedure_step"
    assert answer == insufficient_context_answer(has_sources=True)


def test_validate_knowledge_answer_accepts_inline_step_list_when_each_step_is_cited():
    result = validate_knowledge_answer(
        "1. Prepare for shutdown.[^1] 2. Shut down the machine.[^1] 3. Disconnect energy sources.[^1]",
        [_source(1)],
    )

    assert result.valid


def test_validate_knowledge_answer_rejects_unknown_source_number():
    answer, result = answer_or_insufficient_context("Use the procedure [^2].", [_source(1)])

    assert not result.valid
    assert result.reason == "unknown_citation"
    assert answer == insufficient_context_answer(has_sources=True)


def test_validate_knowledge_answer_rejects_plain_bracket_source_number():
    answer, result = answer_or_insufficient_context("Use the procedure [1].", [_source(1)])

    assert not result.valid
    assert result.reason == "missing_citations"
    assert answer == insufficient_context_answer(has_sources=True)


def test_validate_knowledge_answer_allows_short_uncited_framing_before_cited_steps():
    result = validate_knowledge_answer(
        "Workers must complete these steps:\n1. Prepare for shutdown.[^1]\n2. Shut down the machine.[^1]",
        [_source(1)],
    )

    assert result.valid


def test_validate_knowledge_answer_rejects_uncited_tail_after_cited_claim():
    answer, result = answer_or_insufficient_context(
        "Use the controlled procedure [^1]. This extra claim has no citation.",
        [_source(1)],
    )

    assert not result.valid
    assert result.reason == "uncited_claim"
    assert answer == insufficient_context_answer(has_sources=True)
