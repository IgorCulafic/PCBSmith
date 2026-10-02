"""Read-only selected-part inventory before placement; never package approval.

Reuse native input, exact footprint resolution and model path owners. CAD body and
pad dimensions are observations, not purchased-part or datasheet qualification.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from pcbsmith.evidence.component_pin_evidence import ComponentPinEvidence
from pcbsmith.kicad.library import FootprintSpec, PadSpec, _atom, _children, load_footprint
from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    _resolution_variables,
    _resolve_model_path,
    preflight_model_inventory,
)
from pcbsmith.kicad.project_dependencies import project_footprint_scope
from pcbsmith.native_project import NativeProjectSpec, require_native_input_closure


class SelectedModelPolicy(BaseModel):
    """Explicit selected-model scope; file availability alone is not acceptance."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    applicability: Literal["applicable", "not_applicable"]
    rationale: str = Field(min_length=1)
    registry: tuple[ModelRegistryEntry, ...] = ()
    requirements: tuple[ModelRequirement, ...] = ()

    @model_validator(mode="after")
    def bound_selection(self) -> SelectedModelPolicy:
        if not self.rationale.strip():
            raise ValueError("Selected model policy requires a rationale")
        if self.applicability == "not_applicable":
            if self.registry or self.requirements:
                raise ValueError("Not-applicable selection cannot declare required models")
        elif not self.requirements or not self.registry:
            raise ValueError("Selected model policy requires registry and references")
        elif any(
            item.expected_sha256 is None or item.expected_transform is None
            for item in self.registry
        ):
            raise ValueError("Selected models require exact hashes and expected transforms")
        return self


class PackagePinGeometry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    number: str = Field(min_length=1)
    x_mm: float
    y_mm: float
    maximum_lead_diameter_mm: float = Field(gt=0)


class PackageGeometryEvidence(BaseModel):
    """Explicit THT procurement geometry in the footprint's local coordinate frame."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    part_number: str = Field(min_length=1)
    source_local_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page: int = Field(ge=1)
    coordinate_basis: str = Field(min_length=1)
    body_bounds_mm: tuple[float, float, float, float]
    pins: tuple[PackagePinGeometry, ...] = Field(min_length=1)
    maximum_position_error_mm: float = Field(ge=0)
    minimum_diametral_clearance_mm: float = Field(ge=0)

    @model_validator(mode="after")
    def coherent(self) -> PackageGeometryEvidence:
        x0, y0, x1, y1 = self.body_bounds_mm
        if x0 >= x1 or y0 >= y1:
            raise ValueError("package body bounds must have positive dimensions")
        if len({pin.number for pin in self.pins}) != len(self.pins):
            raise ValueError("duplicate package geometry pin")
        return self


class SmdPackagePinGeometry(BaseModel):
    """Source-reviewed rectangles in footprint-local axes, including tolerances.

    Terminal contact bounds describe guaranteed contact, not the maximum outer
    terminal envelope. Required land bounds are the reviewed minimum copper
    region, not a bounding box inferred from the existing pad.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    number: str = Field(min_length=1)
    terminal_contact_bounds_mm: tuple[float, float, float, float]
    required_land_bounds_mm: tuple[float, float, float, float]
    minimum_contact_size_mm: tuple[float, float]

    @model_validator(mode="after")
    def coherent(self) -> SmdPackagePinGeometry:
        for bounds in (self.terminal_contact_bounds_mm, self.required_land_bounds_mm):
            if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                raise ValueError("SMD contact and land bounds must have positive dimensions")
        if any(size <= 0 for size in self.minimum_contact_size_mm):
            raise ValueError("SMD minimum contact dimensions must be positive")
        return self


class SmdPackageGeometryEvidence(BaseModel):
    """Explicit SMD source geometry; not solder/process or physical acceptance."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    mounting: Literal["smd"]
    part_number: str = Field(min_length=1)
    source_local_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page: int = Field(ge=1)
    coordinate_basis: str = Field(min_length=1)
    land_pattern_basis: str = Field(min_length=1)
    body_bounds_mm: tuple[float, float, float, float]
    pins: tuple[SmdPackagePinGeometry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self) -> SmdPackageGeometryEvidence:
        if not self.coordinate_basis.strip() or not self.land_pattern_basis.strip():
            raise ValueError("SMD geometry requires coordinate and land-pattern review bases")
        x0, y0, x1, y1 = self.body_bounds_mm
        if x0 >= x1 or y0 >= y1:
            raise ValueError("package body bounds must have positive dimensions")
        if len({pin.number for pin in self.pins}) != len(self.pins):
            raise ValueError("duplicate package geometry pin")
        return self


AnyPackageGeometryEvidence = PackageGeometryEvidence | SmdPackageGeometryEvidence
_PACKAGE_GEOMETRY: TypeAdapter[AnyPackageGeometryEvidence] = TypeAdapter(AnyPackageGeometryEvidence)


def parse_package_geometry(value: Any) -> AnyPackageGeometryEvidence:
    """Accept historical untagged THT records and explicitly tagged SMD records."""
    return _PACKAGE_GEOMETRY.validate_python(value)


def _smd_pad_contains(pad: PadSpec, x: float, y: float) -> bool:
    # Inverse KiCad pad rotation: CCW on screen, with y increasing downward.
    theta = math.radians(pad.angle_deg)
    dx, dy = x - pad.x_mm, y - pad.y_mm
    px = abs(dx * math.cos(theta) - dy * math.sin(theta))
    py = abs(dx * math.sin(theta) + dy * math.cos(theta))
    half_x, half_y = pad.width_mm / 2, pad.height_mm / 2
    eps = 1e-9  # floating-point arithmetic only; never a fabrication allowance
    if px > half_x + eps or py > half_y + eps:
        return False
    if pad.shape == "rect":
        return True
    ratio = pad.roundrect_rratio
    if ratio is None or not math.isfinite(ratio) or not 0 <= ratio <= 0.5:
        raise ValueError("SMD roundrect pad needs a valid explicit corner ratio")
    radius = min(pad.width_mm, pad.height_mm) * ratio
    return math.hypot(max(0, px - half_x + radius), max(0, py - half_y + radius)) <= radius + eps


def _check_smd_package_geometry(
    footprint: FootprintSpec, evidence: SmdPackageGeometryEvidence
) -> None:
    # Require all copper pads to be numbered; extra unnamed SMD copper needs
    # an explicit future adapter, not silent omission from terminal coverage.
    if any(not pad.name for pad in footprint.pads):
        raise ValueError("SMD geometry screen requires numbered pads")
    pads = {pad.name: pad for pad in footprint.pads}
    if len(pads) != len(footprint.pads):
        raise ValueError("package geometry screen does not support repeated physical pad numbers")
    if set(pads) != {pin.number for pin in evidence.pins}:
        raise ValueError("package geometry pin coverage differs from footprint")
    for pin in evidence.pins:
        pad = pads[pin.number]
        if (
            pad.kind != "smd"
            or pad.hole is not None
            or pad.drill_mm != 0
            or pad.shape not in {"rect", "roundrect"}
            or pad.chamfer_positions
            or pad.chamfer_ratio not in {None, 0}
            or {layer for layer in pad.layers if layer.endswith(".Cu")} != {"F.Cu"}
            or not all(
                math.isfinite(v)
                for v in (pad.x_mm, pad.y_mm, pad.angle_deg, pad.width_mm, pad.height_mm)
            )
            or pad.width_mm <= 0
            or pad.height_mm <= 0
        ):
            raise ValueError("SMD geometry requires undrilled front rectangular/roundrect pads")
        x0, y0, x1, y1 = pin.required_land_bounds_mm
        # Rect and roundrect copper are convex: all four corners contained
        # proves containment of the entire required land rectangle.
        if not all(
            _smd_pad_contains(pad, x, y) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))
        ):
            raise ValueError(f"SMD pin {pin.number} required land exceeds actual pad copper")
        tx0, ty0, tx1, ty1 = pin.terminal_contact_bounds_mm
        overlap = (min(x1, tx1) - max(x0, tx0), min(y1, ty1) - max(y0, ty0))
        if any(
            actual + 1e-9 < required
            for actual, required in zip(overlap, pin.minimum_contact_size_mm, strict=True)
        ):
            raise ValueError(f"SMD pin {pin.number} terminal contact is insufficient")
    _check_body_containment(footprint, evidence.body_bounds_mm, 0.0)


def _check_package_geometry(footprint: FootprintSpec, evidence: AnyPackageGeometryEvidence) -> None:
    if isinstance(evidence, SmdPackageGeometryEvidence):
        _check_smd_package_geometry(footprint, evidence)
        return
    pads = {pad.name: pad for pad in footprint.pads if pad.name}
    if len(pads) != len([pad for pad in footprint.pads if pad.name]):
        raise ValueError("package geometry screen does not support repeated physical pad numbers")
    if set(pads) != {pin.number for pin in evidence.pins}:
        raise ValueError("package geometry pin coverage differs from footprint")
    for pin in evidence.pins:
        pad = pads[pin.number]
        hole = pad.hole
        if (
            pad.kind not in {"tht", "thru_hole"}
            or hole is None
            or hole.is_slot
            or hole.offset_x_mm != 0
            or hole.offset_y_mm != 0
        ):
            raise ValueError("package geometry screen requires centered round through-hole pads")
        if (
            math.hypot(pad.x_mm - pin.x_mm, pad.y_mm - pin.y_mm)
            > evidence.maximum_position_error_mm
        ):
            raise ValueError(f"package pin {pin.number} position/pitch differs from footprint")
        required = pin.maximum_lead_diameter_mm + evidence.minimum_diametral_clearance_mm
        if hole.minor_mm < required:
            raise ValueError(f"package pin {pin.number} lead/clearance exceeds nominal CAD hole")
    _check_body_containment(footprint, evidence.body_bounds_mm, evidence.maximum_position_error_mm)


def _check_body_containment(
    footprint: FootprintSpec, bounds: tuple[float, float, float, float], tolerance: float
) -> None:
    hull = footprint.courtyard_hull
    if hull is None or len(hull) < 3:
        raise ValueError("package body containment needs a footprint courtyard")
    x0, y0, x1, y1 = bounds
    for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
        distances = []
        for a, b in zip(hull, (*hull[1:], hull[0]), strict=True):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length:
                distances.append(((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) / length)
        if not distances or not (
            all(d >= -tolerance for d in distances) or all(d <= tolerance for d in distances)
        ):
            raise ValueError("source-bound package body exceeds footprint courtyard")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_component_readiness(spec: NativeProjectSpec, project: Path) -> dict[str, Any]:
    """Inventory current selected assets; reject mismatched supplied pin evidence.

    Optional component-pin-evidence.json is a reference -> ComponentPinEvidence
    mapping. No prior review decision is consumed. Missing evidence stays unknown.
    """
    project = project.resolve()
    require_native_input_closure(spec, project)
    retained_spec = NativeProjectSpec.model_validate_json(
        (project / "design-spec.json").read_bytes()
    )
    if spec != retained_spec:
        raise ValueError("Component inventory specification differs from native project")
    inputs = {
        str(path): _sha(path)
        for path in (
            project / "design-spec.json",
            project / "netlist-vs-intent.json",
            project / (spec.project_id + ".kicad_sch"),
            project / ".pcbsmith/kicad" / (spec.project_id + ".net.xml"),
        )
    }
    for name in ("fp-lib-table", "sym-lib-table", "library-sources.json", "Project.kicad_sym"):
        path = project / name
        if path.is_file():
            inputs[str(path)] = _sha(path)
    evidence_path = project / "component-pin-evidence.json"
    pin_evidence: dict[str, ComponentPinEvidence] = {}
    if evidence_path.exists():
        payload = evidence_path.read_bytes()
        inputs[str(evidence_path)] = hashlib.sha256(payload).hexdigest()
        pin_evidence = {
            reference: ComponentPinEvidence.model_validate(value)
            for reference, value in json.loads(payload).items()
        }
        if not set(pin_evidence) <= {part.reference for part in spec.parts}:
            raise ValueError("Pin evidence contains an undeclared component reference")
    geometry_path = project / "component-package-geometry.json"
    geometry: dict[str, AnyPackageGeometryEvidence] = {}
    if geometry_path.exists():
        payload = geometry_path.read_bytes()
        inputs[str(geometry_path)] = hashlib.sha256(payload).hexdigest()
        geometry = {
            ref: parse_package_geometry(value) for ref, value in json.loads(payload).items()
        }
        if not set(geometry) <= {part.reference for part in spec.parts}:
            raise ValueError("Package geometry contains an undeclared component reference")
    selection_path = project / "component-model-selection.json"
    selection: SelectedModelPolicy | None = None
    if selection_path.exists():
        payload = selection_path.read_bytes()
        inputs[str(selection_path)] = hashlib.sha256(payload).hexdigest()
        selection = SelectedModelPolicy.model_validate_json(payload)
        required = {item.reference for item in selection.requirements}
        populated = {part.reference for part in spec.parts if part.populated}
        declared = {part.reference for part in spec.parts}
        if selection.applicability == "applicable" and (
            not populated <= required or not required <= declared
        ):
            raise ValueError(
                "Selected model requirements must cover populated parts "
                "and only declared references"
            )
        selection = selection.model_copy(
            update={
                "registry": tuple(
                    entry.model_copy(
                        update={"local_path": str((project / entry.local_path).resolve())}
                    )
                    if entry.local_path is not None
                    else entry
                    for entry in selection.registry
                )
            }
        )
    model_inventory = []
    components = []
    variables = _resolution_variables(None)
    variables["KIPRJMOD"] = str(project)
    with project_footprint_scope(project):
        for part in spec.parts:
            footprint = load_footprint(part.footprint, verify_content=True)
            inputs[str(footprint.source_file.resolve())] = _sha(footprint.source_file)
            actual_pins = {pad.name for pad in footprint.spec.pads if pad.name}
            if actual_pins != set(part.pins):
                raise ValueError(f"{part.reference}: current footprint pins differ from intent")
            evidence = pin_evidence.get(part.reference)
            pin_status = "not_supplied"
            if evidence is not None:
                source = Path(evidence.source_local_path)
                if not source.is_absolute():
                    source = project / source
                if not source.is_file() or _sha(source) != evidence.source_sha256:
                    raise ValueError(f"{part.reference}: missing or changed pin-evidence source")
                if evidence.part_number != part.mpn:
                    raise ValueError(f"{part.reference}: pin evidence targets another MPN")
                if {pin.number for pin in evidence.pins} != actual_pins:
                    raise ValueError(
                        f"{part.reference}: datasheet pin coverage differs from footprint"
                    )
                inputs[str(source.resolve())] = evidence.source_sha256
                pin_status = "source_and_number_coverage_checked"
            geometry_status = "not_supplied"
            if part.reference in geometry:
                claim = geometry[part.reference]
                source = Path(claim.source_local_path)
                if not source.is_absolute():
                    source = project / source
                if not source.is_file() or _sha(source) != claim.source_sha256:
                    raise ValueError(
                        f"{part.reference}: missing or changed package geometry source"
                    )
                if claim.part_number != part.mpn:
                    raise ValueError(f"{part.reference}: package geometry targets another MPN")
                _check_package_geometry(footprint.spec, claim)
                inputs[str(source.resolve())] = claim.source_sha256
                geometry_status = (
                    "supplied_smd_geometry_matches_cad"
                    if isinstance(claim, SmdPackageGeometryEvidence)
                    else "supplied_tht_geometry_matches_cad"
                )
            kinds = {pad.kind for pad in footprint.spec.pads if pad.name}
            mounting = (
                "smd"
                if kinds and kinds <= {"smd"}
                else "tht"
                if kinds and kinds <= {"tht", "thru_hole"}
                else "either"
            )
            model_inventory.append(
                (part.reference, part.footprint, tuple(_children(footprint.tree, "model")))
            )
            models = []
            for model in _children(footprint.tree, "model"):
                raw = _atom(model[1])
                resolved, finding = _resolve_model_path(raw, board_dir=project, variables=variables)
                exists = resolved is not None and resolved.is_file()
                digest = _sha(resolved) if exists and resolved is not None else None
                if resolved is not None and digest is not None:
                    inputs[str(resolved)] = digest
                models.append(
                    {
                        "raw_path": raw,
                        "resolved_path": str(resolved) if resolved else None,
                        "sha256": digest,
                        "resolution": "resolved" if exists else "unresolved",
                        "finding": finding or (None if exists else "model file missing"),
                        "qualification": (
                            "unverified; footprint default, not final board model selection"
                        ),
                    }
                )
            components.append(
                {
                    "reference": part.reference,
                    "value": part.value,
                    "selected_part": part.mpn,
                    "footprint": part.footprint,
                    "footprint_source": str(footprint.source_file.resolve()),
                    "footprint_sha256": inputs[str(footprint.source_file.resolve())],
                    "mounting": mounting,
                    "cad_fab_bounds_mm": footprint.spec.fab_rect,
                    "cad_pads": [
                        {
                            "number": pad.name,
                            "x_mm": pad.x_mm,
                            "y_mm": pad.y_mm,
                            "kind": pad.kind,
                            "width_mm": pad.width_mm,
                            "height_mm": pad.height_mm,
                            "drill_mm": pad.drill_mm,
                            "hole": None if pad.hole is None else pad.hole.model_dump(mode="json"),
                        }
                        for pad in footprint.spec.pads
                    ],
                    "pin_evidence": pin_status,
                    "package_geometry": geometry_status,
                    "footprint_default_models": models,
                    "package_qualification": "unverified",
                    "remaining_obligations": [
                        "Review exact MPN or procurement envelope and manufacturer pin functions.",
                        "Verify purchased body/lead/pitch dimensions "
                        "and process-specific hole fit.",
                        "Declare exact/proxy model policy and verify "
                        "final board model hashes/transforms.",
                    ],
                }
            )
    selected_models: dict[str, Any] = {"status": "not_declared"}
    if selection is not None:
        assessment = preflight_model_inventory(
            tuple(model_inventory),
            project_dir=project,
            registry=selection.registry,
            requirements=selection.requirements,
            applicability=selection.applicability,
            applicability_rationale=selection.rationale,
        )
        if assessment.status not in {"passed", "not_applicable"} or (
            selection.applicability == "applicable"
            and any(
                item.status != "resolved" or item.transform_alignment != "passed"
                for item in assessment.models
            )
        ):
            raise ValueError(
                "Selected model preflight failed: "
                + "; ".join(
                    (
                        *assessment.findings,
                        *(finding for item in assessment.models for finding in item.findings),
                    )
                )
            )
        for item in assessment.models:
            if item.resolved_path is not None and item.sha256 is not None:
                inputs[item.resolved_path] = item.sha256
        selected_models = {
            "status": assessment.status,
            "policy": selection.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
        }
    if any(
        not Path(path).is_file() or _sha(Path(path)) != digest for path, digest in inputs.items()
    ):
        raise ValueError("Component evidence changed during pre-placement inspection")
    return {
        "schema_id": "pcbsmith-preplacement-component-readiness-v1",
        "status": "review_required",
        "production_accepted": False,
        "project_id": spec.project_id,
        "source_inputs": inputs,
        "components": components,
        "selected_models": selected_models,
        "limitations": "CAD geometry and source/pin-number equality do not qualify procurement, "
        "pin functions or physical fit. Model defaults do not establish final model acceptance.",
    }


def require_component_readiness_snapshot(
    root: Path,
    project: Path,
    expected_sha256: str,
    *,
    require_selected_models: bool = False,
) -> None:
    """Replay current inputs before sealing a prepared review; never import approval."""
    report = root / "component-readiness.json"
    if _sha(report) != expected_sha256:
        raise ValueError("Missing or stale component readiness report")
    spec = NativeProjectSpec.model_validate_json((project / "design-spec.json").read_bytes())
    current = inspect_component_readiness(spec, project)
    if json.loads(report.read_bytes()) != json.loads(json.dumps(current)):
        raise ValueError("Component readiness inputs changed since preparation")
    if require_selected_models and current["selected_models"]["status"] not in {
        "passed",
        "not_applicable",
    }:
        raise ValueError("Predesign approval requires an explicit selected model policy")
