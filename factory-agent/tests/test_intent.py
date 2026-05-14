from factory_agent.planning.intent import assess_intent


def test_assess_intent_treats_create_then_reject_as_create_operation():
    assessment = assess_intent("create job P-005 qty 3 but reject it")
    assert assessment.kind == "operations"
    assert assessment.action == "create"
    assert assessment.entity == "job"


def test_assess_intent_recognizes_scheduling_read_phrases():
    assessment = assess_intent("readiness for product P-001")
    assert assessment.kind == "operations"
    assert assessment.action == "read"
    assert assessment.entity == "product"


def test_assess_intent_treats_pure_osha_loto_question_as_knowledge_conversation():
    assessment = assess_intent(
        "What is the purpose of Lockout/Tagout (LOTO) procedures according to OSHA? "
        "Is there any specific OSHA regulation or standard that defines this?"
    )
    assert assessment.kind == "conversation"
    assert assessment.action is None
    assert assessment.entity is None
    assert assessment.reply is None
