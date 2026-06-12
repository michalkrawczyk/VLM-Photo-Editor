from __future__ import annotations

from typing import TYPE_CHECKING

from vlm_photo_editor.config.registry import get_registry
from vlm_photo_editor.secrets.store import SecretStore

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def build_client(role: str) -> "BaseChatModel":
    model_id = get_registry().get(role)

    if "claude" in model_id or "anthropic" in model_id:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise ImportError(
                "langchain-anthropic not installed. Run: pip install -r requirements-anthropic.txt"
            ) from exc
        api_key = SecretStore.get("anthropic")
        return ChatAnthropic(model=model_id, api_key=api_key)  # type: ignore[call-arg]

    if "gpt" in model_id:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ImportError(
                "langchain-openai not installed. Run: pip install -r requirements-openai.txt"
            ) from exc
        api_key = SecretStore.get("openai")
        return ChatOpenAI(model=model_id, api_key=api_key)  # type: ignore[call-arg]

    raise ValueError(f"Cannot determine provider for model: {model_id!r}")
