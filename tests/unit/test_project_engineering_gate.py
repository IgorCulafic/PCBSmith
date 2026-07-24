"""Automatic Phase 14 applicability and exact-part readiness gate."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_return_adjacency import _fixture, _reference_fill

import pcbsmith.cli as cli
from pcbsmith.evidence.part_discovery import (
    ExactPartDiscoveryReport,
    ExactPartDiscoveryRequest,
    InstalledPartResource,
    PartResourceRecord,
    PartResourceRole,
    PartResourceStatus,
)
from pcbsmith.kicad.board_serialization import parse_canonical_board_netlist_snapshot
from pcbsmith.kicad.return_adjacency import evaluate_return_adjacency
from pcbsmith.project_engineering_gate import evaluate_project_engineering_gate
from pcbsmith.project_engineering_gate_ir import (
    ComponentIdentityStatus,
    InventoryStatus,
    Phase14EvaluationBundle,
    Phase14FeatureDeclaration,
    Phase14RuleFamily,
    ProjectComponentProfile,
    ProjectEngineeringContext,
    ProjectEngineeringGateResult,
    ProjectGateOutcome,
)
from pcbsmith.semantic_ir import SemanticDisposition


def _return_result():
    layout, policy, graph_fill, declaration = _fixture()
    result = evaluate_return_adjacency(
        declaration,
        (_reference_fill(layout, policy, graph_fill),),
    )
    return declaration, result


def _context(*, include_feature: bool = True, layout_fingerprint: str | None = None):
    declaration, _result = _return_result()
    netlist = parse_canonical_board_netlist_snapshot(
        declaration.graph.board_netlist_snapshot_json
    )
    profiles = tuple(
        ProjectComponentProfile(
            reference=item.reference,
            identity_status=(
                ComponentIdentityStatus.EXACT_MPN
                if item.reference == "U1"
                else ComponentIdentityStatus.GENERIC_VALUE
            ),
            manufacturer="Example Semiconductor" if item.reference == "U1" else None,
            part_number="EX-1234-A" if item.reference == "U1" else None,
            required_resource_roles=(
                (PartResourceRole.DATASHEET, PartResourceRole.MODEL_3D)
                if item.reference == "U1"
                else ()
            ),
        )
        for item in netlist.components
    )
    feature = Phase14FeatureDeclaration(
        feature_id="feature:return:sig",
        family=Phase14RuleFamily.RETURN_ADJACENCY,
        subject_component_references=("U1", "U2"),
        required_declaration_ids=(declaration.declaration_id,),
        rationale="Clock-like fixture signal has a reviewed return-path declaration.",
        source_context_ids=("context:fixture-signal-class",),
    )
    return ProjectEngineeringContext.build(
        project_id="project:fixture",
        complexity_level="L1",
        board_layout_snapshot_fingerprint=(
            layout_fingerprint or declaration.board_layout_snapshot_fingerprint
        ),
        board_netlist=netlist,
        inventory_status=InventoryStatus.COMPLETE_REVIEWED,
        component_profiles=profiles,
        phase14_features=((feature,) if include_feature else ()),
        source_context_ids=("context:fixture-review",),
        reviewer_record_id="review:fixture-context",
        intended_consumer="automatic Phase 14 completion gate",
    )


def _discovery_report(
    *,
    model_status: PartResourceStatus = PartResourceStatus.INSTALLED,
    datasheet_revision: str | None = "A",
):
    request = ExactPartDiscoveryRequest(
        manufacturer="Example Semiconductor",
        part_number="EX-1234-A",
        required_roles=(PartResourceRole.DATASHEET, PartResourceRole.MODEL_3D),
        intended_consumer="automatic Phase 14 completion gate",
    )
    model = PartResourceRecord(
        role=PartResourceRole.MODEL_3D,
        status=model_status,
        **(
            {
                "installed_resource": InstalledPartResource(
                    asset_id="asset:model",
                    manufacturer="Example Semiconductor",
                    part_number="EX-1234-A",
                    role=PartResourceRole.MODEL_3D,
                    installed_asset_sha256="a" * 64,
                    installation_record_fingerprint="b" * 64,
                )
            }
            if model_status is PartResourceStatus.INSTALLED
            else {"provider_id": "fixture", "metadata_url": "https://example.com/model"}
        ),
    )
    return ExactPartDiscoveryReport.build(
        request=request,
        provider_search_complete=True,
        records=(
            PartResourceRecord(
                role=PartResourceRole.DATASHEET,
                status=PartResourceStatus.VALIDATED_CACHE,
                source_id="part:example:ex-1234-a:datasheet",
                source_sha256="c" * 64,
                revision=datasheet_revision,
            ),
            model,
        ),
    )


def test_gate_derives_applicability_consumes_real_result_and_can_be_ready() -> None:
    _declaration, return_result = _return_result()
    result = evaluate_project_engineering_gate(
        _context(),
        Phase14EvaluationBundle(return_adjacencies=(return_result,)),
        (_discovery_report(),),
    )

    assert result.outcome is ProjectGateOutcome.READY
    return_axis = next(
        item for item in result.axis_records if item.family is Phase14RuleFamily.RETURN_ADJACENCY
    )
    assert return_axis.applicability == "applicable"
    assert return_axis.disposition is SemanticDisposition.PASS
    assert all(
        item.disposition is SemanticDisposition.NOT_APPLICABLE
        for item in result.axis_records
        if item.family is not Phase14RuleFamily.RETURN_ADJACENCY
    )
    assert all(item.ready for item in result.part_resource_records)


def test_applicable_result_cannot_be_silently_omitted_or_bound_to_another_board() -> None:
    missing = evaluate_project_engineering_gate(
        _context(),
        Phase14EvaluationBundle(),
        (_discovery_report(),),
    )
    assert missing.outcome is ProjectGateOutcome.UNVERIFIED
    return_axis = missing.axis_records[-1]
    assert return_axis.disposition is SemanticDisposition.UNVERIFIED
    assert "differ" in return_axis.findings[0]

    _declaration, return_result = _return_result()
    foreign = evaluate_project_engineering_gate(
        _context(layout_fingerprint="f" * 64),
        Phase14EvaluationBundle(return_adjacencies=(return_result,)),
        (_discovery_report(),),
    )
    assert foreign.outcome is ProjectGateOutcome.UNVERIFIED
    assert "another board snapshot" in foreign.axis_records[-1].findings[0]


def test_result_without_reviewed_feature_and_incomplete_inventory_fail_closed() -> None:
    _declaration, return_result = _return_result()
    undeclared = evaluate_project_engineering_gate(
        _context(include_feature=False),
        Phase14EvaluationBundle(return_adjacencies=(return_result,)),
        (_discovery_report(),),
    )
    assert undeclared.outcome is ProjectGateOutcome.UNVERIFIED
    assert undeclared.axis_records[-1].applicability == "not_applicable"
    assert undeclared.axis_records[-1].disposition is SemanticDisposition.UNVERIFIED

    declaration, _result = _return_result()
    netlist = parse_canonical_board_netlist_snapshot(
        declaration.graph.board_netlist_snapshot_json
    )
    incomplete_context = ProjectEngineeringContext.build(
        project_id="project:incomplete",
        complexity_level="L1",
        board_layout_snapshot_fingerprint=declaration.board_layout_snapshot_fingerprint,
        board_netlist=netlist,
        inventory_status=InventoryStatus.INCOMPLETE,
        component_profiles=(),
        phase14_features=(),
        source_context_ids=(),
        reviewer_record_id=None,
        intended_consumer="automatic Phase 14 completion gate",
    )
    incomplete = evaluate_project_engineering_gate(
        incomplete_context,
        Phase14EvaluationBundle(),
    )
    assert incomplete.outcome is ProjectGateOutcome.UNVERIFIED
    assert all(item.applicability == "unresolved" for item in incomplete.axis_records)


def test_retrieved_but_uninstalled_cad_asset_remains_unverified() -> None:
    _declaration, return_result = _return_result()
    result = evaluate_project_engineering_gate(
        _context(),
        Phase14EvaluationBundle(return_adjacencies=(return_result,)),
        (_discovery_report(model_status=PartResourceStatus.LOCATED),),
    )
    assert result.outcome is ProjectGateOutcome.UNVERIFIED
    model = next(
        item for item in result.part_resource_records if item.role is PartResourceRole.MODEL_3D
    )
    assert model.ready is False
    assert model.findings == ("Required CAD asset is not installed.",)


def test_unrevisioned_exact_part_document_remains_unverified() -> None:
    _declaration, return_result = _return_result()
    result = evaluate_project_engineering_gate(
        _context(),
        Phase14EvaluationBundle(return_adjacencies=(return_result,)),
        (_discovery_report(datasheet_revision=None),),
    )
    assert result.outcome is ProjectGateOutcome.UNVERIFIED
    datasheet = next(
        item
        for item in result.part_resource_records
        if item.role is PartResourceRole.DATASHEET
    )
    assert datasheet.ready is False
    assert datasheet.findings == (
        "Required exact-part document lacks a source revision.",
    )


def test_context_and_gate_result_reject_tampering() -> None:
    _declaration, return_result = _return_result()
    result = evaluate_project_engineering_gate(
        _context(),
        Phase14EvaluationBundle(return_adjacencies=(return_result,)),
        (_discovery_report(),),
    )
    context_payload = result.context.model_dump(mode="python")
    context_payload["intended_consumer"] = "changed consumer"
    with pytest.raises(ValidationError, match="context fingerprint is stale"):
        ProjectEngineeringContext(**context_payload)

    result_payload = deepcopy(result.model_dump(mode="python"))
    result_payload["axis_records"][-1]["disposition"] = "unverified"
    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        ProjectEngineeringGateResult(**result_payload)


def test_project_gate_cli_writes_the_replay_bound_completion_artifact(
    tmp_path,
) -> None:
    _declaration, return_result = _return_result()
    context = _context()
    bundle = Phase14EvaluationBundle(return_adjacencies=(return_result,))
    discovery = _discovery_report()
    context_path = tmp_path / "context.json"
    bundle_path = tmp_path / "bundle.json"
    discovery_path = tmp_path / "discovery.json"
    output_path = tmp_path / "project-gate.json"
    context_path.write_text(context.model_dump_json(), encoding="utf-8")
    bundle_path.write_text(bundle.model_dump_json(), encoding="utf-8")
    discovery_path.write_text(discovery.model_dump_json(), encoding="utf-8")

    status = cli.main(
        [
            "project-engineering-gate",
            str(context_path),
            str(bundle_path),
            "--discovery-report",
            str(discovery_path),
            "--output",
            str(output_path),
        ]
    )

    assert status == 0
    written = ProjectEngineeringGateResult.model_validate_json(
        output_path.read_text("utf-8")
    )
    assert written.outcome is ProjectGateOutcome.READY
