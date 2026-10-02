"""Synthetic input diagnostics only; no board approval or physical qualification."""

from __future__ import annotations

import json

import pytest

from pcbsmith.design_readiness import ReadinessDisposition, review_component_alternatives
from pcbsmith.engineering_preview import (
    EngineeringInputs,
    evaluate_engineering_inputs,
    inspect_engineering_inputs,
    main,
)
from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.production_readiness import PredesignReadinessBundle


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Synthetic source, not a real component datasheet.")
    candidates = [
        dict(
            candidate_id=name,
            manufacturer_part_number="SYNTHETIC-" + name,
            capabilities=["indicator"],
            mounting="through_hole",
            body_width_mm=5,
            body_height_mm=5,
            pin_count=2,
            maximum_unit_current_a=0.002,
            hand_assembly_suitable=True,
            model_classification="proxy",
            evidence_ids=["source"],
        )
        for name in ("a", "z")
    ]
    payload = dict(
        reviewed_references=["D1"],
        component_alternatives=[
            dict(
                intent=dict(
                    intent_id="indicator",
                    role_id="indicator",
                    required_capabilities=["indicator"],
                    preferred_mounting="through_hole",
                    evidence_ids=["source"],
                ),
                candidates=candidates,
                selected_candidate_id="z",
            )
        ],
        support_requirements=[],
        support_observations=[],
        power_source=dict(
            source_id="bench",
            rail_id="5V",
            voltage_v=5,
            available_continuous_current_a=0.02,
            available_peak_current_a=0.02,
            current_authority="dedicated_supply",
            current_detection_verified=False,
            direct_input_capacitance_uf=0,
            evidence_ids=["source"],
        ),
        power_loads=[
            dict(
                load_id="indicator",
                rail_id="5V",
                continuous_current_a=0.002,
                peak_current_a=0.002,
                evidence_ids=["source"],
            )
        ],
        evidence_files=dict(source=dict(relative_path=source.name, sha256=file_sha256(source))),
    )
    (tmp_path / "prepared-inputs.json").write_text(
        json.dumps(
            dict(
                amended_brief=dict(
                    draft=dict(
                        components=[
                            dict(component_id="D1", role="indicator", selection="SYNTHETIC-z")
                        ]
                    )
                )
            )
        )
    )
    return tmp_path, payload


def run_preview(root, payload):
    path = root / "engineering.json"
    path.write_text(json.dumps(payload))
    return inspect_engineering_inputs(root, path)


def tree_hashes(root):
    return {str(p.relative_to(root)): file_sha256(p) for p in root.rglob("*") if p.is_file()}


def test_preview_does_not_write_or_approve(inputs):
    root, payload = inputs
    report = run_preview(root, payload)
    before = tree_hashes(root)
    assert inspect_engineering_inputs(root, root / "engineering.json") == report
    assert tree_hashes(root) == before
    assert not report["blockers"]
    assert report["approval_granted"] is False
    assert report["authority"] == "diagnostic_only"
    assert report["manual_review"]
    with pytest.raises(ValueError):
        PredesignReadinessBundle.model_validate(report)


def test_missing_input_is_worklist_not_success(inputs):
    root, _ = inputs
    before = tree_hashes(root)
    report = inspect_engineering_inputs(root)
    assert report["blockers"]
    assert report["component_worklist"][0]["reference"] == "D1"
    assert "declared_data_checks" not in report
    assert tree_hashes(root) == before


def test_stale_source_fails(inputs):
    root, payload = inputs
    (root / "source.txt").write_text("Changed synthetic evidence")
    assert "source evidence changed" in str(run_preview(root, payload)["blockers"])


@pytest.mark.parametrize("path", ["../outside.txt", "/outside.txt", "C:/outside.txt"])
def test_source_path_escape_fails(inputs, path):
    root, payload = inputs
    payload["evidence_files"]["source"]["relative_path"] = path
    assert run_preview(root, payload)["blockers"]


def test_missing_source_binding_fails(inputs):
    root, payload = inputs
    payload["evidence_files"] = {}
    assert "lack retained files" in str(run_preview(root, payload)["blockers"])


@pytest.mark.parametrize("refs", [["D1", "D1"], ["D2"], []])
def test_reference_coverage_and_duplicates_fail(inputs, refs):
    root, payload = inputs
    payload["reviewed_references"] = refs
    assert run_preview(root, payload)["blockers"]


def test_duplicate_intents_fail(inputs):
    root, payload = inputs
    payload["component_alternatives"] *= 2
    assert "duplicate component intents" in str(run_preview(root, payload)["blockers"])


def test_omitted_selected_support_fails(inputs):
    root, payload = inputs
    payload["component_alternatives"][0]["candidates"][1]["support_requirement_ids"] = ["limit"]
    assert "support obligations are omitted" in str(run_preview(root, payload)["blockers"])


def test_power_overload_is_reported(inputs):
    root, payload = inputs
    payload["power_loads"][0].update(continuous_current_a=0.2, peak_current_a=0.2)
    assert "load_exceeds_source" in str(run_preview(root, payload)["blockers"])


def test_assertion_and_positive_outcome_fields_are_not_inputs(inputs):
    root, payload = inputs
    payload.update(disposition="approve_predesign", approval_granted=True)
    assert "Extra inputs are not permitted" in str(run_preview(root, payload)["blockers"])


def test_source_notes_are_bound_but_not_verified(inputs):
    root, payload = inputs
    payload["source_notes"] = [
        dict(evidence_id="source", locator="page1", statement="Synthetic note")
    ]
    report = run_preview(root, payload)
    assert not report["blockers"]
    assert report["source_notes"] == payload["source_notes"]
    assert report["approval_granted"] is False
    payload["source_notes"][0]["evidence_id"] = "missing"
    assert run_preview(root, payload)["blockers"]


def test_same_engineering_score_allows_either_selection(inputs):
    root, payload = inputs
    parsed = EngineeringInputs.model_validate(payload)
    report = evaluate_engineering_inputs(parsed, expected_references={"D1"}, artifact_root=root)
    comparison = report.component_reviews[0]
    assert comparison.recommended_candidate_id == "a"  # stable display order only
    assert comparison.selected_candidate_id == "z"
    assert comparison.disposition is ReadinessDisposition.READY
    assert all(item.compatible for item in comparison.assessments)


@pytest.mark.parametrize("change", ["bigger", "missing_capability"])
def test_worse_or_incompatible_selection_still_fails(inputs, change):
    root, payload = inputs
    candidate = payload["component_alternatives"][0]["candidates"][1]
    if change == "bigger":
        candidate["body_width_mm"] = 6
    else:
        candidate["capabilities"] = ["different_colour_only"]
    assert run_preview(root, payload)["blockers"]


def test_shared_capability_is_kept_for_colour_alternatives(inputs):
    _, payload = inputs
    raw = payload["component_alternatives"][0]
    raw["candidates"][0]["capabilities"] = ["indicator", "colour617"]
    raw["candidates"][1]["capabilities"] = ["indicator", "colour640"]
    item = EngineeringInputs.model_validate(payload).component_alternatives[0]
    review = review_component_alternatives(
        intent=item.intent,
        candidates=item.candidates,
        selected_candidate_id=item.selected_candidate_id,
    )
    assert all(a.compatible for a in review.assessments)
    assert not review.blockers


def test_cli_missing_inputs_is_nonzero_and_nonapproving(inputs, monkeypatch, capsys):
    root, _ = inputs
    monkeypatch.setattr("sys.argv", ["engineering_preview", str(root)])
    assert main() == 1
    assert json.loads(capsys.readouterr().out)["approval_granted"] is False
