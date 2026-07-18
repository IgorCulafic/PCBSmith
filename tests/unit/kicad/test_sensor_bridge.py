"""Firing fixture 7: explicit exact track bridges across sensor removal regions."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_sensor_copper_removal import (
    _base_layout,
    _declaration,
    _empty_netlist,
    _isolation,
)

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardLayout, TrackSegment, ViaSpec
from pcbsmith.kicad.sensor_bridge import evaluate_sensor_bridges
from pcbsmith.kicad.sensor_copper_removal import evaluate_sensor_copper_removal
from pcbsmith.mask_geometry import OrientedRect, Point
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticResultOutcome,
    SemanticRuleDeclaration,
)
from pcbsmith.sensor_bridge_ir import (
    ExactRationalMillimetres,
    SensorBridgeCheckKind,
    SensorBridgeDeclaration,
    SensorBridgeEvaluationResult,
    bridge_authority_fingerprint,
)


def _region() -> OrientedRect:
    return OrientedRect(
        center=Point(x_mm=3.0, y_mm=4.0),
        width_mm=1.0,
        height_mm=1.0,
    )


def _layout(*segments: TrackSegment, vias: tuple[ViaSpec, ...] = ()) -> BoardLayout:
    return _base_layout(segments=segments, vias=vias)


def _crossing(
    *,
    net_name: str = "SENSE",
    layer: str = "F.Cu",
    width_mm: float = 0.2,
    y: float = 4.0,
) -> TrackSegment:
    return TrackSegment(
        x1=2.0,
        y1=y,
        x2=4.0,
        y2=y,
        layer=layer,
        net_name=net_name,
        width_mm=width_mm,
    )


def _inputs(layout: BoardLayout):
    netlist = _empty_netlist()
    isolation = _isolation(layout)
    removal_declaration = _declaration(isolation, _region())
    removal = evaluate_sensor_copper_removal(
        layout,
        netlist,
        isolation,
        (removal_declaration,),
    )
    return netlist, isolation, removal, removal_declaration


def _bridge_declaration(
    isolation,
    removal_declaration,
    *,
    declaration_id: str = "bridge:front",
    allowed_sources: tuple[str, ...] = ("track:0",),
    allowed_nets: tuple[str, ...] = ("SENSE",),
    maximum_count: int = 1,
    maximum_width: ExactRationalMillimetres | None = None,
) -> SensorBridgeDeclaration:
    width = maximum_width or ExactRationalMillimetres.from_value("0.2")
    authority_fp = bridge_authority_fingerprint(
        declaration_id=declaration_id,
        isolation_result_fingerprint=isolation.semantic_fingerprint(),
        copper_removal_declaration=removal_declaration,
        allowed_bridge_net_names=allowed_nets,
        allowed_track_source_ids=allowed_sources,
        maximum_bridge_track_count=maximum_count,
        maximum_total_bridge_width_mm=width,
    )
    binding_id = f"binding:{declaration_id}"
    binding = EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=(
            EvidenceRef(
                kind="project_design_record",
                title="Reviewed exact intentional sensor bridge",
                locator=declaration_id,
                source_id=f"source:{declaration_id}",
                organization_or_author="Fixture reviewer",
                revision="1",
                local_sha256="e" * 64,
                source_status="pinned",
                locator_status="figure_verified",
                applicability_status="confirmed",
                required_conditions=("board=fixture",),
            ),
        ),
        claim_id=f"claim:{declaration_id}",
        applicability_record_id=f"applicability:{declaration_id}",
        required_conditions=("board=fixture",),
        excluded_conditions=(),
        matched_conditions=("board=fixture",),
        unmatched_conditions=(),
        geometry_source_fingerprint=authority_fp,
        reviewer_record_id="review:sensor-bridge",
    )
    expected_objects = tuple(
        sorted(
            {
                declaration_id,
                removal_declaration.declaration_id,
                removal_declaration.candidate_id,
                removal_declaration.source_feature_id,
                *allowed_sources,
            }
        )
    )
    return SensorBridgeDeclaration(
        declaration_id=declaration_id,
        isolation_result_fingerprint=isolation.semantic_fingerprint(),
        copper_removal_declaration=removal_declaration,
        copper_removal_declaration_fingerprint=removal_declaration.semantic_fingerprint(),
        allowed_bridge_net_names=allowed_nets,
        allowed_track_source_ids=allowed_sources,
        maximum_bridge_track_count=maximum_count,
        maximum_total_bridge_width_mm=width,
        authority_evidence_binding=binding,
        bridge_rule=SemanticRuleDeclaration(
            rule_id=f"rule:{declaration_id}",
            authority=SemanticAuthorityClass.HARD_GEOMETRY,
            object_ids=expected_objects,
            geometry_region_ids=(removal_declaration.region_id,),
            evidence_binding_ids=(binding_id,),
        ),
    )


def _evaluate(layout: BoardLayout, **declaration_changes):
    netlist, isolation, removal, removal_declaration = _inputs(layout)
    declaration = _bridge_declaration(
        isolation,
        removal_declaration,
        **declaration_changes,
    )
    result = evaluate_sensor_bridges(
        layout,
        netlist,
        isolation,
        removal,
        (declaration,),
    )
    return result, declaration


def _typed(result, kind: SensorBridgeCheckKind):
    return tuple(item for item in result.typed_findings if item.check_kind is kind)


def _disposition(result, kind: SensorBridgeCheckKind) -> SemanticDisposition:
    return _typed(result, kind)[0].disposition


def test_exact_declared_bridge_passes_without_overwriting_removal_failure() -> None:
    result, _declaration_value = _evaluate(_layout(_crossing()))

    assert (
        result.copper_removal_result.semantic_result.outcome
        is SemanticResultOutcome.HARD_REJECTED
    )
    assert result.semantic_result.outcome is SemanticResultOutcome.PASSED
    assert result.exception_scope_statement.startswith("separate bridge authority")
    assert len(result.bridge_tracks) == 1
    record = result.bridge_tracks[0]
    assert record.source_id == "track:0"
    assert record.width_mm.as_fraction().numerator == 1
    assert record.width_mm.as_fraction().denominator == 5
    assert record.disposition is SemanticDisposition.PASS
    assert result.copper_removal_result.findings == _inputs(_layout(_crossing()))[2].findings


def test_undeclared_source_fires_independently() -> None:
    result, _ = _evaluate(_layout(_crossing()), allowed_sources=("track:9",))

    assert _disposition(result, SensorBridgeCheckKind.SOURCE_AUTHORIZED) is SemanticDisposition.FAIL
    assert _disposition(result, SensorBridgeCheckKind.NET_AUTHORIZED) is SemanticDisposition.PASS
    assert (
        _disposition(result, SensorBridgeCheckKind.TRACK_COUNT_BUDGET)
        is SemanticDisposition.PASS
    )
    assert (
        _disposition(result, SensorBridgeCheckKind.TOTAL_WIDTH_BUDGET)
        is SemanticDisposition.PASS
    )


def test_undeclared_net_fires_independently() -> None:
    result, _ = _evaluate(_layout(_crossing(net_name="OTHER")))

    assert _disposition(result, SensorBridgeCheckKind.SOURCE_AUTHORIZED) is SemanticDisposition.PASS
    assert _disposition(result, SensorBridgeCheckKind.NET_AUTHORIZED) is SemanticDisposition.FAIL
    assert result.bridge_tracks[0].disposition is SemanticDisposition.FAIL


def test_count_equality_passes_and_excess_fires_independently() -> None:
    layout = _layout(_crossing(y=3.9), _crossing(y=4.1))
    result, _ = _evaluate(
        layout,
        allowed_sources=("track:0", "track:1"),
        maximum_count=1,
        maximum_width=ExactRationalMillimetres.from_value("1.0"),
    )
    assert (
        _disposition(result, SensorBridgeCheckKind.TRACK_COUNT_BUDGET)
        is SemanticDisposition.FAIL
    )
    assert (
        _disposition(result, SensorBridgeCheckKind.TOTAL_WIDTH_BUDGET)
        is SemanticDisposition.PASS
    )

    equality, _ = _evaluate(
        layout,
        allowed_sources=("track:0", "track:1"),
        maximum_count=2,
        maximum_width=ExactRationalMillimetres.from_value("0.4"),
    )
    assert equality.budget_evidence[0].count_budget_passed
    assert equality.budget_evidence[0].total_width_budget_passed


def test_exact_width_one_decimal_unit_below_actual_fails() -> None:
    result, _ = _evaluate(
        _layout(_crossing()),
        maximum_width=ExactRationalMillimetres.from_value("0.199"),
    )

    assert (
        _disposition(result, SensorBridgeCheckKind.TOTAL_WIDTH_BUDGET)
        is SemanticDisposition.FAIL
    )
    assert (
        _disposition(result, SensorBridgeCheckKind.TRACK_COUNT_BUDGET)
        is SemanticDisposition.PASS
    )


def test_zero_count_budget_is_legal_and_fails_one_crossing() -> None:
    result, _ = _evaluate(_layout(_crossing()), maximum_count=0)
    assert not result.budget_evidence[0].count_budget_passed


def test_pads_vias_zones_and_opposite_layer_never_become_bridge_tracks() -> None:
    layout = _layout(
        _crossing(layer="B.Cu"),
        vias=(ViaSpec(x=3.0, y=4.0, net_name="SENSE"),),
    )
    layout = replace(layout, zones=(("SENSE", "F.Cu", (2.5, 3.5, 3.5, 4.5)),))
    result, _ = _evaluate(layout)

    assert result.bridge_tracks == ()
    assert result.budget_evidence[0].actual_bridge_track_count == 0
    assert all(
        not item.source_id.startswith(("via:", "pad:", "zone:"))
        for item in result.bridge_tracks
    )


def test_json_reconstruction_and_caller_isolation_are_exact() -> None:
    result, declaration = _evaluate(_layout(_crossing()))
    reconstructed = SensorBridgeEvaluationResult.model_validate_json(result.model_dump_json())
    payload = declaration.model_dump(mode="json")
    payload["allowed_bridge_net_names"] = ["MUTATED"]

    assert reconstructed == result
    assert result.declarations[0].allowed_bridge_net_names == ("SENSE",)


def test_canonical_allowed_identity_order_is_reversal_deterministic() -> None:
    layout = _layout(_crossing())
    result_a, _ = _evaluate(
        layout,
        allowed_sources=("track:9", "track:0"),
        allowed_nets=("Z", "SENSE"),
    )
    result_b, _ = _evaluate(
        layout,
        allowed_sources=("track:0", "track:9"),
        allowed_nets=("SENSE", "Z"),
    )
    assert result_a == result_b


def test_segment_order_changes_exact_source_identity_and_result() -> None:
    crossing = _crossing()
    separated = _crossing(y=8.0)
    first, _ = _evaluate(_layout(crossing, separated))
    second, _ = _evaluate(_layout(separated, crossing))

    assert first.bridge_tracks[0].source_id == "track:0"
    assert second.bridge_tracks[0].source_id == "track:1"
    assert first.geometry_fingerprint != second.geometry_fingerprint
    assert second.bridge_tracks[0].disposition is SemanticDisposition.FAIL


def test_bridge_declaration_rejects_stale_or_shared_authority() -> None:
    layout = _layout(_crossing())
    _netlist, isolation, _removal, removal_declaration = _inputs(layout)
    valid = _bridge_declaration(isolation, removal_declaration)

    with pytest.raises(ValidationError, match="stale for its isolation/removal authority"):
        SensorBridgeDeclaration.model_validate(
            {**valid.model_dump(mode="json"), "isolation_result_fingerprint": "0" * 64}
        )
    with pytest.raises(ValidationError, match="separate exact hard-geometry rule"):
        SensorBridgeDeclaration.model_validate(
            {
                **valid.model_dump(mode="json"),
                "bridge_rule": {
                    **valid.bridge_rule.model_dump(mode="json"),
                    "rule_id": removal_declaration.rule_id,
                },
            }
        )


def test_bridge_declaration_rejects_incomplete_or_stale_dedicated_binding() -> None:
    layout = _layout(_crossing())
    _netlist, isolation, _removal, removal_declaration = _inputs(layout)
    valid = _bridge_declaration(isolation, removal_declaration)
    binding = valid.authority_evidence_binding.model_dump(mode="json")

    with pytest.raises(ValidationError, match="complete reviewed"):
        SensorBridgeDeclaration.model_validate(
            {
                **valid.model_dump(mode="json"),
                "authority_evidence_binding": {
                    **binding,
                    "reviewer_record_id": None,
                },
            }
        )
    with pytest.raises(ValidationError, match="stale for the exact authorized constraints"):
        SensorBridgeDeclaration.model_validate(
            {
                **valid.model_dump(mode="json"),
                "authority_evidence_binding": {
                    **binding,
                    "geometry_source_fingerprint": "0" * 64,
                },
            }
        )


@pytest.mark.parametrize(
    "field", ("bridge_tracks", "budget_evidence", "findings", "typed_findings")
)
def test_result_replay_rejects_tampered_derived_collections(field: str) -> None:
    result, _ = _evaluate(_layout(_crossing()))
    payload = result.model_dump(mode="json")
    payload[field] = []

    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        SensorBridgeEvaluationResult.model_validate(payload)


def test_replay_rejects_another_board_or_removal_authority() -> None:
    layout = _layout(_crossing())
    netlist, isolation, removal, removal_declaration = _inputs(layout)
    declaration = _bridge_declaration(isolation, removal_declaration)

    with pytest.raises(ValueError, match="differ from the retained copper-removal"):
        evaluate_sensor_bridges(
            _layout(_crossing(y=4.2)),
            netlist,
            isolation,
            removal,
            (declaration,),
        )


def test_exact_rational_and_positive_maximum_are_enforced() -> None:
    with pytest.raises(ValidationError, match="lowest terms"):
        ExactRationalMillimetres(numerator=2, denominator=10)
    layout = _layout(_crossing())
    _netlist, isolation, _removal, removal_declaration = _inputs(layout)
    valid = _bridge_declaration(isolation, removal_declaration)
    with pytest.raises(ValidationError, match="maximum total bridge width must be positive"):
        SensorBridgeDeclaration.model_validate(
            {
                **valid.model_dump(mode="json"),
                "maximum_total_bridge_width_mm": ExactRationalMillimetres.from_value(0).model_dump(
                    mode="json"
                ),
            }
        )
