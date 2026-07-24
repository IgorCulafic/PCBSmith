from __future__ import annotations

import pytest

from pcbsmith.core.geom import Point
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.history import EditHistory


def test_commit_then_undo_and_redo_restores_states() -> None:
    initial = EditorState.blank("main")
    changed = initial.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    history = EditHistory(initial)

    history.commit(changed)

    assert history.current == changed
    assert history.can_undo
    assert not history.can_redo
    assert history.undo() == initial
    assert history.current == initial
    assert history.can_redo
    assert history.redo() == changed
    assert history.current == changed


def test_new_commit_after_undo_clears_redo_stack() -> None:
    initial = EditorState.blank("main")
    first = initial.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    second = initial.place_symbol("stdlib:R", "1k", Point(x=2_540_000, y=0))
    history = EditHistory(initial)
    history.commit(first)
    history.undo()

    history.commit(second)

    assert history.current == second
    assert history.can_undo
    assert not history.can_redo


def test_reset_clears_undo_and_redo() -> None:
    initial = EditorState.blank("main")
    changed = initial.place_symbol("stdlib:R", "10k", Point(x=0, y=0))
    replacement = EditorState.blank("replacement")
    history = EditHistory(initial)
    history.commit(changed)
    history.undo()

    history.reset(replacement)

    assert history.current == replacement
    assert not history.can_undo
    assert not history.can_redo


def test_undo_without_history_raises() -> None:
    history = EditHistory(EditorState.blank("main"))

    with pytest.raises(IndexError, match="No undo state"):
        history.undo()
