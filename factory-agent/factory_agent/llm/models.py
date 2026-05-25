"""OpenAI-compatible chat model factory for planner LLM calls."""

from __future__ import annotations

from typing import Any

from ..config import Settings


class PlannerLLMError(RuntimeError):
    pass


def build_planner_chat_model(settings: Settings, *, json_mode: bool = False):
    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        raise PlannerLLMError("LangGraph planner requires langchain-openai.") from exc

    kwargs: dict[str, Any] = {
        "model": settings.planner_model,
        "temperature": 0,
        "timeout": settings.planner_timeout_s,
        "max_retries": 0,
        "max_tokens": max(settings.planner_max_tokens, 900),
    }
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    if settings.planner_openai_base_url:
        kwargs["base_url"] = settings.planner_openai_base_url
        kwargs["api_key"] = settings.openai_api_key or "local"
    elif settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    return ChatOpenAI(**kwargs)


def build_rag_reranker_chat_model(settings: Settings, *, json_mode: bool = True):
    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        raise PlannerLLMError("RAG reranker requires langchain-openai.") from exc

    kwargs: dict[str, Any] = {
        "model": settings.rag_reranker_model,
        "temperature": 0,
        "timeout": settings.rag_reranker_timeout_s,
        "max_retries": 0,
        "max_tokens": settings.rag_reranker_max_tokens,
    }
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    
    if settings.rag_reranker_openai_base_url:
        kwargs["base_url"] = settings.rag_reranker_openai_base_url
        kwargs["api_key"] = settings.openai_api_key or "local"
    elif settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    return ChatOpenAI(**kwargs)


def build_rag_answer_chat_model(settings: Settings):
    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        raise PlannerLLMError("RAG answer generator requires langchain-openai.") from exc

    kwargs: dict[str, Any] = {
        "model": settings.rag_answer_model,
        "temperature": 0,
        "timeout": settings.rag_answer_timeout_s,
        "max_retries": 0,
        "max_tokens": settings.rag_answer_max_tokens,
    }
    
    if settings.rag_answer_openai_base_url:
        kwargs["base_url"] = settings.rag_answer_openai_base_url
        kwargs["api_key"] = settings.openai_api_key or "local"
    elif settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    return ChatOpenAI(**kwargs)


class TransformersCrossEncoderReranker:
    """Small cross-encoder wrapper with the same ``compute_score`` surface as FlagReranker."""

    def __init__(self, model_name: str, *, device: str | None = None, batch_size: int = 8) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except Exception as exc:  # pragma: no cover - import availability depends on runtime image.
            raise PlannerLLMError("BGE reranker requires torch and transformers.") from exc

        self._torch = torch
        self.model_name = model_name
        self.batch_size = max(1, int(batch_size))
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()

    def compute_score(self, pairs: list[list[str]] | list[tuple[str, str]], *, max_length: int = 1024) -> list[float]:
        if not pairs:
            return []

        scores: list[float] = []
        for start in range(0, len(pairs), self.batch_size):
            batch = pairs[start : start + self.batch_size]
            queries = [str(pair[0]) for pair in batch]
            documents = [str(pair[1]) for pair in batch]
            encoded = self.tokenizer(
                queries,
                documents,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with self._torch.inference_mode():
                output = self.model(**encoded)
            logits = output.logits.detach().float().cpu().view(-1)
            scores.extend(float(value) for value in logits.tolist())
        return scores


def build_bge_reranker(settings: Settings):
    """Build the RAG cross-encoder reranker.

    ``FlagEmbedding`` 1.4.0 calls ``XLMRobertaTokenizer.prepare_for_model``,
    which is absent in the installed Transformers runtime. The direct
    Transformers wrapper keeps the same BGE model while avoiding that broken
    integration layer.
    """

    return TransformersCrossEncoderReranker(settings.bge_reranker_model)
