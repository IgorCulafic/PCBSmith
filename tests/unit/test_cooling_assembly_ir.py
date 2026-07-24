from decimal import Decimal

from pcbsmith.cooling_assembly_ir import (
    CoolingAssemblyProfile,
    CoolingAssemblyRequirement,
    CoolingCandidateRegister,
    CoolingCandidateStatus,
    CoolingInterface,
    CoolingPart,
    CoolingPartCandidate,
    CoolingPartRole,
    CoolingSelectionState,
    evaluate_cooling_assembly,
    evaluate_cooling_candidates,
)
from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge


def _point(quantity_id: str, unit: str, value: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal(value),
        nominal=Decimal(value),
        upper=Decimal(value),
        evidence_binding_ids=(f"evidence:{quantity_id}",),
    )


def _unknown(quantity_id: str, unit: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale=f"{quantity_id} is missing.",
    )


def _profile(*, complete: bool) -> CoolingAssemblyProfile:
    tim = CoolingPart(
        part_id="tim",
        role=CoolingPartRole.TIM,
        selection_state=(
            CoolingSelectionState.EXACT_SELECTED
            if complete
            else CoolingSelectionState.GEOMETRY_PROXY
        ),
        manufacturer="Example" if complete else None,
        mpn="TIM-1" if complete else None,
        occurrence_ids=("TIM1",),
        properties=(_point("thickness", "mm", "0.3") if complete else _unknown("thickness", "mm"),),
        source_binding_ids=("source:tim",),
    )
    sink = CoolingPart(
        part_id="sink",
        role=CoolingPartRole.HEATSINK,
        selection_state=CoolingSelectionState.EXACT_SELECTED,
        manufacturer="Example",
        mpn="HS-1",
        occurrence_ids=("HS1",),
        properties=(_point("sink_to_ambient_rth", "K/W", "4"),),
        source_binding_ids=("source:sink",),
    )
    interface = CoolingInterface(
        interface_id="tim-to-sink",
        part_a_id="tim",
        part_b_id="sink",
        contact_area=_point("contact_area", "mm^2", "100"),
        thermal_resistance=(
            _point("interface_rth", "K/W", "1") if complete else _unknown("interface_rth", "K/W")
        ),
        clamp_force=_point("clamp_force", "N", "20"),
        requires_electrical_isolation=True,
        isolation_withstand=(
            _point("isolation_withstand", "V", "500")
            if complete
            else _unknown("isolation_withstand", "V")
        ),
        surface_potential_ids=("switch-node",),
        source_binding_ids=("source:assembly",),
    )
    return CoolingAssemblyProfile(
        profile_id="cooling:test",
        revision="1",
        geometry_authority_sha256="a" * 64,
        parts=(tim, sink),
        interfaces=(interface,),
        source_context_ids=("source:assembly",),
    )


def _requirements() -> tuple[CoolingAssemblyRequirement, ...]:
    accepted = (
        CoolingSelectionState.EXACT_SELECTED,
        CoolingSelectionState.QUALIFIED_ALTERNATE,
    )
    return (
        CoolingAssemblyRequirement(
            requirement_id="tim-selected",
            role=CoolingPartRole.TIM,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=("thickness",),
            rationale="TIM thickness affects interface resistance and isolation.",
        ),
        CoolingAssemblyRequirement(
            requirement_id="sink-selected",
            role=CoolingPartRole.HEATSINK,
            minimum_parts=1,
            accepted_selection_states=accepted,
            required_property_ids=("sink_to_ambient_rth",),
            rationale="The airflow-specific sink rating is required.",
        ),
    )


def test_complete_selected_assembly_passes() -> None:
    result = evaluate_cooling_assembly(_profile(complete=True), _requirements())
    assert result.disposition == "complete"
    assert result.unsatisfied_requirement_ids == ()
    assert result.incomplete_interface_ids == ()


def test_geometry_proxy_and_unknown_interface_fail_closed() -> None:
    result = evaluate_cooling_assembly(_profile(complete=False), _requirements())
    assert result.disposition == "incomplete"
    assert result.unsatisfied_requirement_ids == ("tim-selected",)
    assert result.incomplete_interface_ids == ("tim-to-sink",)
    assert any("geometry_proxy" in finding for finding in result.findings)


def _candidate(
    candidate_id: str,
    roles: tuple[CoolingPartRole, ...],
    status: CoolingCandidateStatus,
) -> CoolingPartCandidate:
    return CoolingPartCandidate(
        candidate_id=candidate_id,
        roles=roles,
        manufacturer="Example",
        ordering_identity=f"MPN-{candidate_id}",
        configuration="Catalog configuration requiring assembly review.",
        status=status,
        properties=(_point("catalog_property", "mm", "1"),),
        source_binding_ids=(f"source:{candidate_id}",),
        applicability_notes=("Candidate status is not selection authority.",),
    )


def test_candidate_register_reports_uncovered_roles_without_promoting_parts() -> None:
    register = CoolingCandidateRegister(
        register_id="cooling-candidates:test",
        revision="1",
        candidates=(
            _candidate(
                "tim",
                (CoolingPartRole.TIM, CoolingPartRole.INSULATING_HARDWARE),
                CoolingCandidateStatus.VENDOR_CONFIRMATION_REQUIRED,
            ),
            _candidate(
                "sink",
                (CoolingPartRole.HEATSINK,),
                CoolingCandidateStatus.SYSTEM_VALIDATION_REQUIRED,
            ),
        ),
        source_context_ids=("source:test",),
    )
    result = evaluate_cooling_candidates(
        register,
        (
            CoolingPartRole.TIM,
            CoolingPartRole.HEATSINK,
            CoolingPartRole.AIR_MOVER,
        ),
    )
    assert result.disposition == "incomplete"
    assert result.uncovered_role_ids == (CoolingPartRole.AIR_MOVER,)
    assert result.blocked_candidate_ids == ("sink", "tim")
    assert "does not satisfy" in result.findings[0]


def test_rejected_candidate_does_not_cover_a_role() -> None:
    register = CoolingCandidateRegister(
        register_id="cooling-candidates:rejected",
        revision="1",
        candidates=(
            _candidate(
                "rejected-fan",
                (CoolingPartRole.AIR_MOVER,),
                CoolingCandidateStatus.REJECTED,
            ),
        ),
        source_context_ids=("source:test",),
    )
    result = evaluate_cooling_candidates(register, (CoolingPartRole.AIR_MOVER,))
    assert result.disposition == "incomplete"
    assert result.covered_role_ids == ()
    assert result.uncovered_role_ids == (CoolingPartRole.AIR_MOVER,)
