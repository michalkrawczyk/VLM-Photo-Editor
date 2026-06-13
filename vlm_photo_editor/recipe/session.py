from __future__ import annotations

from copy import deepcopy

from vlm_photo_editor.schema.recipe import Recipe


class UndoStack:
    """In-memory undo/redo stack for a single editing session.

    Not persisted. Caller is responsible for calling RecipeStore.save
    when they want to write state to disk.
    """

    def __init__(self, initial: Recipe) -> None:
        self._stack: list[Recipe] = [deepcopy(initial)]
        self._pointer: int = 0

    @property
    def current(self) -> Recipe:
        return deepcopy(self._stack[self._pointer])

    def push(self, recipe: Recipe) -> None:
        self._stack = self._stack[: self._pointer + 1]
        self._stack.append(deepcopy(recipe))
        self._pointer += 1

    def undo(self) -> Recipe:
        if self._pointer == 0:
            raise IndexError("Nothing to undo")
        self._pointer -= 1
        return deepcopy(self._stack[self._pointer])

    def redo(self) -> Recipe:
        if self._pointer >= len(self._stack) - 1:
            raise IndexError("Nothing to redo")
        self._pointer += 1
        return deepcopy(self._stack[self._pointer])

    @property
    def can_undo(self) -> bool:
        return self._pointer > 0

    @property
    def can_redo(self) -> bool:
        return self._pointer < len(self._stack) - 1

    def __len__(self) -> int:
        return len(self._stack)
