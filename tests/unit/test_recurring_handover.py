"""Prospective handover controls; synthetic cases do not approve real boards."""

import argparse
import json
import math
from types import SimpleNamespace

import pytest
from tests.unit.test_manufacturing_lineage import package_fixture
from tests.unit.test_production_readiness import readiness_fixture

from pcbsmith.board_handover import _require_recurring_lineage
from pcbsmith.laser_artwork import removal_svg, verify_actual_copper_isolation
from pcbsmith.mandatory_review import (
    MandatoryReview,
    require_current_native_checks,
    require_mandatory_review,
    require_recurring_deliverables,
)
from pcbsmith.manufacturing_lineage import file_sha256


@pytest.mark.parametrize("role", ["interactive_bom", "floorplan", "floorplan_preview"])
def test_new_requirements_cannot_be_omitted_but_old_record_is_readable(tmp_path, role):
    _, root, request = readiness_fixture(tmp_path)
    policy = require_mandatory_review(request.predesign, root)
    require_recurring_deliverables(policy)
    data = policy.model_dump()
    del data["deliverables"][role]
    legacy = MandatoryReview.model_validate(data)
    with pytest.raises(ValueError, match="recurring deliverables"):
        require_recurring_deliverables(legacy)


@pytest.mark.parametrize("role", ["floorplan", "floorplan_preview"])
def test_handover_vector_must_be_the_reviewed_bytes(tmp_path, role):
    board, root, request = readiness_fixture(tmp_path)
    evidence = "floorplan.floorplan." + ("svg" if role == "floorplan" else "png")
    bundle = SimpleNamespace(evidence_files={evidence: SimpleNamespace(sha256="a" * 64)})
    _require_recurring_lineage(bundle, board, {role: {"sha256": "a" * 64}})
    with pytest.raises(ValueError, match="reviewed vector"):
        _require_recurring_lineage(bundle, board, {role: {"sha256": "b" * 64}})
    with pytest.raises(ValueError, match="reviewed vector"):
        _require_recurring_lineage(
            request.predesign.model_copy(update={"evidence_files": {}}),
            board,
            {role: {"sha256": "a" * 64}},
        )


def test_handover_ibom_requires_current_receipt(tmp_path):
    kwargs = package_fixture(tmp_path)
    board = kwargs["board_file"]
    html = next(
        p
        for role, paths in kwargs["source_artifacts"].items()
        if role.value == "interactive_bom"
        for p in paths
    )
    bundle = SimpleNamespace(evidence_files={})
    files = {"interactive_bom": {"path": str(html)}}
    _require_recurring_lineage(bundle, board, files)
    html.write_bytes(html.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="lineage"):
        _require_recurring_lineage(bundle, board, files)


def circle_case(tmp_path, nominal):
    board = tmp_path / "circle.kicad_pcb"
    board.write_text(
        '(kicad_pcb (footprint "test" (layer "F.Cu") (at 5 5)'
        ' (pad "1" smd circle (at 0 0) (size 1.5 1.5) (layers "F.Cu")))'
        ' (gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts")))'
    )
    points = [
        (5 + 0.75 * math.cos(i * math.tau / 28), 5 + 0.75 * math.sin(i * math.tau / 28))
        for i in range(28)
    ]
    path = "M " + " L ".join(f"{x:.8f},{y:.8f}" for x, y in points) + " Z"
    source = (
        '<svg viewBox="0.0000 0.0000 10 10">'
        '<path style="fill:#000000;fill-rule:evenodd;stroke:none" '
        f'd="{path}"/></svg>'
    ).encode()
    removal, _ = removal_svg(
        source, (0, 0, 10, 10), floating_clearance_mm=nominal, retained_edge_clearance_mm=2
    )
    return board, removal


def test_nominal_svg_clearance_does_not_relax_actual_copper_requirement(tmp_path):
    board, removal = circle_case(tmp_path, 0.8)
    with pytest.raises(ValueError, match="Actual copper isolation"):
        verify_actual_copper_isolation(
            board, removal, minimum_clearance_mm=0.8, minimum_edge_clearance_mm=2
        )
    board, removal = circle_case(tmp_path, 0.81)
    result = verify_actual_copper_isolation(
        board, removal, minimum_clearance_mm=0.8, minimum_edge_clearance_mm=2
    )
    assert 0.806 < result["actual_clearance_lower_bound_mm"] < 0.808
    assert result["circular_enclosure_max_error_mm"] < 0.000057
    assert result["retained_edge_clearance_mm"] == pytest.approx(2)
    assert result["board_sha256"] == file_sha256(board)


@pytest.mark.parametrize("change", ["zone", "arc", "via", "graphic", "stale_pad"])
def test_actual_isolation_blocks_unsupported_or_changed_copper(tmp_path, change):
    board, removal = circle_case(tmp_path, 0.81)
    text = board.read_text()
    if change == "stale_pad":
        text = text.replace("1.5 1.5", "2 2")
    else:
        node = '(gr_line (layer "F.Cu"))' if change == "graphic" else f"({change})"
        text = text[:-1] + node + ")"
    board.write_text(text)
    with pytest.raises(ValueError):
        verify_actual_copper_isolation(
            board, removal, minimum_clearance_mm=0.8, minimum_edge_clearance_mm=2
        )


def test_final_cli_rejects_missing_checks_before_renderer(monkeypatch):
    from pcbsmith.cli import _cmd_visual_review

    monkeypatch.setattr(
        "pcbsmith.cli.generate_visual_review_package",
        lambda **kw: pytest.fail("renderer was called"),
    )
    with pytest.raises(ValueError, match="native-checks"):
        _cmd_visual_review(argparse.Namespace(stage="final"))


@pytest.mark.parametrize(
    "fault", [None, "board", "schematic", "project", "report", "failed_process"]
)
def test_cheap_native_precheck_rejects_changed_inputs(tmp_path, fault):
    board = tmp_path / "fixture.kicad_pcb"
    for suffix in (".kicad_pcb", ".kicad_sch", ".kicad_pro"):
        board.with_suffix(suffix).write_text("synthetic input")
    for kind in ("erc", "drc"):
        path = tmp_path / f"{kind}.json"
        data = {
            "$schema": f"https://schemas.kicad.org/{kind}.v1.json",
            "source": board.with_suffix(".kicad_sch").name if kind == "erc" else board.name,
            "kicad_version": "10.0-test",
        }
        data.update(
            {"sheets": [{"violations": []}]}
            if kind == "erc"
            else {"violations": [], "unconnected_items": [], "schematic_parity": []}
        )
        path.write_text(json.dumps(data))
        process = {
            "command": [
                "kicad-cli",
                "sch" if kind == "erc" else "pcb",
                kind,
                "--severity-all",
                "--schematic-parity",
            ],
            "returncode": 0,
            "report_sha256": file_sha256(path),
            "input_sha256s": {
                str(board.with_suffix(s)): file_sha256(board.with_suffix(s))
                for s in (".kicad_pcb", ".kicad_sch", ".kicad_pro")
            },
        }
        path.with_suffix(".process.json").write_text(json.dumps(process))
    if fault in {"board", "schematic", "project"}:
        board.with_suffix(
            {"board": ".kicad_pcb", "schematic": ".kicad_sch", "project": ".kicad_pro"}[fault]
        ).write_text("changed")
    elif fault == "report":
        with (tmp_path / "drc.json").open("a") as f:
            f.write(" ")
    elif fault == "failed_process":
        path = tmp_path / "erc.process.json"
        data = json.loads(path.read_text())
        data["returncode"] = 1
        path.write_text(json.dumps(data))
    if fault:
        with pytest.raises(ValueError):
            require_current_native_checks(board, tmp_path)
    else:
        assert set(require_current_native_checks(board, tmp_path)) == {"erc", "drc"}


def test_rotated_native_pad_matches_cam_without_axis_assumptions(tmp_path):
    board = tmp_path / "rotated.kicad_pcb"
    board.write_text(
        '(kicad_pcb (footprint "test" (layer "F.Cu") (at 5 5 90)'
        ' (pad "1" smd rect (at 2 0 90) (size 2 1) (layers "F.Cu")))'
        ' (gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts")))'
    )
    native = (
        b'<svg viewBox="0.0000 0.0000 10 10">'
        b'<path style="fill:#000000;fill-rule:evenodd;stroke:none" '
        b'd="M 4.5,2 L 5.5,2 5.5,4 4.5,4 Z"/></svg>'
    )
    removal, _ = removal_svg(native, (0, 0, 10, 10), floating_clearance_mm=0.8)
    result = verify_actual_copper_isolation(
        board, removal, minimum_clearance_mm=0.8, minimum_edge_clearance_mm=0
    )
    assert result["actual_clearance_lower_bound_mm"] >= 0.8


def test_new_publication_blocks_omitted_ibom_before_rendering(tmp_path):
    from pcbsmith.production_generators import _guarded_readiness_review
    from pcbsmith.production_readiness import ReadinessEvidenceFile

    board, root, request = readiness_fixture(tmp_path)
    policy = require_mandatory_review(request.predesign, root)
    data = policy.model_dump(mode="json")
    del data["deliverables"]["interactive_bom"]
    path = root / "mandatory-review.json"
    path.write_text(json.dumps(data))
    bundle = request.predesign.model_copy(
        update={
            "evidence_files": {
                **request.predesign.evidence_files,
                "mandatory-review": ReadinessEvidenceFile(
                    relative_path=path.name, sha256=file_sha256(path)
                ),
            }
        }
    )
    with pytest.raises(ValueError, match="recurring deliverables"):
        _guarded_readiness_review(
            request=request.model_copy(update={"predesign": bundle}),
            artifact_root=root,
            project_id=request.predesign.approval.project_id,
            board_relative_path=board.name,
            board_payload=board.read_bytes(),
            support_payloads={},
            review_generator=lambda *args: pytest.fail("Renderer called"),
        )
