from __future__ import annotations

from pathlib import Path

import pytest

from pcbsmith.kicad.final_fill_adapter import FillReachability, parse_kicad_final_fill_snapshot
from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFinalFillConnectivityObservation,
    classify_final_fill_reachability,
)


def _boards(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.kicad_pcb"
    filled = tmp_path / "filled.kicad_pcb"
    zone = """(zone (net 1) (net_name "GND") (layer "B.Cu") (uuid "zone-1")
      (hatch edge 0.5) (connect_pads yes (clearance 0.2)) (min_thickness 0.2)
      (fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))
      (polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10))))"""
    source.write_text(f"(kicad_pcb (version 20241229) {zone})", encoding="utf-8")
    filled.write_text(
        f"""(kicad_pcb (version 20241229) {zone[:-1]}
        (filled_polygon (layer "B.Cu") (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10)))))""",
        encoding="utf-8",
    )
    return source, filled


def _observation(snapshot, **changes: object) -> KiCadFinalFillConnectivityObservation:
    region = snapshot.regions[0]
    record: dict[str, object] = {
        "region_id": region.region_id,
        "zone_id": region.zone_id,
        "zone_index": 0,
        "region_index": region.region_index,
        "net_name": region.net_name,
        "layer": region.layer,
        "is_island": False,
        "direct_contact_ids": ("pad:J1.2",),
        "connected_pad_ids": ("J1.2",),
        "reachable_pad_ids": ("J1.2",),
        "pad_mapping_exact": True,
        "pad_mapping_scope": "integer_effective_shape_contact_graph",
    }
    record.update(changes)
    return KiCadFinalFillConnectivityObservation(
        board_file="filled.kicad_pcb",
        board_sha256=snapshot.filled_board_sha256,
        kicad_version="10.0.3",
        island_authority="ZONE.IsIsland(layer, filled_outline_index)",
        records=(record,),
        qualification_boundary="fixture",
    )


def test_single_region_with_declared_source_becomes_source_reachable(tmp_path: Path) -> None:
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    result = classify_final_fill_reachability(
        snapshot, _observation(snapshot), declared_source_pad_ids=("J1.2",)
    )
    assert result.regions[0].reachability is FillReachability.SOURCE_REACHABLE
    assert result.unverified_region_ids == ()


def test_kicad_island_is_exactly_floating(tmp_path: Path) -> None:
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    observation = _observation(
        snapshot,
        is_island=True,
        direct_contact_ids=(),
        connected_pad_ids=(),
        reachable_pad_ids=(),
        pad_mapping_scope="isolated_region_exact",
    )
    result = classify_final_fill_reachability(
        snapshot, observation, declared_source_pad_ids=("J1.2",)
    )
    assert result.regions[0].reachability is FillReachability.FLOATING


def test_fragmented_non_island_mapping_stays_unverified(tmp_path: Path) -> None:
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    observation = _observation(
        snapshot,
        direct_contact_ids=(),
        connected_pad_ids=(),
        reachable_pad_ids=(),
        pad_mapping_exact=False,
        pad_mapping_scope="fragmented_zone_pad_mapping_unresolved",
    )
    result = classify_final_fill_reachability(
        snapshot, observation, declared_source_pad_ids=("J1.2",)
    )
    assert result.regions[0].reachability is FillReachability.UNVERIFIED


def test_mixed_board_or_incomplete_region_set_fails_closed(tmp_path: Path) -> None:
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    observation = _observation(snapshot)
    with pytest.raises(ValueError, match="another board revision"):
        classify_final_fill_reachability(
            snapshot,
            observation.model_copy(update={"board_sha256": "f" * 64}),
            declared_source_pad_ids=("J1.2",),
        )
    with pytest.raises(ValueError, match="does not cover"):
        classify_final_fill_reachability(
            snapshot,
            observation.model_copy(update={"records": ()}),
            declared_source_pad_ids=("J1.2",),
        )


def test_thermal_connect_pads_syntax_is_retained_as_zone_intent(tmp_path: Path) -> None:
    source, filled = _boards(tmp_path)
    for path in (source, filled):
        text = path.read_text(encoding="utf-8").replace(
            "(connect_pads yes (clearance 0.2))",
            "(connect_pads (clearance 0.2))",
        )
        path.write_text(text, encoding="utf-8")
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    assert snapshot.zones[0].pad_connection_mode == "thermal"