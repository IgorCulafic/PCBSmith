"""Resolve and classify every KiCad footprint 3D model before rendering."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr

ModelClassification = Literal[
    "exact_package",
    "complete_module",
    "connector_only",
    "proxy",
    "unknown",
]
ModelResolutionStatus = Literal["resolved", "unresolved", "hash_mismatch"]
ModelApplicability = Literal["applicable", "not_applicable", "unresolved"]
PreflightStatus = Literal[
    "passed",
    "not_applicable",
    "attention_required",
    "failed",
]


class ModelTransform(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    offset_xyz: tuple[str, str, str] = ("0", "0", "0")
    scale_xyz: tuple[str, str, str] = ("1", "1", "1")
    rotate_xyz: tuple[str, str, str] = ("0", "0", "0")

    @model_validator(mode="after")
    def finite_coordinates(self) -> ModelTransform:
        for values in (self.offset_xyz, self.scale_xyz, self.rotate_xyz):
            try:
                valid = all(math.isfinite(float(value)) for value in values)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("model transform coordinates must be finite numbers")
        return self


class ModelTransformTolerance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    offset_mm: float = Field(default=0.01, ge=0)
    scale_ratio: float = Field(default=0.001, ge=0)
    rotation_deg: float = Field(default=0.1, ge=0)


class ModelRegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_path: str
    classification: ModelClassification
    license_status: str = Field(min_length=1)
    part_number: str | None = None
    source_url: str | None = None
    local_path: str | None = None
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_transform: ModelTransform | None = None
    transform_tolerance: ModelTransformTolerance = ModelTransformTolerance()
    redistributable: bool = False


class ModelRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    accepted_classifications: tuple[ModelClassification, ...] = Field(min_length=1)


class ModelResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    footprint: str
    raw_path: str
    resolved_path: str | None = None
    status: ModelResolutionStatus
    sha256: str | None = None
    classification: ModelClassification = "unknown"
    license_status: str = "unregistered"
    part_number: str | None = None
    source_url: str | None = None
    redistributable: bool = False
    transform: ModelTransform = ModelTransform()
    transform_alignment: Literal["not_declared", "passed", "failed"] = "not_declared"
    findings: tuple[str, ...] = ()


class ModelPreflightReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-kicad-model-preflight-v1"] = Field(
        validation_alias="schema", serialization_alias="schema"
    )
    board_file: str
    board_sha256: str
    status: PreflightStatus
    applicability: ModelApplicability
    applicability_rationale: str | None = None
    models: tuple[ModelResolution, ...]
    required_references: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def applicability_is_non_vacuous(self) -> ModelPreflightReport:
        if self.applicability == "applicable" and not self.required_references:
            if self.status != "failed":
                raise ValueError("applicable model preflight requires declared references")
        if self.applicability == "not_applicable":
            if not self.applicability_rationale:
                raise ValueError("not-applicable model preflight requires a rationale")
            if self.status != "not_applicable":
                raise ValueError("not-applicable model preflight has a stale status")
        if self.applicability == "unresolved" and self.status == "passed":
            raise ValueError("unresolved model applicability cannot pass")
        return self


class ModelInventoryAssessment(BaseModel):
    """Shared resolution/policy result, without claiming a saved-board identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: PreflightStatus
    applicability: ModelApplicability
    applicability_rationale: str | None = None
    models: tuple[ModelResolution, ...]
    required_references: tuple[str, ...]
    findings: tuple[str, ...]


def preflight_board_models(
    board_file: Path,
    *,
    registry: tuple[ModelRegistryEntry, ...] = (),
    requirements: tuple[ModelRequirement, ...] = (),
    variables: dict[str, str] | None = None,
    applicability: ModelApplicability | None = None,
    applicability_rationale: str | None = None,
) -> ModelPreflightReport:
    board_path = board_file.resolve()
    payload = board_path.read_bytes()
    root = parse_sexpr(payload.decode("utf-8"))
    inventory = tuple(
        (
            _footprint_reference(fp),
            _atom(fp[1]) if len(fp) > 1 else "unknown",
            _direct_children(fp, "model"),
        )
        for fp in _children(root, {"footprint", "module"})
    )
    assessment = preflight_model_inventory(
        inventory,
        project_dir=board_path.parent,
        registry=registry,
        requirements=requirements,
        variables=variables,
        applicability=applicability,
        applicability_rationale=applicability_rationale,
    )
    return ModelPreflightReport(
        schema_id="pcbsmith-kicad-model-preflight-v1",
        board_file=str(board_path),
        board_sha256=hashlib.sha256(payload).hexdigest(),
        **assessment.model_dump(),
    )


def preflight_model_inventory(
    footprints: tuple[tuple[str, str, tuple[SList, ...]], ...],
    *,
    project_dir: Path,
    registry: tuple[ModelRegistryEntry, ...] = (),
    requirements: tuple[ModelRequirement, ...] = (),
    variables: dict[str, str] | None = None,
    applicability: ModelApplicability | None = None,
    applicability_rationale: str | None = None,
) -> ModelInventoryAssessment:
    """Evaluate actual model clauses from selected footprints or a saved board.

    Callers bind their own exact input files. This result has no board identity
    and cannot substitute for the final saved-board preflight.
    """
    registry_by_path = {_normalized_path(entry.raw_path): entry for entry in registry}
    if len(registry_by_path) != len(registry):
        raise ValueError("ambiguous duplicate model registry paths")
    if len({item.reference for item in requirements}) != len(requirements):
        raise ValueError("ambiguous duplicate model requirement references")
    resolution_variables = _resolution_variables(variables)
    resolution_variables.setdefault("KIPRJMOD", str(project_dir.resolve()))
    models: list[ModelResolution] = []
    footprint_references: set[str] = set()

    for reference, footprint_name, model_nodes in footprints:
        if reference in footprint_references:
            raise ValueError(f"ambiguous duplicate footprint reference: {reference}")
        if reference == "<unknown>" or not reference.strip():
            raise ValueError("model preflight requires an explicit footprint reference")
        footprint_references.add(reference)
        for model in model_nodes:
            raw_path = _atom(model[1]) if len(model) > 1 else ""
            entry = registry_by_path.get(_normalized_path(raw_path))
            resolved: Path | None
            resolve_finding: str | None
            if entry is not None and entry.local_path is not None:
                resolved = Path(entry.local_path).resolve()
                resolve_finding = None
            else:
                resolved, resolve_finding = _resolve_model_path(
                    raw_path,
                    board_dir=project_dir.resolve(),
                    variables=resolution_variables,
                )
            findings: list[str] = []
            if resolve_finding is not None:
                findings.append(resolve_finding)
            model_status: ModelResolutionStatus = "unresolved"
            digest: str | None = None
            if resolved is not None and resolved.is_file():
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
                model_status = "resolved"
                if entry is not None and entry.expected_sha256 not in {None, digest}:
                    model_status = "hash_mismatch"
                    findings.append(
                        f"Expected model SHA-256 {entry.expected_sha256}, got {digest}."
                    )
            elif resolved is not None:
                findings.append(f"Resolved model path does not exist: {resolved}")
            transform = _model_transform(model)
            transform_alignment: Literal["not_declared", "passed", "failed"] = "not_declared"
            if entry is not None and entry.expected_transform is not None:
                transform_findings = _transform_findings(
                    actual=transform,
                    expected=entry.expected_transform,
                    tolerance=entry.transform_tolerance,
                )
                if transform_findings:
                    transform_alignment = "failed"
                    findings.extend(transform_findings)
                else:
                    transform_alignment = "passed"
            models.append(
                ModelResolution(
                    reference=reference,
                    footprint=footprint_name,
                    raw_path=raw_path,
                    resolved_path=None if resolved is None else str(resolved),
                    status=model_status,
                    sha256=digest,
                    classification="unknown" if entry is None else entry.classification,
                    license_status="unregistered" if entry is None else entry.license_status,
                    part_number=None if entry is None else entry.part_number,
                    source_url=None if entry is None else entry.source_url,
                    redistributable=False if entry is None else entry.redistributable,
                    transform=transform,
                    transform_alignment=transform_alignment,
                    findings=tuple(findings),
                )
            )

    report_findings: list[str] = []
    failed = False
    requirement_by_ref = {requirement.reference: requirement for requirement in requirements}
    if requirement_by_ref:
        if applicability == "not_applicable":
            raise ValueError("declared model requirements cannot be not applicable")
        effective_applicability: ModelApplicability = "applicable"
    else:
        effective_applicability = applicability or "unresolved"
        if effective_applicability == "not_applicable" and not applicability_rationale:
            raise ValueError("not-applicable model preflight requires a rationale")
        if effective_applicability == "applicable":
            failed = True
            report_findings.append(
                "3D models are applicable, but no required component references were declared."
            )
        elif effective_applicability == "unresolved":
            report_findings.append(
                "Required 3D-model applicability was not declared; "
                "populated rendering is unverified."
            )
    for reference, requirement in sorted(requirement_by_ref.items()):
        if reference not in footprint_references:
            failed = True
            report_findings.append(f"Required reference {reference} is absent from the board.")
            continue
        candidates = tuple(item for item in models if item.reference == reference)
        acceptable = tuple(
            item
            for item in candidates
            if item.status == "resolved"
            and item.classification in requirement.accepted_classifications
            and item.transform_alignment != "failed"
        )
        if not acceptable:
            failed = True
            accepted = ", ".join(requirement.accepted_classifications)
            report_findings.append(
                f"Required reference {reference} has no resolved model classified as {accepted}."
            )

    unresolved_optional = tuple(
        item
        for item in models
        if item.status != "resolved" and item.reference not in requirement_by_ref
    )
    if unresolved_optional:
        report_findings.append(
            f"{len(unresolved_optional)} non-required model reference(s) did not resolve cleanly."
        )
    unregistered = tuple(item for item in models if item.classification == "unknown")
    if unregistered:
        report_findings.append(
            f"{len(unregistered)} model reference(s) have no "
            "exact/proxy/license registry classification."
        )
    optional_misaligned = tuple(
        item
        for item in models
        if item.transform_alignment == "failed" and item.reference not in requirement_by_ref
    )
    if optional_misaligned:
        report_findings.append(
            f"{len(optional_misaligned)} optional model transform(s) differ from "
            "their registered alignment."
        )

    report_status: PreflightStatus
    if effective_applicability == "not_applicable":
        report_status = "not_applicable"
    elif failed:
        report_status = "failed"
    elif (
        effective_applicability == "unresolved"
        or unresolved_optional
        or unregistered
        or optional_misaligned
    ):
        report_status = "attention_required"
    else:
        report_status = "passed"
    return ModelInventoryAssessment(
        status=report_status,
        applicability=effective_applicability,
        applicability_rationale=applicability_rationale,
        models=tuple(models),
        required_references=tuple(sorted(requirement_by_ref)),
        findings=tuple(report_findings),
    )


def _resolution_variables(overrides: dict[str, str] | None) -> dict[str, str]:
    variables = dict(os.environ)
    known_roots = {
        "KICAD10_3DMODEL_DIR": Path("C:/Program Files/KiCad/10.0/share/kicad/3dmodels"),
        "KICAD9_3DMODEL_DIR": Path("C:/Program Files/KiCad/9.0/share/kicad/3dmodels"),
        "KICAD8_3DMODEL_DIR": Path("C:/Program Files/KiCad/8.0/share/kicad/3dmodels"),
        "KICAD7_3DMODEL_DIR": Path("C:/Program Files/KiCad/7.0/share/kicad/3dmodels"),
    }
    for name, path in known_roots.items():
        if name not in variables and path.exists():
            variables[name] = str(path)
    if "KISYS3DMOD" not in variables and "KICAD10_3DMODEL_DIR" in variables:
        variables["KISYS3DMOD"] = variables["KICAD10_3DMODEL_DIR"]
    if overrides:
        variables.update(overrides)
    return variables


def _resolve_model_path(
    raw_path: str,
    *,
    board_dir: Path,
    variables: dict[str, str],
) -> tuple[Path | None, str | None]:
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name)
        if value is None:
            unknown.append(name)
            return match.group(0)
        return value

    expanded = re.sub(r"\$\{([^}]+)\}", replace, raw_path)
    if unknown:
        return None, f"Unresolved KiCad model variable(s): {', '.join(sorted(set(unknown)))}"
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = board_dir / candidate
    return candidate.resolve(), None


def _model_transform(model: SList) -> ModelTransform:
    return ModelTransform(
        offset_xyz=_xyz_child(model, "offset", default=("0", "0", "0")),
        scale_xyz=_xyz_child(model, "scale", default=("1", "1", "1")),
        rotate_xyz=_xyz_child(model, "rotate", default=("0", "0", "0")),
    )


def _transform_findings(
    *,
    actual: ModelTransform,
    expected: ModelTransform,
    tolerance: ModelTransformTolerance,
) -> tuple[str, ...]:
    findings: list[str] = []
    comparisons = (
        (
            "offset",
            actual.offset_xyz,
            expected.offset_xyz,
            tolerance.offset_mm,
            False,
        ),
        (
            "scale",
            actual.scale_xyz,
            expected.scale_xyz,
            tolerance.scale_ratio,
            False,
        ),
        (
            "rotation",
            actual.rotate_xyz,
            expected.rotate_xyz,
            tolerance.rotation_deg,
            True,
        ),
    )
    for name, actual_values, expected_values, allowed, angular in comparisons:
        try:
            actual_numbers = tuple(float(value) for value in actual_values)
            expected_numbers = tuple(float(value) for value in expected_values)
        except ValueError:
            findings.append(f"Registered {name} alignment contains a non-numeric value.")
            continue
        deltas = tuple(
            (
                abs(((actual_value - expected_value + 180.0) % 360.0) - 180.0)
                if angular
                else abs(actual_value - expected_value)
            )
            for actual_value, expected_value in zip(actual_numbers, expected_numbers, strict=True)
        )
        if any(delta > allowed for delta in deltas):
            findings.append(
                f"Model {name} {actual_values!r} differs from registered "
                f"{expected_values!r}; tolerance={allowed:g}."
            )
    return tuple(findings)


def _xyz_child(
    node: SList,
    name: str,
    *,
    default: tuple[str, str, str],
) -> tuple[str, str, str]:
    parents = _direct_children(node, name)
    if not parents:
        return default
    if len(parents) != 1:
        raise ValueError(f"duplicate model transform clause: {name}")
    coordinates = _direct_children(parents[0], "xyz")
    if len(coordinates) != 1 or len(coordinates[0]) != 4:
        raise ValueError(f"malformed model transform clause: {name}")
    xyz = coordinates[0]
    return (_atom(xyz[1]), _atom(xyz[2]), _atom(xyz[3]))


def _footprint_reference(footprint: SList) -> str:
    for child in _direct_children(footprint, "property"):
        if len(child) > 2 and _atom(child[1]) == "Reference":
            return _atom(child[2])
    for child in _direct_children(footprint, "fp_text"):
        if len(child) > 2 and _atom(child[1]) == "reference":
            return _atom(child[2])
    return "<unknown>"


def _children(node: SList, heads: set[str]) -> tuple[SList, ...]:
    found: list[SList] = []
    for child in node:
        if isinstance(child, list):
            if child and _atom(child[0]) in heads:
                found.append(child)
            found.extend(_children(child, heads))
    return tuple(found)


def _direct_children(node: SList, head: str) -> tuple[SList, ...]:
    return tuple(
        child for child in node if isinstance(child, list) and child and _atom(child[0]) == head
    )


def _atom(node: SExpr) -> str:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    raise ValueError("Expected a KiCad atom, got a list.")


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").casefold()
