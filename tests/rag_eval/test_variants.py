import pytest

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
        "V9",
        "V10",
        "V11",
        "V12",
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


def test_context_builder_variants_are_registered_but_not_phase2_executable():
    for variant_id in ("V4", "V5", "V6", "V7", "V9", "V10", "V11", "V12"):
        variant = get_variant(variant_id)
        assert not variant.phase2_executable
        with pytest.raises(NotImplementedError):
            require_phase2_executable(variant)
