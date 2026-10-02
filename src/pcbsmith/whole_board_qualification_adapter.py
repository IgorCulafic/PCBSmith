"""Production W7 adapter deriving gates from revision-bound evidence objects."""

from __future__ import annotations

from collections.abc import Sequence

from pcbsmith.automatic_review_gate import AutomaticReviewGate
from pcbsmith.kicad.final_fill_adapter import FillReachability, KiCadFinalFillSnapshot
from pcbsmith.kicad.final_fill_connectivity import KiCadFinalFillConnectivityObservation
from pcbsmith.kicad.final_fill_thermal import (
    KiCadThermalSpokeAudit,
    ThermalSpokeDisposition,
)
from pcbsmith.kicad.reference_continuity import ReferenceContinuityEvidence
from pcbsmith.kicad.routing_evidence import KiCadDrcEvidence, SavedBoardRoutingEvidence
from pcbsmith.manufacturing_ir import (
    CurrentPathAuthority,
    CurrentPathRecord,
    FabricationElectricalProfile,
)
from pcbsmith.power_topology_ir import BoardPowerTopology
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.whole_board_qualification import (
    QualificationDisposition,
    QualificationGate,
    RoutingCraftAssessment,
    WholeBoardQualification,
)


def qualify_production_board(
    *,
    case_id: str,
    refilled_board_sha256: str,
    drc_evidence: KiCadDrcEvidence | None,
    drc_board_sha256: str | None,
    routing_evidence: SavedBoardRoutingEvidence | None,
    fill_snapshot: KiCadFinalFillSnapshot | None,
    fill_connectivity: KiCadFinalFillConnectivityObservation | None,
    thermal_audit: KiCadThermalSpokeAudit | None,
    topology: BoardPowerTopology | None,
    current_paths: Sequence[CurrentPathRecord] = (),
    fabrication_profile: FabricationElectricalProfile | None = None,
    reference_continuity: ReferenceContinuityEvidence | None = None,
    automatic_review: AutomaticReviewGate | None = None,
    craft: RoutingCraftAssessment | None = None,
) -> WholeBoardQualification:
    """Build all required W7 gates without accepting caller-authored gate dispositions."""

    paths = tuple(current_paths)
    _require_hashes(
        refilled_board_sha256,
        routing_evidence,
        fill_snapshot,
        fill_connectivity,
        thermal_audit,
        topology,
        paths,
        automatic_review,
        craft,
    )
    gates = (
        _drc_gate(refilled_board_sha256, drc_evidence, drc_board_sha256),
        _routing_gate(refilled_board_sha256, routing_evidence),
        _fill_gate(refilled_board_sha256, fill_snapshot, fill_connectivity, thermal_audit),
        _current_path_gate(refilled_board_sha256, topology, paths),
        _current_environment_gate(refilled_board_sha256, topology, paths, fabrication_profile),
        _reference_gate(refilled_board_sha256, topology, reference_continuity),
        _topology_gate(refilled_board_sha256, topology),
        _marking_gate(refilled_board_sha256, automatic_review),
        _visual_gate(refilled_board_sha256, automatic_review),
    )
    retained_craft = craft or RoutingCraftAssessment(
        board_sha256=refilled_board_sha256,
        acute_bend_count=0,
        needless_bend_count=0,
        excessive_jog_count=0,
        unnecessary_via_count=0,
        long_detour_count=0,
        bus_disorder_count=0,
        congested_region_count=0,
        hard_rule_finding_ids=("craft_evidence_missing",),
        hard_rule_authority_ids=("pcbsmith:w7-production-adapter",),
        repair_recommended=False,
        rank_cost_units=0,
    )
    return WholeBoardQualification.build(
        case_id=case_id,
        refilled_board_sha256=refilled_board_sha256,
        gates=gates,
        craft=retained_craft,
    )


def _require_hashes(board: str, *evidence: object) -> None:
    for item in evidence:
        if item is None:
            continue
        if isinstance(item, tuple):
            if any(record.board_sha256 != board for record in item):
                raise ValueError("current-path evidence targets another board revision")
            continue
        candidate = getattr(item, "board_sha256", None)
        if candidate is None and isinstance(item, KiCadFinalFillSnapshot):
            candidate = item.filled_board_sha256
        if candidate is not None and candidate != board:
            raise ValueError("qualification evidence targets another board revision")


def _gate(
    board: str,
    gate_id: str,
    disposition: QualificationDisposition,
    *,
    count: int,
    evidence: tuple[str, ...] = (),
    findings: tuple[str, ...] = (),
    applicable: bool = True,
    notes: tuple[str, ...] = (),
) -> QualificationGate:
    return QualificationGate(
        gate_id=gate_id,
        board_sha256=board,
        disposition=disposition,
        applicable=applicable,
        evaluated_object_count=count,
        evidence_fingerprints=evidence,
        finding_ids=findings,
        notes=notes,
    )


def _drc_gate(
    board: str, evidence: KiCadDrcEvidence | None, bound: str | None,
) -> QualificationGate:
    if evidence is None or bound is None:
        return _gate(board, "kicad_integrity", QualificationDisposition.UNVERIFIED, count=0)
    if bound != board:
        raise ValueError("KiCad DRC report targets another board revision")
    findings = tuple(
        name
        for name, count in (
            ("kicad_violations", evidence.violation_count),
            ("kicad_unconnected_items", evidence.unconnected_item_count),
            ("kicad_schematic_parity", evidence.schematic_parity_count),
        )
        if count
    )
    return _gate(
        board,
        "kicad_integrity",
        QualificationDisposition.FAIL if findings else QualificationDisposition.PASS,
        count=1,
        evidence=(evidence.evidence_fingerprint,),
        findings=findings,
    )


def _routing_gate(board: str, evidence: SavedBoardRoutingEvidence | None) -> QualificationGate:
    if evidence is None:
        return _gate(
            board, "routed_copper_carrier_coverage", QualificationDisposition.UNVERIFIED, count=0
        )
    passed = evidence.routable_net_count > 0 and evidence.copper_carrier_net_coverage == 1.0
    return _gate(
        board,
        "routed_copper_carrier_coverage",
        QualificationDisposition.PASS if passed else QualificationDisposition.FAIL,
        count=max(1, evidence.routable_net_count),
        evidence=(evidence.evidence_fingerprint,),
        findings=()
        if passed
        else tuple(f"uncovered_net:{name}" for name in evidence.uncovered_net_names)
        or ("no_routable_net_evaluated",),
    )


def _fill_gate(
    board: str, snapshot: KiCadFinalFillSnapshot | None,
    observation: KiCadFinalFillConnectivityObservation | None,
    thermal: KiCadThermalSpokeAudit | None,
) -> QualificationGate:
    gate_id = "filled_region_connectivity"
    if snapshot is None or observation is None or thermal is None:
        return _gate(board, gate_id, QualificationDisposition.UNVERIFIED, count=0)
    if not snapshot.regions:
        return _gate(
            board, gate_id, QualificationDisposition.NOT_APPLICABLE, count=0, applicable=False
        )
    findings = tuple(
        [
            f"floating_region:{item.region_id}"
            for item in snapshot.regions
            if item.reachability is FillReachability.FLOATING
        ]
        + [f"starved_thermal:{item}" for item in thermal.starved_thermal_violation_ids]
    )
    unresolved = bool(snapshot.unverified_region_ids) or (
        thermal.disposition is ThermalSpokeDisposition.UNVERIFIED
    )
    disposition = (
        QualificationDisposition.FAIL
        if findings
        else QualificationDisposition.UNVERIFIED
        if unresolved
        else QualificationDisposition.PASS
    )
    return _gate(
        board,
        gate_id,
        disposition,
        count=len(snapshot.regions) + thermal.evaluated_object_count,
        evidence=(
            snapshot.snapshot_fingerprint,
            fingerprint(observation.model_dump(mode="json")),
            thermal.evidence_fingerprint,
        ),
        findings=findings,
    )


def _current_path_gate(
    board: str, topology: BoardPowerTopology | None, paths: tuple[CurrentPathRecord, ...],
) -> QualificationGate:
    gate_id = "current_path_ledger"
    if topology is None:
        return _gate(board, gate_id, QualificationDisposition.UNVERIFIED, count=0)
    if topology.applicability == "unresolved":
        return _gate(
            board,
            gate_id,
            QualificationDisposition.UNVERIFIED,
            count=0,
            evidence=(topology.topology_fingerprint,),
            notes=(topology.applicability_rationale or "topology_unresolved",),
        )
    if not topology.paths:
        return _gate(
            board, gate_id, QualificationDisposition.NOT_APPLICABLE, count=0, applicable=False
        )
    expected = {item.path_id for item in topology.paths}
    actual = {item.path_id for item in paths}
    if len(actual) != len(paths):
        raise ValueError("current-path evidence identities must be unique")
    missing = tuple(sorted(expected - actual))
    extra = tuple(sorted(actual - expected))
    if extra:
        raise ValueError("current-path evidence contains undeclared paths")
    unresolved = tuple(
        item.path_id for item in paths if item.authority is not CurrentPathAuthority.VERIFIED
    )
    disposition = (
        QualificationDisposition.PASS
        if not missing and not unresolved
        else QualificationDisposition.UNVERIFIED
    )
    return _gate(
        board,
        gate_id,
        disposition,
        count=len(paths),
        evidence=tuple(item.record_fingerprint for item in paths),
        findings=(),
        notes=tuple(f"missing_path:{item}" for item in missing)
        + tuple(f"unverified_path:{item}" for item in unresolved),
    )


def _current_environment_gate(
    board: str, topology: BoardPowerTopology | None, paths: tuple[CurrentPathRecord, ...],
    profile: FabricationElectricalProfile | None,
) -> QualificationGate:
    gate_id = "current_environment_model"
    if topology is not None and topology.applicability == "unresolved":
        return _gate(
            board,
            gate_id,
            QualificationDisposition.UNVERIFIED,
            count=0,
            evidence=(topology.topology_fingerprint,),
            notes=(topology.applicability_rationale or "topology_unresolved",),
        )
    if topology is not None and not any(item.requires_ampacity_claim for item in topology.paths):
        return _gate(
            board, gate_id, QualificationDisposition.NOT_APPLICABLE, count=0, applicable=False
        )
    evidence = () if profile is None else (profile.profile_fingerprint,)
    notes: tuple[str, ...] = ("condition_matched_temperature_evaluation_unavailable",)
    if profile is None:
        notes += ("fabrication_electrical_profile_missing",)
    if not paths:
        notes += ("current_path_records_missing",)
    return _gate(
        board,
        gate_id,
        QualificationDisposition.UNVERIFIED,
        count=len(paths),
        evidence=evidence,
        notes=notes,
    )


def _reference_gate(
    board: str, topology: BoardPowerTopology | None, evidence: ReferenceContinuityEvidence | None,
) -> QualificationGate:
    gate_id = "reference_continuity"
    if topology is not None and topology.applicability == "unresolved":
        return _gate(
            board,
            gate_id,
            QualificationDisposition.UNVERIFIED,
            count=0,
            evidence=(topology.topology_fingerprint,),
            notes=(topology.applicability_rationale or "topology_unresolved",),
        )
    if topology is not None and not topology.return_relationships:
        return _gate(
            board, gate_id, QualificationDisposition.NOT_APPLICABLE, count=0, applicable=False
        )
    if evidence is None:
        return _gate(board, gate_id, QualificationDisposition.UNVERIFIED, count=0)
    findings = tuple(
        sorted(str(item.get("finding_id", fingerprint(item))) for item in evidence.findings)
    )
    disposition = (
        QualificationDisposition.PASS
        if evidence.exact_pass_authorized
        else QualificationDisposition.FAIL
        if findings and "unverified" not in evidence.disposition
        else QualificationDisposition.UNVERIFIED
    )
    return _gate(
        board,
        gate_id,
        disposition,
        count=evidence.signal_segment_count + evidence.signal_transition_count,
        evidence=(evidence.evidence_fingerprint,),
        findings=findings if disposition is QualificationDisposition.FAIL else (),
    )


def _topology_gate(board: str, topology: BoardPowerTopology | None) -> QualificationGate:
    if topology is None:
        return _gate(board, "functional_topology", QualificationDisposition.UNVERIFIED, count=0)
    if topology.applicability == "unresolved":
        return _gate(
            board,
            "functional_topology",
            QualificationDisposition.UNVERIFIED,
            count=0,
            evidence=(topology.topology_fingerprint,),
            notes=(topology.applicability_rationale or "topology_unresolved",),
        )
    if topology.applicability == "not_applicable":
        return _gate(
            board,
            "functional_topology",
            QualificationDisposition.NOT_APPLICABLE,
            count=0,
            applicable=False,
            evidence=(topology.topology_fingerprint,),
            notes=(topology.applicability_rationale or "topology_not_applicable",),
        )
    return _gate(
        board,
        "functional_topology",
        QualificationDisposition.PASS,
        count=max(1, len(topology.terminals) + len(topology.regions) + len(topology.paths)),
        evidence=(topology.topology_fingerprint,),
    )


def _marking_gate(board: str, review: AutomaticReviewGate | None) -> QualificationGate:
    if review is None:
        return _gate(board, "production_marking", QualificationDisposition.UNVERIFIED, count=0)
    audit = review.marking_audit
    disposition = (
        QualificationDisposition.PASS
        if review.exact_gate_passed
        else QualificationDisposition.FAIL
        if audit.finding_ids
        else QualificationDisposition.UNVERIFIED
    )
    return _gate(
        board,
        "production_marking",
        disposition,
        count=audit.inspected_mark_count,
        evidence=(audit.evidence_fingerprint,),
        findings=audit.finding_ids if disposition is QualificationDisposition.FAIL else (),
    )


def _visual_gate(board: str, review: AutomaticReviewGate | None) -> QualificationGate:
    if review is None:
        return _gate(board, "visual_review", QualificationDisposition.UNVERIFIED, count=0)
    visual_blockers = tuple(
        item
        for item in review.blocker_ids
        if not item.startswith("production_marking:")
        and not item.startswith("production_marking_unverified:")
    )
    hard = tuple(
        item
        for item in visual_blockers
        if not item.startswith("visual_inspection_unverified:")
        and not item.startswith("visual_package_unverified:")
        and not item.startswith("visual_workflow_unverified:")
    )
    unresolved = tuple(item for item in visual_blockers if item not in hard)
    disposition = (
        QualificationDisposition.FAIL
        if hard
        else QualificationDisposition.UNVERIFIED
        if unresolved
        else QualificationDisposition.PASS
    )
    return _gate(
        board,
        "visual_review",
        disposition,
        count=len(review.required_artifact_ids),
        evidence=(review.visual_manifest_fingerprint,),
        findings=hard,
        notes=unresolved,
    )


__all__ = ["qualify_production_board"]
