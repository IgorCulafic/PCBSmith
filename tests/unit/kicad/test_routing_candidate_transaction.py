from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from pcbsmith.applicability_execution import (
    ApplicableCheckRequirement,
    CheckExecutionRecord,
    ProjectApplicabilityExecutionManifest,
    ProjectCheckApplicability,
    ProjectCheckDisposition,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.placement_readback import KiCadBoardReadbackSnapshot
from pcbsmith.kicad.routing_candidate_adapter import (
    native_source_route_objects,
    route_native_candidate,
    stable_route_terminal_object_id,
)
from pcbsmith.kicad.routing_candidate_transaction import (
    AcceptedRoutingExecution,
    RoutingCandidateInputSnapshot,
    RoutingCandidateTransactionResult,
    RoutingCandidateTransactionStatus,
    RoutingCandidateValidationBundle,
    freeze_native_routing_inputs,
    run_routing_candidate_transaction,
)
from pcbsmith.kicad.routing_evidence import (
    inspect_kicad_drc_report,
    inspect_saved_board_routing,
)
from pcbsmith.production_workflow import (
    GenerationTransactionResult,
    RoutedBoardVerificationEvidence,
    RoutedVerificationKind,
    RoutedVerificationRecord,
    commit_generation_transaction,
)
from pcbsmith.routing_ir import (
    DeterministicRoutingConfiguration,
    PartialCandidateStatus,
    ProtectedRouteObjectPolicy,
    RouteCandidateResult,
    RouteClearanceConstraint,
    RouteFailureKind,
    RouteRequest,
    RouteTopologyConstraint,
    RouteViaTechnology,
    RouteWidthConstraint,
    RoutingBudget,
    TargetRouteDomain,
    TargetRouteNet,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


@pytest.fixture(autouse=True)
def _unit_transaction_without_cli_worker(monkeypatch):
    # These fixtures test transaction behavior. Runtime guards have separate tests.
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    monkeypatch.setattr("pcbsmith.board_job.require_worker", lambda *args: None)


RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fixture() -> tuple[BoardLayout, BoardNetlist]:
    components = (
        BoardComponent(
            reference="R1",
            value="1k",
            footprint=RESISTOR,
            uuid_path="fixture/r1",
        ),
        BoardComponent(
            reference="R2",
            value="1k",
            footprint=RESISTOR,
            uuid_path="fixture/r2",
        ),
    )
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet(name="/SIG", nodes=(("R1", "2"), ("R2", "1"))),
            BoardNet(name="/A", nodes=(("R1", "1"),)),
            BoardNet(name="/B", nodes=(("R2", "2"),)),
        ),
    )
    layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 25.0)),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0), ("R2", 6.0)),
    )
    return layout, netlist


def _snapshot(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    board_payload: bytes | None = None,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> tuple[RoutingCandidateInputSnapshot, dict[str, bytes]]:
    payloads = {
        "design/fixture.kicad_pcb": (
            render_board_from_layout(netlist, layout, profile=profile).encode("utf-8")
            if board_payload is None
            else board_payload
        ),
        "design/fixture.kicad_sch": b"(kicad_sch (version 20260101))\n",
        "design/project.kicad_pro": b'{"board": {}}\n',
    }
    snapshot = freeze_native_routing_inputs(
        payloads=payloads,
        roles={
            "design/fixture.kicad_pcb": "board",
            "design/fixture.kicad_sch": "schematic",
            "design/project.kicad_pro": "other",
        },
        board_relative_path="design/fixture.kicad_pcb",
        schematic_relative_paths=("design/fixture.kicad_sch",),
        layout=layout,
        netlist=netlist,
        profile=profile,
    )
    return snapshot, payloads


def _request(
    layout: BoardLayout,
    netlist: BoardNetlist,
    snapshot: RoutingCandidateInputSnapshot,
    *,
    max_expansions: int = 100_000,
) -> RouteRequest:
    terminals = tuple(
        stable_route_terminal_object_id(
            net_name="/SIG",
            reference=reference,
            pin=pin,
        )
        for reference, pin in netlist.nets[0].nodes
    )
    profile = DEFAULT_PCB_RULE_PROFILE
    return RouteRequest(
        request_id="request:transaction-fixture",
        inputs=snapshot.identity,
        target_domains=(
            TargetRouteDomain(
                domain_id="domain:ordinary",
                nets=(TargetRouteNet(net_name="/SIG", terminal_object_ids=terminals),),
                priority=0,
            ),
        ),
        source_route_objects=native_source_route_objects(
            layout,
            source_board_sha256=snapshot.identity.board_sha256,
        ),
        protected_policy=ProtectedRouteObjectPolicy(),
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
                other_net_names=("/A", "/B"),
                minimum_clearance_mm=0.2,
            ),
        ),
        via_technologies=(
            RouteViaTechnology(
                constraint_id="constraint:via:through",
                technology_id="via:through-default",
                start_layer="F.Cu",
                end_layer="B.Cu",
                diameter_mm=profile.geometry.routing_via_diameter_mm,
                drill_mm=profile.geometry.routing_via_drill_mm,
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
            max_expansions=max_expansions,
            max_expansions_per_net=max_expansions,
            max_stagnant_passes=2,
            max_exact_check_rejections=0,
        ),
        deterministic=DeterministicRoutingConfiguration(
            seed=0,
            route_order=("/SIG",),
            tie_break_policy="pcbsmith-native-lexical-v1",
        ),
    )


def _fixed_clock() -> Iterator[float]:
    yield 10.0
    yield 11.0


def _runner(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> Callable[[RouteRequest, Path], RouteCandidateResult]:
    def run(request: RouteRequest, _candidate_dir: Path) -> RouteCandidateResult:
        times = _fixed_clock()
        return route_native_candidate(
            request=request,
            layout=layout,
            netlist=netlist,
            profile=profile,
            engine_source_commit="fixture",
            clock=lambda: next(times),
        )

    return run


def _verification(board_file: Path) -> RoutedBoardVerificationEvidence:
    board_sha256 = _sha256(board_file.read_bytes())
    records = tuple(
        RoutedVerificationRecord.build(
            kind=kind,
            board_sha256=board_sha256,
            producer_id=f"test.{kind.value}",
            tool_version="test-1",
            input_sha256s=(
                board_sha256,
                _sha256(f"input:{kind.value}".encode()),
            ),
            accepted=True,
            result_code="accepted",
        )
        for kind in RoutedVerificationKind
    )
    return RoutedBoardVerificationEvidence.build(
        board_sha256=board_sha256,
        records=records,
    )


def _applicability(board_file: Path) -> ProjectApplicabilityExecutionManifest:
    board_sha256 = _sha256(board_file.read_bytes())
    context = _sha256(b"routing-transaction-context")
    requirement = ApplicableCheckRequirement.build(
        check_id="routing.saved-board",
        rule_ids=("routing.saved-board.rule",),
        applicability=ProjectCheckApplicability.APPLICABLE,
        applicability_authority_id="test.routing.applicability",
        exact_input_sha256s=(board_sha256, context),
        minimum_evaluated_objects=1,
        rationale="The saved candidate must pass the fixture engineering check.",
    )
    execution = CheckExecutionRecord.build(
        check_id=requirement.check_id,
        exact_input_sha256s=requirement.exact_input_sha256s,
        producer_id="test.routing.checker",
        tool_version="test-1",
        evaluated_object_count=1,
        disposition=ProjectCheckDisposition.PASS,
        result_sha256=_sha256(b"routing-check-pass"),
    )
    return ProjectApplicabilityExecutionManifest.build(
        project_id="fixture",
        saved_design_sha256=board_sha256,
        requirements=(requirement,),
        executions=(execution,),
    )


def _validator(
    board_file: Path,
    _request: RouteRequest,
    _readback: KiCadBoardReadbackSnapshot,
    candidate_dir: Path,
) -> RoutingCandidateValidationBundle:
    drc_file = candidate_dir / "validation" / "kicad-drc.json"
    drc_file.parent.mkdir(parents=True, exist_ok=True)
    drc_file.write_text(
        json.dumps(
            {
                "violations": [],
                "unconnected_items": [],
                "schematic_parity": [],
            }
        ),
        encoding="utf-8",
    )
    board_sha256 = _sha256(board_file.read_bytes())
    return RoutingCandidateValidationBundle.build(
        board_sha256=board_sha256,
        saved_board_routing=inspect_saved_board_routing(board_file),
        kicad_drc=inspect_kicad_drc_report(drc_file),
        verification=_verification(board_file),
        applicability_execution=_applicability(board_file),
        semantic_readback_accepted=True,
    )


def _run(
    tmp_path: Path,
    *,
    layout: BoardLayout,
    netlist: BoardNetlist,
    snapshot: RoutingCandidateInputSnapshot,
    payloads: dict[str, bytes],
    request: RouteRequest,
    candidate_id: str,
    engine_runner: Callable[[RouteRequest, Path], RouteCandidateResult] | None = None,
    generation_committer: Callable[..., GenerationTransactionResult] | None = None,
) -> RoutingCandidateTransactionResult:
    return run_routing_candidate_transaction(
        transaction_root=tmp_path / "transactions",
        project_id="fixture",
        candidate_id=candidate_id,
        generation_id=f"generation-{candidate_id}",
        request=request,
        input_snapshot=snapshot,
        input_payloads=payloads,
        source_layout=layout,
        netlist=netlist,
        engine_runner=engine_runner or _runner(layout, netlist),
        validator=_validator,
        generation_committer=generation_committer or commit_generation_transaction,
    )


def test_clean_internal_candidate_is_retained_and_atomically_accepted(
    tmp_path: Path,
) -> None:
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot)

    result = _run(
        tmp_path,
        layout=layout,
        netlist=netlist,
        snapshot=snapshot,
        payloads=payloads,
        request=request,
        candidate_id="accepted",
    )

    assert result.status is RoutingCandidateTransactionStatus.ACCEPTED
    assert result.failures == ()
    assert result.validation is not None and result.validation.accepted
    assert result.generation_transaction is not None
    assert result.generation_transaction.manifest.status == "committed"
    receipt = AcceptedRoutingExecution.from_transaction(result)
    assert receipt.board_sha256 == result.validation.board_sha256
    assert receipt.engine == result.candidate.engine
    assert AcceptedRoutingExecution.model_validate_json(receipt.model_dump_json()) == receipt
    assert Path(result.retained_directory, "request.json").is_file()
    assert Path(result.retained_directory, "candidate-result.json").is_file()
    assert (tmp_path / "transactions" / "CURRENT.json").is_file()


def test_bounded_partial_is_retained_without_canonical_change(tmp_path: Path) -> None:
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot, max_expansions=0)

    result = _run(
        tmp_path,
        layout=layout,
        netlist=netlist,
        snapshot=snapshot,
        payloads=payloads,
        request=request,
        candidate_id="partial",
    )

    assert result.status is RoutingCandidateTransactionStatus.REJECTED
    assert result.candidate is not None
    assert result.candidate.partial_status in {
        PartialCandidateStatus.BOUNDED_PARTIAL,
        PartialCandidateStatus.FAILED_NO_DELTA,
    }
    assert any(item.kind is RouteFailureKind.BUDGET_EXHAUSTED for item in result.failures)
    with pytest.raises(ValueError, match="accepted transaction"):
        AcceptedRoutingExecution.from_transaction(result)
    assert not (tmp_path / "transactions" / "CURRENT.json").exists()
    assert Path(result.retained_directory, "candidate-result.json").is_file()


def test_stale_board_payload_is_rejected_before_engine_execution(tmp_path: Path) -> None:
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot)
    stale = dict(payloads)
    stale["design/fixture.kicad_pcb"] += b"\n"
    called = False

    def should_not_run(
        _request: RouteRequest,
        _candidate_dir: Path,
    ) -> RouteCandidateResult:
        nonlocal called
        called = True
        raise AssertionError("engine must not run for stale inputs")

    result = _run(
        tmp_path,
        layout=layout,
        netlist=netlist,
        snapshot=snapshot,
        payloads=stale,
        request=request,
        candidate_id="stale-board",
        engine_runner=should_not_run,
    )

    assert result.status is RoutingCandidateTransactionStatus.REJECTED
    assert not called
    assert result.candidate is None
    assert not (tmp_path / "transactions" / "CURRENT.json").exists()


@pytest.mark.parametrize("drift", ("placement", "outline", "hole"))
def test_immutable_board_semantic_drift_is_rejected(
    tmp_path: Path,
    drift: str,
) -> None:
    layout, netlist = _fixture()
    if drift == "placement":
        source_layout = replace(
            layout,
            placements=((layout.placements[0][0], 6.0), layout.placements[1]),
        )
    elif drift == "outline":
        source_layout = replace(layout, width_mm=31.0)
    else:
        source_layout = replace(
            layout,
            placements=(
                (
                    replace(
                        layout.placements[0][0],
                        footprint=(
                            "Resistor_THT:R_Axial_DIN0414_L11.9mm_D4.5mm_P15.24mm_Horizontal"
                        ),
                    ),
                    layout.placements[0][1],
                ),
                layout.placements[1],
            ),
        )
    board_payload = render_board_from_layout(netlist, source_layout).encode("utf-8")
    snapshot, payloads = _snapshot(layout, netlist, board_payload=board_payload)
    request = _request(layout, netlist, snapshot)

    result = _run(
        tmp_path,
        layout=layout,
        netlist=netlist,
        snapshot=snapshot,
        payloads=payloads,
        request=request,
        candidate_id=f"drift-{drift}",
    )

    assert result.status is RoutingCandidateTransactionStatus.REJECTED
    assert result.validation is None
    assert any(
        "detached layout does not match saved board geometry and electrical semantics"
        in item.message
        for item in result.failures
    )
    assert not (tmp_path / "transactions" / "CURRENT.json").exists()


@pytest.mark.parametrize("drift", ("rules", "netlist"))
def test_rule_or_netlist_drift_is_rejected_by_the_adapter(
    tmp_path: Path,
    drift: str,
) -> None:
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot)
    if drift == "rules":
        changed_profile = DEFAULT_PCB_RULE_PROFILE.model_copy(
            update={
                "geometry": DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
                    update={"routing_via_diameter_mm": 0.65}
                )
            }
        )
        runner = _runner(layout, netlist, profile=changed_profile)
    else:
        changed_netlist = replace(
            netlist,
            nets=(
                replace(netlist.nets[0], name="/SIG-CHANGED"),
                *netlist.nets[1:],
            ),
        )
        runner = _runner(layout, changed_netlist)

    result = _run(
        tmp_path,
        layout=layout,
        netlist=netlist,
        snapshot=snapshot,
        payloads=payloads,
        request=request,
        candidate_id=f"drift-{drift}",
        engine_runner=runner,
    )

    assert result.status is RoutingCandidateTransactionStatus.REJECTED
    assert result.candidate is None
    assert any("stale" in item.message for item in result.failures)


def test_failed_publication_is_typed_and_does_not_change_canonical_pointer(
    tmp_path: Path,
) -> None:
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot)

    def failed_rollback(**_kwargs: object) -> GenerationTransactionResult:
        raise OSError("injected rollback failure")

    result = _run(
        tmp_path,
        layout=layout,
        netlist=netlist,
        snapshot=snapshot,
        payloads=payloads,
        request=request,
        candidate_id="rollback-failure",
        generation_committer=failed_rollback,
    )

    assert result.status is RoutingCandidateTransactionStatus.ROLLBACK_FAILED
    assert result.failures[0].kind is RouteFailureKind.ROLLBACK_FAILED
    assert result.canonical_pointer_sha256_before is None
    assert result.canonical_pointer_sha256_after is None
    assert not (tmp_path / "transactions" / "CURRENT.json").exists()


def test_initial_native_routing_preserves_edited_reference_identity():
    from pcbsmith.kicad.board import TrackSegment
    from pcbsmith.kicad.library import _atom, _children, parse_sexpr, serialize_sexpr
    from pcbsmith.kicad.placement_readback import extract_kicad_board_readback
    from pcbsmith.kicad.routing_candidate_transaction import (
        immutable_readback_matches,
        render_native_routing_candidate,
    )

    layout, netlist = _fixture()
    tree = parse_sexpr(render_board_from_layout(netlist, layout))
    fp = _children(tree, "footprint")[0]
    prop = next(p for p in _children(fp, "property") if _atom(p[1]) == "Reference")
    at = _children(prop, "at")[0]
    at[:] = ["at", "1.5", "-2", "0"]
    source = serialize_sexpr(tree)
    edited = replace(layout, part_reference_at=(("R1", (1.5, -2.0, 0.0)),))
    routed = replace(
        edited,
        segments=(
            TrackSegment(x1=6, y1=6, x2=24, y2=6, layer="F.Cu", net_name="/SIG", width_mm=0.5),
        ),
    )
    output = render_native_routing_candidate(
        source, edited, routed, netlist, DEFAULT_PCB_RULE_PROFILE
    )
    before = extract_kicad_board_readback(source)
    after = extract_kicad_board_readback(output)
    assert after.footprints == before.footprints
    assert immutable_readback_matches(before, after)
    assert after.segments


def test_ordinary_route_request_uses_selected_budget_and_width():
    from types import SimpleNamespace

    from pcbsmith.execution import EXECUTION_PROFILES
    from pcbsmith.production_routing import _request as ordinary_request

    layout, netlist = _fixture()
    snapshot, _ = _snapshot(layout, netlist)
    entry = SimpleNamespace(
        budget_profile_name="deep", saved_board_sha256=snapshot.identity.board_sha256
    )
    request = ordinary_request(
        snapshot,
        layout,
        netlist,
        DEFAULT_PCB_RULE_PROFILE,
        entry,
        net_order=("/SIG",),
        net_widths={"/SIG": 0.8},
    )
    assert (
        request.budget.max_expansions_per_net
        == EXECUTION_PROFILES["deep"].work_budget.maximum_expansions
    )
    assert request.width_constraints[0].preferred_width_mm == 0.8


def test_profile_clearance_is_not_an_extra_all_layer_keepout():
    from pcbsmith.kicad.routing_candidate_adapter import _pairwise_clearance_groups

    layout, netlist = _fixture()
    snapshot, _ = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot)
    baseline = DEFAULT_PCB_RULE_PROFILE.fab_spacing.minimum_copper_clearance_mm
    request = request.model_copy(
        update={
            "clearance_constraints": (
                RouteClearanceConstraint(
                    constraint_id="baseline",
                    net_names=("/SIG",),
                    other_net_names=("/A", "/B"),
                    minimum_clearance_mm=baseline,
                ),
            )
        }
    )
    assert _pairwise_clearance_groups(request, DEFAULT_PCB_RULE_PROFILE) == ()
    stronger = request.model_copy(
        update={
            "clearance_constraints": (
                RouteClearanceConstraint(
                    constraint_id="stronger",
                    net_names=("/SIG",),
                    other_net_names=("/A", "/B"),
                    minimum_clearance_mm=baseline + 0.5,
                ),
            )
        }
    )
    assert len(_pairwise_clearance_groups(stronger, DEFAULT_PCB_RULE_PROFILE)) == 1


def test_native_save_comparison_allows_only_equivalent_metadata():
    from pcbsmith.kicad.library import QuotedString, _children, parse_sexpr, serialize_sexpr
    from pcbsmith.kicad.placement_readback import extract_kicad_board_readback
    from pcbsmith.production_routing import native_save_readback_matches

    layout, netlist = _fixture()
    tree = parse_sexpr(render_board_from_layout(netlist, layout))
    fp = _children(tree, "footprint")[0]
    extra = parse_sexpr('(property "Fixture" "x" (at 0 0) (layer "F.Fab"))')
    fp.append(extra)
    before = extract_kicad_board_readback(serialize_sexpr(tree))
    extra.append(["uuid", QuotedString("03c05c82-ad59-4c46-8514-9d032de2ccbb")])
    _children(extra, "at")[0].append("360")
    after = extract_kicad_board_readback(serialize_sexpr(tree))
    assert native_save_readback_matches(before, after)
    _children(fp, "at")[0][1] = "25.1"
    moved = extract_kicad_board_readback(serialize_sexpr(tree))
    assert not native_save_readback_matches(before, moved)


def test_pad_net_comparison_handles_kicad10_and_legacy_syntax(tmp_path):
    from pcbsmith.production_routing import _pin_nets

    for index, net in enumerate(('(net "/V")', '(net 1 "/V")')):
        board = tmp_path / f"syntax-{index}.kicad_pcb"
        board.write_text(
            '(kicad_pcb (footprint "Fixture:X" '
            '(property "Reference" "R1") '
            f'(pad "1" thru_hole circle {net})))',
            encoding="utf-8",
        )
        assert _pin_nets(board) == {("R1", "1"): "/V"}


def test_ordinary_routing_cli_rejection_has_nonzero_exit(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    import pcbsmith.production_routing as module

    data = tmp_path / "input.json"
    data.write_text("{}", encoding="utf-8")
    arguments = ["production-routing"]
    for flag in ("board", "layout", "netlist", "profile", "gate-inputs", "output"):
        arguments.extend(["--" + flag, str(data)])
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(module, "parse_canonical_board_layout_snapshot", lambda _: None)
    monkeypatch.setattr(module, "parse_canonical_board_netlist_snapshot", lambda _: None)
    parser = SimpleNamespace(model_validate_json=lambda _: None)
    monkeypatch.setattr(module, "PcbRuleProfile", parser)
    monkeypatch.setattr(module, "RoutingGateInputs", parser)
    monkeypatch.setattr(
        module,
        "route_saved_placement_candidate",
        lambda **_: SimpleNamespace(status=SimpleNamespace(value="rejected")),
    )
    with pytest.raises(SystemExit) as rejected:
        module.main()
    assert rejected.value.code == 2


@pytest.mark.parametrize("tamper", [None, "board", "result", "source"])
def test_revalidation_preserves_candidate_and_never_calls_engine(tmp_path, tamper):
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot)

    def rejected(*args):
        raise ValueError("synthetic validation unavailable")

    prior = run_routing_candidate_transaction(
        transaction_root=tmp_path / "prior",
        project_id="fixture",
        candidate_id="prior",
        generation_id="prior",
        request=request,
        input_snapshot=snapshot,
        input_payloads=payloads,
        source_layout=layout,
        netlist=netlist,
        engine_runner=_runner(layout, netlist),
        validator=rejected,
    )
    assert prior.candidate.partial_status is PartialCandidateStatus.COMPLETE
    result_file = tmp_path / "prior-result.json"
    result_file.write_text(prior.model_dump_json(), encoding="utf-8")
    digest = _sha256(result_file.read_bytes())
    retained = Path(prior.retained_directory)
    old_board = retained / "candidate" / snapshot.board_relative_path
    original = old_board.read_bytes()
    if tamper == "board":
        old_board.write_bytes(original + b"\n")
    if tamper == "result":
        result_file.write_bytes(result_file.read_bytes() + b"\n")
    if tamper == "source":
        (retained / "inputs" / snapshot.board_relative_path).write_bytes(b"changed")
    calls = []

    def forbidden(*args):
        calls.append(True)
        raise AssertionError("revalidation cannot call router")

    result = run_routing_candidate_transaction(
        transaction_root=tmp_path / "recheck",
        project_id="fixture",
        candidate_id="recheck",
        generation_id="recheck",
        request=request,
        input_snapshot=snapshot,
        input_payloads=payloads,
        source_layout=layout,
        netlist=netlist,
        engine_runner=forbidden,
        validator=_validator,
        revalidate_result=result_file,
        revalidate_sha256=digest,
    )
    assert not calls
    if tamper is None:
        assert result.status is RoutingCandidateTransactionStatus.ACCEPTED
        assert (
            Path(result.retained_directory) / "candidate" / snapshot.board_relative_path
        ).read_bytes() == original
        assert prior.status is RoutingCandidateTransactionStatus.REJECTED
    else:
        assert result.status is RoutingCandidateTransactionStatus.REJECTED
        assert not (tmp_path / "recheck/CURRENT.json").exists()


@pytest.mark.parametrize("native_fill", [False, True])
def test_plane_is_filled_before_validation_and_committed_with_exact_bytes(
    tmp_path, monkeypatch, native_fill
):
    """Synthetic board; real native fill case proves ownership, not board acceptance."""
    from pcbsmith.kicad.library import parse_sexpr, serialize_sexpr
    from pcbsmith.kicad.native_edits import children
    from pcbsmith.kicad.routing_candidate_adapter import NativePlanePour
    from pcbsmith.production_routing import native_save_readback_matches

    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    pour = NativePlanePour(net_name="/SIG")
    request = _request(layout, netlist, snapshot).model_copy(
        update={"additional_constraint_ids": (pour.constraint_id,)}
    )
    observed = []
    if not native_fill:

        def fake_fill(board, output, zone_ids):
            tree = parse_sexpr(board.read_text())
            zone = children(tree, "zone")[0]
            zone.append(
                parse_sexpr(
                    '(filled_polygon (layer "F.Cu") (pts (xy 41 41) (xy 42 41) (xy 42 42)))'
                )
            )
            return (serialize_sexpr(tree) + "\n").encode(), {}

        monkeypatch.setattr("pcbsmith.kicad.native_zone_edits.refill_native_edit", fake_fill)

    def validate(board, req, readback, work):
        assert "filled_polygon" in board.read_text()
        assert (board.parent / "project.kicad_pro").is_file()
        observed.append(board.read_bytes())
        if native_fill:
            from pcbsmith.kicad.final_fill_adapter import refill_and_read_kicad_board
            from pcbsmith.kicad.placement_readback import extract_kicad_board_readback

            again, _ = refill_and_read_kicad_board(board, work / "second-native-save")
            assert native_save_readback_matches(
                readback, extract_kicad_board_readback(again.read_text(encoding="utf-8"))
            )
        return _validator(board, req, readback, work)

    result = run_routing_candidate_transaction(
        transaction_root=tmp_path / "transaction",
        project_id="fixture",
        candidate_id="with-plane",
        generation_id="with-plane",
        request=request,
        input_snapshot=snapshot,
        input_payloads=payloads,
        source_layout=layout,
        netlist=netlist,
        engine_runner=lambda req, work: route_native_candidate(
            request=req, layout=layout, netlist=netlist, plane_pour=pour, native_serialization=True
        ),
        validator=validate,
    )
    assert result.status == RoutingCandidateTransactionStatus.ACCEPTED, result.failures
    assert len(observed) == 1
    assert result.validation.board_sha256 == _sha256(observed[0])
    assert (
        Path(result.retained_directory) / "candidate/design/fixture.kicad_pcb"
    ).read_bytes() == observed[0]


def test_native_annotation_nanometre_rounding_does_not_relax_copper():
    from pcbsmith.kicad.library import _children, parse_sexpr, serialize_sexpr
    from pcbsmith.kicad.placement_readback import extract_kicad_board_readback
    from pcbsmith.production_routing import native_save_readback_matches

    layout, netlist = _fixture()
    tree = parse_sexpr(render_board_from_layout(netlist, layout))
    fp = _children(tree, "footprint")[0]
    prop = _children(fp, "property")[0]
    at = _children(prop, "at")[0]
    at[2] = "-1.83"
    before = extract_kicad_board_readback(serialize_sexpr(tree))
    at[2] = "-1.829999"
    assert native_save_readback_matches(before, extract_kicad_board_readback(serialize_sexpr(tree)))
    at[2] = "-1.8299"
    assert not native_save_readback_matches(
        before, extract_kicad_board_readback(serialize_sexpr(tree))
    )
    at[2] = "-1.83"
    pad_at = _children(_children(fp, "pad")[0], "at")[0]
    pad_at[1] = str(float(pad_at[1]) + 0.000001)
    assert not native_save_readback_matches(
        before, extract_kicad_board_readback(serialize_sexpr(tree))
    )


@pytest.mark.parametrize("tamper", [None, "stdout", "stderr", "source", "candidate"])
def test_revalidate_early_external_log_rejection_without_engine(tmp_path, tamper):
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    request = _request(layout, netlist, snapshot)

    def misplaced_logs(req, work):
        candidate = _runner(layout, netlist)(req, work)
        folder = work / "freerouting/engine"
        folder.mkdir(parents=True)
        (folder / "stdout.log").write_bytes(b"synthetic external stdout\n")
        (folder / "stderr.log").write_bytes(b"synthetic diagnostic\n")
        return candidate.model_copy(update={
            "engine": candidate.engine.model_copy(update={"engine_id": "freerouting-v2.3.0"}),
            "termination": candidate.termination.model_copy(update={
                "stdout_sha256": _sha256((folder / "stdout.log").read_bytes()),
                "stderr_sha256": _sha256((folder / "stderr.log").read_bytes()),
            }),
        })

    common = dict(project_id="fixture", request=request, input_snapshot=snapshot,
                  input_payloads=payloads, source_layout=layout, netlist=netlist,
                  validator=_validator)
    prior = run_routing_candidate_transaction(
        transaction_root=tmp_path / "prior", candidate_id="prior", generation_id="prior",
        engine_runner=misplaced_logs, **common,
    )
    assert prior.status is RoutingCandidateTransactionStatus.REJECTED
    assert prior.failures[0].message == "ValueError: candidate stdout evidence hash is stale"
    root = Path(prior.retained_directory)
    assert not (root / "candidate" / snapshot.board_relative_path).exists()
    result_file = tmp_path / "prior-result.json"
    result_file.write_text(prior.model_dump_json(), encoding="utf-8")
    digest = _sha256(result_file.read_bytes())
    if tamper in {"stdout", "stderr"}:
        (root / "freerouting/engine" / f"{tamper}.log").write_bytes(b"tampered")
    elif tamper == "source":
        (root / "inputs" / snapshot.board_relative_path).write_bytes(b"tampered")
    elif tamper == "candidate":
        (root / "candidate-result.json").write_bytes(b"{}")

    def forbidden(*args):
        raise AssertionError("retained validation must never reroute")

    result = run_routing_candidate_transaction(
        transaction_root=tmp_path / "recheck", candidate_id="recheck", generation_id="recheck",
        engine_runner=forbidden, revalidate_result=result_file, revalidate_sha256=digest,
        **common,
    )
    assert (result.status is RoutingCandidateTransactionStatus.ACCEPTED) == (tamper is None)
    assert (root / "engine/stdout.log").read_bytes() == b""
