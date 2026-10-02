from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pcbsmith.board_job import BoardJob, JobState, JobStopped, input_identity
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.production_routing import _dispatch_routing_candidate
from pcbsmith.routing_policy import resolve_freerouting_config, routing_design_fingerprint


@pytest.fixture
def design(tmp_path):
    part = BoardComponent("R1", "1k", "Resistor:R_1206", "fixture")
    layout = BoardLayout(((part, 10),), (), (), 30, 25)
    netlist = BoardNetlist((part,), (BoardNet("/SIG", (("R1", "1"), ("R1", "2"))),))
    lp = tmp_path / "layout.json"
    np = tmp_path / "netlist.json"
    lp.write_text(canonical_board_layout_snapshot_json(layout))
    np.write_text(canonical_board_netlist_snapshot_json(netlist))
    return lp, np, layout, netlist


def test_default_configuration_prefers_project_and_explicit_choice(tmp_path, monkeypatch):
    monkeypatch.delenv("PCBSMITH_FREEROUTING_CONFIG", raising=False)
    local = tmp_path / ".pcbsmith/freerouting.json"
    local.parent.mkdir()
    local.write_text("{}")
    board = tmp_path / "project/board.kicad_pcb"
    assert resolve_freerouting_config(board) == local
    explicit = tmp_path / "override.json"
    explicit.write_text("{}")
    assert resolve_freerouting_config(board, explicit) == explicit
    monkeypatch.setenv("PCBSMITH_FREEROUTING_CONFIG", str(explicit))
    assert resolve_freerouting_config(board) == explicit
    with pytest.raises(ValueError, match="no native or manual fallback"):
        resolve_freerouting_config(board, tmp_path / "missing.json")
    monkeypatch.setenv("PCBSMITH_FREEROUTING_CONFIG", str(tmp_path / "missing-env.json"))
    with pytest.raises(ValueError, match="configuration missing"):
        resolve_freerouting_config(board)


def test_implicit_configuration_is_part_of_worker_identity(tmp_path, monkeypatch):
    config = tmp_path / "router.json"
    config.write_text('{"max_passes":10}')
    monkeypatch.setenv("PCBSMITH_FREEROUTING_CONFIG", str(config))
    monkeypatch.setattr("pcbsmith.board_job._IMPLEMENTATION_ROOT", tmp_path / "empty")
    args = ["--board", str(tmp_path / "board.kicad_pcb")]
    before = input_identity("pcbsmith.production_routing", args)
    config.write_text('{"max_passes":11}')
    assert before != input_identity("pcbsmith.production_routing", args)


def test_retry_identity_ignores_labels_values_and_requires_physical_change(design):
    lp, np, layout, netlist = design
    old = routing_design_fingerprint(lp, np)
    lp.write_text(
        canonical_board_layout_snapshot_json(
            replace(layout, part_reference_at=(("R1", (2, 2, 0)),))
        )
    )
    np.write_text(
        canonical_board_netlist_snapshot_json(
            replace(netlist, components=(replace(netlist.components[0], value="2k"),))
        )
    )
    assert routing_design_fingerprint(lp, np) == old
    lp.write_text(
        canonical_board_layout_snapshot_json(
            replace(layout, placements=((layout.placements[0][0], 11),))
        )
    )
    assert routing_design_fingerprint(lp, np) != old


def test_new_job_allows_one_retry_only_after_placement_change(tmp_path, design):
    lp, np, layout, netlist = design
    job = BoardJob(tmp_path / "job")
    state = job.start(complexity="simple", rationale="Synthetic automatic policy fixture")
    assert state.routing_policy == "freerouting-one-retry-v1"
    command = ("pcbsmith.production_routing", "--layout", str(lp), "--netlist", str(np))
    first = job.claim(operation="routing", phase="build", input_sha256="a" * 64, command=command)
    job.finish_attempt(first.token, status="failed", result={}, failure_signature="first")
    job.correction(reason="Placement blocks routing", change="Prepare an adjusted placement")
    with pytest.raises(JobStopped, match="placement or netlist change"):
        job.claim(
            operation="routing",
            phase="build",
            input_sha256="b" * 64,
            command=command + ("--routing-options", "different-order.json"),
        )
    lp.write_text(
        canonical_board_layout_snapshot_json(
            replace(layout, placements=((layout.placements[0][0], 12),))
        )
    )
    second = job.claim(operation="routing", phase="build", input_sha256="c" * 64, command=command)
    job.finish_attempt(second.token, status="passed", result={})
    job.correction(reason="A hypothetical further change", change="No further routing authorized")
    with pytest.raises(JobStopped, match="attempts exhausted"):
        job.claim(operation="routing", phase="build", input_sha256="d" * 64, command=command)
    assert len(job.snapshot().attempts) == 2


def test_old_state_without_policy_keeps_legacy_semantics(tmp_path):
    job = BoardJob(tmp_path)
    state = job.start(complexity="simple", rationale="Serialization-only fixture")
    historical = state.model_dump()
    historical.pop("routing_policy")
    old = JobState.model_validate(historical)
    assert old.routing_policy is None and "routing_policy" not in old.model_dump()


def test_external_failure_never_calls_native_router(tmp_path, monkeypatch):
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    calls = []

    def external(**kwargs):
        calls.append("external")
        raise RuntimeError("bounded external failure")

    def native(**kwargs):
        pytest.fail("Native fallback must not run")

    monkeypatch.setattr(
        "pcbsmith.kicad.freerouting_production.route_freerouting_production", external
    )
    monkeypatch.setattr("pcbsmith.production_routing.route_native_candidate", native)
    with pytest.raises(RuntimeError, match="external failure"):
        _dispatch_routing_candidate(
            None,
            tmp_path,
            board=tmp_path / "board",
            layout=None,
            netlist=None,
            profile=None,
            external=object(),
        )
    assert calls == ["external"]
    with pytest.raises(ValueError, match="explicit --legacy-native-reason"):
        _dispatch_routing_candidate(
            None,
            tmp_path,
            board=tmp_path / "board",
            layout=None,
            netlist=None,
            profile=None,
            external=None,
        )


def test_native_engine_requires_explicit_legacy_purpose(tmp_path, monkeypatch):
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    candidate = SimpleNamespace(partial_status=SimpleNamespace(value="fixture"))
    monkeypatch.setattr(
        "pcbsmith.production_routing.route_native_candidate", lambda **kwargs: candidate
    )
    assert (
        _dispatch_routing_candidate(
            None,
            tmp_path,
            board=tmp_path / "board",
            layout=None,
            netlist=None,
            profile=None,
            external=None,
            legacy_native_reason="Explicit frozen research reproduction",
        )
        is candidate
    )


def test_default_production_entry_preflights_freerouting_without_flag(tmp_path, monkeypatch):
    from tests.unit.kicad.test_routing_external_adapters import _binding

    from pcbsmith.kicad.freerouting_production import FreeroutingProductionConfig
    from pcbsmith.production_routing import route_saved_placement_candidate

    jar = tmp_path / "router.jar"
    jar.write_bytes(b"fixture")
    config = tmp_path / ".pcbsmith/freerouting.json"
    config.parent.mkdir()
    config.write_text(
        FreeroutingProductionConfig(
            binding=_binding(jar),
            java_executable="fixture-java",
            kicad_python="fixture-python",
            process_seconds=20,
            max_passes=4,
        ).model_dump_json()
    )
    monkeypatch.delenv("PCBSMITH_FREEROUTING_CONFIG", raising=False)
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    observed = []
    monkeypatch.setattr(
        FreeroutingProductionConfig, "preflight", lambda self: observed.append(self.backend)
    )
    gate = SimpleNamespace(
        evaluate=lambda: SimpleNamespace(allowed=False, blockers=["fixture stop after preflight"])
    )
    with pytest.raises(ValueError, match="fixture stop after preflight"):
        route_saved_placement_candidate(
            board=tmp_path / "board.kicad_pcb",
            layout=None,
            netlist=None,
            profile=None,
            gate_inputs=gate,
            output=tmp_path / "candidate",
        )
    assert observed == ["router:freerouting-v2.3.0"]
    assert not (tmp_path / "candidate").exists()


def test_partial_external_result_does_not_trigger_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    partial = SimpleNamespace(partial_status="partial")
    logs = tmp_path / "freerouting/engine"
    logs.mkdir(parents=True)
    (logs / "stdout.log").write_text("Synthetic partial router result")
    (logs / "stderr.log").write_text("")
    monkeypatch.setattr(
        "pcbsmith.kicad.freerouting_production.route_freerouting_production", lambda **kw: partial
    )
    monkeypatch.setattr(
        "pcbsmith.production_routing.route_native_candidate",
        lambda **kw: pytest.fail("Unexpected fallback"),
    )
    assert (
        _dispatch_routing_candidate(
            None,
            tmp_path,
            board=tmp_path / "board",
            layout=None,
            netlist=None,
            profile=None,
            external=object(),
        )
        is partial
    )


@pytest.mark.parametrize("with_metadata", [False, True])
def test_revalidation_restores_pinned_policy_and_budget(tmp_path, monkeypatch, with_metadata):
    import hashlib

    from tests.unit.kicad.test_routing_candidate_transaction import _fixture, _request, _snapshot

    from pcbsmith.kicad.routing_candidate_transaction import (
        freeze_native_routing_inputs,
        run_routing_candidate_transaction,
    )
    from pcbsmith.production_routing import _retained_routing_parameters
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    monkeypatch.setattr("pcbsmith.board_job.require_worker", lambda *args: None)
    layout, netlist = _fixture()
    snapshot, payloads = _snapshot(layout, netlist)
    metadata = (
        {
            "evidence/freerouting-config.json": b'{"fixture":true}',
            "evidence/routing-policy.json": b'{"automatic_fallback":false}',
        }
        if with_metadata
        else {}
    )
    payloads.update(metadata)
    snapshot = freeze_native_routing_inputs(
        payloads=payloads,
        roles={k: "evidence" for k in payloads},
        board_relative_path=snapshot.board_relative_path,
        schematic_relative_paths=snapshot.schematic_relative_paths,
        layout=layout,
        netlist=netlist,
        profile=DEFAULT_PCB_RULE_PROFILE,
    )
    request = _request(layout, netlist, snapshot)
    if with_metadata:
        request = type(request).model_validate(
            {
                **request.model_dump(),
                "budget": {
                    "max_passes": 5,
                    "max_expansions": 0,
                    "max_expansions_per_net": 0,
                    "max_stagnant_passes": 0,
                    "max_exact_check_rejections": 0,
                    "external_process_seconds": 15,
                },
            }
        )

    def stop(*args):
        raise ValueError("Synthetic stop before routing")

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
        engine_runner=stop,
        validator=stop,
    )
    result = tmp_path / "result.json"
    result.write_text(prior.model_dump_json())
    digest = hashlib.sha256(result.read_bytes()).hexdigest()
    restored, budget = _retained_routing_parameters(result, digest)
    assert restored == metadata and budget == request.budget
    if with_metadata:
        (Path(prior.retained_directory) / "inputs/evidence/freerouting-config.json").write_bytes(
            b"changed"
        )
        with pytest.raises(ValueError, match="settings changed"):
            _retained_routing_parameters(result, digest)
    with pytest.raises(ValueError, match="result changed"):
        _retained_routing_parameters(result, "0" * 64)


@pytest.mark.parametrize(
    "case",
    ["valid", "ordinary", "local-design", "adapter-changed", "evidence-changed", "foreign-token"],
)
def test_diagnosed_adapter_recovery_preserves_design_and_attempt_limit(
    tmp_path, design, monkeypatch, case
):
    import hashlib

    from tests.unit.test_board_job import Clock
    from tests.unit.test_board_job_diagnostic import assessment

    from pcbsmith.board_job import ContinuationRequest

    lp, np, _, _ = design
    clock = Clock()
    job = BoardJob(tmp_path / "job", clock=clock, monotonic=clock)
    job.start(complexity="simple", rationale="Synthetic adapter recovery")
    command = ("pcbsmith.production_routing", "--layout", str(lp), "--netlist", str(np))
    first = job.claim(operation="routing", phase="build", input_sha256="a" * 64, command=command)
    job.finish_attempt(
        first.token, status="failed", result={}, failure_signature="adapter exception"
    )
    job.begin_diagnostic("Inspect the retained adapter exception")
    report = assessment(job.root)
    if case == "local-design":
        report = report.model_copy(update={"cause": "local_design", "action": "local_edit"})
    job.complete_diagnostic(report)
    report_file = job.root / "assessment.json"
    report_file.write_text(report.model_dump_json())
    implementation = tmp_path / "implementation"
    adapter = implementation / "kicad/freerouting_production.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("qualified synthetic adapter")
    monkeypatch.setattr("pcbsmith.board_job._IMPLEMENTATION_ROOT", implementation)
    retained = job.root / "qualified-adapter.py"
    retained.write_bytes(adapter.read_bytes())
    sha = hashlib.sha256(retained.read_bytes()).hexdigest()
    clock.now += 2000
    request = ContinuationRequest(
        predecessor_sha256=hashlib.sha256(job.path.read_bytes()).hexdigest(),
        assessment_file="assessment.json",
        assessment_sha256=hashlib.sha256(report_file.read_bytes()).hexdigest(),
        authorization_reference="Explicit synthetic authorization after adapter repair",
        seconds=600,
        reserve_seconds=120,
        build_operations=("routing",),
        blocker_resolution="Synthetic adapter fixed and qualified independently",
        resolved_evidence={"qualified-adapter.py": sha},
        retry_failed_operations={"routing": "foreign" if case == "foreign-token" else first.token},
        routing_adapter_repair_sha256=None if case == "ordinary" else sha,
    )
    if case in {"local-design", "foreign-token"}:
        before = job.path.read_bytes()
        with pytest.raises(JobStopped, match="diagnosed platform|latest failed"):
            job.continue_authorized(request)
        assert job.path.read_bytes() == before
        return
    job.continue_authorized(request)
    if case == "adapter-changed":
        adapter.write_text("unqualified adapter")
    if case == "evidence-changed":
        retained.write_text("changed evidence")
    if case != "valid":
        with pytest.raises(
            JobStopped, match="placement or netlist|adapter changed|evidence changed"
        ):
            job.claim(operation="routing", phase="build", input_sha256="b" * 64, command=command)
        assert len(job.snapshot().attempts) == 1
        return
    second = job.claim(operation="routing", phase="build", input_sha256="b" * 64, command=command)
    assert second.routing_design_sha256 == first.routing_design_sha256
    job.finish_attempt(second.token, status="passed", result={})
    with pytest.raises(JobStopped, match="one attempt"):
        job.claim(operation="routing", phase="build", input_sha256="c" * 64, command=command)
    state = job.snapshot()
    assert len(state.attempts) == 2 and state.cycle == 0 and state.deadline == 2800


@pytest.mark.parametrize(
    "case",
    [
        "transaction-return",
        "transaction-error",
        "geometry-mismatch",
        "asset-mismatch",
        "source-mutation",
    ],
)
def test_production_routing_retains_project_footprint_scope(tmp_path, monkeypatch, case):
    """Real layout/asset checks surround a synthetic transaction; no engine is run."""
    import hashlib
    import json

    from pcbsmith.kicad.board import render_board_from_layout
    from pcbsmith.kicad.board_serialization import board_layout_snapshot_fingerprint
    from pcbsmith.kicad.library import (
        _PROJECT_FOOTPRINTS,
        _PROJECT_LIBRARY_NAMES,
        load_footprint,
    )
    from pcbsmith.kicad.project_dependencies import project_footprint_scope
    from pcbsmith.production_routing import route_saved_placement_candidate
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    local = tmp_path / "PrivateGauge.pretty/Gauge.kicad_mod"
    local.parent.mkdir()
    local.write_text(
        '(footprint "Gauge" (layer "F.Cu") '
        '(pad "1" thru_hole circle (at 0 0) (size 2.5 2.5) '
        '(drill 0.8) (layers "*.Cu" "*.Mask")))'
    )
    key = "PrivateGauge:Gauge"
    (tmp_path / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "PrivateGauge") (uri "${KIPRJMOD}/PrivateGauge.pretty")))'
    )
    (tmp_path / "library-sources.json").write_text(
        json.dumps(
            [
                {
                    "kind": "footprint",
                    "id": key,
                    "sha256": hashlib.sha256(local.read_bytes()).hexdigest(),
                }
            ]
        )
    )
    parts = tuple(BoardComponent(f"J{i}", "PROBE", key, f"fixture/j{i}") for i in (1, 2))
    netlist = BoardNetlist(parts, (BoardNet("/SIG", (("J1", "1"), ("J2", "1"))),))
    layout = BoardLayout(((parts[0], 6), (parts[1], 24)), (), (), 30, 20)
    board = tmp_path / "fixture.kicad_pcb"
    with project_footprint_scope(tmp_path):
        board.write_text(render_board_from_layout(netlist, layout))
    board.with_suffix(".kicad_sch").write_text("(kicad_sch (version 20260101))")
    board.with_suffix(".kicad_pro").write_text('{"board": {}}')
    if case == "geometry-mismatch":
        wrong = replace(layout, placements=((parts[0], 7), (parts[1], 24)))
        with project_footprint_scope(tmp_path):
            board.write_text(render_board_from_layout(netlist, wrong))
    if case == "asset-mismatch":
        local.write_text(local.read_text().replace("(drill 0.8)", "(drill 1.0)"))
    source = board.read_bytes()
    entry = SimpleNamespace(
        allowed=True,
        saved_board_sha256=hashlib.sha256(source).hexdigest(),
        saved_layout_fingerprint=board_layout_snapshot_fingerprint(
            canonical_board_layout_snapshot_json(layout)
        ),
        deferred_routed_features=(),
        budget_profile_name="standard",
        model_dump_json=lambda **kw: '{"synthetic_unit_fixture":true}',
    )
    gate = SimpleNamespace(
        evaluate=lambda: entry,
        engineering_gate=SimpleNamespace(
            context=SimpleNamespace(
                board_netlist_snapshot_json=canonical_board_netlist_snapshot_json(netlist)
            )
        ),
        context=SimpleNamespace(project_id="scope-fixture"),
        routed_engineering_source_sha256=None,
        model_dump_json=lambda **kw: '{"synthetic_unit_fixture":true}',
    )
    calls = []
    returned = {"synthetic_unit_fixture": True}

    def transaction(**kwargs):
        calls.append("transaction")
        assert load_footprint(key).source_file == local.resolve()
        assert (
            kwargs["input_payloads"]["design/PrivateGauge.pretty/Gauge.kicad_mod"]
            == local.read_bytes()
        )
        if case == "transaction-error":
            raise RuntimeError("intentional transaction failure")
        if case == "source-mutation":
            board.write_bytes(source + b"\n")
        return returned

    monkeypatch.setattr(
        "pcbsmith.production_routing.run_routing_candidate_transaction", transaction
    )
    previous = (_PROJECT_FOOTPRINTS.get(), _PROJECT_LIBRARY_NAMES.get())
    kwargs = dict(
        board=board,
        layout=layout,
        netlist=netlist,
        profile=DEFAULT_PCB_RULE_PROFILE,
        gate_inputs=gate,
        output=tmp_path / "candidate",
        legacy_native_reason="Unit boundary fixture; no engine",
    )
    if case == "transaction-return":
        assert route_saved_placement_candidate(**kwargs) is returned
    else:
        errors = {
            "transaction-error": (RuntimeError, "intentional transaction failure"),
            "geometry-mismatch": (ValueError, "detached layout does not match"),
            "asset-mismatch": (ValueError, "footprint hash mismatch"),
            "source-mutation": (ValueError, "routing changed source project inputs"),
        }
        error, message = errors[case]
        with pytest.raises(error, match=message):
            route_saved_placement_candidate(**kwargs)
    assert (_PROJECT_FOOTPRINTS.get(), _PROJECT_LIBRARY_NAMES.get()) == previous
    assert calls == ([] if case in {"geometry-mismatch", "asset-mismatch"} else ["transaction"])
    if case != "source-mutation":
        assert board.read_bytes() == source
