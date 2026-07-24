"""Regenerate the BLDC ESC R001 schematic and unrouted placement package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from pcbsmith.generation.bldc_esc import compose_bldc_esc
from pcbsmith.kicad.bldc_esc_board import generate_bldc_esc_placement_board
from pcbsmith.kicad.export_bldc_esc import INSTANCES, export_bldc_esc_to_kicad
from pcbsmith.kicad.model_preflight import preflight_board_models

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "bldc-esc-60a-schematic-r001"
PROJECT_NAME = "bldc-esc-60a-r001"
KICAD = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")

EXPECTED_PLACEMENT_DRC = frozenset(
    {"unconnected_items", "silk_over_copper", "silk_overlap", "lib_footprint_mismatch"}
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-renders", action="store_true")
    return parser.parse_args()


def _run(*args: str) -> None:
    subprocess.run((str(KICAD), *args), check=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pin_net_audit(netlist_file: Path) -> dict[str, object]:
    expected = {
        (reference, pin): net
        for reference, _library, _x, _y, pin_nets in INSTANCES
        for pin, net in pin_nets.items()
    }
    root = ET.fromstring(netlist_file.read_text(encoding="utf-8"))
    actual: dict[tuple[str, str], str] = {}
    for net in root.findall("./nets/net"):
        name = (net.get("name") or "").lstrip("/")
        for node in net.findall("node"):
            actual[(node.get("ref") or "", node.get("pin") or "")] = name
    missing = sorted(f"{ref}.{pin}" for ref, pin in expected.keys() - actual.keys())
    extra = sorted(f"{ref}.{pin}" for ref, pin in actual.keys() - expected.keys())
    wrong = {
        f"{ref}.{pin}": {"expected": expected[(ref, pin)], "actual": actual[(ref, pin)]}
        for ref, pin in expected.keys() & actual.keys()
        if expected[(ref, pin)] != actual[(ref, pin)]
    }
    return {
        "schema": "pcbsmith-bldc-pin-net-audit-v1",
        "status": "passed" if not (missing or extra or wrong) else "failed",
        "expected_pin_count": len(expected),
        "actual_pin_count": len(actual),
        "missing": missing,
        "extra": extra,
        "wrong": wrong,
    }


def _drc_audit(report: Path) -> dict[str, object]:
    counts = Counter(
        re.match(r"^\[([^]]+)]", line).group(1)
        for line in report.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\[([^]]+)]", line)
    )
    blockers = {name: count for name, count in counts.items() if name not in EXPECTED_PLACEMENT_DRC}
    return {
        "schema": "pcbsmith-bldc-placement-drc-audit-v1",
        "status": "placement_passed_routing_prohibited" if not blockers else "failed",
        "counts": dict(sorted(counts.items())),
        "expected_unrouted_categories": sorted(EXPECTED_PLACEMENT_DRC),
        "blocking_categories": blockers,
    }


def _model_audit(board_file: Path) -> dict[str, object]:
    preflight = preflight_board_models(board_file)
    records = []
    for model in preflight.models:
        if "-envelope.wrl" in model.raw_path:
            classification = "datasheet_envelope_proxy"
        elif "wurth-7461057-model" in model.raw_path:
            classification = "exact_manufacturer_model"
        else:
            classification = "installed_library_model"
        records.append(
            {
                "reference": model.reference,
                "path": model.raw_path,
                "resolution_status": model.status,
                "classification": classification,
                "sha256": model.sha256,
            }
        )
    unresolved = [
        record["reference"] for record in records if record["resolution_status"] != "resolved"
    ]
    return {
        "schema": "pcbsmith-bldc-model-audit-v1",
        "status": "passed_for_placement_review" if not unresolved else "failed",
        "unresolved_references": unresolved,
        "models": records,
    }


def _render_reviews(board: Path, output: Path) -> None:
    from PIL import Image

    from pcbsmith.review.visual_package import rasterize_svg_with_resvg

    review = output / "review-images"
    review.mkdir(parents=True, exist_ok=True)
    render_jobs = (
        ("top", "01-top-3d-4k.png", ()),
        ("bottom", "02-bottom-3d-4k.png", ()),
        ("top", "03-top-oblique-3d-4k.png", ("--perspective", "--rotate", "35,0,-25")),
        (
            "bottom",
            "04-bottom-oblique-3d-4k.png",
            ("--perspective", "--rotate", "-35,0,25"),
        ),
    )
    for side, filename, extra in render_jobs:
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
            str(board),
        )
    svg_jobs = (
        ("05-front-placement", "F.Cu,F.SilkS,Edge.Cuts", False),
        ("06-back-placement", "B.Cu,B.SilkS,Edge.Cuts", True),
        ("07-front-copper-only", "F.Cu,Edge.Cuts", False),
        ("08-back-copper-only", "B.Cu,Edge.Cuts", True),
        ("09-front-courtyard", "F.CrtYd,F.Fab,Edge.Cuts", False),
        ("10-back-courtyard", "B.CrtYd,B.Fab,Edge.Cuts", True),
    )
    for name, layers, mirror in svg_jobs:
        svg = review / f"{name}.svg"
        mirror_args = ("--mirror",) if mirror else ()
        _run(
            "pcb",
            "export",
            "svg",
            "--mode-single",
            "--page-size-mode",
            "2",
            "--exclude-drawing-sheet",
            *mirror_args,
            "-l",
            layers,
            "-o",
            str(svg),
            str(board),
        )
        rasterize_svg_with_resvg(svg, review / f"{name}-4k.png", 3840, 2160, None)

    # Native-resolution crops make dense regions reviewable without relying
    # on UI zoom.  Pixel boxes are tied to the fixed 3840x2160 orthographic
    # render contract above and intentionally retain surrounding context.
    crop_jobs = (
        ("01-top-3d-4k.png", "11-power-entry-detail.png", (850, 0, 2200, 2160)),
        ("01-top-3d-4k.png", "12-phase-cells-detail.png", (2000, 0, 3250, 2160)),
        ("01-top-3d-4k.png", "13-gate-driver-detail.png", (1700, 230, 2800, 1930)),
        ("02-bottom-3d-4k.png", "14-control-power-detail.png", (900, 0, 3060, 2160)),
    )
    for source_name, target_name, crop_box in crop_jobs:
        with Image.open(review / source_name) as source:
            source.crop(crop_box).save(review / target_name)


def main() -> int:
    args = _args()
    output = args.output.resolve()
    evidence = output / "evidence"
    output.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    if not KICAD.exists():
        raise FileNotFoundError(f"KiCad 10 CLI was not found at {KICAD}")

    circuit = compose_bldc_esc()
    (output / "circuit-authority.json").write_text(
        circuit.model_dump_json(indent=2), encoding="utf-8"
    )
    artifacts = export_bldc_esc_to_kicad(circuit, output, project_name=PROJECT_NAME)
    schematic = Path(artifacts["schematic_file"])
    project = output / f"{PROJECT_NAME}.kicad_pro"
    netlist = output / "netlist.xml"
    schematic_pdf = output / f"{PROJECT_NAME}-schematic.pdf"
    erc_report = output / "erc.rpt"
    board = output / f"{PROJECT_NAME}-placement.kicad_pcb"
    drc_report = output / "placement-drc.rpt"

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
    _netlist, layout = generate_bldc_esc_placement_board(netlist_file=netlist, board_file=board)
    _run("pcb", "drc", "-o", str(drc_report), str(board))

    pin_audit = _pin_net_audit(netlist)
    drc_audit = _drc_audit(drc_report)
    model_audit = _model_audit(board)
    for name, data in (
        ("pin-net-audit.json", pin_audit),
        ("placement-drc-audit.json", drc_audit),
        ("model-audit.json", model_audit),
    ):
        (evidence / name).write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if pin_audit["status"] != "passed" or drc_audit["blocking_categories"]:
        raise RuntimeError("BLDC ESC placement evidence gate failed")
    if not args.skip_renders:
        _render_reviews(board, output)

    summary = {
        "schema": "pcbsmith-bldc-esc-r001-placement-summary-v1",
        "status": "unrouted_placement_candidate_pending_user_review",
        "project_file": str(project),
        "schematic_file": str(schematic),
        "board_file": str(board),
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
    }
    (evidence / "placement-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
