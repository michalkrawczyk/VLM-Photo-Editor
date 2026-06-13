from __future__ import annotations

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.ops import Op


def apply(container: ImageContainer, op: Op) -> ImageContainer:
    raise NotImplementedError(
        f"Backend {op.backend!r} is not implemented; op {op.op_name!r} cannot execute"
    )
