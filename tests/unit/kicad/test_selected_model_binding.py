"""Synthetic early-selection/replay controls; no package or visual qualification."""

from __future__ import annotations

import hashlib
import json

import pytest
from tests.unit.kicad.test_component_readiness import _save_report, native  # noqa: F401
from tests.unit.kicad.test_component_readiness import inventory as base_inventory  # noqa: F401
from tests.unit.test_production_readiness import readiness_fixture

from pcbsmith.kicad.component_readiness import (
    SelectedModelPolicy,
    inspect_component_readiness,
    require_component_readiness_snapshot,
)
from pcbsmith.kicad.model_preflight import preflight_board_models
from pcbsmith.production_readiness import (
    ReadinessEvidenceFile,
    _require_selected_board_models,
    require_predesign_bundle,
)


@pytest.fixture
def inventory(request):
    return request.getfixturevalue("base_inventory")


def policy_fixture(root):
    model = root / "models/missing.step"
    model.parent.mkdir(exist_ok=True)
    model.write_text("Synthetic model bytes, not a renderable STEP file", encoding="utf-8")
    policy = {
        "applicability": "applicable",
        "rationale": "Synthetic proxy policy",
        "requirements": [{"reference": "U1", "accepted_classifications": ["proxy"]}],
        "registry": [
            {
                "raw_path": "${KIPRJMOD}/models/missing.step",
                "local_path": "models/missing.step",
                "classification": "proxy",
                "license_status": "synthetic fixture",
                "expected_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "expected_transform": {},
            }
        ],
    }
    save_policy(root, policy)
    return policy


def save_policy(root, policy):
    (root / "component-model-selection.json").write_text(json.dumps(policy), encoding="utf-8")


def test_selected_models_pass_and_bind_before_approval(inventory):
    spec, root, _ = inventory
    policy_fixture(root)
    result = inspect_component_readiness(spec, root)
    assert result["selected_models"]["status"] == "passed"
    assert result["selected_models"]["assessment"]["models"][0]["classification"] == "proxy"
    output, digest = _save_report(spec, root)
    require_component_readiness_snapshot(output, root, digest, require_selected_models=True)
    (root / "models/missing.step").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Selected model preflight failed"):
        require_component_readiness_snapshot(output, root, digest, require_selected_models=True)


def test_missing_policy_cannot_seal_new_preparation(inventory):
    spec, root, _ = inventory
    output, digest = _save_report(spec, root)
    with pytest.raises(ValueError, match="explicit selected model policy"):
        require_component_readiness_snapshot(output, root, digest, require_selected_models=True)


def test_explicit_not_applicable_remains_supported(inventory):
    spec, root, _ = inventory
    save_policy(root, {"applicability": "not_applicable", "rationale": "2D-only fixture"})
    output, digest = _save_report(spec, root)
    require_component_readiness_snapshot(output, root, digest, require_selected_models=True)
    assert inspect_component_readiness(spec, root)["selected_models"]["status"] == "not_applicable"


@pytest.mark.parametrize(
    "change",
    [
        "hash",
        "transform",
        "classification",
        "coverage",
        "missing_hash",
        "missing_transform",
        "duplicate",
    ],
)
def test_invalid_selection_rejected_before_layout(inventory, change):
    spec, root, _ = inventory
    policy = policy_fixture(root)
    entry = policy["registry"][0]
    if change == "hash":
        entry["expected_sha256"] = "0" * 64
    elif change == "transform":
        entry["expected_transform"] = {"offset_xyz": ["0", "0", "4"]}
    elif change == "classification":
        policy["requirements"][0]["accepted_classifications"] = ["exact_package"]
    elif change == "coverage":
        policy["requirements"][0]["reference"] = "U2"
    elif change == "duplicate":
        policy["registry"].append(dict(entry))
    else:
        entry.pop("expected_sha256" if change == "missing_hash" else "expected_transform")
    save_policy(root, policy)
    with pytest.raises(ValueError):
        inspect_component_readiness(spec, root)


def publication_fixture(tmp_path, inventory):
    spec, root, fp = inventory
    policy_fixture(root)
    early = inspect_component_readiness(spec, root)
    board, evidence, request = readiness_fixture(tmp_path / "publication")
    # Selected footprint itself is the saved-board fixture, with its exact model clauses.
    board.write_text(
        "(kicad_pcb "
        + fp.read_text(encoding="utf-8").replace(
            '(footprint "DIP"',
            '(footprint "Test:DIP" (property "Reference" "U1") (property "Value" "PART")',
        )
        + ")",
        encoding="utf-8",
    )
    record = evidence / "component-readiness.json"
    record.write_text(json.dumps(early), encoding="utf-8")
    bundle = request.predesign.model_copy(
        update={
            "evidence_files": {
                **request.predesign.evidence_files,
                "component-readiness": ReadinessEvidenceFile(
                    relative_path=record.name,
                    sha256=hashlib.sha256(record.read_bytes()).hexdigest(),
                ),
            }
        }
    )
    policy = SelectedModelPolicy.model_validate(early["selected_models"]["policy"])
    actual = preflight_board_models(
        board,
        registry=policy.registry,
        requirements=policy.requirements,
        applicability=policy.applicability,
        applicability_rationale=policy.rationale,
    )
    from tests.unit.mandatory_review_fixtures import rebind_mandatory_fixture

    bundle = rebind_mandatory_fixture(bundle, evidence)
    return board, evidence, bundle, actual


def test_publication_replays_same_policy(inventory, tmp_path):
    board, evidence, bundle, actual = publication_fixture(tmp_path, inventory)
    require_predesign_bundle(bundle, evidence)
    _require_selected_board_models(bundle, evidence, board, actual)


@pytest.mark.parametrize("change", ["claim", "transform", "remove", "extra", "hash"])
def test_publication_cannot_weaken_early_selection(inventory, tmp_path, change):
    board, evidence, bundle, actual = publication_fixture(tmp_path, inventory)
    if change == "claim":
        actual = actual.model_copy(update={"required_references": ()})
    elif change == "hash":
        (inventory[1] / "models/missing.step").write_text("changed", encoding="utf-8")
    else:
        text = board.read_text(encoding="utf-8")
        if change == "transform":
            text = text.replace('missing.step")', 'missing.step" (offset (xyz 0 0 2)))')
        elif change == "remove":
            text = text.replace('(model "${KIPRJMOD}/models/missing.step")', "")
        else:
            text = text.replace("(model ", '(model "${KIPRJMOD}/models/missing.step") (model ')
        board.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        _require_selected_board_models(bundle, evidence, board, actual)


@pytest.mark.parametrize("input_fault", [None, "changed-source", "overload"])
def test_complete_prepare_approve_publish_with_bound_inventory(
    inventory, tmp_path, monkeypatch, input_fault
):
    """Exercise real adapters; native/render/worker fixtures are explicitly synthetic."""
    from tests.unit.test_production_readiness import fixture_review
    from tests.unit.test_production_workflow import _empty_component_review

    from pcbsmith.kicad.floorplan import FILES
    from pcbsmith.manufacturing_lineage import file_sha256, native_input_hashes
    from pcbsmith.predesign_preparation import approve_prepared_predesign, prepare_predesign_inputs
    from pcbsmith.production_generators import persist_registered_placement_candidate
    from pcbsmith.production_readiness import readiness_blockers

    spec, root, fp = inventory
    from pcbsmith.native_project import inspect_native_input_closure

    part = spec.parts[0].model_copy(update={"pins": {"1": "V", "2": "V", "3": "GND"}})
    spec = spec.model_copy(update={"parts": (part,)})
    (root / "design-spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    xml = root / ".pcbsmith/kicad/closure.net.xml"
    xml.write_text(
        xml.read_text(encoding="utf-8")
        .replace('<node ref="U1" pin="1"/>', '<node ref="U1" pin="1"/><node ref="U1" pin="2"/>')
        .replace(
            '<net name="/GND"><node ref="U1" pin="2"/>', '<net name="/GND"><node ref="U1" pin="3"/>'
        ),
        encoding="utf-8",
    )
    _, closure = inspect_native_input_closure(spec, root / "closure.kicad_sch", xml)
    (root / "netlist-vs-intent.json").write_text(json.dumps(closure), encoding="utf-8")
    policy_fixture(root)
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    prepared = root / "complete-preparation"
    prepare_predesign_inputs(root / "design-spec.json", root, prepared)
    fixture_board, fixture_evidence, fixture_request = readiness_fixture(tmp_path / "publication")
    prior = fixture_request.predesign.readiness
    engineering = {
        "component_alternatives": [
            {
                "intent": review.intent.model_dump(mode="json"),
                "candidates": [c.model_dump(mode="json") for c in review.candidates],
                "selected_candidate_id": review.selected_candidate_id,
            }
            for review in prior.component_reviews
        ],
        "reviewed_references": ["U1"],
        "support_requirements": [],
        "support_observations": [],
        "power_source": prior.power_review.source.model_dump(mode="json"),
        "power_loads": [load.model_dump(mode="json") for load in prior.power_review.loads],
        "evidence_files": {
            key: item.model_dump(mode="json")
            for key, item in fixture_request.predesign.evidence_files.items()
        },
    }
    engineering["evidence_files"] = {
        key: value
        for key, value in engineering["evidence_files"].items()
        if key not in {"component-readiness", "mandatory-review"}
        and not key.startswith("floorplan.")
    }
    for key, binding in fixture_request.predesign.evidence_files.items():
        # Borrow engineering observations only; preserve this preparation
        # owner's freshly generated and geometry-bound vector artifacts.
        if key in {"component-readiness", "mandatory-review"} or key.startswith("floorplan."):
            continue
        (prepared / binding.relative_path).write_bytes(
            (fixture_evidence / binding.relative_path).read_bytes()
        )
    from tests.unit.mandatory_review_fixtures import policy_fixture as mandatory_policy_fixture

    from pcbsmith.routed_copper_graph_ir import fingerprint

    policy = mandatory_policy_fixture(
        fixture_request.predesign, file_sha256(prepared / "component-readiness.json")
    )
    fields = json.loads((prepared / "prepared-inputs.json").read_bytes())
    policy = policy.model_copy(update={"brief_sha256": fingerprint(fields["amended_brief"])})
    policy_path = prepared / "mandatory-review.json"
    policy_path.write_text(policy.model_dump_json())
    engineering["evidence_files"]["mandatory-review"] = {
        "relative_path": policy_path.name,
        "sha256": file_sha256(policy_path),
    }
    if input_fault == "changed-source":
        source = next(iter(engineering["evidence_files"].values()))
        (prepared / source["relative_path"]).write_text("Changed synthetic evidence")
    elif input_fault == "overload":
        engineering["power_loads"][0].update(continuous_current_a=100, peak_current_a=100)
    engineering_file = prepared / "engineering.json"
    engineering_file.write_text(json.dumps(engineering), encoding="utf-8")
    assertion_file = prepared / "assertion.json"
    assertion_file.write_text(
        json.dumps(
            {
                "prepared_inputs_sha256": file_sha256(prepared / "prepared-inputs.json"),
                "engineering_sha256": file_sha256(engineering_file),
                "disposition": "approve_predesign",
                "rationale": "Synthetic integration test only",
                "reviewer_id": "test-fixture",
                "reviewer_role": "authorized_delegate",
                "recorded_at": "2026-09-10T00:00:00+00:00",
                "floorplan_review": {
                    "floorplan_sha256": file_sha256(prepared / FILES[0]),
                    "inspected": True,
                    "presented": True,
                    "reviewer_id": "test-fixture",
                    "rationale": "Synthetic assertion, no human acceptance",
                    "presentation_reference": "synthetic test",
                    "corridor_rationale": "Synthetic single-component fixture",
                },
            }
        ),
        encoding="utf-8",
    )
    if input_fault is not None:
        reason = "source evidence changed" if input_fault == "changed-source" else "exceeds_source"
        with pytest.raises(ValueError, match=reason):
            approve_prepared_predesign(prepared, engineering_file, assertion_file)
        assert not (prepared / "predesign.json").exists()
        assert not (prepared / "floorplan-review.json").exists()
        return
    bundle = approve_prepared_predesign(prepared, engineering_file, assertion_file)
    assert "component-readiness" in bundle.evidence_files
    # Publication uses a synthetic saved board containing the same selected footprint.
    model_fp = fp.read_text(encoding="utf-8").replace(
        '(footprint "DIP"',
        '(footprint "Test:DIP" (property "Reference" "U1") (property "Value" "PART")',
    )
    fixture_board.write_text(
        '(kicad_pcb (version 20260206) (generator "pcbsmith-test") '
        '(layers (0 "F.Cu" signal) (31 "B.Cu" signal)) ' + model_fp + ")",
        encoding="utf-8",
    )
    policy = SelectedModelPolicy.model_validate(
        json.loads((prepared / "component-readiness.json").read_bytes())["selected_models"][
            "policy"
        ]
    )
    preflight = preflight_board_models(
        fixture_board,
        registry=policy.registry,
        requirements=policy.requirements,
        applicability=policy.applicability,
        applicability_rationale=policy.rationale,
    )
    visual = fixture_request.visual_requirements[0].model_copy(
        update={
            "model_required": True,
            "aligned_model_required": True,
        }
    )
    request = fixture_request.model_copy(
        update={
            "predesign": bundle,
            "native_inputs": native_input_hashes(fixture_board),
            "model_preflight": preflight,
            "visual_requirements": (visual,),
        }
    )
    transaction_root = tmp_path / "transactions"
    result = persist_registered_placement_candidate(
        generator_id="pcbsmith.kicad.board:generate_board",
        transaction_root=transaction_root,
        project_id=spec.project_id,
        generation_id="bound-model-control",
        generation_sha256="a" * 64,
        board_relative_path="design/board.kicad_pcb",
        board_payload=fixture_board.read_bytes(),
        support_payloads={
            "design/" + p.name: p.read_bytes()
            for p in fixture_board.parent.iterdir()
            if p != fixture_board
        },
        readiness_request=request,
        readiness_artifact_root=prepared,
        review_generator=lambda b, o: fixture_review(b, o),
        component_review_generator=lambda _b: _empty_component_review(spec.project_id),
    )
    generation = transaction_root / "generations/bound-model-control"
    assert (
        readiness_blockers(
            generation_root=generation,
            project_id=spec.project_id,
            board_sha256=file_sha256(fixture_board),
            board_relative_path="design/board.kicad_pcb",
            retained_artifacts={
                a.relative_path: a.content_sha256 for a in result.transaction.manifest.artifacts
            },
        )
        == ()
    )


def test_only_single_terminal_nets_stop_before_output(inventory, monkeypatch):
    from pcbsmith.predesign_preparation import prepare_predesign_inputs

    _, root, _ = inventory
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    output = root / "not-created"
    with pytest.raises(ValueError, match="at least one multi-terminal net"):
        prepare_predesign_inputs(root / "design-spec.json", root, output)
    assert not output.exists()


def test_public_publication_boundary_rejects_weakened_model_report(inventory, tmp_path):
    from pcbsmith.design_readiness import VisualSubjectRequirement
    from pcbsmith.manufacturing_lineage import file_sha256, native_input_hashes
    from pcbsmith.production_readiness import (
        PublicationReadinessRequest,
        require_publication_request,
    )

    board, evidence, bundle, actual = publication_fixture(tmp_path, inventory)
    board.write_text(
        board.read_text(encoding="utf-8").replace(
            "(kicad_pcb ", '(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) '
        ),
        encoding="utf-8",
    )
    actual = actual.model_copy(update={"board_sha256": file_sha256(board)})
    request = PublicationReadinessRequest(
        predesign=bundle,
        native_inputs=native_input_hashes(board),
        reference_intents={"U1": "fixture-resistance"},
        model_preflight=actual,
        visual_requirements=(
            VisualSubjectRequirement(
                subject_id="U1-model",
                minimum_crop_width_px=32,
                minimum_crop_height_px=32,
                minimum_occupancy_fraction=0.2,
                component_reference="U1",
                artifact_id="2d:front:png",
                model_required=True,
                aligned_model_required=True,
            ),
        ),
        visual_crops={"U1-model": (0, 0, 64, 64)},
    )
    require_publication_request(
        request, board_file=board, artifact_root=evidence, project_id="fixture"
    )
    weakened = actual.model_copy(update={"required_references": ()})
    with pytest.raises(ValueError, match="differs from replay of the selected policy"):
        require_publication_request(
            request.model_copy(update={"model_preflight": weakened}),
            board_file=board,
            artifact_root=evidence,
            project_id="fixture",
        )


def test_prepare_selected_models_preserves_exact_policy(inventory, tmp_path):
    from pcbsmith.production_readiness import prepare_selected_board_models

    board, evidence, bundle, actual = publication_fixture(tmp_path, inventory)
    assert prepare_selected_board_models(bundle, evidence, board) == actual
    policy_file = evidence / "component-readiness.json"
    policy_file.write_bytes(policy_file.read_bytes() + b" ")
    with pytest.raises(ValueError, match="source evidence changed"):
        prepare_selected_board_models(bundle, evidence, board)


def test_prepare_models_requires_explicit_policy(tmp_path):
    from pcbsmith.production_readiness import prepare_selected_board_models

    board, evidence, request = readiness_fixture(tmp_path)
    bundle = request.predesign.model_copy(
        update={
            "evidence_files": {
                key: value
                for key, value in request.predesign.evidence_files.items()
                if key != "component-readiness"
            }
        }
    )
    with pytest.raises(ValueError, match="explicit component/model readiness"):
        prepare_selected_board_models(bundle, evidence, board)
