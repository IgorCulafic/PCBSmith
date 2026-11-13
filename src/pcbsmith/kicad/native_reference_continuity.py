"""Source-bound four-layer reference geometry using actual saved plane contacts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.copper_layers import saved_copper_layers
from pcbsmith.kicad.final_fill_adapter import FillReachability
from pcbsmith.kicad.final_fill_connectivity import classify_final_fill_reachability
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.native_fill_graph import _child, _net, read_native_fill
from pcbsmith.kicad.reference_continuity import (
    ReferenceContinuityEvidence,
    _fingerprint,
    reference_continuity_context,
)
from pcbsmith.kicad.reference_continuity_geometry import Polygon, segment_fully_covered
from pcbsmith.routed_copper_graph_ir import NativeFilledCopperInput, fingerprint
from pcbsmith.semantic_ir import SemanticIrModel


class NativeReferencePolicy(SemanticIrModel):
    schema_id: Literal["pcbsmith-native-adjacent-reference-policy-v1"]
    layer_references: dict[str, tuple[str, str]]
    source_pad_ids: dict[str, tuple[str, ...]]
    maximum_stitch_distance_mm: Decimal = Field(gt=0)
    allowed_transition_void_half_size_mm: Decimal | None = Field(default=None, gt=0)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_adjacent_references(self) -> Self:
        if (
            set(self.layer_references) != {"F.Cu", "B.Cu"}
            or self.layer_references["F.Cu"][0] != "In1.Cu"
            or self.layer_references["B.Cu"][0] != "In2.Cu"
            or self.layer_references["F.Cu"][1] != self.layer_references["B.Cu"][1]
        ):
            raise ValueError(
                "qualified four-layer scope requires adjacent inner references on one net"
            )
        nets = {v[1] for v in self.layer_references.values()}
        if set(self.source_pad_ids) != nets or any(not ids for ids in self.source_pad_ids.values()):
            raise ValueError("each reference net requires explicit physical source pads")
        return self


def _nm(value: Any) -> int:
    exact = Decimal(_atom(value)) * 1_000_000
    if exact != exact.to_integral_value():
        raise ValueError("native reference geometry must use integer nanometres")
    return int(exact)


def _xy(node: Any, field: str) -> tuple[int, int]:
    item = _child(node, field)
    return _nm(item[1]), _nm(item[2])


def evaluate_native_reference_continuity(
    board: Path,
    policy_file: Path,
    native: NativeFilledCopperInput,
) -> ReferenceContinuityEvidence:
    """Qualify centerline support and connected stitches; never SI/EMC or current rating."""
    before = reference_continuity_context(board, policy_file)
    if board.read_bytes().decode("utf-8") != native.board_text:
        raise ValueError("reference analysis targets another native board")
    policy = NativeReferencePolicy.model_validate_json(policy_file.read_bytes())
    snapshot, observation = read_native_fill(native)
    tree = parse_sexpr(native.board_text)
    if saved_copper_layers(tree) != ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"):
        raise ValueError("native adjacent reference analysis requires the exact four-layer stack")
    contact_graph = observation.region_contact_graph
    assert contact_graph is not None
    pad_nets = {p: c.net_name for c in contact_graph.item_components for p in c.pad_ids}
    sources = tuple(p for ids in policy.source_pad_ids.values() for p in ids)
    for net, ids in policy.source_pad_ids.items():
        if any(pad_nets.get(p) != net for p in ids):
            raise ValueError("reference source pad is absent or on another net")
    classified = classify_final_fill_reachability(
        snapshot, observation, declared_source_pad_ids=sources
    )
    reachable = {
        r.region_id
        for r in classified.regions
        if r.reachability == FillReachability.SOURCE_REACHABLE
    }
    regions = {r.region_id: r for r in observation.records}
    polygons: dict[str, Polygon] = {
        r.region_id: (r.outline_nm, r.holes_nm or ())
        for r in observation.records
        if r.outline_nm is not None and r.region_id in reachable
    }
    names = {_atom(n[1]): _atom(n[2]) for n in _children(tree, "net") if len(n) >= 3}
    reference_nets = set(policy.source_pad_ids)
    signals = [
        n
        for tag in ("segment", "arc")
        for n in _children(tree, tag)
        if _net(n, names) not in reference_nets
    ]
    vias = _children(tree, "via")
    reference_vias = [v for v in vias if _net(v, names) in reference_nets]
    signal_vias = [v for v in vias if _net(v, names) not in reference_nets]
    findings: list[dict[str, object]] = []
    # Signal plated pads need their own antipad/transition inventory. Do not
    # silently use the via-only allowance for a different conductor type.
    unsupported_pad_nets = {
        _net(p, names)
        for fp in _children(tree, "footprint")
        for p in _children(fp, "pad")
        if _atom(p[2]) == "thru_hole"
        and _children(p, "net")
        and _net(p, names) not in reference_nets
    }
    links: dict[str, set[str]] = {r: set() for r in regions}
    for a, b in contact_graph.region_contacts:
        links[a].add(b)
        links[b].add(a)

    def contact_regions(via: Any, layer: str, net: str) -> set[str]:
        identity = "PCB_VIA:" + _atom(_child(via, "uuid")[1])
        pending = [
            r.region_id
            for r in regions.values()
            if r.layer == layer
            and r.net_name == net
            and identity in r.direct_contact_ids
            and r.region_id in reachable
        ]
        result: set[str] = set()
        while pending:
            node = pending.pop()
            if node in result:
                continue
            result.add(node)
            pending.extend(links[node] - result)
        return result & reachable

    approved_voids: dict[tuple[str, tuple[int, int]], Polygon] = {}
    transitions = 0
    unstitched = 0
    for via in signal_vias:
        net, position = _net(via, names), _xy(via, "at")
        adjacent = [
            s
            for s in signals
            if _atom(s[0]) == "segment"
            and _net(s, names) == net
            and position in {_xy(s, "start"), _xy(s, "end")}
        ]
        used = {_atom(_child(s, "layer")[1]) for s in adjacent}
        if len(used) < 2:
            # A signal via without a proved two-sided use is outside this scoped
            # observer; it cannot earn a void allowance based on proximity alone.
            findings.append(
                {"kind": "unqualified_signal_via", "via_id": _atom(_child(via, "uuid")[1])}
            )
            unstitched += 1
            transitions += 1
            continue
        transitions += 1
        candidate_void: Polygon | None = None
        if policy.allowed_transition_void_half_size_mm is not None:
            half = _nm(str(policy.allowed_transition_void_half_size_mm))
            x, y = position
            candidate_void = (
                (
                    (x - half, y - half),
                    (x + half, y - half),
                    (x + half, y + half),
                    (x - half, y + half),
                ),
                (),
            )
        maximum = policy.maximum_stitch_distance_mm * 1_000_000
        matched = False
        for stitch in reference_vias:
            sx, sy = _xy(stitch, "at")
            if Decimal((sx - position[0]) ** 2 + (sy - position[1]) ** 2) > maximum**2:
                continue
            if used != {"F.Cu", "B.Cu"}:
                continue
            supported = True
            for segment in adjacent:
                layer = _atom(_child(segment, "layer")[1])
                ref_layer, ref_net = policy.layer_references[layer]
                if _net(stitch, names) != ref_net:
                    supported = False
                    break
                selected = contact_regions(stitch, ref_layer, ref_net)
                coverage = tuple(polygons[r] for r in sorted(selected))
                if candidate_void is not None:
                    coverage += (candidate_void,)
                if not selected or not segment_fully_covered(
                    _xy(segment, "start"), _xy(segment, "end"), coverage
                ):
                    supported = False
                    break
            if supported:
                matched = True
                break
        if not matched:
            unstitched += 1
            findings.append(
                {
                    "kind": "transition_without_connected_local_reference",
                    "via_id": _atom(_child(via, "uuid")[1]),
                }
            )
        elif candidate_void is not None:
            approved_voids[(net, position)] = candidate_void
    supported_count = 0
    unsupported_count = 0
    unsupported_geometry = 0
    for segment in signals:
        net, layer = _net(segment, names), _atom(_child(segment, "layer")[1])
        identity = _atom(_child(segment, "uuid")[1])
        if (
            _atom(segment[0]) != "segment"
            or layer not in policy.layer_references
            or net in unsupported_pad_nets
        ):
            unsupported_geometry += 1
            findings.append({"kind": "unsupported_signal_geometry", "track_id": identity})
            continue
        ref_layer, ref_net = policy.layer_references[layer]
        coverage = tuple(
            polygons[r.region_id]
            for r in regions.values()
            if r.region_id in polygons and r.layer == ref_layer and r.net_name == ref_net
        )
        endpoints = (_xy(segment, "start"), _xy(segment, "end"))
        coverage += tuple(approved_voids[(net, p)] for p in endpoints if (net, p) in approved_voids)
        if segment_fully_covered(*endpoints, coverage):
            supported_count += 1
        else:
            unsupported_count += 1
            findings.append(
                {
                    "kind": "exact_centerline_reference_discontinuity",
                    "track_id": identity,
                    "signal_layer": layer,
                    "reference_layer": ref_layer,
                }
            )
    passed = not (unsupported_count or unsupported_geometry or unstitched)
    data: dict[str, Any] = {
        "authority": "native-adjacent-reference-geometric-v2",
        "reference_net_names": tuple(sorted(reference_nets)),
        "copper_layer_count": 4,
        "signal_segment_count": len(signals),
        "exact_supported_segment_count": supported_count,
        "exact_unsupported_segment_count": unsupported_count,
        "unsupported_geometry_segment_count": unsupported_geometry,
        "signal_transition_count": transitions,
        "transition_without_nearby_reference_via_count": unstitched,
        "maximum_transition_stitch_distance_mm": float(policy.maximum_stitch_distance_mm),
        "exact_pass_authorized": passed,
        "automatic_multilayer_pass_prohibited": False,
        "plane_evidence_fingerprint": fingerprint(native.model_dump(mode="json")),
        "layer_reference_roles": policy.layer_references,
        "allowed_transition_void_half_size_mm": (
            float(policy.allowed_transition_void_half_size_mm)
            if policy.allowed_transition_void_half_size_mm is not None
            else None
        ),
        "disposition": "unsupported_track_geometry_unverified"
        if unsupported_geometry
        else "exact_geometric_continuity_observed"
        if passed
        else "exact_geometric_discontinuities_observed",
        "findings": tuple(findings),
        "context": before,
        "scope": "Exact outer straight-centerline support on declared adjacent "
        "source-connected inner planes. Signal-via transitions require a nearby "
        "through-via directly contacting both local reference "
        "regions. An explicitly bounded transition-void box is permitted only after that proof. "
        "Signal plated pads/arcs/inner routes are unsupported. "
        "No conductor-width, impedance, SI/EMC, "
        "current-density, ampacity or loop-inductance claim.",
    }
    provisional = ReferenceContinuityEvidence.model_construct(**data, evidence_fingerprint="0" * 64)
    result = ReferenceContinuityEvidence(
        **data,
        evidence_fingerprint=_fingerprint(
            provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        ),
    )
    if reference_continuity_context(board, policy_file) != before:
        raise ValueError("reference inputs changed during observation")
    return result
