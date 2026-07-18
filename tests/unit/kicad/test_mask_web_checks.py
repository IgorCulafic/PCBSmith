from __future__ import annotations

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.mask_geometry import (
    Disc,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    Point,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


def _profile(minimum_mm: float = 0.2) -> PcbRuleProfile:
    evidence = EvidenceRef(
        kind="manufacturer_capability",
        title="Mask process fixture",
        locator="minimum mask web",
        source_id="mask-process-fixture-v1",
    )
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={
            "minimum_solder_mask_web_mm": minimum_mm,
            "evidence": (evidence,),
        }
    )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})


def _aperture(
    source_id: str,
    x_mm: float,
    *,
    side: MaskSide = MaskSide.FRONT,
    parent_source_id: str | None = None,
    merge_group_id: str | None = None,
    owner_ref: str | None = None,
) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        parent_source_id=parent_source_id,
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=side,
        geometry=Disc(
            center=Point(x_mm=x_mm, y_mm=2.0),
            radius_mm=0.5,
        ),
        owner_ref=owner_ref,
        merge_group_id=merge_group_id,
    )


def _layout(*apertures: MaskAperture, graphics: tuple[str, ...] = ()) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=10.0,
        height_mm=10.0,
        graphics=graphics,
        mask_apertures=apertures,
    )


def _run(layout: BoardLayout, profile: PcbRuleProfile):
    return run_design_checks(
        layout,
        BoardNetlist(components=(), nets=()),
        DesignChecksSpec(),
        profile,
    )


def test_inactive_mask_rule_does_not_inspect_sources() -> None:
    unsupported = MaskAperture(
        source_id="unsupported",
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.FRONT,
        verification=MaskVerification.UNSUPPORTED,
        unsupported_reason="fixture",
    )

    report = _run(
        _layout(unsupported, graphics=('  (gr_poly (layer "F.Mask"))',)),
        DEFAULT_PCB_RULE_PROFILE,
    )

    assert "solder_mask_web" not in report.checks_run
    assert not [finding for finding in report.findings if finding.category == "solder_mask"]


def test_exact_positive_mask_sliver_is_a_structured_blocker() -> None:
    profile = _profile()
    report = _run(
        _layout(
            _aperture("first", 1.0, owner_ref="U1"),
            _aperture("second", 2.15, owner_ref="U1"),
        ),
        profile,
    )

    findings = [finding for finding in report.findings if finding.rule == "fab.solder_mask_web"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "blocker"
    assert finding.scope == "component"
    assert finding.object_ids == ("first", "second")
    assert finding.component_refs == ("U1",)
    assert finding.constraint_ids == ("minimum_solder_mask_web_mm",)
    assert finding.evidence_refs == profile.geometry.evidence
    assert "0.15mm" in finding.evidence
    assert report.status == "failed"


def test_mask_web_at_limit_and_cross_side_pair_pass() -> None:
    report = _run(
        _layout(
            _aperture("front-a", 1.0),
            _aperture("front-b", 2.2),
            _aperture("back-overlap", 1.0, side=MaskSide.BACK),
        ),
        _profile(),
    )

    assert not [
        finding
        for finding in report.findings
        if finding.rule in {"fab.solder_mask_web", "fab.mask_aperture_merge"}
    ]


def test_undeclared_merge_blocks_but_common_merge_group_is_reviewed() -> None:
    accidental = _run(
        _layout(
            _aperture("first", 1.0),
            _aperture("second", 1.8),
        ),
        _profile(),
    )
    deliberate = _run(
        _layout(
            _aperture("first", 1.0, merge_group_id="gang-1"),
            _aperture("second", 1.8, merge_group_id="gang-1"),
        ),
        _profile(),
    )

    merged = [
        finding for finding in accidental.findings if finding.rule == "fab.mask_aperture_merge"
    ]
    assert len(merged) == 1
    assert merged[0].severity == "blocker"
    assert "overlap" in merged[0].evidence
    assert not [
        finding for finding in deliberate.findings if finding.rule == "fab.mask_aperture_merge"
    ]


def test_merge_group_does_not_waive_a_positive_web_and_parent_children_are_ignored() -> None:
    grouped_sliver = _run(
        _layout(
            _aperture("first", 1.0, merge_group_id="gang-1"),
            _aperture("second", 2.15, merge_group_id="gang-1"),
        ),
        _profile(),
    )
    same_parent = _run(
        _layout(
            _aperture("child-a", 1.0, parent_source_id="parent"),
            _aperture("child-b", 1.8, parent_source_id="parent"),
        ),
        _profile(),
    )

    assert len(
        [finding for finding in grouped_sliver.findings if finding.rule == "fab.solder_mask_web"]
    ) == 1
    assert not [
        finding
        for finding in same_parent.findings
        if finding.rule in {"fab.solder_mask_web", "fab.mask_aperture_merge"}
    ]


def test_unverified_source_requires_human_review_with_stable_identity() -> None:
    profile = _profile()
    unsupported = MaskAperture(
        source_id="raw-front-mask",
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.FRONT,
        owner_ref="U2",
        verification=MaskVerification.UNSUPPORTED,
        unsupported_reason="raw mask graphic is opaque",
    )

    first = _run(_layout(unsupported), profile)
    second = _run(_layout(unsupported), profile)
    findings = [
        finding
        for finding in first.findings
        if finding.rule == "fab.solder_mask_web_unverified"
    ]

    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].object_ids == ("raw-front-mask",)
    assert findings[0].component_refs == ("U2",)
    assert findings[0].constraint_ids == ("minimum_solder_mask_web_mm",)
    assert first.status == "needs_human_review"
    assert findings[0].fingerprint == next(
        finding.fingerprint
        for finding in second.findings
        if finding.rule == "fab.solder_mask_web_unverified"
    )