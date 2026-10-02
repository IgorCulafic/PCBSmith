"""Layer-aware copper intent for routing benchmarks.

The contract separates logical copper roles from physical layer names so the
same design intent can target two-layer mixed copper or future dedicated plane
stackups without changing net semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CopperRole = Literal["signal", "pad_escape", "branch", "trunk", "plane"]
RegionKind = Literal["board_fill", "manhattan_corridor"]


@dataclass(frozen=True)
class CopperPathIntent:
    path_id: str
    net_name: str
    source: tuple[str, str]
    sink: tuple[str, str]
    role: CopperRole
    nominal_width_mm: float
    escape_width_mm: float
    maximum_escape_length_mm: float

    def record(self) -> dict[str, object]:
        return {
            "path_id": self.path_id,
            "net_name": self.net_name,
            "source": list(self.source),
            "sink": list(self.sink),
            "role": self.role,
            "nominal_width_mm": self.nominal_width_mm,
            "escape_width_mm": self.escape_width_mm,
            "maximum_escape_length_mm": self.maximum_escape_length_mm,
        }


@dataclass(frozen=True)
class CopperRegionIntent:
    region_id: str
    net_name: str
    role: CopperRole
    kind: RegionKind
    logical_layer_role: str
    physical_layer: str
    width_mm: float | None
    clearance_mm: float
    edge_inset_mm: float
    priority: int
    source: tuple[str, str] | None = None
    sink: tuple[str, str] | None = None

    def record(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "net_name": self.net_name,
            "role": self.role,
            "kind": self.kind,
            "logical_layer_role": self.logical_layer_role,
            "physical_layer": self.physical_layer,
            "width_mm": self.width_mm,
            "clearance_mm": self.clearance_mm,
            "edge_inset_mm": self.edge_inset_mm,
            "priority": self.priority,
            "source": list(self.source) if self.source else None,
            "sink": list(self.sink) if self.sink else None,
        }


@dataclass(frozen=True)
class CopperIntentPlan:
    case_id: str
    copper_layer_count: int
    layer_roles: dict[str, str]
    paths: tuple[CopperPathIntent, ...]
    regions: tuple[CopperRegionIntent, ...]

    def record(self) -> dict[str, object]:
        return {
            "schema": "pcbsmith-copper-intent-v1",
            "case_id": self.case_id,
            "stackup": {
                "copper_layer_count": self.copper_layer_count,
                "current_role_assignments": self.layer_roles,
                "dedicated_plane_threshold": 4,
                "future_layer_policy": {
                    "four_layer": [
                        "component_and_critical_signal",
                        "ground_reference_plane",
                        "power_distribution_plane",
                        "secondary_signal",
                    ],
                    "six_plus_layer": (
                        "Resolve logical roles only after stackup, impedance, return-path, "
                        "voltage-domain, and fabrication constraints are selected."
                    ),
                },
            },
            "paths": [path.record() for path in self.paths],
            "regions": [region.record() for region in self.regions],
            "acceptance_boundary": (
                "Copper regions and path evidence establish routing topology only. They do "
                "not establish ampacity, voltage drop, thermal rise, via capacity, plane "
                "resonance, or fabrication suitability."
            ),
        }


def build_copper_intent(contract: dict[str, object]) -> CopperIntentPlan:
    """Derive a two-layer pilot while retaining logical roles for 4+ layers."""
    board = contract.get("board")
    nets = contract.get("nets")
    if not isinstance(board, dict) or not isinstance(nets, list):
        raise TypeError("Case contract must contain board and nets")
    layers = int(str(board.get("layers", 2)))
    layer_roles = (
        {
            "ground_reference": "B.Cu",
            "power_distribution": "F.Cu",
            "primary_signal": "F.Cu",
            "secondary_signal": "B.Cu",
        }
        if layers == 2
        else {
            "ground_reference": "In1.Cu",
            "power_distribution": "In2.Cu",
            "primary_signal": "F.Cu",
            "secondary_signal": "B.Cu",
        }
    )
    paths: list[CopperPathIntent] = []
    regions: list[CopperRegionIntent] = []
    for raw_net in nets:
        if not isinstance(raw_net, dict):
            continue
        name = str(raw_net["name"])
        nodes_raw = raw_net.get("nodes")
        if not isinstance(nodes_raw, list) or len(nodes_raw) < 2:
            continue
        nodes = tuple((str(node[0]), str(node[1])) for node in nodes_raw)
        width = float(str(raw_net["width_mm"]))
        width_class = str(raw_net.get("width_class", "signal"))
        if name == "GND":
            regions.append(
                CopperRegionIntent(
                    region_id="gnd-reference-plane",
                    net_name=name,
                    role="plane",
                    kind="board_fill",
                    logical_layer_role="ground_reference",
                    physical_layer=layer_roles["ground_reference"],
                    width_mm=None,
                    clearance_mm=0.2,
                    edge_inset_mm=0.5,
                    priority=1,
                )
            )
        if width_class not in {"power", "load", "return"}:
            continue
        source = nodes[0]
        role: CopperRole = "plane" if name == "GND" else "trunk" if name == "VIN" else "branch"
        escape = min(width, 0.4 if width >= 0.8 else width)
        for index, sink in enumerate(nodes[1:], start=1):
            path_id = f"{name.lower()}-{index:02d}"
            paths.append(
                CopperPathIntent(
                    path_id=path_id,
                    net_name=name,
                    source=source,
                    sink=sink,
                    role=role,
                    nominal_width_mm=width,
                    escape_width_mm=escape,
                    maximum_escape_length_mm=3.0,
                )
            )
            if name != "GND":
                regions.append(
                    CopperRegionIntent(
                        region_id=path_id,
                        net_name=name,
                        role=role,
                        kind="manhattan_corridor",
                        logical_layer_role="power_distribution",
                        physical_layer=layer_roles["power_distribution"],
                        width_mm=width,
                        clearance_mm=0.2,
                        edge_inset_mm=0.5,
                        priority=100 + len(regions),
                        source=source,
                        sink=sink,
                    )
                )
    return CopperIntentPlan(
        case_id=str(contract["case_id"]),
        copper_layer_count=layers,
        layer_roles=layer_roles,
        paths=tuple(paths),
        regions=tuple(regions),
    )


__all__ = [
    "CopperIntentPlan",
    "CopperPathIntent",
    "CopperRegionIntent",
    "build_copper_intent",
]
