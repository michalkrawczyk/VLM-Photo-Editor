from __future__ import annotations

from vlm_photo_editor.schema.ops import OpName

# Ops whose backends manage the mask internally (cannot use the generic apply→mask flow).
# Defined once here; imported by executor, validator, and compiler.
INPAINT_OPS: frozenset[OpName] = frozenset({OpName.BACKGROUND_REPLACE, OpName.REGION_EDIT})
