from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFilledRegionContactObservation,
    KiCadFinalFillConnectivityObservation,
)
from pcbsmith.kicad.final_fill_thermal import (
    ThermalSpokeDisposition,
    audit_kicad_thermal_spokes,
)


def _observation(*, thermal: tuple[str, ...] = (), unresolved: tuple[str, ...] = ()):
    return KiCadFinalFillConnectivityObservation(
        board_file="board.kicad_pcb",
        board_sha256="a" * 64,
        kicad_version="10.0.3",
        island_authority="ZONE.IsIsland(layer, filled_outline_index)",
        records=(
            KiCadFilledRegionContactObservation(
                region_id="region:1",
                zone_id="zone:1",
                zone_index=0,
                region_index=0,
                net_name="GND",
                layer="B.Cu",
                is_island=False,
                direct_contact_ids=("pad:J1.1",),
                connected_pad_ids=("J1.1",),
                reachable_pad_ids=("J1.1",),
                thermal_applicable_pad_ids=thermal,
                thermal_resolution_unverified_pad_ids=unresolved,
                pad_mapping_exact=True,
                pad_mapping_scope="integer_effective_shape_contact_graph",
            ),
        ),
        qualification_boundary="fixture",
    )


def _report(tmp_path: Path, violations: list[dict[str, object]]) -> Path:
    path = tmp_path / "drc.json"
    path.write_text(json.dumps({"violations": violations}), encoding="utf-8")
    return path


def test_applicable_thermal_passes_only_with_exact_revision_and_no_starvation(
    tmp_path: Path,
) -> None:
    audit = audit_kicad_thermal_spokes(
        _observation(thermal=("J1.1",)),
        _report(tmp_path, []),
        drc_report_board_sha256="a" * 64,
    )
    assert audit.disposition is ThermalSpokeDisposition.PASS
    assert audit.evaluated_object_count == 1


def test_starved_thermal_fails_and_unknown_mode_is_unverified(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        [{"type": "starved_thermal", "items": [{"uuid": "pad-uuid"}]}],
    )
    failed = audit_kicad_thermal_spokes(
        _observation(thermal=("J1.1",)),
        report,
        drc_report_board_sha256="a" * 64,
    )
    assert failed.disposition is ThermalSpokeDisposition.FAIL
    unverified = audit_kicad_thermal_spokes(
        _observation(unresolved=("J1.1",)),
        report,
        drc_report_board_sha256="a" * 64,
    )
    assert unverified.disposition is ThermalSpokeDisposition.UNVERIFIED


def test_no_thermal_contacts_is_explicitly_not_applicable(tmp_path: Path) -> None:
    audit = audit_kicad_thermal_spokes(
        _observation(),
        _report(tmp_path, []),
        drc_report_board_sha256="a" * 64,
    )
    assert audit.disposition is ThermalSpokeDisposition.NOT_APPLICABLE
    assert audit.evaluated_object_count == 0


def test_foreign_revision_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="another board revision"):
        audit_kicad_thermal_spokes(
            _observation(),
            _report(tmp_path, []),
            drc_report_board_sha256="b" * 64,
        )
