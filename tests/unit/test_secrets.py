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
        ("abcde", "*bcde"),
    ],
)
def test_secret_store_mask(key: str, expected: str) -> None:
    assert SecretStore.mask(key) == expected


def test_model_registry_default_roles():
    reg = get_registry()
    assert reg.get("planner") == "claude-sonnet-4-6"
    assert reg.get("critic") == "claude-sonnet-4-6"
    assert reg.get("preference_aggregator") == "claude-haiku-4-5-20251001"


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
