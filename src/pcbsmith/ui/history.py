from __future__ import annotations

from dataclasses import dataclass, field

from pcbsmith.ui.editor_state import EditorState


@dataclass
class EditHistory:
    current: EditorState
    _undo_stack: list[EditorState] = field(default_factory=list)
    _redo_stack: list[EditorState] = field(default_factory=list)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def commit(self, state: EditorState) -> EditorState:
        if state == self.current:
            return self.current

        self._undo_stack.append(self.current)
        self.current = state
        self._redo_stack.clear()
        return self.current

    def reset(self, state: EditorState) -> None:
        self.current = state
        self._undo_stack.clear()
        self._redo_stack.clear()

    def undo(self) -> EditorState:
        if not self._undo_stack:
            raise IndexError("No undo state")

        self._redo_stack.append(self.current)
        self.current = self._undo_stack.pop()
        return self.current

    def redo(self) -> EditorState:
        if not self._redo_stack:
            raise IndexError("No redo state")

        self._undo_stack.append(self.current)
        self.current = self._redo_stack.pop()
        return self.current
