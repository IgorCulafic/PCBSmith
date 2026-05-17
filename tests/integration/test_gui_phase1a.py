from __future__ import annotations

from pathlib import Path

from pcbsmith.core.geom import Point
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.operations import project_io
from pcbsmith.operations.project_io import ProjectIOError
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.main_window import MainWindow
from pcbsmith.ui.schematic_scene import SchematicScene


def test_gui_entrypoint_imports() -> None:
    from pcbsmith.ui.app import main

    assert callable(main)


def test_scene_renders_symbols_and_wires() -> None:
    state = (
        EditorState.blank("main")
        .place_symbol("stdlib:R", "10k", Point(x=0, y=0))
        .place_symbol("stdlib:R", "1k", Point(x=20_320_000, y=0))
        .add_wire((Point(x=5_080_000, y=0), Point(x=15_240_000, y=0)))
    )
    scene = SchematicScene()

    scene.load_editor_state(state)

    assert len(scene.symbol_items()) == 2
    assert len(scene.wire_items()) == 1


def test_scene_represents_bent_wire_segments() -> None:
    start = Point(x=0, y=0)
    bend = Point(x=5_080_000, y=0)
    end = Point(x=5_080_000, y=5_080_000)
    state = EditorState.blank("main").add_wire((start, bend, end))
    scene = SchematicScene()

    scene.load_editor_state(state)

    wire_item = scene.wire_items()[0]
    assert wire_item.segments() == ((start, bend), (bend, end))


def test_wire_tool_routes_diagonal_segments_at_45_degrees() -> None:
    scene = SchematicScene()

    scene.set_tool("wire")
    scene.handle_canvas_click(Point(x=0, y=0))
    scene.handle_canvas_click(Point(x=5_080_000, y=10_160_000))

    wire = scene.editor_state.to_schematic().wires[0]
    assert wire.points == (
        Point(x=0, y=0),
        Point(x=5_080_000, y=5_080_000),
        Point(x=5_080_000, y=10_160_000),
    )


def test_wire_item_uses_adjustable_visible_stroke_width() -> None:
    scene = SchematicScene()
    scene.set_wire_stroke_width(6)
    scene.add_wire(Point(x=0, y=0), Point(x=5_080_000, y=0))

    assert scene.wire_items()[0].stroke_width() == 6


def test_scene_tools_place_resistor_and_wire() -> None:
    scene = SchematicScene()

    scene.set_tool("place_resistor")
    scene.handle_canvas_click(Point(x=0, y=0))
    scene.handle_canvas_click(Point(x=20_320_000, y=0))
    scene.set_tool("wire")
    scene.handle_canvas_click(Point(x=5_080_000, y=0))
    scene.handle_canvas_click(Point(x=15_240_000, y=0))

    schematic = scene.editor_state.to_schematic()
    assert [symbol.reference for symbol in schematic.symbols] == ["R1", "R2"]
    assert len(schematic.wires) == 1


def test_scene_load_editor_state_clears_pending_wire_start() -> None:
    scene = SchematicScene()
    replacement_state = EditorState.blank("replacement").place_symbol(
        "stdlib:R",
        "10k",
        Point(x=20_320_000, y=0),
    )

    scene.set_tool("wire")
    scene.handle_canvas_click(Point(x=0, y=0))
    scene.load_editor_state(replacement_state)
    scene.handle_canvas_click(Point(x=15_240_000, y=0))

    schematic = scene.editor_state.to_schematic()
    assert [symbol.reference for symbol in schematic.symbols] == ["R1"]
    assert schematic.wires == ()


def test_main_window_has_phase1a_docks(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.library_dock.windowTitle() == "Library"
    assert window.console_dock.windowTitle() == "Console"
    assert window.scene is not None
    assert window.view is not None


def test_library_can_place_resistor(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)

    window.place_resistor_at_origin()

    assert [item.symbol.reference for item in window.scene.symbol_items()] == ["R1"]


def test_gui_saves_and_reopens_schematic(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    project_dir = tmp_path / "demo"
    project_io.create_project(project_dir, "Demo")

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    window.scene.place_resistor(Point(x=0, y=0), value="10k")
    window.scene.place_resistor(Point(x=20_320_000, y=0), value="1k")
    window.scene.add_wire(Point(x=5_080_000, y=0), Point(x=15_240_000, y=0))
    window.save_project()

    reopened = MainWindow()
    qtbot.addWidget(reopened)
    reopened.open_project(project_dir)

    schematic = reopened.scene.editor_state.to_schematic()
    assert [symbol.reference for symbol in schematic.symbols] == ["R1", "R2"]
    assert len(schematic.wires) == 1


def test_open_project_reports_project_io_errors(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    window.open_project(tmp_path / "missing")

    assert errors == [f"Project file not found: {tmp_path / 'missing' / project_io.PROJECT_FILE}"]
    assert window.project_dir is None
    assert window.project is None


def test_open_project_reports_missing_schematic_list(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    project_dir = tmp_path / "demo"
    project_io.save_project(project_dir, Project(name="Demo", schematics=()))
    window = MainWindow()
    qtbot.addWidget(window)
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    window.open_project(project_dir)

    assert errors == ["Project has no schematics"]
    assert window.project_dir is None
    assert window.project is None


def test_create_project_reports_project_io_errors(monkeypatch, tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    def fail_create_project(project_dir, name):  # type: ignore[no-untyped-def]
        raise ProjectIOError("create failed")

    monkeypatch.setattr(project_io, "create_project", fail_create_project)
    window = MainWindow()
    qtbot.addWidget(window)
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    window.create_project(tmp_path / "demo", "Demo")

    assert errors == ["create failed"]
    assert window.project_dir is None
    assert window.project is None


def test_save_project_reports_project_io_errors(monkeypatch, tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    project_dir = tmp_path / "demo"
    project_io.create_project(project_dir, "Demo")
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    def fail_save_schematic(project_dir, relative_path, schematic):  # type: ignore[no-untyped-def]
        raise ProjectIOError("save failed")

    monkeypatch.setattr(project_io, "save_schematic", fail_save_schematic)

    window.save_project()

    assert errors == ["save failed"]


def test_save_project_reports_missing_schematic_list(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.project_dir = Path("demo")
    window.project = Project(name="Demo", schematics=())
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]

    window.save_project()

    assert errors == ["No schematic is open"]


def test_save_project_uses_opened_schematic_path(tmp_path, qtbot) -> None:  # type: ignore[no-untyped-def]
    project_dir = tmp_path / "demo"
    project_io.create_project(project_dir, "Demo")

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_project(project_dir)
    window.scene.place_resistor(Point(x=0, y=0), value="10k")

    project_io.save_schematic(project_dir, "schematics/other.sch.json", Schematic(id="other"))
    project_io.save_project(
        project_dir,
        Project(name="Demo", schematics=("schematics/other.sch.json",)),
    )

    window.save_project()

    opened_schematic = project_io.load_schematic(project_dir, "schematics/main.sch.json")
    changed_manifest_schematic = project_io.load_schematic(
        project_dir,
        "schematics/other.sch.json",
    )
    assert [symbol.reference for symbol in opened_schematic.symbols] == ["R1"]
    assert changed_manifest_schematic.symbols == ()


def test_gui_runs_erc_to_console(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.scene.place_resistor(Point(x=0, y=0), value="10k")

    window.run_erc()

    assert "ERC001" in window.console.toPlainText()


def test_gui_reports_erc_errors(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    errors: list[str] = []
    window.show_error = errors.append  # type: ignore[method-assign]
    window.scene.load_editor_state(
        EditorState.blank("main").place_symbol(
            "stdlib:UNKNOWN",
            "bad",
            Point(x=0, y=0),
        )
    )

    window.run_erc()

    assert errors == ["ERC failed: Unknown symbol stdlib:UNKNOWN"]
