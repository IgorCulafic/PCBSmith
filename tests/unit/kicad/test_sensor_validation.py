"""Firing fixture 8: enclosure-bound thermal and humidity validation campaigns."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_sensor_bridge import (
    _bridge_declaration,
    _crossing,
    _inputs,
    _layout,
)
from tests.unit.kicad.test_sensor_isolation import _case

from pcbsmith.kicad.sensor_bridge import evaluate_sensor_bridges
from pcbsmith.kicad.sensor_isolation import evaluate_sensor_isolation_fabrication
from pcbsmith.kicad.sensor_validation import evaluate_sensor_validation
from pcbsmith.semantic_ir import (
    SemanticDisposition,
    SemanticQuantity,
    SemanticResultOutcome,
)
from pcbsmith.sensor_validation_ir import (
    SensorEnclosureRevisionContext,
    SensorValidationCampaignRecord,
    SensorValidationDeclaration,
    SensorValidationEvaluationResult,
    SensorValidationKind,
    SensorValidationRequirement,
)


def _isolation(*, humidity_required: bool = True):
    catalog, context, layout, rules = _case()
    if not humidity_required:
        validation = catalog.candidate.validation.model_copy(
            update={"humidity_requirement_id": None}
        )
        candidate = catalog.candidate.model_copy(update={"validation": validation})
        catalog = catalog.model_copy(update={"candidate": candidate})
    return evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )


def _enclosure(
    *,
    revision: str = "enclosure-r3",
    airflow: str = "airflow:still",
    orientation: str = "orientation:upright",
) -> SensorEnclosureRevisionContext:
    return SensorEnclosureRevisionContext(
        enclosure_profile_id="enclosure:fixture",
        enclosure_revision=revision,
        enclosure_geometry_fingerprint="9" * 64,
        ambient_chamber_id="chamber:fixture-23c",
        reference_instrumentation_ids=("instrument:humidity", "instrument:temperature"),
        airflow_state_id=airflow,
        mounting_orientation_id=orientation,
    )


def _requirement(
    kind: SensorValidationKind,
    *,
    target_value: float | None = None,
) -> SensorValidationRequirement:
    requirement_id = (
        "validation:sensor-thermal"
        if kind is SensorValidationKind.THERMAL
        else "validation:sensor-humidity"
    )
    value = target_value if target_value is not None else (
        0.3 if kind is SensorValidationKind.THERMAL else 2.0
    )
    unit = "degC" if kind is SensorValidationKind.THERMAL else "%RH"
    return SensorValidationRequirement(
        requirement_id=requirement_id,
        kind=kind,
        target=SemanticQuantity(
            quantity_id=f"target:{kind.value}:maximum-error",
            value=value,
            unit=unit,
            source_binding_ids=("binding:fabrication",),
        ),
        evidence_binding_ids=("binding:fabrication",),
    )


def _declaration(
    isolation,
    *,
    humidity_required: bool = True,
    enclosure: SensorEnclosureRevisionContext | None = None,
    copper=None,
    bridge=None,
) -> SensorValidationDeclaration:
    requirements = [_requirement(SensorValidationKind.THERMAL)]
    if humidity_required:
        requirements.append(_requirement(SensorValidationKind.HUMIDITY))
    return SensorValidationDeclaration(
        declaration_id="sensor-validation:fixture",
        validation_profile_id="validation-profile:fixture",
        validation_profile_revision="4",
        candidate_id=isolation.catalog.candidate.candidate_id,
        sensor_reference=isolation.catalog.candidate.sensor_reference,
        board_revision="pcb-r8",
        firmware_state_id="firmware:measurement-r2",
        radio_state_id="radio:periodic-advertising",
        load_state_id="load:nominal-display-on",
        required_enclosure=enclosure or _enclosure(),
        requirements=tuple(requirements),
        isolation_result_fingerprint=isolation.semantic_fingerprint(),
        copper_removal_result_fingerprint=(
            None if copper is None else copper.semantic_fingerprint()
        ),
        sensor_bridge_result_fingerprint=(
            None if bridge is None else bridge.semantic_fingerprint()
        ),
    )


def _campaign(
    requirement: SensorValidationRequirement,
    *,
    enclosure: SensorEnclosureRevisionContext | None = None,
    passed: bool = True,
    record_suffix: str | None = None,
    **changes,
) -> SensorValidationCampaignRecord:
    values = {
        "record_id": f"campaign:{record_suffix or requirement.kind.value}",
        "validation_profile_id": "validation-profile:fixture",
        "validation_profile_revision": "4",
        "requirement_id": requirement.requirement_id,
        "kind": requirement.kind,
        "board_revision": "pcb-r8",
        "enclosure": enclosure or _enclosure(),
        "firmware_state_id": "firmware:measurement-r2",
        "radio_state_id": "radio:periodic-advertising",
        "load_state_id": "load:nominal-display-on",
        "stabilization_time_s": 900.0,
        "sample_count": 120,
        "target": requirement.target,
        "passed": passed,
        "raw_data_sha256": ("a" if requirement.kind is SensorValidationKind.THERMAL else "b")
        * 64,
        "test_date": date(2026, 7, 16),
        "reviewer_record_id": "review:sensor-campaign",
        "reviewer_identity": "Fixture reviewer",
    }
    values.update(changes)
    return SensorValidationCampaignRecord.build(**values)


def _indexed(result):
    return {item.requirement_id: item for item in result.finding_records}


def test_absent_enclosure_and_campaigns_are_explicitly_pending() -> None:
    isolation = _isolation()
    declaration = _declaration(isolation)

    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=None,
    )

    assert result.semantic_result.outcome is SemanticResultOutcome.VALIDATION_PENDING
    assert all(
        item.disposition is SemanticDisposition.VALIDATION_PENDING
        for item in result.finding_records
    )
    assert all(
        item.mismatch_reasons == ("enclosure_context_absent",)
        for item in result.finding_records
    )
    assert result.isolation_result.metrics == isolation.metrics
    assert result.isolation_result.findings == isolation.findings


def test_nonmatching_enclosure_remains_pending_despite_matching_campaign() -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False)
    thermal = declaration.requirements[0]
    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(revision="wrong-revision"),
        campaigns=(_campaign(thermal),),
    )

    record = result.finding_records[0]
    assert record.disposition is SemanticDisposition.VALIDATION_PENDING
    assert record.mismatch_reasons == ("enclosure_context_mismatch",)
    assert record.matched_campaign_record_id is None


def test_exact_thermal_only_campaign_passes_when_humidity_is_optional() -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False)
    campaign = _campaign(declaration.requirements[0])

    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=(campaign,),
    )

    assert result.semantic_result.outcome is SemanticResultOutcome.PASSED
    assert result.finding_records[0].disposition is SemanticDisposition.PASS
    assert result.campaigns[0].sample_count == 120
    assert result.campaigns[0].stabilization_time_s == 900.0


def test_thermal_pass_does_not_substitute_for_required_humidity_campaign() -> None:
    isolation = _isolation()
    declaration = _declaration(isolation)
    thermal = next(
        item for item in declaration.requirements if item.kind is SensorValidationKind.THERMAL
    )
    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=(_campaign(thermal),),
    )
    indexed = _indexed(result)

    assert indexed["validation:sensor-thermal"].disposition is SemanticDisposition.PASS
    assert (
        indexed["validation:sensor-humidity"].disposition
        is SemanticDisposition.VALIDATION_PENDING
    )
    assert indexed["validation:sensor-humidity"].mismatch_reasons == (
        "matching_campaign_absent",
    )


def test_exact_thermal_and_humidity_campaigns_pass_without_geometry_changes() -> None:
    isolation = _isolation()
    declaration = _declaration(isolation)
    campaigns = tuple(_campaign(item) for item in declaration.requirements)
    before = isolation.model_dump_json()

    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=campaigns,
    )

    assert result.semantic_result.outcome is SemanticResultOutcome.PASSED
    assert all(item.disposition is SemanticDisposition.PASS for item in result.finding_records)
    assert isolation.model_dump_json() == before
    assert result.isolation_result.feature_evidence == isolation.feature_evidence
    assert result.isolation_result.metrics == isolation.metrics
    assert result.isolation_result.findings == isolation.findings
    assert result.separation_statement.startswith("performance validation is separate")


def test_matching_failed_campaign_fails_only_its_validation_requirement() -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False)
    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=(_campaign(declaration.requirements[0], passed=False),),
    )

    assert result.finding_records[0].disposition is SemanticDisposition.FAIL
    assert result.semantic_result.outcome is SemanticResultOutcome.VALIDATION_FAILED
    assert result.semantic_result.summary.route_acceptance_blocked is False
    assert all(item.disposition is SemanticDisposition.PASS for item in isolation.findings)


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        ({"board_revision": "pcb-wrong"}, "board_revision_mismatch"),
        ({"firmware_state_id": "firmware:wrong"}, "firmware_state_mismatch"),
        ({"radio_state_id": "radio:wrong"}, "radio_state_mismatch"),
        ({"load_state_id": "load:wrong"}, "load_state_mismatch"),
        ({"validation_profile_revision": "wrong"}, "validation_profile_mismatch"),
        (
            {"enclosure": _enclosure(revision="campaign-wrong")},
            "enclosure_context_mismatch",
        ),
    ),
)
def test_nonmatching_campaign_context_is_pending(change: dict, reason: str) -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False)
    campaign = _campaign(declaration.requirements[0], **change)

    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=(campaign,),
    )

    assert result.finding_records[0].disposition is SemanticDisposition.VALIDATION_PENDING
    assert result.finding_records[0].mismatch_reasons == (reason,)


def test_nonmatching_target_is_pending_not_geometry_failure() -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False)
    wrong_target = _requirement(SensorValidationKind.THERMAL, target_value=0.4).target
    campaign = _campaign(declaration.requirements[0], target=wrong_target)

    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=(campaign,),
    )

    assert result.finding_records[0].mismatch_reasons == ("target_mismatch",)
    assert result.semantic_result.summary.hard_failure_count == 0


def test_raw_data_hash_tamper_is_rejected_by_canonical_campaign_record() -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False)
    campaign = _campaign(declaration.requirements[0])
    payload = campaign.model_dump(mode="json")
    payload["raw_data_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="canonical record differs"):
        SensorValidationCampaignRecord.model_validate(payload)


def test_campaign_reversal_caller_isolation_and_json_roundtrip_are_exact() -> None:
    isolation = _isolation()
    declaration = _declaration(isolation)
    campaign_values = [_campaign(item) for item in declaration.requirements]
    first = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=campaign_values,
    )
    second = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=tuple(reversed(campaign_values)),
    )
    before = first.model_dump_json()
    campaign_values.clear()

    assert first == second
    assert first.model_dump_json() == before
    assert SensorValidationEvaluationResult.model_validate_json(before) == first


def test_complete_copper_and_bridge_authorities_are_retained_unchanged() -> None:
    layout = _layout(_crossing())
    netlist, isolation, copper, removal_declaration = _inputs(layout)
    bridge_declaration = _bridge_declaration(isolation, removal_declaration)
    bridge = evaluate_sensor_bridges(
        layout,
        netlist,
        isolation,
        copper,
        (bridge_declaration,),
    )
    declaration = _declaration(
        isolation,
        copper=copper,
        bridge=bridge,
    )
    campaigns = tuple(_campaign(item) for item in declaration.requirements)
    copper_before = copper.model_dump_json()
    bridge_before = bridge.model_dump_json()

    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=campaigns,
        copper_removal_result=copper,
        sensor_bridge_result=bridge,
    )

    assert result.copper_removal_result == copper
    assert result.sensor_bridge_result == bridge
    assert result.copper_removal_result.pair_evidence == copper.pair_evidence
    assert result.copper_removal_result.source_evidence == copper.source_evidence
    assert result.copper_removal_result.findings == copper.findings
    assert result.sensor_bridge_result.bridge_tracks == bridge.bridge_tracks
    assert result.sensor_bridge_result.budget_evidence == bridge.budget_evidence
    assert result.sensor_bridge_result.findings == bridge.findings
    assert copper.model_dump_json() == copper_before
    assert bridge.model_dump_json() == bridge_before


def test_upstream_fingerprint_mismatch_is_rejected_not_reported_as_pending() -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False).model_copy(
        update={"isolation_result_fingerprint": "f" * 64}
    )

    with pytest.raises(ValueError, match="another isolation result"):
        evaluate_sensor_validation(
            isolation,
            declaration,
            enclosure_context=_enclosure(),
        )


@pytest.mark.parametrize("field", ("upstream_integrity", "findings", "finding_records"))
def test_result_replay_rejects_tampered_derived_evidence(field: str) -> None:
    isolation = _isolation(humidity_required=False)
    declaration = _declaration(isolation, humidity_required=False)
    result = evaluate_sensor_validation(
        isolation,
        declaration,
        enclosure_context=_enclosure(),
        campaigns=(_campaign(declaration.requirements[0]),),
    )
    payload = result.model_dump(mode="json")
    if field == "upstream_integrity":
        payload[field]["isolation_metrics_fingerprint"] = "f" * 64
    else:
        payload[field] = []

    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        SensorValidationEvaluationResult.model_validate(payload)
