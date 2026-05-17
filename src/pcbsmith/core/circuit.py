from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class CircuitPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str
    net: str | None = None
    role: str | None = None


class CircuitComponent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    symbol_id: str
    value: str
    footprint_id: str | None = None
    pins: tuple[CircuitPin, ...] = ()


class CircuitNet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    role: str | None = None


class CircuitDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    components: tuple[CircuitComponent, ...] = ()
    nets: tuple[CircuitNet, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_circuit(self) -> CircuitDesign:
        references = [component.reference for component in self.components]
        if len(references) != len(set(references)):
            raise ValueError("Duplicate circuit component reference")

        declared_nets = {net.name for net in self.nets}
        if declared_nets:
            for component in self.components:
                for pin in component.pins:
                    if pin.net is not None and pin.net not in declared_nets:
                        raise ValueError(
                            f"Component {component.reference} pin {pin.number} "
                            f"uses undeclared net {pin.net}"
                        )
        return self


def compose_circuit_designs(name: str, *designs: CircuitDesign) -> CircuitDesign:
    components = tuple(component for design in designs for component in design.components)
    nets_by_name: dict[str, CircuitNet] = {}
    notes: list[str] = []

    for design in designs:
        notes.extend(design.notes)
        for net in design.nets:
            nets_by_name.setdefault(net.name, net)
        for component in design.components:
            for pin in component.pins:
                if pin.net is not None:
                    nets_by_name.setdefault(pin.net, CircuitNet(name=pin.net))

    return CircuitDesign(
        name=name,
        components=components,
        nets=tuple(nets_by_name.values()),
        notes=tuple(notes),
    )


__all__ = [
    "CircuitComponent",
    "CircuitDesign",
    "CircuitNet",
    "CircuitPin",
    "compose_circuit_designs",
]
