"""Replay the narrow four-layer production proof at publication and handover.

Existing readiness retention owns the three referenced native/policy files.
This consumer performs no fill, routing, native edit or evidence generation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field

from pcbsmith.kicad.final_fill_thermal import audit_kicad_thermal_spokes, thermal_rule_context
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.native_fill_graph import _net, read_native_fill
from pcbsmith.kicad.native_reference_continuity import (
    NativeReferencePolicy,
    evaluate_native_reference_continuity,
)
from pcbsmith.kicad.reference_continuity import ReferenceContinuityEvidence
from pcbsmith.production_planes import PostRoutePlanePlan
from pcbsmith.routed_copper_graph_ir import NativeFilledCopperInput
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.whole_board_qualification_adapter import _fill_gate


class FourLayerPublicationEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-four-layer-publication-v1"]
    plan: PostRoutePlanePlan
    reference_policy_relative_path: str
    native_filled_copper: NativeFilledCopperInput | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    thermal_drc_relative_path: str | None = Field(default=None, exclude_if=lambda v: v is None)
    thermal_receipt_relative_path: str | None = Field(default=None, exclude_if=lambda v: v is None)
    reference_evidence: ReferenceContinuityEvidence | None = Field(
        default=None, exclude_if=lambda v: v is None
    )


def _declared_plane_outline(tree: Any, plan: PostRoutePlanePlan) -> set[tuple[Decimal, Decimal]]:
    edges = [
        node
        for node in tree
        if isinstance(node, list)
        and _children(node, "layer")
        and _atom(_children(node, "layer")[0][1]) == "Edge.Cuts"
    ]
    rectangle = len(edges) == 1 and _atom(edges[0][0]) == "gr_rect"
    if not rectangle and (len(edges) != 4 or any(_atom(node[0]) != "gr_line" for node in edges)):
        raise ValueError("post-route inner-plane publication requires a rectangular board")
    lines = [
        tuple(
            tuple(Decimal(_atom(v)) for v in _children(node, tag)[0][1:3])
            for tag in ("start", "end")
        )
        for node in edges
    ]
    points = {point for line in lines for point in line}
    left, top = min(p[0] for p in points), min(p[1] for p in points)
    right, bottom = max(p[0] for p in points), max(p[1] for p in points)
    corners = ((left, top), (right, top), (right, bottom), (left, bottom))
    if (
        (
            not rectangle
            and {frozenset(line) for line in lines}
            != {frozenset((corners[i], corners[(i + 1) % 4])) for i in range(4)}
        )
        or left == right
        or top == bottom
    ):
        raise ValueError("post-route inner-plane publication requires a closed rectangle")
    inset = Decimal(str(plan.edge_inset_mm))
    if inset * 2 >= min(right - left, bottom - top):
        raise ValueError("post-route plane inset leaves no area")
    return {
        (left + inset, top + inset),
        (right - inset, top + inset),
        (right - inset, bottom - inset),
        (left + inset, bottom - inset),
    }


def require_four_layer_publication(
    board: Path,
    evidence: FourLayerPublicationEvidence,
    artifact_root: Path,
    retained_file_hashes: Mapping[str, str],
) -> None:
    def retained(relative: str) -> Path:
        posix = PurePosixPath(relative)
        file = artifact_root / posix
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or ":" in relative
            or "\\" in relative
            or not file.resolve().is_relative_to(artifact_root.resolve())
            or not file.is_file()
            or relative not in retained_file_hashes
            or hashlib.sha256(file.read_bytes()).hexdigest() != retained_file_hashes[relative]
        ):
            raise ValueError("four-layer proof file is missing, changed or unretained")
        return file

    from pcbsmith.kicad.copper_layers import saved_copper_layers

    raw = board.read_bytes()
    tree = parse_sexpr(raw.decode("utf-8"))
    if saved_copper_layers(tree) != ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"):
        raise ValueError("four-layer publication requires the exact ordered four-layer stack")
    policy_file = retained(evidence.reference_policy_relative_path)
    policy = NativeReferencePolicy.model_validate_json(policy_file.read_bytes())
    if policy != evidence.plan.reference_policy:
        raise ValueError("publication reference policy differs from its plane plan")
    names = {_atom(n[1]): _atom(n[2]) for n in _children(tree, "net") if len(n) >= 3}
    pads = {
        "pad:" + _atom(_children(pad, "uuid")[0][1]): _net(pad, names)
        for fp in _children(tree, "footprint")
        for pad in _children(fp, "pad")
        if _children(pad, "net") and _children(pad, "uuid")
    }
    if any(pads.get(pad) != net for net, ids in policy.source_pad_ids.items() for pad in ids):
        raise ValueError("publication reference source pad is absent or on another net")
    intended = _declared_plane_outline(tree, evidence.plan)
    routed = any(_children(tree, tag) for tag in ("segment", "arc", "via", "zone"))
    routed_fields = (
        evidence.native_filled_copper,
        evidence.thermal_drc_relative_path,
        evidence.thermal_receipt_relative_path,
        evidence.reference_evidence,
    )
    if not routed:
        if any(value is not None for value in routed_fields):
            raise ValueError("unrouted placement cannot reuse filled-board evidence")
        return
    if any(value is None for value in routed_fields):
        raise ValueError("four-layer routed publication requires the complete native plane proof")
    assert evidence.native_filled_copper is not None
    assert evidence.thermal_drc_relative_path is not None
    assert evidence.thermal_receipt_relative_path is not None
    assert evidence.reference_evidence is not None
    if evidence.native_filled_copper.board_text.encode("utf-8") != raw:
        raise ValueError("four-layer plane proof targets different board bytes")
    snapshot, contacts = read_native_fill(evidence.native_filled_copper)
    if sorted((z.net_name, z.layer) for z in snapshot.zones) != [
        (evidence.plan.net_name, "In1.Cu"),
        (evidence.plan.net_name, "In2.Cu"),
    ]:
        raise ValueError("four-layer publication requires exactly the two declared inner planes")
    if any(
        len(z.outline_point_loops) != 1
        or len(z.outline_point_loops[0]) != 4
        or {(p.x_mm, p.y_mm) for p in z.outline_point_loops[0]} != intended
        for z in snapshot.zones
    ):
        raise ValueError("published plane geometry differs from its frozen post-route plan")
    report = retained(evidence.thermal_drc_relative_path)
    receipt = retained(evidence.thermal_receipt_relative_path)
    if receipt != report.parent / "final-fill-execution.json":
        raise ValueError("four-layer thermal receipt is not bound to its native report")
    thermal = audit_kicad_thermal_spokes(
        contacts,
        report,
        drc_report_board_sha256=snapshot.filled_board_sha256,
        project_file=board.with_suffix(".kicad_pro"),
    )
    # Always replay the execution receipt, including solid/via-only planes where
    # the thermal-specific checker has no applicable pads.
    from pcbsmith.kicad.final_fill_adapter import verify_native_fill_execution
    from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report

    verify_native_fill_execution(board, report)
    if not inspect_kicad_drc_report(report).clean:
        raise ValueError("four-layer final-fill native DRC is not clean")
    gate = _fill_gate(
        snapshot.filled_board_sha256,
        snapshot,
        contacts,
        thermal,
        declared_source_pad_ids=tuple(p for ids in policy.source_pad_ids.values() for p in ids),
        thermal_rules_sha256=thermal_rule_context(board.with_suffix(".kicad_pro")),
    )
    if gate.disposition.value != "pass":
        raise ValueError("four-layer native filled-region connectivity is not qualified")
    reference = evaluate_native_reference_continuity(
        board, policy_file, evidence.native_filled_copper
    )
    if reference != evidence.reference_evidence:
        raise ValueError("four-layer reference proof differs from exact current-input replay")
    if not reference.exact_pass_authorized or reference.signal_segment_count < 1:
        raise ValueError("four-layer reference continuity is not qualified")
