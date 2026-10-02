"""Export BenchLeaf draft handover files; never authorizes manufacture."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import subprocess
from pathlib import Path

from benchleaf_r001 import PARTS, PROJECT

from pcbsmith.kicad.board import export_kicad_netlist_xml
from pcbsmith.manufacturing_lineage import saved_assembly_rows
from pcbsmith.production_generators import generate_nonmutating_kicad_drc

ROOT = Path(__file__).resolve().parents[2] / "outputs" / PROJECT
CLI = Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")


def run(command, logs):
    result = subprocess.run([str(p) for p in command], capture_output=True, text=True, check=False)
    logs.append(
        dict(
            command=[str(p) for p in command],
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)


def verify_bottom_copper(root):
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union

    native = root / "checks/native-readback-final.json"
    record = json.loads(native.read_text(encoding="utf-8"))
    board = root / "design" / (PROJECT + ".kicad_pcb")
    digest = hashlib.sha256(board.read_bytes()).hexdigest()
    assert record["board_sha256"] == digest, "Native snapshot targets another board"
    snapshot = record["snapshot"]
    assert snapshot["copper_layers"] == 2 and snapshot["zone_count"] == 0
    assert all(t["layer"] == "B.Cu" for t in snapshot["tracks"])
    holes = unary_union(
        [Point(h["x"], h["y"]).buffer(h["diameter"] / 2, quad_segs=64) for h in snapshot["holes"]]
    )
    all_pads = [p for f in snapshot["footprints"] for p in f["pads"] if p["net"]]
    nets = sorted({t["net"] for t in snapshot["tracks"]})
    assert set(nets) == {p["net"] for p in all_pads}
    findings = []
    for net in nets:
        pads = [p for p in all_pads if p["net"] == net]
        assert all(p["bottom_copper"] for p in pads)
        parts = [
            Point(p["x"], p["y"]).buffer(min(p["width"], p["height"]) / 2, quad_segs=64)
            for p in pads
        ]
        tracks = [t for t in snapshot["tracks"] if t["net"] == net]
        parts.extend(
            LineString([t["start"], t["end"]]).buffer(t["width"] / 2, quad_segs=64) for t in tracks
        )
        conductor = unary_union(parts).difference(holes)
        assert conductor.geom_type == "Polygon", (net, conductor.geom_type)
        findings.append(
            dict(
                net=net,
                pads=len(pads),
                connected_components=1,
                routed_length_mm=round(sum(math.dist(t["start"], t["end"]) for t in tracks), 3),
            )
        )
    result = dict(
        status="passed",
        board_sha256=digest,
        native_snapshot_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
        method="Inscribed pad discs and B.Cu tracks, with drill voids subtracted",
        nets=findings,
        input_cap_positive_trace_mm=8.552,
        output_cap_positive_trace_mm=7.5,
        limitation="Geometric connectivity only; no physical/electrical qualification",
    )
    (root / "checks/bottom-only-connectivity-final.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main(root=ROOT):
    verify_bottom_copper(root)
    board = root / "design" / (PROJECT + ".kicad_pcb")
    digest = hashlib.sha256(board.read_bytes()).hexdigest()
    (root / "assembly").mkdir(parents=True, exist_ok=True)
    draft = root / "fabrication-draft"
    draft.mkdir(exist_ok=False)
    schematic_dir = root / "schematic"
    schematic_dir.mkdir(exist_ok=False)
    logs = []
    try:
        run(
            [
                CLI,
                "pcb",
                "export",
                "gerbers",
                "--output",
                draft / "gerbers",
                "--layers",
                "F.Cu,B.Cu,F.SilkS,Edge.Cuts",
                board,
            ],
            logs,
        )
        run(
            [
                CLI,
                "pcb",
                "export",
                "drill",
                "--output",
                draft / "drill",
                "--format",
                "excellon",
                "--excellon-units",
                "mm",
                "--generate-map",
                "--map-format",
                "svg",
                "--generate-report",
                "--report-path",
                draft / "drill-report.txt",
                board,
            ],
            logs,
        )
        run(
            [
                CLI,
                "pcb",
                "export",
                "pos",
                "--output",
                root / "assembly/positions.csv",
                "--format",
                "csv",
                "--units",
                "mm",
                board,
            ],
            logs,
        )
        for name, layers, mirror in [
            ("bottom-copper-top-coordinates", "B.Cu,Edge.Cuts", False),
            ("bottom-copper-underside-view", "B.Cu,Edge.Cuts", True),
            ("assembly-top", "F.SilkS,F.Fab,Edge.Cuts", False),
        ]:
            command = [
                CLI,
                "pcb",
                "export",
                "svg",
                "--mode-single",
                "--page-size-mode",
                "2",
                "--exclude-drawing-sheet",
                "--output",
                draft / (name + ".svg"),
                "--layers",
                layers,
            ]
            if mirror:
                command.append("--mirror")
            run([*command, board], logs)
        run(
            [
                CLI,
                "sch",
                "export",
                "svg",
                "--output",
                schematic_dir,
                board.with_suffix(".kicad_sch"),
            ],
            logs,
        )
        export_kicad_netlist_xml(board.with_suffix(".kicad_sch"))
        generate_nonmutating_kicad_drc(board, root / "checks/drc-final.json")
        assembly = saved_assembly_rows(board)
        populated = {r.reference: r for r in assembly if r.in_bom}
        expected = {r for r, p in PARTS.items() if p.get("populated", True)}
        assert set(populated) == expected
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerow(
            ["Reference", "Quantity", "Value", "MPN or procurement specification", "Footprint"]
        )
        for reference in sorted(populated):
            r = populated[reference]
            writer.writerow(
                [reference, 1, r.value, PARTS[reference]["mpn"], PARTS[reference]["footprint"]]
            )
        (root / "assembly/bom.csv").write_bytes(text.getvalue().encode("utf-8"))
        assert hashlib.sha256(board.read_bytes()).hexdigest() == digest
    finally:
        (root / "checks/export-processes.json").write_text(
            json.dumps(logs, indent=2), encoding="utf-8"
        )
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for directory in (draft, root / "assembly", schematic_dir)
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    (root / "checks/draft-export-manifest.json").write_text(
        json.dumps(
            dict(
                status="draft-not-released",
                board_sha256=digest,
                files=files,
                limitations=[
                    "No fabrication process qualification",
                    "No bench measurements",
                    "No production routed-release receipt",
                    "No purchasing or fabrication order",
                ],
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Draft exports retained:", len(files), "files; populated BOM:", len(populated))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    main(parser.parse_args().root.resolve())
