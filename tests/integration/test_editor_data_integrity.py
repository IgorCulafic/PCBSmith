from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from pcbsmith.core.geom import Point
from pcbsmith.operations import project_io
from pcbsmith.ui.main_window import MainWindow


@pytest.mark.parametrize(
    "answer,switched,saved",
    [
        (QMessageBox.StandardButton.Cancel, False, False),
        (QMessageBox.StandardButton.Discard, True, False),
        (QMessageBox.StandardButton.Save, True, True),
    ],
)
def test_dirty_open_decision(qtbot, tmp_path, monkeypatch, answer, switched, saved):
    a, b = tmp_path / "a", tmp_path / "b"
    project_io.create_project(a, "A")
    project_io.create_project(b, "B")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(a)
    window.scene.place_resistor(Point(x=0, y=0))
    assert window.is_dirty and window.isWindowModified()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answer)
    window.open_project(b)
    assert window.project_dir == (b if switched else a)
    assert bool(project_io.load_schematic(a, "schematics/main.sch.json").symbols) == saved


def test_save_failure_cancels_navigation_and_keeps_dirty(qtbot, tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    project_io.create_project(a, "A")
    project_io.create_project(b, "B")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(a)
    window.scene.place_resistor(Point(x=0, y=0))
    errors = []
    window.show_error = errors.append
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)

    def fail_save(*args, **kwargs):
        raise project_io.ProjectIOError("disk is full")

    monkeypatch.setattr(project_io, "save_schematic", fail_save)
    window.open_project(b)
    assert window.project_dir == a and window.is_dirty
    assert len(window.scene.editor_state.symbols) == 1
    assert errors == ["disk is full"]


def test_close_and_new_respect_cancel(qtbot, tmp_path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not window.close()
    window.create_project(tmp_path / "new", "New")
    assert not (tmp_path / "new").exists()
    assert window.is_dirty


def test_saved_identity_tracks_undo_and_redo(qtbot, tmp_path):
    project_io.create_project(tmp_path, "A")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(tmp_path)
    window.scene.place_resistor(Point(x=0, y=0))
    assert window.is_dirty
    window.undo()
    assert not window.is_dirty
    window.redo()
    assert window.is_dirty
    assert window.save_project()
    assert not window.is_dirty
    window.undo()
    assert window.is_dirty
    window.redo()
    assert not window.is_dirty


def test_save_while_reopening_same_project_keeps_saved_edit(qtbot, tmp_path, monkeypatch):
    project_io.create_project(tmp_path, "A")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(tmp_path)
    window.scene.place_resistor(Point(x=0, y=0))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Save)
    window.open_project(tmp_path)
    assert len(window.scene.editor_state.symbols) == 1
    assert not window.is_dirty


def test_external_edit_cannot_be_overwritten_by_gui_save(qtbot, tmp_path):
    project_io.create_project(tmp_path, "A")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(tmp_path)
    window.scene.place_resistor(Point(x=0, y=0))
    path = tmp_path / "schematics/main.sch.json"
    external = path.read_bytes() + b"\n"
    path.write_bytes(external)
    errors = []
    window.show_error = errors.append
    assert not window.save_project()
    assert window.is_dirty and path.read_bytes() == external
    assert "changed since" in errors[0]
