from __future__ import annotations

from vlm_photo_editor.config.policy import allowed_ops_for_mode
from vlm_photo_editor.ops.validator import validate_op_graph
from vlm_photo_editor.schema.ops import Op, OpGraph, OpName, RiskTier
from vlm_photo_editor.schema.plan import CompilerResult, HumanPlan

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


class CompilerError(ValueError):
    """HumanPlan could not be compiled to a valid OpGraph."""


class Compiler:
    def compile(self, plan: HumanPlan, mode: str) -> CompilerResult:
        allowed = allowed_ops_for_mode(mode)  # KeyError for unknown mode → let propagate
        ops: list[Op] = []

        for step in plan.steps:
            n = len(step.op_names)
            params_list = list(step.op_params) + [{}] * max(0, n - len(step.op_params))

            for op_name_str, params in zip(step.op_names, params_list):
                try:
                    op_name = OpName(op_name_str)
                except ValueError:
                    raise CompilerError(
                        f"Step {step.step_id!r}: unknown op {op_name_str!r}. "
                        f"Valid: {[n.value for n in OpName]}"
                    )
                ops.append(
                    Op(
                        op_name=op_name,
                        params=dict(params),  # shallow copy — don't mutate step
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
