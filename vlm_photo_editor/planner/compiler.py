from __future__ import annotations

import socket
import time

from vlm_photo_editor.background.providers import DEFAULT_GENAI_MODEL as _DEFAULT_GENAI_MODEL
from vlm_photo_editor.background.providers import (
    available_genai_providers,
    provider_env_hint,
    provider_name_for,
)
from vlm_photo_editor.config.policy import EditMode, allowed_ops_for_mode
from vlm_photo_editor.ops.validator import validate_op_graph
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.op_catalog import BBoxClass, all_specs, get_spec
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName
from vlm_photo_editor.schema.plan import CompilerResult, HumanPlan

_PS_MCP_HOST = "127.0.0.1"
_PS_MCP_PORT = 8080
_PS_CACHE_TTL = 5.0
_ps_cache: tuple[float, bool] | None = None


def _ps_available() -> bool:
    global _ps_cache
    now = time.monotonic()
    if _ps_cache is not None and now - _ps_cache[0] < _PS_CACHE_TTL:
        return _ps_cache[1]
    try:
        with socket.create_connection((_PS_MCP_HOST, _PS_MCP_PORT), timeout=0.2):
            result = True
    except OSError:
        result = False
    _ps_cache = (now, result)
    return result


_INPAINT_OPS = frozenset(
    n for n, s in all_specs().items() if s.bbox_class is BBoxClass.SELF_MANAGED_INPAINT
)

# Ops that change image dimensions; mask's selection can't carry across them.
_SIZE_CHANGING_OPS = frozenset(
    n for n, s in all_specs().items() if s.bbox_class is BBoxClass.SIZE_CHANGING
)


class CompilerError(ValueError):
    """HumanPlan could not be compiled to a valid OpGraph.

    ``repairable`` is False when the failure is environmental (PS missing, GenAI key
    absent, unknown mode): asking the planner for a revised plan cannot fix it.
    """

    def __init__(self, *args: object, repairable: bool = True) -> None:
        super().__init__(*args)
        self.repairable = repairable


def _is_valid_mask_target(op: Op) -> bool:
    """True if `op` can follow a `mask` selection step (i.e. can apply outside it)."""
    spec = get_spec(op.op_name)
    if spec.bbox_class is BBoxClass.SIZE_CHANGING:
        return False
    if spec.bbox_class is BBoxClass.SELF_MANAGED_INPAINT:
        return op.op_name == OpName.REGION_EDIT and op.params.get("method") == "blur"
    return True


def _collapse_mask_ops(ops: list[Op], detected_subject: DetectedSubject | None) -> list[Op]:
    """Fold each `mask` op into the op immediately following it: `mask` protects the
    subject, so the next op is confined to the region OUTSIDE it (invert=True). If
    Character Focus detected a subject, its bbox is used immediately. Otherwise the op
    is left with bbox=None — the app layer resolves it from a manually-drawn Region
    Selection at execute time (still applied as protect-that-box/edit-outside-it), or
    blocks execution with a clear message if none is drawn. `mask` itself never
    survives into the compiled OpGraph."""
    if not any(op.op_name == OpName.MASK for op in ops):
        return ops

    result: list[Op] = []
    i = 0
    while i < len(ops):
        op = ops[i]
        if op.op_name != OpName.MASK:
            result.append(op)
            i += 1
            continue
        if i + 1 >= len(ops):
            raise CompilerError(
                f"Step {op.step_id!r}: 'mask' must be immediately followed by another op "
                "to apply the protected-subject selection to."
            )
        nxt = ops[i + 1]
        if not _is_valid_mask_target(nxt):
            raise CompilerError(
                f"Step {nxt.step_id!r}: 'mask' cannot precede {nxt.op_name.value!r}; that "
                "op manages its own region selection."
            )
        bbox = detected_subject.bbox if detected_subject is not None else None
        result.append(
            nxt.model_copy(
                update={
                    "bbox": bbox,
                    "params": {**nxt.params, "invert": True},
                }
            )
        )
        i += 2
    return result


class Compiler:
    def compile(
        self,
        plan: HumanPlan,
        mode: EditMode | str,
        detected_subject: DetectedSubject | None = None,
    ) -> CompilerResult:
        from vlm_photo_editor.config.settings import get_settings

        settings = get_settings()
        try:
            allowed = allowed_ops_for_mode(mode)
        except KeyError as exc:
            raise CompilerError(str(exc), repairable=False) from exc
        no_genai = settings.no_genai

        if settings.ps_mode == "strict" and not _ps_available():
            raise CompilerError(
                "PS-strict mode requires Photoshop. "
                "Connect the PS plugin or switch to 'auto' mode.",
                repairable=False,
            )
        # ps_mode == "none" will block Backend.PHOTOSHOP when that backend is added.

        ops: list[Op] = []

        for step in plan.steps:
            n = len(step.op_names)
            if len(step.op_params) != n:
                raise CompilerError(
                    f"Step {step.step_id!r}: op_params length ({len(step.op_params)}) "
                    f"does not match op_names length ({n})"
                )
            params_list = list(step.op_params)

            for op_name_str, params in zip(step.op_names, params_list):
                try:
                    op_name = OpName(op_name_str)
                except ValueError:
                    raise CompilerError(
                        f"Step {step.step_id!r}: unknown op {op_name_str!r}. "
                        f"Valid: {[n.value for n in OpName]}"
                    )

                params = dict(params)  # shallow copy — don't mutate step
                backend_str = params.pop("backend", None)
                if backend_str is not None:
                    try:
                        backend = Backend(backend_str)
                    except ValueError:
                        raise CompilerError(
                            f"Step {step.step_id!r}: unknown backend {backend_str!r}. "
                            f"Valid: {[b.value for b in Backend]}"
                        )
                else:
                    backend = get_spec(op_name).default_backend

                # no_genai safety net: block all GENAI ops; redirect inpaint to OPENCV
                if no_genai and backend == Backend.GENAI:
                    if op_name in _INPAINT_OPS:
                        backend = Backend.OPENCV
                    else:
                        raise CompilerError(
                            f"Step {step.step_id!r}: op {op_name.value!r} requires Backend.GENAI "
                            "but GenAI is disabled (no_genai=True).",
                            repairable=False,
                        )

                # Key/deps gate: fail early with a clear message rather than at execution time.
                if backend == Backend.GENAI:
                    model = params.get("model", _DEFAULT_GENAI_MODEL)
                    prov = provider_name_for(model)
                    if prov not in available_genai_providers():
                        hint = provider_env_hint(prov)
                        raise CompilerError(
                            f"Step {step.step_id!r}: op {op_name.value!r} needs provider "
                            f"'{prov}' but no key/deps found. {hint}",
                            repairable=False,
                        )

                ops.append(
                    Op(
                        op_name=op_name,
                        backend=backend,
                        params=params,
                        step_id=step.step_id,  # STABLE ID linkage
                        risk_tier=get_spec(op_name).risk_tier,
                    )
                )

        ops = _collapse_mask_ops(ops, detected_subject)

        if detected_subject is not None:
            b = detected_subject.bbox
            ops = [
                (
                    op.model_copy(
                        update={
                            "params": {
                                **op.params,
                                "focus_x": b.x,
                                "focus_y": b.y,
                                "focus_w": b.width,
                                "focus_h": b.height,
                            }
                        }
                    )
                    if op.op_name == OpName.FRAME and "focus_x" not in op.params
                    else op
                )
                for op in ops
            ]

        graph = OpGraph(ops=ops)
        try:
            validate_op_graph(graph, allowed_ops=allowed)
        except ValueError as exc:
            raise CompilerError(f"Plan failed validation: {exc}") from exc

        return CompilerResult(plan=plan, op_graph=graph)
