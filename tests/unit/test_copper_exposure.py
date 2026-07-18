from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.copper_exposure import (
    CopperExposureResult,
    CopperGeometryVerification,
    OuterCopperRegion,
    classify_outer_copper_exposure,
)
from pcbsmith.mask_geometry import (
    Compound,
    Disc,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    Point,
)


def _disc(x_mm: float, radius_mm: float = 1.0) -> Disc:
    return Disc(center=Point(x_mm=x_mm, y_mm=0.0), radius_mm=radius_mm)


def _copper(
    source_id: str = "track:1",
    *,
    side: MaskSide = MaskSide.FRONT,
    geometry: Disc | None = None,
) -> OuterCopperRegion:
    return OuterCopperRegion(
        source_id=source_id,
        side=side,
        net_name="LED_A",
        role="routed_conductor",
        geometry=geometry or _disc(0.0),
    )


def _exact_aperture(
    source_id: str,
    geometry: Disc | Compound,
    *,
    side: MaskSide = MaskSide.FRONT,
) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=side,
        geometry=geometry,
    )


def _unsupported_aperture(
    source_id: str,
    geometry: Disc | None,
    *,
    side: MaskSide = MaskSide.FRONT,
) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        source_kind=MaskSourceKind.PAD,
        side=side,
        geometry=geometry,
        verification=MaskVerification.UNSUPPORTED,
        unsupported_reason="source geometry is not modeled",
    )


def _bounded_aperture(
    source_id: str,
    geometry: Disc,
    *,
    maximum_error_mm: float,
    side: MaskSide = MaskSide.FRONT,
) -> MaskAperture:
    return MaskAperture(
        source_id=source_id,
        source_kind=MaskSourceKind.PAD,
        side=side,
        geometry=geometry,
        verification=MaskVerification.BOUNDED_APPROXIMATION,
        maximum_error_mm=maximum_error_mm,
    )


def test_one_containing_aperture_primitive_is_fully_exposed() -> None:
    result = classify_outer_copper_exposure(
        [_copper()], [_exact_aperture("mask:large", _disc(0.0, 2.0))]
    )[0]

    assert result.state == "fully_exposed"
    assert result.aperture_source_ids == ("mask:large",)
    assert result.unresolved_aperture_source_ids == ()


def test_one_noncontaining_overlap_is_partially_exposed() -> None:
    result = classify_outer_copper_exposure(
        [_copper()], [_exact_aperture("mask:partial", _disc(1.0, 0.5))]
    )[0]

    assert result.state == "partially_exposed"
    assert result.aperture_source_ids == ("mask:partial",)


def test_separated_aperture_leaves_copper_masked() -> None:
    result = classify_outer_copper_exposure([_copper()], [_exact_aperture("mask:far", _disc(4.0))])[
        0
    ]

    assert result.state == "masked"
    assert result.aperture_source_ids == ()


def test_boundary_touching_has_no_exposed_area() -> None:
    result = classify_outer_copper_exposure(
        [_copper()], [_exact_aperture("mask:touching", _disc(2.0))]
    )[0]

    assert result.state == "masked"


def test_front_and_back_apertures_are_isolated() -> None:
    results = classify_outer_copper_exposure(
        [
            _copper("via:1", side=MaskSide.BACK),
            _copper("via:1", side=MaskSide.FRONT),
        ],
        [_exact_aperture("mask:front", _disc(0.0, 2.0))],
    )

    assert [(item.side, item.state) for item in results] == [
        (MaskSide.BACK, "masked"),
        (MaskSide.FRONT, "fully_exposed"),
    ]


def test_multiple_overlapping_union_parts_are_unknown_without_union_proof() -> None:
    aperture = _exact_aperture(
        "mask:compound",
        Compound(parts=(_disc(-0.75, 0.75), _disc(0.75, 0.75))),
    )

    result = classify_outer_copper_exposure([_copper()], [aperture])[0]

    assert result.state == "unknown"
    assert result.aperture_source_ids == ("mask:compound",)
    assert "union containment" in result.reason


def test_unlocated_unsupported_aperture_poisons_its_entire_side() -> None:
    result = classify_outer_copper_exposure(
        [_copper()], [_unsupported_aperture("mask:unknown", None)]
    )[0]

    assert result.state == "unknown"
    assert result.unresolved_aperture_source_ids == ("mask:unknown",)


def test_bounded_approximation_only_poisons_copper_within_its_error_envelope() -> None:
    results = classify_outer_copper_exposure(
        [_copper("track:near"), _copper("track:far", geometry=_disc(8.0))],
        [_bounded_aperture("mask:bounded", _disc(0.0, 0.5), maximum_error_mm=0.1)],
    )

    assert [(item.copper_source_id, item.state) for item in results] == [
        ("track:far", "masked"),
        ("track:near", "unknown"),
    ]
    assert results[0].unresolved_aperture_source_ids == ()
    assert results[1].unresolved_aperture_source_ids == ("mask:bounded",)


def test_bounded_approximation_at_error_boundary_is_relevant() -> None:
    result = classify_outer_copper_exposure(
        [_copper()],
        [_bounded_aperture("mask:error-boundary", _disc(2.2), maximum_error_mm=0.2)],
    )[0]

    assert result.state == "unknown"
    assert result.unresolved_aperture_source_ids == ("mask:error-boundary",)


def test_bounded_approximation_beyond_error_envelope_is_irrelevant() -> None:
    result = classify_outer_copper_exposure(
        [_copper()],
        [_bounded_aperture("mask:beyond-error", _disc(2.21), maximum_error_mm=0.2)],
    )[0]

    assert result.state == "masked"
    assert result.unresolved_aperture_source_ids == ()


def test_touching_bounded_approximation_is_relevant() -> None:
    result = classify_outer_copper_exposure(
        [_copper()],
        [_bounded_aperture("mask:touching-bounded", _disc(2.0), maximum_error_mm=0.01)],
    )[0]

    assert result.state == "unknown"


def test_unsupported_nominal_geometry_does_not_localize_uncertainty() -> None:
    result = classify_outer_copper_exposure(
        [_copper()], [_unsupported_aperture("mask:unsupported-far", _disc(50.0))]
    )[0]

    assert result.state == "unknown"
    assert result.unresolved_aperture_source_ids == ("mask:unsupported-far",)


def test_proven_full_exposure_is_monotonic_despite_unsupported_aperture() -> None:
    result = classify_outer_copper_exposure(
        [_copper()],
        [
            _unsupported_aperture("mask:unknown", None),
            _exact_aperture("mask:full", _disc(0.0, 2.0)),
        ],
    )[0]

    assert result.state == "fully_exposed"
    assert result.aperture_source_ids == ("mask:full",)
    assert result.unresolved_aperture_source_ids == ("mask:unknown",)


def test_conflicting_duplicate_copper_identity_is_unknown_integrity() -> None:
    results = classify_outer_copper_exposure(
        [_copper(geometry=_disc(0.0)), _copper(geometry=_disc(3.0))], []
    )

    assert len(results) == 1
    assert results[0].state == "unknown"
    assert results[0].role == "unknown"
    assert "conflicting definitions" in results[0].reason


def test_identical_duplicate_is_deduplicated_and_results_are_deterministic() -> None:
    duplicate = _copper("track:z")
    results = classify_outer_copper_exposure(
        [_copper("track:a"), duplicate, duplicate],
        [_exact_aperture("mask:z", _disc(0.0, 2.0))],
    )

    assert [item.copper_source_id for item in results] == ["track:a", "track:z"]
    assert all(item.state == "fully_exposed" for item in results)


def test_unsupported_copper_geometry_is_unknown() -> None:
    region = OuterCopperRegion(
        source_id="zone:1",
        side=MaskSide.FRONT,
        net_name="GND",
        role="copper_pour",
        verification=CopperGeometryVerification.UNSUPPORTED,
        unsupported_reason="filled zone geometry is unavailable",
    )

    result = classify_outer_copper_exposure([region], [])[0]

    assert result.state == "unknown"
    assert result.role == "copper_pour"


def test_models_are_frozen_strict_and_semantically_versioned() -> None:
    result = CopperExposureResult(
        copper_source_id="track:1",
        side=MaskSide.FRONT,
        state="masked",
        role="routed_conductor",
        reason="no opening",
    )

    assert '"schema_version":1' in result.semantic_json()
    assert len(result.semantic_fingerprint()) == 64
    with pytest.raises(ValidationError):
        CopperExposureResult.model_validate(
            {
                **result.model_dump(),
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        result.state = "fully_exposed"  # type: ignore[misc]
