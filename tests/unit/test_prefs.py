"""Unit tests for P8: preferences learning loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vlm_photo_editor.config.registry import AGGREGATOR_PRESETS, ModelEntry, ModelRegistry
from vlm_photo_editor.preferences.store import AGGREGATE_AFTER, DeltaStore, PreferenceStore
from vlm_photo_editor.schema.prefs import (
    EditDelta,
    ExplicitRule,
    LearnedRule,
    Preferences,
)
from vlm_photo_editor.templates.planner import _prefs_lines

# ── DeltaStore ────────────────────────────────────────────────────────────────


def test_delta_store_append_and_list(tmp_path: Path) -> None:
    path = tmp_path / "deltas.jsonl"
    ds = DeltaStore(path)
    assert ds.list() == []

    d = EditDelta(
        intent="improve portrait", mode="full", change_requests=[], accepted_ops=["exposure"]
    )
    ds.append(d)

    # Re-open to verify persistence
    ds2 = DeltaStore(path)
    deltas = ds2.list()
    assert len(deltas) == 1
    assert deltas[0].delta_id == d.delta_id
    assert deltas[0].accepted_ops == ["exposure"]


def test_delta_store_append_multiple(tmp_path: Path) -> None:
    ds = DeltaStore(tmp_path / "deltas.jsonl")
    for i in range(3):
        ds.append(EditDelta(intent=f"intent {i}", mode="full"))
    assert len(ds.list()) == 3


def test_delta_store_clear(tmp_path: Path) -> None:
    ds = DeltaStore(tmp_path / "deltas.jsonl")
    ds.append(EditDelta(intent="x", mode="full"))
    ds.clear()
    assert ds.list() == []


def test_delta_store_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "deltas.jsonl"
    ds = DeltaStore(path)
    ds.append(EditDelta(intent="x", mode="full"))
    assert path.exists()


# ── PreferenceStore ───────────────────────────────────────────────────────────


def test_preference_store_empty_load(tmp_path: Path) -> None:
    ps = PreferenceStore(tmp_path / "prefs.json")
    prefs = ps.load()
    assert prefs.explicit == []
    assert prefs.learned == []


def test_preference_store_save_atomic_on_write_failure(tmp_path: Path, monkeypatch) -> None:
    """A crash mid-write must not corrupt a previously-saved prefs file."""
    path = tmp_path / "prefs.json"
    ps = PreferenceStore(path)
    ps.add_explicit("Prefer warm tones")
    original_bytes = path.read_bytes()

    def _crash_partway(self, data, *args, **kwargs):
        with open(self, "w", encoding="utf-8") as f:
            f.write(data[: len(data) // 2])
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(Path, "write_text", _crash_partway)
    with pytest.raises(OSError):
        ps.add_explicit("Prefer cool tones")

    assert path.read_bytes() == original_bytes
    assert not list(tmp_path.glob("*.tmp"))


def test_preference_store_add_and_load(tmp_path: Path) -> None:
    ps = PreferenceStore(tmp_path / "prefs.json")
    rule = ps.add_explicit("Prefer warm tones")
    prefs = PreferenceStore(tmp_path / "prefs.json").load()
    assert len(prefs.explicit) == 1
    assert prefs.explicit[0].rule_id == rule.rule_id
    assert prefs.explicit[0].description == "Prefer warm tones"
    assert prefs.explicit[0].active is True


def test_preference_store_remove_explicit(tmp_path: Path) -> None:
    ps = PreferenceStore(tmp_path / "prefs.json")
    r1 = ps.add_explicit("rule one")
    ps.add_explicit("rule two")
    ps.remove_explicit(r1.rule_id)
    prefs = ps.load()
    assert len(prefs.explicit) == 1
    assert prefs.explicit[0].description == "rule two"


def test_toggle_disables_explicit_rule(tmp_path: Path) -> None:
    ps = PreferenceStore(tmp_path / "prefs.json")
    rule = ps.add_explicit("keep headroom")
    assert ps.load().explicit[0].active is True
    ps.toggle_rule(rule.rule_id)
    assert ps.load().explicit[0].active is False
    ps.toggle_rule(rule.rule_id)
    assert ps.load().explicit[0].active is True


def test_toggle_disables_learned_rule(tmp_path: Path) -> None:
    ps = PreferenceStore(tmp_path / "prefs.json")
    candidate = LearnedRule(
        description="increase exposure", confidence=0.8, approved=True, active=True
    )
    ps.add_learned([candidate])
    ps.approve_learned(candidate.rule_id)
    ps.toggle_rule(candidate.rule_id)
    assert ps.load().learned[0].active is False


def test_approve_learned_rule(tmp_path: Path) -> None:
    ps = PreferenceStore(tmp_path / "prefs.json")
    candidate = LearnedRule(description="warmer tones", confidence=0.75)
    ps.add_learned([candidate])
    prefs = ps.load()
    assert prefs.learned[0].approved is False

    ps.approve_learned(candidate.rule_id)
    prefs = ps.load()
    assert prefs.learned[0].approved is True
    assert prefs.learned[0].active is True


def test_add_learned_no_duplicates(tmp_path: Path) -> None:
    ps = PreferenceStore(tmp_path / "prefs.json")
    candidate = LearnedRule(description="test rule", confidence=0.6)
    ps.add_learned([candidate])
    ps.add_learned([candidate])  # same rule_id
    assert len(ps.load().learned) == 1


# ── Explicit beats learned in planner prompt ──────────────────────────────────


def test_explicit_beats_learned_in_prompt() -> None:
    prefs = Preferences(
        explicit=[ExplicitRule(description="keep colors neutral", active=True)],
        learned=[
            LearnedRule(description="apply warm filter", active=True, approved=True, confidence=0.9)
        ],
    )
    lines = _prefs_lines(prefs, framing_intent=None)
    prompt_text = "\n".join(lines)
    explicit_pos = prompt_text.index("USER PREFERENCES")
    learned_pos = prompt_text.index("LEARNED PREFERENCES")
    assert explicit_pos < learned_pos, "Explicit must appear before learned (higher priority)"


def test_inactive_rule_excluded_from_prompt() -> None:
    prefs = Preferences(
        explicit=[ExplicitRule(description="inactive rule", active=False)],
        learned=[LearnedRule(description="unapproved rule", active=True, approved=False)],
    )
    lines = _prefs_lines(prefs, framing_intent=None)
    assert lines == [], "Inactive or unapproved rules must not appear in prompt"


def test_approved_rule_appears_in_prompt() -> None:
    prefs = Preferences(
        learned=[
            LearnedRule(description="warmer tones", active=True, approved=True, confidence=0.8)
        ]
    )
    lines = _prefs_lines(prefs, framing_intent=None)
    prompt_text = "\n".join(lines)
    assert "warmer tones" in prompt_text
    assert "LEARNED PREFERENCES" in prompt_text


# ── Aggregator ────────────────────────────────────────────────────────────────


def test_aggregator_produces_candidates() -> None:
    from vlm_photo_editor.agents.aggregator import Aggregator

    mock_response = MagicMock()
    mock_response.content = '{"rules": [{"description": "prefer warmer tones", "confidence": 0.8}]}'

    with patch("vlm_photo_editor.agents.aggregator.build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.invoke.return_value = mock_response
        mock_build.return_value = mock_client

        deltas = [
            EditDelta(
                intent="improve portrait",
                mode="full",
                change_requests=["warmer"],
                accepted_ops=["color_grade"],
            ),
            EditDelta(
                intent="fix landscape",
                mode="full",
                change_requests=["warmer sky"],
                accepted_ops=["color_grade"],
            ),
        ]
        rules = Aggregator().aggregate(deltas)

    assert len(rules) == 1
    assert rules[0].description == "prefer warmer tones"
    assert rules[0].confidence == pytest.approx(0.8)
    assert rules[0].approved is False
    assert rules[0].active is False


def test_aggregator_fail_open_on_bad_json() -> None:
    from vlm_photo_editor.agents.aggregator import Aggregator

    mock_response = MagicMock()
    mock_response.content = "Sorry, I cannot help with that."

    with patch("vlm_photo_editor.agents.aggregator.build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.invoke.return_value = mock_response
        mock_build.return_value = mock_client

        rules = Aggregator().aggregate([EditDelta(intent="x", mode="full")])

    assert rules == []


def test_aggregator_fail_open_on_exception() -> None:
    from vlm_photo_editor.agents.aggregator import Aggregator

    with patch("vlm_photo_editor.agents.aggregator.build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.invoke.side_effect = RuntimeError("network error")
        mock_build.return_value = mock_client

        rules = Aggregator().aggregate([EditDelta(intent="x", mode="full")])

    assert rules == []


def test_aggregator_empty_deltas() -> None:
    from vlm_photo_editor.agents.aggregator import Aggregator

    with patch("vlm_photo_editor.agents.aggregator.build_client") as mock_build:
        rules = Aggregator().aggregate([])
        mock_build.assert_not_called()

    assert rules == []


# ── Aggregate threshold ───────────────────────────────────────────────────────


def test_aggregate_threshold_constant() -> None:
    assert AGGREGATE_AFTER == 5


# ── ModelRegistry.set_entry() ─────────────────────────────────────────────────


def test_set_entry_replaces_full_model_entry() -> None:
    registry = ModelRegistry()
    new_entry = ModelEntry("claude-haiku-4-5-20251001", provider="anthropic")
    registry.set_entry("preference_aggregator", new_entry)
    entry = registry.get_entry("preference_aggregator")
    assert entry.model_id == "claude-haiku-4-5-20251001"
    assert entry.provider == "anthropic"
    assert entry.loader is None


def test_aggregator_presets_cover_all_three_options() -> None:
    names = set(AGGREGATOR_PRESETS.keys())
    assert any("LFM" in n or "local" in n.lower() for n in names), "Missing local LFM preset"
    assert any("haiku" in n.lower() for n in names), "Missing haiku preset"
    assert any("gpt" in n.lower() for n in names), "Missing gpt preset"


@pytest.mark.parametrize(
    "preset_name,expected_provider",
    [
        ("LFM2.5-1.2B (local)", "local"),
        ("claude-haiku-4.5", "anthropic"),
        ("gpt-4.1-mini", "openai"),
    ],
)
def test_aggregator_preset_providers(preset_name: str, expected_provider: str) -> None:
    entry = AGGREGATOR_PRESETS[preset_name]
    assert entry.provider == expected_provider
