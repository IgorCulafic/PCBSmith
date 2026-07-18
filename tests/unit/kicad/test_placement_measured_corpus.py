"""Measured shaped-placement corpus authority tests."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_placement_serialization import _component

from pcbsmith.kicad.board import (
    BoardCutoutPolygon,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.board_serialization import parse_canonical_board_layout_snapshot
from pcbsmith.kicad.placement_measured_corpus import (
    MeasuredShapedPlacementCorpus,
    run_measured_shaped_placement_corpus,
)
from pcbsmith.kicad.placement_readback import (
    PlacementKiCadSaveRoundtripAuthority,
    extract_kicad_board_readback,
)
from pcbsmith.kicad.placement_serialization import build_placement_serialization_authority
from pcbsmith.mask_geometry import ViaMaskIntent
from pcbsmith.placement_serialization_ir import PlacementSerializationAuthority


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _front_routed_case() -> PlacementSerializationAuthority:
    r1 = _component("R1")
    r2 = _component("R2")
    r3 = _component("R3")
    layout = BoardLayout(
        placements=((r1, 5.0), (r2, 11.0), (r3, 14.0)),
        segments=(
            TrackSegment(5.825, 6.0, 7.0, 6.0, "F.Cu", "/LINK", 0.25),
            TrackSegment(7.0, 6.0, 9.0, 6.0, "B.Cu", "/LINK", 0.25),
            TrackSegment(9.0, 6.0, 10.175, 6.0, "F.Cu", "/LINK", 0.25),
        ),
        vias=(
            ViaSpec(
                7.0,
                6.0,
                "/LINK",
                0.7,
                0.3,
                ViaMaskIntent.INHERIT,
                ViaMaskIntent.INHERIT,
            ),
            ViaSpec(
                9.0,
                6.0,
                "/LINK",
                0.7,
                0.3,
                ViaMaskIntent.INHERIT,
                ViaMaskIntent.INHERIT,
            ),
        ),
        width_mm=18.0,
        height_mm=14.0,
        parts_row_y_mm=6.0,
        part_y_mm=(("R3", 10.0),),
        part_rotation=(("R3", 90.0),),
        outline=(
            (0.0, 2.0),
            (2.0, 0.0),
            (16.0, 0.0),
            (18.0, 2.0),
            (18.0, 12.0),
            (16.0, 14.0),
            (2.0, 14.0),
            (0.0, 12.0),
        ),
    )
    netlist = BoardNetlist(
        components=(r1, r2, r3),
        nets=(BoardNet("/LINK", (("R1", "2"), ("R2", "1"))),),
    )
    return build_placement_serialization_authority(
        layout, netlist, layout, ("/LINK",), ("R1", "R2", "R3")
    )


def _back_cutout_case() -> PlacementSerializationAuthority:
    r4 = _component("R4")
    layout = BoardLayout(
        placements=((r4, 11.0),),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=16.0,
        parts_row_y_mm=8.0,
        part_flip=("R4",),
        outline=(
            (0.0, 2.0),
            (2.0, 0.0),
            (18.0, 0.0),
            (20.0, 2.0),
            (20.0, 14.0),
            (18.0, 16.0),
            (2.0, 16.0),
            (0.0, 14.0),
        ),
        cutouts=(BoardCutoutPolygon(((3.0, 3.0), (6.0, 3.0), (6.0, 6.0), (3.0, 6.0))),),
    )
    netlist = BoardNetlist(
        components=(r4,),
        nets=(BoardNet("/LOCAL", (("R4", "1"),)),),
    )
    return build_placement_serialization_authority(layout, netlist, layout, ("/LOCAL",), ("R4",))


def _fake_roundtrip(
    serialization: PlacementSerializationAuthority,
) -> PlacementKiCadSaveRoundtripAuthority:
    text = serialization.rendered_board_text
    snapshot = extract_kicad_board_readback(text)
    report = json.dumps(
        {
            "ignored_checks": [
                {
                    "description": "Footprint doesn't match copy in library",
                    "key": "lib_footprint_mismatch",
                }
            ],
            "schematic_parity": [],
            "unconnected_items": [],
            "violations": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return PlacementKiCadSaveRoundtripAuthority(
        serialization_authority=serialization,
        kicad_cli_version="10.0-test",
        initial_board_text=text,
        saved_board_text=text,
        initial_board_sha256=_sha256(text),
        saved_board_sha256=_sha256(text),
        repeated_saved_board_sha256=_sha256(text),
        initial_snapshot=snapshot,
        saved_snapshot=snapshot,
        drc_status="passed",
        drc_report_json=report,
        drc_report_sha256=_sha256(report),
        require_drc_pass=True,
    )


def test_runner_canonicalizes_cases_rederives_metrics_and_reconstructs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_verify(
        authority: PlacementSerializationAuthority,
        output_root: Path,
        *,
        require_drc_pass: bool,
    ) -> PlacementKiCadSaveRoundtripAuthority:
        calls.append((output_root.name, require_drc_pass))
        return _fake_roundtrip(authority)

    monkeypatch.setattr(
        "pcbsmith.kicad.placement_measured_corpus.verify_placement_kicad_save_roundtrip",
        fake_verify,
    )
    corpus = run_measured_shaped_placement_corpus(
        (("z-back-cutout", _back_cutout_case()), ("a-front-routed", _front_routed_case())),
        tmp_path,
    )

    assert tuple(case.case_id for case in corpus.cases) == (
        "a-front-routed",
        "z-back-cutout",
    )
    assert calls == [("a-front-routed", True), ("z-back-cutout", True)]
    for case_id in ("a-front-routed", "z-back-cutout"):
        policy = tmp_path / case_id / "run-1" / "placement-roundtrip.kicad_pro"
        assert json.loads(policy.read_text(encoding="utf-8"))["board"]["design_settings"][
            "rule_severities"
        ] == {
            "footprint_filters_mismatch": "warning",
            "footprint_type_mismatch": "warning",
            "lib_footprint_mismatch": "ignore",
            "missing_courtyard": "warning",
            "track_not_centered_on_via": "warning",
            "tuning_profile_track_geometries": "warning",
        }
    assert corpus.kicad_cli_versions == ("10.0-test",)
    assert "no performance" in corpus.authorized_inference
    assert MeasuredShapedPlacementCorpus.model_validate_json(corpus.model_dump_json()) == corpus

    routed, cutout = corpus.cases
    assert routed.measurements.front_placement_count == 3
    assert routed.measurements.back_placement_count == 0
    assert routed.measurements.segment_count == 3
    assert routed.measurements.via_count == 2
    assert routed.measurements.total_routed_length.lower.as_fraction() == Fraction(87, 20)
    assert routed.measurements.total_routed_length.upper.as_fraction() == Fraction(87, 20)
    assert cutout.measurements.has_cutouts
    assert cutout.measurements.back_placement_count == 1
    assert cutout.measurements.substrate_area_after_cutouts.as_fraction() == 303


def test_runner_rejects_too_few_duplicate_and_unsafe_cases_before_kicad(tmp_path: Path) -> None:
    authority = _front_routed_case()
    with pytest.raises(ValueError, match="at least two"):
        run_measured_shaped_placement_corpus((("one", authority),), tmp_path)
    with pytest.raises(ValueError, match="unique"):
        run_measured_shaped_placement_corpus(
            (("same", authority), ("same", _back_cutout_case())), tmp_path
        )
    with pytest.raises(ValueError, match="safe canonical"):
        run_measured_shaped_placement_corpus(
            (("../escape", authority), ("valid", _back_cutout_case())), tmp_path
        )


@pytest.mark.parametrize(
    "tamper",
    (
        "measurement",
        "artifact_hash",
        "drc_policy",
        "ignored_check",
        "case_fingerprint",
        "corpus_fingerprint",
        "tool_version",
    ),
)
def test_retained_corpus_rejects_every_derived_authority_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
) -> None:
    monkeypatch.setattr(
        "pcbsmith.kicad.placement_measured_corpus.verify_placement_kicad_save_roundtrip",
        lambda authority, output_root, *, require_drc_pass: _fake_roundtrip(authority),
    )
    corpus = run_measured_shaped_placement_corpus(
        (("front", _front_routed_case()), ("back", _back_cutout_case())), tmp_path
    )
    payload = corpus.model_dump(mode="json")
    if tamper == "measurement":
        payload["cases"][0]["measurements"]["placement_count"] += 1
    elif tamper == "artifact_hash":
        payload["cases"][0]["artifact_hashes"]["saved_board_sha256"] = "0" * 64
    elif tamper == "drc_policy":
        payload["cases"][0]["drc_policy"]["project_sha256"] = "0" * 64
    elif tamper == "ignored_check":
        report = json.loads(payload["cases"][0]["roundtrip_authority"]["drc_report_json"])
        report["ignored_checks"].append(
            {
                "description": "Track endpoint not centered on via",
                "key": "track_not_centered_on_via",
            }
        )
        canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
        payload["cases"][0]["roundtrip_authority"]["drc_report_json"] = canonical
        payload["cases"][0]["roundtrip_authority"]["drc_report_sha256"] = _sha256(canonical)
    elif tamper == "case_fingerprint":
        payload["cases"][0]["case_fingerprint"] = "0" * 64
    elif tamper == "corpus_fingerprint":
        payload["corpus_fingerprint"] = "0" * 64
    else:
        payload["kicad_cli_versions"] = ["tampered"]
    with pytest.raises(ValidationError):
        MeasuredShapedPlacementCorpus.model_validate(payload)


def test_routed_length_is_a_conservative_rational_interval_for_diagonal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = _front_routed_case()
    # Rebuild a valid serialization rather than tampering with retained hashes.
    layout = replace(
        _layout_from_authority(first),
        segments=(TrackSegment(5.0, 6.0, 6.0, 7.0, "F.Cu", "/LINK", 0.25),),
        vias=(),
    )
    netlist = BoardNetlist(
        components=tuple(component for component, _ in layout.placements),
        nets=(BoardNet("/LINK", (("R1", "2"), ("R2", "1"))),),
    )
    diagonal = build_placement_serialization_authority(
        layout,
        netlist,
        layout,
        ("/LINK",),
        tuple(component.reference for component, _ in layout.placements),
    )
    monkeypatch.setattr(
        "pcbsmith.kicad.placement_measured_corpus.verify_placement_kicad_save_roundtrip",
        lambda authority, output_root, *, require_drc_pass: _fake_roundtrip(authority),
    )
    corpus = run_measured_shaped_placement_corpus(
        (("diagonal", diagonal), ("back", _back_cutout_case())), tmp_path
    )
    diagonal_case = next(case for case in corpus.cases if case.case_id == "diagonal")
    interval = diagonal_case.measurements.total_routed_length
    assert interval.lower.as_fraction() ** 2 <= 2
    assert interval.upper.as_fraction() ** 2 >= 2
    assert interval.lower.as_fraction() < interval.upper.as_fraction()


def _layout_from_authority(authority: PlacementSerializationAuthority) -> BoardLayout:
    return parse_canonical_board_layout_snapshot(authority.final_layout_snapshot_json)


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_R5_KICAD_GOLDEN") != "1",
    reason="set PCBSMITH_R5_KICAD_GOLDEN=1 to exercise the installed KiCad CLI",
)
def test_live_measured_corpus_is_order_and_repeat_deterministic(tmp_path: Path) -> None:
    cases = (("front-routed", _front_routed_case()), ("back-cutout", _back_cutout_case()))
    first = run_measured_shaped_placement_corpus(cases, tmp_path / "first")
    reversed_order = run_measured_shaped_placement_corpus(
        tuple(reversed(cases)), tmp_path / "reversed"
    )
    repeated = run_measured_shaped_placement_corpus(cases, tmp_path / "repeated")

    assert first == reversed_order == repeated
    assert all(case.measurements.drc_status == "passed" for case in first.cases)
    assert all(case.measurements.drc_finding_count == 0 for case in first.cases)
    assert any(case.measurements.has_cutouts for case in first.cases)
    assert any(case.measurements.back_placement_count for case in first.cases)
    assert any(case.measurements.front_placement_count for case in first.cases)
