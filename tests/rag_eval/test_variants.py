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
