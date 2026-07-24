from decimal import Decimal

from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge
from pcbsmith.protection_coordination_ir import (
    ProtectionCoordinationProfile,
    ProtectionEventKind,
    ProtectionPath,
    ProtectionRequirement,
    evaluate_protection_coordination,
)


def _known(quantity_id: str, unit: str, value: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.DESIGN_TARGET,
        lower=Decimal(value),
        nominal=Decimal(value),
        upper=Decimal(value),
        evidence_binding_ids=("policy:test",),
    )


def _unknown(quantity_id: str, unit: str) -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id=quantity_id,
        unit=unit,
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Missing test input.",
    )


def _path(*, unresolved: bool) -> ProtectionPath:
    return ProtectionPath(
        path_id="path:ocp",
        event_kinds=(ProtectionEventKind.PHASE_SHORT,),
        detector_ids=("driver-vds-ocp",),
        action_ids=("gate-soft-shutdown",),
        independent_domain_id="gate-driver-hardware",
        detection_threshold=(
            _unknown("threshold", "V") if unresolved else _known("threshold", "V", "0.5")
        ),
        detection_latency=(
            _unknown("detect", "s") if unresolved else _known("detect", "s", "0.000001")
        ),
        shutdown_latency=(
            _unknown("shutdown", "s") if unresolved else _known("shutdown", "s", "0.000001")
        ),
        residual_energy=(_unknown("energy", "J") if unresolved else _known("energy", "J", "0.01")),
        source_binding_ids=("source:driver",),
        notes=("Test path.",),
    )


def _requirement() -> ProtectionRequirement:
    return ProtectionRequirement(
        requirement_id="requirement:phase-short",
        event_kind=ProtectionEventKind.PHASE_SHORT,
        required_independent_domain_count=1,
        required_action_ids=("gate-soft-shutdown",),
        maximum_total_latency=_known("max-latency", "s", "0.00001"),
        maximum_residual_energy=_known("max-energy", "J", "0.1"),
        source_binding_ids=("policy:test",),
    )


def test_unresolved_path_inputs_fail_closed() -> None:
    report = evaluate_protection_coordination(
        ProtectionCoordinationProfile(
            profile_id="protection:test",
            revision="1",
            paths=(_path(unresolved=True),),
            requirements=(_requirement(),),
            source_context_ids=("source:driver",),
        )
    )
    assert report.disposition == "incomplete"
    assert "detect" in report.evaluations[0].missing_input_ids


def test_bounded_path_with_required_action_and_domain_is_covered() -> None:
    report = evaluate_protection_coordination(
        ProtectionCoordinationProfile(
            profile_id="protection:test",
            revision="1",
            paths=(_path(unresolved=False),),
            requirements=(_requirement(),),
            source_context_ids=("source:driver",),
        )
    )
    assert report.disposition == "complete"
    assert report.evaluations[0].disposition == "covered"


def test_known_path_that_exceeds_latency_limit_is_incomplete() -> None:
    slow = _path(unresolved=False).model_copy(
        update={"detection_latency": _known("detect-slow", "s", "0.001")}
    )
    report = evaluate_protection_coordination(
        ProtectionCoordinationProfile(
            profile_id="protection:test",
            revision="1",
            paths=(slow,),
            requirements=(_requirement(),),
            source_context_ids=("source:driver",),
        )
    )
    assert report.disposition == "incomplete"
    assert any("exceeds the latency limit" in finding for finding in report.evaluations[0].findings)
