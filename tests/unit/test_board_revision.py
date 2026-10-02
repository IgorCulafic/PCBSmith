from __future__ import annotations

import json

import pytest
from tests.unit.kicad.test_native_edits import BOARD

import pcbsmith.board_revision as revision
from pcbsmith.board_revision import LEDGER, BoardRevisionRequest
from pcbsmith.kicad.native_edits import NativeEdit


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    board = folder / "board.kicad_pcb"
    board.write_bytes(BOARD)
    (folder / "test.step").write_text("synthetic test-only model")
    board.with_suffix(".kicad_sch").write_text("(kicad_sch)")
    board.with_suffix(".kicad_pro").write_text("{}")
    (folder / "parts.kicad_sym").write_text("(kicad_symbol_lib)")
    (folder / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "local") (uri "${KIPRJMOD}/parts.kicad_sym")))'
    )
    return board


def request(board):
    return BoardRevisionRequest(
        source_inputs=revision.inspect_board_revision(board)["source_inputs"],
        rationale="Requested label move",
        edits=(NativeEdit(kind="text", target="text", position_mm=(1.5, 1)),),
    )


@pytest.fixture
def checks(monkeypatch):
    calls = []

    # These are test-only native check substitutes. Live KiCad proofs are retained separately.
    def run(board, output, **kwargs):
        output.mkdir(parents=True)
        for name in ("erc.json", "drc.json", "summary.json"):
            (output / name).write_text('{"synthetic_unit_test_only": true}')
        calls.append(board)
        return {"passed": True}

    monkeypatch.setattr(revision, "_native_checks", run)
    return calls


def test_candidate_replays_without_source_mutation_and_apply_checks_again(source, checks, tmp_path):
    req = request(source)
    output = tmp_path / "candidate"
    candidate = revision.create_board_revision(board=source, request=req, output=output)
    assert source.read_bytes() == BOARD
    assert revision.replay_board_revision(output)[0] == candidate
    assert len(checks) == 1
    revision.apply_board_revision(board=source, directory=output)
    assert len(checks) == 2
    assert source.read_bytes() == candidate.read_bytes()
    journal = json.loads((source.parent / LEDGER).read_bytes())
    assert journal["edits"][0]["production_accepted"] is False
    assert journal["edits"][0]["request"] == req.model_dump(mode="json")
    assert (output / "before" / source.name).read_bytes() == BOARD
    with pytest.raises(ValueError, match="conflicts"):
        revision.apply_board_revision(board=source, directory=output)


@pytest.mark.parametrize("file", ["board.kicad_pcb", "board.kicad_pro", "parts.kicad_sym"])
def test_source_conflicts_block_before_checks(source, checks, tmp_path, file):
    req = request(source)
    (source.parent / file).write_bytes(b"new user work")
    with pytest.raises(ValueError, match="source changed"):
        revision.create_board_revision(board=source, request=req, output=tmp_path / "candidate")
    assert not checks
    assert not (tmp_path / "candidate").exists()


def test_missing_dependency_binding_is_not_accepted(source, checks, tmp_path):
    req = request(source)
    assert "parts.kicad_sym" in req.source_inputs
    del req.source_inputs["parts.kicad_sym"]
    with pytest.raises(ValueError, match="complete current input closure"):
        revision.create_board_revision(board=source, request=req, output=tmp_path / "candidate")
    assert not checks
    assert (tmp_path / "candidate/failure.json").is_file()


@pytest.mark.parametrize(
    "target",
    [
        "design/board.kicad_pcb",
        "design/board.kicad_pro",
        "design/parts.kicad_sym",
        "before/board.kicad_pcb",
        "checks/drc.json",
        "request.json",
        "delta.json",
    ],
)
def test_tampering_cannot_apply(source, checks, tmp_path, target):
    output = tmp_path / "candidate"
    revision.create_board_revision(board=source, request=request(source), output=output)
    path = output / target
    path.write_bytes(path.read_bytes() + b" ")
    # Parser-equivalent whitespace is still stale evidence except delta JSON,
    # whose data is deliberately compared semantically rather than byte-wise.
    if target == "delta.json":
        path.write_text("{}")
    with pytest.raises(ValueError):
        revision.apply_board_revision(board=source, directory=output)
    assert source.read_bytes() == BOARD


def test_a_positive_status_does_not_replace_live_checks(source, checks, tmp_path, monkeypatch):
    output = tmp_path / "candidate"
    revision.create_board_revision(board=source, request=request(source), output=output)
    monkeypatch.setattr(revision, "_native_checks", lambda *a, **k: {"passed": False})
    with pytest.raises(ValueError, match="current native checks"):
        revision.apply_board_revision(board=source, directory=output)
    assert source.read_bytes() == BOARD
    assert not (source.parent / LEDGER).exists()


def test_new_dependency_and_concurrent_ledger_prevent_apply(source, checks, tmp_path, monkeypatch):
    output = tmp_path / "candidate"
    revision.create_board_revision(board=source, request=request(source), output=output)

    def concurrent(*args, **kwargs):
        ledger = source.parent / LEDGER
        ledger.parent.mkdir()
        ledger.write_text('{"external": true}')
        return {"passed": True}

    monkeypatch.setattr(revision, "_native_checks", concurrent)
    with pytest.raises(ValueError, match="changed during apply"):
        revision.apply_board_revision(board=source, directory=output)
    assert source.read_bytes() == BOARD
    assert json.loads((source.parent / LEDGER).read_text()) == {"external": True}


def test_failed_checks_and_noop_never_gain_acceptance(source, checks, tmp_path, monkeypatch):
    output = tmp_path / "failed"
    monkeypatch.setattr(revision, "_native_checks", lambda *a, **k: {"passed": False})

    # Keep the normal retained-file contract while injecting a failing result.
    def failed(board, directory, **kwargs):
        directory.mkdir()
        return {"passed": False}

    monkeypatch.setattr(revision, "_native_checks", failed)
    revision.create_board_revision(board=source, request=request(source), output=output)
    receipt = json.loads((output / "revision.json").read_bytes())
    assert receipt["status"] == "blocked_candidate" and receipt["production_accepted"] is False
    with pytest.raises(ValueError, match="digitally checked"):
        revision.apply_board_revision(board=source, directory=output)
    req = request(source).model_copy(
        update={"edits": (NativeEdit(kind="text", target="text", position_mm=(1, 1)),)}
    )
    no_op = revision.create_board_revision(board=source, request=req, output=tmp_path / "noop")
    assert no_op.read_bytes() == BOARD
    assert json.loads((tmp_path / "noop/revision.json").read_bytes())["status"] == "no_change"


def test_native_failure_is_retained_and_original_is_untouched(source, tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("KiCad not available in synthetic test")

    monkeypatch.setattr(revision, "_native_checks", unavailable)
    with pytest.raises(RuntimeError, match="not available"):
        revision.create_board_revision(
            board=source, request=request(source), output=tmp_path / "candidate"
        )
    failure = json.loads((tmp_path / "candidate/failure.json").read_bytes())
    assert failure["status"] == "failed" and failure["production_accepted"] is False
    assert failure["source_inputs"] == request(source).source_inputs
    assert source.read_bytes() == BOARD


def test_inspection_output_cannot_overwrite_the_source(source, capsys, monkeypatch):
    from pcbsmith.cli import main

    # Keep this isolated overwrite test past the separately tested CLI job gate.
    monkeypatch.setattr("pcbsmith.board_job.require_worker", lambda *_: None)

    assert main(["production-inspect-board", str(source), "--output", str(source)]) == 2
    assert "fresh and outside" in capsys.readouterr().err
    assert source.read_bytes() == BOARD


def test_requested_move_and_optimization_have_distinct_objectives(
    source, checks, tmp_path, monkeypatch
):
    # Isolate objective evaluation from separately tested vector preconditions.
    monkeypatch.setattr(revision, "_revision_floorplan", lambda *_: None)
    # The synthetic fixture has one component, so its generic pairwise cost is unchanged.
    edits = (NativeEdit(kind="component", target="R1", position_mm=(10, 11)),)
    requested = request(source).model_copy(update={"edits": edits})
    revision.create_board_revision(board=source, request=requested, output=tmp_path / "requested")
    optimized = requested.model_copy(update={"intent": "optimize"})
    with pytest.raises(ValueError, match="did not improve"):
        revision.create_board_revision(
            board=source, request=optimized, output=tmp_path / "optimized"
        )
    assert source.read_bytes() == BOARD


def test_unrouted_pose_revision_replays_and_preserves_source(source, checks, tmp_path, monkeypatch):
    # This test isolates delta preservation; vector and real native checks have separate gates.
    monkeypatch.setattr(revision, "_revision_floorplan", lambda *_: None)
    before = b"\n".join(
        line for line in BOARD.splitlines() if not line.lstrip().startswith((b"(segment", b"(via"))
    )
    source.write_bytes(before)
    req = BoardRevisionRequest(
        source_inputs=revision.inspect_board_revision(source)["source_inputs"],
        rationale="Explicit pre-route pose correction",
        validation_stage="unrouted_placement",
        edits=(NativeEdit(kind="component", target="R1", position_mm=(10, 11), rotation_deg=180),),
    )
    output = tmp_path / "pose"
    candidate = revision.create_board_revision(board=source, request=req, output=output)
    assert source.read_bytes() == before
    assert revision.replay_board_revision(output)[0] == candidate
    revision.apply_board_revision(board=source, directory=output)
    assert source.read_bytes() == candidate.read_bytes()
    assert len(checks) == 2
    revision._require_unrouted_annotations(source)
    assert (output / "before" / source.name).read_bytes() == before


def test_partial_apply_is_rolled_back_using_existing_transaction(
    source, checks, tmp_path, monkeypatch
):
    from pcbsmith.operations import file_transaction as transaction

    output = tmp_path / "candidate"
    revision.create_board_revision(board=source, request=request(source), output=output)
    real_write = transaction.atomic_write
    fired = False

    def fail_once(path, payload):
        nonlocal fired
        if path == source.parent / LEDGER and not fired:
            fired = True
            raise OSError("injected journal failure")
        return real_write(path, payload)

    monkeypatch.setattr(transaction, "atomic_write", fail_once)
    with pytest.raises(transaction.FileTransactionError, match="rolled back"):
        revision.apply_board_revision(board=source, directory=output)
    assert fired and source.read_bytes() == BOARD
    assert not (source.parent / LEDGER).exists()
    transaction.require_complete_project(source.parent)


@pytest.fixture(autouse=True)
def isolated_producer_contracts(monkeypatch):
    """Synthetic inner-contract tests; real job authorization is tested separately."""
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)


def test_manual_track_revision_requires_explicit_user_authorization(source, checks, tmp_path):
    req = request(source).model_copy(
        update={
            "edits": (
                NativeEdit(
                    kind="segment", target="route", points_mm=((12, 10), (16, 11), (20, 10))
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="Manual copper routing is disabled"):
        revision.create_board_revision(board=source, request=req, output=tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists() and not checks
    authorized = req.model_copy(
        update={"manual_routing_authorization": "User explicitly asked for this local trace repair"}
    )
    candidate = revision.create_board_revision(
        board=source, request=authorized, output=tmp_path / "allowed"
    )
    assert candidate.exists() and len(checks) == 1


def test_placement_edit_requires_vector_before_candidate_creation(source, checks, tmp_path):
    req = request(source).model_copy(
        update={"edits": (NativeEdit(kind="component", target="R1", position_mm=(10, 11)),)}
    )
    output = tmp_path / "missing-vector"
    with pytest.raises(ValueError, match="reviewed vector floorplan"):
        revision.create_board_revision(board=source, request=req, output=output)
    assert not output.exists()
    assert not checks
    assert source.read_bytes() == BOARD
