"""Supported local revision entry point; editing never grants production acceptance.

Uses the native delta adapter and existing file transaction / native check owners.
The source is immutable until explicit apply, which replays and checks the delta.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.board_revision_workflow import (
    NativeRevisionRegion,
    diagnose_native_revision,
    semantic_obligations,
    verify_regional_delta,
)
from pcbsmith.iterative_fixing_ir import FindingObservation
from pcbsmith.iterative_fixing_workflow import (
    WorkflowCheckpoint,
    WorkflowStepOutcome,
    WorkflowStepResult,
    build_evidence_manifest,
    run_iterative_fix_workflow,
)
from pcbsmith.kicad.check_reports import drc_sections, erc_violations, validate_native_header
from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.model_preflight import preflight_board_models
from pcbsmith.kicad.native_edits import (
    NativeEdit,
    apply_native_edits,
    inspect_edit_objects,
    object_inventory,
)
from pcbsmith.kicad.native_zone_edits import merge_verified_fill, refill_native_edit
from pcbsmith.kicad.part_substitution import (
    PartSubstitution,
    plan_part_substitutions,
    refresh_substitution_closure,
    substitution_context_files,
)
from pcbsmith.kicad.project_dependencies import native_project_hashes, retain_native_project
from pcbsmith.kicad.zero_ohm_links import ZeroOhmLink, plan_zero_ohm_links
from pcbsmith.local_routing_repair import RoutingRepairRegion
from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.operations.file_transaction import (
    atomic_write,
    commit_project_files,
    project_path,
    require_complete_project,
)
from pcbsmith.placement_repair_transaction import (
    assess_requested_placement,
    extract_placement_snapshot,
)
from pcbsmith.production_generators import generate_nonmutating_kicad_drc
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.semantic_ir import SemanticIrModel

LEDGER = ".pcbsmith/accepted-board-edits.json"


class BoardRevisionRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-board-revision-request"] = "pcbsmith-board-revision-request"
    source_inputs: dict[str, str] = Field(min_length=1)
    intent: Literal["requested", "optimize"] = "requested"
    validation_stage: Literal[
        "routed", "unrouted_annotations", "unrouted_placement", "unrouted_no_connects"
    ] = "routed"
    rationale: str = Field(min_length=1)
    manual_routing_authorization: str | None = Field(default=None, exclude_if=lambda v: v is None)
    edits: tuple[NativeEdit, ...] = Field(default=(), max_length=64)
    substitutions: tuple[PartSubstitution, ...] = Field(default=(), max_length=16)
    zero_ohm_links: tuple[ZeroOhmLink, ...] = Field(default=(), max_length=16)
    no_connect_terminals: tuple[tuple[str, str], ...] = Field(
        default=(), max_length=64, exclude_if=lambda v: not v
    )
    maximum_displacement_mm: float = Field(default=5, gt=0, le=100)
    maximum_changed_objects: int = Field(default=64, ge=1, le=1000)
    mutable_zone_ids: tuple[str, ...] = ()
    region: NativeRevisionRegion | None = None
    protected_regions: tuple[RoutingRepairRegion, ...] = ()
    finding: FindingObservation | None = None

    floorplan_bundle_path: str | None = None
    floorplan_origin_mm: float | None = None

    def semantic_json(self) -> str:
        # Preserve fingerprints of retained pre-extension routed requests.
        payload = self.model_dump(mode="json")
        if self.floorplan_bundle_path is None:
            payload.pop("floorplan_bundle_path")
        if self.floorplan_origin_mm is None:
            payload.pop("floorplan_origin_mm")
        if not self.substitutions:
            payload.pop("substitutions")
        if not self.zero_ohm_links:
            payload.pop("zero_ohm_links")
        if self.validation_stage == "routed":
            payload.pop("validation_stage")
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )

    @model_validator(mode="after")
    def optimization_scope(self) -> Self:
        if self.no_connect_terminals or self.validation_stage == "unrouted_no_connects":
            if (
                not self.no_connect_terminals
                or self.validation_stage != "unrouted_no_connects"
                or self.edits
                or self.substitutions
                or self.zero_ohm_links
                or self.mutable_zone_ids
                or self.intent != "requested"
                or len(set(self.no_connect_terminals)) != len(self.no_connect_terminals)
            ):
                raise ValueError("no-connect repair requires its separate unrouted terminal scope")
        if self.validation_stage == "unrouted_placement" and (
            not any(edit.kind == "component" for edit in self.edits)
            or any(edit.kind not in {"component", "text", "reference"} for edit in self.edits)
            or self.substitutions
            or self.zero_ohm_links
            or self.mutable_zone_ids
            or self.intent != "requested"
        ):
            raise ValueError("unrouted placement permits requested poses and annotations only")
        if self.zero_ohm_links and (
            self.substitutions or self.validation_stage != "routed" or self.intent != "requested"
        ):
            raise ValueError("Zero-ohm links require a requested routed native revision")
        if len({link.reference for link in self.zero_ohm_links}) != len(self.zero_ohm_links):
            raise ValueError("Zero-ohm link references must be unique")
        if (
            not self.edits
            and not self.substitutions
            and not self.zero_ohm_links
            and not self.no_connect_terminals
        ):
            raise ValueError("A revision requires edits or qualified substitutions")
        if self.substitutions and (
            self.edits
            or self.mutable_zone_ids
            or self.validation_stage != "routed"
            or self.intent != "requested"
            or self.finding is not None
        ):
            raise ValueError("Substitution is a separate routed same-footprint revision scope")
        if self.validation_stage == "unrouted_annotations" and (
            any(edit.kind not in {"text", "reference"} for edit in self.edits)
            or self.mutable_zone_ids
        ):
            raise ValueError("unrouted annotation scope permits only text/reference edits")
        if self.intent == "optimize" and any(edit.kind != "component" for edit in self.edits):
            raise ValueError(
                "this entry point supports optimization intent only for component poses"
            )
        if len(set(self.mutable_zone_ids)) != len(self.mutable_zone_ids):
            raise ValueError("mutable zone identities must be unique")
        if self.region and self.region.initial_region.expansion_index != 0:
            raise ValueError("initial region must have expansion index zero")
        return self


def _json(path: Path, data: object) -> None:
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())


def _copy_context(
    board: Path,
    destination: Path,
    extra_files: tuple[str, ...] = (),
) -> dict[str, str]:
    require_complete_project(board.parent)
    for suffix in (".kicad_sch", ".kicad_pro"):
        if not board.with_suffix(suffix).is_file():
            raise ValueError("local revision requires matching schematic and project")
    retained = retain_native_project(board, destination)
    for relative in extra_files:
        source = project_path(board.parent, relative)
        if source.is_symlink() or not source.is_file():
            raise ValueError("Revision context requires regular project-local files")
        payload = source.read_bytes()
        target = project_path(destination, relative)
        if target.exists() and target.read_bytes() != payload:
            raise ValueError("Revision context changed during retention")
        atomic_write(target, payload)
        retained[relative] = hashlib.sha256(payload).hexdigest()
    _require_inputs(board.parent, retained)
    return retained


def _require_inputs(root: Path, expected: dict[str, str]) -> None:
    require_complete_project(root)
    for relative, digest in expected.items():
        target = project_path(root, relative)
        if not target.is_file() or file_sha256(target) != digest:
            raise ValueError(f"revision source changed: {relative}")


def inspect_board_revision(
    board: Path,
    *,
    substitutions: tuple[PartSubstitution, ...] = (),
    extra_files: tuple[str, ...] = (),
) -> dict[str, Any]:
    board = board.resolve()
    with tempfile.TemporaryDirectory(prefix="pcbsmith-inspect-") as work:
        inputs = _copy_context(
            board,
            Path(work),
            tuple(sorted(set(extra_files) | set(substitution_context_files(board, substitutions)))),
        )
    return {
        "source_inputs": inputs,
        "objects": inspect_edit_objects(board.read_bytes()),
        "coordinates": (
            "board mm; reference positions are footprint-local mm; model offset is local xyz mm"
        ),
        "status": "inspection_only",
        "production_accepted": False,
    }


def _inspect_request(board: Path, request: BoardRevisionRequest) -> dict[str, Any]:
    return inspect_board_revision(
        board, substitutions=request.substitutions, extra_files=tuple(request.source_inputs)
    )


def _plan_revision_delta(
    source: Path,
    request: BoardRevisionRequest,
) -> tuple[bytes, dict[str, Any], dict[str, bytes]]:
    if request.no_connect_terminals:
        from pcbsmith.kicad.no_connect_repair import plan_no_connect_repair

        payload, plan = plan_no_connect_repair(
            source, request.no_connect_terminals, request.maximum_changed_objects
        )
        return payload, plan, {}
    payload, raw_plan = apply_native_edits(
        source.read_bytes(),
        request.edits,
        maximum_displacement_mm=request.maximum_displacement_mm,
        maximum_changed_objects=request.maximum_changed_objects,
        allowed_zone_ids=request.mutable_zone_ids,
    )
    planned: dict[str, Any] = dict(raw_plan)
    extras: dict[str, bytes] = {}
    if request.zero_ohm_links:
        payload, extras, records = plan_zero_ohm_links(source, payload, request.zero_ohm_links)
        after = object_inventory(parse_sexpr(payload.decode()))
        before = planned["before"]
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        if len(changed) > request.maximum_changed_objects:
            raise ValueError("Zero-ohm link revision exceeds changed-object allowance")
        planned.update(
            after=after,
            changed_ids=changed,
            protected_ids=sorted(before.keys() - set(changed)),
            zero_ohm_links=records,
        )
    if request.substitutions:
        extras, records = plan_part_substitutions(source, request.substitutions)
        payload = extras.pop(source.name)
        after = object_inventory(parse_sexpr(payload.decode()))
        before = planned["before"]
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        if (
            len(changed) != len(request.substitutions)
            or len(changed) > request.maximum_changed_objects
        ):
            raise ValueError("Substitution exceeds its exact changed-object allowance")
        planned.update(
            after=after,
            changed_ids=changed,
            protected_ids=sorted(before.keys() - set(changed)),
            part_substitutions=records,
            endpoint_policy="all copper and pads preserved",
        )
    return payload, planned, extras


def _expected_revision_inputs(
    candidate: Path,
    request: BoardRevisionRequest,
    payload: bytes,
    extras: dict[str, bytes],
) -> dict[str, str]:
    expected = dict(request.source_inputs)
    expected.update({name: hashlib.sha256(value).hexdigest() for name, value in extras.items()})
    expected[candidate.name] = hashlib.sha256(payload).hexdigest()
    if request.substitutions:
        from pcbsmith.native_project import NativeProjectSpec, require_native_input_closure

        spec = NativeProjectSpec.model_validate_json(extras["design-spec.json"])
        require_native_input_closure(spec, candidate.parent)
        for relative in ("netlist-vs-intent.json", f".pcbsmith/kicad/{candidate.stem}.net.xml"):
            expected[relative] = file_sha256(candidate.parent / relative)
    return expected


def _require_unrouted_annotations(board: Path) -> None:
    root = parse_sexpr(board.read_text(encoding="utf-8"))
    if any(isinstance(n, list) and n and n[0] in {"segment", "arc", "via", "zone"} for n in root):
        raise ValueError("unrouted annotation scope requires no tracks, arcs, vias or zones")


def _native_checks(
    board: Path,
    output: Path,
    *,
    check_models: bool,
    unrouted_annotations: bool = False,
    unrouted_placement: bool = False,
    unrouted_no_connects: bool = False,
) -> dict[str, Any]:
    if sum((unrouted_annotations, unrouted_placement, unrouted_no_connects)) > 1:
        raise ValueError("native check stage must be unambiguous")
    pre_route = unrouted_annotations or unrouted_placement or unrouted_no_connects
    if pre_route:
        _require_unrouted_annotations(board)
    output.mkdir(parents=True, exist_ok=False)
    before = native_project_hashes(board)
    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI is required for board revision checks")
    report = output / "erc.json"
    command = (
        str(install.path),
        "sch",
        "erc",
        "--format",
        "json",
        "--severity-all",
        "--output",
        str(report),
        str(board.with_suffix(".kicad_sch")),
    )
    started = time.monotonic()
    result = run_kicad_process(command)
    _json(
        output / "erc.process.json",
        {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "native_inputs": before,
        },
    )
    if result.returncode or not report.is_file():
        raise RuntimeError("native ERC failed to execute; inspect retained process log")
    erc = validate_native_header(
        json.loads(report.read_bytes()), "ERC", board.with_suffix(".kicad_sch")
    )
    erc_process_path = output / "erc.process.json"
    erc_process = json.loads(erc_process_path.read_bytes())
    erc_process["report_sha256"] = file_sha256(report)
    _json(erc_process_path, erc_process)
    erc_findings = erc_violations(erc)
    generate_nonmutating_kicad_drc(board, output / "drc.json")
    drc = validate_native_header(json.loads((output / "drc.json").read_bytes()), "DRC", board)
    sections = drc_sections(drc)
    model_status = "not_requested"
    model_resolution_passed = True
    if check_models:
        models = install.path.parent.parent / "share/kicad/3dmodels"
        variables = {f"KICAD{version}_3DMODEL_DIR": str(models) for version in (8, 9, 10)}
        preflight = preflight_board_models(board, variables=variables)
        _json(output / "model-preflight.json", preflight.model_dump(mode="json"))
        model_status = str(preflight.status)
        # Working model edits check resolution, not package/visual qualification.
        # The unregistered/unreviewed preflight status is retained unchanged.
        model_resolution_passed = bool(preflight.models) and all(
            model.status == "resolved" for model in preflight.models
        )
    if native_project_hashes(board) != before:
        raise ValueError("native checker changed revision inputs")
    checked = {
        "native_inputs": before,
        "erc_findings": len(erc_findings),
        "drc_findings": {k: len(v) for k, v in sections.items()},
        "model_status": model_status,
        "model_resolution_passed": model_resolution_passed,
        "check_scope": "native ERC/DRC and optional model resolution; working CAD only",
        "elapsed_seconds": time.monotonic() - started,
        "erc_ignored_checks": erc.get("ignored_checks", []),
        "drc_ignored_checks": drc.get("ignored_checks", []),
        "validation_stage": (
            "unrouted_no_connects"
            if unrouted_no_connects
            else "unrouted_placement"
            if unrouted_placement
            else "unrouted_annotations"
            if unrouted_annotations
            else "routed"
        ),
        "unconnected_items_deferred": len(sections["unconnected_items"]) if pre_route else 0,
        "passed": not erc_findings
        and not sections["violations"]
        and not sections["schematic_parity"]
        and (pre_route or not sections["unconnected_items"])
        and model_resolution_passed,
    }
    _json(output / "summary.json", checked)
    return checked


def _placement_evidence(
    source: Path, candidate: Path, request: BoardRevisionRequest
) -> dict[str, Any]:
    poses = {p.reference: p for p in extract_placement_snapshot(source).poses}
    objects = inspect_edit_objects(source.read_bytes())
    targets = []
    for edit in request.edits:
        if edit.kind != "component":
            continue
        obj = next(
            o for o in objects if o["id"] == edit.target or o.get("reference") == edit.target
        )
        previous = poses[str(obj["reference"])]
        position = edit.position_mm or (previous.x_mm, previous.y_mm)
        targets.append(
            previous.model_copy(
                update={
                    "x_mm": position[0],
                    "y_mm": position[1],
                    "rotation_deg": edit.rotation_deg
                    if edit.rotation_deg is not None
                    else previous.rotation_deg,
                }
            )
        )
    blockers = assess_requested_placement(
        source,
        candidate,
        tuple(targets),
        optimize=request.intent == "optimize",
        added_references=tuple(link.reference for link in request.zero_ohm_links),
    )
    current_poses = {p.reference: p for p in extract_placement_snapshot(candidate).poses}
    for link in request.zero_ohm_links:
        pose = current_poses[link.reference]
        if (pose.x_mm, pose.y_mm) != link.position_mm or (
            pose.rotation_deg + link.axis_screen_deg
        ) % 360 != 0:
            raise ValueError("Jumper placement differs from its declared intent")
    if blockers:
        raise ValueError("; ".join(blockers))
    return {
        "owner": "placement_repair_transaction",
        "targets": [p.model_dump(mode="json") for p in targets],
        "optimization": request.intent == "optimize",
        "blockers": [],
    }


def _filled_delta(
    planned: dict[str, Any], filled: bytes, evidence: dict[str, Any], request: BoardRevisionRequest
) -> dict[str, Any]:
    after = object_inventory(parse_sexpr(filled.decode()))
    before = planned["before"]
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if set(changed) - set(planned["changed_ids"]) - set(request.mutable_zone_ids):
        raise ValueError("refill changed protected native objects")
    if len(changed) > request.maximum_changed_objects:
        raise ValueError("refill exceeds changed-object budget")
    return {
        **planned,
        "after": after,
        "changed_ids": changed,
        "protected_ids": sorted(before.keys() - set(changed)),
        "fill": evidence,
    }


def _verify_checkpoint(
    directory: Path, source: Path, request: BoardRevisionRequest
) -> WorkflowCheckpoint:
    checkpoint = WorkflowCheckpoint.model_validate_json(
        (directory / "workflow/checkpoint.json").read_bytes()
    )
    if (
        checkpoint.source_sha256 != file_sha256(source)
        or checkpoint.configuration_fingerprint != request.semantic_fingerprint()
    ):
        raise ValueError("checkpoint does not match current workflow authority")
    for item in checkpoint.step_results:
        if item.evidence_paths != (f"workflow/{item.step_id}.json",):
            raise ValueError("checkpoint has unexpected evidence paths")
        evidence = json.loads(project_path(directory, item.evidence_paths[0]).read_bytes())
        if fingerprint(evidence) != item.result_fingerprint:
            raise ValueError("checkpoint evidence is stale")
        for relative, digest in evidence.get("retained_files", {}).items():
            if file_sha256(project_path(directory, relative)) != digest:
                raise ValueError("checkpoint retained evidence is stale")
    return checkpoint


def _revision_floorplan(board: Path, request: BoardRevisionRequest) -> dict[str, Any] | None:
    if not (request.zero_ohm_links or any(e.kind == "component" for e in request.edits)):
        return None
    if not request.floorplan_bundle_path or request.floorplan_origin_mm is None:
        raise ValueError(
            "placement changes require a reviewed vector floorplan and explicit origin"
        )
    from pcbsmith.kicad.floorplan import FILES, require_floorplan
    from pcbsmith.production_readiness import PredesignReadinessBundle

    bundle_file = project_path(board.parent, request.floorplan_bundle_path)
    bundle = PredesignReadinessBundle.model_validate_json(bundle_file.read_bytes())
    for path in (bundle_file, *(bundle_file.parent / name for name in FILES)):
        relative = path.relative_to(board.parent).as_posix()
        if request.source_inputs.get(relative) != file_sha256(path):
            raise ValueError("revision must retain exact floorplan inputs in its source closure")
    return require_floorplan(bundle, bundle_file.parent)


def create_board_revision(
    *, board: Path, request: BoardRevisionRequest, output: Path, resume: bool = False
) -> Path:
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    if not resume and (
        request.zero_ohm_links
        or any(e.kind in {"segment", "segment_add", "segment_remove", "via"} for e in request.edits)
    ):
        from pcbsmith.routing_policy import require_manual_routing_authorization

        require_manual_routing_authorization(request.manual_routing_authorization)
    board, output = board.resolve(), output.resolve()
    if output.is_relative_to(board.parent) or (output.exists() and not resume):
        raise ValueError("revision output must be fresh and outside the source project")
    _require_inputs(board.parent, request.source_inputs)
    floorplan_layout = _revision_floorplan(board, request)
    if (
        request.substitutions
        and _inspect_request(board, request)["source_inputs"] != request.source_inputs
    ):
        raise ValueError("Substitution request lacks the complete qualification/source context")
    if request.validation_stage in {
        "unrouted_annotations",
        "unrouted_placement",
        "unrouted_no_connects",
    }:
        _require_unrouted_annotations(board)
    started = time.monotonic()
    if resume:
        recorded = BoardRevisionRequest.model_validate_json((output / "request.json").read_bytes())
        if (
            recorded != request
            or (output / "revision.json").exists()
            or (output / "failure.json").exists()
        ):
            raise ValueError("resume requires the same interrupted, nonterminal request")
        # Every resumed stage is checked against retained predecessor/request bytes.
        if (
            _inspect_request(output / "before" / board.name, request)["source_inputs"]
            != request.source_inputs
        ):
            raise ValueError("resume predecessor is stale")
    else:
        output.mkdir(parents=True)
        _json(output / "request.json", request.model_dump(mode="json"))
    from pcbsmith.board_job import bind_revision_job

    bind_revision_job(output, resume=resume)
    try:
        inputs = request.source_inputs
        if not resume:
            inputs = _copy_context(board, output / "before", tuple(request.source_inputs))
            if inputs != request.source_inputs:
                raise ValueError("request does not cover the complete current input closure")
            shutil.copytree(output / "before", output / "design")
        source = output / "before" / board.name
        candidate = output / "design" / board.name
        # Computing the delta is a read-only plan; the IF2 runner writes the isolated candidate.
        payload, planned, extra_payloads = _plan_revision_delta(source, request)
        if floorplan_layout is not None:
            from pcbsmith.kicad.floorplan import require_native_floorplan_text

            assert request.floorplan_origin_mm is not None
            require_native_floorplan_text(
                payload.decode("utf-8"), floorplan_layout, origin_mm=request.floorplan_origin_mm
            )
        errors: list[Exception] = []
        checks: dict[str, Any] = {}
        delta: dict[str, Any] = dict(planned)

        def stage(step: str, action: Any) -> WorkflowStepResult:
            nonlocal delta
            stage_started = time.monotonic()
            try:
                evidence = action()
                retained = []
                if step == "IF4":
                    retained = [output / "delta.json"] + list((output / "fill").rglob("*"))
                elif step == "IF5":
                    retained = list((output / "checks").rglob("*"))
                evidence["retained_files"] = {
                    p.relative_to(output).as_posix(): file_sha256(p)
                    for p in retained
                    if p.is_file()
                }
                path = f"workflow/{step}.json"
                _json(output / path, evidence)
                blockers = tuple(evidence.get("blockers", ()))
                return WorkflowStepResult(
                    step_id=step,
                    outcome=WorkflowStepOutcome.BLOCKED
                    if blockers
                    else WorkflowStepOutcome.ACCEPTED,
                    result_fingerprint=fingerprint(evidence),
                    evidence_paths=(path,),
                    candidate_path=str(candidate) if step == "IF5" and not blockers else None,
                    candidate_sha256=file_sha256(candidate)
                    if step == "IF5" and not blockers
                    else None,
                    attempts_used=len(evidence.get("run", {}).get("attempts", [])) or 1,
                    elapsed_seconds=time.monotonic() - stage_started,
                    changed_object_count=len(delta["changed_ids"]),
                    preserved_object_count=len(delta["protected_ids"]),
                    blockers=blockers,
                )
            except Exception as exc:
                errors.append(exc)
                evidence = {"error": f"{type(exc).__name__}: {exc}"}
                path = f"workflow/{step}-failure.json"
                _json(output / path, evidence)
                return WorkflowStepResult(
                    step_id=step,
                    outcome=WorkflowStepOutcome.BLOCKED,
                    result_fingerprint=fingerprint(evidence),
                    evidence_paths=(path,),
                    attempts_used=1,
                    elapsed_seconds=time.monotonic() - stage_started,
                    changed_object_count=0,
                    preserved_object_count=0,
                    blockers=(str(exc),),
                )

        def envelope() -> dict[str, Any]:
            result = verify_regional_delta(source.read_bytes(), payload, planned, request)
            if result["status"] == "blocked_envelope":
                result["blockers"] = ["bounded regional expansions exhausted"]
                return result
            if extra_payloads:
                commit_project_files(
                    candidate.parent,
                    {candidate.name: payload, **extra_payloads},
                    expected_sha256s=request.source_inputs,
                )
            else:
                atomic_write(candidate, payload)
            _json(output / "planned-delta.json", planned)
            return result

        def placement() -> dict[str, Any]:
            return _placement_evidence(source, candidate, request)

        def fill() -> dict[str, Any]:
            nonlocal delta
            if request.mutable_zone_ids:
                if resume and (output / "fill").exists():
                    (output / "fill").rename(output / f"interrupted-fill-{time.time_ns()}")
                atomic_write(candidate, payload)
                atomic_write(output / "pre-fill.kicad_pcb", payload)
                filled, evidence = refill_native_edit(
                    candidate, output / "fill", request.mutable_zone_ids
                )
                delta = _filled_delta(planned, filled, evidence, request)
                # Full zone extent participates in region/keepout checks, not just edited vertices.
                verify = verify_regional_delta(source.read_bytes(), filled, delta, request)
                if verify["status"] == "blocked_envelope":
                    raise ValueError("refill exceeds declared region")
                atomic_write(candidate, filled)
            else:
                evidence = {"status": "not_applicable"}
            _json(output / "delta.json", delta)
            return evidence

        def native() -> dict[str, Any]:
            nonlocal checks, delta
            delta = json.loads((output / "delta.json").read_bytes())
            if not delta["changed_ids"]:
                return {"status": "no_change", "blockers": []}
            if resume and (output / "checks").exists():
                archived = output / f"interrupted-checks-{time.time_ns()}"
                (output / "checks").rename(archived)
            if request.substitutions:
                refresh_substitution_closure(candidate)
            checks = _native_checks(
                candidate,
                output / "checks",
                check_models=any(e.kind == "model_offset" for e in request.edits),
                **(
                    {request.validation_stage: True}
                    if request.validation_stage
                    in {"unrouted_annotations", "unrouted_placement", "unrouted_no_connects"}
                    else {}
                ),
            )
            obligations = semantic_obligations(
                board.name, request, delta, file_sha256(candidate), checks["passed"]
            )
            _json(output / "semantic-obligations.json", obligations)
            return {
                "native_checks": checks,
                "qualification_obligations": obligations,
                "scope": "working CAD only",
                "blockers": [] if checks["passed"] else ["native_checks_failed"],
            }

        if resume:
            saved = _verify_checkpoint(output, source, request)
            completed = {item.step_id for item in saved.step_results}
            expected_payload = payload if "IF2" in completed else source.read_bytes()
            raw_fill = output / "fill/native" / board.name
            # A completed atomic fill write can precede its checkpoint by a few instructions.
            if raw_fill.is_file() and request.mutable_zone_ids:
                filled_payload, evidence = merge_verified_fill(
                    payload, raw_fill.read_bytes(), request.mutable_zone_ids
                )
                if candidate.read_bytes() == filled_payload:
                    expected_payload = filled_payload
                if "IF4" in completed:
                    expected_payload = filled_payload
                    delta = _filled_delta(planned, filled_payload, evidence, request)
            for relative, value in extra_payloads.items():
                wanted = value if "IF2" in completed else (source.parent / relative).read_bytes()
                if (candidate.parent / relative).read_bytes() != wanted:
                    raise ValueError("resume substitution context is stale")
            if candidate.read_bytes() != expected_payload:
                raise ValueError("resume candidate is stale")
            if "IF4" in completed:
                if json.loads((output / "delta.json").read_bytes()) != delta:
                    raise ValueError("resume delta is stale")
            if "IF5" in completed:
                checks = json.loads((output / "workflow/IF5.json").read_bytes()).get(
                    "native_checks", {}
                )
        checkpoint = run_iterative_fix_workflow(
            case_id=output.name,
            source_board=source,
            configuration_fingerprint=request.semantic_fingerprint(),
            checkpoint_path=output / "workflow/checkpoint.json",
            runners={
                "IF1": lambda: stage(
                    "IF1", lambda: diagnose_native_revision(source, request, planned)
                ),
                "IF2": lambda: stage("IF2", envelope),
                "IF3": lambda: stage("IF3", placement),
                "IF4": lambda: stage("IF4", fill),
                "IF5": lambda: stage("IF5", native),
            },
        )
        manifest = build_evidence_manifest(checkpoint, root=output)
        _json(output / "workflow/evidence-manifest.json", manifest.model_dump(mode="json"))
        _json(
            output / "workflow/scope.json",
            {
                "scope": "working CAD revision; no production qualification",
                "production_accepted": False,
            },
        )
        if errors:
            raise errors[0]
        if not (output / "delta.json").exists():
            raise ValueError("bounded regional expansions exhausted")
        delta = json.loads((output / "delta.json").read_bytes())
        _require_inputs(board.parent, inputs)
        expected = _expected_revision_inputs(
            candidate, request, candidate.read_bytes(), extra_payloads
        )
        if _inspect_request(candidate, request)["source_inputs"] != expected:
            raise ValueError("candidate context changed outside the native delta")
        if _inspect_request(board, request)["source_inputs"] != inputs:
            raise ValueError("source context changed during revision")
        status = (
            "no_change"
            if not delta["changed_ids"]
            else "digitally_checked_candidate"
            if checks.get("passed")
            else "blocked_candidate"
        )
        receipt: dict[str, Any] = {
            "schema": "pcbsmith-board-revision-v1",
            "status": status,
            "source_board_name": board.name,
            "source_inputs": inputs,
            "candidate_inputs": expected,
            "request_sha256": file_sha256(output / "request.json"),
            "delta_sha256": file_sha256(output / "delta.json"),
            "check_files": {
                p.relative_to(output).as_posix(): file_sha256(p)
                for folder in ("checks", "workflow", "fill")
                for p in (output / folder).rglob("*")
                if p.is_file()
            },
            "production_accepted": False,
            "automatic_router_used": False,
            "shared_if_workflow": True,
            "invalidated": [
                "visual and component review",
                "affected engineering qualification",
                "routing publication lineage",
                "manufacturing outputs",
                "affected physical qualification",
            ],
            "elapsed_seconds": time.monotonic() - started,
        }
        for relative in ("planned-delta.json", "pre-fill.kicad_pcb", "semantic-obligations.json"):
            if (output / relative).is_file():
                receipt["check_files"][relative] = file_sha256(output / relative)
        _json(output / "revision.json", receipt)
        return candidate
    except BaseException as exc:
        if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
            _json(
                output / "failure.json",
                {
                    "schema": "pcbsmith-board-revision-v1",
                    "source_inputs": request.source_inputs,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": time.monotonic() - started,
                    "production_accepted": False,
                },
            )
        raise


def replay_board_revision(directory: Path) -> tuple[Path, BoardRevisionRequest, dict[str, Any]]:
    """Recompute the exact delta, rather than trusting a successful receipt label."""
    receipt: dict[str, Any] = json.loads((directory / "revision.json").read_bytes())
    if (
        receipt.get("schema") != "pcbsmith-board-revision-v1"
        or receipt.get("status") != "digitally_checked_candidate"
    ):
        raise ValueError("only a digitally checked edit candidate can be applied")
    request = BoardRevisionRequest.model_validate_json((directory / "request.json").read_bytes())
    if file_sha256(directory / "request.json") != receipt.get("request_sha256"):
        raise ValueError("revision request is stale")
    name = receipt["source_board_name"]
    before = project_path(directory / "before", name)
    candidate = project_path(directory / "design", name)
    if Path(name).name != name or not name.endswith(".kicad_pcb"):
        raise ValueError("invalid candidate board name")
    if _inspect_request(before, request)["source_inputs"] != request.source_inputs:
        raise ValueError("retained predecessor context differs from request")
    if request.validation_stage in {
        "unrouted_annotations",
        "unrouted_placement",
        "unrouted_no_connects",
    }:
        _require_unrouted_annotations(before)
    payload, delta, extra_payloads = _plan_revision_delta(before, request)
    if request.mutable_zone_ids:
        if (directory / "pre-fill.kicad_pcb").read_bytes() != payload:
            raise ValueError("pre-fill candidate is stale")
        payload, evidence = merge_verified_fill(
            payload, (directory / "fill/native" / name).read_bytes(), request.mutable_zone_ids
        )
        delta = _filled_delta(delta, payload, evidence, request)
    if (
        candidate.read_bytes() != payload
        or json.loads((directory / "delta.json").read_bytes()) != delta
    ):
        raise ValueError("candidate does not replay from its declared native edits")
    _placement_evidence(before, candidate, request)
    if (
        verify_regional_delta(before.read_bytes(), payload, delta, request)["status"]
        == "blocked_envelope"
    ):
        raise ValueError("candidate exceeds declared region")
    diagnose_native_revision(before, request, delta)
    if receipt.get("shared_if_workflow"):
        checkpoint = _verify_checkpoint(directory, before, request)
        if not checkpoint.terminal or len(checkpoint.step_results) != 5:
            raise ValueError("revision workflow is incomplete")
        if any(s.outcome != WorkflowStepOutcome.ACCEPTED for s in checkpoint.step_results):
            raise ValueError("revision workflow is blocked")
        if checkpoint.step_results[-1].candidate_sha256 != hashlib.sha256(payload).hexdigest():
            raise ValueError("workflow candidate is stale")
    elif request.mutable_zone_ids or request.region or request.protected_regions or request.finding:
        raise ValueError("extended revision requires shared workflow evidence")
    expected = _expected_revision_inputs(candidate, request, payload, extra_payloads)
    if (
        receipt.get("candidate_inputs") != expected
        or _inspect_request(candidate, request)["source_inputs"] != expected
    ):
        raise ValueError("candidate project inputs changed outside its edit")
    if (
        receipt.get("source_inputs") != request.source_inputs
        or receipt.get("production_accepted") is not False
    ):
        raise ValueError("invalid edit provenance or promoted status")
    required_checks = {"checks/erc.json", "checks/drc.json", "checks/summary.json"}
    if not required_checks.issubset(receipt.get("check_files", {})):
        raise ValueError("revision is missing retained native check files")
    for relative, digest in receipt["check_files"].items():
        if file_sha256(project_path(directory, relative)) != digest:
            raise ValueError("retained edit check evidence is stale")
    return candidate, request, receipt


def apply_board_revision(*, board: Path, directory: Path) -> str:
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    from pcbsmith.board_job import bind_revision_job

    bind_revision_job(directory, resume=True)
    """Apply a checked working edit with optimistic conflict detection and a journal.

    This updates the CAD working revision, never production/review/release approval.
    """
    board, directory = board.resolve(), directory.resolve()
    candidate, request, receipt = replay_board_revision(directory)
    if (
        board.name != candidate.name
        or _inspect_request(board, request)["source_inputs"] != request.source_inputs
    ):
        raise ValueError("current project conflicts with the edit predecessor")
    check_dir = Path(tempfile.mkdtemp(prefix="apply-check-", dir=directory))
    if request.mutable_zone_ids:
        refilled, _ = refill_native_edit(candidate, check_dir / "fill", request.mutable_zone_ids)
        if refilled != candidate.read_bytes():
            raise ValueError("candidate fill is stale under current native rules")
    checks = _native_checks(
        candidate,
        check_dir / "native",
        check_models=any(e.kind == "model_offset" for e in request.edits),
        **(
            {request.validation_stage: True}
            if request.validation_stage
            in {"unrouted_annotations", "unrouted_placement", "unrouted_no_connects"}
            else {}
        ),
    )
    if not checks["passed"]:
        raise ValueError("current native checks block application")
    # Recheck byte equality after the native tools and before the atomic transaction.
    replay_board_revision(directory)
    if _inspect_request(board, request)["source_inputs"] != request.source_inputs:
        raise ValueError("current project changed during apply checks")
    ledger_file = project_path(board.parent, LEDGER)
    ledger: dict[str, Any] = (
        json.loads(ledger_file.read_bytes())
        if ledger_file.exists()
        else {"schema": "pcbsmith-working-edits-v1", "edits": []}
    )
    if ledger.get("schema") != "pcbsmith-working-edits-v1" or not isinstance(
        ledger.get("edits"), list
    ):
        raise ValueError("unsupported accepted-edit journal")
    ledger["edits"].append(
        {
            "source_inputs": request.source_inputs,
            "board_sha256": receipt["candidate_inputs"][board.name],
            "request": request.model_dump(mode="json"),
            "retained_revision": str(directory),
            "production_accepted": False,
        }
    )
    expected: dict[str, str | None] = dict(request.source_inputs)
    expected.setdefault(LEDGER, None)
    candidate_payload = candidate.read_bytes()
    if hashlib.sha256(candidate_payload).hexdigest() != receipt["candidate_inputs"][board.name]:
        raise ValueError("candidate changed before commit")
    changed_payloads = {
        relative: project_path(candidate.parent, relative).read_bytes()
        for relative, digest in receipt["candidate_inputs"].items()
        if digest != request.source_inputs.get(relative)
    }
    return commit_project_files(
        board.parent,
        {
            **changed_payloads,
            board.name: candidate_payload,
            LEDGER: (json.dumps(ledger, indent=2) + "\n").encode(),
        },
        expected_sha256s=expected,
    )
