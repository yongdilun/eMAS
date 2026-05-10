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
