from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import pcbsmith.production_generators as production_generators
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.routing_candidate_transaction import AcceptedRoutingExecution
from pcbsmith.kicad.routing_evidence import inspect_saved_board_routing
from pcbsmith.production_generators import (
    GENERATOR_REGISTRY,
    GeneratorPublicationCapability,
    audit_generator_registry,
    generate_nonmutating_kicad_drc,
    persist_registered_routed_candidate,
    registered_generator,
)
from pcbsmith.review.visual_package import RenderProfile, VisualReviewManifest
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.routing_ir import (
    RouteTerminationEvidence,
    RouteTerminationState,
    RoutingEngineIdentity,
)


def _routing_execution(
    board_payload: bytes, engine: RoutingEngineIdentity | None = None
) -> AcceptedRoutingExecution:
    engine = engine or RoutingEngineIdentity(
        engine_id="pcbsmith-native",
        engine_version="test",
        adapter_id="pcbsmith.test",
        adapter_version="1",
    )
    empty_sha256 = hashlib.sha256(b"").hexdigest()
    termination = RouteTerminationEvidence(
        state=RouteTerminationState.COMPLETED,
        reason="completed in production boundary fixture",
        exit_code=0,
        stdout_sha256=empty_sha256,
        stderr_sha256=empty_sha256,
        elapsed_seconds=0.0,
    )
    fields = {
        "candidate_id": "candidate:test",
        "board_sha256": hashlib.sha256(board_payload).hexdigest(),
        "request_fingerprint": "a" * 64,
        "input_snapshot_fingerprint": "b" * 64,
        "candidate_result_fingerprint": "c" * 64,
        "routing_transaction_fingerprint": "d" * 64,
        "engine": engine,
        "termination": termination,
        "routing_generation_id": "generation:test-routing",
        "routing_generation_sha256": "e" * 64,
        "routing_generation_transaction_fingerprint": "f" * 64,
    }
    provisional = AcceptedRoutingExecution.model_construct(
        **fields,
        receipt_fingerprint="0" * 64,
    )
    return AcceptedRoutingExecution(
        **fields,
        receipt_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"receipt_fingerprint"})
        ),
    )


def test_registry_covers_every_public_board_generator() -> None:
    source = Path(__file__).parents[2] / "src" / "pcbsmith" / "kicad"

    audit = audit_generator_registry(source)

    assert audit.clean, audit
    assert len(audit.discovered_ids) == 24
    assert len(GENERATOR_REGISTRY) == 24


def test_unknown_generator_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="unregistered board generator"):
        registered_generator("pcbsmith.kicad.future_board:generate_future_board")


def test_explicit_routed_builders_are_registered_for_routed_publication() -> None:
    routed_ids = {
        item.generator_id
        for item in GENERATOR_REGISTRY
        if item.capability is GeneratorPublicationCapability.ROUTED
    }

    assert routed_ids == {
        "pcbsmith.production_routing:route_saved_placement_candidate",
        "pcbsmith.kicad.aerosense_2f_board:generate_aerosense_routed_board",
        "pcbsmith.kicad.protocol_analyzer_8ch_board:generate_protocol_analyzer_routed_board",
        "pcbsmith.kicad.retro_pad_3x3_board:generate_retro_pad_3x3_routed_board",
        "pcbsmith.kicad.retro_pad_board:generate_retro_pad_board",
        "pcbsmith.kicad.retro_pad_r003_board:generate_retro_pad_r003_routed_board",
    }


def test_placement_only_generator_cannot_publish_routed_candidate(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="placement publication only"):
        persist_registered_routed_candidate(
            generator_id=("pcbsmith.kicad.bldc_esc_board:generate_bldc_esc_placement_board"),
            transaction_root=tmp_path,
            project_id="esc",
            generation_id="candidate-1",
            generation_sha256="a" * 64,
            board_relative_path="design/board.kicad_pcb",
            board_payload=b"not-even-inspected",
            review_generator=lambda _board, _output: pytest.fail("must not review"),
            drc_generator=lambda _board, _report: pytest.fail("must not run DRC"),
        )

    assert not (tmp_path / "CURRENT.json").exists()


def test_routed_builder_cannot_publish_without_routing_execution(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="routing-engine execution evidence"):
        persist_registered_routed_candidate(
            generator_id=(
                "pcbsmith.kicad.retro_pad_r003_board:generate_retro_pad_r003_routed_board"
            ),
            transaction_root=tmp_path,
            project_id="fixture",
            generation_id="route-without-engine",
            generation_sha256="a" * 64,
            board_relative_path="design/board.kicad_pcb",
            board_payload=b"claimed-routed-board",
            review_generator=lambda _board, _output: pytest.fail("must not review"),
            drc_generator=lambda _board, _report: pytest.fail("must not run DRC"),
        )

    assert not (tmp_path / "CURRENT.json").exists()


def test_routed_builder_rejects_execution_for_another_board(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="different publication board"):
        persist_registered_routed_candidate(
            generator_id=(
                "pcbsmith.kicad.retro_pad_r003_board:generate_retro_pad_r003_routed_board"
            ),
            transaction_root=tmp_path,
            project_id="fixture",
            generation_id="route-stale-engine",
            generation_sha256="a" * 64,
            board_relative_path="design/board.kicad_pcb",
            board_payload=b"current-board",
            routing_execution=_routing_execution(b"other-board"),
            review_generator=lambda _board, _output: pytest.fail("must not review"),
            drc_generator=lambda _board, _report: pytest.fail("must not run DRC"),
        )

    assert not (tmp_path / "CURRENT.json").exists()


def test_production_drc_retains_json_without_board_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = tmp_path / "board.kicad_pcb"
    report = tmp_path / "evidence" / "drc.json"
    board.write_bytes(b"exact-board")
    observed: tuple[str, ...] = ()

    monkeypatch.setattr(
        production_generators,
        "find_kicad_cli",
        lambda: KiCadInstall(path=Path("kicad-cli"), source="test"),
    )

    def run(command: tuple[str, ...]) -> KiCadProcessResult:
        nonlocal observed
        observed = command
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            '{"$schema":"https://schemas.kicad.org/drc.v1.json",'
            '"source":"board.kicad_pcb","kicad_version":"10.0.3",'
            '"violations":[],"unconnected_items":[],"schematic_parity":[]}',
            encoding="utf-8",
        )
        return KiCadProcessResult(
            command=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(production_generators, "run_kicad_process", run)

    generate_nonmutating_kicad_drc(board, report)

    assert report.is_file()
    assert board.read_bytes() == b"exact-board"
    assert "--refill-zones" in observed
    assert "--schematic-parity" in observed
    assert "--save-board" not in observed
    receipt = json.loads(report.with_suffix(".execution.json").read_text())
    assert receipt["check_id"] == "kicad.drc"
    assert receipt["producer_id"] == "kicad-cli.pcb.drc"
    assert receipt["result_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert hashlib.sha256(board.read_bytes()).hexdigest() in receipt["exact_input_sha256s"]


def test_registered_routed_fixture_without_readiness_cannot_publish(
    tmp_path: Path,
) -> None:
    board_payload = b"""(kicad_pcb
  (version 20260206)
  (net 1 "SIG")
  (footprint "Test:A"
    (layer "F.Cu")
    (at 1 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  (footprint "Test:B"
    (layer "F.Cu")
    (at 5 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  )
  (segment (start 1 1) (end 5 1) (width 0.25) (layer "F.Cu") (net 1))
)
"""

    def drc(board: Path, report: Path) -> None:
        assert board.with_suffix(".kicad_pro").read_bytes() == b'{"board": {}}'
        report.write_text(
            json.dumps(
                {
                    "violations": [],
                    "unconnected_items": [],
                    "schematic_parity": [],
                }
            ),
            encoding="utf-8",
        )

    def review(board: Path, output: Path) -> VisualReviewManifest:
        output.mkdir(parents=True)
        (output / "front.png").write_bytes(b"review")
        routing = inspect_saved_board_routing(board)
        return VisualReviewManifest(
            schema_id="pcbsmith-visual-review-manifest-v1",
            render_profile=RenderProfile(),
            stage="final",
            board_file=str(board),
            board_sha256=routing.board_sha256,
            copper_sha256="b" * 64,
            routing_evidence=routing,
            kicad_version="10.0-test",
            renderer_version="test",
            model_preflight_status="passed",
            workflow_conformance_status="conformant",
            package_status="generated_pending_inspection",
            artifacts=(),
        )

    with pytest.raises(ValueError, match="requires predesign and readiness"):
        persist_registered_routed_candidate(
            generator_id=(
                "pcbsmith.kicad.retro_pad_r003_board:generate_retro_pad_r003_routed_board"
            ),
            transaction_root=tmp_path,
            project_id="fixture",
            generation_id="route-1",
            generation_sha256="a" * 64,
            board_relative_path="design/board.kicad_pcb",
            board_payload=board_payload,
            review_generator=review,
            drc_generator=drc,
            routing_execution=_routing_execution(board_payload),
            support_payloads={
                "design/board.kicad_pro": b'{"board": {}}',
                "design/board.kicad_sch": b"(kicad_sch)",
            },
        )

    assert not (tmp_path / "CURRENT.json").exists()


@pytest.fixture(autouse=True)
def isolated_producer_contracts(monkeypatch):
    """Synthetic inner-contract tests; real job authorization is tested separately."""
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)


def test_ordinary_router_cannot_claim_foreign_engine_receipt(tmp_path):
    with pytest.raises(ValueError, match="registered native or Freerouting adapter"):
        persist_registered_routed_candidate(
            generator_id="pcbsmith.production_routing:route_saved_placement_candidate",
            transaction_root=tmp_path,
            project_id="fixture",
            generation_id="fixture",
            generation_sha256="a" * 64,
            board_relative_path="board.kicad_pcb",
            board_payload=b"fixture",
            routing_execution=_routing_execution(b"fixture"),
            review_generator=lambda *_: None,
            drc_generator=lambda *_: None,
        )


@pytest.mark.parametrize(
    "change,accepted",
    [
        ({}, True),
        ({"engine_version": "2.2.4"}, False),
        ({"executable_sha256": None}, False),
        ({"adapter_id": "foreign"}, False),
    ],
)
def test_ordinary_publication_recognizes_pinned_freerouting(
    tmp_path, monkeypatch, change, accepted
):
    engine = RoutingEngineIdentity(
        **{
            "engine_id": "freerouting-v2.3.0",
            "engine_version": "2.3.0",
            "adapter_id": "pcbsmith.kicad.routing_external_adapters",
            "adapter_version": "1",
            "source_commit": "v2.3.0",
            "executable_sha256": "a" * 64,
            **change,
        }
    )
    calls = []

    def readiness(**kwargs):
        calls.append("readiness")
        raise ValueError("Synthetic stop: readiness remains mandatory")

    monkeypatch.setattr(production_generators, "_guarded_readiness_review", readiness)
    with pytest.raises(
        ValueError,
        match="readiness remains mandatory"
        if accepted
        else "registered native or Freerouting adapter",
    ):
        persist_registered_routed_candidate(
            generator_id="pcbsmith.production_routing:route_saved_placement_candidate",
            transaction_root=tmp_path,
            project_id="fixture",
            generation_id="fixture",
            generation_sha256="a" * 64,
            board_relative_path="board.kicad_pcb",
            board_payload=b"fixture",
            routing_execution=_routing_execution(b"fixture", engine),
            review_generator=lambda *_: None,
            drc_generator=lambda *_: None,
        )
    assert bool(calls) == accepted
    assert not (tmp_path / "CURRENT.json").exists()
