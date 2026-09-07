import logging
from unittest.mock import patch

import pytest

from vlm_photo_editor.config.registry import ModelRegistry, get_registry
from vlm_photo_editor.secrets.redaction import RedactionFilter, install_redaction_filter
from vlm_photo_editor.secrets.store import SecretStore


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, "", 0, msg, (), None)


def test_redaction_filter_scrubs_key():
    record = _make_record("key is sk-abcdefghijklmnopqrstuvwxyz1234")
    RedactionFilter().filter(record)
    assert "sk-" not in record.msg
    assert "[REDACTED]" in record.msg


def test_redaction_filter_clears_args():
    record = _make_record("plain message")
    record.args = ("arg1", "arg2")
    RedactionFilter().filter(record)
    assert record.args == ()


def test_redaction_filter_passthrough_safe():
    record = _make_record("no key here, just a normal log")
    result = RedactionFilter().filter(record)
    assert result is True
    assert record.msg == "no key here, just a normal log"


def test_redaction_filter_short_sk_not_redacted():
    record = _make_record("sk-short")
    RedactionFilter().filter(record)
    assert "[REDACTED]" not in record.msg


def test_install_redaction_filter_attaches_to_root():
    root_logger = logging.getLogger()
    before = len(root_logger.filters)
    install_redaction_filter()
    assert len(root_logger.filters) >= before + 1
    # Restore: remove the filter we just added
    for f in list(root_logger.filters):
        if isinstance(f, RedactionFilter):
            root_logger.removeFilter(f)
            break


def test_secret_store_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-testkey1234567890abcdef")
    key = SecretStore.get("anthropic")
    assert key == "sk-testkey1234567890abcdef"


def test_secret_store_replicate_reads_token_env(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_testtoken1234567890abcdef")
    monkeypatch.delenv("REPLICATE_API_KEY", raising=False)
    key = SecretStore.get("replicate")
    assert key == "r8_testtoken1234567890abcdef"


def test_secret_store_has_returns_true_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-present1234567890abcdef")
    assert SecretStore.has("anthropic") is True


def test_secret_store_has_returns_false_when_key_absent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with (
        patch("keyring.get_password", return_value=None),
        patch("dotenv.find_dotenv", return_value=""),
    ):
        assert SecretStore.has("anthropic") is False


def test_secret_store_env_takes_priority_over_keyring(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-value-1234567890abcd")
    with patch("keyring.get_password", return_value="sk-keyring-value-should-not-win"):
        key = SecretStore.get("anthropic")
    assert key == "sk-env-value-1234567890abcd"


def test_secret_store_missing_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with (
        patch("keyring.get_password", return_value=None),
        patch("dotenv.find_dotenv", return_value=""),
    ):
        with pytest.raises(KeyError, match="anthropic"):
            SecretStore.get("anthropic")


def test_secret_store_from_keyring(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with (
        patch("keyring.get_password", return_value="sk-keyring-value12345678abcdef"),
        patch("dotenv.find_dotenv", return_value=""),
    ):
        key = SecretStore.get("anthropic")
    assert key == "sk-keyring-value12345678abcdef"


@pytest.mark.parametrize(
    "key,expected",
    [
        ("sk-abc1234", "******1234"),
        ("ab", "****"),
        ("abcd", "****"),
        ("abcde", "****"),
        ("abcdefghi", "*****fghi"),
    ],
)
def test_secret_store_mask(key: str, expected: str) -> None:
    assert SecretStore.mask(key) == expected


def test_model_registry_default_roles():
    reg = get_registry()
    assert reg.get("planner") == "claude-sonnet-4-6"
    assert reg.get("critic") == "claude-sonnet-4-6"
    assert reg.get("preference_aggregator") == "LiquidAI/LFM2.5-1.2B-Instruct"


def test_model_registry_set_takes_effect():
    reg = ModelRegistry()
    reg.set("planner", "gpt-4o")
    assert reg.get("planner") == "gpt-4o"
    assert reg.get("critic") == "claude-sonnet-4-6"


def test_model_registry_unknown_role_raises():
    reg = ModelRegistry()
    with pytest.raises(KeyError, match="unknown_role"):
        reg.get("unknown_role")


def test_model_registry_all_roles():
    reg = ModelRegistry()
    roles = reg.all_roles()
    assert "planner" in roles
    assert "critic" in roles


def test_planner_presets_cover_local_and_cloud() -> None:
    from vlm_photo_editor.config.registry import PLANNER_PRESETS

    assert any(not e.is_local for e in PLANNER_PRESETS.values()), "need a cloud planner preset"
    assert any("gpt" in n.lower() for n in PLANNER_PRESETS), "need a gpt planner preset"
    # Default entry must be selectable from the preset switcher.
    assert PLANNER_PRESETS["claude-sonnet-4.6"].model_id == get_registry().get("planner")


@pytest.mark.parametrize(
    "preset_name,provider,reasoning_effort,use_responses_api",
    [
        ("claude-sonnet-4.6", "anthropic", None, False),
        ("gpt-4o", "openai", None, False),
        ("gpt-5.6-luna", "openai", None, True),
        ("gpt-5.6-luna (no reasoning)", "openai", "none", False),
        ("gpt-5.6-terra", "openai", None, True),
        ("gpt-5.6-terra (no reasoning)", "openai", "none", False),
    ],
)
def test_planner_preset_entries(
    preset_name: str, provider: str, reasoning_effort: str | None, use_responses_api: bool
) -> None:
    from vlm_photo_editor.config.registry import PLANNER_PRESETS

    entry = PLANNER_PRESETS[preset_name]
    assert entry.provider == provider
    assert entry.reasoning_effort == reasoning_effort
    assert entry.use_responses_api is use_responses_api


def test_redaction_filter_formats_percent_args():
    """SEC-B2: key in args must be redacted after getMessage() formats the string."""
    key = "sk-ant-abc123abcdefghij"
    record = logging.LogRecord("test", logging.INFO, "", 0, "api key=%s", (key,), None)
    RedactionFilter().filter(record)
    assert "[REDACTED]" in record.msg
    assert "sk-ant-" not in record.msg
    assert record.args == ()


def test_model_registry_set_preserves_extra_fields():
    """SEC-B5: set() must not drop vllm_base_url, gguf_path, max_images_per_call."""
    from vlm_photo_editor.config.registry import ModelEntry

    reg = ModelRegistry()
    entry = ModelEntry(
        model_id="old-model",
        provider="local",
        loader="vllm",
        vllm_base_url="http://my-server:9000/v1",
        max_images_per_call=4,
    )
    reg.set_entry("planner", entry)
    reg.set("planner", "new-model")
    updated = reg.get_entry("planner")
    assert updated.model_id == "new-model"
    assert updated.vllm_base_url == "http://my-server:9000/v1"
    assert updated.max_images_per_call == 4
    assert updated.loader == "vllm"
