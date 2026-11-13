"""Declarative inner-plane stage after a completed external route, before native validation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.final_fill_adapter import KiCadFinalFillSnapshot
from pcbsmith.kicad.native_reference_continuity import NativeReferencePolicy
from pcbsmith.kicad.reference_continuity import ReferenceContinuityEvidence
from pcbsmith.kicad.routing_candidate_adapter import native_layout_route_deltas
from pcbsmith.routed_copper_graph_ir import NativeFilledCopperInput
from pcbsmith.routing_ir import (
    PartialCandidateStatus,
    RouteCandidateResult,
    RouteRequest,
    validate_route_candidate_result,
)
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.whole_board_qualification import QualificationGate


def verify_post_route_planes(
    board: Path,
    native: Path,
    snapshot: KiCadFinalFillSnapshot,
    plan: PostRoutePlanePlan,
    output: Path,
) -> tuple[NativeFilledCopperInput, QualificationGate, ReferenceContinuityEvidence]:
    """Run source-bound native plane checks; retain rejected results as well as passes."""
    from pcbsmith.kicad.cli import find_kicad_cli
    from pcbsmith.kicad.final_fill_connectivity import observe_final_fill_contacts
    from pcbsmith.kicad.final_fill_thermal import audit_kicad_thermal_spokes, thermal_rule_context
    from pcbsmith.kicad.native_fill_graph import read_native_fill, retain_native_fill
    from pcbsmith.kicad.native_reference_continuity import evaluate_native_reference_continuity
    from pcbsmith.whole_board_qualification_adapter import _fill_gate

    if board.read_bytes() != native.read_bytes():
        raise ValueError("post-route plane verification requires byte-stable native fill")
    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("native plane verification requires installed KiCad")
    observation = observe_final_fill_contacts(
        board,
        output / "plane-contacts.json",
        kicad_python=install.path.parent / "python.exe",
    )
    evidence = retain_native_fill(board, snapshot, observation)
    read_native_fill(evidence)
    thermal = audit_kicad_thermal_spokes(
        observation,
        native.parent / "fill-drc.json",
        drc_report_board_sha256=snapshot.filled_board_sha256,
        project_file=board.with_suffix(".kicad_pro"),
    )
    gate = _fill_gate(
        snapshot.filled_board_sha256,
        snapshot,
        observation,
        thermal,
        declared_source_pad_ids=tuple(
            p for ids in plan.reference_policy.source_pad_ids.values() for p in ids
        ),
        thermal_rules_sha256=thermal_rule_context(board.with_suffix(".kicad_pro")),
    )
    policy = output / "reference-policy.json"
    policy.write_text(plan.reference_policy.model_dump_json(indent=2), encoding="utf-8")
    for name, result in (
        ("plane-evidence", evidence),
        ("plane-thermal", thermal),
        ("plane-fill-gate", gate),
    ):
        (output / f"{name}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    reference = evaluate_native_reference_continuity(board, policy, evidence)
    (output / "plane-reference.json").write_text(
        reference.model_dump_json(indent=2), encoding="utf-8"
    )
    return evidence, gate, reference


class PostRoutePlanePlan(SemanticIrModel):
    schema_id: Literal["pcbsmith-post-route-inner-planes-v1"]
    net_name: str = Field(min_length=1)
    edge_inset_mm: float = Field(ge=0.5)
    reference_policy: NativeReferencePolicy
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def plane_reference_agrees(self) -> Self:
        if set(self.reference_policy.source_pad_ids) != {self.net_name}:
            raise ValueError("post-route planes must use their declared reference net")
        return self

    def zones(
        self,
        layout: BoardLayout,
        request: RouteRequest,
    ) -> tuple[tuple[str, str, tuple[float, float, float, float]], ...]:
        if set(request.allowed_layers) != {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}:
            raise ValueError("post-route inner planes require four ordered copper layers")
        if self.net_name not in {n.net_name for d in request.target_domains for n in d.nets}:
            raise ValueError("post-route plane net is absent from the routed request")
        if any(
            self.net_name in rule.net_names and not {"In1.Cu", "In2.Cu"} <= set(rule.allowed_layers)
            for rule in request.net_layer_constraints
        ):
            raise ValueError("post-route planes conflict with the declared net layer constraint")
        inset = self.edge_inset_mm
        if 2 * inset >= min(layout.width_mm, layout.height_mm):
            raise ValueError("post-route plane inset leaves no area")
        return tuple(
            (
                self.net_name,
                layer,
                (inset, inset, layout.width_mm - inset, layout.height_mm - inset),
            )
            for layer in ("In1.Cu", "In2.Cu")
        )


def append_post_route_planes(
    request: RouteRequest,
    candidate: RouteCandidateResult,
    source: BoardLayout,
    plan: PostRoutePlanePlan,
) -> RouteCandidateResult:
    """Preserve the exact external route; only append source-bound zone intent.

    This does not claim fill or engineering acceptance. The shared candidate
    transaction must natively fill, check and atomically validate these zones.
    """
    from pcbsmith.kicad.routing_candidate_transaction import apply_declared_route_deltas

    validate_route_candidate_result(request, candidate)
    if candidate.partial_status is not PartialCandidateStatus.COMPLETE:
        return candidate
    if source.zones or candidate.zone_deltas:
        raise ValueError("post-route plane creation requires a zone-free initial placement")
    routed = apply_declared_route_deltas(request=request, candidate=candidate, source_layout=source)
    final = replace(routed, zones=plan.zones(routed, request))
    segments, vias, zones = native_layout_route_deltas(
        request=request,
        source_layout=source,
        final_layout=final,
    )
    if (
        tuple(sorted(segments, key=lambda d: d.mutation_id)) != candidate.segment_deltas
        or tuple(sorted(vias, key=lambda d: d.mutation_id)) != candidate.via_deltas
    ):
        raise ValueError("post-route plane stage changed external tracks or vias")
    values = candidate.model_dump()
    values["zone_deltas"] = zones
    values["engine"]["adapter_id"] = "pcbsmith.production_routing.freerouting_with_native_planes"
    values["engine"]["adapter_version"] = "1"
    result = RouteCandidateResult.model_validate(values)
    validate_route_candidate_result(request, result)
    return result
