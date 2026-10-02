"""Current native copper-loop execution for the production routing boundary.

Consumes explicit project engineering limits; no default approval or inferred
physical qualification. Native geometry is checked before graph construction.
"""

from __future__ import annotations

import hashlib
import heapq
import math
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import Field

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.decoupling_loop_ir import (
    DecouplingLoopDeclaration,
    DecouplingLoopEvaluationResult,
    DecouplingLoopPolicy,
    DecouplingTerminalInventory,
    DecouplingTerminalInventoryEntry,
    decoupling_loop_context_fingerprint,
)
from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM, BoardLayout, BoardNetlist
from pcbsmith.kicad.decoupling_loop import evaluate_decoupling_loop
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph, resolve_copper_path
from pcbsmith.kicad.routing_candidate_transaction import require_saved_layout_matches
from pcbsmith.project_engineering_gate_ir import Phase14FeatureDeclaration
from pcbsmith.routed_copper_graph_ir import (
    CopperTerminalAnchorBinding,
    DeclaredCopperPathSelection,
    ExactRational,
    ResolvedCopperPathResult,
    RoutedCopperGraphResult,
)
from pcbsmith.rule_profiles import PcbRuleProfile
from pcbsmith.semantic_ir import EvidenceApplicabilityBinding, SemanticIrModel


class LoopRequirement(SemanticIrModel):
    declaration_id: str
    capacitor_reference: str
    capacitor_power_pin: str = "1"
    capacitor_return_pin: str = "2"
    load_reference: str
    load_power_pin: str
    load_return_pin: str
    power_net_name: str
    return_net_name: str
    maximum_via_count: int = Field(ge=0)
    minimum_track_width_mm: Decimal = Field(gt=0)
    maximum_projected_loop_area_mm2: Decimal = Field(gt=0)
    projected_area_method: Literal["exact_simple", "conservative_envelope"] = Field(
        default="exact_simple", exclude_if=lambda v: v == "exact_simple"
    )
    require_dedicated: bool
    rationale: str = Field(min_length=1)


class RoutedEngineeringSource(SemanticIrModel):
    project_id: str
    revision: str = Field(min_length=1)
    reviewer_record_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    loops: tuple[LoopRequirement, ...] = Field(min_length=1)


class ConservativeEnvelopeRevision(SemanticIrModel):
    """Explicit narrow review of a retained candidate; no route-input rewrite."""

    retained_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_board_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_reference: str = Field(min_length=1)
    source: RoutedEngineeringSource


def read_envelope_revision(
    path: Path,
    digest: str,
    *,
    original: RoutedEngineeringSource,
    original_sha256: str,
    retained_result_sha256: str,
) -> ConservativeEnvelopeRevision:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("engineering revision changed")
    revision = ConservativeEnvelopeRevision.model_validate_json(raw)
    if (
        revision.retained_result_sha256 != retained_result_sha256
        or revision.predecessor_source_sha256 != original_sha256
    ):
        raise ValueError("engineering revision predecessor mismatch")
    if not revision.authorization_reference.strip():
        raise ValueError("engineering revision requires explicit authorization")
    updated = revision.source
    if (
        updated.project_id != original.project_id
        or updated.revision == original.revision
        or not updated.reviewer_record_id.strip()
    ):
        raise ValueError("engineering revision requires same project and a new reviewed revision")
    previous = {item.declaration_id: item for item in original.loops}
    if len(updated.loops) != len(previous) or len({i.declaration_id for i in updated.loops}) != len(
        previous
    ):
        raise ValueError("engineering revision cannot change loop coverage")
    for item in updated.loops:
        prior = previous.get(item.declaration_id)
        if (
            prior is None
            or prior.projected_area_method != "exact_simple"
            or item.projected_area_method != "conservative_envelope"
            or item.model_dump(exclude={"projected_area_method", "rationale"})
            != prior.model_dump(exclude={"projected_area_method", "rationale"})
        ):
            raise ValueError("engineering revision may change only the area method and rationale")
    return revision


def read_engineering_source(
    path: Path, digest: str, project_id: str, features: Sequence[Phase14FeatureDeclaration]
) -> RoutedEngineeringSource:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("routed engineering source changed")
    source = RoutedEngineeringSource.model_validate_json(raw)
    if source.project_id != project_id:
        raise ValueError("routed engineering source belongs to another project")
    required = {d for feature in features for d in feature.required_declaration_ids}
    declarations = [item.declaration_id for item in source.loops]
    if set(declarations) != required or len(set(declarations)) != len(declarations):
        raise ValueError("routed engineering declarations do not cover deferred features exactly")
    for feature in features:
        if feature.family.value != "decoupling_loop":
            raise ValueError("unsupported deferred routed engineering family")
        for item in source.loops:
            if item.declaration_id in feature.required_declaration_ids:
                if {item.capacitor_reference, item.load_reference} != set(
                    feature.subject_component_references
                ):
                    raise ValueError("routed loop roles differ from declared feature subjects")
    return source


def native_terminal_anchors(
    board: Path, netlist: BoardNetlist
) -> tuple[CopperTerminalAnchorBinding, ...]:
    expected = {(r, p): n.name for n in netlist.nets for r, p in n.nodes}
    found: dict[tuple[str, str], list[CopperTerminalAnchorBinding]] = {}
    origin = Decimal(str(BOARD_SHEET_ORIGIN_MM))
    for fp in _children(parse_sexpr(board.read_text(encoding="utf-8")), "footprint"):
        props = {_atom(n[1]): _atom(n[2]) for n in _children(fp, "property")}
        ref = props["Reference"]
        at = _children(fp, "at")[0]
        x, y = Decimal(_atom(at[1])) - origin, Decimal(_atom(at[2])) - origin
        angle = Decimal(_atom(at[3])) % 360 if len(at) > 3 else Decimal(0)
        angle = (angle + 360) % 360
        layer = _atom(_children(fp, "layer")[0][1])
        if layer != "F.Cu" or angle not in {0, 90, 180, 270}:
            raise ValueError("native loop adapter requires front-side orthogonal footprints")
        for pad in _children(fp, "pad"):
            pin = _atom(pad[1])
            key = (ref, pin)
            if key not in expected:
                continue
            names = _children(pad, "net")
            if not names or _atom(names[0][-1]) != expected[key]:
                raise ValueError("native terminal net mismatch")
            pos = _children(pad, "at")[0]
            dx, dy = Decimal(_atom(pos[1])), Decimal(_atom(pos[2]))
            dx, dy = {0: (dx, dy), 90: (dy, -dx), 180: (-dx, -dy), 270: (-dy, dx)}[int(angle)]
            layers = {_atom(v) for v in _children(pad, "layers")[0][1:]}
            through = _atom(pad[2]) == "thru_hole" and "*.Cu" in layers
            if not through and "F.Cu" not in layers:
                raise ValueError("unsupported native terminal copper layers")
            shape = _atom(pad[3])
            if shape not in {"circle", "oval", "rect", "roundrect"}:
                raise ValueError("unsupported native pad contact shape")
            size = _children(pad, "size")[0]
            diameter = min(Decimal(_atom(size[1])), Decimal(_atom(size[2]))) if through else None
            siblings = found.setdefault(key, [])
            if any(a.x_mm == x + dx and a.y_mm == y + dy for a in siblings):
                raise ValueError("stacked native pad aliases are not supported")
            suffix = "" if not siblings else f":instance-{len(siblings) + 1}"
            siblings.append(
                CopperTerminalAnchorBinding(
                    anchor_id=f"pad:{ref}:{pin}" + suffix,
                    physical_pad_source_id=f"native-pad:{ref}:{pin}" + suffix,
                    component_reference=ref,
                    pad_number=pin,
                    net_name=expected[key],
                    layer="F.Cu",
                    x_mm=x + dx,
                    y_mm=y + dy,
                    through_hole_diameter_mm=diameter,
                    copper_contact_radius_mm=min(Decimal(_atom(size[1])), Decimal(_atom(size[2])))
                    / 2,
                )
            )
    if set(found) != set(expected):
        raise ValueError("native loop terminal inventory incomplete")
    return tuple(a for k in sorted(found) for a in found[k])


def _select_path(
    graph: RoutedCopperGraphResult, start: str, end: str, net: str, name: str
) -> ResolvedCopperPathResult:
    nodes = {a: n.node_id for n in graph.nodes for a in n.anchor_ids}
    adjacency: dict[str, list[tuple[str, str, float]]] = {}
    for edge in graph.edges:
        if edge.net_name != net:
            continue
        if edge.kind == "exact_zone_fill":
            raise ValueError("native loop selection does not support zone shortcuts")
        if edge.kind != "via" and edge.planar_squared_length is None:
            raise ValueError("track edge has no exact length")
        weight = (
            1.0
            if edge.kind == "via"
            else math.sqrt(float(edge.planar_squared_length.fraction()))
            if edge.planar_squared_length is not None
            else 1.0
        )
        adjacency.setdefault(edge.start_node_id, []).append(
            (edge.end_node_id, edge.edge_id, weight)
        )
        adjacency.setdefault(edge.end_node_id, []).append(
            (edge.start_node_id, edge.edge_id, weight)
        )
    queue: list[tuple[float, tuple[str, ...], str]] = [(0.0, (), nodes[start])]
    visited = set()
    selected: tuple[str, ...] | None = None
    while queue:
        distance, path, node = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        if node == nodes[end]:
            selected = path
            break
        for neighbor, edge_id, weight in sorted(adjacency.get(node, ())):
            if neighbor not in visited:
                heapq.heappush(queue, (distance + weight, (*path, edge_id), neighbor))
    return resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id=name,
            graph_fingerprint=graph.graph_fingerprint,
            net_name=net,
            start_anchor_id=start,
            end_anchor_id=end,
            ordered_edge_ids=selected,
        ),
    )


def execute_native_loops(
    *,
    board: Path,
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
    source: RoutedEngineeringSource,
    source_sha256: str,
) -> tuple[DecouplingLoopEvaluationResult, ...]:
    if layout.zones:
        raise ValueError(
            "native loop adapter requires routed tracks; zone support is not qualified"
        )
    require_saved_layout_matches(board.read_text(encoding="utf-8"), layout, netlist, profile)
    anchors = native_terminal_anchors(board, netlist)
    graph = build_routed_copper_graph(layout, netlist, anchors, resolve_point_contacts=True)
    by_id = {a.anchor_id: a for a in anchors}
    results = []
    for item in source.loops:
        roles = {
            "source_power": f"pad:{item.capacitor_reference}:{item.capacitor_power_pin}",
            "source_return": f"pad:{item.capacitor_reference}:{item.capacitor_return_pin}",
            "load_power": f"pad:{item.load_reference}:{item.load_power_pin}",
            "load_return": f"pad:{item.load_reference}:{item.load_return_pin}",
        }
        for role, identity in roles.items():
            if any(a.anchor_id.startswith(identity + ":instance-") for a in anchors):
                raise ValueError(
                    "loop endpoint has multiple physical pads; explicit endpoint selection required"
                )
            net = item.power_net_name if role.endswith("power") else item.return_net_name
            if identity not in by_id or by_id[identity].net_name != net:
                raise ValueError("routed loop pin role/net does not match saved board")
        supply = _select_path(
            graph,
            roles["source_power"],
            roles["load_power"],
            item.power_net_name,
            item.declaration_id + ":supply",
        )
        return_leg = _select_path(
            graph,
            roles["load_return"],
            roles["source_return"],
            item.return_net_name,
            item.declaration_id + ":return",
        )
        inventory = DecouplingTerminalInventory(
            inventory_id=item.declaration_id + ":inventory",
            graph_fingerprint=graph.graph_fingerprint,
            power_net_name=item.power_net_name,
            return_net_name=item.return_net_name,
            completeness="complete",
            distinct_physical_pad_instances=True,
            entries=tuple(
                DecouplingTerminalInventoryEntry(
                    anchor_id=a.anchor_id,
                    physical_pad_source_id=a.physical_pad_source_id,
                    component_reference=a.component_reference,
                    pad_number=a.pad_number,
                    net_name=a.net_name,
                )
                for a in anchors
                if a.net_name in {item.power_net_name, item.return_net_name}
            ),
        )
        policy = DecouplingLoopPolicy(
            policy_id=item.declaration_id + ":policy",
            mode="sourced_hard",
            intended_consumer="prototype routed engineering acceptance",
            maximum_via_count=ExactRational.build(Fraction(item.maximum_via_count)),
            minimum_track_width_mm=item.minimum_track_width_mm,
            maximum_projected_loop_area_mm2=ExactRational.build(
                Fraction(item.maximum_projected_loop_area_mm2)
            ),
            projected_area_method=item.projected_area_method,
            require_dedicated=item.require_dedicated,
            applicability_binding=None,
        )
        role_fields = {role + "_anchor_id": identity for role, identity in roles.items()}
        role_fields.update(
            {
                role + "_pad_source_id": by_id[identity].physical_pad_source_id
                for role, identity in roles.items()
            }
        )
        declaration = DecouplingLoopDeclaration(
            declaration_id=item.declaration_id,
            graph_fingerprint=graph.graph_fingerprint,
            board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
            board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
            supply_path_result_fingerprint=supply.result_fingerprint,
            return_path_result_fingerprint=return_leg.result_fingerprint,
            expected_power_net_name=item.power_net_name,
            expected_return_net_name=item.return_net_name,
            terminal_inventory=inventory,
            policy=policy,
            **role_fields,
        )
        conditions = ("project=" + source.project_id, "loop=" + item.declaration_id)
        evidence = EvidenceRef(
            kind="project_requirement",
            title="Reviewed prototype routed-loop limits",
            locator="loops." + item.declaration_id,
            source_id="routed-engineering-source:" + source_sha256,
            organization_or_author=source.reviewer_record_id,
            revision=source.revision,
            local_sha256=source_sha256,
            source_status="pinned",
            locator_status="text_verified",
            applicability_status="confirmed",
            required_conditions=conditions,
        )
        binding = EvidenceApplicabilityBinding(
            binding_id=item.declaration_id + ":binding",
            evidence=(evidence,),
            claim_id=policy.policy_id,
            applicability_record_id=source.reviewer_record_id,
            required_conditions=conditions,
            matched_conditions=conditions,
            geometry_source_fingerprint=decoupling_loop_context_fingerprint(declaration),
            reviewer_record_id=source.reviewer_record_id,
        )
        declaration = declaration.model_copy(
            update={"policy": policy.model_copy(update={"applicability_binding": binding})}
        )
        results.append(evaluate_decoupling_loop(graph, supply, return_leg, declaration))
    return tuple(results)
