"""Unit tests for P9: Critic agent, PS-strict/No-PS mode, local model indicator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from vlm_photo_editor.agents.critic import Critic, CriticVerdict, _encode_image
from vlm_photo_editor.config.registry import CRITIC_PRESETS, ModelEntry, ModelRegistry
from vlm_photo_editor.config.settings import AppSettings

# ── Helpers ───────────────────────────────────────────────────────────────────


def _blank(w: int = 4, h: int = 4) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _mock_critic_response(json_str: str) -> MagicMock:
    resp = MagicMock()
    resp.content = json_str
    return resp


# ── Critic verdicts ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "response_json,expected_passed,expected_reason_substr,expected_uncertain",
    [
        ('{"passed": true, "reason": "looks good"}', True, "looks good", False),
        (
            '{"passed": false, "reason": "exposure not changed"}',
            False,
            "exposure not changed",
            False,
        ),
        ("Sorry I cannot help", True, "parse error", True),  # fail-open on bad JSON
    ],
)
def test_critic_verdict(
    response_json: str,
    expected_passed: bool,
    expected_reason_substr: str,
    expected_uncertain: bool,
) -> None:
    with patch("vlm_photo_editor.agents.critic.build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.invoke.return_value = _mock_critic_response(response_json)
        mock_build.return_value = mock_client

        verdict = Critic().verify(_blank(), _blank(), "improve exposure")

    assert verdict.passed is expected_passed
    assert expected_reason_substr in verdict.reason
    assert verdict.uncertain is expected_uncertain


def test_critic_fail_open_on_exception() -> None:
    with patch("vlm_photo_editor.agents.critic.build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.invoke.side_effect = RuntimeError("network error")
        mock_build.return_value = mock_client

        verdict = Critic().verify(_blank(), _blank(), "remove background")

    assert verdict.passed is True
    assert "critic error" in verdict.reason
    assert verdict.uncertain is True


# ── CriticVerdict dataclass ────────────────────────────────────────────────────


def test_critic_verdict_fields() -> None:
    v = CriticVerdict(passed=False, reason="too dark")
    assert v.passed is False
    assert v.reason == "too dark"
    assert v.uncertain is False


# ── _encode_image dtype handling ────────────────────────────────────────────────


def test_encode_image_handles_16bit_without_wraparound() -> None:
    pixels16 = np.zeros((4, 4, 3), dtype=np.uint16)
    pixels16[:2, :, :] = 60000  # bright half; raw uint8 cast would wrap this to a low value

    b64 = _encode_image(pixels16)

    import base64
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(base64.standard_b64decode(b64)))
    arr = np.array(img)
    assert arr.dtype == np.uint8
    assert arr[:2].mean() > arr[2:].mean()  # bright half normalized brighter than dark half


# ── use_local_critic removed ──────────────────────────────────────────────────


def test_use_local_critic_removed() -> None:
    assert not hasattr(
        AppSettings(), "use_local_critic"
    ), "AppSettings.use_local_critic was removed in P9 — derive from registry entry"


def test_local_model_loader_removed() -> None:
    assert not hasattr(
        AppSettings(), "local_model_loader"
    ), "AppSettings.local_model_loader was removed in P9"


# ── ModelEntry.is_local ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("local", True),
        ("anthropic", False),
        ("openai", False),
        ("replicate", False),
    ],
)
def test_model_entry_is_local(provider: str, expected: bool) -> None:
    entry = ModelEntry("some-model", provider=provider)
    assert entry.is_local is expected


def test_critic_local_entry_is_local() -> None:
    registry = ModelRegistry()
    registry.set_entry("critic", ModelEntry("LiquidAI/LFM2.5-VL-1.6B", provider="local"))
    assert registry.get_entry("critic").is_local is True


def test_critic_cloud_entry_not_local() -> None:
    registry = ModelRegistry()
    assert registry.get_entry("critic").is_local is False  # default is cloud


# ── CRITIC_PRESETS ─────────────────────────────────────────────────────────────


def test_critic_presets_cover_local_and_cloud() -> None:
    has_local = any(e.is_local for e in CRITIC_PRESETS.values())
    has_cloud = any(not e.is_local for e in CRITIC_PRESETS.values())
    assert has_local, "CRITIC_PRESETS must include at least one local option"
    assert has_cloud, "CRITIC_PRESETS must include at least one cloud option"


@pytest.mark.parametrize(
    "preset_name,expected_provider",
    [
        ("LFM2.5-VL-1.6B (local)", "local"),
        ("claude-sonnet-4.6", "anthropic"),
        ("gpt-4o", "openai"),
    ],
)
def test_critic_preset_providers(preset_name: str, expected_provider: str) -> None:
    entry = CRITIC_PRESETS[preset_name]
    assert entry.provider == expected_provider


# ── PS-strict planner prompt ──────────────────────────────────────────────────


def test_ps_strict_lines_injected_when_strict() -> None:
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.templates.planner import build_system_prompt

    settings = get_settings()
    original = settings.ps_mode
    try:
        settings.ps_mode = "strict"
        prompt = build_system_prompt("full", None, None, None)
        assert "PS-STRICT MODE" in prompt
        assert 'backend="genai"' in prompt or 'backend="genai"' in prompt
    finally:
        settings.ps_mode = original


def test_ps_strict_lines_absent_in_auto() -> None:
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.templates.planner import build_system_prompt

    settings = get_settings()
    original = settings.ps_mode
    try:
        settings.ps_mode = "auto"
        prompt = build_system_prompt("full", None, None, None)
        assert "PS-STRICT MODE" not in prompt
    finally:
        settings.ps_mode = original


# ── Compiler PS-strict enforcement ────────────────────────────────────────────


def test_compiler_ps_strict_raises_when_ps_absent() -> None:
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.planner.compiler import Compiler, CompilerError
    from vlm_photo_editor.schema.plan import HumanPlan

    settings = get_settings()
    original = settings.ps_mode
    try:
        settings.ps_mode = "strict"
        plan = HumanPlan(steps=[], mode="full")
        with patch("vlm_photo_editor.planner.compiler._ps_available", return_value=False):
            with pytest.raises(CompilerError, match="Photoshop"):
                Compiler().compile(plan, "full")
    finally:
        settings.ps_mode = original


def test_compiler_ps_strict_passes_when_ps_present() -> None:
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.planner.compiler import Compiler
    from vlm_photo_editor.schema.plan import HumanPlan

    settings = get_settings()
    original = settings.ps_mode
    try:
        settings.ps_mode = "strict"
        plan = HumanPlan(steps=[], mode="full")
        with patch("vlm_photo_editor.planner.compiler._ps_available", return_value=True):
            result = Compiler().compile(plan, "full")
        assert result.op_graph.ops == []
    finally:
        settings.ps_mode = original


def test_compiler_auto_mode_does_not_check_ps() -> None:
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.planner.compiler import Compiler
    from vlm_photo_editor.schema.plan import HumanPlan

    settings = get_settings()
    original = settings.ps_mode
    try:
        settings.ps_mode = "auto"
        plan = HumanPlan(steps=[], mode="full")
        # PS unavailable, but auto mode should not raise
        with patch("vlm_photo_editor.planner.compiler._ps_available", return_value=False):
            result = Compiler().compile(plan, "full")
        assert result.op_graph.ops == []
    finally:
        settings.ps_mode = original


# ── AppSettings.ps_mode ────────────────────────────────────────────────────────


def test_app_settings_ps_mode_default() -> None:
    assert AppSettings().ps_mode == "auto"


@pytest.mark.parametrize("mode", ["auto", "strict", "none"])
def test_app_settings_ps_mode_values(mode: str) -> None:
    s = AppSettings()
    s.ps_mode = mode
    assert s.ps_mode == mode
