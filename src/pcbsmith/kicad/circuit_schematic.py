from __future__ import annotations

from pcbsmith.core.circuit import CircuitDesign
from pcbsmith.core.geom import Point, Vec, mm_to_nm
from pcbsmith.core.schematic import NetLabel, Schematic, SymbolInstance, Wire
from pcbsmith.kicad.kicad_export import NATIVE_SYMBOL_SPECS

_COLUMN_SPACING_MM = 38.1
_ROW_SPACING_MM = 20.32
_ORIGIN_X_MM = 25.4
_ORIGIN_Y_MM = 25.4
_COMPONENTS_PER_ROW = 5
_LABEL_STUB_MM = 2.54


def circuit_design_to_schematic(circuit: CircuitDesign) -> Schematic:
    symbols: list[SymbolInstance] = []
    labels: list[NetLabel] = []
    wires: list[Wire] = []

    for index, component in enumerate(circuit.components):
        spec = NATIVE_SYMBOL_SPECS.get(component.symbol_id)
        if spec is None:
            raise ValueError(
                f"Unsupported circuit symbol for KiCad schematic: {component.symbol_id}"
            )
        position = _component_position(index)
        symbols.append(
            SymbolInstance(
                reference=component.reference,
                symbol_id=component.symbol_id,
                value=component.value,
                position=position,
                footprint_id=component.footprint_id,
            )
        )
        for pin in component.pins:
            if pin.net is None:
                continue
            pin_index = _pin_index(pin.number, component.reference)
            try:
                pin_point = position + spec.pin_offsets[pin_index]
            except IndexError as exc:
                raise ValueError(
                    f"Component {component.reference} pin {pin.number} is not available "
                    f"on {component.symbol_id}"
                ) from exc
            label_point = pin_point + _label_stub_vector(
                spec.pin_offsets[pin_index],
                component.symbol_id,
            )
            wires.append(Wire(points=(pin_point, label_point)))
            labels.append(NetLabel(name=pin.net, position=label_point))

    return Schematic(
        id=circuit.name,
        symbols=tuple(symbols),
        wires=tuple(wires),
        labels=_unique_labels(labels),
    )


def _component_position(index: int) -> Point:
    column = index % _COMPONENTS_PER_ROW
    row = index // _COMPONENTS_PER_ROW
    return Point.from_mm(
        _ORIGIN_X_MM + (column * _COLUMN_SPACING_MM),
        _ORIGIN_Y_MM + (row * _ROW_SPACING_MM),
    )


def _pin_index(pin_number: str, reference: str) -> int:
    try:
        pin_index = int(pin_number) - 1
    except ValueError as exc:
        raise ValueError(f"Component {reference} has nonnumeric pin {pin_number}") from exc
    if pin_index < 0:
        raise ValueError(f"Component {reference} has invalid pin {pin_number}")
    return pin_index


def _label_stub_vector(pin_offset: Vec, symbol_id: str) -> Vec:
    stub_nm = mm_to_nm(_LABEL_STUB_MM)
    if symbol_id == "stdlib:CONN_01X02":
        return Vec(-stub_nm, 0)
    if pin_offset.dx < 0:
        return Vec(-stub_nm, 0)
    if pin_offset.dx > 0:
        return Vec(stub_nm, 0)
    if pin_offset.dy < 0:
        return Vec(0, -stub_nm)
    return Vec(0, stub_nm)


def _unique_labels(labels: list[NetLabel]) -> tuple[NetLabel, ...]:
    seen: set[tuple[str, int, int]] = set()
    unique: list[NetLabel] = []
    for label in labels:
        key = (label.name, label.position.x, label.position.y)
        if key in seen:
            continue
        seen.add(key)
        unique.append(label)
    return tuple(unique)


__all__ = ["circuit_design_to_schematic"]
