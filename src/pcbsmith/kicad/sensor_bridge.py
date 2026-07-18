"""KiCad adapter for opt-in exact sensor-region track bridge exceptions."""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction
from typing import Any, TypedDict, cast

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.copper_identity import track_copper_source_id
from pcbsmith.mask_geometry import (
    ApertureRelation,
    Capsule,
    Disc,
    MaskGeometry,
    Point,
    measure_geometry,
)
from pcbsmith.semantic_ir import (
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticFinding,
    SemanticLayoutResult,
    SemanticVerification,
)
from pcbsmith.sensor_bridge_ir import (
    ExactRationalMillimetres,
    SensorBridgeBudgetEvidence,
    SensorBridgeCheckKind,
    SensorBridgeDeclaration,
    SensorBridgeEvaluationResult,
    SensorBridgeTrackRecord,
    SensorBridgeTypedFinding,
)
from pcbsmith.sensor_copper_removal_ir import CopperRemovalEvaluationResult, fingerprint
from pcbsmith.sensor_isolation_ir import SensorIsolationEvaluationResult


class _Derived(TypedDict):
    isolation_result: SensorIsolationEvaluationResult
    copper_removal_result: CopperRemovalEvaluationResult
    declarations: tuple[SensorBridgeDeclaration, ...]
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    bridge_tracks: tuple[SensorBridgeTrackRecord, ...]
    budget_evidence: tuple[SensorBridgeBudgetEvidence, ...]
    geometry_fingerprint: str
    input_fingerprint: str
    findings: tuple[SemanticFinding, ...]
    typed_findings: tuple[SensorBridgeTypedFinding, ...]
    semantic_result: SemanticLayoutResult


def _exact_track_geometry(layout: BoardLayout, index: int) -> MaskGeometry | None:
    segment = layout.segments[index]
    if segment.layer not in {"F.Cu", "B.Cu"}:
        return None
    values = (segment.x1, segment.y1, segment.x2, segment.y2, segment.width_mm)
    if not all(math.isfinite(value) for value in values) or segment.width_mm <= 0.0:
        return None
    first = Point(x_mm=segment.x1, y_mm=segment.y1)
    if segment.x1 == segment.x2 and segment.y1 == segment.y2:
        return Disc(center=first, radius_mm=segment.width_mm / 2.0)
    return Capsule(
        a=first,
        b=Point(x_mm=segment.x2, y_mm=segment.y2),
        radius_mm=segment.width_mm / 2.0,
    )


def _semantic_finding(
    *,
    declaration: SensorBridgeDeclaration,
    kind: SensorBridgeCheckKind,
    disposition: SemanticDisposition,
    source_id: str | None,
    net_name: str | None,
) -> SemanticFinding:
    copper = declaration.copper_removal_declaration
    check_object = f"bridge-check:{kind.value}:{source_id or declaration.declaration_id}"
    messages = {
        SensorBridgeCheckKind.SOURCE_AUTHORIZED: (
            "Exact overlapping track source is explicitly authorized"
            if disposition is SemanticDisposition.PASS
            else "Exact overlapping track source is not explicitly authorized"
        ),
        SensorBridgeCheckKind.NET_AUTHORIZED: (
            "Exact overlapping track net is explicitly authorized"
            if disposition is SemanticDisposition.PASS
            else "Exact overlapping track net is not explicitly authorized"
        ),
        SensorBridgeCheckKind.LAYER_REMOVAL_AUTHORITY: (
            "Exact track layer and retained removal authority match"
        ),
        SensorBridgeCheckKind.TRACK_COUNT_BUDGET: (
            "Exact overlapping track count is within its reviewed maximum"
            if disposition is SemanticDisposition.PASS
            else "Exact overlapping track count exceeds its reviewed maximum"
        ),
        SensorBridgeCheckKind.TOTAL_WIDTH_BUDGET: (
            "Exact total overlapping track width is within its reviewed maximum"
            if disposition is SemanticDisposition.PASS
            else "Exact total overlapping track width exceeds its reviewed maximum"
        ),
    }
    actions = {
        SensorBridgeCheckKind.SOURCE_AUTHORIZED: "Name the exact track source or remove it",
        SensorBridgeCheckKind.NET_AUTHORIZED: "Use an allowed bridge net or remove the track",
        SensorBridgeCheckKind.LAYER_REMOVAL_AUTHORITY: "Retain the exact layer/removal binding",
        SensorBridgeCheckKind.TRACK_COUNT_BUDGET: (
            "Reduce bridge track count or re-review the limit"
        ),
        SensorBridgeCheckKind.TOTAL_WIDTH_BUDGET: (
            "Reduce total bridge width or re-review the limit"
        ),
    }
    return SemanticFinding(
        rule_id=declaration.bridge_rule.rule_id,
        authority=SemanticAuthorityClass.HARD_GEOMETRY,
        disposition=disposition,
        verification=SemanticVerification.EXACT,
        object_ids=tuple(
            item
            for item in (
                declaration.declaration_id,
                copper.declaration_id,
                source_id,
                check_object,
            )
            if item is not None
        ),
        net_refs=() if net_name is None or net_name == "<no-net>" else (net_name,),
        region_ids=(copper.region_id,),
        evidence_binding_ids=(declaration.authority_evidence_binding.binding_id,),
        message=messages[kind],
        suggested_action=actions[kind],
    )


def _append_finding(
    findings: list[SemanticFinding],
    typed: list[SensorBridgeTypedFinding],
    *,
    declaration: SensorBridgeDeclaration,
    kind: SensorBridgeCheckKind,
    passed: bool,
    source_id: str | None = None,
    net_name: str | None = None,
) -> None:
    disposition = SemanticDisposition.PASS if passed else SemanticDisposition.FAIL
    finding = _semantic_finding(
        declaration=declaration,
        kind=kind,
        disposition=disposition,
        source_id=source_id,
        net_name=net_name,
    )
    findings.append(finding)
    typed.append(
        SensorBridgeTypedFinding(
            declaration_id=declaration.declaration_id,
            check_kind=kind,
            source_id=source_id,
            disposition=cast(Any, disposition),
            semantic_finding_id=finding.finding_id,
        )
    )


def rederive_sensor_bridge_result(
    *,
    isolation_result: SensorIsolationEvaluationResult,
    copper_removal_result: CopperRemovalEvaluationResult,
    board_layout_snapshot_json: str,
    board_netlist_snapshot_json: str,
    declarations: Sequence[SensorBridgeDeclaration],
) -> _Derived:
    """Rebuild all bridge evidence from retained exact inputs."""

    isolation = SensorIsolationEvaluationResult.model_validate_json(
        isolation_result.model_dump_json()
    )
    copper_result = CopperRemovalEvaluationResult.model_validate_json(
        copper_removal_result.model_dump_json()
    )
    layout = parse_canonical_board_layout_snapshot(board_layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(board_netlist_snapshot_json)
    if board_layout_snapshot_json != canonical_board_layout_snapshot_json(layout):
        raise ValueError("board layout snapshot did not round-trip exactly")
    if board_netlist_snapshot_json != canonical_board_netlist_snapshot_json(netlist):
        raise ValueError("board netlist snapshot did not round-trip exactly")
    if (
        copper_result.isolation_result != isolation
        or copper_result.board_layout_snapshot_json != board_layout_snapshot_json
        or copper_result.board_netlist_snapshot_json != board_netlist_snapshot_json
    ):
        raise ValueError("bridge inputs differ from the retained copper-removal evaluation")

    canonical_declarations = tuple(
        sorted(
            (
                SensorBridgeDeclaration.model_validate_json(item.model_dump_json())
                for item in declarations
            ),
            key=lambda item: item.declaration_id,
        )
    )
    if not canonical_declarations:
        raise ValueError("sensor bridge evaluation requires an explicit declaration")
    if len({item.declaration_id for item in canonical_declarations}) != len(
        canonical_declarations
    ):
        raise ValueError("sensor bridge declaration identities must be unique")
    if len(
        {
            item.copper_removal_declaration.declaration_id
            for item in canonical_declarations
        }
    ) != len(canonical_declarations):
        raise ValueError("one copper-removal declaration may have only one bridge authority")

    retained_removal = {
        item.declaration_id: item for item in copper_result.declarations
    }
    for declaration in canonical_declarations:
        copper = declaration.copper_removal_declaration
        if declaration.isolation_result_fingerprint != isolation.semantic_fingerprint():
            raise ValueError("bridge declaration is bound to another isolation result")
        if retained_removal.get(copper.declaration_id) != copper:
            raise ValueError(
                "bridge declaration is not bound to an exact retained removal declaration"
            )

    findings: list[SemanticFinding] = []
    typed_findings: list[SensorBridgeTypedFinding] = []
    track_records: list[SensorBridgeTrackRecord] = []
    budgets: list[SensorBridgeBudgetEvidence] = []

    for declaration in canonical_declarations:
        copper = declaration.copper_removal_declaration
        overlaps: list[tuple[int, MaskGeometry, ExactRationalMillimetres]] = []
        for index, segment in enumerate(layout.segments):
            if segment.layer != copper.layer:
                continue
            geometry = _exact_track_geometry(layout, index)
            if geometry is None:
                continue
            if measure_geometry(geometry, copper.geometry).relation is not ApertureRelation.OVERLAP:
                continue
            overlaps.append(
                (index, geometry, ExactRationalMillimetres.from_value(segment.width_mm))
            )

        actual_width = sum(
            (item[2].as_fraction() for item in overlaps), start=Fraction(0, 1)
        )
        actual_width_quantity = ExactRationalMillimetres.from_value(actual_width)
        count_passed = len(overlaps) <= declaration.maximum_bridge_track_count
        width_passed = (
            actual_width <= declaration.maximum_total_bridge_width_mm.as_fraction()
        )
        source_ids = tuple(track_copper_source_id(index) for index, _geometry, _width in overlaps)
        budgets.append(
            SensorBridgeBudgetEvidence(
                declaration_id=declaration.declaration_id,
                bridge_track_source_ids=source_ids,
                actual_bridge_track_count=len(overlaps),
                maximum_bridge_track_count=declaration.maximum_bridge_track_count,
                actual_total_bridge_width_mm=actual_width_quantity,
                maximum_total_bridge_width_mm=declaration.maximum_total_bridge_width_mm,
                count_budget_passed=count_passed,
                total_width_budget_passed=width_passed,
            )
        )
        _append_finding(
            findings,
            typed_findings,
            declaration=declaration,
            kind=SensorBridgeCheckKind.TRACK_COUNT_BUDGET,
            passed=count_passed,
        )
        _append_finding(
            findings,
            typed_findings,
            declaration=declaration,
            kind=SensorBridgeCheckKind.TOTAL_WIDTH_BUDGET,
            passed=width_passed,
        )

        for index, geometry, width in overlaps:
            segment = layout.segments[index]
            source_id = track_copper_source_id(index)
            source_declared = source_id in declaration.allowed_track_source_ids
            net_allowed = segment.net_name in declaration.allowed_bridge_net_names
            layer_exact = segment.layer == copper.layer
            disposition = (
                SemanticDisposition.PASS
                if source_declared and net_allowed and layer_exact and count_passed and width_passed
                else SemanticDisposition.FAIL
            )
            track_records.append(
                SensorBridgeTrackRecord(
                    declaration_id=declaration.declaration_id,
                    copper_removal_declaration_id=copper.declaration_id,
                    source_id=source_id,
                    segment_index=index,
                    net_name=segment.net_name or "<no-net>",
                    layer=cast(Any, segment.layer),
                    width_mm=width,
                    geometry=geometry,
                    source_declared=source_declared,
                    net_allowed=net_allowed,
                    layer_authority_exact=layer_exact,
                    count_budget_passed=count_passed,
                    total_width_budget_passed=width_passed,
                    disposition=disposition,
                )
            )
            for kind, passed in (
                (SensorBridgeCheckKind.SOURCE_AUTHORIZED, source_declared),
                (SensorBridgeCheckKind.NET_AUTHORIZED, net_allowed),
                (SensorBridgeCheckKind.LAYER_REMOVAL_AUTHORITY, layer_exact),
            ):
                _append_finding(
                    findings,
                    typed_findings,
                    declaration=declaration,
                    kind=kind,
                    passed=passed,
                    source_id=source_id,
                    net_name=segment.net_name or "<no-net>",
                )

    canonical_tracks = tuple(
        sorted(track_records, key=lambda item: (item.declaration_id, item.source_id))
    )
    canonical_budgets = tuple(sorted(budgets, key=lambda item: item.declaration_id))
    canonical_findings = tuple(sorted(findings, key=lambda item: item.finding_id))
    canonical_typed = tuple(
        sorted(
            typed_findings,
            key=lambda item: (
                item.declaration_id,
                item.check_kind.value,
                item.source_id or "",
            ),
        )
    )
    geometry_fp = fingerprint([item.model_dump(mode="json") for item in canonical_tracks])
    declarations_fp = fingerprint(
        [item.model_dump(mode="json") for item in canonical_declarations]
    )
    layout_snapshot_fp = board_layout_snapshot_fingerprint(board_layout_snapshot_json)
    netlist_snapshot_fp = board_netlist_snapshot_fingerprint(board_netlist_snapshot_json)
    input_fp = fingerprint(
        {
            "isolation_result_fingerprint": isolation.semantic_fingerprint(),
            "copper_removal_result_fingerprint": copper_result.semantic_fingerprint(),
            "board_layout_snapshot_fingerprint": layout_snapshot_fp,
            "board_netlist_snapshot_fingerprint": netlist_snapshot_fp,
            "declarations_fingerprint": declarations_fp,
            "geometry_fingerprint": geometry_fp,
        }
    )
    semantic = SemanticLayoutResult.build(
        context_fingerprint=isolation.context.semantic_fingerprint(),
        declarations_fingerprint=declarations_fp,
        geometry_fingerprint=geometry_fp,
        findings=canonical_findings,
    )
    return {
        "isolation_result": isolation,
        "copper_removal_result": copper_result,
        "declarations": canonical_declarations,
        "board_layout_snapshot_fingerprint": layout_snapshot_fp,
        "board_netlist_snapshot_fingerprint": netlist_snapshot_fp,
        "bridge_tracks": canonical_tracks,
        "budget_evidence": canonical_budgets,
        "geometry_fingerprint": geometry_fp,
        "input_fingerprint": input_fp,
        "findings": canonical_findings,
        "typed_findings": canonical_typed,
        "semantic_result": semantic,
    }


def evaluate_sensor_bridges(
    layout: BoardLayout,
    netlist: BoardNetlist,
    isolation_result: SensorIsolationEvaluationResult,
    copper_removal_result: CopperRemovalEvaluationResult,
    declarations: Sequence[SensorBridgeDeclaration],
) -> SensorBridgeEvaluationResult:
    """Evaluate a separate, explicit bridge authority without mutating removal findings."""

    layout_snapshot = canonical_board_layout_snapshot_json(layout)
    netlist_snapshot = canonical_board_netlist_snapshot_json(netlist)
    derived = rederive_sensor_bridge_result(
        isolation_result=isolation_result,
        copper_removal_result=copper_removal_result,
        board_layout_snapshot_json=layout_snapshot,
        board_netlist_snapshot_json=netlist_snapshot,
        declarations=declarations,
    )
    return SensorBridgeEvaluationResult(
        isolation_result=derived["isolation_result"],
        copper_removal_result=derived["copper_removal_result"],
        board_layout_snapshot_json=layout_snapshot,
        board_netlist_snapshot_json=netlist_snapshot,
        board_layout_snapshot_fingerprint=derived["board_layout_snapshot_fingerprint"],
        board_netlist_snapshot_fingerprint=derived["board_netlist_snapshot_fingerprint"],
        declarations=derived["declarations"],
        bridge_tracks=derived["bridge_tracks"],
        budget_evidence=derived["budget_evidence"],
        geometry_fingerprint=derived["geometry_fingerprint"],
        input_fingerprint=derived["input_fingerprint"],
        findings=derived["findings"],
        typed_findings=derived["typed_findings"],
        semantic_result=derived["semantic_result"],
    )
