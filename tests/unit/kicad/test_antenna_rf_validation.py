"""Firing fixture 8 for record-only antenna RF validation authority."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_antenna_enclosure as enclosure_fixture

from pcbsmith.antenna_enclosure_ir import ExactDecimalInterval
from pcbsmith.antenna_rf_validation_ir import (
    AntennaRfCampaignContext,
    AntennaRfCampaignRecord,
    AntennaRfCampaignRequirement,
    AntennaRfMeasuredMetric,
    AntennaRfMetricEvidence,
    AntennaRfMetricRequirement,
    AntennaRfValidationResult,
    canonical_json,
    canonical_rf_raw_result_json,
    fingerprint,
    rf_requirement_binding_fingerprint,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.antenna_enclosure import evaluate_antenna_enclosure_exclusion
from pcbsmith.kicad.antenna_rf_validation import evaluate_antenna_rf_validation
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticResultOutcome,
)

VALIDATION_SOURCE_SHA = "d" * 64
BOARD_SHA = "e" * 64
FIRMWARE_SHA = "f" * 64
SETUP_SHA = "1" * 64
ENVIRONMENT_SHA = "2" * 64


def _enclosure_result(*, state: str = "pass", include_nonapplicable: bool = False):
    placement = enclosure_fixture._placement()
    declaration = enclosure_fixture._declaration(placement)
    if state == "pending":
        return evaluate_antenna_enclosure_exclusion(placement, declaration, None)
    if state == "fail":
        wall_xy = enclosure_fixture._rect(-0.5, -0.5, 0.5, 0.5)
    else:
        wall_xy = enclosure_fixture._rect(16.0, -1.0, 17.0, 1.0)
    interval = ExactDecimalInterval(lower_mm="0", upper_mm="1")
    objects = [enclosure_fixture._object(xy=wall_xy, z=interval)]
    if include_nonapplicable:
        objects.append(
            enclosure_fixture._object(
                object_id="object:glass-window",
                material="glass",
                xy=enclosure_fixture._rect(-0.5, -0.5, 0.5, 0.5),
                z=interval,
            )
        )
    return evaluate_antenna_enclosure_exclusion(
        placement, declaration, enclosure_fixture._profile(tuple(objects))
    )


def _context(enclosure) -> AntennaRfCampaignContext:
    placement = enclosure.placement_result
    antenna = placement.declaration
    config = canonical_json(
        {
            "antenna_height_mm": "1200",
            "orientation": "co-polarized",
            "packet_count": 1000,
        }
    )
    return AntennaRfCampaignContext(
        antenna_id=antenna.antenna_id,
        module_reference=antenna.module_reference,
        selected_footprint_library_id=antenna.selected_footprint_library_id,
        component_uuid_path=antenna.component_uuid_path,
        component_revision=antenna.component_revision,
        module_source_sha256=antenna.source_file_sha256,
        placement_result_fingerprint=placement.result_fingerprint,
        anchor_x_mm=str(placement.transform.anchor_x_mm),
        anchor_y_mm=str(placement.transform.anchor_y_mm),
        rotation_deg=str(placement.transform.rotation_deg),
        side=placement.transform.side,
        board_layout_snapshot_fingerprint=placement.board_layout_snapshot_fingerprint,
        board_revision="board-revision:8",
        board_artifact_sha256=BOARD_SHA,
        enclosure_profile_id=enclosure.declaration.enclosure_profile_id,
        enclosure_id=enclosure.declaration.enclosure_id,
        enclosure_revision=enclosure.declaration.enclosure_revision,
        enclosure_model_sha256=enclosure.declaration.model_sha256,
        firmware_artifact_id="firmware:rf-fixture",
        firmware_version="8.2.1",
        firmware_sha256=FIRMWARE_SHA,
        radio_mode="802.15.4-oqpsk",
        band_id="2.4GHz",
        channel_id="channel:20",
        counterpart_id="counterpart:golden-node",
        counterpart_revision="counterpart-revision:3",
        range_id="range:anechoic-a",
        range_revision="range-revision:5",
        setup_id="setup:rf-link-budget-8",
        setup_artifact_sha256=SETUP_SHA,
        setup_config_json=config,
        setup_config_sha256=fingerprint(json.loads(config)),
        environment_profile_id="environment:23C-50RH",
        environment_profile_sha256=ENVIRONMENT_SHA,
    )


def _metrics() -> tuple[AntennaRfMetricRequirement, ...]:
    return (
        AntennaRfMetricRequirement(
            metric_id="metric:packet-error-rate",
            unit="percent",
            comparator="less_or_equal",
            target="1.0",
        ),
        AntennaRfMetricRequirement(
            metric_id="metric:rssi",
            unit="dBm",
            comparator="greater_or_equal",
            target="-70.0",
        ),
    )


def _binding(geometry_fp: str) -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id="binding:rf-campaign-requirement",
        evidence=(
            EvidenceRef(
                kind="validation_plan",
                title="Fixture reviewed RF campaign plan",
                locator="section:link-budget-acceptance",
                source_id="source:rf-validation-plan",
                organization_or_author="Fixture RF Laboratory",
                revision="8",
                local_sha256=VALIDATION_SOURCE_SHA,
                source_status="pinned",
                locator_status="text_verified",
                applicability_status="confirmed",
                required_conditions=("module-revision=7", "setup-revision=8"),
            ),
        ),
        claim_id="claim:rf-validation-acceptance",
        applicability_record_id="applicability:rf-validation-8",
        required_conditions=("module-revision=7", "setup-revision=8"),
        excluded_conditions=(),
        matched_conditions=("module-revision=7", "setup-revision=8"),
        unmatched_conditions=(),
        geometry_source_fingerprint=geometry_fp,
        reviewer_record_id="review:rf-lab:8",
    )


def _requirement(
    enclosure,
    *,
    context: AntennaRfCampaignContext | None = None,
    metrics: tuple[AntennaRfMetricRequirement, ...] | None = None,
) -> AntennaRfCampaignRequirement:
    retained_context = context or _context(enclosure)
    retained_metrics = metrics or _metrics()
    requirement_id = "requirement:rf-campaign-8"
    profile_id = "validation-profile:rf-8"
    binding_fp = rf_requirement_binding_fingerprint(
        requirement_id=requirement_id,
        validation_profile_id=profile_id,
        validation_source_sha256=VALIDATION_SOURCE_SHA,
        context=retained_context,
        metrics=retained_metrics,
    )
    return AntennaRfCampaignRequirement(
        requirement_id=requirement_id,
        validation_profile_id=profile_id,
        validation_source_sha256=VALIDATION_SOURCE_SHA,
        context=retained_context,
        metrics=retained_metrics,
        applicability_binding=_binding(binding_fp),
    )


def _measurements(
    *, rssi: str = "-70", packet_error_rate: str = "1"
) -> tuple[AntennaRfMeasuredMetric, ...]:
    return (
        AntennaRfMeasuredMetric(
            metric_id="metric:packet-error-rate",
            unit="percent",
            value=packet_error_rate,
        ),
        AntennaRfMeasuredMetric(metric_id="metric:rssi", unit="dBm", value=rssi),
    )


def _record(
    requirement: AntennaRfCampaignRequirement,
    *,
    availability: str = "complete",
    measurements: tuple[AntennaRfMeasuredMetric, ...] | None = None,
    context: AntennaRfCampaignContext | None = None,
    profile_id: str | None = None,
) -> AntennaRfCampaignRecord:
    retained_measurements = measurements if measurements is not None else _measurements()
    record_id = "campaign:rf-fixture-8"
    if availability == "unavailable":
        retained_measurements = ()
    complete = availability == "complete"
    raw_json = (
        canonical_rf_raw_result_json(record_id, retained_measurements) if complete else None
    )
    return AntennaRfCampaignRecord(
        record_id=record_id,
        availability=availability,
        requirement_id=requirement.requirement_id,
        validation_profile_id=profile_id or requirement.validation_profile_id,
        requirement_fingerprint=requirement.semantic_fingerprint(),
        context=context or requirement.context,
        raw_data_artifact_id="raw-data:rf-fixture-8" if complete else None,
        raw_data_artifact_sha256="3" * 64 if complete else None,
        acquisition_tool="fixture-spectrum-and-packet-harness" if complete else None,
        acquisition_method="conducted-counterpart-link" if complete else None,
        acquisition_version="3.1" if complete else None,
        raw_result_record_json=raw_json,
        raw_result_record_sha256=(
            fingerprint(json.loads(raw_json)) if raw_json is not None else None
        ),
        measurements=retained_measurements,
    )


def test_missing_campaign_is_validation_pending_and_geometry_is_unchanged() -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    before_json = enclosure.placement_result.model_dump_json()

    result = evaluate_antenna_rf_validation(enclosure, requirement, None)

    assert result.geometry_finding.disposition is SemanticDisposition.PASS
    assert all(
        item.disposition is SemanticDisposition.VALIDATION_PENDING
        for item in result.metric_evidence
    )
    assert result.semantic_result.outcome is SemanticResultOutcome.VALIDATION_PENDING
    assert result.pcb_geometry_before_fingerprint == result.pcb_geometry_after_fingerprint
    assert result.enclosure_result.placement_result.model_dump_json() == before_json


def test_exact_matching_campaign_and_threshold_equality_pass() -> None:
    enclosure = _enclosure_result(include_nonapplicable=True)
    assert enclosure.semantic_result.outcome is SemanticResultOutcome.PASSED
    requirement = _requirement(enclosure)
    record = _record(requirement, measurements=_measurements(rssi="-70.0", packet_error_rate="1.0"))

    result = evaluate_antenna_rf_validation(enclosure, requirement, record)

    assert result.geometry_finding.disposition is SemanticDisposition.PASS
    assert all(item.disposition is SemanticDisposition.PASS for item in result.metric_evidence)
    assert result.semantic_result.outcome is SemanticResultOutcome.PASSED
    assert result.campaign_record == record
    assert result.campaign_record is not None
    assert result.campaign_record.raw_result_record_json is not None


def test_one_metric_failure_causes_validation_failure() -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    record = _record(requirement, measurements=_measurements(rssi="-70", packet_error_rate="1.1"))

    result = evaluate_antenna_rf_validation(enclosure, requirement, record)

    by_id = {item.requirement.metric_id: item for item in result.metric_evidence}
    assert by_id["metric:rssi"].disposition is SemanticDisposition.PASS
    assert by_id["metric:packet-error-rate"].disposition is SemanticDisposition.FAIL
    assert result.semantic_result.outcome is SemanticResultOutcome.VALIDATION_FAILED


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("antenna_id", "wrong"),
        ("module_reference", "wrong"),
        ("selected_footprint_library_id", "wrong"),
        ("component_uuid_path", "wrong"),
        ("component_revision", "wrong"),
        ("module_source_sha256", "4" * 64),
        ("placement_result_fingerprint", "4" * 64),
        ("anchor_x_mm", Decimal("0.1")),
        ("anchor_y_mm", Decimal("0.1")),
        ("side", "back"),
        ("rotation_deg", Decimal("90")),
        ("board_layout_snapshot_fingerprint", "4" * 64),
        ("enclosure_profile_id", "wrong"),
        ("enclosure_id", "wrong"),
        ("enclosure_revision", "wrong"),
        ("enclosure_model_sha256", "4" * 64),
    ),
)
def test_stale_upstream_requirement_context_is_rejected(field: str, value: object) -> None:
    enclosure = _enclosure_result()
    context = _context(enclosure).model_copy(update={field: value})
    requirement = _requirement(enclosure, context=context)

    with pytest.raises(ValueError, match="another module/placement/enclosure"):
        evaluate_antenna_rf_validation(enclosure, requirement, None)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("board_revision", "wrong"),
        ("board_artifact_sha256", "4" * 64),
        ("firmware_artifact_id", "wrong"),
        ("firmware_version", "wrong"),
        ("firmware_sha256", "4" * 64),
        ("radio_mode", "wrong"),
        ("band_id", "wrong"),
        ("channel_id", "wrong"),
        ("counterpart_id", "wrong"),
        ("counterpart_revision", "wrong"),
        ("range_id", "wrong"),
        ("range_revision", "wrong"),
        ("setup_id", "wrong"),
        ("setup_artifact_sha256", "4" * 64),
        ("environment_profile_id", "wrong"),
        ("environment_profile_sha256", "4" * 64),
    ),
)
def test_campaign_must_match_every_non_upstream_condition(field: str, value: object) -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    stale_context = requirement.context.model_copy(update={field: value})
    record = _record(requirement, context=stale_context)

    with pytest.raises(ValueError, match="conditions are stale"):
        evaluate_antenna_rf_validation(enclosure, requirement, record)


def test_stale_setup_config_profile_and_requirement_target_are_rejected() -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    payload = requirement.context.model_dump(mode="json")
    payload["setup_config_json"] = '{"changed":true}'
    with pytest.raises(ValidationError, match="SHA-256 is stale"):
        AntennaRfCampaignContext.model_validate(payload)

    changed_config = canonical_json({"changed": True})
    changed_context = requirement.context.model_copy(
        update={
            "setup_config_json": changed_config,
            "setup_config_sha256": fingerprint(json.loads(changed_config)),
        }
    )
    with pytest.raises(ValueError, match="conditions are stale"):
        evaluate_antenna_rf_validation(
            enclosure, requirement, _record(requirement, context=changed_context)
        )

    with pytest.raises(ValueError, match="conditions are stale"):
        evaluate_antenna_rf_validation(
            enclosure, requirement, _record(requirement, profile_id="wrong")
        )

    changed_metric = requirement.metrics[0].model_copy(update={"target": Decimal("2")})
    changed_requirement = _requirement(
        enclosure, metrics=(changed_metric, requirement.metrics[1])
    )
    old_record = _record(requirement)
    with pytest.raises(ValueError, match="conditions are stale"):
        evaluate_antenna_rf_validation(enclosure, changed_requirement, old_record)


def test_raw_hash_mismatch_and_metric_unit_mismatch_cannot_pass() -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    record = _record(requirement)
    payload = record.model_dump(mode="json")
    payload["raw_result_record_sha256"] = "4" * 64
    with pytest.raises(ValidationError, match="SHA-256 is stale"):
        AntennaRfCampaignRecord.model_validate(payload)

    wrong_unit = tuple(
        item.model_copy(update={"unit": "dB"}) if item.metric_id == "metric:rssi" else item
        for item in _measurements()
    )
    with pytest.raises(ValueError, match="unit differs"):
        evaluate_antenna_rf_validation(
            enclosure, requirement, _record(requirement, measurements=wrong_unit)
        )


def test_incomplete_unavailable_extra_missing_and_duplicate_metrics() -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    for availability in ("incomplete", "unavailable"):
        record = _record(requirement, availability=availability)
        result = evaluate_antenna_rf_validation(enclosure, requirement, record)
        assert result.semantic_result.outcome is SemanticResultOutcome.VALIDATION_PENDING
        assert all(
            item.disposition is SemanticDisposition.VALIDATION_PENDING
            for item in result.metric_evidence
        )
        if availability == "incomplete":
            assert {item.metric_id for item in record.measurements} == {
                item.metric_id for item in requirement.metrics
            }

    missing = _record(requirement, measurements=(_measurements()[0],))
    with pytest.raises(ValueError, match="omits required metrics"):
        evaluate_antenna_rf_validation(enclosure, requirement, missing)

    extra_metric = AntennaRfMeasuredMetric(
        metric_id="metric:unrequested", unit="dB", value="1"
    )
    extra = _record(
        requirement, measurements=(*_measurements(), extra_metric)
    )
    with pytest.raises(ValueError, match="unrequested"):
        evaluate_antenna_rf_validation(enclosure, requirement, extra)

    payload = _record(requirement).model_dump(mode="json")
    payload["measurements"].append(payload["measurements"][0])
    payload["raw_result_record_json"] = canonical_rf_raw_result_json(
        payload["record_id"],
        tuple(AntennaRfMeasuredMetric.model_validate(item) for item in payload["measurements"]),
    )
    payload["raw_result_record_sha256"] = fingerprint(
        json.loads(payload["raw_result_record_json"])
    )
    with pytest.raises(ValidationError, match="identities must be unique"):
        AntennaRfCampaignRecord.model_validate(payload)


@pytest.mark.parametrize(
    ("geometry_state", "expected"),
    (
        ("pending", SemanticDisposition.VALIDATION_PENDING),
        ("fail", SemanticDisposition.FAIL),
    ),
)
def test_geometry_pending_and_fail_cannot_be_overridden_by_passing_rf_data(
    geometry_state: str, expected: SemanticDisposition
) -> None:
    enclosure = _enclosure_result(state=geometry_state)
    requirement = _requirement(enclosure)
    result = evaluate_antenna_rf_validation(
        enclosure, requirement, _record(requirement)
    )

    assert all(item.disposition is SemanticDisposition.PASS for item in result.metric_evidence)
    assert result.geometry_finding.disposition is expected
    expected_outcome = (
        SemanticResultOutcome.VALIDATION_PENDING
        if geometry_state == "pending"
        else SemanticResultOutcome.VALIDATION_FAILED
    )
    assert result.semantic_result.outcome is expected_outcome


def test_json_replay_reversal_and_tamper_guards() -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    record = _record(requirement)
    result = evaluate_antenna_rf_validation(enclosure, requirement, record)
    assert AntennaRfValidationResult.model_validate_json(result.model_dump_json()) == result

    reversed_requirement = _requirement(
        enclosure, metrics=tuple(reversed(requirement.metrics))
    )
    reversed_record = _record(
        reversed_requirement, measurements=tuple(reversed(record.measurements))
    )
    assert reversed_requirement == requirement
    assert reversed_record == record
    assert evaluate_antenna_rf_validation(
        enclosure, reversed_requirement, reversed_record
    ) == result

    for mutate in (
        lambda payload: payload["geometry_finding"].update({"message": "tampered"}),
        lambda payload: payload["metric_evidence"][0].update(
            {"disposition": "fail"}
        ),
        lambda payload: payload.update({"evidence_fingerprint": "4" * 64}),
        lambda payload: payload.update({"result_fingerprint": "4" * 64}),
    ):
        payload = deepcopy(result.model_dump(mode="json"))
        mutate(payload)
        with pytest.raises(ValidationError):
            AntennaRfValidationResult.model_validate(payload)


def test_nested_metric_evidence_rejects_identity_unit_value_and_disposition_tamper() -> None:
    enclosure = _enclosure_result()
    requirement = _requirement(enclosure)
    result = evaluate_antenna_rf_validation(
        enclosure, requirement, _record(requirement)
    )
    evidence = result.metric_evidence[0]
    assert evidence.measured is not None
    for measured_update in (
        {"metric_id": "metric:wrong"},
        {"unit": "wrong"},
        {"value": Decimal("1.1")},
    ):
        stale = evidence.model_copy(
            update={"measured": evidence.measured.model_copy(update=measured_update)}
        )
        with pytest.raises(ValidationError):
            AntennaRfMetricEvidence.model_validate_json(stale.model_dump_json())
    stale = evidence.model_copy(update={"disposition": SemanticDisposition.FAIL})
    with pytest.raises(ValidationError, match="disposition is stale"):
        AntennaRfMetricEvidence.model_validate_json(stale.model_dump_json())
