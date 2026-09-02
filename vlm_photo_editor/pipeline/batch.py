"""Concurrent batch planning and execution for P11.

Uses anyio.create_task_group to plan N images concurrently, then routes each
image through accept-mode-aware execution. Rate-limit errors trigger exponential
backoff with jitter before retry.

Call anyio.run(run_batch, ...) directly from the UI — do NOT wrap in run_job(),
which itself calls anyio.run() and cannot be nested.
"""

from __future__ import annotations

import logging
import random
import re
from collections.abc import Callable
from typing import Any

import anyio

from vlm_photo_editor.agents.edit_flow import _can_auto_approve
from vlm_photo_editor.schema.batch import BatchImageRecord, ImageStatus
from vlm_photo_editor.schema.ops import AcceptMode

_log = logging.getLogger(__name__)

_BASE_DELAY = 1.0  # seconds
_MAX_DELAY = 60.0  # seconds

_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)


def _safe_error(exc: BaseException) -> str:
    """Exception type plus a URL-stripped, truncated message.

    Provider SDK exceptions routinely embed the request URL (and, for the
    ``google`` provider, the API key as a query parameter). This value is both
    logged through an unredacted logger (SR-P1) and rendered verbatim in the UI,
    so it must not carry raw provider text.
    """
    msg = _URL_RE.sub("<url>", str(exc)).strip()
    if len(msg) > 200:
        msg = msg[:200] + "…"
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def _is_rate_limit(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    return name == "RateLimitError" or "429" in msg or "rate limit" in msg or "overloaded" in msg


async def _plan_single(
    record: BatchImageRecord,
    planner: Any,
    compiler: Any,
    intent: str,
    prefs: Any | None,
    mode: str,
    framing_intent: Any | None,
    max_retries: int,
    on_image_progress: Callable[[str], None] | None,
    genai_available: bool = True,
) -> None:
    """Plan one image with exponential back-off on rate-limit errors.

    Mutates *record* in place: sets status, plan, op_graph, error, retry_count.
    """
    record.status = ImageStatus.PLANNING
    attempt = 0
    while True:
        try:
            plan = await anyio.to_thread.run_sync(
                lambda: planner.plan(
                    record.container,
                    intent,
                    prefs,
                    mode,
                    framing_intent,
                    detected_subject=record.detected_subject,
                    genai_available=genai_available,
                )
            )
            result = await anyio.to_thread.run_sync(
                lambda: compiler.compile(plan, mode, detected_subject=record.detected_subject)
            )
            record.plan = result.plan
            record.op_graph = result.op_graph
            record.status = ImageStatus.NEEDS_REVIEW
            break
        except Exception as exc:
            if _is_rate_limit(exc) and attempt < max_retries:
                delay = min(_MAX_DELAY, _BASE_DELAY * (2**attempt) + random.uniform(0, 1))
                _log.warning(
                    "rate_limit image=%s attempt=%d sleeping=%.1fs",
                    record.filename,
                    attempt,
                    delay,
                )
                await anyio.sleep(delay)
                attempt += 1
                record.retry_count = attempt
                continue
            record.status = ImageStatus.FAILED
            record.error = _safe_error(exc)
            _log.error("batch_plan_failed image=%s error=%s", record.filename, record.error)
            break

    if on_image_progress is not None:
        on_image_progress(record.image_id)


async def run_batch(
    records: list[BatchImageRecord],
    intent: str,
    prefs: Any | None,
    mode: str,
    framing_intent: Any | None,
    accept_mode: AcceptMode,
    max_retries: int = 3,
    on_image_progress: Callable[[str], None] | None = None,
) -> list[BatchImageRecord]:
    """Plan all images concurrently, then execute auto-approvable ones.

    Wall time < N × single-image time (DoD #1): all _plan_single coroutines
    run inside one anyio task group, each dispatching its blocking VLM call to
    a worker thread.

    Returns records with updated status fields.
    """
    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.background.providers import default_provider_available
    from vlm_photo_editor.planner.compiler import Compiler

    planner = Planner()  # _llm is immutable after init — safe to share across threads
    compiler = Compiler()  # stateless
    genai_available = default_provider_available()

    async with anyio.create_task_group() as tg:
        for record in records:
            tg.start_soon(
                _plan_single,
                record,
                planner,
                compiler,
                intent,
                prefs,
                mode,
                framing_intent,
                max_retries,
                on_image_progress,
                genai_available,
            )

    # Sequential execution for auto-approvable images (avoids N concurrent numpy arrays).
    for record in records:
        if record.status == ImageStatus.NEEDS_REVIEW and _can_auto_approve(
            record.op_graph, accept_mode
        ):
            _execute_record(record)

    return records


def _execute_record(record: BatchImageRecord) -> None:
    """Synchronous executor call — runs after the async planning phase."""
    from vlm_photo_editor.ops.executor import Executor

    try:
        result = Executor().apply(record.container, record.op_graph)
        record.edited_container = result.container
        record.genai_ops = result.genai_ops
        record.status = ImageStatus.AUTO_EXECUTED
    except Exception as exc:
        record.status = ImageStatus.FAILED
        record.error = _safe_error(exc)
        _log.error("batch_execute_failed image=%s error=%s", record.filename, record.error)
