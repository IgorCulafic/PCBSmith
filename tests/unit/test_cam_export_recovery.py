"""Synthetic recovery guard checks; no native board production or approval."""

import hashlib
import json

import pytest
from tests.unit.test_board_job import Clock
from tests.unit.test_board_job_diagnostic import assessment

from pcbsmith.board_job import BoardJob, ContinuationRequest, JobStopped


@pytest.mark.parametrize("fault", [None, "board", "variants", "exporter", "command", "renew"])
def test_export_repair_keeps_cad_and_allows_one_export(tmp_path, monkeypatch, fault):
    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    clock = Clock()
    job = BoardJob(tmp_path, clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="Synthetic export recovery")
    board, variants, exporter = [
        tmp_path / n for n in ("board.kicad_pcb", "variants.json", "laser_artwork.py")
    ]
    for p in (board, variants, exporter):
        p.write_text("synthetic fixture")
    monkeypatch.setattr("pcbsmith.board_job._IMPLEMENTATION_ROOT", tmp_path)
    command = [
        "pcbsmith.laser_artwork",
        "--board",
        str(board),
        "--variants",
        str(variants),
        "--output",
        str(tmp_path / "failed"),
    ]
    first = job.claim(
        operation="laser-artwork", phase="verify", input_sha256="a" * 64, command=command
    )
    job.finish_attempt(first.token, status="failed", result={}, failure_signature="paste guard")
    job.begin_diagnostic("Inspect exact export guard")
    report = assessment(tmp_path)
    job.complete_diagnostic(report)
    report_file = tmp_path / "assessment.json"
    report_file.write_text(report.model_dump_json())
    new = [*command[:-1], str(tmp_path / "corrected")]
    plan = tmp_path / "cam-plan.json"
    plan.write_text(
        json.dumps(
            dict(
                command=new,
                source_inputs={p.name: sha(p) for p in (board, variants)},
                exporter_sha256=sha(exporter),
            )
        )
    )
    clock.now += 2000
    request = ContinuationRequest(
        predecessor_sha256=sha(job.path),
        assessment_file=report_file.name,
        assessment_sha256=sha(report_file),
        authorization_reference="Explicit fixture export repair",
        seconds=600,
        reserve_seconds=120,
        evaluation_seconds=600,
        build_operations=(),
        blocker_resolution="Qualified synthetic exporter",
        resolved_evidence={plan.name: sha(plan)},
        cam_export_repair_plan=plan.name,
    )
    job.continue_authorized(request)
    if fault in {"board", "variants", "exporter"}:
        {"board": board, "variants": variants, "exporter": exporter}[fault].write_text("changed")
    elif fault == "command":
        new += ["--mirror-x"]
    if fault not in {None, "renew"}:
        with pytest.raises(JobStopped, match="CAM repair"):
            job.claim(operation="laser-artwork", phase="verify", input_sha256="b" * 64, command=new)
        assert len(job.snapshot().attempts) == 1
        return
    second = job.claim(
        operation="laser-artwork", phase="verify", input_sha256="b" * 64, command=new
    )
    job.finish_attempt(
        second.token,
        status="failed" if fault else "passed",
        result={},
        failure_signature="fixture" if fault else None,
    )
    if fault == "renew":
        job.begin_diagnostic("Retain hypothetical second failure")
        job.complete_diagnostic(report)
        clock.now += 2000
        with pytest.raises(JobStopped, match="cannot renew"):
            job.continue_authorized(
                request.model_copy(
                    update={
                        "predecessor_sha256": sha(job.path),
                        "authorization_reference": "another scope",
                    }
                )
            )
    else:
        with pytest.raises(JobStopped, match="inventory|continuation scope"):
            job.claim(
                operation="routing", phase="build", input_sha256="c" * 64, command=("unused",)
            )
    assert len(job.snapshot().attempts) == 2
