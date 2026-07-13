from __future__ import annotations

import socket
import time

from vlm_photo_editor.config.policy import EditMode, allowed_ops_for_mode
from vlm_photo_editor.ops.validator import validate_op_graph
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName, RiskTier
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


_OP_RISK: dict[OpName, RiskTier] = {
    OpName.CROP: RiskTier.LOW,
    OpName.ROTATE: RiskTier.LOW,
    OpName.WHITE_BALANCE: RiskTier.LOW,
    OpName.EXPOSURE: RiskTier.LOW,
    OpName.DENOISE: RiskTier.LOW,
    OpName.MASK: RiskTier.MEDIUM,
    OpName.REGION_EDIT: RiskTier.HIGH,
    OpName.BACKGROUND_REPLACE: RiskTier.HIGH,
    OpName.FRAME: RiskTier.LOW,
}

# Default backend per op; PIL is the Op default so only non-PIL entries are listed.
_OP_DEFAULT_BACKEND: dict[OpName, Backend] = {
    OpName.BACKGROUND_REPLACE: Backend.GENAI,
    OpName.REGION_EDIT: Backend.GENAI,
}

_INPAINT_OPS = {OpName.BACKGROUND_REPLACE, OpName.REGION_EDIT}


class CompilerError(ValueError):
    """HumanPlan could not be compiled to a valid OpGraph."""


class Compiler:
    def compile(self, plan: HumanPlan, mode: EditMode | str) -> CompilerResult:
        from vlm_photo_editor.config.settings import get_settings

        settings = get_settings()
        allowed = allowed_ops_for_mode(mode)  # KeyError for unknown mode → let propagate
        no_genai = settings.no_genai

        if settings.ps_mode == "strict" and not _ps_available():
            raise CompilerError(
                "PS-strict mode requires Photoshop. "
                "Connect the PS plugin or switch to 'auto' mode."
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
                    backend = _OP_DEFAULT_BACKEND.get(op_name, Backend.PIL)

                # no_genai safety net: block all GENAI ops; redirect inpaint to OPENCV
                if no_genai and backend == Backend.GENAI:
                    if op_name in _INPAINT_OPS:
                        backend = Backend.OPENCV
                    else:
                        raise CompilerError(
                            f"Step {step.step_id!r}: op {op_name.value!r} requires Backend.GENAI "
                            "but GenAI is disabled (no_genai=True)."
                        )

                ops.append(
                    Op(
                        op_name=op_name,
                        backend=backend,
                        params=params,
                        step_id=step.step_id,  # STABLE ID linkage
                        risk_tier=_OP_RISK.get(op_name, RiskTier.LOW),
                    )
                )

        graph = OpGraph(ops=ops)
        try:
            validate_op_graph(graph, allowed_ops=allowed)
        except ValueError as exc:
            raise CompilerError(f"Plan failed validation: {exc}") from exc

        return CompilerResult(plan=plan, op_graph=graph)
