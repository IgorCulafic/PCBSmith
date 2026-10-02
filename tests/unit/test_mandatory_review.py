"""Negative controls for mandatory review; no real-board acceptance claims."""

import json

import pytest
from tests.unit.test_production_readiness import readiness_fixture

from pcbsmith.board_handover import inspect_handover
from pcbsmith.mandatory_review import (
    MandatoryReview,
    native_rule_blockers,
    require_diagnostic_coverage,
    require_engineering_coverage,
    require_mandatory_review,
)
from pcbsmith.production_readiness import require_predesign_bundle
from pcbsmith.routed_copper_graph_ir import fingerprint


@pytest.mark.parametrize("missing", ["component-readiness", "mandatory-review"])
def test_omission_does_not_select_legacy_acceptance(tmp_path, missing):
    _, root, request = readiness_fixture(tmp_path)
    bundle = request.predesign.model_copy(
        update={
            "evidence_files": {
                k: v for k, v in request.predesign.evidence_files.items() if k != missing
            }
        }
    )
    with pytest.raises(ValueError, match="requires"):
        require_predesign_bundle(bundle, root)


@pytest.mark.parametrize(
    "change",
    [
        "missing_topic",
        "blank_observation",
        "stale_component",
        "stale_brief",
        "unresolved",
        "missing_source",
        "isolation",
    ],
)
def test_incomplete_or_stale_mandatory_review_blocks(tmp_path, change):
    from pcbsmith.manufacturing_lineage import file_sha256
    from pcbsmith.production_readiness import ReadinessEvidenceFile

    _, root, request = readiness_fixture(tmp_path)
    path = root / "mandatory-review.json"
    data = json.loads(path.read_bytes())
    if change == "missing_topic":
        data["applicability"].pop("high_speed")
    elif change == "blank_observation":
        next(iter(data["components"].values()))["observations"]["ratings"] = " "
    elif change == "stale_component":
        data["component_readiness_sha256"] = "a" * 64
    elif change == "stale_brief":
        data["brief_sha256"] = "b" * 64
    elif change == "unresolved":
        data["applicability"]["bga"]["disposition"] = "unresolved"
    elif change == "missing_source":
        data["applicability"]["bga"]["evidence_ids"] = ["absent"]
    elif change == "isolation":
        data["applicability"]["isolation_cam"]["disposition"] = "applicable"
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
    with pytest.raises(ValueError):
        require_mandatory_review(bundle, root)


def test_rule_exceptions_are_exact_and_cannot_disable_required_rules(tmp_path):
    board, root, request = readiness_fixture(tmp_path)
    policy = require_mandatory_review(request.predesign, root)
    assert not native_rule_blockers(policy, board.with_suffix(".kicad_pro"), {"drc": {}})
    ignored = {"ignored_checks": ["optional_rule"]}
    issue = "drc:ignored:" + fingerprint("optional_rule")
    assert (
        issue in native_rule_blockers(policy, board.with_suffix(".kicad_pro"), {"drc": ignored})[0]
    )
    data = policy.model_dump(mode="json")
    data["rule_exceptions"] = [
        {
            "issue_id": issue,
            "rationale": "Software-only exclusion test",
            "authorization_evidence_id": "fixture:source",
        }
    ]
    scoped = MandatoryReview.model_validate(data)
    assert not native_rule_blockers(scoped, board.with_suffix(".kicad_pro"), {"drc": ignored})
    assert native_rule_blockers(
        scoped, board.with_suffix(".kicad_pro"), {"drc": {"ignored_checks": ["clearance"]}}
    )
    assert native_rule_blockers(
        scoped, board.with_suffix(".kicad_pro"), {"drc": {"ignored_checks": ["different_rule"]}}
    )


def test_applicable_engineering_and_diagnostics_cannot_be_omitted(tmp_path):
    from tests.unit.test_production_readiness import fixture_review
    from tests.unit.test_project_engineering_gate import _context

    from pcbsmith.project_engineering_gate import evaluate_project_engineering_gate
    from pcbsmith.project_engineering_gate_ir import Phase14EvaluationBundle

    board, root, request = readiness_fixture(tmp_path)
    policy = require_mandatory_review(request.predesign, root)
    # Declared return-path feature contradicts the no-feature policy.
    gate = evaluate_project_engineering_gate(_context(), Phase14EvaluationBundle(), ())
    with pytest.raises(ValueError, match="return_adjacency"):
        require_engineering_coverage(policy, gate)
    data = policy.model_dump(mode="json")
    data["applicability"]["high_speed"]["disposition"] = "applicable"
    with pytest.raises(ValueError, match="high_speed"):
        require_diagnostic_coverage(
            MandatoryReview.model_validate(data), fixture_review(board, tmp_path / "views")
        )


def test_handover_does_not_accept_finished_job_or_missing_release(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(
        json.dumps(
            {
                "generation_root": "absent",
                "board": "absent.pcb",
                "release_report": "absent.json",
                "job_status": "finished",
            }
        )
    )
    report = inspect_handover(path)
    assert not report["cad_handover_ready"]
    assert report["blockers"]


@pytest.mark.parametrize("kind,rule", [("erc", "pin_not_connected"), ("drc", "clearance")])
def test_kicad_10_ignored_object_cannot_waive_required_rule(tmp_path, kind, rule):
    board, root, request = readiness_fixture(tmp_path)
    policy = require_mandatory_review(request.predesign, root)
    value = {"key": rule, "description": "Synthetic disabled required rule"}
    data = policy.model_dump(mode="json")
    data["required_native_rules"][kind] = [rule]
    data["rule_exceptions"] = [
        {
            "issue_id": f"{kind}:ignored:" + fingerprint(value),
            "rationale": "Even an explicit exception must not waive a required rule",
            "authorization_evidence_id": "fixture:source",
        }
    ]
    blockers = native_rule_blockers(
        MandatoryReview.model_validate(data),
        board.with_suffix(".kicad_pro"),
        {kind: {"ignored_checks": [value]}},
    )
    assert f"required native rule is disabled: {kind}:{rule}" in blockers


def test_combined_worklist_includes_both_families_without_creating_decisions(tmp_path):
    from pcbsmith.mandatory_review import native_rule_worklist

    board, root, request = readiness_fixture(tmp_path)
    policy = require_mandatory_review(request.predesign, root)
    reports = {kind: {"ignored_checks": [{"key": kind + "_optional"}]} for kind in ("erc", "drc")}
    result = native_rule_worklist(policy, board.with_suffix(".kicad_pro"), reports)
    assert not result["ready"]
    assert {item["kind"] for item in result["items"]} == {"erc", "drc"}
    assert all(item["decision"] is None for item in result["items"])
    result = native_rule_worklist(policy, board.with_suffix(".kicad_pro"), {"drc": {}})
    assert "missing native report: erc" in result["blockers"]


@pytest.mark.parametrize("fault", [None, "source", "report", "severity", "failed", "findings"])
def test_native_review_requires_actual_current_process_and_report(tmp_path, fault):
    from pcbsmith.mandatory_review import require_bound_native_report
    from pcbsmith.manufacturing_lineage import file_sha256

    board, _, _ = readiness_fixture(tmp_path)
    source = board.with_suffix(".kicad_sch")
    report = tmp_path / "erc.json"
    data = {
        "$schema": "https://schemas.kicad.org/erc.v1.json",
        "source": source.name,
        "kicad_version": "10.0-test",
        "sheets": [{"violations": [{"type": "bad"}] if fault == "findings" else []}],
    }
    report.write_text(json.dumps(data))
    process = {
        "command": ["kicad-cli", "sch", "erc", "--severity-all"],
        "input_sha256s": {
            str(p): file_sha256(p) for p in (source, board.with_suffix(".kicad_pro"))
        },
        "report_sha256": file_sha256(report),
        "returncode": 0,
    }
    if fault == "source":
        source.write_text(source.read_text() + " ")
    elif fault == "report":
        report.write_text(report.read_text() + " ")
    elif fault == "severity":
        process["command"].remove("--severity-all")
    elif fault == "failed":
        process["returncode"] = 1
    report.with_suffix(".process.json").write_text(json.dumps(process))
    if fault:
        with pytest.raises(ValueError):
            require_bound_native_report(board, "erc", report)
    else:
        assert require_bound_native_report(board, "erc", report) == data


@pytest.mark.parametrize("fault", [None, "predecessor", "native", "source", "replace", "weaken"])
def test_review_completion_only_adds_bound_observations(tmp_path, fault):
    from pcbsmith.mandatory_review import require_native_review_completion
    from pcbsmith.manufacturing_lineage import file_sha256, native_input_hashes

    board, root, request = readiness_fixture(tmp_path)
    original = require_mandatory_review(request.predesign, root)
    source = tmp_path / "observations.txt"
    source.write_text("Synthetic source inspection; not real board evidence")
    digest = request.predesign.evidence_files["mandatory-review"].sha256
    completion = {
        "schema_id": "pcbsmith-native-review-completion-v1",
        "predecessor_review_sha256": digest,
        "native_inputs": native_input_hashes(board),
        "reviewer": "test",
        "authorization_reference": "synthetic authorization",
        "rule_exceptions": [
            {
                "issue_id": "erc:ignored:" + fingerprint("optional"),
                "rationale": "Synthetic exception",
                "authorization_evidence_id": "observation",
            }
        ],
        "evidence_files": {
            "observation": {"relative_path": source.name, "sha256": file_sha256(source)}
        },
    }
    if fault == "predecessor":
        completion["predecessor_review_sha256"] = "a" * 64
    elif fault == "native":
        completion["native_inputs"] = {}
    elif fault == "source":
        source.write_text("changed")
    elif fault == "replace":
        from pcbsmith.mandatory_review import RuleException

        original = original.model_copy(
            update={
                "rule_exceptions": (RuleException.model_validate(completion["rule_exceptions"][0]),)
            }
        )
    elif fault == "weaken":
        completion["minimum_board_rules"] = {}
    path = tmp_path / "completion.json"
    path.write_text(json.dumps(completion))
    if fault:
        with pytest.raises(ValueError):
            require_native_review_completion(original, digest, board, path)
    else:
        updated = require_native_review_completion(original, digest, board, path)
        assert updated.model_dump(exclude={"rule_exceptions"}) == original.model_dump(
            exclude={"rule_exceptions"}
        )
        assert len(updated.rule_exceptions) == len(original.rule_exceptions) + 1


def test_registered_guard_retains_both_omissions_before_rendering(tmp_path, monkeypatch):
    from pcbsmith.manufacturing_lineage import file_sha256
    from pcbsmith.production_generators import _guarded_readiness_drc

    board, root, request = readiness_fixture(tmp_path)
    reports = tmp_path / "checks"
    reports.mkdir()

    def make_report(kind, output):
        source = board if kind == "drc" else board.with_suffix(".kicad_sch")
        data = {
            "$schema": f"https://schemas.kicad.org/{kind}.v1.json",
            "source": source.name,
            "kicad_version": "10.0-test",
            "ignored_checks": [{"key": kind + "_optional"}],
        }
        data.update(
            {"sheets": [{"violations": []}]}
            if kind == "erc"
            else {"violations": [], "unconnected_items": [], "schematic_parity": []}
        )
        output.write_text(json.dumps(data))
        output.with_suffix(".process.json").write_text(
            json.dumps(
                {
                    "command": [
                        "kicad-cli",
                        "sch" if kind == "erc" else "pcb",
                        kind,
                        "--severity-all",
                        "--schematic-parity",
                    ],
                    "returncode": 0,
                    "report_sha256": file_sha256(output),
                    "input_sha256s": {
                        str(p): file_sha256(p)
                        for p in (
                            board,
                            board.with_suffix(".kicad_sch"),
                            board.with_suffix(".kicad_pro"),
                        )
                    },
                }
            )
        )

    monkeypatch.setattr(
        "pcbsmith.production_generators.require_publication_request", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "pcbsmith.kicad.kicad_validate.run_native_erc_check",
        lambda source, output: make_report("erc", output),
    )
    with pytest.raises(ValueError, match="Combined native review blocked"):
        _guarded_readiness_drc(
            request,
            root,
            "fixture",
            board,
            reports / "drc.json",
            lambda board, output: make_report("drc", output),
        )
    retained = json.loads((reports / "native-rule-worklist.json").read_bytes())
    assert {item["kind"] for item in retained["items"]} == {"erc", "drc"}
    assert not retained["ready"]


@pytest.mark.parametrize("fault", [None, "stale_board", "stale_report", "conflicting_execution"])
def test_release_assembles_only_actual_native_execution(tmp_path, monkeypatch, fault):
    from pcbsmith.applicability_execution import (
        ApplicableCheckRequirement,
        CheckExecutionRecord,
        ProjectApplicabilityExecutionManifest,
        ProjectCheckApplicability,
        ProjectCheckDisposition,
    )
    from pcbsmith.manufacturing_lineage import file_sha256
    from pcbsmith.production_workflow import assemble_routed_release_execution

    board, _, _ = readiness_fixture(tmp_path)
    digest = file_sha256(board)
    requirement = ApplicableCheckRequirement.build(
        check_id="pending-engineering",
        rule_ids=("test",),
        applicability=ProjectCheckApplicability.APPLICABLE,
        applicability_authority_id="test",
        exact_input_sha256s=(digest,),
        minimum_evaluated_objects=1,
        rationale="Synthetic unresolved engineering requirement",
    )
    report = tmp_path / "drc.json"
    report.write_text("{}")
    record = CheckExecutionRecord.build(
        check_id="kicad.drc",
        producer_id="kicad-cli.pcb.drc",
        tool_version="test",
        exact_input_sha256s=(digest,),
        evaluated_object_count=1,
        disposition=ProjectCheckDisposition.PASS,
        result_sha256=file_sha256(report),
        limitations=(),
    )
    report.with_suffix(".execution.json").write_text(record.model_dump_json())
    executions = ()
    if fault == "conflicting_execution":
        executions = (
            CheckExecutionRecord.build(
                check_id="kicad.drc",
                producer_id="kicad-cli.pcb.drc",
                tool_version="different",
                exact_input_sha256s=(digest,),
                evaluated_object_count=1,
                disposition=ProjectCheckDisposition.PASS,
                result_sha256=file_sha256(report),
                limitations=(),
            ),
        )
    manifest = ProjectApplicabilityExecutionManifest.build(
        project_id="test",
        saved_design_sha256=digest,
        requirements=(requirement,),
        executions=executions,
    )
    # Binding replay has separate positive/stale-source controls above.
    monkeypatch.setattr("pcbsmith.mandatory_review.require_bound_native_report", lambda *a: {})
    if fault == "stale_board":
        board.write_bytes(board.read_bytes() + b" ")
    if fault == "stale_report":
        report.write_text("changed")
    if fault:
        with pytest.raises(ValueError):
            assemble_routed_release_execution(manifest, board, report)
    else:
        assembled = assemble_routed_release_execution(manifest, board, report)
        assert record in assembled.executions
        assert requirement in assembled.requirements
        assert assembled.authority.value == "blocked"  # Does not manufacture other checks.
        assert assemble_routed_release_execution(assembled, board, report) == assembled
