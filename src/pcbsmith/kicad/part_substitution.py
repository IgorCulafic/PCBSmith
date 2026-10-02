"""Source-bound same-footprint part substitutions for the shared revision owner.

No routing or geometry generation. Qualification is a retained engineering
assertion plus exact source/pin/geometry checks, never physical acceptance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from pcbsmith.evidence.component_pin_evidence import ComponentPinEvidence
from pcbsmith.kicad.component_readiness import (
    AnyPackageGeometryEvidence,
    SelectedModelPolicy,
    SmdPackageGeometryEvidence,
    _check_package_geometry,
    parse_package_geometry,
)
from pcbsmith.kicad.library import QuotedString, SList, _measure, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.model_preflight import preflight_board_models
from pcbsmith.kicad.native_edits import atom, child, children, reference
from pcbsmith.native_project import NativeProjectSpec, require_native_input_closure
from pcbsmith.operations.file_transaction import project_path
from pcbsmith.semantic_ir import SemanticIrModel


class PartSubstitution(SemanticIrModel):
    reference: str = Field(pattern=r"^[A-Z]+[0-9]+$")
    expected_mpn: str = Field(min_length=1)
    replacement_value: str = Field(min_length=1)
    pin_evidence: ComponentPinEvidence
    geometry_evidence: AnyPackageGeometryEvidence
    electrical_review_path: str = Field(min_length=1)
    electrical_review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    suitable_for_current_circuit: Literal[True]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(root: Path, relative: str, digest: str) -> Path:
    path = project_path(root, relative)
    if path.is_symlink() or not path.is_file() or _sha(path) != digest:
        raise ValueError("Substitution evidence source is missing, changed or not a regular file")
    return path


def substitution_context_files(
    board: Path, substitutions: tuple[PartSubstitution, ...]
) -> tuple[str, ...]:
    if not substitutions:
        return ()
    root = board.parent
    paths = {
        "design-spec.json",
        "netlist-vs-intent.json",
        "component-pin-evidence.json",
        "component-package-geometry.json",
        "component-model-selection.json",
        f".pcbsmith/kicad/{board.stem}.net.xml",
    }
    for name in ("component-pin-evidence.json", "component-package-geometry.json"):
        for value in json.loads((root / name).read_bytes()).values():
            evidence = (
                ComponentPinEvidence.model_validate(value)
                if name == "component-pin-evidence.json"
                else parse_package_geometry(value)
            )
            _source(root, evidence.source_local_path, evidence.source_sha256)
            paths.add(evidence.source_local_path)
    for replacement in substitutions:
        for evidence in (replacement.pin_evidence, replacement.geometry_evidence):
            _source(root, evidence.source_local_path, evidence.source_sha256)
            paths.add(evidence.source_local_path)
        _source(root, replacement.electrical_review_path, replacement.electrical_review_sha256)
        paths.add(replacement.electrical_review_path)
    for relative in paths:
        path = project_path(root, relative)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Substitution requires current project-local evidence: {relative}")
    return tuple(sorted(paths))


def _property(node: SList, name: str) -> SList:
    props = [p for p in children(node, "property") if atom(p[1]) == name]
    if len(props) != 1 or len(props[0]) < 3:
        raise ValueError(f"Substitution needs one explicit {name} property")
    return props[0]


def plan_part_substitutions(
    board: Path,
    substitutions: tuple[PartSubstitution, ...],
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    """Compute a reproducible project delta without changing any source files."""
    if not substitutions:
        return {}, []
    root = board.parent
    context = substitution_context_files(board, substitutions)
    before = {relative: _sha(root / relative) for relative in context}
    spec = NativeProjectSpec.model_validate_json((root / "design-spec.json").read_bytes())
    if spec.project_id != board.stem:
        raise ValueError("Substitution requires matching native project and board identities")
    require_native_input_closure(spec, root)
    pcb = parse_sexpr(board.read_text(encoding="utf-8"))
    sch_path = board.with_suffix(".kicad_sch")
    schematic = parse_sexpr(sch_path.read_text(encoding="utf-8"))
    if children(schematic, "sheet"):
        raise ValueError("Substitution currently supports a single-sheet native project")
    pins = json.loads((root / "component-pin-evidence.json").read_bytes())
    geometry = json.loads((root / "component-package-geometry.json").read_bytes())
    policy = SelectedModelPolicy.model_validate_json(
        (root / "component-model-selection.json").read_bytes()
    )
    registry = tuple(
        e.model_copy(update={"local_path": str((root / e.local_path).resolve())})
        if e.local_path is not None
        else e
        for e in policy.registry
    )
    model_report = preflight_board_models(
        board,
        registry=registry,
        requirements=policy.requirements,
        applicability=policy.applicability,
        applicability_rationale=policy.rationale,
    )
    if model_report.status not in {"passed", "not_applicable"}:
        raise ValueError("Substitution source model policy does not pass")
    updated_parts = {part.reference: part for part in spec.parts}
    records = []
    if len({s.reference for s in substitutions}) != len(substitutions):
        raise ValueError("Duplicate substitution reference")
    for item in substitutions:
        if (
            not item.reviewer_id.strip()
            or not item.rationale.strip()
            or not item.replacement_value.strip()
        ):
            raise ValueError("Substitution requires a current electrical review assertion")
        part = updated_parts.get(item.reference)
        if part is None or part.mpn != item.expected_mpn:
            raise ValueError("Substitution source part differs from the declared predecessor")
        mpn = item.pin_evidence.part_number
        if mpn == part.mpn or mpn != item.geometry_evidence.part_number:
            raise ValueError("Replacement MPN must be new and match pin/geometry evidence")
        fps = [fp for fp in children(pcb, "footprint") if reference(fp) == item.reference]
        symbols = [s for s in children(schematic, "symbol") if reference(s) == item.reference]
        if len(fps) != 1 or len(symbols) != 1:
            raise ValueError("Substitution reference is missing or ambiguous in native inputs")
        fp, symbol = fps[0], symbols[0]
        if "locked" in fp or children(fp, "locked"):
            raise ValueError("Locked components cannot be substituted")
        if atom(child(fp, "layer")[1]) != "F.Cu":
            raise ValueError("Substitution geometry currently supports front-side components only")
        if (
            atom(fp[1]) != part.footprint
            or atom(_property(symbol, "Footprint")[2]) != part.footprint
        ):
            raise ValueError("Substitution must preserve the exact source footprint")
        old_pin = ComponentPinEvidence.model_validate(pins[item.reference])
        old_geometry = parse_package_geometry(geometry[item.reference])
        if old_pin.part_number != part.mpn or old_geometry.part_number != part.mpn:
            raise ValueError("Source pin/geometry evidence targets another MPN")

        def functions(
            evidence: ComponentPinEvidence,
        ) -> dict[str, tuple[str, str, tuple[str, ...]]]:
            return {p.number: (p.name, p.electrical_role, p.functions) for p in evidence.pins}

        if functions(old_pin) != functions(item.pin_evidence) or any(
            pin.electrical_role == "unknown" for pin in item.pin_evidence.pins
        ):
            raise ValueError("Replacement pin functions require remapping or unresolved review")
        measured = _measure(fp, part.footprint)
        # Saved board pad angles include the parent rotation; package evidence
        # and pad positions use footprint-local coordinates.
        at = child(fp, "at")
        angle = float(atom(at[3])) if len(at) > 3 else 0.0
        measured = replace(
            measured,
            pads=tuple(replace(pad, angle_deg=pad.angle_deg - angle) for pad in measured.pads),
        )
        if {p.name for p in measured.pads if p.name} != set(part.pins):
            raise ValueError("Saved footprint pin inventory differs from source specification")
        if set(part.pins) != {p.number for p in item.pin_evidence.pins}:
            raise ValueError("Replacement pin coverage differs from source specification")
        _check_package_geometry(measured, old_geometry)
        _check_package_geometry(measured, item.geometry_evidence)
        for pad in children(fp, "pad"):
            number = atom(pad[1])
            if not number:
                continue
            nets = children(pad, "net")
            actual = atom(nets[0][-1]).removeprefix("/") if nets else None
            wanted = part.pins[number]
            if wanted is None:
                if actual and not actual.startswith("unconnected-"):
                    raise ValueError("Saved no-connect pin acquired a net")
            elif actual != wanted:
                raise ValueError("Saved board pin nets differ from substitution source intent")
        if policy.applicability == "applicable" and (
            item.reference not in model_report.required_references
            or any(
                model.classification != "proxy" or model.transform_alignment != "passed"
                for model in model_report.models
                if model.reference == item.reference
            )
        ):
            raise ValueError(
                "Replacement requires fresh exact-model qualification; proxy-only reuse supported"
            )
        for native in (fp, symbol):
            if (
                atom(_property(native, "MPN")[2]) != part.mpn
                or atom(_property(native, "Value")[2]) != part.value
            ):
                raise ValueError("Native part metadata differs from the source specification")
            _property(native, "MPN")[2] = QuotedString(mpn)
            _property(native, "Value")[2] = QuotedString(item.replacement_value)
        updated_parts[item.reference] = part.model_copy(
            update={"mpn": mpn, "value": item.replacement_value}
        )
        pins[item.reference] = item.pin_evidence.model_dump(mode="json")
        geometry[item.reference] = item.geometry_evidence.model_dump(mode="json")
        records.append(
            {
                "reference": item.reference,
                "from_mpn": part.mpn,
                "to_mpn": mpn,
                "footprint": part.footprint,
                "pin_functions": "same_declared_mapping",
                "geometry": (
                    "source_bound_smd_land_screen_passed"
                    if isinstance(item.geometry_evidence, SmdPackageGeometryEvidence)
                    else "source_bound_round_tht_screen_passed"
                ),
                "reviewer_id": item.reviewer_id,
                "electrical_review_sha256": item.electrical_review_sha256,
                "physical_qualification": "unverified",
                "production_accepted": False,
            }
        )
    if any(_sha(root / relative) != digest for relative, digest in before.items()):
        raise ValueError("Substitution evidence changed during planning")
    changed_spec = spec.model_copy(
        update={"parts": tuple(updated_parts[p.reference] for p in spec.parts)}
    )
    return {
        board.name: (serialize_sexpr(pcb) + "\n").encode(),
        sch_path.name: (serialize_sexpr(schematic) + "\n").encode(),
        "design-spec.json": (changed_spec.model_dump_json(indent=2) + "\n").encode(),
        "component-pin-evidence.json": (json.dumps(pins, indent=2) + "\n").encode(),
        "component-package-geometry.json": (json.dumps(geometry, indent=2) + "\n").encode(),
    }, records


def refresh_substitution_closure(board: Path) -> None:
    """Use a fresh native export, never an edited or fabricated positive netlist."""
    from pcbsmith.board_job import require_library_worker
    from pcbsmith.kicad.board import export_kicad_netlist_xml
    from pcbsmith.native_project import inspect_native_input_closure
    from pcbsmith.operations.file_transaction import atomic_write

    require_library_worker()
    spec = NativeProjectSpec.model_validate_json((board.parent / "design-spec.json").read_bytes())
    schematic = board.with_suffix(".kicad_sch")
    xml = export_kicad_netlist_xml(schematic)
    _, report = inspect_native_input_closure(spec, schematic, xml)
    if report["status"] != "passed":
        raise ValueError("Substitution native export differs from current part/pin intent")
    atomic_write(
        board.parent / "netlist-vs-intent.json", (json.dumps(report, indent=2) + "\n").encode()
    )
    require_native_input_closure(spec, board.parent)
