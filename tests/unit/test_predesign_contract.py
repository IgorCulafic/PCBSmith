from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.concept_review import ConceptItem, examine_concept
from pcbsmith.predesign_contract import (
    AmendmentDecisionV2,
    ApproverMetadataV2,
    BriefAmendmentPatchV2,
    BriefAmendmentSetV2,
    ComponentGeometryBindingV2,
    ConceptOverlayManifestV2,
    ElectricalDemandInventoryRecordV2,
    PredesignApprovalContractV2,
    PreRouteFeasibilityInputsV2,
    SourceDemandCoverageRecordV2,
    SourceDemandCoverageV2,
    artifact_sha256,
    require_predesign_approval,
)
from pcbsmith.project_brief import (
    AssetReference,
    ComponentRequirement,
    MechanicalRequirement,
    PlacementRequirement,
    ProjectBriefDraft,
    RequirementValue,
    normalize_project_brief,
)
from pcbsmith.prompt_examiner import (
    AnchorKind,
    ExaminedClaim,
    PromptResolution,
    SourceSpan,
    TypedSpatialAnchor,
    examine_prompt,
)
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.workflow_feasibility import (
    NeckSection,
    PlacementEnvelope,
    PreRouteNetDemand,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
FIXTURE_FOOTPRINT = "Resistor_SMD:R_0603_1608Metric"


@dataclass(frozen=True)
class _ContractFixture:
    contract: PredesignApprovalContractV2
    artifact_root: Path


def _value(requirement_id: str, value: str | float | int | bool) -> RequirementValue:
    return RequirementValue(
        requirement_id=requirement_id,
        value=value,
        unit="mm",
        source="user",
        resolution="explicit",
        source_text=requirement_id,
    )


def _draft(*, maximum_width_mm: float, include_u2: bool = False) -> ProjectBriefDraft:
    text = "Maximum width is 20 mm and U1 must be near the center."
    return ProjectBriefDraft(
        project_id="fixture",
        title="Predesign fixture",
        original_text=text,
        functional_requirements=(_value("function.demo", "demonstrate contract"),),
        electrical_requirements=(),
        manufacturing_requirements=(),
        mechanics=MechanicalRequirement(
            maximum_width_mm=_value("mechanics.max-width", maximum_width_mm),
            maximum_height_mm=_value("mechanics.max-height", 10.0),
            board_thickness_mm=_value("mechanics.thickness", 1.6),
            layer_count=_value("manufacturing.layers", 2),
            outline_asset_id="outline",
        ),
        components=(
            ComponentRequirement(
                component_id="U1",
                quantity=1,
                role="controller",
                footprint_id=FIXTURE_FOOTPRINT,
                side="front",
                mounting="smd",
            ),
            *(
                (
                    ComponentRequirement(
                        component_id="U2",
                        quantity=1,
                        role="secondary controller",
                        footprint_id=FIXTURE_FOOTPRINT,
                        side="front",
                        mounting="smd",
                    ),
                )
                if include_u2
                else ()
            ),
        ),
        placements=(
            PlacementRequirement(
                placement_id="placement.u1",
                subject="U1",
                relation="near board center",
                side="front",
                anchor_semantics="center",
                tolerance_mm=1.0,
                resolution="explicit",
                source_text="U1 must be near the center",
            ),
            *(
                (
                    PlacementRequirement(
                        placement_id="placement.u2",
                        subject="U2",
                        relation="near U1",
                        side="front",
                        anchor_semantics="adjacent",
                        tolerance_mm=1.0,
                        resolution="explicit",
                        source_text="derived fixture placement",
                    ),
                )
                if include_u2
                else ()
            ),
        ),
        artwork=(),
        assets=(
            AssetReference(
                asset_id="outline",
                purpose="outline",
                source_file="outline.svg",
                source_sha256=SHA_A,
                physical_width_mm=20.0,
            ),
        ),
    )


def _write_overlays(
    *,
    root: Path,
    prompt_sha256: str,
    outline_sha256: str,
    concept_sha256: str,
) -> tuple[ConceptOverlayManifestV2, ...]:
    manifests: list[ConceptOverlayManifestV2] = []
    for side in ("front", "back"):
        svg_path = f"engineering-overlay-{side}.svg"
        png_path = f"engineering-overlay-{side}.png"
        svg = f"<svg data-side='{side}'/>".encode()
        png = b"\x89PNG\r\n" + side.encode()
        (root / svg_path).write_bytes(svg)
        (root / png_path).write_bytes(png)
        manifests.append(
            ConceptOverlayManifestV2.build(
                project_id="fixture",
                prompt_examination_sha256=prompt_sha256,
                board_outline_sha256=outline_sha256,
                concept_review_sha256=concept_sha256,
                side=side,
                svg_path=svg_path,
                svg_sha256=hashlib.sha256(svg).hexdigest(),
                svg_bytes=len(svg),
                png_path=png_path,
                png_sha256=hashlib.sha256(png).hexdigest(),
                png_bytes=len(png),
            )
        )
    return tuple(manifests)


def _build_contract(
    tmp_path: Path,
    *,
    with_amendment: bool = True,
    feasibility_state: str = "ready",
    omit_component_envelope: bool = False,
    include_u2: bool = False,
    shrink_component_envelope: bool = False,
    unknown_terminal_component: bool = False,
) -> _ContractFixture:
    text = "Maximum width is 20 mm and U1 must be near the center."
    span = SourceSpan(
        span_id="span.request",
        start=0,
        end=len(text),
        exact_text=text,
    )
    prompt = examine_prompt(
        project_id="fixture",
        original_text=text,
        spans=(span,),
        claims=(
            ExaminedClaim(
                claim_id="claim.width",
                field_path="mechanics.maximum_width_mm",
                value=20.0,
                unit="mm",
                resolution=PromptResolution.EXPLICIT,
                source_span_ids=(span.span_id,),
            ),
        ),
        anchors=(
            TypedSpatialAnchor(
                anchor_id="anchor.u1.center",
                kind=AnchorKind.CENTER,
                subject_ids=("U1",),
                reference_id="board.center",
                axis="both",
                tolerance_mm=1.0,
                source_span_ids=(span.span_id,),
            ),
        ),
    )
    original = normalize_project_brief(
        _draft(maximum_width_mm=20.0, include_u2=include_u2)
    )
    amended = (
        normalize_project_brief(
            _draft(maximum_width_mm=25.0, include_u2=include_u2)
        )
        if with_amendment
        else original
    )
    prompt_hash = artifact_sha256(prompt)
    original_hash = artifact_sha256(original)
    amended_hash = artifact_sha256(amended)

    outline = ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0))
    concept = examine_concept(
        "fixture",
        outline,
        (
            ConceptItem(
                item_id="U1",
                label="Controller",
                side="front",
                kind="footprint",
                anchor_mm=(10.0, 5.0),
                footprint_id=FIXTURE_FOOTPRINT,
                containment="body",
                requirement_resolution="explicit",
            ),
            *(
                (
                    ConceptItem(
                        item_id="U2",
                        label="Secondary controller",
                        side="front",
                        kind="footprint",
                        anchor_mm=(13.0, 5.0),
                        footprint_id=FIXTURE_FOOTPRINT,
                        containment="body",
                        requirement_resolution="explicit",
                    ),
                )
                if include_u2
                else ()
            ),
        ),
        tight_clearance_mm=0.5,
    )
    concept_hash = artifact_sha256(concept)

    concept_envelopes = {
        item.item.item_id: item.envelope for item in concept.items
    }
    u1_polygon = concept_envelopes["U1"]
    if shrink_component_envelope:
        center_x = sum(point[0] for point in u1_polygon) / len(u1_polygon)
        center_y = sum(point[1] for point in u1_polygon) / len(u1_polygon)
        u1_polygon = tuple(
            (
                round(center_x + (x - center_x) * 0.5, 4),
                round(center_y + (y - center_y) * 0.5, 4),
            )
            for x, y in u1_polygon
        )
    envelopes = (
        ()
        if omit_component_envelope
        else (
            PlacementEnvelope(
                envelope_id="env.u1",
                subject_id="U1",
                polygon=u1_polygon,
                source_geometry_sha256=concept_hash,
            ),
            *(
                (
                    PlacementEnvelope(
                        envelope_id="env.u2",
                        subject_id="U2",
                        polygon=concept_envelopes["U2"],
                        source_geometry_sha256=concept_hash,
                    ),
                )
                if include_u2
                else ()
            ),
        )
    )
    necks = (
        ()
        if feasibility_state == "unverified"
        else (
            NeckSection(
                neck_id="neck.main",
                usable_width_mm=0.25,
                routing_layers=("F.Cu",),
                capacity_quantum_mm=0.25,
                source_geometry_sha256=concept.outline_sha256,
            ),
        )
    )
    demands = (
        PreRouteNetDemand(
            net_name="NET1",
            terminal_ids=(
                ("U1/1", "Z99/1")
                if unknown_terminal_component
                else ("U1/1", "U1/2")
            ),
            trace_width_mm=0.25,
            clearance_mm=0.0,
            candidate_neck_ids=("neck.main",) if necks else (),
            net_class_id="signal",
            priority=1,
        ),
        *(
            (
                PreRouteNetDemand(
                    net_name="NET2",
                    terminal_ids=("U1/3", "U1/4"),
                    trace_width_mm=0.25,
                    clearance_mm=0.0,
                    candidate_neck_ids=("neck.main",),
                    net_class_id="signal",
                    priority=2,
                ),
            )
            if feasibility_state == "blocked"
            else ()
        ),
    )
    pre_route_inputs = PreRouteFeasibilityInputsV2.build(
        project_id="fixture",
        prompt_examination_sha256=prompt_hash,
        amended_brief_sha256=amended_hash,
        board_outline=outline,
        board_outline_sha256=concept.outline_sha256,
        keepout_polygons=(),
        envelopes=envelopes,
        necks=necks,
        net_demands=demands,
    )
    report = pre_route_inputs.evaluate()
    inputs_hash = artifact_sha256(pre_route_inputs)
    report_hash = artifact_sha256(report)

    patches: tuple[BriefAmendmentPatchV2, ...]
    if with_amendment:
        patches = (
            BriefAmendmentPatchV2.build(
                amendment_id="amend.maximum-width",
                decision_id="decision.maximum-width",
                path="/mechanics/maximum_width_mm/value",
                before=20.0,
                replacement=25.0,
            ),
        )
    else:
        patches = ()
    amendment_set = BriefAmendmentSetV2.build(
        project_id="fixture",
        prompt_examination_sha256=prompt_hash,
        board_outline_sha256=concept.outline_sha256,
        original_brief_sha256=original_hash,
        amended_brief_sha256=amended_hash,
        patches=patches,
    )
    amendment_hash = artifact_sha256(amendment_set)
    decisions = (
        (
            AmendmentDecisionV2.build(
                project_id="fixture",
                prompt_examination_sha256=prompt_hash,
                board_outline_sha256=concept.outline_sha256,
                amendment_set_sha256=amendment_hash,
                decision_id="decision.maximum-width",
                amendment_ids=("amend.maximum-width",),
            ),
        )
        if with_amendment
        else ()
    )

    coverage_record = SourceDemandCoverageRecordV2.build(
        demand_id="demand.request",
        source_span_ids=(span.span_id,),
        claim_ids=("claim.width",),
        anchor_ids=("anchor.u1.center",),
        requirement_ids=(
            "function.demo",
            "manufacturing.layers",
            "mechanics.max-height",
            "mechanics.max-width",
            "mechanics.thickness",
        ),
        component_ids=("U1", "U2") if include_u2 else ("U1",),
        placement_ids=("placement.u1", "placement.u2")
        if include_u2
        else ("placement.u1",),
        asset_ids=("outline",),
        concept_item_ids=("U1", "U2") if include_u2 else ("U1",),
        feasibility_envelope_ids=(
            ()
            if omit_component_envelope
            else (("env.u1", "env.u2") if include_u2 else ("env.u1",))
        ),
        feasibility_net_names=tuple(item.net_name for item in demands),
    )
    coverage = SourceDemandCoverageV2.build(
        project_id="fixture",
        prompt_examination_sha256=prompt_hash,
        amended_brief_sha256=amended_hash,
        board_outline_sha256=concept.outline_sha256,
        concept_review_sha256=concept_hash,
        pre_route_inputs_sha256=inputs_hash,
        pre_route_feasibility_sha256=report_hash,
        component_geometry_bindings=(
            ()
            if omit_component_envelope
            else (
                ComponentGeometryBindingV2(
                    component_id="U1",
                    concept_item_ids=("U1",),
                    feasibility_envelope_ids=("env.u1",),
                ),
                *(
                    (
                        ComponentGeometryBindingV2(
                            component_id="U2",
                            concept_item_ids=("U2",),
                            feasibility_envelope_ids=("env.u2",),
                        ),
                    )
                    if include_u2
                    else ()
                ),
            )
        ),
        electrical_demand_inventory=tuple(
            ElectricalDemandInventoryRecordV2(
                net_name=item.net_name,
                terminal_ids=item.terminal_ids,
                source_claim_ids=("claim.width",),
                source_requirement_ids=("function.demo",),
            )
            for item in demands
        ),
        records=(coverage_record,),
    )
    overlays = _write_overlays(
        root=tmp_path,
        prompt_sha256=prompt_hash,
        outline_sha256=concept.outline_sha256,
        concept_sha256=concept_hash,
    )
    contract = PredesignApprovalContractV2.build(
        project_id="fixture",
        prompt_examination=prompt,
        original_brief=original,
        amended_brief=amended,
        amendment_set=amendment_set,
        decisions=decisions,
        concept_review=concept,
        concept_tight_clearance_mm=0.5,
        overlay_manifests=overlays,
        pre_route_inputs=pre_route_inputs,
        pre_route_feasibility=report,
        source_demand_coverage=coverage,
        asserted_approver_id="requester.fixture",
        asserted_approver_role="requester",
        recorded_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        capture_method="interactive_assertion",
    )
    return _ContractFixture(contract=contract, artifact_root=tmp_path)


def test_full_contract_replays_and_verifies_live_overlays(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)

    accepted = require_predesign_approval(
        fixture.contract,
        artifact_root=fixture.artifact_root,
    )

    assert accepted.approved
    assert accepted.accepted_amendment_ids == ("amend.maximum-width",)
    assert accepted.pre_route_inputs.evaluate() == accepted.pre_route_feasibility


def test_clean_prompt_requires_no_invented_amendment_or_decision(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path, with_amendment=False)

    accepted = require_predesign_approval(
        fixture.contract,
        artifact_root=fixture.artifact_root,
    )

    assert not accepted.amendment_set.patches
    assert not accepted.decisions
    assert not accepted.accepted_decision_ids


def test_live_overlay_one_byte_mutation_fails_closed(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    path = tmp_path / "engineering-overlay-front.svg"
    payload = bytearray(path.read_bytes())
    payload[0] ^= 1
    path.write_bytes(payload)

    with pytest.raises(RuntimeError, match="hash changed"):
        require_predesign_approval(fixture.contract, artifact_root=tmp_path)


def test_missing_live_overlay_fails_closed(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    (tmp_path / "engineering-overlay-back.png").unlink()

    with pytest.raises(RuntimeError, match="unavailable"):
        require_predesign_approval(fixture.contract, artifact_root=tmp_path)


def test_overlay_symlink_is_rejected_when_supported(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    path = tmp_path / "engineering-overlay-back.svg"
    target = tmp_path / "actual-back.svg"
    path.replace(target)
    try:
        path.symlink_to(target.name)
    except OSError:
        pytest.skip("file symlinks are unavailable in this environment")

    with pytest.raises(RuntimeError, match="symlink"):
        require_predesign_approval(fixture.contract, artifact_root=tmp_path)


@pytest.mark.parametrize("state", ["blocked", "unverified"])
def test_nonready_replayed_feasibility_cannot_be_approved(
    tmp_path: Path,
    state: str,
) -> None:
    with pytest.raises(ValidationError, match="pre-route feasibility is not ready"):
        _build_contract(tmp_path, feasibility_state=state)


def test_omitted_component_envelope_cannot_pass_as_complete(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="every brief component requires"):
        _build_contract(tmp_path, omit_component_envelope=True)


def test_component_envelope_cannot_shrink_below_concept_geometry(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="differs from concept geometry"):
        _build_contract(tmp_path, shrink_component_envelope=True)


def test_pre_route_inputs_reject_vacuous_demand_set(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    inputs = fixture.contract.pre_route_inputs

    with pytest.raises(ValidationError, match="at least 1 item"):
        PreRouteFeasibilityInputsV2.build(
            project_id=inputs.project_id,
            prompt_examination_sha256=inputs.prompt_examination_sha256,
            amended_brief_sha256=inputs.amended_brief_sha256,
            board_outline=inputs.board_outline,
            board_outline_sha256=inputs.board_outline_sha256,
            keepout_polygons=inputs.keepout_polygons,
            envelopes=inputs.envelopes,
            necks=inputs.necks,
            net_demands=(),
            search_state_budget=inputs.search_state_budget,
        )


def test_coverage_rejects_vacuous_electrical_inventory(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    coverage = fixture.contract.source_demand_coverage

    with pytest.raises(ValidationError, match="at least 1 item"):
        SourceDemandCoverageV2.build(
            project_id=coverage.project_id,
            prompt_examination_sha256=coverage.prompt_examination_sha256,
            amended_brief_sha256=coverage.amended_brief_sha256,
            board_outline_sha256=coverage.board_outline_sha256,
            concept_review_sha256=coverage.concept_review_sha256,
            pre_route_inputs_sha256=coverage.pre_route_inputs_sha256,
            pre_route_feasibility_sha256=coverage.pre_route_feasibility_sha256,
            component_geometry_bindings=coverage.component_geometry_bindings,
            electrical_demand_inventory=(),
            records=coverage.records,
        )


def test_terminal_requires_fixed_component_slash_terminal_syntax() -> None:
    with pytest.raises(ValidationError, match="fixed '<component_id>/<terminal_id>'"):
        ElectricalDemandInventoryRecordV2(
            net_name="NET1",
            terminal_ids=("U1.1", "U1.2"),
            source_claim_ids=("claim.width",),
        )


def test_terminal_component_must_exist_in_amended_brief(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="undeclared brief component"):
        _build_contract(tmp_path, unknown_terminal_component=True)


def test_feasibility_threshold_inflation_is_rejected(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    inputs = fixture.contract.pre_route_inputs

    with pytest.raises(ValidationError, match="frozen policy"):
        PreRouteFeasibilityInputsV2.build(
            project_id=inputs.project_id,
            prompt_examination_sha256=inputs.prompt_examination_sha256,
            amended_brief_sha256=inputs.amended_brief_sha256,
            board_outline=inputs.board_outline,
            board_outline_sha256=inputs.board_outline_sha256,
            keepout_polygons=inputs.keepout_polygons,
            envelopes=inputs.envelopes,
            necks=inputs.necks,
            net_demands=inputs.net_demands,
            attention_utilization=0.99,
            search_state_budget=inputs.search_state_budget,
        )


def test_concept_threshold_weakening_is_rejected(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    tampered = fixture.contract.model_copy(
        update={"concept_tight_clearance_mm": 0.0001}
    )

    with pytest.raises(ValidationError, match="frozen policy"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_stale_outer_artifact_hash_fails_closed(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    tampered = fixture.contract.model_copy(
        update={"prompt_examination_sha256": "f" * 64}
    )

    with pytest.raises(ValidationError, match="artifact hash is stale"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_project_mismatch_fails_closed(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    tampered = fixture.contract.model_copy(update={"project_id": "other"})

    with pytest.raises(ValidationError, match="one project identity"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_omitted_accepted_amendment_fails_closed(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    tampered = fixture.contract.model_copy(update={"accepted_amendment_ids": ()})

    with pytest.raises(ValidationError, match="do not exactly cover applied patches"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def _coverage_with_record(
    contract: PredesignApprovalContractV2,
    record: SourceDemandCoverageRecordV2,
    *,
    component_geometry_bindings: tuple[ComponentGeometryBindingV2, ...] | None = None,
) -> SourceDemandCoverageV2:
    coverage = contract.source_demand_coverage
    return SourceDemandCoverageV2.build(
        project_id=coverage.project_id,
        prompt_examination_sha256=coverage.prompt_examination_sha256,
        amended_brief_sha256=coverage.amended_brief_sha256,
        board_outline_sha256=coverage.board_outline_sha256,
        concept_review_sha256=coverage.concept_review_sha256,
        pre_route_inputs_sha256=coverage.pre_route_inputs_sha256,
        pre_route_feasibility_sha256=coverage.pre_route_feasibility_sha256,
        component_geometry_bindings=(
            coverage.component_geometry_bindings
            if component_geometry_bindings is None
            else component_geometry_bindings
        ),
        electrical_demand_inventory=coverage.electrical_demand_inventory,
        records=(record,),
    )


def _coverage_record_with(
    record: SourceDemandCoverageRecordV2,
    *,
    source_span_ids: tuple[str, ...] | None = None,
    component_ids: tuple[str, ...] | None = None,
) -> SourceDemandCoverageRecordV2:
    return SourceDemandCoverageRecordV2.build(
        demand_id=record.demand_id,
        source_span_ids=(
            record.source_span_ids if source_span_ids is None else source_span_ids
        ),
        claim_ids=record.claim_ids,
        anchor_ids=record.anchor_ids,
        requirement_ids=record.requirement_ids,
        component_ids=record.component_ids if component_ids is None else component_ids,
        placement_ids=record.placement_ids,
        artwork_ids=record.artwork_ids,
        asset_ids=record.asset_ids,
        concept_item_ids=record.concept_item_ids,
        feasibility_envelope_ids=record.feasibility_envelope_ids,
        feasibility_net_names=record.feasibility_net_names,
    )


def test_cross_swapped_component_geometry_bindings_are_rejected(
    tmp_path: Path,
) -> None:
    fixture = _build_contract(tmp_path, include_u2=True)
    swapped = (
        ComponentGeometryBindingV2(
            component_id="U1",
            concept_item_ids=("U2",),
            feasibility_envelope_ids=("env.u2",),
        ),
        ComponentGeometryBindingV2(
            component_id="U2",
            concept_item_ids=("U1",),
            feasibility_envelope_ids=("env.u1",),
        ),
    )
    record = fixture.contract.source_demand_coverage.records[0]
    coverage = _coverage_with_record(
        fixture.contract,
        record,
        component_geometry_bindings=swapped,
    )
    tampered = fixture.contract.model_copy(
        update={
            "source_demand_coverage": coverage,
            "source_demand_coverage_sha256": artifact_sha256(coverage),
        }
    )

    with pytest.raises(ValidationError, match="exact component identity"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_missing_source_demand_coverage_fails_closed(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    record = _coverage_record_with(
        fixture.contract.source_demand_coverage.records[0],
        component_ids=(),
    )
    coverage = _coverage_with_record(fixture.contract, record)
    tampered = fixture.contract.model_copy(
        update={
            "source_demand_coverage": coverage,
            "source_demand_coverage_sha256": artifact_sha256(coverage),
        }
    )

    with pytest.raises(ValidationError, match="binding lacks one declared"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_coverage_evidence_fingerprint_rejects_identity_mutation(
    tmp_path: Path,
) -> None:
    fixture = _build_contract(tmp_path)
    payload = fixture.contract.source_demand_coverage.records[0].model_dump(
        mode="json"
    )
    payload["component_ids"] = []

    with pytest.raises(ValidationError, match="evidence_fingerprint is stale"):
        SourceDemandCoverageRecordV2.model_validate(payload)


def test_coverage_spans_must_match_each_cited_source(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    record = _coverage_record_with(
        fixture.contract.source_demand_coverage.records[0],
        source_span_ids=(),
    )
    coverage = _coverage_with_record(fixture.contract, record)
    tampered = fixture.contract.model_copy(
        update={
            "source_demand_coverage": coverage,
            "source_demand_coverage_sha256": artifact_sha256(coverage),
        }
    )

    with pytest.raises(ValidationError, match="do not exactly match cited"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_amendment_before_hash_is_replayed_not_trusted(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    patch_payload = fixture.contract.amendment_set.patches[0].model_dump(mode="json")
    patch_payload["before_sha256"] = "f" * 64
    patch_payload["patch_fingerprint"] = fingerprint(
        {
            key: value
            for key, value in patch_payload.items()
            if key != "patch_fingerprint"
        }
    )
    amendment = BriefAmendmentPatchV2.model_validate(patch_payload)
    amendment_set = BriefAmendmentSetV2.build(
        project_id="fixture",
        prompt_examination_sha256=fixture.contract.prompt_examination_sha256,
        board_outline_sha256=fixture.contract.board_outline_sha256,
        original_brief_sha256=fixture.contract.original_brief_sha256,
        amended_brief_sha256=fixture.contract.amended_brief_sha256,
        patches=(amendment,),
    )
    tampered = fixture.contract.model_copy(
        update={
            "amendment_set": amendment_set,
            "amendment_set_sha256": artifact_sha256(amendment_set),
        }
    )

    with pytest.raises(ValidationError, match="before-value hash is stale"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_approval_traceability_is_bound_to_exact_payload(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    approver = ApproverMetadataV2.build(
        asserted_approver_id="requester.fixture",
        asserted_approver_role="requester",
        recorded_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        capture_method="interactive_assertion",
        approval_payload_sha256="f" * 64,
    )
    tampered = fixture.contract.model_copy(update={"approver": approver})

    with pytest.raises(ValidationError, match="traceability metadata is stale"):
        require_predesign_approval(tampered, artifact_root=tmp_path)


def test_naive_approver_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone offset"):
        ApproverMetadataV2.build(
            asserted_approver_id="requester.fixture",
            asserted_approver_role="requester",
            recorded_at=datetime(2026, 7, 31, 12, 0),
            capture_method="interactive_assertion",
            approval_payload_sha256=SHA_A,
        )


def test_decision_schema_rejects_free_text_fields(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    payload = fixture.contract.decisions[0].model_dump(mode="json")
    payload["accepted_decision"] = "free-text approval"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AmendmentDecisionV2.model_validate(payload)


def test_overlay_manifest_rejects_escape_path(tmp_path: Path) -> None:
    fixture = _build_contract(tmp_path)
    manifest = fixture.contract.overlay_manifests[0]

    with pytest.raises(ValidationError, match="safe relative"):
        ConceptOverlayManifestV2.build(
            project_id=manifest.project_id,
            prompt_examination_sha256=manifest.prompt_examination_sha256,
            board_outline_sha256=manifest.board_outline_sha256,
            concept_review_sha256=manifest.concept_review_sha256,
            side=manifest.side,
            svg_path="../escape.svg",
            svg_sha256=SHA_A,
            svg_bytes=1,
            png_path="front.png",
            png_sha256=SHA_B,
            png_bytes=1,
        )
