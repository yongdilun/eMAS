from factory_agent.planning.intent import semantic_frame_for_text
from factory_agent.rag.knowledge_policy import default_knowledge_policy_registry


OSHA_LOTO_PROMPT = (
    "What is the purpose of Lockout/Tagout (LOTO) procedures according to OSHA? "
    "Is there any specific OSHA regulation or standard that defines this?"
)
UNSUPPORTED_NOTIFICATION_PROMPT = (
    "According to the OSHA lockout/tagout guide, what notification is required before starting lockout?"
)
SYNTHETIC_NOTIFICATION_SOURCE_ID = "loto_notification_requirement"
SYNTHETIC_NOTIFICATION_SOURCE_TITLE = "LOTO Notification Requirements"

MINIMUM_SOURCE_LOCATOR_FIELDS = {
    "source_id",
    "source_number",
    "doc_id",
    "chunk_id",
    "title",
    "organization",
    "snippet",
}


def assert_minimum_locator(source):
    missing = [key for key in MINIMUM_SOURCE_LOCATOR_FIELDS if not source.get(key)]
    assert not missing, f"missing source locator fields: {missing}"
    assert "file_path" not in source


def assert_no_synthetic_loto_notification_source(result):
    serialized = str(result.answer) + " " + str(result.sources)
    assert SYNTHETIC_NOTIFICATION_SOURCE_ID not in serialized
    assert SYNTHETIC_NOTIFICATION_SOURCE_TITLE not in serialized
    assert "policy:loto-notification-requirement" not in serialized


def test_loto_notification_policy_uses_insufficient_context_without_retrieved_evidence():
    registry = default_knowledge_policy_registry()
    frame = semantic_frame_for_text(UNSUPPORTED_NOTIFICATION_PROMPT)

    result = registry.apply(
        route_family=frame.route,
        query=UNSUPPORTED_NOTIFICATION_PROMPT,
        answer="No relevant documents or data found for this query.",
        sources=[],
        safety_content=None,
        semantic_frame=frame,
    )

    assert result.policy_id == "loto_notification_document_content"
    assert result.answer.startswith("I do not have enough retrieved evidence")
    assert "affected employees to be notified before lockout/tagout starts" not in result.answer
    assert result.sources == []
    assert_no_synthetic_loto_notification_source(result)
    assert "approved energy-control procedure" in result.safety_content


def test_loto_notification_policy_keeps_related_retrieved_sources_without_synthetic_source():
    registry = default_knowledge_policy_registry()
    frame = semantic_frame_for_text(UNSUPPORTED_NOTIFICATION_PROMPT)

    result = registry.apply(
        route_family=frame.route,
        query=UNSUPPORTED_NOTIFICATION_PROMPT,
        answer="The OSHA guide describes energy-control program responsibilities [^1].",
        sources=[
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "title": "Control of Hazardous Energy Lockout/Tagout",
                "organization": "OSHA",
                "chunk_id": "osha_3120_lockout_tagout_c0001",
                "snippet": "Energy-control program responsibilities are described in the OSHA guide.",
            }
        ],
        safety_content=None,
        semantic_frame=frame,
    )

    assert result.policy_id == "loto_notification_document_content"
    assert result.answer.startswith("I do not have enough retrieved evidence")
    assert "related sources checked" in result.answer
    assert [source["doc_id"] for source in result.sources] == ["osha_3120_lockout_tagout"]
    assert [source["source_number"] for source in result.sources] == [1]
    assert_no_synthetic_loto_notification_source(result)
    for source in result.sources:
        assert_minimum_locator(source)
        assert source.get("policy_only") is not True
    assert "approved energy-control procedure" in result.safety_content


def test_loto_notification_policy_preserves_answer_when_retrieved_evidence_supports_claim():
    registry = default_knowledge_policy_registry()
    prompt = "What does the LOTO procedure say about notifying affected employees before lockout?"
    frame = semantic_frame_for_text(prompt)

    result = registry.apply(
        route_family=frame.route,
        query=prompt,
        answer="The retrieved procedure says to notify affected employees before lockout starts [^1].",
        sources=[
            {
                "source_number": 1,
                "doc_id": "osha_3120_lockout_tagout",
                "chunk_id": "osha_3120_lockout_tagout_c0027",
                "title": "Control of Hazardous Energy Lockout/Tagout",
                "organization": "OSHA",
                "snippet": "Notify affected employees before lockout starts.",
            }
        ],
        safety_content=None,
        semantic_frame=frame,
    )

    assert result.policy_id == "loto_notification_document_content"
    assert result.answer == "The retrieved procedure says to notify affected employees before lockout starts [^1]."
    assert [source["doc_id"] for source in result.sources] == ["osha_3120_lockout_tagout"]
    assert_no_synthetic_loto_notification_source(result)
    assert "approved energy-control procedure" in result.safety_content


def test_osha_loto_policy_does_not_invent_standard_when_rag_is_empty():
    registry = default_knowledge_policy_registry()
    frame = semantic_frame_for_text(OSHA_LOTO_PROMPT)

    result = registry.apply(
        route_family=frame.route,
        query=OSHA_LOTO_PROMPT,
        answer="No relevant documents or data found for this query.",
        sources=[],
        safety_content=None,
        semantic_frame=frame,
    )

    assert result.policy_id == "osha_loto_control_of_hazardous_energy"
    assert result.answer.startswith("I do not have enough retrieved evidence")
    assert "29 CFR 1910.147" not in result.answer
    assert result.sources == []
    assert "consult your safety officer" in result.safety_content


def test_unknown_non_loto_procedure_prompt_has_no_osha_loto_policy():
    registry = default_knowledge_policy_registry()
    prompt = "What SOP applies before cleaning Line 2?"
    frame = semantic_frame_for_text(prompt)

    result = registry.apply(
        route_family=frame.route,
        query=prompt,
        answer="No relevant documents or data found for this query.",
        sources=[],
        safety_content=None,
        semantic_frame=frame,
    )

    assert frame.route == "rag.procedure"
    assert result.policy_id is None
    assert "29 CFR 1910.147" not in result.answer
    assert result.answer.startswith("I do not have enough retrieved evidence")
    assert result.sources == []
    assert result.safety_content is None


def test_osha_loto_policy_is_route_scoped_not_keyword_only():
    registry = default_knowledge_policy_registry()
    prompt = "Use OSHA LOTO guidance and show machine M-CNC-01 status"
    frame = semantic_frame_for_text(prompt)

    result = registry.apply(
        route_family=frame.route,
        query=prompt,
        answer="",
        sources=[],
        safety_content=None,
        semantic_frame=frame,
    )

    assert frame.route == "tool.read.machine_status"
    assert result.policy_id is None
    assert result.answer == ""
    assert result.sources == []
