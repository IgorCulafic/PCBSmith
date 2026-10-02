from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.reference_continuity import ReferenceContinuityEvidence
from pcbsmith.kicad.reference_continuity_geometry import segment_fully_covered


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _evidence(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_id": "pcbsmith-reference-continuity-evidence",
        "schema_version": 1,
        "authority": "exact-straight-centerline-geometric-v1",
        "reference_net_names": ["GND"],
        "copper_layer_count": 2,
        "signal_segment_count": 2,
        "exact_supported_segment_count": 2,
        "exact_unsupported_segment_count": 0,
        "unsupported_geometry_segment_count": 0,
        "signal_transition_count": 0,
        "transition_without_nearby_reference_via_count": 0,
        "maximum_transition_stitch_distance_mm": 2.0,
        "exact_pass_authorized": True,
        "automatic_multilayer_pass_prohibited": True,
        "disposition": "exact_geometric_continuity_observed",
        "findings": [],
        "scope": "exact centerline geometry only",
    }
    value.update(updates)
    value["evidence_fingerprint"] = _fingerprint(value)
    return value


def test_exact_evidence_can_authorize_only_a_clean_two_layer_model() -> None:
    parsed = ReferenceContinuityEvidence.model_validate(_evidence())
    assert parsed.exact_pass_authorized

    stale = _evidence(exact_unsupported_segment_count=1, exact_supported_segment_count=1)
    stale["exact_pass_authorized"] = True
    stale["evidence_fingerprint"] = _fingerprint(
        {key: value for key, value in stale.items() if key != "evidence_fingerprint"}
    )
    with pytest.raises(ValidationError, match="exact reference-continuity disposition is stale"):
        ReferenceContinuityEvidence.model_validate(stale)


def test_multilayer_never_receives_automatic_exact_pass() -> None:
    value = _evidence(
        copper_layer_count=4,
        exact_pass_authorized=False,
        disposition="unsupported_stackup_unverified",
    )
    parsed = ReferenceContinuityEvidence.model_validate(value)
    assert parsed.automatic_multilayer_pass_prohibited
    assert not parsed.exact_pass_authorized


def test_fingerprint_tamper_fails_closed() -> None:
    value = _evidence()
    value["scope"] = "tampered"
    with pytest.raises(ValidationError, match="evidence fingerprint is stale"):
        ReferenceContinuityEvidence.model_validate(value)


def test_exact_segment_union_and_hole_geometry() -> None:
    polygons = (
        (
            ((0, 0), (10, 0), (10, 10), (0, 10)),
            (((4, 4), (6, 4), (6, 6), (4, 6)),),
        ),
    )
    assert segment_fully_covered((1, 1), (9, 1), polygons)
    assert not segment_fully_covered((1, 5), (9, 5), polygons)
    assert not segment_fully_covered((-1, 1), (9, 1), polygons)


def test_adjacent_zone_union_is_continuous() -> None:
    polygons = (
        (((0, 0), (5, 0), (5, 10), (0, 10)), ()),
        (((5, 0), (10, 0), (10, 10), (5, 10)), ()),
    )
    assert segment_fully_covered((1, 5), (9, 5), polygons)
