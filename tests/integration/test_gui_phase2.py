from __future__ import annotations

from pcbsmith.core.geom import Point
from pcbsmith.services import component_catalog
from pcbsmith.ui.schematic_scene import SchematicScene


def test_scene_places_catalog_component(qtbot) -> None:
    scene = SchematicScene()
    catalog = component_catalog.builtin_catalog()
    entry = component_catalog.entry_by_id(catalog, "pcbs:capacitor_0603")

    item = scene.place_catalog_entry(entry, Point(x=0, y=0))

    symbol = scene.editor_state.symbols[0]
    assert item.symbol.reference == "C1"
    assert symbol.symbol_id == "stdlib:C"
    assert symbol.value == "100nF"
    assert symbol.footprint_id == "stdlib:C_0603"
