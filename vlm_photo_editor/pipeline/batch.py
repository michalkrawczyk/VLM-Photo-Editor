"""Concurrent batch planning and execution for P11.

Uses anyio.create_task_group to plan N images concurrently, then routes each
image through accept-mode-aware execution. Rate-limit errors trigger exponential
backoff with jitter before retry.

Call anyio.run(run_batch, ...) directly from the UI — do NOT wrap in run_job(),
which itself calls anyio.run() and cannot be nested.

``adapt_plan_to_batch`` is the Mode-A ("apply the same edit to every image")
counterpart: one already-approved ``HumanPlan`` is the methodology; every other
image is planned for itself by ``Planner.adapt`` and executed when it stays inside
the approved risk envelope. Call it with ``anyio.run`` like ``run_batch``.

``apply_plan_to_batch`` recompiles one approved plan verbatim against each image
(no VLM call, plain-sync); Mode A uses the same compile+execute step for the
image the plan was approved on.
"""

from __future__ import annotations

import logging
import random
import re
from collections.abc import Callable
from typing import Any

import anyio

from vlm_photo_editor.agents.edit_flow import _can_auto_approve
from vlm_photo_editor.config.settings import get_settings
from vlm_photo_editor.planner.repair import compile_checked, compile_with_repair
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
    reference_plan: Any | None = None,
) -> None:
    """Plan one image with exponential back-off on rate-limit errors.

    With *reference_plan* (Mode A) the planner adapts that approved plan to this image
    instead of planning from the instruction alone.

    Mutates *record* in place: sets status, plan, op_graph, error, retry_count.
    """
    record.status = ImageStatus.PLANNING
    attempt = 0
    while True:
        try:
            if reference_plan is None:
                plan = await anyio.to_thread.run_sync(
                    lambda: planner.plan(
                        record.container,
                        record.intent or intent,  # per-image overrides the batch-wide fallback
                        prefs,
                        mode,
                        framing_intent,
                        detected_subject=record.detected_subject,
                        genai_available=genai_available,
                    )
                )
            else:
                plan = await anyio.to_thread.run_sync(
                    lambda: planner.adapt(
                        record.container,
                        reference_plan,
                        record.intent or intent,
                        prefs,
                        mode,
                        framing_intent,
                        detected_subject=record.detected_subject,
                        genai_available=genai_available,
                        image_report=_image_report(record),
                    )
                )
            result, repairs = await anyio.to_thread.run_sync(
                lambda: compile_with_repair(
                    plan,
                    lambda p: compile_checked(
                        p,
                        mode,
                        record.detected_subject,
                        record.container.width,
                        record.container.height,
                        compiler,
                    ),
                    lambda prev, error: planner.revise(
                        record.container,
                        prev,
                        error,
                        prefs,
                        mode,
                        framing_intent,
                        detected_subject=record.detected_subject,
                        genai_available=genai_available,
                        original_intent=record.intent or intent,
                    ),
                    get_settings().max_crop_retries,
                )
            )
            if repairs:
                _log.info("batch_plan_repaired image=%s repairs=%d", record.filename, len(repairs))
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


def _image_report(record: BatchImageRecord) -> Any | None:
    """Measurements for the planner, or None when disabled/unavailable (never fatal)."""
    if not get_settings().image_report_enabled:
        return None
    try:
        from vlm_photo_editor.analysis import compute_report

        return compute_report(record.container)
    except Exception:
        _log.warning("batch_image_report_failed image=%s", record.filename, exc_info=True)
        return None


def within_approved_envelope(op_graph: Any, reference_op_graph: Any) -> bool:
    """True when an adapted plan stays inside what the user approved.

    Adapted plans may change steps freely, but must not run anything riskier or costlier
    than the reference: no op above its highest risk tier, and no genAI/Photoshop backend
    unless the reference already used it.
    """
    from vlm_photo_editor.schema.ops import Backend, RiskTier

    order = list(RiskTier)
    ref_ops = reference_op_graph.ops if reference_op_graph else []
    ceiling = max((order.index(op.risk_tier) for op in ref_ops), default=0)
    ref_backends = {op.backend for op in ref_ops}
    for op in op_graph.ops:
        if order.index(op.risk_tier) > ceiling:
            return False
        if op.backend in (Backend.GENAI, Backend.PHOTOSHOP) and op.backend not in ref_backends:
            return False
    return True


def _compile_and_execute(
    record: BatchImageRecord,
    plan: Any,
    mode: str,
    compiler: Any,
    on_image_progress: Callable[[str], None] | None,
) -> None:
    """Compile *plan* against THIS image, validate crop bounds, execute.

    Any failure marks the record FAILED with a sanitised error. Progress fires once.
    """
    from vlm_photo_editor.ops.validator import validate_crop_bounds

    record.status = ImageStatus.PLANNING
    try:
        result = compiler.compile(plan, mode, detected_subject=record.detected_subject)
        record.plan = result.plan
        record.op_graph = result.op_graph  # per-image graph -> accurate Recipe sidecar
        validate_crop_bounds(result.op_graph, record.container.width, record.container.height)
    except Exception as exc:
        record.status = ImageStatus.FAILED
        record.error = _safe_error(exc)
        _log.error("batch_apply_compile_failed image=%s error=%s", record.filename, record.error)
    else:
        _execute_record(record)  # Executor().apply -> AUTO_EXECUTED | FAILED
    if on_image_progress is not None:
        on_image_progress(record.image_id)


def apply_plan_to_batch(
    records: list[BatchImageRecord],
    plan: Any,  # HumanPlan — Any to match module style
    mode: str,
    on_image_progress: Callable[[str], None] | None = None,
) -> list[BatchImageRecord]:
    """Recompile one approved HumanPlan against each image, then execute.

    Per record: compile the plan against THIS image's detected_subject, validate
    crop bounds against THIS image's dimensions, then execute. Any failure marks
    the record FAILED with a sanitised error and the loop continues. Progress
    fires once per record (image_id), matching run_batch's on_image_progress
    contract.

    Plain-sync: no VLM call, so no task group and no ``anyio.run`` wrapper.
    """
    from vlm_photo_editor.planner.compiler import Compiler

    compiler = Compiler()  # stateless
    for record in records:
        _compile_and_execute(record, plan, mode, compiler, on_image_progress)
    return records


async def adapt_plan_to_batch(
    records: list[BatchImageRecord],
    reference_plan: Any,
    reference_op_graph: Any,
    intent: str,
    prefs: Any | None,
    mode: str,
    framing_intent: Any | None,
    max_retries: int = 3,
    on_image_progress: Callable[[str], None] | None = None,
    plan_image_name: str | None = None,
) -> list[BatchImageRecord]:
    """Mode A: follow one approved plan, but plan each image for itself.

    The record named *plan_image_name* is the image the plan was approved on: it runs the
    approved plan verbatim. Every other image is planned concurrently by
    ``Planner.adapt`` (same methodology, parameters re-derived for that image) and then
    executed — unless its plan leaves the approved envelope (``within_approved_envelope``),
    in which case it waits in NEEDS_REVIEW for the user.
    """
    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.background.providers import default_provider_available
    from vlm_photo_editor.planner.compiler import Compiler

    compiler = Compiler()  # stateless
    plan_image = [r for r in records if r.filename == plan_image_name]
    others = [r for r in records if r not in plan_image]

    for record in plan_image:
        _compile_and_execute(record, reference_plan, mode, compiler, on_image_progress)

    if others:
        planner = Planner()  # _llm is immutable after init — safe to share across threads
        genai_available = default_provider_available()
        async with anyio.create_task_group() as tg:
            for record in others:
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
                    reference_plan,
                )

    # Sequential execution (avoids N concurrent numpy arrays).
    for record in others:
        if record.status == ImageStatus.NEEDS_REVIEW and within_approved_envelope(
            record.op_graph, reference_op_graph
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
