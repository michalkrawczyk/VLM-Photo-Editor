from __future__ import annotations

from vlm_photo_editor.schema.op_catalog import BBoxClass, all_specs
from vlm_photo_editor.schema.ops import OpName

# Ops whose backends manage the mask internally (cannot use the generic apply→mask flow).
# Defined once here; imported by executor, validator, and compiler.
INPAINT_OPS: frozenset[OpName] = frozenset(
    n for n, s in all_specs().items() if s.bbox_class is BBoxClass.SELF_MANAGED_INPAINT
)
