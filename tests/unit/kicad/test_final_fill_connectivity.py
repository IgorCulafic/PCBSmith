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


def test_new_physical_pad_inventory_cannot_silently_omit_observed_contacts(tmp_path):
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    values = _observation(snapshot).model_dump()
    values["pad_zone_contacts"] = ()
    with pytest.raises(ValueError, match="cover every observed pad contact"):
        KiCadFinalFillConnectivityObservation.model_validate(values)


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


def _graph_observation(snapshot, *, orphan=False):
    values = _observation(snapshot).model_dump(mode="json")
    record = values["records"][0]
    record.update(
        direct_contact_ids=[] if orphan else ["pad:physical-source"],
        connected_pad_ids=[] if orphan else ["pad:physical-source"],
        reachable_pad_ids=[] if orphan else ["pad:physical-source"],
        outline_nm=[[0, 0], [10_000_000, 0], [10_000_000, 10_000_000], [0, 10_000_000]],
        holes_nm=[],
    )
    values["region_contact_graph"] = {
        "authority": "native-copper-items-and-filled-regions-v1",
        "item_components": [
            {
                "net_name": record["net_name"],
                "item_ids": ["pad:physical-source"],
                "pad_ids": ["pad:physical-source"],
            }
        ],
        "region_contacts": [],
    }
    return values


def test_complete_graph_proves_isolation_without_native_flag(tmp_path):
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    values = _graph_observation(snapshot, orphan=True)
    observation = KiCadFinalFillConnectivityObservation.model_validate(values)
    result = classify_final_fill_reachability(
        snapshot, observation, declared_source_pad_ids=("pad:physical-source",)
    )
    assert not observation.records[0].is_island
    assert result.regions[0].reachability == FillReachability.FLOATING
    # Older empty-contact observations do not gain an inferred proof of completeness.
    values.pop("region_contact_graph")
    legacy = KiCadFinalFillConnectivityObservation.model_validate(values)
    result = classify_final_fill_reachability(
        snapshot, legacy, declared_source_pad_ids=("pad:physical-source",)
    )
    assert result.regions[0].reachability == FillReachability.UNVERIFIED


@pytest.mark.parametrize(
    "defect",
    [
        "invented_source",
        "omitted_pad",
        "missing_item",
        "foreign_net",
        "duplicate_component",
        "unsupported_item",
        "missing_geometry",
    ],
)
def test_region_graph_rejects_inconsistent_contact_evidence(tmp_path, defect):
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    values = _graph_observation(snapshot)
    record = values["records"][0]
    components = values["region_contact_graph"]["item_components"]
    if defect == "invented_source":
        record["reachable_pad_ids"].append("pad:invented")
    elif defect == "omitted_pad":
        components[0]["pad_ids"] = []
    elif defect == "missing_item":
        values["region_contact_graph"]["item_components"] = []
    elif defect == "foreign_net":
        components[0]["net_name"] = "POWER"
    elif defect == "duplicate_component":
        components.append(components[0])
    elif defect == "unsupported_item":
        components[0]["item_ids"].append("zone:all-fragments")
    else:
        record.pop("outline_nm")
        record.pop("holes_nm")
    with pytest.raises(ValueError):
        KiCadFinalFillConnectivityObservation.model_validate(values)


@pytest.mark.parametrize(
    "defect", [None, "other_layer", "other_net", "unknown_region", "duplicate_link", "missing_link"]
)
def test_zone_contact_evidence_requires_same_net_and_layer(tmp_path, defect):
    source, filled = _boards(tmp_path)
    snapshot = parse_kicad_final_fill_snapshot(
        source, filled, kicad_version="10.0.3", refilled_by_kicad=True
    )
    values = _graph_observation(snapshot)
    first = values["records"][0]
    second = dict(
        first,
        region_id="zone:zone-2:filled:0",
        zone_id="zone:zone-2",
        zone_index=1,
        direct_contact_ids=[],
        connected_pad_ids=[],
    )
    values["records"].append(second)
    link = sorted((first["region_id"], second["region_id"]))
    values["region_contact_graph"]["region_contacts"] = [link]
    if defect == "other_layer":
        second["layer"] = "F.Cu"
    elif defect == "other_net":
        second["net_name"] = "POWER"
    elif defect == "unknown_region":
        link[1] = "zone:zone-missing:filled:0"
    elif defect == "duplicate_link":
        values["region_contact_graph"]["region_contacts"].append(link)
    elif defect == "missing_link":
        values["region_contact_graph"]["region_contacts"] = []
    if defect:
        with pytest.raises(ValueError):
            KiCadFinalFillConnectivityObservation.model_validate(values)
    else:
        observed = KiCadFinalFillConnectivityObservation.model_validate(values)
        assert observed.records[1].reachable_pad_ids == ("pad:physical-source",)
