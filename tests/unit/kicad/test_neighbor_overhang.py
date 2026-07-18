"""R6.5 package/class-specific neighbor-overhang firing fixtures 9-10."""

from __future__ import annotations

from dataclasses import asdict

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.neighbor_overhang import evaluate_neighbor_overhang
from pcbsmith.neighbor_overhang_ir import (
    ActiveElectricalClearance,
    BoardCoordinateNeighborGeometry,
    NeighborAuthorityReview,
    NeighborGeometryRole,
    NeighborOverhangDeclaration,
    NeighborOverhangRequirement,
    NeighborOverhangResult,
    NeighborRuleVerdict,
    NeighborToleranceModel,
    OverhangDirection,
    PackageGeometryKind,
    fingerprint,
    neighbor_full_context_fingerprint,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticVerification,
)

SHA = "a" * 64
COMPONENT = BoardComponent(
    reference="U1", value="PKG", footprint="Test:ExactPackage", uuid_path="/U1"
)
NEIGHBOR = BoardComponent(
    reference="U2", value="NEIGHBOR", footprint="Test:ExactPackage", uuid_path="/U2"
)
NETLIST = BoardNetlist(components=(COMPONENT, NEIGHBOR), nets=())
LAYOUT = BoardLayout(
    placements=((COMPONENT, 5.0), (NEIGHBOR, 6.0)),
    segments=(),
    vias=(),
    width_mm=10.0,
    height_mm=10.0,
)


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),
        )
    )


def _binding(
    binding_id: str, claim_id: str, object_fingerprint: str
) -> EvidenceApplicabilityBinding:
    condition = f"condition:{binding_id}"
    return EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=(
            EvidenceRef(
                kind="reviewed-source",
                title=claim_id,
                locator=f"figure:{binding_id}",
                source_id=f"source:{binding_id}",
                local_sha256=SHA,
                source_status="pinned",
                locator_status="figure_bound",
                applicability_status="confirmed",
                required_conditions=(condition,),
            ),
        ),
        claim_id=claim_id,
        applicability_record_id=f"applicability:{binding_id}",
        required_conditions=(condition,),
        matched_conditions=(condition,),
        unmatched_conditions=(),
        excluded_conditions=(),
        geometry_source_fingerprint=object_fingerprint,
        reviewer_record_id="reviewer-record:neighbor",
    )


def _declaration(
    *,
    selected_class: str | None = "class-a",
    rule_class: str = "class-a",
    package_kind: PackageGeometryKind = PackageGeometryKind.CHIP,
    rule_kind: PackageGeometryKind | None = None,
    adjacent_start_um: int = 3250,
    maximum_overhang_um: int = 150,
    geometry_state: str = "exact",
    authority: SemanticAuthorityClass = SemanticAuthorityClass.HARD_GEOMETRY,
    reverse_order: bool = False,
) -> NeighborOverhangDeclaration:
    layout_json = canonical_board_layout_snapshot_json(LAYOUT)
    netlist_json = canonical_board_netlist_snapshot_json(NETLIST)
    layout_fp = board_layout_snapshot_fingerprint(layout_json)
    netlist_fp = board_netlist_snapshot_fingerprint(netlist_json)

    def geometry(
        geometry_id: str,
        role: NeighborGeometryRole,
        compound: ExactPlanarCompound | None,
        *,
        component_reference: str = "U1",
    ) -> BoardCoordinateNeighborGeometry:
        return BoardCoordinateNeighborGeometry(
            geometry_id=geometry_id,
            source_geometry_id=f"kicad-source:{geometry_id}",
            role=role,
            component_reference=component_reference,
            layer="F.Cu",
            board_layout_snapshot_fingerprint=layout_fp,
            board_netlist_snapshot_fingerprint=netlist_fp,
            verification=(
                SemanticVerification.EXACT
                if compound is not None
                else SemanticVerification.UNSUPPORTED
            ),
            compound=compound,
            source_binding_ids=(f"binding:{geometry_id}",),
        )

    pad = geometry("pad:1", NeighborGeometryRole.PAD, _rect(2.1, 1.0, 2.9, 2.0))
    terminal = geometry("terminal:1", NeighborGeometryRole.TERMINAL, _rect(2.0, 1.2, 3.0, 1.8))
    adjacent = geometry(
        "copper:adjacent",
        NeighborGeometryRole.ADJACENT_COPPER,
        (
            None
            if geometry_state == "unsupported"
            else _rect(adjacent_start_um / 1000, 1.2, adjacent_start_um / 1000 + 0.5, 1.8)
        ),
        component_reference="U2",
    )
    geometries = (pad, terminal) if geometry_state == "missing" else (pad, terminal, adjacent)
    tolerance = NeighborToleranceModel(
        tolerance_model_id="tolerance:place-fab",
        placement_tolerance_um=30,
        fabrication_tolerance_um=20,
        board_layout_snapshot_fingerprint=layout_fp,
        board_netlist_snapshot_fingerprint=netlist_fp,
        source_binding_ids=("binding:tolerance",),
    )
    clearance = ActiveElectricalClearance(
        clearance_id="clearance:active",
        clearance_um=200,
        clearance_domain_id="domain:net-class",
        board_layout_snapshot_fingerprint=layout_fp,
        board_netlist_snapshot_fingerprint=netlist_fp,
        source_binding_ids=("binding:clearance",),
    )
    preliminary = NeighborOverhangRequirement(
        requirement_id="rule:neighbor",
        acceptance_class=rule_class,
        package_geometry_kind=rule_kind or package_kind,
        package_identity="package:exact-revision",
        component_reference="U1",
        allowed_overhang_direction=OverhangDirection.X_POSITIVE,
        maximum_terminal_overhang_um=maximum_overhang_um,
        maximum_terminal_overhang_fraction_numerator=1,
        maximum_terminal_overhang_fraction_denominator=2,
        minimum_post_tolerance_copper_gap_um=200,
        tolerance_model_id=tolerance.tolerance_model_id,
        clearance_id=clearance.clearance_id,
        authority=authority,
        review=None,
        source_binding_ids=("binding:rule",),
    )
    review = None
    if authority in {
        SemanticAuthorityClass.HARD_GEOMETRY,
        SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
    }:
        review = NeighborAuthorityReview(
            review_id="review:neighbor",
            reviewer_record_id="reviewer-record:neighbor",
            reviewer_identity="assembler-reviewer:1",
            status="active",
            full_context_fingerprint=neighbor_full_context_fingerprint(
                board_layout_snapshot_fingerprint_value=layout_fp,
                board_netlist_snapshot_fingerprint_value=netlist_fp,
                component_fingerprint=fingerprint(asdict(COMPONENT)),
                package_geometry_kind=package_kind,
                package_identity="package:exact-revision",
                acceptance_class=rule_class,
                geometries=geometries,
                tolerance=tolerance,
                clearance=clearance,
                requirement=preliminary,
            ),
            source_binding_ids=("binding:review",),
        )
    rule = preliminary.model_copy(update={"review": review})
    bound_objects = [
        *((item, item.geometry_id, item.source_binding_ids[0]) for item in geometries),
        (tolerance, tolerance.tolerance_model_id, "binding:tolerance"),
        (clearance, clearance.clearance_id, "binding:clearance"),
        (rule, rule.requirement_id, "binding:rule"),
    ]
    if review is not None:
        bound_objects.append((review, review.review_id, "binding:review"))
    bindings = tuple(
        _binding(binding_id, claim_id, item.semantic_fingerprint())
        for item, claim_id, binding_id in bound_objects
    )
    if reverse_order:
        geometries = tuple(reversed(geometries))
        bindings = tuple(reversed(bindings))
    return NeighborOverhangDeclaration(
        declaration_id="declaration:neighbor",
        board_layout_snapshot_json=layout_json,
        board_netlist_snapshot_json=netlist_json,
        board_layout_snapshot_fingerprint=layout_fp,
        board_netlist_snapshot_fingerprint=netlist_fp,
        component_reference="U1",
        package_geometry_kind=package_kind,
        package_identity="package:exact-revision",
        selected_acceptance_class=selected_class,
        geometries=geometries,
        tolerance_models=(tolerance,),
        clearances=(clearance,),
        requirements=(rule,),
        evidence_bindings=bindings,
    )


def test_exact_equality_passes_and_one_integer_quantum_less_gap_fails() -> None:
    equality = evaluate_neighbor_overhang(LAYOUT, NETLIST, _declaration(adjacent_start_um=3250))
    assert equality.overhang_finding.measured_terminal_overhang_um == 100
    assert equality.overhang_finding.terminal_span_um == 1000
    assert equality.overhang_finding.pad_span_um == 800
    assert equality.overhang_finding.fraction_reference_span_um == 800
    assert equality.overhang_finding.total_tolerance_deduction_um == 50
    assert equality.overhang_finding.worst_case_terminal_overhang_um == 150
    assert equality.overhang_finding.verdict is NeighborRuleVerdict.PASS
    assert equality.copper_gap_finding.witness is not None
    assert equality.copper_gap_finding.witness.squared_distance_um2_numerator == 250**2
    assert equality.copper_gap_finding.post_tolerance_gap is not None
    assert equality.copper_gap_finding.post_tolerance_gap.exact_post_tolerance_gap_um == 200
    assert equality.copper_gap_finding.verdict is NeighborRuleVerdict.PASS

    one_less = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(adjacent_start_um=3249)
    )
    assert one_less.copper_gap_finding.post_tolerance_gap is not None
    assert one_less.copper_gap_finding.post_tolerance_gap.exact_post_tolerance_gap_um == 199
    assert one_less.copper_gap_finding.verdict is NeighborRuleVerdict.FAIL
    assert one_less.copper_gap_finding.disposition is SemanticDisposition.FAIL
    assert one_less.overhang_finding.disposition is SemanticDisposition.PASS


def test_selected_acceptance_class_changes_expected_result() -> None:
    class_a = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(rule_class="class-a", maximum_overhang_um=150)
    )
    class_b = evaluate_neighbor_overhang(
        LAYOUT,
        NETLIST,
        _declaration(
            selected_class="class-b", rule_class="class-b", maximum_overhang_um=149
        ),
    )
    assert class_a.overhang_finding.disposition is SemanticDisposition.PASS
    assert class_b.overhang_finding.disposition is SemanticDisposition.FAIL


@pytest.mark.parametrize("kind", tuple(PackageGeometryKind))
def test_chip_melf_gull_wing_and_other_are_distinct_not_aliases(
    kind: PackageGeometryKind,
) -> None:
    other_kind = next(item for item in PackageGeometryKind if item is not kind)
    exact = evaluate_neighbor_overhang(LAYOUT, NETLIST, _declaration(package_kind=kind))
    mismatch = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(package_kind=kind, rule_kind=other_kind)
    )
    assert exact.overhang_finding.disposition is SemanticDisposition.PASS
    assert mismatch.overhang_finding.disposition is SemanticDisposition.UNVERIFIED
    assert "applicable_package_class_rule_missing_or_ambiguous" in (
        mismatch.overhang_finding.reason_ids
    )


@pytest.mark.parametrize("geometry_state", ("unsupported", "missing"))
def test_unsupported_or_missing_geometry_is_unverified(geometry_state: str) -> None:
    result = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(geometry_state=geometry_state)
    )
    assert result.overhang_finding.disposition is SemanticDisposition.UNVERIFIED
    assert result.copper_gap_finding.disposition is SemanticDisposition.UNVERIFIED
    assert result.copper_gap_finding.verdict is NeighborRuleVerdict.PROCESS_REVIEW_REQUIRED


def test_terminal_adjacent_copper_overlap_is_an_exact_gap_failure() -> None:
    result = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(adjacent_start_um=2900)
    )
    assert result.copper_gap_finding.witness is not None
    assert result.copper_gap_finding.witness.relation == "interior_overlap"
    assert result.copper_gap_finding.post_tolerance_gap is not None
    assert result.copper_gap_finding.post_tolerance_gap.exact_post_tolerance_gap_um == -50
    assert result.copper_gap_finding.disposition is SemanticDisposition.FAIL
    assert result.copper_gap_finding.verdict is NeighborRuleVerdict.FAIL


def test_missing_acceptance_class_or_rule_is_process_review_required() -> None:
    missing_class = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(selected_class=None)
    )
    missing_rule = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(selected_class="class-z")
    )
    assert missing_class.overhang_finding.verdict is NeighborRuleVerdict.PROCESS_REVIEW_REQUIRED
    assert missing_class.copper_gap_finding.witness is not None
    assert missing_class.copper_gap_finding.witness.squared_distance_um2_numerator == 250**2
    assert missing_rule.copper_gap_finding.disposition is SemanticDisposition.UNVERIFIED


def test_advisory_rule_never_hard_fails() -> None:
    result = evaluate_neighbor_overhang(
        LAYOUT,
        NETLIST,
        _declaration(
            adjacent_start_um=3249,
            maximum_overhang_um=149,
            authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        ),
    )
    assert result.overhang_finding.disposition is SemanticDisposition.ADVISORY
    assert result.copper_gap_finding.disposition is SemanticDisposition.ADVISORY
    assert result.overhang_finding.verdict is NeighborRuleVerdict.PROCESS_REVIEW_REQUIRED
    assert result.copper_gap_finding.verdict is NeighborRuleVerdict.PROCESS_REVIEW_REQUIRED


def test_reviewer_backed_hard_geometry_authority_can_decide_exact_geometry() -> None:
    result = evaluate_neighbor_overhang(
        LAYOUT,
        NETLIST,
        _declaration(authority=SemanticAuthorityClass.HARD_GEOMETRY),
    )
    assert result.overhang_finding.disposition is SemanticDisposition.PASS
    assert result.copper_gap_finding.disposition is SemanticDisposition.PASS


def test_process_authority_without_a_qualified_process_record_cannot_decide() -> None:
    result = evaluate_neighbor_overhang(
        LAYOUT,
        NETLIST,
        _declaration(authority=SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT),
    )
    assert result.overhang_finding.disposition is SemanticDisposition.UNVERIFIED
    assert "qualified_process_record_missing" in result.overhang_finding.reason_ids


def test_source_snapshot_and_full_context_tamper_are_rejected_or_unverified() -> None:
    declaration = _declaration()
    changed_layout = LAYOUT.__class__(
        **{**LAYOUT.__dict__, "width_mm": 10.001}
    )
    with pytest.raises(ValueError, match="caller BoardLayout"):
        evaluate_neighbor_overhang(changed_layout, NETLIST, declaration)

    binding = declaration.evidence_bindings[0]
    stale_binding = binding.model_copy(update={"geometry_source_fingerprint": "b" * 64})
    source_tampered = declaration.model_copy(
        update={"evidence_bindings": (stale_binding, *declaration.evidence_bindings[1:])}
    )
    source_result = evaluate_neighbor_overhang(LAYOUT, NETLIST, source_tampered)
    assert source_result.overhang_finding.disposition is SemanticDisposition.UNVERIFIED
    assert any(
        reason.startswith("unconfirmed_object_binding:")
        for reason in source_result.overhang_finding.reason_ids
    )

    other_reviewer = binding.model_copy(update={"reviewer_record_id": "reviewer:other"})
    reviewer_tampered = declaration.model_copy(
        update={"evidence_bindings": (other_reviewer, *declaration.evidence_bindings[1:])}
    )
    reviewer_result = evaluate_neighbor_overhang(LAYOUT, NETLIST, reviewer_tampered)
    assert reviewer_result.overhang_finding.disposition is SemanticDisposition.UNVERIFIED

    rule = declaration.requirements[0]
    assert rule.review is not None
    stale_review = rule.review.model_copy(update={"full_context_fingerprint": "b" * 64})
    stale_rule = rule.model_copy(update={"review": stale_review})
    context_tampered = declaration.model_copy(update={"requirements": (stale_rule,)})
    context_result = evaluate_neighbor_overhang(LAYOUT, NETLIST, context_tampered)
    assert "review_full_context_mismatch" in context_result.overhang_finding.reason_ids


def test_replay_order_immutability_and_result_tamper_rejection() -> None:
    forward = evaluate_neighbor_overhang(LAYOUT, NETLIST, _declaration())
    reversed_result = evaluate_neighbor_overhang(
        LAYOUT, NETLIST, _declaration(reverse_order=True)
    )
    assert (
        forward.declaration.semantic_fingerprint()
        == reversed_result.declaration.semantic_fingerprint()
    )
    assert forward.result_fingerprint == reversed_result.result_fingerprint
    assert NeighborOverhangResult.model_validate_json(forward.model_dump_json()) == forward
    with pytest.raises(ValidationError):
        forward.declaration.selected_acceptance_class = "class-z"  # type: ignore[misc]
    payload = forward.model_dump(mode="json")
    payload["copper_gap_finding"]["disposition"] = "fail"
    with pytest.raises(ValidationError, match="stale copper_gap_finding"):
        NeighborOverhangResult.model_validate(payload)


def test_geometry_rejects_non_integer_micrometre_coordinates() -> None:
    declaration = _declaration()
    geometry = declaration.geometries[0]
    with pytest.raises(ValidationError, match="integer micrometres"):
        BoardCoordinateNeighborGeometry(
            **{
                **geometry.model_dump(),
                "compound": _rect(2.0001, 1.0, 2.9, 2.0),
            }
        )
