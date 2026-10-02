"""Registered, fail-closed publication boundary for KiCad board generators.

Board builders intentionally remain pure file generators.  This module is the
single boundary that decides whether one of those builders may publish a
placement or routed production candidate.  Registration is explicit so a new
generator cannot silently bypass the Phase 17 transaction workflow.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import model_validator

from pcbsmith.applicability_execution import CheckExecutionRecord, ProjectCheckDisposition
from pcbsmith.board_rebuild import RebuildDecision, require_generation_mode
from pcbsmith.component_review_execution import ProjectComponentReviewExecution
from pcbsmith.kicad.check_reports import drc_sections, validate_native_header
from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.kicad.project_dependencies import retain_native_project, retain_project_libraries
from pcbsmith.kicad.routing_candidate_transaction import AcceptedRoutingExecution
from pcbsmith.manufacturing_lineage import native_input_hashes
from pcbsmith.operations.file_transaction import atomic_write
from pcbsmith.production_readiness import (
    PredesignReadinessBundle,
    PublicationReadinessRequest,
    evaluate_saved_readiness,
    require_predesign_bundle,
    require_publication_request,
    retain_readiness_inputs,
)
from pcbsmith.production_workflow import (
    PlacementReviewTransactionResult,
    RoutedReviewTransactionResult,
    persist_placement_and_generate_review,
    persist_routed_board_and_generate_review,
)
from pcbsmith.review.visual_package import VisualReviewManifest
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_revision import (
    RevisionPublicationAuthority,
    UnchangedCopperRevision,
    require_revision_publication_authority,
    require_unchanged_copper_revision,
)
from pcbsmith.semantic_ir import SemanticIrModel


class GeneratorPublicationCapability(StrEnum):
    """Highest candidate stage a registered builder may publish."""

    PLACEMENT = "placement"
    ROUTED = "routed"
    PAUSED = "paused"
    RESEARCH = "research"


@dataclass(frozen=True)
class GeneratorRegistration:
    generator_id: str
    module: str
    entrypoint: str
    capability: GeneratorPublicationCapability
    notes: str

    @property
    def source_relative_path(self) -> str:
        return self.module.replace(".", "/") + ".py"


@dataclass(frozen=True)
class GeneratorRegistryAudit:
    discovered_ids: tuple[str, ...]
    registered_ids: tuple[str, ...]
    unregistered_ids: tuple[str, ...]
    stale_registration_ids: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.unregistered_ids and not self.stale_registration_ids


class RegisteredRoutingPublicationEvidence(SemanticIrModel):
    """Bind a registered routed generator to exact accepted engine execution."""

    schema_id: Literal["pcbsmith-registered-routing-publication"] = (
        "pcbsmith-registered-routing-publication"
    )
    schema_version: Literal[1] = 1
    generator_id: str
    generator_capability: Literal["routed"] = "routed"
    board_sha256: str
    routing_execution: AcceptedRoutingExecution | UnchangedCopperRevision
    evidence_fingerprint: str

    @model_validator(mode="after")
    def publication_is_exact(self) -> Self:
        require_identity(self.generator_id, "generator_id")
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        if self.routing_execution.board_sha256 != self.board_sha256:
            raise ValueError("routing execution targets a different publication board")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != fingerprint(payload):
            raise ValueError("registered routing publication fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        generator_id: str,
        board_sha256: str,
        routing_execution: AcceptedRoutingExecution | UnchangedCopperRevision,
    ) -> RegisteredRoutingPublicationEvidence:
        fields: dict[str, Any] = {
            "generator_id": generator_id,
            "generator_capability": "routed",
            "board_sha256": board_sha256,
            "routing_execution": routing_execution,
        }
        provisional = cls.model_construct(**fields, evidence_fingerprint="0" * 64)
        return cls(
            **fields,
            evidence_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
            ),
        )


def _registration(
    module_name: str,
    entrypoint: str,
    capability: GeneratorPublicationCapability,
    notes: str,
) -> GeneratorRegistration:
    module = f"pcbsmith.kicad.{module_name}"
    return GeneratorRegistration(
        generator_id=f"{module}:{entrypoint}",
        module=module,
        entrypoint=entrypoint,
        capability=capability,
        notes=notes,
    )


_PLACEMENT = GeneratorPublicationCapability.PLACEMENT
_ROUTED = GeneratorPublicationCapability.ROUTED

# Every public board-builder entrypoint under pcbsmith.kicad is listed here.
# An AST inventory test makes this list fail when a builder is added, renamed,
# or removed without an explicit migration decision.
ORDINARY_ROUTER_ID = "pcbsmith.production_routing:route_saved_placement_candidate"
GENERATOR_REGISTRY: tuple[GeneratorRegistration, ...] = (
    GeneratorRegistration(
        generator_id=ORDINARY_ROUTER_ID,
        module="pcbsmith.production_routing",
        entrypoint="route_saved_placement_candidate",
        capability=_ROUTED,
        notes="Ordinary saved-placement routing; requires exact accepted native routing receipt.",
    ),
    _registration(
        "montenegro_env_display_board",
        "write_montenegro_board",
        GeneratorPublicationCapability.PAUSED,
        "Paused Montenegro writer; no production generation/publication.",
    ),
    _registration(
        "thermometer_pwled_micro_pilot",
        "build_thermometer_pwled_micro_board",
        GeneratorPublicationCapability.RESEARCH,
        "Synthetic research fixture constructor; no production publication.",
    ),
    _registration(
        "aerosense_2f_board",
        "generate_aerosense_placement_board",
        _PLACEMENT,
        "Approved AeroSense exact-footprint placement candidate.",
    ),
    _registration(
        "aerosense_2f_board",
        "generate_aerosense_routed_board",
        _ROUTED,
        "Explicit routed builder; saved-board inspection remains authoritative.",
    ),
    _registration(
        "bldc_esc_board",
        "generate_bldc_esc_placement_board",
        _PLACEMENT,
        "BLDC ESC visual-placement study; routing was never established.",
    ),
    _registration(
        "bldc_esc_r002_board",
        "generate_bldc_esc_r002_board",
        _PLACEMENT,
        "Cooling-review placement study; not a routed production candidate.",
    ),
    _registration(
        "board",
        "generate_board",
        _PLACEMENT,
        "Generic board serializer; routed status requires a dedicated routed builder.",
    ),
    _registration(
        "clover_board",
        "generate_clover_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "flyback_board",
        "generate_flyback_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "led_art_board",
        "generate_led_art_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "metal_detector_board",
        "generate_detector_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "pear_board",
        "generate_pear_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "protocol_analyzer_8ch_board",
        "generate_protocol_analyzer_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "protocol_analyzer_8ch_board",
        "generate_protocol_analyzer_routed_board",
        _ROUTED,
        "Explicit routed builder; saved-board inspection remains authoritative.",
    ),
    _registration(
        "protocol_analyzer_8ch_r002_board",
        "generate_protocol_analyzer_r002_placement_board",
        _PLACEMENT,
        "R002 compaction remains an unrouted placement candidate.",
    ),
    _registration(
        "retro_pad_3x3_board",
        "generate_retro_pad_3x3_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "retro_pad_3x3_board",
        "generate_retro_pad_3x3_routed_board",
        _ROUTED,
        "Explicit routed builder; saved-board inspection remains authoritative.",
    ),
    _registration(
        "retro_pad_board",
        "generate_retro_pad_board",
        _ROUTED,
        "Original routed Retro-Pad builder retained behind objective route inspection.",
    ),
    _registration(
        "retro_pad_board",
        "generate_retro_pad_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "retro_pad_r003_board",
        "generate_retro_pad_r003_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "retro_pad_r003_board",
        "generate_retro_pad_r003_routed_board",
        _ROUTED,
        "Explicit routed builder; saved-board inspection remains authoritative.",
    ),
    _registration(
        "servo555_board",
        "generate_servo555_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "thermometer_board",
        "generate_thermometer_board",
        _PLACEMENT,
        "Completed historical board retained as placement-only legacy evidence.",
    ),
)

_REGISTRY_BY_ID = {item.generator_id: item for item in GENERATOR_REGISTRY}
if len(_REGISTRY_BY_ID) != len(GENERATOR_REGISTRY):
    raise RuntimeError("production generator registry contains duplicate IDs")


def registered_generator(generator_id: str) -> GeneratorRegistration:
    try:
        return _REGISTRY_BY_ID[generator_id]
    except KeyError as exc:
        raise ValueError(
            f"unregistered board generator {generator_id!r}; publication is blocked"
        ) from exc


def discover_board_generator_ids(kicad_source_dir: Path) -> tuple[str, ...]:
    """Discover public board entrypoints without importing generator modules."""

    discovered: list[str] = []
    for source in sorted(kicad_source_dir.glob("*.py")):
        module = f"pcbsmith.kicad.{source.stem}"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith(("generate_", "build_", "write_")) and node.name.endswith(
                "board"
            ):
                discovered.append(f"{module}:{node.name}")
    ordinary = kicad_source_dir.parent / "production_routing.py"
    if ordinary.is_file():
        tree = ast.parse(ordinary.read_text(encoding="utf-8"), filename=str(ordinary))
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "route_saved_placement_candidate"
            for node in tree.body
        ):
            discovered.append(ORDINARY_ROUTER_ID)
    return tuple(sorted(discovered))


def audit_generator_registry(kicad_source_dir: Path) -> GeneratorRegistryAudit:
    discovered = discover_board_generator_ids(kicad_source_dir)
    registered = tuple(sorted(_REGISTRY_BY_ID))
    return GeneratorRegistryAudit(
        discovered_ids=discovered,
        registered_ids=registered,
        unregistered_ids=tuple(sorted(set(discovered) - set(registered))),
        stale_registration_ids=tuple(sorted(set(registered) - set(discovered))),
    )


def persist_registered_placement_candidate(
    *,
    generator_id: str,
    transaction_root: Path,
    project_id: str,
    generation_id: str,
    generation_sha256: str,
    board_relative_path: str,
    board_payload: bytes,
    review_generator: Callable[[Path, Path], VisualReviewManifest],
    component_review_generator: Callable[[Path], ProjectComponentReviewExecution],
    support_payloads: Mapping[str, bytes] | None = None,
    readiness_request: PublicationReadinessRequest | None = None,
    readiness_artifact_root: Path | None = None,
) -> PlacementReviewTransactionResult:
    """Publish one registered builder's placement candidate atomically."""
    from pcbsmith.board_job import require_library_worker

    require_library_worker()

    registration = registered_generator(generator_id)
    if registration.capability in {
        GeneratorPublicationCapability.PAUSED,
        GeneratorPublicationCapability.RESEARCH,
    }:
        raise ValueError("paused/research generator cannot publish production candidates")
    guarded_review = _guarded_readiness_review(
        request=readiness_request,
        artifact_root=readiness_artifact_root,
        project_id=project_id,
        board_relative_path=board_relative_path,
        board_payload=board_payload,
        support_payloads=support_payloads,
        review_generator=review_generator,
    )
    return persist_placement_and_generate_review(
        transaction_root=transaction_root,
        project_id=project_id,
        generation_id=generation_id,
        generation_sha256=generation_sha256,
        board_relative_path=board_relative_path,
        board_payload=board_payload,
        review_generator=guarded_review,
        component_review_generator=component_review_generator,
        support_payloads=support_payloads,
    )


def persist_registered_routed_candidate(
    *,
    generator_id: str,
    transaction_root: Path,
    project_id: str,
    generation_id: str,
    generation_sha256: str,
    board_relative_path: str,
    board_payload: bytes,
    review_generator: Callable[[Path, Path], VisualReviewManifest],
    drc_generator: Callable[[Path, Path], None],
    routing_execution: AcceptedRoutingExecution | UnchangedCopperRevision | None = None,
    revision_authority: RevisionPublicationAuthority | None = None,
    support_payloads: Mapping[str, bytes] | None = None,
    readiness_request: PublicationReadinessRequest | None = None,
    readiness_artifact_root: Path | None = None,
) -> RoutedReviewTransactionResult:
    """Publish a routed candidate only from an explicitly routed-capable builder."""
    from pcbsmith.board_job import require_library_worker

    require_library_worker()

    registration = registered_generator(generator_id)
    if registration.capability is not GeneratorPublicationCapability.ROUTED:
        raise ValueError(f"generator {generator_id!r} is registered for placement publication only")
    if routing_execution is None:
        raise ValueError("routed publication requires accepted routing-engine execution evidence")
    if generator_id == ORDINARY_ROUTER_ID:
        engine = routing_execution.engine
        legacy_native = (
            engine.engine_id == "pcbsmith-native-astar"
            and engine.adapter_id == "pcbsmith.kicad.routing_candidate_adapter"
        )
        pinned_freerouting = (
            engine.engine_id == "freerouting-v2.3.0"
            and engine.engine_version == "2.3.0"
            and engine.adapter_id == "pcbsmith.kicad.routing_external_adapters"
            and engine.adapter_version == "1"
            and engine.source_commit == "v2.3.0"
            and engine.executable_sha256 is not None
        )
        if not (legacy_native or pinned_freerouting):
            raise ValueError(
                "ordinary routed publication requires its registered native or Freerouting adapter"
            )
    if isinstance(routing_execution, UnchangedCopperRevision):
        require_unchanged_copper_revision(routing_execution, board_payload)
        prefix = Path(board_relative_path).parent
        for relative, expected in routing_execution.candidate_inputs.items():
            if relative == Path(board_relative_path).name:
                continue
            retained = (support_payloads or {}).get((prefix / relative).as_posix())
            if retained is None or hashlib.sha256(retained).hexdigest() != expected:
                raise ValueError(
                    "publication must retain exact checked substitution inputs: " + relative
                )
        require_revision_publication_authority(
            revision_authority, routing_execution, board_payload, project_id, readiness_request
        )
    elif revision_authority is not None:
        raise ValueError("revision authority requires unchanged-copper revision provenance")
    board_sha256 = hashlib.sha256(board_payload).hexdigest()
    publication_evidence = RegisteredRoutingPublicationEvidence.build(
        generator_id=generator_id,
        board_sha256=board_sha256,
        routing_execution=routing_execution,
    )
    guarded_review = _guarded_readiness_review(
        request=readiness_request,
        artifact_root=readiness_artifact_root,
        project_id=project_id,
        board_relative_path=board_relative_path,
        board_payload=board_payload,
        support_payloads=support_payloads,
        review_generator=review_generator,
    )
    return persist_routed_board_and_generate_review(
        transaction_root=transaction_root,
        project_id=project_id,
        generation_id=generation_id,
        generation_sha256=generation_sha256,
        board_relative_path=board_relative_path,
        board_payload=board_payload,
        review_generator=guarded_review,
        drc_generator=lambda board, report: _guarded_readiness_drc(
            readiness_request, readiness_artifact_root, project_id, board, report, drc_generator
        ),
        revision_authority=revision_authority,
        revision_proof=(
            routing_execution if isinstance(routing_execution, UnchangedCopperRevision) else None
        ),
        readiness_request=readiness_request,
        support_payloads=support_payloads,
        routing_execution_evidence=(
            json.dumps(publication_evidence.model_dump(mode="json"), indent=2) + "\n"
        ).encode("utf-8"),
    )


def _guarded_readiness_review(
    *,
    request: PublicationReadinessRequest | None,
    artifact_root: Path | None,
    project_id: str,
    board_relative_path: str,
    board_payload: bytes,
    support_payloads: Mapping[str, bytes] | None,
    review_generator: Callable[[Path, Path], VisualReviewManifest],
) -> Callable[[Path, Path], VisualReviewManifest]:
    if request is None or artifact_root is None:
        raise ValueError("production publication requires predesign and readiness inputs")
    require_predesign_bundle(request.predesign, artifact_root)
    from pcbsmith.mandatory_review import require_mandatory_review, require_recurring_deliverables

    require_recurring_deliverables(require_mandatory_review(request.predesign, artifact_root))
    if request.predesign.approval.project_id != project_id:
        raise ValueError("predesign approval belongs to another project")
    board_path = Path(board_relative_path)
    names = {
        board_path.name,
        *(
            board_path.with_suffix(suffix).name
            for suffix in (".kicad_sch", ".kicad_pro", ".kicad_dru")
        ),
        "fp-lib-table",
        "sym-lib-table",
    }
    inputs = {board_path.name: hashlib.sha256(board_payload).hexdigest()}
    inputs.update(
        {
            Path(relative).name: hashlib.sha256(payload).hexdigest()
            for relative, payload in (support_payloads or {}).items()
            if Path(relative).parent == board_path.parent and Path(relative).name in names
        }
    )
    if request.native_inputs != inputs:
        raise ValueError("readiness request differs from exact publication inputs")

    def generate(board: Path, output: Path) -> VisualReviewManifest:
        require_publication_request(
            request, board_file=board, artifact_root=artifact_root, project_id=project_id
        )
        manifest = review_generator(board, output)
        from pcbsmith.production_workflow import review_output_root

        output = review_output_root(output, manifest)
        receipt = evaluate_saved_readiness(
            request,
            board_file=board,
            artifact_root=artifact_root,
            review_directory=output,
            review=manifest,
            project_id=project_id,
        )
        retain_readiness_inputs(request.predesign, artifact_root, output / "readiness-inputs")
        atomic_write(
            output / "design-readiness.json", (receipt.model_dump_json(indent=2) + "\n").encode()
        )
        return manifest

    return generate


def _guarded_readiness_drc(
    request: PublicationReadinessRequest | None,
    artifact_root: Path | None,
    project_id: str,
    board: Path,
    report: Path,
    generator: Callable[[Path, Path], None],
) -> None:
    if request is None or artifact_root is None:
        raise ValueError("production DRC requires readiness inputs")
    require_publication_request(
        request, board_file=board, artifact_root=artifact_root, project_id=project_id
    )
    generator(board, report)
    from pcbsmith.kicad.kicad_validate import run_native_erc_check
    from pcbsmith.mandatory_review import (
        native_rule_worklist,
        require_bound_native_report,
        require_mandatory_review,
    )

    erc_file = report.with_name("erc.json")
    run_native_erc_check(board.with_suffix(".kicad_sch"), erc_file)
    reports = {}
    errors = []
    for kind, path in (("erc", erc_file), ("drc", report)):
        try:
            reports[kind] = require_bound_native_report(board, kind, path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{kind}: {exc}")
    mandatory = require_mandatory_review(request.predesign, artifact_root)
    worklist = native_rule_worklist(mandatory, board.with_suffix(".kicad_pro"), reports)
    worklist["blockers"].extend(errors)
    worklist["ready"] = not worklist["blockers"]
    atomic_write(
        report.with_name("native-rule-worklist.json"),
        (json.dumps(worklist, indent=2) + "\n").encode(),
    )
    if not worklist["ready"]:
        raise ValueError("Combined native review blocked: " + "; ".join(worklist["blockers"]))


def generate_registered_board_candidate(
    *,
    generator_id: str,
    schematic_file: Path,
    output_directory: Path,
    predesign: PredesignReadinessBundle,
    artifact_root: Path,
    builder_options: Mapping[str, Any] | None = None,
    rebuild_decision: RebuildDecision | None = None,
) -> Path:
    """Enforce predesign BEFORE invoking a builder, retaining a fresh isolated attempt.

    The result is only a candidate. Publication, bounded routing/local repair,
    visual decisions and release remain owned by the existing production workflow.
    """
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    registration = registered_generator(generator_id)
    if registration.capability in {
        GeneratorPublicationCapability.PAUSED,
        GeneratorPublicationCapability.RESEARCH,
    }:
        raise ValueError("paused/research generator is unavailable for production")
    schematic_file = schematic_file.resolve()
    predecessor = require_generation_mode(schematic_file, rebuild_decision)
    from pcbsmith.kicad.project_dependencies import project_footprint_scope

    with project_footprint_scope(schematic_file.parent):
        require_predesign_bundle(predesign, artifact_root)
    from pcbsmith.mandatory_review import require_mandatory_review, require_recurring_deliverables

    require_recurring_deliverables(require_mandatory_review(predesign, artifact_root))
    if output_directory.exists():
        raise ValueError("generation target already exists; choose a fresh attempt directory")
    from pcbsmith.kicad.floorplan import require_floorplan
    from pcbsmith.kicad.layout_input import ReviewedLayoutInput

    reviewed_layout = require_floorplan(predesign, artifact_root)
    if generator_id != "pcbsmith.kicad.board:generate_board":
        raise ValueError("generator needs a validated vector-floorplan adapter")
    options = dict(builder_options or {})
    if "layout" in options:
        raise ValueError("use the floorplan-derived layout_input")
    layout_input = ReviewedLayoutInput.model_validate(options.get("layout_input", reviewed_layout))
    geometry = layout_input.model_dump(mode="json", include={"width_mm", "height_mm", "placements"})
    if geometry != ReviewedLayoutInput.model_validate(reviewed_layout).model_dump(
        mode="json", include={"width_mm", "height_mm", "placements"}
    ):
        raise ValueError("builder placement differs from reviewed vector floorplan")
    options["layout_input"] = layout_input.model_dump(mode="json")
    if {"board_file", "schematic_file", "finder", "runner"} & set(options):
        raise ValueError("builder options cannot override the isolated production boundary")
    builder = getattr(importlib.import_module(registration.module), registration.entrypoint)
    if "schematic_file" not in inspect.signature(builder).parameters:
        raise ValueError("this historical builder requires an explicit research adapter")
    source_payloads = {
        path: path.read_bytes()
        for path in (
            schematic_file,
            schematic_file.with_suffix(".kicad_pro"),
            schematic_file.with_suffix(".kicad_dru"),
            schematic_file.parent / "fp-lib-table",
            schematic_file.parent / "sym-lib-table",
            schematic_file.parent / "library-sources.json",
        )
        if path.is_file()
    }
    if schematic_file not in source_payloads:
        raise ValueError("generation schematic is missing")
    output_directory.mkdir(parents=True)
    if predecessor is not None:
        atomic_write(output_directory / "predecessor.kicad_pcb", predecessor.read_bytes())
        if rebuild_decision is None:
            raise ValueError("missing rebuild decision")
        atomic_write(
            output_directory / "rebuild-decision.json",
            (rebuild_decision.model_dump_json(indent=2) + "\n").encode(),
        )
    inputs_directory = output_directory / "design"
    inputs_directory.mkdir()
    for path, payload in source_payloads.items():
        atomic_write(inputs_directory / path.name, payload)
    # Explicit auxiliary file options are copied, so native exporters can never
    # write intermediate output beside the original input through these paths.
    for key, value in tuple(options.items()):
        if key.endswith("_file"):
            source = Path(value)
            destination = inputs_directory / source.name
            if destination.exists():
                raise ValueError("builder input filename collision")
            shutil.copy2(source, destination)
            options[key] = destination
    retained_schematic = inputs_directory / schematic_file.name
    board = retained_schematic.with_suffix(".kicad_pcb")
    retain_readiness_inputs(predesign, artifact_root, output_directory / "predesign-inputs")
    atomic_write(
        output_directory / "predesign.json", (predesign.model_dump_json(indent=2) + "\n").encode()
    )
    try:
        library_payloads = retain_project_libraries(schematic_file.parent, inputs_directory)
        source_payloads.update(library_payloads)
        if predecessor is not None:
            closure = retain_native_project(predecessor, output_directory / "predecessor-inputs")
            if rebuild_decision is None or closure != rebuild_decision.source_inputs:
                raise ValueError("rebuild predecessor dependencies changed during retention")
            for relative in closure:
                previous = schematic_file.parent / relative
                source_payloads[previous] = previous.read_bytes()
                if previous != predecessor and relative != ".pcbsmith/accepted-board-edits.json":
                    atomic_write(inputs_directory / relative, source_payloads[previous])
        from pcbsmith.kicad.native_format import upgrade_generated_native_file
        from pcbsmith.kicad.project_dependencies import project_footprint_scope

        upgrade_generated_native_file(
            retained_schematic, output_directory / "schematic-format.json"
        )
        with project_footprint_scope(inputs_directory):
            builder(schematic_file=retained_schematic, board_file=board, **options)
        if not board.is_file():
            raise ValueError("registered builder omitted its saved candidate")
        upgrade_generated_native_file(board, output_directory / "board-format.json")
        from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM
        from pcbsmith.kicad.floorplan import require_native_floorplan

        require_native_floorplan(board, reviewed_layout, origin_mm=BOARD_SHEET_ORIGIN_MM)
        if any(path.read_bytes() != payload for path, payload in source_payloads.items()):
            raise ValueError("original native inputs changed during candidate generation")
        require_generation_mode(schematic_file, rebuild_decision)
        rebuild_comparison = None
        if predecessor is not None:
            from pcbsmith.kicad.library import parse_sexpr
            from pcbsmith.kicad.native_edits import object_inventory

            try:
                before = object_inventory(parse_sexpr(predecessor.read_text(encoding="utf-8")))
                after = object_inventory(parse_sexpr(board.read_text(encoding="utf-8")))
                rebuild_comparison = {
                    "status": "compared_native_object_semantics",
                    "unchanged_ids": sorted(
                        k for k in before.keys() & after.keys() if before[k] == after[k]
                    ),
                    "changed_or_removed_ids": sorted(
                        k for k in before if before[k] != after.get(k)
                    ),
                    "added_ids": sorted(after.keys() - before.keys()),
                }
            except (ValueError, UnicodeError) as exc:
                rebuild_comparison = {"status": "comparison_unavailable", "reason": str(exc)}
            atomic_write(
                output_directory / "rebuild-comparison.json",
                (json.dumps(rebuild_comparison, indent=2) + "\n").encode(),
            )
        receipt = dict(
            status="candidate_generated",
            workflow_mode="rebuild" if predecessor else "initial_generation",
            rebuild_comparison=rebuild_comparison,
            production_accepted=False,
            rebuild_decision=rebuild_decision.model_dump(mode="json") if rebuild_decision else None,
            generator_id=generator_id,
            predesign_approval=predesign.approval.contract_fingerprint,
            predesign_readiness=predesign.readiness.report_fingerprint,
            native_inputs=native_input_hashes(board),
            project_library_inputs={
                path.relative_to(schematic_file.parent.resolve()).as_posix(): hashlib.sha256(
                    payload
                ).hexdigest()
                for path, payload in library_payloads.items()
            },
        )
        atomic_write(
            output_directory / "builder-receipt.json",
            (json.dumps(receipt, indent=2) + "\n").encode(),
        )
    except BaseException as exc:
        atomic_write(
            output_directory / "builder-failure.json",
            (
                json.dumps(
                    dict(status="failed", generator_id=generator_id, error=str(exc)), indent=2
                )
                + "\n"
            ).encode(),
        )
        raise
    return board


def generate_nonmutating_kicad_drc(
    board_file: Path,
    report_file: Path,
    *,
    schematic_parity: bool = True,
) -> None:
    """Retain exact KiCad JSON DRC without rewriting the inspected board.

    Production transactions bind model preflight, routing evidence, review,
    and DRC to one byte-exact board.  KiCad's ``--save-board`` option is
    therefore deliberately excluded here.
    """

    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI is required for production DRC")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.unlink(missing_ok=True)
    receipt_file = report_file.with_suffix(".execution.json")
    receipt_file.unlink(missing_ok=True)
    input_paths = [
        board_file,
        *(
            path
            for path in (
                board_file.with_suffix(".kicad_pro"),
                board_file.with_suffix(".kicad_sch"),
                board_file.with_suffix(".kicad_dru"),
                board_file.parent / "fp-lib-table",
                board_file.parent / "sym-lib-table",
            )
            if path.is_file()
        ),
    ]
    input_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths}
    parity = ("--schematic-parity",) if schematic_parity else ()
    command = (
        str(install.path),
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-all",
        "--output",
        str(report_file),
        *parity,
        "--refill-zones",
        str(board_file),
    )
    result = run_kicad_process(command)
    atomic_write(
        report_file.with_suffix(".process.json"),
        (
            json.dumps(
                {
                    "command": command,
                    "input_sha256s": {str(path): digest for path, digest in input_hashes.items()},
                    "report_sha256": hashlib.sha256(report_file.read_bytes()).hexdigest()
                    if report_file.is_file()
                    else None,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                indent=2,
            )
            + "\n"
        ).encode(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"KiCad DRC process failed ({result.returncode}): {result.stderr}")
    if not report_file.is_file():
        detail = result.stderr.strip() or result.stdout.strip() or "KiCad DRC failed"
        raise RuntimeError(f"KiCad DRC did not retain JSON: {detail}")
    if any(
        hashlib.sha256(path.read_bytes()).hexdigest() != digest
        for path, digest in input_hashes.items()
    ):
        raise RuntimeError("KiCad DRC inputs changed during execution")
    payload = report_file.read_bytes()
    data = validate_native_header(json.loads(payload), "DRC", board_file)
    sections = drc_sections(data)
    clean = not any(sections.values())
    context_sha256 = fingerprint(
        {
            "command_options": [option for option in command if option.startswith("--")],
            "input_files": {path.name: digest for path, digest in input_hashes.items()},
        }
    )
    record = CheckExecutionRecord.build(
        check_id="kicad.drc",
        producer_id="kicad-cli.pcb.drc",
        tool_version=data["kicad_version"],
        exact_input_sha256s=tuple(sorted({*input_hashes.values(), context_sha256})),
        evaluated_object_count=1,
        disposition=ProjectCheckDisposition.PASS if clean else ProjectCheckDisposition.FAIL,
        result_sha256=hashlib.sha256(payload).hexdigest(),
        limitations=(
            "Configured rules and all enabled severities; "
            "ignored checks and exclusions are not physical qualification.",
            *(() if schematic_parity else ("Schematic parity was not requested.",)),
        ),
    )
    atomic_write(receipt_file, (record.model_dump_json(indent=2) + "\n").encode())


__all__ = [
    "GENERATOR_REGISTRY",
    "GeneratorPublicationCapability",
    "GeneratorRegistration",
    "GeneratorRegistryAudit",
    "RegisteredRoutingPublicationEvidence",
    "audit_generator_registry",
    "discover_board_generator_ids",
    "generate_nonmutating_kicad_drc",
    "persist_registered_placement_candidate",
    "persist_registered_routed_candidate",
    "registered_generator",
]
