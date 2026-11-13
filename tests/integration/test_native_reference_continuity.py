"""Qualify native adjacent reference roles, voids and actual stitch contacts."""

import os
import subprocess
from pathlib import Path

import pytest

from pcbsmith.kicad.final_fill_adapter import refill_and_read_kicad_board
from pcbsmith.kicad.final_fill_connectivity import KiCadFinalFillConnectivityObservation
from pcbsmith.kicad.native_fill_graph import retain_native_fill
from pcbsmith.kicad.native_reference_continuity import evaluate_native_reference_continuity
from pcbsmith.kicad.reference_continuity import ReferenceContinuityEvidence


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_NATIVE_FILL_PROOF"), reason="requires native KiCad"
)
@pytest.mark.parametrize(
    "variant",
    [
        "connected",
        "void",
        "wrong_stitch",
        "disconnected_stitch",
        "distant_stitch",
        "orphan_reference",
        "no_void_allowance",
    ],
)
def test_native_reference_continuity(tmp_path, variant):
    root = Path(os.environ.get("PCBSMITH_NATIVE_FILL_OUTPUT", str(tmp_path))) / variant
    root.mkdir(parents=True, exist_ok=False)
    python = "C:/Program Files/KiCad/10.0/bin/python.exe"
    board = root / "reference.kicad_pcb"

    def run(label, args):
        result = subprocess.run(
            [python, *map(str, args)], capture_output=True, timeout=60, check=False
        )
        (root / f"{label}.stderr.log").write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr.decode(errors="replace")

    run("fixture", ["tests/fixtures/four_layer_reference_native.py", board, variant])
    filled, snapshot = refill_and_read_kicad_board(board, root / "fill")
    contacts = root / "contacts.json"
    run("contacts", ["tools/kicad_final_fill_connectivity_bridge.py", filled, contacts])
    observation = KiCadFinalFillConnectivityObservation.model_validate_json(contacts.read_bytes())
    native = retain_native_fill(filled, snapshot, observation)
    original = filled.read_bytes()
    result = evaluate_native_reference_continuity(filled, board.with_suffix(".policy.json"), native)
    (root / "reference-result.json").write_text(result.model_dump_json(indent=2))
    assert ReferenceContinuityEvidence.model_validate_json(result.model_dump_json()) == result
    assert result.signal_segment_count == 2
    assert result.exact_pass_authorized == (variant == "connected")
    assert result.signal_transition_count == (2 if variant == "wrong_stitch" else 1)
    assert filled.read_bytes() == original
    if variant == "connected":
        assert result.transition_without_nearby_reference_via_count == 0
    elif variant in {"wrong_stitch", "disconnected_stitch", "distant_stitch", "orphan_reference"}:
        assert result.transition_without_nearby_reference_via_count > 0
