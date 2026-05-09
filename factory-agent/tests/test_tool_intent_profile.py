from factory_agent.schemas import ToolInfo
from factory_agent.planning.tool_intent_profile import (
    build_tool_intent_profile,
    build_tool_intent_vocabulary,
    intent_feature_tokens,
    profile_match_score,
    tool_covers_descriptive_terms,
    vocabulary_for_tools,
)


def _tool(name: str, description: str, endpoint: str) -> ToolInfo:
    return ToolInfo(
        name=name,
        description=description,
        endpoint=endpoint,
        method="GET",
        input_schema={"type": "object", "properties": {}},
        is_read_only=True,
        requires_approval=False,
    )


def test_profile_derives_endpoint_and_feature_tokens():
    tool = _tool("get__reports_machine-utilization", "Machine utilization", "/reports/machine-utilization")

    profile = build_tool_intent_profile(tool)

    assert profile.endpoint_root == "report"
    assert {"machine", "utilization"} <= set(profile.identity_tokens)
    assert "utilization" in profile.feature_tokens


def test_profile_scores_specialized_endpoint_above_generic_entity():
    specialized = _tool("get__reports_machine-utilization", "Machine utilization", "/reports/machine-utilization")
    generic = _tool("get__machines_utilization", "Get machine utilization", "/machines/utilization")

    assert profile_match_score("show machine utilization report", specialized) > profile_match_score(
        "show machine utilization report",
        generic,
    )


def test_profile_marks_endpoint_descriptive_terms_as_tool_evidence():
    tool = _tool("get__predictive_high-risk-jobs", "List high-risk jobs", "/predictive/high-risk-jobs")

    assert tool_covers_descriptive_terms("show predictive high risk jobs", tool)


def test_vocabulary_derives_generic_and_entity_tokens_from_registry_shape():
    tools = [
        _tool("get__machines", "Get machines", "/machines"),
        _tool("get__machines_{id}", "Get machine by id", "/machines/{id}"),
        _tool("get__reports_machine-utilization", "Get machine utilization", "/reports/machine-utilization"),
    ]

    vocabulary = build_tool_intent_vocabulary(tools, generic_threshold=0.60, operator_tokens={"show"})

    assert "get" in vocabulary.generic_tokens
    assert "machine" in vocabulary.entity_tokens
    assert "show" not in intent_feature_tokens("show machine utilization report", vocabulary=vocabulary)
    assert {"utilization", "report"} <= intent_feature_tokens("show machine utilization report", vocabulary=vocabulary)


def test_entity_tokens_still_support_specialized_endpoint_phrases():
    tools = [
        _tool("get__machines", "List machines", "/machines"),
        _tool("get__machines_{id}", "Get machine by id", "/machines/{id}"),
        _tool("get__reference_machine-types", "List machine types", "/reference/machine-types"),
    ]
    vocabulary = build_tool_intent_vocabulary(tools, generic_threshold=0.60, operator_tokens={"list"})

    assert "machine" in vocabulary.entity_tokens
    assert "type" in intent_feature_tokens("list machine types", vocabulary=vocabulary)
    assert profile_match_score("list machine types", tools[2], vocabulary=vocabulary) > profile_match_score(
        "list machine types",
        tools[0],
        vocabulary=vocabulary,
    )


def test_profile_prefers_shallow_collection_for_plain_entity_list():
    tools = [
        _tool("get__widgets", "List widgets", "/widgets"),
        _tool("get__widgets_{id}", "Get widget by id", "/widgets/{id}"),
        _tool("get__widgets_recommendations", "List widget recommendations", "/widgets/recommendations"),
        _tool("get__orders", "List orders", "/orders"),
        _tool("get__orders_{id}", "Get order by id", "/orders/{id}"),
        _tool("get__reports", "List reports", "/reports"),
    ]
    vocabulary = build_tool_intent_vocabulary(tools, generic_threshold=0.60, operator_tokens={"show"})

    assert profile_match_score("show widgets", tools[0], vocabulary=vocabulary) > profile_match_score(
        "show widgets",
        tools[2],
        vocabulary=vocabulary,
    )


def test_profile_prefers_endpoint_feature_over_filter_field_match():
    collection = _tool("get__widgets", "List widgets filtered by widget type", "/widgets")
    collection.query_params = ["widget_type"]
    collection.input_schema = {
        "type": "object",
        "properties": {"widget_type": {"type": "string"}},
        "x-query-params": ["widget_type"],
    }
    reference = _tool("get__reference_widget-types", "List widget types", "/reference/widget-types")
    tools = [
        collection,
        _tool("get__widgets_{id}", "Get widget by id", "/widgets/{id}"),
        reference,
    ]
    vocabulary = build_tool_intent_vocabulary(tools, generic_threshold=0.60, operator_tokens={"list"})

    assert profile_match_score("list widget types", reference, vocabulary=vocabulary) > profile_match_score(
        "list widget types",
        collection,
        vocabulary=vocabulary,
    )


def test_profile_prefers_requested_feature_endpoint_over_root_lookup():
    lookup = _tool("get__products_{id}", "Get product by id", "/products/{id}")
    feature = _tool("get__planning_readiness", "Check readiness", "/planning/readiness")
    tools = [
        _tool("get__products", "List products", "/products"),
        lookup,
        feature,
    ]
    vocabulary = build_tool_intent_vocabulary(tools, generic_threshold=0.60, operator_tokens={"for"})

    assert profile_match_score("readiness for product P-001", feature, vocabulary=vocabulary) > profile_match_score(
        "readiness for product P-001",
        lookup,
        vocabulary=vocabulary,
    )


def test_scoped_vocabulary_preserves_generated_entity_tokens():
    tools = [
        _tool("get__jobs_{id}", "Get job by id", "/jobs/{id}"),
        _tool("get__ai_scheduling_jobs_{id}_proposal", "Generate proposal", "/ai/scheduling/jobs/{id}/proposal"),
        _tool("get__ai_scheduling_jobs_{id}_proposals", "List proposals", "/ai/scheduling/jobs/{id}/proposals"),
    ]

    vocabulary = vocabulary_for_tools(tools)

    assert "proposal" in vocabulary.entity_tokens
    assert "proposal" not in vocabulary.generic_tokens
    assert "proposal" in intent_feature_tokens("show proposal for job JOB-SEED-001", vocabulary=vocabulary)

