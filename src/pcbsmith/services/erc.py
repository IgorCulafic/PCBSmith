from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.geom import Point
from pcbsmith.core.library import Pin, PinElectricalType, Symbol
from pcbsmith.core.netops import PinRef, derive_netlist
from pcbsmith.core.schematic import Schematic, SymbolInstance


class ERCIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    where: str


def _rotate_offset(point: Point, rotation_deg: int) -> tuple[int, int]:
    rotation = rotation_deg % 360
    if rotation == 0:
        return (point.x, point.y)
    if rotation == 90:
        return (-point.y, point.x)
    if rotation == 180:
        return (-point.x, -point.y)
    if rotation == 270:
        return (point.y, -point.x)
    msg = (
        f"Unsupported symbol rotation {rotation_deg}; "
        "expected one of 0, 90, 180, or 270 degrees"
    )
    raise ValueError(msg)


def _pin_tip(instance: SymbolInstance, pin: Pin) -> tuple[int, int]:
    pin_x, pin_y = _rotate_offset(pin.position, instance.rotation_deg)
    return (instance.position.x + pin_x, instance.position.y + pin_y)


def _where(pin_ref: PinRef) -> str:
    reference, pin_number = pin_ref
    return f"{reference}.{pin_number}"


def run_erc(schematic: Schematic, symbols: dict[str, Symbol]) -> list[ERCIssue]:
    netlist = derive_netlist(schematic, symbols)
    connected_pins = {pin_ref for net in netlist.nets for pin_ref in net.pins}
    no_connect_positions = {
        (marker.position.x, marker.position.y) for marker in schematic.no_connects
    }
    issues: list[ERCIssue] = []

    for instance in schematic.symbols:
        symbol = symbols[instance.symbol_id]
        for pin in symbol.pins:
            pin_ref = (instance.reference, pin.number)
            if pin_ref in connected_pins:
                continue
            if pin.electrical_type == PinElectricalType.NO_CONNECT:
                continue
            if _pin_tip(instance, pin) in no_connect_positions:
                continue
            issues.append(
                ERCIssue(
                    code="ERC001",
                    message=f"Unconnected pin {_where(pin_ref)}",
                    where=_where(pin_ref),
                )
            )

    pin_types: dict[PinRef, PinElectricalType] = {}
    for instance in schematic.symbols:
        symbol = symbols[instance.symbol_id]
        for pin in symbol.pins:
            pin_types[(instance.reference, pin.number)] = pin.electrical_type

    for net in netlist.nets:
        power_outputs = sorted(
            pin_ref
            for pin_ref in net.pins
            if pin_types.get(pin_ref) == PinElectricalType.POWER_OUT
        )
        if len(power_outputs) < 2:
            continue
        locations = ", ".join(_where(pin_ref) for pin_ref in power_outputs)
        issues.append(
            ERCIssue(
                code="ERC002",
                message=f"Net {net.name} has multiple power outputs: {locations}",
                where=net.name,
            )
        )

    return issues
