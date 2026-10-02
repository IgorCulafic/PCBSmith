from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from pcbsmith.kicad.board import BoardLayout, TrackSegment
from pcbsmith.kicad.routing_candidate_adapter import native_source_route_objects
from pcbsmith.kicad.routing_external_adapters import (
    FREEROUTING_V1_9_0,
    FREEROUTING_V2_2_4,
    FREEROUTING_V2_3_0,
    KRT_V0_19_0,
    PINNED_H0_EXTERNAL_ROUTERS,
    ExternalProcessCancelled,
    ExternalProcessResult,
    ExternalToolBinding,
    external_distribution_sha256,
    run_freerouting_dsn_ses_candidate,
    run_krt_board_candidate,
)
from pcbsmith.routing_ir import (
    DeterministicRoutingConfiguration,
    PartialCandidateStatus,
    ProtectedRouteObjectPolicy,
    RouteClearanceConstraint,
    RouteFailureKind,
    RouteRequest,
    RouteTopologyConstraint,
    RouteViaTechnology,
    RouteWidthConstraint,
    RoutingBudget,
    RoutingInputIdentity,
    TargetRouteDomain,
    TargetRouteNet,
)

BOARD_SHA = "b" * 64
OTHER_SHA = "a" * 64


def _layout(segments: tuple[TrackSegment, ...] = ()) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=segments,
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
    )


def _request(
    layout: BoardLayout,
    *,
    protected: bool = False,
) -> RouteRequest:
    source_objects = native_source_route_objects(
        layout,
        source_board_sha256=BOARD_SHA,
    )
    terminals = ("terminal:R1:2", "terminal:R2:1")
    return RouteRequest(
        request_id="request:external-fixture",
        inputs=RoutingInputIdentity(
            project_sha256=OTHER_SHA,
            board_sha256=BOARD_SHA,
            schematic_sha256="c" * 64,
            netlist_sha256="d" * 64,
            placement_sha256="e" * 64,
            outline_sha256="f" * 64,
            holes_sha256="0" * 64,
            rules_sha256="1" * 64,
            protected_copper_sha256="2" * 64,
        ),
        target_domains=(
            TargetRouteDomain(
                domain_id="domain:ordinary",
                nets=(TargetRouteNet(net_name="/SIG", terminal_object_ids=terminals),),
                priority=0,
            ),
        ),
        source_route_objects=source_objects,
        protected_policy=ProtectedRouteObjectPolicy(
            protected_objects=source_objects if protected else (),
        ),
        allowed_layers=("F.Cu", "B.Cu"),
        width_constraints=(
            RouteWidthConstraint(
                constraint_id="constraint:width:sig",
                net_names=("/SIG",),
                minimum_width_mm=0.2,
                preferred_width_mm=0.4,
                maximum_width_mm=0.6,
            ),
        ),
        clearance_constraints=(
            RouteClearanceConstraint(
                constraint_id="constraint:clearance:sig",
                net_names=("/SIG",),
                other_net_names=(),
                minimum_clearance_mm=0.2,
            ),
        ),
        via_technologies=(
            RouteViaTechnology(
                constraint_id="constraint:via:through",
                technology_id="via:through-default",
                start_layer="F.Cu",
                end_layer="B.Cu",
                diameter_mm=0.6,
                drill_mm=0.3,
            ),
        ),
        topology_constraints=(
            RouteTopologyConstraint(
                constraint_id="constraint:topology:sig",
                domain_id="domain:ordinary",
                net_name="/SIG",
                topology_kind="any_tree",
                ordered_terminal_object_ids=terminals,
            ),
        ),
        budget=RoutingBudget(
            max_passes=4,
            max_expansions=100_000,
            max_expansions_per_net=100_000,
            max_stagnant_passes=2,
            max_exact_check_rejections=0,
        ),
        deterministic=DeterministicRoutingConfiguration(
            seed=0,
            route_order=("/SIG",),
            tie_break_policy="fixture",
        ),
    )


def _binding(path: Path) -> ExternalToolBinding:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ExternalToolBinding(
        root_path=str(path),
        entrypoint_path=str(path),
        entrypoint_sha256=digest,
        distribution_sha256=digest,
    )


def _routed_layout(source: BoardLayout) -> BoardLayout:
    return replace(
        source,
        segments=source.segments
        + (
            TrackSegment(
                x1=5.0,
                y1=6.0,
                x2=25.0,
                y2=6.0,
                layer="F.Cu",
                net_name="/SIG",
                width_mm=0.4,
            ),
        ),
    )


def test_pinned_external_matrix_has_distinct_audited_source_identities() -> None:
    assert len(PINNED_H0_EXTERNAL_ROUTERS) == 5
    assert len({item.engine_id for item in PINNED_H0_EXTERNAL_ROUTERS}) == 5
    assert KRT_V0_19_0.source_revision == ("9f0bf5025a03c6856a93f13f68ae6f667f3ba060")
    assert FREEROUTING_V2_2_4.source_revision == ("20f1a72e546b9b23c7ba5127086885cfacbdd4be")
    assert not FREEROUTING_V1_9_0.headless


def test_distribution_hash_covers_every_file_and_relative_path(tmp_path: Path) -> None:
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "route.py").write_text("print('route')\n", encoding="utf-8")
    first = external_distribution_sha256(tool)
    (tool / "rules.py").write_text("CLEARANCE = 0.2\n", encoding="utf-8")
    second = external_distribution_sha256(tool)

    assert first != second


def test_freerouting_dsn_ses_adapter_retains_command_and_typed_budget_gap(
    tmp_path: Path,
) -> None:
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"pinned-freerouting-fixture")
    binding = _binding(jar)
    source = _layout()
    request = _request(source)
    captured: tuple[str, ...] | None = None

    def execute(
        command: Sequence[str],
        _working_directory: Path,
    ) -> ExternalProcessResult:
        nonlocal captured
        captured = tuple(command)
        output = Path(command[command.index("-do") + 1])
        output.write_bytes(b"(session fixture)")
        return ExternalProcessResult(
            exit_code=0,
            stdout=b"routed\n",
            stderr=b"",
            elapsed_seconds=2.5,
        )

    result = run_freerouting_dsn_ses_candidate(
        request=request,
        source_layout=source,
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_3_0,
        binding=binding,
        dsn_payload=b"(pcb fixture)",
        ses_importer=lambda _path: _routed_layout(source),
        java_executable="java-fixture",
        executor=execute,
    )

    assert captured is not None
    assert captured[:3] == ("java-fixture", "-jar", str(jar.resolve()))
    assert ("-mp", "4") == captured[7:9]
    assert result.partial_status is PartialCandidateStatus.BOUNDED_PARTIAL
    assert result.segment_deltas
    assert result.failures[0].kind is RouteFailureKind.REJECTED_CONSTRAINT
    assert "budget:max_expansions" in result.failures[0].resource_ids
    assert (tmp_path / "candidate" / "interchange" / "input.dsn").is_file()
    assert (tmp_path / "candidate" / "interchange" / "output.ses").is_file()
    assert (tmp_path / "candidate" / "engine" / "stdout.log").read_bytes() == (b"routed\n")


def test_freerouting_retains_protected_copper_through_readback(
    tmp_path: Path,
) -> None:
    existing = TrackSegment(
        x1=1.0,
        y1=1.0,
        x2=2.0,
        y2=1.0,
        layer="F.Cu",
        net_name="/SIG",
        width_mm=0.4,
    )
    source = _layout((existing,))
    request = _request(source, protected=True)
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"pinned")
    called = False

    def execute(
        command: Sequence[str],
        _working_directory: Path,
    ) -> ExternalProcessResult:
        nonlocal called
        called = True
        Path(command[command.index("-do") + 1]).write_bytes(b"(session fixture)")
        return ExternalProcessResult(exit_code=0, stdout=b"", stderr=b"", elapsed_seconds=1.0)

    result = run_freerouting_dsn_ses_candidate(
        request=request,
        source_layout=source,
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_3_0,
        binding=_binding(jar),
        dsn_payload=b"(pcb fixture)",
        ses_importer=lambda _path: _routed_layout(source),
        executor=execute,
    )

    assert called
    assert result.partial_status is PartialCandidateStatus.BOUNDED_PARTIAL
    assert all(item.operation.value == "add" for item in result.segment_deltas)


def test_missing_or_changed_external_binary_returns_typed_unavailable_result(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.jar"
    request = _request(_layout())
    binding = ExternalToolBinding(
        root_path=str(missing),
        entrypoint_path=str(missing),
        entrypoint_sha256="a" * 64,
        distribution_sha256="b" * 64,
    )

    result = run_freerouting_dsn_ses_candidate(
        request=request,
        source_layout=_layout(),
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_3_0,
        binding=binding,
        dsn_payload=b"(pcb fixture)",
        ses_importer=lambda _path: _layout(),
    )

    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA
    assert result.failures[0].kind is RouteFailureKind.ENGINE_FAILURE
    assert result.termination.reason == "external_tool_unavailable"


def test_known_bad_freerouting_224_is_blocked_before_launch(tmp_path: Path) -> None:
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"pinned")
    called = False

    def execute(_command: Sequence[str], _working_directory: Path) -> ExternalProcessResult:
        nonlocal called
        called = True
        raise AssertionError("known-bad release must not launch")

    result = run_freerouting_dsn_ses_candidate(
        request=_request(_layout()),
        source_layout=_layout(),
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_2_4,
        binding=_binding(jar),
        dsn_payload=b"(pcb fixture)",
        ses_importer=lambda _path: _layout(),
        executor=execute,
    )
    assert not called
    assert result.termination.reason == "known_bad_router_version"
    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA


@pytest.mark.parametrize(
    ("failure", "termination_reason"),
    (("timeout", "external_process_timeout"), ("cancel", "external_process_cancelled")),
)
def test_timeout_and_cancel_return_no_delta(
    tmp_path: Path,
    failure: str,
    termination_reason: str,
) -> None:
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"pinned")

    def execute(command: Sequence[str], _working_directory: Path) -> ExternalProcessResult:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1.0, output=b"partial", stderr=b"timeout")
        raise ExternalProcessCancelled("cancelled")

    result = run_freerouting_dsn_ses_candidate(
        request=_request(_layout()),
        source_layout=_layout(),
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_3_0,
        binding=_binding(jar),
        dsn_payload=b"(pcb fixture)",
        ses_importer=lambda _path: _layout(),
        executor=execute,
    )
    assert result.termination.reason == termination_reason
    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA
    assert not result.segment_deltas and not result.via_deltas


def test_jvm_fatal_signature_rolls_back_even_with_zero_exit(tmp_path: Path) -> None:
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"pinned")

    def execute(_command: Sequence[str], _working_directory: Path) -> ExternalProcessResult:
        return ExternalProcessResult(
            exit_code=0,
            stdout=b"java.lang.StackOverflowError",
            stderr=b"",
            elapsed_seconds=1.0,
        )

    result = run_freerouting_dsn_ses_candidate(
        request=_request(_layout()),
        source_layout=_layout(),
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_3_0,
        binding=_binding(jar),
        dsn_payload=b"(pcb fixture)",
        ses_importer=lambda _path: _layout(),
        executor=execute,
    )
    assert result.termination.reason == "external_jvm_fatal"
    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA


@pytest.mark.parametrize("mode", ("missing", "malformed", "semantic-drift"))
def test_missing_malformed_and_semantically_drifted_output_roll_back(
    tmp_path: Path,
    mode: str,
) -> None:
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"pinned")
    source = _layout()

    def execute(command: Sequence[str], _working_directory: Path) -> ExternalProcessResult:
        if mode != "missing":
            Path(command[command.index("-do") + 1]).write_bytes(b"(session fixture)")
        return ExternalProcessResult(exit_code=0, stdout=b"", stderr=b"", elapsed_seconds=1.0)

    def importer(_path: Path) -> BoardLayout:
        if mode == "malformed":
            raise ValueError("malformed SES")
        if mode == "semantic-drift":
            return replace(source, width_mm=source.width_mm + 1.0)
        return source

    result = run_freerouting_dsn_ses_candidate(
        request=_request(source),
        source_layout=source,
        candidate_directory=tmp_path / "candidate",
        spec=FREEROUTING_V2_3_0,
        binding=_binding(jar),
        dsn_payload=b"(pcb fixture)",
        ses_importer=importer,
        executor=execute,
    )
    assert result.partial_status is PartialCandidateStatus.FAILED_NO_DELTA
    assert not result.segment_deltas and not result.via_deltas
    assert result.termination.reason in {
        "external_process_failed",
        "external_output_import_failed",
    }


def test_krt_direct_board_adapter_uses_isolated_input_and_output(
    tmp_path: Path,
) -> None:
    script = tmp_path / "route.py"
    script.write_text("# pinned fixture\n", encoding="utf-8")
    source = _layout()
    request = _request(source)
    captured: tuple[str, ...] | None = None

    def execute(
        command: Sequence[str],
        _working_directory: Path,
    ) -> ExternalProcessResult:
        nonlocal captured
        captured = tuple(command)
        Path(command[3]).write_bytes(b"(kicad_pcb)")
        return ExternalProcessResult(
            exit_code=0,
            stdout=b"",
            stderr=b"",
            elapsed_seconds=1.0,
        )

    result = run_krt_board_candidate(
        request=request,
        source_layout=source,
        candidate_directory=tmp_path / "candidate",
        spec=KRT_V0_19_0,
        binding=_binding(script),
        source_board_payload=b"(kicad_pcb source)",
        board_importer=lambda _path: _routed_layout(source),
        python_executable="python-fixture",
        executor=execute,
    )

    assert captured is not None
    assert captured[:2] == ("python-fixture", str(script.resolve()))
    assert captured[4:6] == ("--nets", "/SIG")
    assert result.partial_status is PartialCandidateStatus.BOUNDED_PARTIAL
    assert result.segment_deltas
