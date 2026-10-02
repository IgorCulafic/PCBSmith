"""Thin working-revision adapter over the existing IF diagnosis/region/semantic owners."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import Field

from pcbsmith.iterative_fixing_ir import (
    ChangeImpactBudget,
    FindingFamily,
    FindingObservation,
    generate_dry_run_impact_report,
)
from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.native_edits import atom, child, children, object_id, reference
from pcbsmith.local_routing_repair import (
    RoutingCandidateMetrics,
    RoutingRepairRegion,
    SelectedRoutingDomain,
    run_local_routing_repair,
)
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.semantic_repair_transaction import (
    RepairGateRecord,
    SemanticRepairCandidate,
    SemanticRepairKind,
    evaluate_semantic_repair,
)


class NativeRevisionRegion(SemanticIrModel):
    initial_region: RoutingRepairRegion
    maximum_expansions: int = Field(default=0, ge=0, le=8)
    expansion_margin_mm: float = Field(default=1, gt=0, le=20)


def diagnose_native_revision(board: Path, request: Any, delta: dict[str, Any]) -> dict[str, Any]:
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    nodes = {object_id(n, i): n for i, n in enumerate(tree) if isinstance(n, list)}
    reports = []
    for index, edit in enumerate(request.edits):
        if edit.kind == "segment_add":
            reports.append(
                {
                    "kind": "requested_segment_addition",
                    "request_fingerprint": request.semantic_fingerprint(),
                    "net_name": edit.net_name,
                    "points_mm": edit.points_mm,
                    "native_checks_required": True,
                }
            )
            continue
        node = next(
            n
            for identity, n in nodes.items()
            if identity == edit.target or reference(n) == edit.target
        )
        identity = next(k for k, v in nodes.items() if v is node)
        ref = reference(node)
        if edit.kind in {"component", "reference", "model_offset"}:
            subject = f"footprint:{ref}" if edit.kind != "reference" else f"marking:reference:{ref}"
        else:
            subject = f"{node[0] if edit.kind != 'text' else 'marking'}:{identity}"
        family = (
            FindingFamily.PLACEMENT
            if edit.kind == "component"
            else FindingFamily.MARKING
            if edit.kind in {"text", "reference"}
            else FindingFamily.MODEL
            if edit.kind == "model_offset"
            else FindingFamily.ISOLATED_ZONE
            if edit.kind.startswith("zone_")
            else FindingFamily.CLEARANCE
        )
        observation = request.finding or FindingObservation(
            finding_id=f"requested-edit:{index}",
            evidence_fingerprint=request.semantic_fingerprint(),
            source_board_sha256=request.source_inputs[board.name],
            family=family,
            subject_object_ids=(subject,),
            mutable_object_ids=(subject,),
            component_refs=(ref,) if ref else (),
        )
        if request.finding and subject not in observation.subject_object_ids:
            raise ValueError("finding does not identify the requested edit target")
        budget = ChangeImpactBudget(
            maximum_mutable_object_count=request.maximum_changed_objects,
            maximum_affected_net_count=request.maximum_changed_objects,
            maximum_region_count=1,
            maximum_existing_copper_object_count=request.maximum_changed_objects,
            maximum_component_count=request.maximum_changed_objects,
            maximum_component_displacement_mm=request.maximum_displacement_mm,
            maximum_component_rotation_degrees=360,
            maximum_added_segment_count=request.maximum_changed_objects,
        )
        report = generate_dry_run_impact_report(
            board_file=board, observation=observation, budget=budget
        )
        if report.envelope.blocker_ids or report.diagnosis.unresolved_authority_ids:
            raise ValueError(
                f"repair diagnosis blocked: {report.envelope.blocker_ids} "
                f"{report.diagnosis.unresolved_authority_ids}"
            )
        reports.append(report.model_dump(mode="json"))
    return {
        "reports": reports,
        "declared_native_delta": delta["changed_ids"],
        "part_substitutions": delta.get("part_substitutions", []),
        "scope": "working revision diagnosis; engineering/review obligations remain explicit",
    }


def _bounds(node: list[Any]) -> tuple[float, float, float, float] | None:
    points = []
    if node[0] == "footprint":
        at = child(node, "at")
        x, y = float(atom(at[1])), float(atom(at[2]))
        radius = 0.0
        extent = 0.0

        # Conservatively enclose footprint-local native geometry, including markings/pads.
        def visit(item: Any) -> None:
            nonlocal radius, extent
            if not isinstance(item, list) or not item:
                return
            if item[0] in {"at", "start", "end", "center", "xy"} and len(item) >= 3:
                try:
                    radius = max(radius, math.hypot(float(atom(item[1])), float(atom(item[2]))))
                except ValueError:
                    pass
            if item[0] == "size" and len(item) >= 3:
                extent = max(extent, math.hypot(float(atom(item[1])), float(atom(item[2]))) / 2)
            for c in item[1:]:
                visit(c)

        for c in node[1:]:
            if isinstance(c, list) and c and c[0] not in {"at", "model"}:
                visit(c)
        radius += extent
        return x - radius, y - radius, x + radius, y + radius

    def walk(item: Any) -> None:
        if not isinstance(item, list) or not item:
            return
        if item[0] in {"at", "start", "mid", "end", "xy"} and len(item) >= 3:
            points.append((float(atom(item[1])), float(atom(item[2]))))
        for c in item[1:]:
            walk(c)

    walk(node)
    if not points:
        return None
    extent = 0.0
    for name in ("width", "size"):
        if children(node, name):
            extent = max(extent, float(atom(child(node, name)[1])) / 2)
    return (
        min(p[0] for p in points) - extent,
        min(p[1] for p in points) - extent,
        max(p[0] for p in points) + extent,
        max(p[1] for p in points) + extent,
    )


def verify_regional_delta(
    before: bytes, after: bytes, delta: dict[str, Any], request: Any
) -> dict[str, Any]:
    changed = set(delta["changed_ids"])
    shapes = []
    nets = set()
    for payload in (before, after):
        for i, n in enumerate(parse_sexpr(payload.decode("utf-8"))):
            if isinstance(n, list) and object_id(n, i) in changed:
                bounds = _bounds(n)
                if bounds:
                    shapes.append(bounds)
                if children(n, "net"):
                    nets.add(atom(child(n, "net")[1]))
    for region in request.protected_regions:
        if any(
            b[0] <= region.x_max_mm
            and b[2] >= region.x_min_mm
            and b[1] <= region.y_max_mm
            and b[3] >= region.y_min_mm
            for b in shapes
        ):
            raise ValueError("native delta intersects a protected mating/return/placement region")
    if request.region is None:
        return {
            "status": "object_envelope",
            "bounds": shapes,
            "protected_regions_checked": len(request.protected_regions),
        }
    plan = request.region
    domain = SelectedRoutingDomain(
        domain_id="requested-native-delta",
        validation_scope="geometry_envelope",
        net_names=tuple(nets) or ("non-copper",),
        mutable_object_ids=tuple(changed),
        protected_object_fingerprints=tuple(
            (k, v) for k, v in delta["before"].items() if k not in changed
        ),
        initial_region=plan.initial_region,
        maximum_expansions=plan.maximum_expansions,
    )

    def produce(region: RoutingRepairRegion) -> tuple[RoutingCandidateMetrics, ...]:
        outside = sum(
            not (
                b[0] >= region.x_min_mm
                and b[1] >= region.y_min_mm
                and b[2] <= region.x_max_mm
                and b[3] <= region.y_max_mm
            )
            for b in shapes
        )
        return (
            RoutingCandidateMetrics(
                candidate_id=f"region-{region.expansion_index}",
                engine_id="native-object-delta",
                validation_scope="geometry_envelope",
                region=region,
                drc_violation_count=None,
                open_count=None,
                width_failure_count=None,
                return_failure_count=None,
                protected_change_count=outside,
                unrelated_net_change_count=0,
                craft_penalty=0,
                route_length_mm=0,
                via_count=0,
                retained_directory=f"region-{region.expansion_index}",
            ),
        )

    run = run_local_routing_repair(
        domain, producer=produce, expansion_margin_mm=plan.expansion_margin_mm
    )
    return {
        "status": "accepted_envelope" if run.accepted else "blocked_envelope",
        "run": run.model_dump(mode="json"),
        "failure_class": "outside_declared_region"
        if any(a.protected_change_count for a in run.attempts)
        else None,
        "scope": "geometric envelope only; native checks run after bounded expansion",
    }


def semantic_obligations(
    board_name: str, request: Any, delta: dict[str, Any], candidate_hash: str, native_passed: bool
) -> dict[str, Any]:
    decisions = []
    kinds = set()
    for edit in request.edits:
        if edit.kind in {"text", "reference"}:
            kinds.add(SemanticRepairKind.MARKING)
        elif edit.kind == "model_offset":
            kinds.add(SemanticRepairKind.MODEL)
        elif edit.kind.startswith("zone_"):
            kinds.add(SemanticRepairKind.FILL)
    if request.mutable_zone_ids:
        kinds.add(SemanticRepairKind.FILL)
    for kind in sorted(kinds):
        # Native checking does not invent the required human/mechanical/thermal observations.
        gates = (
            RepairGateRecord(
                gate_id="drc",
                evaluated=True,
                passed=native_passed,
                evidence_id="checks/drc.json" if native_passed else None,
            ),
        )
        protected = tuple(
            (k, v) for k, v in delta["before"].items() if k not in delta["changed_ids"]
        )
        candidate = SemanticRepairCandidate(
            candidate_id=f"working:{kind}",
            kind=kind,
            source_board_sha256=request.source_inputs[board_name],
            candidate_board_sha256=candidate_hash,
            target_object_ids=tuple(delta["changed_ids"]),
            changed_object_ids=tuple(delta["changed_ids"]),
            protected_fingerprints_before=protected,
            protected_fingerprints_after=protected,
            gates=gates,
            triggered_view_ids=(),
            inspection_record_ids=(),
            retained_directory=".",
        )
        decisions.append(evaluate_semantic_repair(candidate).model_dump(mode="json"))
    return {
        "scope": "engineering/visual qualification; separate from working CAD application",
        "decisions": decisions,
        "qualification_accepted": False,
        "handover_required": True,
        "floorplan_review_required": bool(
            request.zero_ohm_links
            or request.substitutions
            or any(e.kind == "component" for e in request.edits)
        ),
        "part_substitutions": delta.get("part_substitutions", []),
        "fingerprint": fingerprint(decisions),
    }
