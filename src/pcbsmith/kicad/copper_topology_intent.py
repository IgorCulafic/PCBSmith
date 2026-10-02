"""Placement-resolved copper topology intent with future stackup roles.

This is the second bounded Phase 17 copper experiment.  It keeps logical roles
independent of KiCad layer names, groups multi-terminal power nets into one
shared tree, and declares ground escapes separately from the reference plane.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CopperRole = Literal["signal", "pad_escape", "branch", "trunk", "plane"]
RegionKind = Literal["board_fill", "manhattan_corridor", "shared_tree"]


@dataclass(frozen=True)
class CopperTopologyPath:
    path_id: str
    region_id: str
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
            "region_id": self.region_id,
            "net_name": self.net_name,
            "source": list(self.source),
            "sink": list(self.sink),
            "role": self.role,
            "nominal_width_mm": self.nominal_width_mm,
            "escape_width_mm": self.escape_width_mm,
            "maximum_escape_length_mm": self.maximum_escape_length_mm,
        }


@dataclass(frozen=True)
class CopperTopologyRegion:
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
    nodes: tuple[tuple[str, str], ...]

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
            "nodes": [list(node) for node in self.nodes],
        }


@dataclass(frozen=True)
class CopperGroundEscape:
    escape_id: str
    net_name: str
    pad: tuple[str, str]
    source_layer: str
    target_layer: str
    track_width_mm: float
    via_diameter_mm: float
    via_drill_mm: float
    preferred_offset_mm: float
    maximum_offset_mm: float
    allow_via_in_pad_fallback: bool

    def record(self) -> dict[str, object]:
        return {
            "escape_id": self.escape_id,
            "net_name": self.net_name,
            "pad": list(self.pad),
            "source_layer": self.source_layer,
            "target_layer": self.target_layer,
            "strategy": "short_offset_through_via",
            "track_width_mm": self.track_width_mm,
            "via_diameter_mm": self.via_diameter_mm,
            "via_drill_mm": self.via_drill_mm,
            "preferred_offset_mm": self.preferred_offset_mm,
            "maximum_offset_mm": self.maximum_offset_mm,
            "allow_via_in_pad_fallback": self.allow_via_in_pad_fallback,
        }


@dataclass(frozen=True)
class CopperTopologyPlan:
    case_id: str
    copper_layer_count: int
    layer_roles: dict[str, str]
    paths: tuple[CopperTopologyPath, ...]
    regions: tuple[CopperTopologyRegion, ...]
    escapes: tuple[CopperGroundEscape, ...]

    def record(self) -> dict[str, object]:
        return {
            "schema": "pcbsmith-copper-topology-intent-v2",
            "case_id": self.case_id,
            "strategy": "shared_tree_with_ground_escapes",
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
                        "Resolve logical roles after impedance, return-path, voltage-domain, "
                        "thermal, fabrication, and assembly constraints are selected."
                    ),
                },
            },
            "paths": [path.record() for path in self.paths],
            "regions": [region.record() for region in self.regions],
            "escapes": [escape.record() for escape in self.escapes],
            "acceptance_boundary": (
                "Shared-tree regions and ground escapes are routing-topology evidence. "
                "They do not establish continuous cross-section, ampacity, voltage drop, "
                "temperature rise, via capacity, assembly suitability, or release."
            ),
        }


def build_copper_topology_intent(
    contract: dict[str, object],
    *,
    allow_diagnostic_via_in_pad: bool = False,
) -> CopperTopologyPlan:
    """Build shared power trees and explicit ground-escape intent."""
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
    paths: list[CopperTopologyPath] = []
    regions: list[CopperTopologyRegion] = []
    escapes: list[CopperGroundEscape] = []
    for raw_net in nets:
        if not isinstance(raw_net, dict):
            continue
        name = str(raw_net["name"])
        raw_nodes = raw_net.get("nodes")
        if not isinstance(raw_nodes, list) or len(raw_nodes) < 2:
            continue
        nodes = tuple((str(node[0]), str(node[1])) for node in raw_nodes)
        width = float(str(raw_net["width_mm"]))
        width_class = str(raw_net.get("width_class", "signal"))
        if name == "GND":
            region_id = "gnd-reference-plane"
            regions.append(
                CopperTopologyRegion(
                    region_id=region_id,
                    net_name=name,
                    role="plane",
                    kind="board_fill",
                    logical_layer_role="ground_reference",
                    physical_layer=layer_roles["ground_reference"],
                    width_mm=None,
                    clearance_mm=0.2,
                    edge_inset_mm=0.5,
                    priority=1,
                    nodes=nodes,
                )
            )
            for index, pad in enumerate(nodes, start=1):
                escapes.append(
                    CopperGroundEscape(
                        escape_id=f"gnd-escape-{index:02d}",
                        net_name=name,
                        pad=pad,
                        source_layer="F.Cu",
                        target_layer=layer_roles["ground_reference"],
                        track_width_mm=min(width, 0.4),
                        via_diameter_mm=0.7,
                        via_drill_mm=0.3,
                        preferred_offset_mm=0.9,
                        maximum_offset_mm=1.5,
                        allow_via_in_pad_fallback=allow_diagnostic_via_in_pad,
                    )
                )
        if width_class not in {"power", "load", "return"}:
            continue
        source = nodes[0]
        role: CopperRole = "plane" if name == "GND" else "trunk" if name == "VIN" else "branch"
        escape_width = min(width, 0.4 if width >= 0.8 else width)
        if name == "GND":
            region_id = "gnd-reference-plane"
        elif len(nodes) > 2:
            region_id = f"{name.lower()}-shared-tree"
            regions.append(
                CopperTopologyRegion(
                    region_id=region_id,
                    net_name=name,
                    role=role,
                    kind="shared_tree",
                    logical_layer_role="power_distribution",
                    physical_layer=layer_roles["power_distribution"],
                    width_mm=width,
                    clearance_mm=0.2,
                    edge_inset_mm=0.5,
                    priority=100 + len(regions),
                    nodes=nodes,
                )
            )
        else:
            region_id = f"{name.lower()}-01"
            regions.append(
                CopperTopologyRegion(
                    region_id=region_id,
                    net_name=name,
                    role=role,
                    kind="manhattan_corridor",
                    logical_layer_role="power_distribution",
                    physical_layer=layer_roles["power_distribution"],
                    width_mm=width,
                    clearance_mm=0.2,
                    edge_inset_mm=0.5,
                    priority=100 + len(regions),
                    nodes=nodes,
                )
            )
        for index, sink in enumerate(nodes[1:], start=1):
            paths.append(
                CopperTopologyPath(
                    path_id=f"{name.lower()}-{index:02d}",
                    region_id=region_id,
                    net_name=name,
                    source=source,
                    sink=sink,
                    role=role,
                    nominal_width_mm=width,
                    escape_width_mm=escape_width,
                    maximum_escape_length_mm=3.0,
                )
            )
    return CopperTopologyPlan(
        case_id=str(contract["case_id"]),
        copper_layer_count=layers,
        layer_roles=layer_roles,
        paths=tuple(paths),
        regions=tuple(regions),
        escapes=tuple(escapes),
    )


__all__ = [
    "CopperGroundEscape",
    "CopperTopologyPath",
    "CopperTopologyPlan",
    "CopperTopologyRegion",
    "build_copper_topology_intent",
]
