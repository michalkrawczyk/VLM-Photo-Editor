"""Runs an ``EvalCase`` end to end and scores it with ``ImageReport`` deltas.

Two entry points share the same scoring:
- ``run_oracle``: the case's own deterministic ops, no VLM. Validates ops + measurements.
- ``run_case``: a caller-supplied planner (``planner_fn``) goes plan -> compile -> execute.
  Used by the VLM tier to compare prompt/model versions (e.g. with vs without the report).

Results stay local and key-free: ``write_results`` only ever sees ``CaseResult`` fields.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from vlm_photo_editor.analysis import compute_report
from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.ops.executor import Executor
from vlm_photo_editor.planner.compiler import CompilerError
from vlm_photo_editor.planner.repair import compile_checked, compile_with_repair
from vlm_photo_editor.schema.ops import OpGraph
from vlm_photo_editor.schema.plan import HumanPlan
from vlm_photo_editor.templates.planner import build_system_prompt

from .cases import EvalCase

PlannerFn = Callable[[ImageContainer, str], HumanPlan]
ReviseFn = Callable[[ImageContainer, HumanPlan, str], HumanPlan]


@dataclass
class CaseResult:
    case: str
    passed: bool
    n_steps: int = 0
    repairs: int = 0
    latency_s: float = 0.0
    error: str | None = None
    before_p50: float | None = None
    after_p50: float | None = None
    before_cast: float | None = None
    after_cast: float | None = None
    before_clip_pct: float | None = None
    after_clip_pct: float | None = None
    before_noise: float | None = None
    after_noise: float | None = None
    before_tilt: float | None = None
    after_tilt: float | None = None
    ops: list[str] | None = None  # the executed plan, e.g. 'exposure {"ev": 1.0}'


def _score(case: EvalCase, before_c: ImageContainer, graph: OpGraph) -> CaseResult:
    before = compute_report(before_c)
    after_c = Executor().apply(before_c, graph).container
    after = compute_report(after_c)
    ok = (
        case.passes(before, after)
        and after_c.pixels.dtype == before_c.pixels.dtype
        and after_c.bit_depth == before_c.bit_depth
    )
    return CaseResult(
        case=case.name,
        passed=ok,
        n_steps=len(graph.ops),
        ops=[f"{op.op_name.value} {json.dumps(op.params, sort_keys=True)}" for op in graph.ops],
        before_p50=before.luma_p50,
        after_p50=after.luma_p50,
        before_cast=before.cast_rb_ratio,
        after_cast=after.cast_rb_ratio,
        before_clip_pct=before.clipped_highlight_pct,
        after_clip_pct=after.clipped_highlight_pct,
        before_noise=before.noise_sigma,
        after_noise=after.noise_sigma,
        before_tilt=before.tilt_deg,
        after_tilt=after.tilt_deg,
    )


def run_oracle(case: EvalCase) -> CaseResult:
    container = case.make_image()
    graph = OpGraph(ops=case.oracle(compute_report(container)))
    return _score(case, container, graph)


def run_case(
    case: EvalCase,
    planner_fn: PlannerFn,
    revise_fn: ReviseFn | None = None,
    max_repairs: int = 0,
) -> CaseResult:
    """Plan -> compile (with bounded repair when ``revise_fn`` is given) -> execute -> score."""
    container = case.make_image()
    start = time.perf_counter()
    repairs = 0
    try:
        plan = planner_fn(container, case.intent)
        compiled, notes = compile_with_repair(
            plan,
            lambda p: _compile_and_dry_run(p, container),
            lambda prev, error: (revise_fn or _no_revise)(container, prev, error),
            max_repairs if revise_fn else 0,
        )
        repairs = len(notes)
        result = _score(case, container, compiled.op_graph)
    except (CompilerError, ValueError) as exc:  # a rejected plan is a failed case, not a crash
        return CaseResult(
            case=case.name,
            passed=False,
            repairs=len(getattr(exc, "notes", [])),
            error=f"{type(exc).__name__}: {exc}",
        )
    result.repairs = repairs
    result.latency_s = round(time.perf_counter() - start, 3)
    return result


def _compile_and_dry_run(plan: HumanPlan, container: ImageContainer):
    """Compile, then execute once so execute-time rejections share the repair budget.

    The app resolves a masked op's missing subject by asking the user to draw a region; the eval
    has neither a detector nor a user, so such a plan is unexecutable here. Reporting it as a
    repairable error (the executor's own message) mirrors telling the planner no subject exists.
    """
    compiled = compile_checked(plan, "full", None, container.width, container.height)
    Executor().apply(container, compiled.op_graph)
    return compiled


def _no_revise(container: ImageContainer, plan: HumanPlan, error: str) -> HumanPlan:
    raise AssertionError("revise_fn is required when max_repairs > 0")


def prompt_fingerprint() -> str:
    """Short hash of the static planner prompt, so a result file says which prompt produced it."""
    prompt = build_system_prompt("full", None, None, None)
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def write_results(results: list[CaseResult], path: Path, *, label: str) -> None:
    payload = {
        "label": label,
        "prompt_sha": prompt_fingerprint(),
        "pass_rate": sum(r.passed for r in results) / max(1, len(results)),
        "results": [asdict(r) for r in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
