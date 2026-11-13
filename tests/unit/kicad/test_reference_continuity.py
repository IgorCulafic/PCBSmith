from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.reference_continuity import (
    ReferenceContinuityEvidence,
    observe_reference_continuity,
    reference_continuity_context,
)
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


def _native_files(tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text(
        '(kicad_pcb (layers (0 "F.Cu" signal) (2 "In1.Cu" power) '
        '(4 "In2.Cu" power) (31 "B.Cu" signal)) '
        '(setup (stackup (layer "dielectric 1" (thickness 0.2)))))'
    )
    board.with_suffix(".kicad_pro").write_text("{}")
    policy = tmp_path / "policy.json"
    policy.write_text('{"reference_net_names": ["GND"]}')
    return board, policy


@pytest.mark.parametrize("changed", ["board", "rules", "stackup", "policy"])
def test_context_changes_for_each_material_input(tmp_path, changed):
    board, policy = _native_files(tmp_path)
    before = reference_continuity_context(board, policy)
    target = {
        "board": board,
        "rules": board.with_suffix(".kicad_pro"),
        "stackup": board,
        "policy": policy,
    }[changed]
    original = target.read_text()
    target.write_text(original.replace("0.2", "0.4") if changed == "stackup" else original + "\n")
    after = reference_continuity_context(board, policy)
    assert after != before
    assert (after.stackup_sha256 != before.stackup_sha256) == (changed == "stackup")


@pytest.mark.parametrize("mutate", [False, True])
def test_fresh_native_observer_binds_context_only_when_inputs_unchanged(
    tmp_path, monkeypatch, mutate
):
    board, policy = _native_files(tmp_path)

    def run(command, **kwargs):
        assert kwargs["timeout"] == 60
        assert not Path(command[-1]).exists()
        Path(command[-1]).write_text(
            json.dumps(
                {
                    "reference_continuity": _evidence(
                        copper_layer_count=4,
                        exact_pass_authorized=False,
                        disposition="unsupported_stackup_unverified",
                    )
                }
            )
        )
        if mutate:
            board.with_suffix(".kicad_pro").write_text('{"modified": true}')
        return subprocess.CompletedProcess(command, 0, b"observed", b"")

    monkeypatch.setattr("pcbsmith.kicad.reference_continuity.subprocess.run", run)
    out = tmp_path / "observation"
    if mutate:
        with pytest.raises(ValueError, match="changed board, rules, stackup or policy"):
            observe_reference_continuity(board, policy, out, kicad_python=Path("native-python"))
        assert not (out / "reference-continuity.json").exists()
    else:
        evidence = observe_reference_continuity(
            board, policy, out, kicad_python=Path("native-python")
        )
        assert evidence.context == reference_continuity_context(board, policy)
        with pytest.raises(FileExistsError):
            observe_reference_continuity(board, policy, out, kicad_python=Path("native-python"))
