from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vlm_photo_editor.imageio.container import ImageContainer
    from vlm_photo_editor.schema.plan import HumanPlan
    from vlm_photo_editor.schema.prefs import Preferences


# Bump when the op vocabulary the planner is told about changes meaning (e.g. WB direction),
# or the planner prompt/plan shape changes (v3: diagnosis, few-shot, order/minimal-edit rules;
# v4: tone op; v5: saturation, sharpen ops), so plans cached under the old wording are not replayed.
_KEY_VERSION = 5


class PlanCache:
    def __init__(self, ttl: int = 3600) -> None:
        self._store: dict[str, tuple[HumanPlan, float]] = {}
        self._ttl = ttl

    def key(
        self,
        container: ImageContainer,
        mode: str,
        prefs: Preferences | None,
        intent: str = "",
        framing_mode: str | None = None,
    ) -> str:
        img_hash = hashlib.sha256(container.pixels.tobytes()).hexdigest()[:16]
        prefs_ver = str(prefs.version) if prefs else "0"
        # intent and framing_mode change the plan the VLM produces, so they must be
        # part of the key — otherwise a second request on the same image+mode replays
        # the first plan.
        intent_hash = hashlib.sha256(intent.encode("utf-8")).hexdigest()[:16]
        return f"v{_KEY_VERSION}:{img_hash}:{mode}:{prefs_ver}:{framing_mode or '-'}:{intent_hash}"

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
