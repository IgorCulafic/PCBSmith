from __future__ import annotations

import json
from pathlib import Path

import pytest

import pcbsmith.production_generators as production_generators
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
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


def test_registry_covers_every_public_board_generator() -> None:
    source = Path(__file__).parents[2] / "src" / "pcbsmith" / "kicad"

    audit = audit_generator_registry(source)

    assert audit.clean, audit
    assert len(audit.discovered_ids) == 21
    assert len(GENERATOR_REGISTRY) == 21


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
        "pcbsmith.kicad.aerosense_2f_board:"
        "generate_aerosense_routed_board",
        "pcbsmith.kicad.protocol_analyzer_8ch_board:"
        "generate_protocol_analyzer_routed_board",
        "pcbsmith.kicad.retro_pad_3x3_board:generate_retro_pad_3x3_routed_board",
        "pcbsmith.kicad.retro_pad_board:generate_retro_pad_board",
        "pcbsmith.kicad.retro_pad_r003_board:generate_retro_pad_r003_routed_board",
    }


def test_placement_only_generator_cannot_publish_routed_candidate(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="placement publication only"):
        persist_registered_routed_candidate(
            generator_id=(
                "pcbsmith.kicad.bldc_esc_board:"
                "generate_bldc_esc_placement_board"
            ),
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
            '{"violations":[],"unconnected_items":[],"schematic_parity":[]}',
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


def test_registered_routed_builder_commits_complete_candidate_fixture(
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

    result = persist_registered_routed_candidate(
        generator_id=(
            "pcbsmith.kicad.retro_pad_r003_board:"
            "generate_retro_pad_r003_routed_board"
        ),
        transaction_root=tmp_path,
        project_id="fixture",
        generation_id="route-1",
        generation_sha256="a" * 64,
        board_relative_path="design/board.kicad_pcb",
        board_payload=board_payload,
        review_generator=review,
        drc_generator=drc,
        support_payloads={
            "design/board.kicad_pro": b'{"board": {}}',
            "design/board.kicad_sch": b"(kicad_sch)",
        },
    )

    assert result.transaction.manifest.status == "committed"
    assert result.routing_evidence.copper_carrier_net_coverage == 1.0
    assert result.drc_evidence.clean
    assert (tmp_path / "CURRENT.json").is_file()
    assert (tmp_path / "generations" / "route-1" / "verification" / "drc.json").is_file()
    assert (
        tmp_path / "generations" / "route-1" / "design" / "board.kicad_pro"
    ).is_file()
    schematic_artifacts = tuple(
        artifact
        for artifact in result.transaction.manifest.artifacts
        if artifact.role == "schematic"
    )
    assert tuple(item.relative_path for item in schematic_artifacts) == (
        "design/board.kicad_sch",
    )
