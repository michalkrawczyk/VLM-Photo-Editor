"""P10 Hardening — unit tests covering all DoD items."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

# ── A. build_client — vLLM loader ─────────────────────────────────────────────


def _vllm_entry(model_id: str = "my-model", base_url: str = "http://gpu:8000/v1"):
    from vlm_photo_editor.config.registry import ModelEntry

    return ModelEntry(model_id=model_id, provider="local", loader="vllm", vllm_base_url=base_url)


def test_build_client_vllm_returns_chatopenai_with_correct_args():
    from vlm_photo_editor.models.registry import build_client

    entry = _vllm_entry("my-vllm-model", "http://gpu-server:8000/v1")
    mock_cls = MagicMock()
    mock_openai_mod = MagicMock()
    mock_openai_mod.ChatOpenAI = mock_cls

    with (
        patch("vlm_photo_editor.config.registry.ModelRegistry.get_entry", return_value=entry),
        patch.dict(sys.modules, {"langchain_openai": mock_openai_mod}),
    ):
        build_client("planner")

    mock_cls.assert_called_once_with(
        base_url="http://gpu-server:8000/v1",
        model="my-vllm-model",
        api_key="not-needed",
    )


# ── B. build_client — llamacpp loader ─────────────────────────────────────────


def _llamacpp_entry(gguf_path: str | None = "/models/lfm.gguf"):
    from vlm_photo_editor.config.registry import ModelEntry

    return ModelEntry(
        model_id="lfm-1.2b",
        provider="local",
        loader="llamacpp",
        gguf_path=gguf_path,
    )


def test_build_client_llamacpp_with_gguf_path():
    from vlm_photo_editor.models.registry import build_client

    entry = _llamacpp_entry("/models/lfm.gguf")
    mock_cls = MagicMock()
    mock_chat_models_mod = MagicMock()
    mock_chat_models_mod.ChatLlamaCpp = mock_cls

    with (
        patch("vlm_photo_editor.config.registry.ModelRegistry.get_entry", return_value=entry),
        patch.dict(
            sys.modules,
            {
                "langchain_community": MagicMock(),
                "langchain_community.chat_models": mock_chat_models_mod,
            },
        ),
    ):
        build_client("cost_router")

    mock_cls.assert_called_once_with(model_path="/models/lfm.gguf")


def test_build_client_llamacpp_without_gguf_path_raises():
    entry = _llamacpp_entry(gguf_path=None)
    with patch("vlm_photo_editor.config.registry.ModelRegistry.get_entry", return_value=entry):
        from vlm_photo_editor.models.registry import build_client

        with pytest.raises(ValueError, match="gguf_path"):
            build_client("cost_router")


# ── C. available_loaders ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "specs_present, vllm_reachable, expected",
    [
        # all installed + vLLM reachable
        (
            {
                "langchain_ollama",
                "langchain_huggingface",
                "langchain_community",
                "llama_cpp",
                "langchain_openai",
            },
            True,
            ["ollama", "transformers", "llamacpp", "vllm"],
        ),
        # nothing installed
        (set(), False, []),
        # only ollama + transformers; vLLM package present but server unreachable
        (
            {"langchain_ollama", "langchain_huggingface", "langchain_openai"},
            False,
            ["ollama", "transformers"],
        ),
        # llamacpp requires BOTH langchain_community AND llama_cpp
        ({"langchain_community"}, False, []),
    ],
)
def test_available_loaders(specs_present, vllm_reachable, expected):
    from vlm_photo_editor.models.registry import available_loaders

    def fake_find_spec(name):
        return MagicMock() if name in specs_present else None

    with (
        patch("importlib.util.find_spec", side_effect=fake_find_spec),
        patch("vlm_photo_editor.models.registry._vllm_reachable", return_value=vllm_reachable),
    ):
        assert available_loaders() == expected


# ── D. install_loader_deps ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "loader, expected_req_file",
    [
        ("llamacpp", "requirements-llamacpp.txt"),
        ("ollama", "requirements-ollama.txt"),
        ("transformers", "requirements-huggingface.txt"),
        ("vllm", "requirements-openai.txt"),
    ],
)
def test_install_loader_deps_calls_pip_with_correct_file(loader, expected_req_file):
    from vlm_photo_editor.models.registry import install_loader_deps

    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        ok = install_loader_deps(loader)

    assert ok is True
    mock_run.assert_called_once_with(
        [sys.executable, "-m", "pip", "install", "-r", expected_req_file],
        capture_output=True,
    )


def test_install_loader_deps_unknown_raises():
    from vlm_photo_editor.models.registry import install_loader_deps

    with pytest.raises(ValueError, match="Unknown loader"):
        install_loader_deps("unknown_loader_xyz")


# ── E. Plan cache ─────────────────────────────────────────────────────────────


def _fake_container(seed: int = 0):
    container = MagicMock()
    rng = np.random.default_rng(seed)
    container.pixels = rng.integers(0, 256, (10, 10, 3), dtype=np.uint8)
    return container


def _fake_prefs(version: int = 1):
    prefs = MagicMock()
    prefs.version = version
    return prefs


def _fake_plan():
    return MagicMock()


def test_plan_cache_miss_then_hit():
    from vlm_photo_editor.pipeline.plan_cache import PlanCache

    cache = PlanCache(ttl=3600)
    container = _fake_container()
    prefs = _fake_prefs()
    key = cache.key(container, "full", prefs)

    assert cache.get(key) is None  # miss

    plan = _fake_plan()
    cache.set(key, plan)
    assert cache.get(key) is plan  # hit


def test_plan_cache_ttl_expiry():
    from vlm_photo_editor.pipeline.plan_cache import PlanCache

    cache = PlanCache(ttl=1)
    container = _fake_container(seed=42)
    key = cache.key(container, "background", None)

    plan = _fake_plan()
    cache.set(key, plan)

    # Advance time past TTL
    with patch("time.monotonic", return_value=time.monotonic() + 10):
        assert cache.get(key) is None


def test_plan_cache_key_differs_by_mode_prefs_intent_and_framing():
    from vlm_photo_editor.pipeline.plan_cache import PlanCache

    cache = PlanCache()
    container = _fake_container()
    keys = {
        cache.key(container, "full", _fake_prefs(1)),
        cache.key(container, "frame", _fake_prefs(1)),
        cache.key(container, "full", _fake_prefs(2)),
        cache.key(container, "full", None),
        cache.key(container, "full", _fake_prefs(1), "brighten"),
        cache.key(container, "full", _fake_prefs(1), "crop tighter"),
        cache.key(container, "frame", _fake_prefs(1), "", "rule_of_thirds"),
        cache.key(container, "frame", _fake_prefs(1), "", "portrait_headroom"),
    }

    assert len(keys) == 8
    # Same inputs → same key, so a genuine repeat still hits the cache.
    assert cache.key(container, "frame", _fake_prefs(1), "x", "face_only") == cache.key(
        container, "frame", _fake_prefs(1), "x", "face_only"
    )


# ── F. Async job queue ────────────────────────────────────────────────────────


def test_run_job_returns_result():
    from vlm_photo_editor.pipeline.job_queue import run_job

    result = run_job(lambda x, y: x + y, 3, 4)
    assert result == 7


def test_run_job_calls_on_progress_with_1():
    from vlm_photo_editor.pipeline.job_queue import run_job

    progress_values: list[float] = []
    run_job(lambda: None, on_progress=progress_values.append)
    assert progress_values == [1.0]


def test_run_job_no_progress_callback():
    from vlm_photo_editor.pipeline.job_queue import run_job

    # Must not raise when on_progress is None (default)
    assert run_job(lambda: "ok") == "ok"


# ── G. Redaction audit ────────────────────────────────────────────────────────
# Use a handler-level StringIO capture so the RedactionFilter runs before
# the output is collected. pytest.caplog captures records at the root logger
# before root-level filters apply, making it unsuitable for this audit.

_FAKE_KEY = "sk-fakekeyabcdefghijklmnopqrstuvwxyz1234"
_FAKE_R8 = "r8_fakekeyreplicate1234567890abcdef"


def _capture_with_filter(messages: list[tuple[str, str]]) -> str:
    """Log *messages* through a handler that has RedactionFilter attached; return output."""
    import io

    from vlm_photo_editor.secrets.redaction import RedactionFilter

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.addFilter(RedactionFilter())
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test.audit.redact")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        for level, msg in messages:
            getattr(logger, level)(msg)
    finally:
        logger.removeHandler(handler)

    return buf.getvalue()


@pytest.mark.parametrize("key", [_FAKE_KEY, _FAKE_R8])
def test_redaction_filter_scrubs_key_from_log_output(key):
    output = _capture_with_filter(
        [
            ("warning", f"API call with key={key} result=ok"),
            ("error", f"Exception: auth failed for {key}"),
        ]
    )
    assert key not in output, f"Key leaked in log output: {output!r}"
    assert "[REDACTED]" in output


def test_redaction_applies_to_exception_message():
    try:
        raise RuntimeError(f"Auth error with key {_FAKE_KEY}")
    except RuntimeError as exc:
        output = _capture_with_filter([("error", f"Caught: {exc}")])

    assert _FAKE_KEY not in output, f"Key leaked: {output!r}"
    assert "[REDACTED]" in output
