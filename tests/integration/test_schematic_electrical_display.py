from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsRectItem

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Pin, PinElectricalType, Symbol
from pcbsmith.core.netops import derive_netlist
from pcbsmith.core.schematic import Junction, NetLabel, NoConnect, Schematic, SymbolInstance
from pcbsmith.knowledge.builtin_library import SYMBOLS
from pcbsmith.operations.project_io import load_schematic, save_schematic
from pcbsmith.operations.schematic_anchors import schematic_anchors
from pcbsmith.rules.erc import run_erc
from pcbsmith.ui.editor_state import EditorState
from pcbsmith.ui.items import SymbolItem
from pcbsmith.ui.schematic_scene import SchematicScene


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("mirrored", [False, True])
def test_asymmetric_pin_display_matches_connectivity_and_v1_orientation(
    qtbot,
    monkeypatch,
    rotation,
    mirrored,
):
    # Asymmetric coordinates detect axis swaps and reflection/rotation order.
    library = Symbol(
        id="test:ASYM",
        name="Asymmetric",
        pins=[
            Pin(
                number="1",
                name="signal",
                position=Point(x=2_000_000, y=3_000_000),
                electrical_type=PinElectricalType.PASSIVE,
            ),
            Pin(
                number="2",
                name="unused",
                position=Point(x=-5_000_000, y=1_000_000),
                electrical_type=PinElectricalType.PASSIVE,
            ),
        ],
    )
    monkeypatch.setitem(SYMBOLS, library.id, library)
    symbol = SymbolInstance(
        reference="U1",
        symbol_id=library.id,
        value="test",
        position=Point(x=17_000_000, y=29_000_000),
        rotation_deg=rotation,
        mirrored_x=mirrored,
    )
    old_renderer = QGraphicsRectItem()
    old_renderer.setPos(symbol.position.x, symbol.position.y)
    old_renderer.setRotation(rotation)
    if mirrored:
        old_renderer.setTransform(QTransform.fromScale(-1, 1))
    shown = SymbolItem(symbol)
    expected = []
    for pin in library.pins:
        point = QPointF(pin.position.x, pin.position.y)
        old = old_renderer.mapToScene(point)
        actual = shown.mapToScene(point)
        assert actual == old
        expected.append(Point(x=round(old.x()), y=round(old.y())))
    schematic = Schematic(
        id="test",
        symbols=(symbol,),
        labels=(NetLabel(name="SIGNAL", position=expected[0]),),
        no_connects=(NoConnect(position=expected[1]),),
    )
    anchors = schematic_anchors(schematic, SYMBOLS)
    assert [anchor.position for anchor in anchors] == expected
    netlist = derive_netlist(schematic, SYMBOLS)
    assert [(net.name, net.pins) for net in netlist.nets] == [("SIGNAL", frozenset({("U1", "1")}))]
    assert run_erc(schematic, SYMBOLS) == []


def test_junction_is_visible_after_load_edit_undo_and_save(qtbot, tmp_path):
    junction = Junction(position=Point(x=10_000_000, y=0))
    schematic = Schematic(id="main", junctions=(junction,))
    scene = SchematicScene()
    scene.load_editor_state(EditorState.from_schematic(schematic))
    (item,) = scene.junction_items()
    assert item.scene() is scene and item.isVisible()
    assert item.brush().color().alpha() == 255 and item.boundingRect().width() > 0
    scene.place_resistor(Point(x=0, y=0))
    scene.undo()
    assert scene.junction_items()[0].junction == junction
    save_schematic(tmp_path, "main.sch.json", scene.editor_state.to_schematic())
    assert load_schematic(tmp_path, "main.sch.json").junctions == (junction,)
