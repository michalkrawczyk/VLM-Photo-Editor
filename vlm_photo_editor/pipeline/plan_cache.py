from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vlm_photo_editor.imageio.container import ImageContainer
    from vlm_photo_editor.schema.plan import HumanPlan
    from vlm_photo_editor.schema.prefs import Preferences


class PlanCache:
    def __init__(self, ttl: int = 3600) -> None:
        self._store: dict[str, tuple[HumanPlan, float]] = {}
        self._ttl = ttl

    def key(
        self,
        container: ImageContainer,
        mode: str,
        prefs: Preferences | None,
    ) -> str:
        img_hash = hashlib.sha256(container.pixels.tobytes()).hexdigest()[:16]
        prefs_ver = str(prefs.version) if prefs else "0"
        return f"{img_hash}:{mode}:{prefs_ver}"

    def get(self, key: str) -> HumanPlan | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        plan, ts = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return plan

    def set(self, key: str, plan: HumanPlan) -> None:
        self._store[key] = (plan, time.monotonic())


def _make_cache() -> PlanCache:
    from vlm_photo_editor.config.settings import get_settings

    return PlanCache(ttl=get_settings().cache_ttl_seconds)


_cache: PlanCache | None = None


def get_plan_cache() -> PlanCache:
    global _cache
    if _cache is None:
        _cache = _make_cache()
    return _cache
