"""Synthetic adapter inputs; these are never retained native or approval evidence."""

import json
from pathlib import Path

from pcbsmith.kicad.final_fill_adapter import parse_kicad_final_fill_snapshot
from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFilledRegionContactObservation,
    KiCadFinalFillConnectivityObservation,
    classify_final_fill_reachability,
)
from pcbsmith.kicad.final_fill_thermal import audit_kicad_thermal_spokes


def write_marking_example(root: Path) -> tuple[Path, Path]:
    board = root / "synthetic-markings.kicad_pcb"
    footprints = []
    violations = []
    for index in range(11):
        ref = f"R{index + 1}"
        footprints.append(
            f'(footprint "Test:R" (layer "F.Cu") '
            f'(property "Reference" "{ref}" (at {index} 0) (layer "F.SilkS")))'
        )
        violations.append({
            "type": "silk_over_copper" if index < 8 else "silk_overlap",
            "items": [
                {"uuid": f"ref-{index}", "description": f"Reference field of {ref}",
                 "pos": {"x": index, "y": 0.0}},
                {"uuid": f"other-{index}",
                 "description": f"Pad 1 of {ref}" if index < 8 else "Silkscreen text",
                 "pos": {"x": index + 0.5, "y": 0.5}},
            ],
        })
    board.write_text('(kicad_pcb (version 20241229) ' + ''.join(footprints) + ')',
                     encoding="utf-8")
    report = root / "synthetic-markings-drc.json"
    report.write_text(json.dumps({"violations": violations}), encoding="utf-8")
    return board, report


def write_empty_drc(root: Path) -> Path:
    report = root / "synthetic-drc.json"
    report.write_text(json.dumps({
        "violations": [], "unconnected_items": [], "schematic_parity": [],
    }), encoding="utf-8")
    return report


def filled_region_example(root: Path):
    source = root / "synthetic-source.kicad_pcb"
    filled = root / "synthetic-filled.kicad_pcb"
    zone = '''(zone (net 1) (net_name "GND") (layer "B.Cu") (uuid "zone-1")
      (connect_pads yes (clearance 0.2)) (min_thickness 0.2)
      (fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))
      (polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10))))'''
    source.write_text(f"(kicad_pcb (version 20241229) {zone})", encoding="utf-8")
    filled.write_text(
        f'''(kicad_pcb (version 20241229) {zone[:-1]}
        (filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10)))))''',
        encoding="utf-8",
    )
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="synthetic-unit-test", refilled_by_kicad=True,
    )
    region = snapshot.regions[0]
    observation = KiCadFinalFillConnectivityObservation(
        board_file=str(filled), board_sha256=snapshot.filled_board_sha256,
        kicad_version="synthetic-unit-test",
        island_authority="ZONE.IsIsland(layer, filled_outline_index)",
        records=(KiCadFilledRegionContactObservation(
            region_id=region.region_id, zone_id=region.zone_id, zone_index=0,
            region_index=region.region_index, net_name=region.net_name, layer=region.layer,
            is_island=False, direct_contact_ids=("pad:J1.1",),
            connected_pad_ids=("J1.1",), reachable_pad_ids=("J1.1",),
            pad_mapping_exact=True, pad_mapping_scope="integer_effective_shape_contact_graph",
        ),),
        qualification_boundary="Synthetic adapter test; no native tool was executed.",
    )
    classified = classify_final_fill_reachability(
        snapshot, observation, declared_source_pad_ids=("J1.1",),
    )
    thermal = audit_kicad_thermal_spokes(
        observation, write_empty_drc(root),
        drc_report_board_sha256=snapshot.filled_board_sha256,
    )
    return classified, observation, thermal
