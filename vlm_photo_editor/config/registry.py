from __future__ import annotations

_DEFAULT_MAPPINGS: dict[str, str] = {
    "planner": "claude-sonnet-4-6",
    "critic": "claude-sonnet-4-6",
    "preference_aggregator": "claude-haiku-4-5-20251001",
}


class ModelRegistry:
    def __init__(self, mappings: dict[str, str] | None = None) -> None:
        self._mappings: dict[str, str] = dict(mappings or _DEFAULT_MAPPINGS)

    def get(self, role: str) -> str:
        if role not in self._mappings:
            raise KeyError(f"Unknown role: {role!r}. Available: {sorted(self._mappings)}")
        return self._mappings[role]

    def set(self, role: str, model: str) -> None:
        self._mappings[role] = model

    def all_roles(self) -> dict[str, str]:
        return dict(self._mappings)


_registry = ModelRegistry()


def get_registry() -> ModelRegistry:
    return _registry
