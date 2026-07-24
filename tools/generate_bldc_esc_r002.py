"""Generate the BLDC ESC R002 thermal-mechanical placement review package."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from generate_bldc_esc_r001 import (
    KICAD,
    _drc_audit,
    _model_audit,
    _pin_net_audit,
    _run,
    _sha256,
)

from pcbsmith.generation.bldc_esc import compose_bldc_esc
from pcbsmith.generation.bldc_esc_engineering import (
    write_bldc_esc_engineering_evidence,
)
from pcbsmith.kicad.bldc_esc_models import generate_bldc_esc_r002_mechanical_models
from pcbsmith.kicad.bldc_esc_r002_board import generate_bldc_esc_r002_board
from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM, BoardLayout
from pcbsmith.kicad.export_bldc_esc import export_bldc_esc_to_kicad
from pcbsmith.kicad.glb_alignment import GlbBounds, read_component_model_bounds
from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    preflight_board_models,
)
from pcbsmith.review.visual_package import (
    DetailRegion,
    ReviewFeatures,
    generate_visual_review_package,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "bldc-esc-60a-r002"
PROJECT_NAME = "bldc-esc-60a-r002"

ALIGNMENT_REFERENCES = (
    "J1",
    "J2",
    "J3",
    "J4",
    "J5",
    "D1",
    "U2",
    "CB1",
    "CB2",
    "CB3",
    "CB4",
    "CB5",
    "CB6",
    "CB7",
    "CB8",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "Q5",
    "Q6",
    "RSH1",
    "RSH2",
    "RSH3",
    "HS1",
    "TIM1",
    "TIM2",
    "TIM3",
    "TIM4",
    "TIM5",
    "TIM6",
    "H5",
    "H6",
    "H7",
    "H8",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-renders", action="store_true")
    return parser.parse_args()


def _register_mechanical_library(output: Path) -> None:
    table = output / "fp-lib-table"
    payload = table.read_text(encoding="utf-8")
    entry = (
        '  (lib (name "PCBSmith_Mechanical")(type "KiCad")'
        '(uri "${KIPRJMOD}/PCBSmith_Mechanical.pretty")(options "")'
        '(descr "BLDC ESC R002 thermal-mechanical review envelopes"))\n'
    )
    if entry not in payload:
        payload = payload.rsplit(")", 1)[0] + entry + ")\n"
        table.write_text(payload, encoding="utf-8")


def _anchor_map(layout: BoardLayout) -> dict[str, tuple[float, float]]:
    y_by_ref = dict(layout.part_y_mm)
    return {
        component.reference: (
            x + BOARD_SHEET_ORIGIN_MM,
            y_by_ref.get(component.reference, layout.parts_row_y_mm) + BOARD_SHEET_ORIGIN_MM,
        )
        for component, x in layout.placements
    }


def _bounds_record(bounds: GlbBounds) -> dict[str, object]:
    return {
        "board_center_mm": [round(value, 6) for value in bounds.board_center_mm],
        "board_bounds_mm": {
            "x": [round(bounds.x_min_mm, 6), round(bounds.x_max_mm, 6)],
            "y": [round(bounds.z_min_mm, 6), round(bounds.z_max_mm, 6)],
        },
        "height_bounds_mm": [round(bounds.y_min_mm, 6), round(bounds.y_max_mm, 6)],
    }


def _alignment_audit(glb: Path, layout: BoardLayout) -> dict[str, object]:
    bounds = read_component_model_bounds(glb, ALIGNMENT_REFERENCES)
    anchors = _anchor_map(layout)
    records: list[dict[str, object]] = []
    failed: list[str] = []
    for reference in ALIGNMENT_REFERENCES:
        expected = anchors[reference]
        actual = bounds[reference].board_center_mm
        offset = (actual[0] - expected[0], actual[1] - expected[1])
        magnitude = (offset[0] ** 2 + offset[1] ** 2) ** 0.5
        if magnitude > 0.05:
            failed.append(reference)
        records.append(
            {
                "reference": reference,
                "expected_anchor_mm": [round(value, 6) for value in expected],
                "model_center_offset_mm": [round(value, 6) for value in offset],
                "offset_magnitude_mm": round(magnitude, 6),
                **_bounds_record(bounds[reference]),
            }
        )

    interfaces: list[dict[str, object]] = []
    interface_failed: list[str] = []
    heatsink_bottom = bounds["HS1"].y_min_mm
    for index in range(1, 7):
        mosfet = bounds[f"Q{index}"]
        tim = bounds[f"TIM{index}"]
        package_to_tim = tim.y_min_mm - mosfet.y_max_mm
        tim_to_heatsink = heatsink_bottom - tim.y_max_mm
        identity = f"Q{index}/TIM{index}/HS1"
        if abs(package_to_tim) > 0.05 or abs(tim_to_heatsink) > 0.05:
            interface_failed.append(identity)
        interfaces.append(
            {
                "identity": identity,
                "package_to_tim_gap_mm": round(package_to_tim, 6),
                "tim_to_heatsink_gap_mm": round(tim_to_heatsink, 6),
            }
        )
    for reference in ("H5", "H6", "H7", "H8"):
        gap = heatsink_bottom - bounds[reference].y_max_mm
        identity = f"{reference}/HS1"
        if abs(gap) > 0.05:
            interface_failed.append(identity)
        interfaces.append({"identity": identity, "support_to_heatsink_gap_mm": round(gap, 6)})

    return {
        "schema": "pcbsmith-bldc-r002-glb-alignment-v1",
        "status": "passed" if not failed and not interface_failed else "failed",
        "glb_file": str(glb),
        "glb_sha256": _sha256(glb),
        "center_tolerance_mm": 0.05,
        "failed_references": failed,
        "failed_interfaces": interface_failed,
        "components": records,
        "thermal_interfaces": interfaces,
    }


def _export_partial_step(board: Path, target: Path) -> dict[str, object]:
    result = subprocess.run(
        (str(KICAD), "pcb", "export", "step", "--force", "-o", str(target), str(board)),
        check=False,
        capture_output=True,
        text=True,
    )
    diagnostics = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    vrml_omissions = diagnostics.count("Cannot use VRML models")
    return {
        "schema": "pcbsmith-bldc-r002-step-export-v1",
        "status": "partial_proxy_models_omitted" if vrml_omissions else "complete",
        "step_file": str(target),
        "step_sha256": _sha256(target) if target.exists() else None,
        "return_code": result.returncode,
        "vrml_model_omissions": vrml_omissions,
        "diagnostics": diagnostics,
    }


def _render_reviews(board: Path, hidden_board: Path, output: Path) -> None:
    from PIL import Image

    from pcbsmith.review.visual_package import rasterize_svg_with_resvg

    review = output / "review-images"
    review.mkdir(parents=True, exist_ok=True)
    render_jobs = (
        (board, "top", "01-top-heatsink-installed-4k.png", ()),
        (hidden_board, "top", "02-top-heatsink-hidden-4k.png", ()),
        (
            board,
            "top",
            "03-top-heatsink-installed-oblique-4k.png",
            ("--perspective", "--rotate", "35,0,-25"),
        ),
        (board, "front", "04-front-heatsink-installed-4k.png", ()),
        (board, "bottom", "05-bottom-assembly-4k.png", ()),
    )
    for source, side, filename, extra in render_jobs:
        _run(
            "pcb",
            "render",
            "-w",
            "3840",
            "-h",
            "2160",
            "--side",
            side,
            "--quality",
            "high",
            "--background",
            "opaque",
            "--floor",
            *extra,
            "-o",
            str(review / filename),
            str(source),
        )
    svg_jobs = (
        ("06-front-placement", "F.Cu,F.SilkS,Edge.Cuts", False),
        ("07-back-placement", "B.Cu,B.SilkS,Edge.Cuts", True),
        ("08-front-courtyard", "F.CrtYd,F.Fab,Edge.Cuts", False),
        ("09-front-mechanical-fab", "F.Fab,Edge.Cuts", False),
        ("10-front-copper-only", "F.Cu,Edge.Cuts", False),
    )
    for name, layers, mirror in svg_jobs:
        svg = review / f"{name}.svg"
        _run(
            "pcb",
            "export",
            "svg",
            "--mode-single",
            "--page-size-mode",
            "2",
            "--exclude-drawing-sheet",
            *(("--mirror",) if mirror else ()),
            "-l",
            layers,
            "-o",
            str(svg),
            str(board),
        )
        rasterize_svg_with_resvg(svg, review / f"{name}-4k.png", 3840, 2160, None)

    crops = (
        (
            "01-top-heatsink-installed-4k.png",
            "11-heatsink-installed-detail.png",
            (1850, 0, 3320, 2160),
        ),
        (
            "02-top-heatsink-hidden-4k.png",
            "12-mosfet-tim-detail.png",
            (1850, 0, 3320, 2160),
        ),
    )
    for source_name, target_name, crop_box in crops:
        with Image.open(review / source_name) as source:
            source.crop(crop_box).save(review / target_name)


def _canonical_visual_review(board: Path, output: Path) -> dict[str, object]:
    """Generate the shared baseline while retaining custom views as supplements."""

    inventory = preflight_board_models(board)
    registry: dict[str, ModelRegistryEntry] = {}
    for item in inventory.models:
        if item.status != "resolved" or item.resolved_path is None:
            continue
        project_model = item.raw_path.startswith("${KIPRJMOD}")
        exact_manufacturer = "wurth-7461057-model" in item.raw_path
        registry[item.raw_path] = ModelRegistryEntry(
            raw_path=item.raw_path,
            local_path=item.resolved_path,
            expected_sha256=item.sha256,
            classification=("exact_package" if exact_manufacturer else "proxy")
            if project_model
            else "exact_package",
            license_status=(
                "manufacturer_model_retained_in_project"
                if exact_manufacturer
                else (
                    "project_generated_visual_or_mechanical_proxy"
                    if project_model
                    else "KiCad_official_library_local_install"
                )
            ),
            source_url=(
                "https://www.we-online.com/en/components/products/WP-BUTR"
                if exact_manufacturer
                else (
                    None if project_model else "https://gitlab.com/kicad/libraries/kicad-packages3D"
                )
            ),
            redistributable=not exact_manufacturer,
        )
    required = tuple(
        ModelRequirement(
            reference=reference,
            accepted_classifications=("exact_package", "complete_module", "proxy"),
        )
        for reference in ALIGNMENT_REFERENCES
    )
    preflight = preflight_board_models(
        board,
        registry=tuple(registry.values()),
        requirements=required,
    )
    evidence = output / "evidence"
    (evidence / "canonical-model-preflight.json").write_text(
        json.dumps(preflight.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    predecessor = (
        ROOT / "outputs" / "bldc-esc-60a-schematic-r001" / "bldc-esc-60a-r001-placement.kicad_pcb"
    )
    visual = generate_visual_review_package(
        board_file=board,
        output_dir=output,
        stage="placement",
        features=ReviewFeatures(
            has_bottom_components=True,
            has_holes=True,
            has_zones=False,
            has_keepouts=False,
            has_cutouts=False,
            has_vias=False,
            declared_classes=(),
            detail_regions=(
                DetailRegion(
                    region_id="power-entry-and-dc-link",
                    bounds_mm=(0.0, 0.0, 58.0, 42.0),
                    reason="Battery terminals, protection, and bulk DC-link placement.",
                ),
                DetailRegion(
                    region_id="driver-and-control",
                    bounds_mm=(36.0, 20.0, 58.0, 50.0),
                    reason="Gate-driver, control, sensing, and connector placement separation.",
                ),
                DetailRegion(
                    region_id="phase-bank-and-clamps",
                    bounds_mm=(69.0, 0.0, 71.0, 90.0),
                    reason="Three-phase symmetry, MOSFET/TIM stack, clamps, and heatsink envelope.",
                ),
                DetailRegion(
                    region_id="mosfet-tim-interface",
                    bounds_mm=(75.0, 0.0, 55.0, 63.0),
                    reason="MOSFET package, isolating TIM, and shared-spreader interface detail.",
                ),
            ),
            predecessor_board=str(predecessor),
        ),
        model_preflight=preflight,
        source_revision="bldc-esc-60a-r002",
        progress=lambda message: print(f"[canonical-review] {message}", flush=True),
    )
    return {
        "authoritative_status_source": str(output / "review" / "manifest.json"),
        "generation_time_status": visual.package_status,
        "generation_time_workflow_conformance": visual.workflow_conformance_status,
        "manifest": str(output / "review" / "manifest.json"),
        "conformance_report": str(output / "review" / "conformance.json"),
        "generation_time_artifact_count": len(visual.artifacts),
        "generation_time_required_artifact_count": sum(
            artifact.required for artifact in visual.artifacts
        ),
    }


def main() -> int:
    args = _args()
    output = args.output.resolve()
    evidence = output / "evidence"
    output.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    circuit = compose_bldc_esc()
    (output / "circuit-authority.json").write_text(
        circuit.model_dump_json(indent=2), encoding="utf-8"
    )
    artifacts = export_bldc_esc_to_kicad(circuit, output, project_name=PROJECT_NAME)
    generate_bldc_esc_r002_mechanical_models(output)
    _register_mechanical_library(output)

    schematic = Path(artifacts["schematic_file"])
    project = output / f"{PROJECT_NAME}.kicad_pro"
    netlist = output / "netlist.xml"
    schematic_pdf = output / f"{PROJECT_NAME}-schematic.pdf"
    erc_report = output / "erc.rpt"
    board = output / f"{PROJECT_NAME}-thermal-placement.kicad_pcb"
    hidden_board = output / f"{PROJECT_NAME}-heatsink-hidden.kicad_pcb"
    drc_report = output / "placement-drc.rpt"
    glb = output / f"{PROJECT_NAME}-assembly.glb"
    step = output / f"{PROJECT_NAME}-mcad-partial.step"

    _run("sch", "erc", "--exit-code-violations", "-o", str(erc_report), str(schematic))
    _run(
        "sch",
        "export",
        "netlist",
        "--format",
        "kicadxml",
        "-o",
        str(netlist),
        str(schematic),
    )
    _run("sch", "export", "pdf", "-o", str(schematic_pdf), str(schematic))
    _netlist, layout = generate_bldc_esc_r002_board(
        netlist_file=netlist,
        board_file=board,
        include_heatsink=True,
    )
    generate_bldc_esc_r002_board(
        netlist_file=netlist,
        board_file=hidden_board,
        include_heatsink=False,
    )
    _run("pcb", "drc", "-o", str(drc_report), str(board))
    _run("pcb", "export", "glb", "--force", "-o", str(glb), str(board))

    pin_audit = _pin_net_audit(netlist)
    drc_audit = _drc_audit(drc_report)
    model_audit = _model_audit(board)
    alignment_audit = _alignment_audit(glb, layout)
    step_audit = _export_partial_step(board, step)
    for name, data in (
        ("pin-net-audit.json", pin_audit),
        ("placement-drc-audit.json", drc_audit),
        ("model-audit.json", model_audit),
        ("glb-alignment-audit.json", alignment_audit),
        ("step-export-audit.json", step_audit),
    ):
        (evidence / name).write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if (
        pin_audit["status"] != "passed"
        or drc_audit["blocking_categories"]
        or alignment_audit["status"] != "passed"
    ):
        raise RuntimeError("BLDC ESC R002 placement evidence gate failed")
    engineering_analysis = write_bldc_esc_engineering_evidence(evidence)
    if not args.skip_renders:
        _render_reviews(board, hidden_board, output)
        canonical_visual_review = _canonical_visual_review(board, output)
    else:
        canonical_visual_review = {
            "authoritative_status_source": str(output / "review" / "manifest.json"),
            "generation_time_status": "not_generated_skip_renders",
            "generation_time_workflow_conformance": "not_evaluated",
        }

    summary = {
        "schema": "pcbsmith-bldc-esc-r002-placement-summary-v2",
        "status": "placement_candidate_engineering_incomplete",
        "project_file": str(project),
        "schematic_file": str(schematic),
        "board_file": str(board),
        "heatsink_hidden_board_file": str(hidden_board),
        "board_sha256": _sha256(board),
        "component_count": len(circuit.components),
        "board_footprint_count": len(layout.placements),
        "board_size_mm": [layout.width_mm, layout.height_mm],
        "copper_layers": 4,
        "routing_segments": len(layout.segments),
        "routing_vias": len(layout.vias),
        "pin_net_audit": pin_audit["status"],
        "placement_drc": drc_audit["status"],
        "model_audit": model_audit["status"],
        "glb_alignment_audit": alignment_audit["status"],
        "step_export": step_audit["status"],
        "engineering_analysis": engineering_analysis,
        "canonical_visual_review": canonical_visual_review,
    }
    (evidence / "placement-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
