"""Prepare replayable predesign inputs from a declarative circuit and reviewed engineering.

This adapter computes geometry, feasibility, alternatives, support and power reviews.
It never supplies observations or authorizes itself: the caller supplies a source-bound
review assertion after inspecting the retained inputs/overlays. Publication still uses
the existing registered generation boundary.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pcbsmith.design_readiness import require_design_readiness
from pcbsmith.engineering_preview import EngineeringInputs, evaluate_engineering_inputs
from pcbsmith.kicad.component_readiness import (
    inspect_component_readiness,
    require_component_readiness_snapshot,
)
from pcbsmith.kicad.concept_review import ConceptItem, examine_concept, write_concept_review_package
from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.native_project import NativeProjectSpec, require_native_input_closure
from pcbsmith.predesign_contract import (
    BriefAmendmentSetV2,
    ComponentGeometryBindingV2,
    ConceptOverlayManifestV2,
    ElectricalDemandInventoryRecordV2,
    PredesignApprovalContractV2,
    PreRouteFeasibilityInputsV2,
    SourceDemandCoverageRecordV2,
    SourceDemandCoverageV2,
    artifact_sha256,
)
from pcbsmith.production_readiness import (
    PredesignReadinessBundle,
    ReadinessEvidenceFile,
    require_predesign_bundle,
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
from pcbsmith.prompt_examiner import ExaminedClaim, PromptResolution, SourceSpan, examine_prompt
from pcbsmith.workflow_feasibility import NeckSection, PlacementEnvelope, PreRouteNetDemand


def prepare_predesign_inputs(spec_file: Path, project: Path, output: Path) -> dict[str, Any]:
    from pcbsmith.board_job import require_library_worker
    from pcbsmith.kicad.project_dependencies import project_footprint_scope

    require_library_worker()
    with project_footprint_scope(project):
        return _prepare_predesign_inputs(spec_file, project, output)


def _prepare_predesign_inputs(spec_file: Path, project: Path, output: Path) -> dict[str, Any]:
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    if output.exists():
        raise ValueError("Predesign preparation requires a fresh output directory")
    spec = NativeProjectSpec.model_validate_json(spec_file.read_text(encoding="utf-8"))
    retained = NativeProjectSpec.model_validate_json(
        (project / "design-spec.json").read_text(encoding="utf-8")
    )
    if spec != retained:
        raise ValueError("Native project specification differs from preparation input")
    netlist = require_native_input_closure(spec, project)
    if not any(
        len(net.nodes) >= 2 and not net.name.startswith("unconnected-") for net in netlist.nets
    ):
        raise ValueError("Predesign routing feasibility requires at least one multi-terminal net")
    component_readiness = inspect_component_readiness(spec, project)
    mounting_by_ref = {
        item["reference"]: item["mounting"] for item in component_readiness["components"]
    }
    output.mkdir(parents=True)
    (output / "component-readiness.json").write_text(
        json.dumps(component_readiness, indent=2) + "\n", encoding="utf-8"
    )
    outline = (
        (0.0, 0.0),
        (spec.width_mm, 0.0),
        (spec.width_mm, spec.height_mm),
        (0.0, spec.height_mm),
    )
    (output / "outline.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{spec.width_mm}mm" '
        f'height="{spec.height_mm}mm" viewBox="0 0 {spec.width_mm} {spec.height_mm}">'
        f'<rect width="{spec.width_mm}" height="{spec.height_mm}" '
        'fill="none" stroke="black" stroke-width="0.1"/></svg>',
        encoding="utf-8",
    )

    def val(key: str, value: str | float | int | bool, unit: str | None = None) -> RequirementValue:
        return RequirementValue(
            requirement_id=key,
            value=value,
            unit=unit,
            source="engineering",
            resolution="derived",
            source_text=spec.user_request,
            rationale="Engineering selection recorded in exact design-spec.json; user "
            "request preserved separately.",
        )

    brief = normalize_project_brief(
        ProjectBriefDraft(
            project_id=spec.project_id,
            title=spec.title,
            original_text=spec.user_request,
            functional_requirements=(val("function.request", spec.user_request),),
            electrical_requirements=(
                val(
                    "electrical.pin-intent",
                    "Per-pin nets and deliberate no-connects retained in "
                    "design-spec.json and native XML",
                ),
            ),
            manufacturing_requirements=(
                val("manufacturing.profile", spec.profile.model_dump_json()),
            ),
            mechanics=MechanicalRequirement(
                maximum_width_mm=val("mechanics.width", spec.width_mm, "mm"),
                maximum_height_mm=val("mechanics.height", spec.height_mm, "mm"),
                board_thickness_mm=val(
                    "mechanics.thickness", spec.profile.geometry.board_thickness_mm, "mm"
                ),
                layer_count=val("manufacturing.layers", spec.profile.geometry.copper_layer_count),
                outline_asset_id="outline",
            ),
            components=tuple(
                ComponentRequirement(
                    component_id=p.reference,
                    quantity=1,
                    role=p.role,
                    selection=p.mpn,
                    footprint_id=p.footprint,
                    side="front",
                    mounting=mounting_by_ref[p.reference],
                    source="engineering",
                    resolution="derived",
                )
                for p in spec.parts
            ),
            placements=tuple(
                PlacementRequirement(
                    placement_id="placement." + p.reference.lower(),
                    subject=p.reference,
                    relation=f"Anchor {p.board_at}",
                    side="front",
                    anchor_semantics="native footprint origin",
                    tolerance_mm=0.01,
                    resolution="derived",
                    source_text="Retained design-spec.json",
                )
                for p in spec.parts
            ),
            artwork=(),
            assets=(
                AssetReference(
                    asset_id="outline",
                    purpose="outline",
                    source_file="outline.svg",
                    source_sha256=file_sha256(output / "outline.svg"),
                    physical_width_mm=spec.width_mm,
                ),
            ),
            engineering_freedoms=(
                "Component values and implementation chosen by assistant within the "
                "requested function.",
            ),
        )
    )
    span = SourceSpan(
        span_id="request", start=0, end=len(spec.user_request), exact_text=spec.user_request
    )
    prompt = examine_prompt(
        project_id=spec.project_id,
        original_text=spec.user_request,
        spans=(span,),
        claims=(
            ExaminedClaim(
                claim_id="claim.request",
                field_path="functional_requirements",
                value=spec.user_request,
                resolution=PromptResolution.DERIVED,
                source_span_ids=("request",),
                rationale="User function plus explicitly identified engineering "
                "defaults from the retained request.",
            ),
        ),
        anchors=(),
    )
    concept = examine_concept(
        spec.project_id,
        outline,
        tuple(
            ConceptItem(
                item_id=p.reference,
                label=p.reference + " " + p.value,
                side="front",
                kind="footprint",
                anchor_mm=p.board_at[:2],
                rotation_deg=p.board_at[2],
                footprint_id=p.footprint,
                containment="courtyard",
                requirement_resolution="derived",
                note="Assistant engineering placement; human visual acceptance not asserted.",
            )
            for p in spec.parts
        ),
        tight_clearance_mm=0.5,
    )
    from shapely.geometry import Polygon

    conflicts = []
    for index, a in enumerate(concept.items):
        for b in concept.items[index + 1 :]:
            if Polygon(a.envelope).intersection(Polygon(b.envelope)).area > 1e-8:
                conflicts.append(
                    f"Overlapping component courtyards: {a.item.item_id}/{b.item.item_id}"
                )
    if conflicts:
        concept = concept.model_copy(
            update=dict(outcome="blocked", hard_conflicts=tuple(conflicts))
        )
    write_concept_review_package(concept, output)
    from pcbsmith.kicad.floorplan import write_floorplan

    write_floorplan(
        concept, output, {p.reference: p.role for p in spec.parts}, spec.floorplan_corridors
    )
    ph, bh, ch = artifact_sha256(prompt), artifact_sha256(brief), artifact_sha256(concept)
    envelopes = tuple(
        PlacementEnvelope(
            envelope_id="env." + i.item.item_id,
            subject_id=i.item.item_id,
            polygon=i.envelope,
            source_geometry_sha256=ch,
        )
        for i in concept.items
    )
    # Conservatively assign every net to one whole-width cross-section. This is only
    # a coarse capacity bound; it is never route existence/return-path evidence.
    neck = NeckSection(
        neck_id="whole-width",
        usable_width_mm=spec.width_mm - 2 * spec.profile.fab_spacing.minimum_copper_to_edge_mm,
        routing_layers=("F.Cu", "B.Cu"),
        capacity_quantum_mm=0.1,
        source_geometry_sha256=concept.outline_sha256,
    )
    demands = tuple(
        PreRouteNetDemand(
            net_name=n.name,
            terminal_ids=tuple(ref + "/" + pin for ref, pin in n.nodes),
            trace_width_mm=spec.profile.geometry.default_power_trace_width_mm,
            clearance_mm=spec.profile.fab_spacing.minimum_copper_clearance_mm,
            candidate_neck_ids=(neck.neck_id,),
            net_class_id="conservative-all-nets",
            priority=i + 1,
        )
        for i, n in enumerate(netlist.nets)
        if not n.name.startswith("unconnected-") and len(n.nodes) >= 2
    )
    inputs = PreRouteFeasibilityInputsV2.build(
        project_id=spec.project_id,
        prompt_examination_sha256=ph,
        amended_brief_sha256=bh,
        board_outline=outline,
        board_outline_sha256=concept.outline_sha256,
        keepout_polygons=(),
        envelopes=envelopes,
        necks=(neck,),
        net_demands=demands,
    )
    feasible = inputs.evaluate()
    ih, fh = artifact_sha256(inputs), artifact_sha256(feasible)
    amendment = BriefAmendmentSetV2.build(
        project_id=spec.project_id,
        prompt_examination_sha256=ph,
        board_outline_sha256=concept.outline_sha256,
        original_brief_sha256=bh,
        amended_brief_sha256=bh,
        patches=(),
    )
    reqids = tuple(
        v.requirement_id
        for v in (
            *brief.draft.functional_requirements,
            *brief.draft.electrical_requirements,
            *brief.draft.manufacturing_requirements,
            brief.draft.mechanics.maximum_width_mm,
            brief.draft.mechanics.maximum_height_mm,
            brief.draft.mechanics.board_thickness_mm,
            brief.draft.mechanics.layer_count,
        )
    )
    record = SourceDemandCoverageRecordV2.build(
        demand_id="requested-circuit",
        source_span_ids=("request",),
        claim_ids=("claim.request",),
        anchor_ids=(),
        requirement_ids=reqids,
        component_ids=tuple(p.reference for p in spec.parts),
        placement_ids=tuple(p.placement_id for p in brief.draft.placements),
        asset_ids=("outline",),
        concept_item_ids=tuple(p.reference for p in spec.parts),
        feasibility_envelope_ids=tuple(e.envelope_id for e in envelopes),
        feasibility_net_names=tuple(n.net_name for n in demands),
    )
    coverage = SourceDemandCoverageV2.build(
        project_id=spec.project_id,
        prompt_examination_sha256=ph,
        amended_brief_sha256=bh,
        board_outline_sha256=concept.outline_sha256,
        concept_review_sha256=ch,
        pre_route_inputs_sha256=ih,
        pre_route_feasibility_sha256=fh,
        component_geometry_bindings=tuple(
            ComponentGeometryBindingV2(
                component_id=p.reference,
                concept_item_ids=(p.reference,),
                feasibility_envelope_ids=("env." + p.reference,),
            )
            for p in spec.parts
        ),
        electrical_demand_inventory=tuple(
            ElectricalDemandInventoryRecordV2(
                net_name=n.net_name,
                terminal_ids=n.terminal_ids,
                source_claim_ids=("claim.request",),
                source_requirement_ids=("function.request",),
            )
            for n in demands
        ),
        records=(record,),
    )
    overlays = tuple(
        ConceptOverlayManifestV2.build(
            project_id=spec.project_id,
            prompt_examination_sha256=ph,
            board_outline_sha256=concept.outline_sha256,
            concept_review_sha256=ch,
            side=side,
            svg_path=f"engineering-overlay-{side}.svg",
            svg_sha256=file_sha256(output / f"engineering-overlay-{side}.svg"),
            svg_bytes=(output / f"engineering-overlay-{side}.svg").stat().st_size,
            png_path=f"engineering-overlay-{side}.png",
            png_sha256=file_sha256(output / f"engineering-overlay-{side}.png"),
            png_bytes=(output / f"engineering-overlay-{side}.png").stat().st_size,
        )
        for side in ("front", "back")
    )
    fields = dict(
        project_id=spec.project_id,
        prompt_examination=prompt,
        original_brief=brief,
        amended_brief=brief,
        amendment_set=amendment,
        decisions=(),
        concept_review=concept,
        concept_tight_clearance_mm=0.5,
        overlay_manifests=overlays,
        pre_route_inputs=inputs,
        pre_route_feasibility=feasible,
        source_demand_coverage=coverage,
    )
    payload = {
        k: [x.model_dump(mode="json") for x in v]
        if isinstance(v, tuple)
        else v.model_dump(mode="json")
        if hasattr(v, "model_dump")
        else v
        for k, v in fields.items()
    }
    payload["source_spec_sha256"] = file_sha256(spec_file)
    payload["native_project_path"] = str(project.resolve())
    payload["component_readiness_sha256"] = file_sha256(output / "component-readiness.json")
    (output / "prepared-inputs.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    from pcbsmith.mandatory_review import APPLICABILITY_TOPICS, COMPONENT_TOPICS

    # This worklist deliberately contains no approval or inferred N/A decisions.
    template = {
        "schema_id": "pcbsmith-mandatory-review-v1",
        "brief_sha256": bh,
        "component_readiness_sha256": payload["component_readiness_sha256"],
        "reviewer": "",
        "review_reference": "",
        "applicability": {
            topic: {"disposition": "unresolved", "rationale": "", "evidence_ids": []}
            for topic in APPLICABILITY_TOPICS
        },
        "components": {
            part.reference: {
                "observations": {topic: "" for topic in sorted(COMPONENT_TOPICS)},
                "evidence_ids": [],
            }
            for part in spec.parts
        },
        "deliverables": {
            role: ""
            for role in (
                "pcb",
                "schematic",
                "project",
                "interactive_bom",
                "floorplan",
                "floorplan_preview",
            )
        },
        "required_native_rules": {"erc": [], "drc": []},
        "minimum_board_rules": {
            "min_clearance": spec.profile.fab_spacing.minimum_copper_clearance_mm,
            "min_track_width": spec.profile.geometry.minimum_trace_width_mm,
            "min_copper_edge_clearance": spec.profile.fab_spacing.minimum_copper_to_edge_mm,
        },
        "rule_exceptions": [],
    }
    (output / "mandatory-review.template.json").write_text(
        json.dumps(template, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def approve_prepared_predesign(
    root: Path, engineering_file: Path, assertion_file: Path
) -> PredesignReadinessBundle:
    from pcbsmith.board_job import require_library_worker
    from pcbsmith.kicad.project_dependencies import project_footprint_scope

    require_library_worker()
    fields = json.loads((root / "prepared-inputs.json").read_text(encoding="utf-8"))
    project = fields.get("native_project_path")
    if project:
        with project_footprint_scope(Path(project)):
            return _approve_prepared_predesign(root, engineering_file, assertion_file)
    return _approve_prepared_predesign(root, engineering_file, assertion_file)


def _approve_prepared_predesign(
    root: Path, engineering_file: Path, assertion_file: Path
) -> PredesignReadinessBundle:
    """Validate a supplied review, replay all evaluators, then seal exact evidence."""
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    prepared = root / "prepared-inputs.json"
    assertion = json.loads(assertion_file.read_text(encoding="utf-8"))
    if assertion["prepared_inputs_sha256"] != file_sha256(prepared) or assertion[
        "engineering_sha256"
    ] != file_sha256(engineering_file):
        raise ValueError("Reviewer assertion targets stale inputs")
    if assertion["disposition"] != "approve_predesign" or not assertion["rationale"].strip():
        raise ValueError("Predesign review is not approved")
    fields = json.loads(prepared.read_text(encoding="utf-8"))
    fields.pop("source_spec_sha256")
    project_path = fields.pop("native_project_path", None)
    component_hash = fields.pop("component_readiness_sha256", None)
    if not project_path or not component_hash:
        raise ValueError("Prepared review lacks current component inventory; refresh preparation")
    require_component_readiness_snapshot(
        root, Path(project_path), component_hash, require_selected_models=True
    )
    # The contract owns structural/geometry/overlay replay. Reconstruct through its
    # model types, not model_construct or copied positive outcomes.
    annotations = PredesignApprovalContractV2.model_fields
    for key in (
        "prompt_examination",
        "original_brief",
        "amended_brief",
        "amendment_set",
        "concept_review",
        "pre_route_inputs",
        "pre_route_feasibility",
        "source_demand_coverage",
    ):
        model = annotations[key].annotation
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise TypeError(f"Predesign field {key} no longer has a model annotation")
        fields[key] = model.model_validate(fields[key])
    fields["overlay_manifests"] = tuple(
        ConceptOverlayManifestV2.model_validate(v) for v in fields["overlay_manifests"]
    )
    fields["decisions"] = ()
    approval = PredesignApprovalContractV2.build(
        **fields,
        asserted_approver_id=assertion["reviewer_id"],
        asserted_approver_role=assertion["reviewer_role"],
        recorded_at=datetime.fromisoformat(assertion["recorded_at"]),
        capture_method="interactive_assertion",
    )
    engineering = EngineeringInputs.model_validate_json(
        engineering_file.read_text(encoding="utf-8")
    )
    refs = {r.component_id for r in approval.amended_brief.draft.components}
    readiness = evaluate_engineering_inputs(
        engineering, expected_references=refs, artifact_root=root
    )
    require_design_readiness(readiness)
    bundle = PredesignReadinessBundle(
        approval=approval,
        readiness=readiness,
        evidence_files={
            **engineering.evidence_files,
            "component-readiness": ReadinessEvidenceFile(
                relative_path="component-readiness.json",
                sha256=file_sha256(root / "component-readiness.json"),
            ),
        },
    )
    from pcbsmith.mandatory_review import require_mandatory_review, require_recurring_deliverables

    require_recurring_deliverables(require_mandatory_review(bundle, root))
    from pcbsmith.kicad.floorplan import FILES, review_floorplan

    visual_assertion = assertion.get("floorplan_review", {})
    review_floorplan(root, approval.concept_review, visual_assertion)
    review_path = root / "floorplan-review.json"
    if review_path.exists():
        raise ValueError("floorplan review already retained; use a new preparation revision")
    review_path.write_text(json.dumps(visual_assertion, indent=2) + "\n", encoding="utf-8")
    bundle = bundle.model_copy(
        update={
            "evidence_files": {
                **bundle.evidence_files,
                "component-readiness": ReadinessEvidenceFile(
                    relative_path="component-readiness.json",
                    sha256=file_sha256(root / "component-readiness.json"),
                ),
                **{
                    "floorplan." + name: ReadinessEvidenceFile(
                        relative_path=name, sha256=file_sha256(root / name)
                    )
                    for name in FILES
                },
            }
        }
    )
    require_predesign_bundle(bundle, root)
    (root / "predesign.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("prepare", "refresh"):
        p = sub.add_parser(operation)
        p.add_argument("spec", type=Path)
        p.add_argument("project", type=Path)
        p.add_argument("output", type=Path)
    for operation in ("approve", "reapprove"):
        p = sub.add_parser(operation)
        p.add_argument("root", type=Path)
        p.add_argument("engineering", type=Path)
        p.add_argument("assertion", type=Path)
    a = parser.parse_args()
    import sys

    from pcbsmith.board_job import require_worker

    require_worker("pcbsmith.predesign_preparation", sys.argv[1:])

    if a.operation in {"prepare", "refresh"}:
        result = prepare_predesign_inputs(a.spec, a.project, a.output)
        print(result["concept_review"]["outcome"])
        print(result["pre_route_feasibility"]["outcome"])
        print(
            json.dumps(
                {
                    "floorplan_svg": str((a.output / "floorplan.svg").resolve()),
                    "floorplan_preview": str((a.output / "floorplan.png").resolve()),
                    "next": "Inspect/present the preview; complete the mandatory review worklist.",
                }
            )
        )
    else:
        print(approve_prepared_predesign(a.root, a.engineering, a.assertion).readiness.disposition)


if __name__ == "__main__":
    main()
