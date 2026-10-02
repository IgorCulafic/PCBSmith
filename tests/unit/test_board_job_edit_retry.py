from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from pcbsmith.board_job import ContinuationRequest, JobStopped, _validate_edit_input_retry
from pcbsmith.board_revision import BoardRevisionRequest


@pytest.fixture
def selector_failure(tmp_path):
    root = tmp_path.resolve()
    board = root / "source/board.kicad_pcb"
    output = root / "failed"
    payload = b"synthetic unchanged source"
    digest = hashlib.sha256(payload).hexdigest()
    for path in (board, output / "before/board.kicad_pcb", output / "design/board.kicad_pcb"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    old = BoardRevisionRequest(
        source_inputs={"board.kicad_pcb": digest},
        rationale="synthetic request",
        validation_stage="unrouted_annotations",
        edits=[{"kind": "reference", "target": "nested-id", "position_mm": [0, -3]}],
    )
    (output / "request.json").write_text(old.model_dump_json())
    failure = {
        "status": "failed",
        "source_inputs": old.source_inputs,
        "error": "ValueError: edit target is missing or ambiguous: nested-id",
    }
    (output / "failure.json").write_text(json.dumps(failure))
    new = old.model_dump()
    new["edits"][0]["target"] = "parent-id"
    corrected = root / "corrected.json"
    corrected.write_text(BoardRevisionRequest.model_validate(new).model_dump_json())
    request = ContinuationRequest(
        predecessor_sha256="a" * 64,
        assessment_file="assessment.json",
        assessment_sha256="b" * 64,
        authorization_reference="new explicit synthetic decision",
        seconds=600,
        reserve_seconds=120,
        build_operations=("edit",),
        blocker_resolution="corrected selector only",
        resolved_evidence={
            str(path.relative_to(root).as_posix()): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (corrected, output / "failure.json")
        },
        retry_failed_operations={"edit": "failed-token"},
        edit_retry_request="corrected.json",
    )
    command = (
        "pcbsmith.cli",
        "production-edit-board",
        str(board),
        "--request",
        str(output / "request.json"),
        "--output",
        str(output),
    )
    attempt = SimpleNamespace(command=command)
    return root, attempt, request


def test_selector_retry_replays_actual_unchanged_files(selector_failure):
    root, attempt, request = selector_failure
    _validate_edit_input_retry(root, attempt, request)
    command = (
        *attempt.command[:3],
        "--request",
        str(root / "corrected.json"),
        "--output",
        str(root / "new"),
    )
    _validate_edit_input_retry(root, attempt, request, command)


@pytest.mark.parametrize(
    "changed",
    [
        "source/board.kicad_pcb",
        "failed/before/board.kicad_pcb",
        "failed/design/board.kicad_pcb",
        "corrected.json",
        "failed/failure.json",
    ],
)
def test_selector_retry_rejects_changed_evidence(selector_failure, changed):
    root, attempt, request = selector_failure
    (root / changed).write_bytes(b"changed")
    with pytest.raises(JobStopped):
        _validate_edit_input_retry(root, attempt, request)


def test_selector_retry_rejects_already_started_mutation(selector_failure):
    root, attempt, request = selector_failure
    (root / "failed/workflow").mkdir()
    with pytest.raises(JobStopped, match="before mutation"):
        _validate_edit_input_retry(root, attempt, request)


def test_selector_retry_cannot_change_geometry_even_when_hash_bound(selector_failure):
    root, attempt, request = selector_failure
    path = root / "corrected.json"
    data = json.loads(path.read_bytes())
    data["edits"][0]["position_mm"] = [5, 6]
    path.write_text(json.dumps(data))
    request.resolved_evidence["corrected.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(JobStopped, match="only selectors"):
        _validate_edit_input_retry(root, attempt, request)


def test_selector_retry_rejects_different_command(selector_failure):
    root, attempt, request = selector_failure
    with pytest.raises(JobStopped, match="authorized request"):
        _validate_edit_input_retry(root, attempt, request, attempt.command)


def test_selector_retry_requires_explicit_request_binding(selector_failure):
    _, _, request = selector_failure
    data = request.model_dump()
    data.pop("edit_retry_request")
    with pytest.raises(ValueError, match="exact corrected request"):
        ContinuationRequest.model_validate(data)
