from tests.rag_eval.variants import (
    RUN_1_VARIANT_IDS,
    RUN_1_VARIANTS,
    get_variant,
    require_phase2_executable,
)


def test_run1_variant_registry_has_expected_ids():
    assert set(RUN_1_VARIANTS) == set(RUN_1_VARIANT_IDS)
    assert set(RUN_1_VARIANT_IDS) == {
        "V0",
        "V1",
        "V2",
        "V3",
        "V4",
        "V5",
        "V6",
        "V7",
        "V8",
        "V9",
        "V10",
        "V11",
        "V12",
        "V13",
        "V14",
        "V15",
        "V15A",
        "V15B",
        "V15C",
    }


def test_phase2_executable_variants_have_clean_retrieval_configs():
    expected = {
        "V0": ("vector", False),
        "V1": ("vector", True),
        "V2": ("hybrid", False),
        "V3": ("hybrid", True),
    }

    for variant_id, (retrieval_mode, use_rerank) in expected.items():
        variant = get_variant(variant_id)
        config = variant.to_pipeline_config()

        assert variant.phase2_executable
        assert config.retrieval_mode == retrieval_mode
        assert config.use_rerank is use_rerank
        assert config.expand_neighbors is False
        assert config.query_rewrite is False
        assert config.context_builder == "none"
        assert config.compression == "none"
        assert config.vector_top_k >= 10
        assert config.fusion_top_k >= 10


def test_context_builder_variants_are_phase3_executable():
    expected = {
        "V4": ("small_to_big", "none", False),
        "V5": ("small_to_big", "none", False),
        "V6": ("small_to_big", "light_extractive", False),
        "V7": ("small_to_big", "none", True),
        "V9": ("rse", "none", False),
        "V10": ("rse", "none", False),
        "V11": ("rse", "light_extractive", False),
        "V12": ("rse", "none", True),
    }
    for variant_id, (context_builder, compression, query_rewrite) in expected.items():
        variant = get_variant(variant_id)
        config = variant.to_pipeline_config()
        assert variant.phase2_executable
        require_phase2_executable(variant)
        assert config.context_builder == context_builder
        assert config.compression == compression
        assert config.query_rewrite is query_rewrite


def test_document_augmentation_variants_are_registered_and_executable():
    expected = {
        "V8": "small_to_big",
        "V13": "rse",
    }
    for variant_id, context_builder in expected.items():
        variant = get_variant(variant_id)
        config = variant.to_pipeline_config()

        assert variant.phase2_executable
        require_phase2_executable(variant)
        assert config.document_augmentation is True
        assert config.retrieval_mode == "hybrid"
        assert config.use_rerank is True
        assert config.context_builder == context_builder
        assert config.compression == "none"
        assert config.query_rewrite is False
        assert "augmented" in variant.index_paths()["vector_db_path"]
        assert "augmented" in variant.index_paths()["bm25_path"]


def test_v8_uses_small_to_big_not_rse():
    config = get_variant("V8").to_pipeline_config()
    assert config.context_builder == "small_to_big"
    assert config.context_builder != "rse"


def test_v13_uses_rse_not_small_to_big():
    config = get_variant("V13").to_pipeline_config()
    assert config.context_builder == "rse"
    assert config.context_builder != "small_to_big"


def test_v14_uses_budgeted_rse_without_changing_v12():
    v12 = get_variant("V12").to_pipeline_config()
    v14 = get_variant("V14").to_pipeline_config()

    assert v12.context_builder == "rse"
    assert v12.compression == "none"
    assert v12.document_augmentation is False
    assert v12.allow_rerank_fallback is False

    assert v14.variant_id == "V14"
    assert v14.retrieval_mode == "hybrid"
    assert v14.use_rerank is True
    assert v14.expand_neighbors is False
    assert v14.query_rewrite is True
    assert v14.context_builder == "budgeted_rse"
    assert v14.compression == "none"
    assert v14.document_augmentation is False
    assert v14.allow_rerank_fallback is False
    assert v14.context_builder_settings["budgeted_rse"]["max_context_tokens"] <= 3500
    assert v14.context_builder_settings["budgeted_rse"]["max_segment_tokens"] <= 1600


def test_v15_uses_corpus_aware_multi_query_and_evidence_cards_without_changing_v14():
    v14 = get_variant("V14").to_pipeline_config()
    v15 = get_variant("V15").to_pipeline_config()

    assert v14.query_rewrite is True
    assert v14.corpus_aware_query_rewrite is False
    assert v14.multi_query_retrieval is False
    assert v14.context_builder == "budgeted_rse"
    assert v14.context_builder_settings["budgeted_rse"]["use_evidence_cards"] is False

    assert v15.variant_id == "V15"
    assert v15.retrieval_mode == "hybrid"
    assert v15.use_rerank is True
    assert v15.expand_neighbors is False
    assert v15.query_rewrite is False
    assert v15.corpus_aware_query_rewrite is True
    assert v15.multi_query_retrieval is True
    assert v15.context_builder == "budgeted_rse"
    assert v15.compression == "none"
    assert v15.document_augmentation is False
    assert v15.allow_rerank_fallback is False
    assert v15.context_builder_settings["budgeted_rse"]["use_evidence_cards"] is True
    assert v15.context_builder_settings["budgeted_rse"]["max_context_tokens"] <= 3500


def test_v15_abc_split_keeps_v12_and_v14_intact_and_avoids_legacy_rewrite():
    v12 = get_variant("V12").to_pipeline_config()
    v14 = get_variant("V14").to_pipeline_config()
    v15a = get_variant("V15A").to_pipeline_config()
    v15b = get_variant("V15B").to_pipeline_config()
    v15c = get_variant("V15C").to_pipeline_config()

    assert v12.query_rewrite is True
    assert v12.corpus_aware_query_rewrite is False
    assert v12.context_builder == "rse"

    assert v14.query_rewrite is True
    assert v14.corpus_aware_query_rewrite is False
    assert v14.context_builder == "budgeted_rse"
    assert v14.context_builder_settings["budgeted_rse"]["use_evidence_cards"] is False

    for config in (v15a, v15b, v15c):
        assert config.retrieval_mode == "hybrid"
        assert config.use_rerank is True
        assert config.expand_neighbors is False
        assert config.query_rewrite is False
        assert config.corpus_aware_query_rewrite is True
        assert config.multi_query_retrieval is True
        assert config.context_builder == "budgeted_rse"
        assert config.compression == "none"
        assert config.document_augmentation is False
        assert config.allow_rerank_fallback is False

    assert v15a.context_builder_settings["budgeted_rse"]["use_evidence_cards"] is False
    assert v15b.context_builder_settings["budgeted_rse"]["use_evidence_cards"] is True
    assert v15b.context_builder_settings["budgeted_rse"]["evidence_card_context_mode"] == "metadata_only"
    assert v15c.context_builder_settings["budgeted_rse"]["use_evidence_cards"] is True
    assert v15c.context_builder_settings["budgeted_rse"]["evidence_card_context_mode"] == "mode_aware"
