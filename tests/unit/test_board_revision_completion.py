"""Fault injection tests; native acceptance is verified by retained CLI runs."""

from __future__ import annotations

import json

import pytest
from tests.unit import test_board_revision as fixtures

import pcbsmith.board_revision as revision
from pcbsmith.board_revision_workflow import NativeRevisionRegion
from pcbsmith.local_routing_repair import RoutingRepairRegion

source = fixtures.source
checks = fixtures.checks
request = fixtures.request


def test_shared_stages_bound_expansion_and_unevaluated_metrics(source, checks, tmp_path):
    req = request(source).model_copy(
        update={
            "region": NativeRevisionRegion(
                initial_region=RoutingRepairRegion(
                    x_min_mm=0, y_min_mm=0, x_max_mm=1.1, y_max_mm=2, expansion_index=0
                ),
                maximum_expansions=1,
                expansion_margin_mm=1,
            )
        }
    )
    output = tmp_path / "candidate"
    revision.create_board_revision(board=source, request=req, output=output)
    checkpoint = json.loads((output / "workflow/checkpoint.json").read_bytes())
    assert [s["step_id"] for s in checkpoint["step_results"]] == ["IF1", "IF2", "IF3", "IF4", "IF5"]
    attempts = json.loads((output / "workflow/IF2.json").read_bytes())["run"]["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["protected_change_count"] > 0
    assert attempts[1]["protected_change_count"] == 0
    assert all(a["drc_violation_count"] is None for a in attempts)
    assert all(a["validation_scope"] == "geometry_envelope" for a in attempts)
    assert revision.replay_board_revision(output)
    obligations = json.loads((output / "semantic-obligations.json").read_bytes())
    assert obligations["qualification_accepted"] is False
    assert obligations["decisions"] and not obligations["decisions"][0]["accepted"]


def test_region_exhaustion_and_protected_region_stop_before_native(source, checks, tmp_path):
    region = RoutingRepairRegion(
        x_min_mm=0, y_min_mm=0, x_max_mm=1.1, y_max_mm=2, expansion_index=0
    )
    req = request(source).model_copy(update={"region": NativeRevisionRegion(initial_region=region)})
    with pytest.raises(ValueError, match="expansions exhausted"):
        revision.create_board_revision(board=source, request=req, output=tmp_path / "exhausted")
    protected = request(source).model_copy(update={"protected_regions": (region,)})
    with pytest.raises(ValueError, match="protected"):
        revision.create_board_revision(
            board=source, request=protected, output=tmp_path / "protected"
        )
    assert not checks


def test_interrupted_native_stage_resumes_without_redoing_completed_stages(
    source, checks, tmp_path, monkeypatch
):
    req = request(source)
    output = tmp_path / "candidate"
    real_checks = revision._native_checks

    def interrupt(board, output, **kwargs):
        output.mkdir()
        (output / "partial.json").write_text("interrupted test")
        raise KeyboardInterrupt

    monkeypatch.setattr(revision, "_native_checks", interrupt)
    with pytest.raises(KeyboardInterrupt):
        revision.create_board_revision(board=source, request=req, output=output)
    before = (output / "workflow/IF1.json").read_bytes()
    assert not (output / "failure.json").exists()
    monkeypatch.setattr(revision, "_native_checks", real_checks)
    from pcbsmith.cli import main

    # This legacy synthetic checkpoint tests native resume, not job authorization.
    monkeypatch.setattr("pcbsmith.board_job.require_worker", lambda *_: None)

    assert (
        main(
            [
                "production-edit-board",
                str(source),
                "--request",
                str(output / "request.json"),
                "--output",
                str(output),
                "--resume",
            ]
        )
        == 0
    )
    candidate = output / "design" / source.name
    assert (output / "workflow/IF1.json").read_bytes() == before
    assert list(output.glob("interrupted-checks-*/partial.json"))
    assert len(checks) == 1
    assert revision.replay_board_revision(output)[0] == candidate


@pytest.mark.parametrize("target", ["workflow/IF1.json", "delta.json", "design/board.kicad_pcb"])
def test_resume_rejects_changed_stage_evidence(source, tmp_path, monkeypatch, target):
    output = tmp_path / "candidate"
    req = request(source)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(revision, "_native_checks", interrupt)
    with pytest.raises(KeyboardInterrupt):
        revision.create_board_revision(board=source, request=req, output=output)
    path = output / target
    path.write_text("{}" if target.endswith(".json") else "(kicad_pcb)")
    with pytest.raises(ValueError, match="stale"):
        revision.create_board_revision(board=source, request=req, output=output, resume=True)


def test_interrupted_apply_requires_recovery_and_protects_manual_work(
    source, checks, tmp_path, monkeypatch
):
    from pcbsmith.operations import file_transaction as tx

    output = tmp_path / "candidate"
    original = source.read_bytes()
    revision.create_board_revision(board=source, request=request(source), output=output)
    real_write = tx.atomic_write

    def interrupt(path, payload):
        if path == source.parent / revision.LEDGER:
            raise KeyboardInterrupt
        return real_write(path, payload)

    monkeypatch.setattr(tx, "atomic_write", interrupt)
    with pytest.raises(KeyboardInterrupt):
        revision.apply_board_revision(board=source, directory=output)
    with pytest.raises(tx.FileTransactionError, match="Incomplete"):
        revision.inspect_board_revision(source)
    monkeypatch.setattr(tx, "atomic_write", real_write)
    candidate = source.read_bytes()
    source.write_bytes(b"manual work after interruption")
    with pytest.raises(tx.FileTransactionError):
        tx.recover_project_files(source.parent)
    assert source.read_bytes() == b"manual work after interruption"
    source.write_bytes(candidate)
    assert tx.recover_project_files(source.parent)
    assert source.read_bytes() == original
    assert not (source.parent / revision.LEDGER).exists()


def test_local_sheets_models_and_custom_rules_are_bound(source, tmp_path):
    from pcbsmith.kicad.project_dependencies import retain_native_project

    nested = source.parent / "sheets"
    nested.mkdir()
    (nested / "child.kicad_sch").write_text("(kicad_sch)")
    source.with_suffix(".kicad_sch").write_text(
        '(kicad_sch (sheet (property "Sheetfile" "sheets/child.kicad_sch")))'
    )
    source.with_suffix(".kicad_dru").write_text("(version 1)")
    hashes = retain_native_project(source, tmp_path / "retained")
    assert {"sheets/child.kicad_sch", "test.step", "board.kicad_dru"} <= hashes.keys()
    (nested / "child.kicad_sch").write_text(
        '(kicad_sch (sheet (property "Sheetfile" "${KIPRJMOD}/board.kicad_sch")))'
    )
    with pytest.raises(ValueError, match="cyclic"):
        retain_native_project(source, tmp_path / "cycle")


def test_candidate_save_failure_retains_rejection_and_preserves_source(
    source, checks, tmp_path, monkeypatch
):
    original = source.read_bytes()
    output = tmp_path / "candidate"
    real_write = revision.atomic_write

    def fail_candidate(path, payload):
        if path == output / "design" / source.name:
            raise OSError("injected candidate save failure")
        return real_write(path, payload)

    monkeypatch.setattr(revision, "atomic_write", fail_candidate)
    with pytest.raises(OSError, match="candidate save failure"):
        revision.create_board_revision(board=source, request=request(source), output=output)
    assert source.read_bytes() == original
    assert not checks
    assert (output / "workflow/IF2-failure.json").is_file()
    assert json.loads((output / "failure.json").read_bytes())["status"] == "failed"


@pytest.fixture(autouse=True)
def isolated_producer_contracts(monkeypatch):
    """Synthetic inner-contract tests; real job authorization is tested separately."""
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
