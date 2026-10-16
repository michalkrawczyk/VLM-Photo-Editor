from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


@dataclass
class ModelEntry:
    model_id: str
    provider: Literal["anthropic", "replicate", "local", "openai"] = "anthropic"
    hf_repo: str | None = None
    loader: Literal["transformers", "ollama", "vllm", "llamacpp"] | None = None
    vllm_base_url: str = "http://localhost:8000/v1"
    gguf_path: str | None = None
    max_images_per_call: int = 1
    # OpenAI-only knobs (ignored for other providers):
    reasoning_effort: str | None = None  # "none" | "low" | "medium" | "high"; None = API default
    use_responses_api: bool = False  # route via /v1/responses — needed for reasoning + tools

    @property
    def is_local(self) -> bool:
        return self.provider == "local"


# Named presets for the preference_aggregator role — shown in the UI model switcher.
AGGREGATOR_PRESETS: dict[str, ModelEntry] = {
    "LFM2.5-1.2B (local)": ModelEntry(
        "LiquidAI/LFM2.5-1.2B-Instruct",
        provider="local",
        hf_repo="LiquidAI/LFM2.5-1.2B-Instruct",
        loader="transformers",
    ),
    "claude-haiku-4.5": ModelEntry("claude-haiku-4-5-20251001"),
    "gpt-4.1-mini": ModelEntry("gpt-4.1-mini", provider="openai"),
    "gpt-6-luna": ModelEntry("gpt-6-luna", provider="openai", use_responses_api=True),
    "gpt-6-luna (no reasoning)": ModelEntry(
        "gpt-6-luna", provider="openai", reasoning_effort="none"
    ),
    "gpt-6.1-sol": ModelEntry("gpt-6.1-sol", provider="openai", use_responses_api=True),
    "gpt-6.1-sol (no reasoning)": ModelEntry(
        "gpt-6.1-sol", provider="openai", reasoning_effort="none"
    ),
    "gpt-6-astra": ModelEntry("gpt-6-astra", provider="openai", use_responses_api=True),
    "gpt-6-astra (no reasoning)": ModelEntry(
        "gpt-6-astra", provider="openai", reasoning_effort="none"
    ),
}

# Named presets for the critic role — shown in the UI model switcher.
CRITIC_PRESETS: dict[str, ModelEntry] = {
    "LFM2.5-VL-1.6B (local)": ModelEntry(
        "LiquidAI/LFM2.5-VL-1.6B",
        provider="local",
        hf_repo="LiquidAI/LFM2.5-VL-1.6B",
        loader="transformers",
    ),
    "claude-sonnet-5.5": ModelEntry("claude-sonnet-5-5"),
    "gpt-6-luna": ModelEntry("gpt-6-luna", provider="openai", use_responses_api=True),
    "gpt-6-luna (no reasoning)": ModelEntry(
        "gpt-6-luna", provider="openai", reasoning_effort="none"
    ),
    "gpt-6.1-sol": ModelEntry("gpt-6.1-sol", provider="openai", use_responses_api=True),
    "gpt-6.1-sol (no reasoning)": ModelEntry(
        "gpt-6.1-sol", provider="openai", reasoning_effort="none"
    ),
    "gpt-6-astra": ModelEntry("gpt-6-astra", provider="openai", use_responses_api=True),
    "gpt-6-astra (no reasoning)": ModelEntry(
        "gpt-6-astra", provider="openai", reasoning_effort="none"
    ),
}

# Named presets for the planner role — shown in the UI model switcher.
PLANNER_PRESETS: dict[str, ModelEntry] = {
    "claude-sonnet-5.5": ModelEntry("claude-sonnet-5-5"),
    "claude-haiku-4.5": ModelEntry("claude-haiku-4-5-20251001"),
    "claude-opus-5.5": ModelEntry("claude-opus-5-5"),
    "gpt-4.1-mini": ModelEntry("gpt-4.1-mini", provider="openai"),
    "gpt-6-luna": ModelEntry("gpt-6-luna", provider="openai", use_responses_api=True),
    "gpt-6-luna (no reasoning)": ModelEntry(
        "gpt-6-luna", provider="openai", reasoning_effort="none"
    ),
    "gpt-6.1-sol": ModelEntry("gpt-6.1-sol", provider="openai", use_responses_api=True),
    "gpt-6.1-sol (no reasoning)": ModelEntry(
        "gpt-6.1-sol", provider="openai", reasoning_effort="none"
    ),
    "gpt-6-astra": ModelEntry("gpt-6-astra", provider="openai", use_responses_api=True),
    "gpt-6-astra (no reasoning)": ModelEntry(
        "gpt-6-astra", provider="openai", reasoning_effort="none"
    ),
}

_DEFAULT_ENTRIES: dict[str, ModelEntry] = {
    "planner": PLANNER_PRESETS["gpt-6.1-sol"],
    "critic": CRITIC_PRESETS["gpt-6.1-sol"],
    # Default: local LFM2.5-1.2B — no API cost; switchable via AGGREGATOR_PRESETS in the UI.
    "preference_aggregator": AGGREGATOR_PRESETS["LFM2.5-1.2B (local)"],
    # Lightweight on-device router for P10 cost triage; no API key required.
    "cost_router": ModelEntry(
        "LiquidAI/LFM2.5-1.2B-Instruct",
        provider="local",
        hf_repo="LiquidAI/LFM2.5-1.2B-Instruct",
        loader="transformers",
    ),
}


class ModelRegistry:
    def __init__(self, mappings: dict[str, str] | None = None) -> None:
        if mappings is not None:
            self._entries: dict[str, ModelEntry] = {
                role: ModelEntry(mid) for role, mid in mappings.items()
            }
        else:
            self._entries = dict(_DEFAULT_ENTRIES)

    def get(self, role: str) -> str:
        return self.get_entry(role).model_id

    def get_entry(self, role: str) -> ModelEntry:
        if role not in self._entries:
            raise KeyError(f"Unknown role: {role!r}. Available: {sorted(self._entries)}")
        return self._entries[role]

    def set(self, role: str, model: str) -> None:
        """Change only ``model_id`` for ``role``.

        ``provider``/``loader``/``vllm_base_url`` are preserved from the existing
        entry. For a cross-provider swap (e.g. Anthropic default → an OpenAI id)
        use :meth:`set_entry` with a fully populated ``ModelEntry`` — otherwise the
        stale provider drives ``build_client`` and the wrong client is built (CFG-B1).
        """
        existing = self._entries.get(role)
        if existing is not None:
            self._entries[role] = replace(existing, model_id=model)
        else:
            self._entries[role] = ModelEntry(model)

    def set_entry(self, role: str, entry: ModelEntry) -> None:
        """Replace the full entry (model_id + provider + loader) for a role."""
        self._entries[role] = entry

    def all_roles(self) -> dict[str, str]:
        return {role: entry.model_id for role, entry in self._entries.items()}


_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    return _registry
