from __future__ import annotations

import json
from pathlib import Path

from tools.extract_phase17_series_escape_feedback import extract_feedback
from tools.route_phase17_corpus_freerouting import (
    _drc_counts,
    _freerouting_compatibility_error,
    _freerouting_crash,
    _freerouting_version,
    _next_attempt_directory,
)


def test_next_attempt_migrates_legacy_run_without_deleting_it(tmp_path: Path) -> None:
    root = tmp_path / "freerouting-v2.2.4"
    root.mkdir()
    (root / "route-evidence.json").write_text("{}\n", encoding="utf-8")
    (root / "interchange").mkdir()
    (root / "interchange" / "input.dsn").write_text("dsn\n", encoding="utf-8")

    attempt = _next_attempt_directory(root)

    assert attempt == root / "attempt-02"
    assert (root / "attempt-01" / "route-evidence.json").exists()
    assert (root / "attempt-01" / "interchange" / "input.dsn").exists()
    assert attempt.is_dir()


def test_next_attempt_appends_after_existing_attempts(tmp_path: Path) -> None:
    root = tmp_path / "freerouting-v2.2.4"
    (root / "attempt-01").mkdir(parents=True)
    (root / "attempt-02").mkdir()

    attempt = _next_attempt_directory(root)

    assert attempt == root / "attempt-03"
    assert (root / "attempt-01").is_dir()
    assert (root / "attempt-02").is_dir()


def test_drc_counts_separates_violations_from_unconnected(tmp_path: Path) -> None:
    report = tmp_path / "drc.json"
    report.write_text(
        json.dumps(
            {
                "violations": [
                    {"type": "clearance"},
                    {"type": "shorting_items"},
                ],
                "unconnected_items": [{"description": "one"}],
            }
        ),
        encoding="utf-8",
    )

    violations, unconnected, types = _drc_counts(report)

    assert violations == 2
    assert unconnected == 1
    assert types == ("clearance", "shorting_items")


def test_series_escape_feedback_extracts_only_u1_to_numeric_series_opens(
    tmp_path: Path,
) -> None:
    root = tmp_path / "corpus"
    attempt = (
        root
        / "boards"
        / "RT40-medium-controller"
        / "external"
        / "freerouting-v2.2.4"
        / "attempt-01"
    )
    attempt.mkdir(parents=True)
    (root / "freerouting-summary.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "RT40",
                        "attempt_directory": "external/freerouting-v2.2.4/attempt-01",
                        "source_board_sha256": "a" * 64,
                        "routed_board_sha256": "b" * 64,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (attempt / "drc.json").write_text(
        json.dumps(
            {
                "unconnected_items": [
                    {
                        "items": [
                            {"description": "Pad 8 [SIG7_A] of U1 on F.Cu"},
                            {"description": "Pad 1 [SIG7_A] of R7 on F.Cu"},
                        ]
                    },
                    {
                        "items": [
                            {"description": "Zone [GND] on B.Cu, priority 0"},
                            {"description": "Pad 48 [GND] of U1 on F.Cu"},
                        ]
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = extract_feedback(root)

    assert payload["targets"] == {"RT40": ["SIG7_A"]}
    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["drc_report_sha256"]


def test_freerouting_crash_classifies_polyline_stack_overflow(tmp_path: Path) -> None:
    stdout = tmp_path / "router.stdout.log"
    stderr = tmp_path / "router.stderr.log"
    stdout.write_text("normal preamble\n", encoding="utf-8")
    stderr.write_text(
        "java.lang.StackOverflowError\n"
        "\tat app.freerouting.board.PolylineTrace.combine(PolylineTrace.java:177)\n",
        encoding="utf-8",
    )

    assert _freerouting_crash(stdout, stderr) == {
        "kind": "java_stack_overflow",
        "subsystem": "PolylineTrace.combine",
        "signature": "java.lang.StackOverflowError:PolylineTrace.combine",
    }


def test_freerouting_version_is_derived_from_pinned_jar_name() -> None:
    assert _freerouting_version(Path("freerouting-2.1.0.jar")) == "2.1.0"


def test_freerouting_224_is_blocked_before_launch_for_retained_wiring(
    tmp_path: Path,
) -> None:
    board = tmp_path / "retained.kicad_pcb"
    board.write_text(
        "(kicad_pcb (version 20240108) (segment (start 1 1) (end 2 2)))\n",
        encoding="utf-8",
    )

    error = _freerouting_compatibility_error("2.2.4", board)

    assert error is not None
    assert "StackOverflowError" in error
    assert _freerouting_compatibility_error("2.3.0", board) is None
