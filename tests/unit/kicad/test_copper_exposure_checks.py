from __future__ import annotations

import pytest

import pcbsmith.kicad.design_checks as design_checks_module
from pcbsmith.kicad.board import BoardLayout, BoardNetlist, TrackSegment
from pcbsmith.kicad.copper_identity import track_copper_source_id
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.mask_geometry import (
    Disc,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    Point,
)
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    OrdinaryClearanceRequirement,
    PcbRuleProfile,
)


def _requirement(
    requirement_id: str = "exposure-a",
    *,
    mask_states_a: tuple[str, ...] = ("fully_exposed",),
    roles_a: tuple[str, ...] = (),
) -> OrdinaryClearanceRequirement:
    return OrdinaryClearanceRequirement(
        requirement_id=requirement_id,
        nets_a=("/A",),
        nets_b=("/B",),
        minimum_clearance_mm=0.4,
        mask_states_a=mask_states_a,
        roles_a=roles_a,
    )


def _profile(
    *requirements: OrdinaryClearanceRequirement,
    minimum_web_mm: float | None = None,
) -> PcbRuleProfile:
    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
        update={"pairwise_clearances": requirements}
    )
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={
            "default_pad_solder_mask_expansion_mm": 0.0,
            "minimum_solder_mask_web_mm": minimum_web_mm,
        }
    )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={"fab_spacing": spacing, "geometry": geometry}
    )


def _unsupported(source_id: str = "raw-front-mask") -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.FRONT,
        verification=MaskVerification.UNSUPPORTED,
        unsupported_reason="unlocated raw front-mask fixture",
    )


def _covering_aperture() -> MaskAperture:
    return MaskAperture(
        source_id="exact-front-opening",
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.FRONT,
        geometry=Disc(center=Point(x_mm=2.0, y_mm=2.0), radius_mm=2.0),
    )


def _layout(*apertures: MaskAperture) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(TrackSegment(1.0, 2.0, 3.0, 2.0, "F.Cu", "/A", 0.2),),
        vias=(),
        width_mm=10.0,
        height_mm=10.0,
        mask_apertures=apertures,
    )


def _run(layout: BoardLayout, profile: PcbRuleProfile):
    return run_design_checks(
        layout,
        BoardNetlist(components=(), nets=()),
        DesignChecksSpec(),
        profile,
    )


def _exposure_findings(report):
    return [
        finding for finding in report.findings if finding.rule == "fab.copper_exposure_unverified"
    ]


def test_no_mask_selector_does_not_run_exposure_check() -> None:
    report = _run(
        _layout(_unsupported()),
        _profile(_requirement(mask_states_a=())),
    )

    assert "outer_copper_exposure" not in report.checks_run
    assert _exposure_findings(report) == []


def test_scoped_unknown_exposure_is_one_stable_structured_warning() -> None:
    profile = _profile(_requirement("z-scope"), _requirement("a-scope"))
    first = _run(_layout(_unsupported()), profile)
    second = _run(_layout(_unsupported()), profile)

    assert "outer_copper_exposure" in first.checks_run
    findings = _exposure_findings(first)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "warning"
    assert finding.phase == "fabrication_geometry"
    assert finding.category == "solder_mask"
    assert finding.scope == "net"
    assert finding.object_ids == (track_copper_source_id(0), "raw-front-mask")
    assert finding.component_refs == ()
    assert finding.net_refs == ("/A",)
    assert finding.constraint_ids == ("a-scope", "z-scope")
    assert "side=front" in finding.evidence
    assert "net=/A" in finding.evidence
    assert "role=routed_conductor" in finding.evidence
    assert "raw-front-mask" in finding.evidence
    assert "unlocated raw front-mask fixture" in finding.evidence
    assert finding.fingerprint == _exposure_findings(second)[0].fingerprint


def test_explicit_unknown_selector_makes_scope_executable() -> None:
    report = _run(
        _layout(_unsupported()),
        _profile(_requirement(mask_states_a=("unknown",))),
    )

    assert "outer_copper_exposure" in report.checks_run
    assert _exposure_findings(report) == []


def test_definitive_role_mismatch_excludes_unknown_track() -> None:
    report = _run(
        _layout(_unsupported()),
        _profile(_requirement(roles_a=("component_termination",))),
    )

    assert "outer_copper_exposure" in report.checks_run
    assert _exposure_findings(report) == []


def test_proven_full_exposure_is_not_warned_despite_unresolved_source() -> None:
    report = _run(
        _layout(_covering_aperture(), _unsupported()),
        _profile(_requirement()),
    )

    assert "outer_copper_exposure" in report.checks_run
    assert _exposure_findings(report) == []


def test_mask_web_and_exposure_share_one_aperture_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real_collect = design_checks_module.collect_mask_apertures

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_collect(*args, **kwargs)

    monkeypatch.setattr(design_checks_module, "collect_mask_apertures", counted)
    report = _run(
        _layout(_unsupported()),
        _profile(_requirement(), minimum_web_mm=0.2),
    )

    assert calls == 1
    assert "outer_copper_exposure" in report.checks_run
    assert "solder_mask_web" in report.checks_run
    warning_rules = {finding.rule for finding in report.findings if finding.severity == "warning"}
    assert "fab.copper_exposure_unverified" in warning_rules
    assert "fab.solder_mask_web_unverified" in warning_rules
