from __future__ import annotations

import importlib.util

from .base import Candidate, GenAIProvider
from .google_provider import GoogleProvider
from .huggingface import HuggingFaceProvider
from .openai_provider import OpenAIProvider
from .replicate import ReplicateProvider

__all__ = [
    "Candidate",
    "GenAIProvider",
    "ReplicateProvider",
    "HuggingFaceProvider",
    "OpenAIProvider",
    "GoogleProvider",
    "DEFAULT_GENAI_MODEL",
    "get_provider",
    "provider_name_for",
    "available_genai_providers",
    "provider_env_hint",
    "default_provider_available",
]

DEFAULT_GENAI_MODEL = "black-forest-labs/flux-fill-dev"


def provider_name_for(model: str) -> str:
    if model.startswith("hf:"):
        return "huggingface"
    if model.startswith("openai:"):
        return "openai"
    if model.startswith("google:"):
        return "google"
    return "replicate"


def get_provider(model: str) -> GenAIProvider:
    name = provider_name_for(model)
    if name == "huggingface":
        return HuggingFaceProvider()
    if name == "openai":
        return OpenAIProvider()
    if name == "google":
        return GoogleProvider()
    return ReplicateProvider()


def available_genai_providers() -> list[str]:
    """Return provider names whose key/deps are currently available."""
    from vlm_photo_editor.secrets.store import SecretStore

    result: list[str] = []
    if SecretStore.has("replicate"):
        result.append("replicate")
    if SecretStore.has("openai"):
        result.append("openai")
    if SecretStore.has("google"):
        result.append("google")
    if importlib.util.find_spec("diffusers") is not None:
        result.append("huggingface")
    return result


def provider_env_hint(provider: str) -> str:
    from vlm_photo_editor.secrets.store import _env_key

    if provider == "huggingface":
        return "pip install diffusers torch"
    return _env_key(provider)


def default_provider_available() -> bool:
    """Whether the provider behind DEFAULT_GENAI_MODEL has its key/deps available."""
    return provider_name_for(DEFAULT_GENAI_MODEL) in available_genai_providers()
