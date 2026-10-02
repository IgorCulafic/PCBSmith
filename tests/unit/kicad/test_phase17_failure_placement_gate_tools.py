from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from tools.run_phase17_failure_and_placement_gates import (
    _classifier_source,
    _latest_route,
    _placement_baseline,
    _review_validator_source,
    _summarize,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attempt(root: Path, number: int, *, valid_hash: bool) -> Path:
    attempt = root / "external" / "freerouting-v2.2.4" / f"attempt-{number:02d}"
    attempt.mkdir(parents=True)
    board = attempt / "fixture-freerouting.kicad_pcb"
    board.write_text(f"board-{number}\n", encoding="utf-8")
    evidence = {
        "routed_board_sha256": _sha(board) if valid_hash else "0" * 64,
    }
    (attempt / "route-evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    return board


def test_latest_route_uses_latest_hash_bound_candidate(tmp_path: Path) -> None:
    case = tmp_path / "RC01-fixture"
    first = _attempt(case, 1, valid_hash=True)
    _attempt(case, 2, valid_hash=False)
    third = _attempt(case, 3, valid_hash=True)

    assert _latest_route(case) == third
    assert _latest_route(case) != first


def test_latest_route_fails_when_all_retained_hashes_are_stale(tmp_path: Path) -> None:
    case = tmp_path / "RC01-fixture"
    _attempt(case, 1, valid_hash=False)

    with pytest.raises(FileNotFoundError, match="No retained Freerouting candidate"):
        _latest_route(case)


def test_classifier_source_is_hash_bindable() -> None:
    source = _classifier_source()

    assert source.is_file()
    assert inspect.getsourcefile(_latest_route) != str(source)
    assert Path(inspect.getsourcefile(_latest_route) or "").is_file()
    assert _review_validator_source().is_file()
    runner_source = Path(inspect.getsourcefile(_latest_route) or "").read_text()
    assert "immutable_copy_sha256" not in runner_source
    assert "observed_board_sha256" in runner_source


def test_bridge_never_uses_layerless_via_width() -> None:
    source = Path("tools/kicad_board_feasibility_bridge.py").read_text(encoding="utf-8")
    via_branch = source.split("if isinstance(item, pcbnew.PCB_VIA):", 1)[1].split(
        "if isinstance(item, pcbnew.PCB_TRACK):", 1
    )[0]

    observe_source = source.split("def observe(", 1)[1]
    assert observe_source.count('"board_identity": _board_identity(board)') == 1

    assert "GetWidth(" not in via_branch
    assert "GetBoundingBox(" not in via_branch
    assert "GetFrontWidth(" not in source
    assert "APP_ASSERT_DIALOG" not in source
    assert "SetAssertMode(wx.APP_ASSERT_EXCEPTION)" in source
    assert "wx.Image.CleanUpHandlers()" in source
    assert ".get(_uuid(member), _semantic_base(member))" not in source
    assert "footprint is parent" not in source
    assert "other is pad" not in source


def test_placement_baseline_requires_matching_source_and_bridge(tmp_path: Path) -> None:
    case = tmp_path / "boards" / "RC01-fixture"
    case.mkdir(parents=True)
    placement = case / "fixture-placement.kicad_pcb"
    placement.write_text("placement\n", encoding="utf-8")
    output = tmp_path / "evidence"
    run = output / "cases" / case.name / "placement" / "revision-current"
    run.mkdir(parents=True)
    result = {
        "execution_complete": True,
        "source_board_sha256": _sha(placement),
        "bridge_sha256": "a" * 64,
    }
    (run / "gate-result.json").write_text(json.dumps(result), encoding="utf-8")
    observation = {"board_identity": {"footprint_pose_fingerprint": "b" * 64}}
    (run / "physical-observation.json").write_text(json.dumps(observation), encoding="utf-8")

    retained, observed = _placement_baseline(case, output, "a" * 64)

    assert retained == result
    assert observed == observation
    with pytest.raises(FileNotFoundError, match="no current hash-bound placement baseline"):
        _placement_baseline(case, output, "c" * 64)


def test_summary_is_mode_neutral_and_recomputes_counts() -> None:
    results = [
        {
            "two_layer_feasibility": "feasible_current_placement",
            "execution_complete": True,
            "failure_reconciliation_complete": True,
            "placement_gate_passed": True,
        },
        {
            "two_layer_feasibility": "indeterminate",
            "execution_complete": False,
            "failure_reconciliation_complete": False,
            "placement_gate_passed": False,
        },
    ]

    summary = _summarize(results)

    assert summary["attempted"] == 2
    assert summary["execution_complete"] == 1
    assert summary["reconciliation_complete"] == 1
    assert summary["placement_gate_passed"] == 1
    assert summary["feasibility_counts"] == {
        "feasible_current_placement": 1,
        "indeterminate": 1,
    }
