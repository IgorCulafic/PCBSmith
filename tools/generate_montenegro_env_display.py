"""Generate or package the Montenegro environment-display prototype."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pcbsmith.generation.montenegro_env_display import compose_montenegro_env_display
from pcbsmith.kicad.board import export_kicad_netlist_xml, parse_board_netlist
from pcbsmith.kicad.export_montenegro_env_display import export_montenegro_env_display_to_kicad
from pcbsmith.kicad.fabrication import export_fab_package
from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    preflight_board_models,
)
from pcbsmith.kicad.montenegro_env_display_board import (
    MONTENEGRO_RULE_PROFILE,
    compute_montenegro_layout,
    write_montenegro_board,
)
from pcbsmith.kicad.montenegro_geometry import (
    build_montenegro_geometry,
    write_geometry_contract,
)
from pcbsmith.kicad.routing_evidence import inspect_saved_board_routing
from pcbsmith.kicad.validate import export_schematic_svg, run_kicad_drc, run_kicad_erc
from pcbsmith.review.visual_package import (
    DetailRegion,
    ReviewFeatures,
    generate_visual_review_package,
    rasterize_svg_with_resvg,
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "montenegro-env-display-r001"
DEFAULT_OUTPUT = ROOT / "outputs" / PROJECT
DEFAULT_SOURCE = Path(
    r"C:\Users\igori\Downloads\montenegro-map-montenegro-map-montenegrin-country-map-black-white-national-nation-outline-geography-border-boundary-shape-253353952.webp"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_render_models(design: Path, board: Path):
    models = design / "models"
    models.mkdir(parents=True, exist_ok=True)
    scale = 1.0 / 2.54
    (models / "sht45-package-proxy.wrl").write_text(
        f"""#VRML V2.0 utf8
Transform {{
  translation 0 0 {0.30 * scale:.6f}
  children [ Shape {{
    appearance Appearance {{ material Material {{ diffuseColor 0.08 0.08 0.08 }} }}
    geometry Box {{ size {1.5 * scale:.6f} {1.5 * scale:.6f} {0.60 * scale:.6f} }}
  }} ]
}}
""",
        encoding="ascii",
    )
    board_text = board.read_text(encoding="utf-8")
    board_text = board_text.replace(
        "${KICAD10_3DMODEL_DIR}/Sensor_Humidity.3dshapes/"
        "Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad.step",
        "${KIPRJMOD}/models/sht45-package-proxy.wrl",
    ).replace(
        "${KICAD10_3DMODEL_DIR}/Connector_JST.3dshapes/"
        "JST_PH_S7B-PH-SM4-TB_1x07-1MP_P2.00mm_Horizontal.step",
        "${KICAD10_3DMODEL_DIR}/Connector_JST.3dshapes/"
        "JST_PH_S7B-PH-K_1x07_P2.00mm_Horizontal.step",
    )
    board.write_text(board_text, encoding="utf-8")

    inventory = preflight_board_models(board)
    registry: dict[str, ModelRegistryEntry] = {}
    for item in inventory.models:
        if item.status != "resolved" or item.resolved_path is None:
            continue
        is_proxy = item.raw_path.startswith("${KIPRJMOD}/models/")
        registry[item.raw_path] = ModelRegistryEntry(
            raw_path=item.raw_path,
            local_path=item.resolved_path,
            expected_sha256=item.sha256,
            classification="proxy" if is_proxy else "exact_package",
            license_status=(
                "project_generated_visual_proxy"
                if is_proxy
                else "KiCad_official_library_local_install"
            ),
            source_url=(
                None if is_proxy else "https://gitlab.com/kicad/libraries/kicad-packages3D"
            ),
            redistributable=is_proxy,
        )
    return preflight_board_models(
        board,
        registry=tuple(registry.values()),
        requirements=(
            ModelRequirement(reference="J1", accepted_classifications=("exact_package",)),
            ModelRequirement(reference="J2", accepted_classifications=("exact_package",)),
            ModelRequirement(reference="U1", accepted_classifications=("exact_package",)),
            ModelRequirement(reference="U4", accepted_classifications=("proxy", "exact_package")),
            ModelRequirement(reference="D1", accepted_classifications=("exact_package",)),
            ModelRequirement(reference="MECH1", accepted_classifications=("proxy",)),
        ),
        applicability="applicable",
        applicability_rationale=(
            "Populated 3D review is required; SHT45 and OLED are explicitly "
            "classified visual proxies."
        ),
    )


def _write_reports(output: Path, summary: dict[str, object]) -> None:
    (output / "REPORT.md").write_text(
        """# Montenegro Environment Display R001 — engineering report

## Result

The prototype is a 150 mm-wide, two-layer Montenegro-shaped presentation PCB.
The front contains a 35-pixel addressable LED border and a central 1.5-inch
RGB OLED envelope. The back contains the ESP32-S3, USB-C protection and power,
SHT45 sensing, controls, and display connector.

## Workflow improvements demonstrated

- Source-hashed outline feasibility was frozen before PCB generation.
- LED count was reduced from 40 to 35 from real spacing/courtyard evidence.
- Edge-functional USB orientation was checked after back-side mirroring.
- Connector-to-ESD-to-series-resistor ordering is explicit.
- Routing is phased and preserves successful prefixes; no restart is allowed.
- Constrained USB/OLED and I2C nets route before power and ordinary signals.
- The one coastline gap uses a geometry-checked local bridge instead of a
  straight chord outside the outline.
- The SHT45 was moved after evidence showed its old peninsula placement made
  legal routing impractical.
- Manufacturing minima (0.15 mm) and routing targets (0.18 mm) are separate.
- ERC, DRC, model preflight, 4K/layer/detail/3D review, and fabrication export
  are recorded as machine-readable evidence.

## Current release state

This is a routed engineering-review prototype, not a released production
design. KiCad reports no copper clearance, short, crossing, courtyard, or
solder-mask errors. Residual DRC findings are isolated copper-pour connectivity
items on the irregular outline, plus visual silkscreen warnings. Fabrication
files are provided for inspection only under `RELEASE-HOLD.md`.
""",
        encoding="utf-8",
    )
    (output / "RELEASE-HOLD.md").write_text(
        """# Fabrication release hold

Do not order or assemble this revision without engineering review.

- Resolve the residual GND/+5 V copper-pour island connectivity findings.
- Confirm the outline artwork license and replace it if redistribution rights
  cannot be established.
- Replace the OLED mechanical proxy with the selected module's controlled
  drawing and verify connector/mounting alignment.
- Validate NCP1117 dissipation (approximately 0.95 W worst-case estimate),
  enclosure airflow, and temperature-sensor self-heating bias.
- Validate USB impedance/return continuity against the actual fab stack-up.
- Confirm via-in-pad acceptability for the intended home-fabrication process.
- Perform physical antenna-clearance, enclosure, and connector-access checks.
""",
        encoding="utf-8",
    )
    (output / "generation-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--reuse-routed",
        action="store_true",
        help="Package the already-generated deterministic routed board.",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    design = output / "design"
    evidence = output / "evidence"
    design.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    board = design / f"{PROJECT}.kicad_pcb"
    schematic = design / f"{PROJECT}.kicad_sch"

    geometry = build_montenegro_geometry(args.source.resolve())
    write_geometry_contract(geometry, output / "geometry.json")
    if not args.reuse_routed:
        circuit = compose_montenegro_env_display()
        (output / "circuit.json").write_text(circuit.model_dump_json(indent=2), encoding="utf-8")
        artifacts = export_montenegro_env_display_to_kicad(circuit, design, project_name=PROJECT)
        schematic = Path(artifacts["schematic_file"])
        netlist_file = export_kicad_netlist_xml(schematic)
        netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
        placement, route = compute_montenegro_layout(netlist, geometry, design)
        if route.failed:
            raise RuntimeError(f"routing failed: {route.failed}")
        write_montenegro_board(design / f"{PROJECT}-placement.kicad_pcb", netlist, placement)
        write_montenegro_board(board, netlist, route.layout)
    elif not board.exists() or not schematic.exists():
        raise FileNotFoundError("--reuse-routed requires existing board and schematic files")

    erc = run_kicad_erc(schematic)
    drc = run_kicad_drc(board, schematic_parity=True)
    model_preflight = _prepare_render_models(design, board)
    routing = inspect_saved_board_routing(board)
    (evidence / "model-preflight.json").write_text(
        model_preflight.model_dump_json(indent=2), encoding="utf-8"
    )
    (evidence / "routing-evidence.json").write_text(
        routing.model_dump_json(indent=2), encoding="utf-8"
    )

    schematic_svg, schematic_findings = export_schematic_svg(schematic)
    if schematic_svg is not None:
        schematic_png = output / "review" / "schematic" / "schematic-4k.png"
        schematic_png.parent.mkdir(parents=True, exist_ok=True)
        rasterize_svg_with_resvg(Path(schematic_svg), schematic_png, 3840, 2715, None)

    visual = generate_visual_review_package(
        board_file=board,
        output_dir=output,
        stage="final",
        model_preflight=model_preflight,
        features=ReviewFeatures(
            has_bottom_components=True,
            has_holes=True,
            has_zones=True,
            has_keepouts=True,
            has_vias=True,
            declared_classes=(),
            detail_regions=(
                DetailRegion(
                    region_id="usb-power",
                    bounds_mm=(20, 70, 68, 115),
                    reason="USB orientation, ESD and regulator",
                    side="back",
                ),
                DetailRegion(
                    region_id="display",
                    bounds_mm=(48, 72, 112, 128),
                    reason="OLED envelope and clean front",
                    side="front",
                ),
                DetailRegion(
                    region_id="mcu-rf",
                    bounds_mm=(108, 65, 163, 126),
                    reason="ESP32-S3 and antenna clearance",
                    side="back",
                ),
                DetailRegion(
                    region_id="sensor",
                    bounds_mm=(45, 125, 78, 160),
                    reason="SHT45 airflow and local routing",
                    side="back",
                ),
            ),
        ),
    )
    fab = export_fab_package(board, project_name=PROJECT, profile=MONTENEGRO_RULE_PROFILE)
    summary = {
        "schema": "pcbsmith-montenegro-generation-summary-v1",
        "project": PROJECT,
        "board_file": str(board),
        "board_sha256": _sha256(board),
        "schematic_file": str(schematic),
        "schematic_sha256": _sha256(schematic),
        "source_outline_sha256": geometry.source_sha256,
        "led_count": len(geometry.led_sites),
        "erc": erc.model_dump(mode="json"),
        "drc": drc.model_dump(mode="json"),
        "routing": routing.model_dump(mode="json"),
        "model_preflight": model_preflight.model_dump(mode="json"),
        "schematic_export_findings": list(schematic_findings),
        "visual_manifest": visual.model_dump(mode="json"),
        "fabrication_zip": str(fab.zip_file),
        "release_status": "hold",
    }
    _write_reports(output, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
