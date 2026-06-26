from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from vlm_photo_editor.config.registry import get_registry
from vlm_photo_editor.secrets.store import SecretStore

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


def build_client(role: str) -> "BaseChatModel":
    entry = get_registry().get_entry(role)
    model_id = entry.model_id

    if entry.provider == "local":
        if entry.loader == "vllm":
            try:
                from langchain_openai import ChatOpenAI
            except ImportError as exc:
                raise ImportError(
                    "langchain-openai not installed. Run: pip install -r requirements-openai.txt"
                ) from exc
            return ChatOpenAI(base_url=entry.vllm_base_url, model=model_id, api_key="not-needed")  # type: ignore[call-arg]

        if entry.loader == "llamacpp":
            if not entry.gguf_path:
                raise ValueError(
                    f"loader='llamacpp' requires gguf_path in ModelEntry for role {role!r}"
                )
            try:
                from langchain_community.chat_models import ChatLlamaCpp
            except ImportError as exc:
                raise ImportError(
                    "langchain-community not installed. Run: pip install -r requirements-llamacpp.txt"
                ) from exc
            return ChatLlamaCpp(model_path=entry.gguf_path)  # type: ignore[return-value]

        if entry.loader == "ollama":
            try:
                from langchain_ollama import ChatOllama
            except ImportError as exc:
                raise ImportError(
                    "langchain-ollama not installed. Run: pip install -r requirements-ollama.txt"
                ) from exc
            return ChatOllama(model=model_id)  # type: ignore[return-value]

        try:
            from langchain_huggingface import HuggingFacePipeline
        except ImportError as exc:
            raise ImportError(
                "langchain-huggingface not installed. Run: pip install -r requirements-huggingface.txt"
            ) from exc
        hf_repo = entry.hf_repo or model_id
        return HuggingFacePipeline.from_model_id(model_id=hf_repo, task="text-generation")  # type: ignore[return-value]

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


_LOADER_REQS: dict[str, str] = {
    "ollama": "requirements-ollama.txt",
    "transformers": "requirements-huggingface.txt",
    "vllm": "requirements-openai.txt",
    "llamacpp": "requirements-llamacpp.txt",
}


def _vllm_reachable() -> bool:
    import urllib.request

    registry = get_registry()
    base_url = "http://localhost:8000/v1"
    for entry in registry._entries.values():
        if getattr(entry, "loader", None) == "vllm":
            base_url = entry.vllm_base_url
            break
    # Try /v1/models then /health
    probes = [
        base_url.rstrip("/") + "/models",
        base_url.rstrip("/").removesuffix("/v1") + "/health",
    ]
    for url in probes:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            pass
    return False


def available_loaders() -> list[str]:
    """Return loader names whose packages are installed (and server reachable for vLLM)."""
    import importlib.util

    result: list[str] = []
    if importlib.util.find_spec("langchain_ollama"):
        result.append("ollama")
    if importlib.util.find_spec("langchain_huggingface"):
        result.append("transformers")
    if importlib.util.find_spec("langchain_community") and importlib.util.find_spec("llama_cpp"):
        result.append("llamacpp")
    if importlib.util.find_spec("langchain_openai") and _vllm_reachable():
        result.append("vllm")
    return result


def install_loader_deps(loader: str) -> bool:
    """Run pip install for the given loader's requirements file. Returns True on success."""
    if loader not in _LOADER_REQS:
        raise ValueError(f"Unknown loader: {loader!r}. Available: {sorted(_LOADER_REQS)}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", _LOADER_REQS[loader]],
        capture_output=True,
    )
    return result.returncode == 0
