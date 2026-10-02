"""Read-only engineering input review; never an approval or a board producer.

The CLI prints diagnostics to stdout. It accepts no reviewer assertion, writes no
source artifacts, consumes no board operation and cannot authorize a stopped job.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from pcbsmith.design_readiness import (
    ComponentCandidate,
    ComponentUseIntent,
    DesignReadinessReport,
    DesignReadinessStage,
    PowerConversionContract,
    PowerRailLoad,
    PowerSourceContract,
    SupportObservation,
    SupportRequirement,
    evaluate_design_readiness,
    review_component_alternatives,
    review_power_path,
    review_support_circuits,
)
from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.production_readiness import ReadinessEvidenceFile, require_readiness_evidence
from pcbsmith.semantic_ir import SemanticIrModel


class ComponentComparisonInput(SemanticIrModel):
    intent: ComponentUseIntent
    candidates: tuple[ComponentCandidate, ...] = Field(min_length=2)
    selected_candidate_id: str


class SourceNote(SemanticIrModel):
    """A caller's source interpretation, not machine-verified truth."""

    evidence_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    statement: str = Field(min_length=1)

    @model_validator(mode="after")
    def nonblank(self) -> SourceNote:
        if not all(v.strip() for v in (self.evidence_id, self.locator, self.statement)):
            raise ValueError("source notes require nonblank source, locator and statement")
        return self


class EngineeringInputs(SemanticIrModel):
    reviewed_references: tuple[str, ...] = Field(min_length=1)
    component_alternatives: tuple[ComponentComparisonInput, ...] = Field(min_length=1)
    support_requirements: tuple[SupportRequirement, ...]
    support_observations: tuple[SupportObservation, ...]
    power_source: PowerSourceContract
    power_loads: tuple[PowerRailLoad, ...] = Field(min_length=1)
    power_conversions: tuple[PowerConversionContract, ...] = ()
    evidence_files: dict[str, ReadinessEvidenceFile]
    source_notes: tuple[SourceNote, ...] = ()

    @model_validator(mode="after")
    def unique_references_and_bound_notes(self) -> EngineeringInputs:
        if len(self.reviewed_references) != len(set(self.reviewed_references)):
            raise ValueError("reviewed references must be unique")
        if any(not ref.strip() for ref in self.reviewed_references):
            raise ValueError("reviewed references must be nonblank")
        for note in self.source_notes:
            if note.evidence_id not in self.evidence_files:
                raise ValueError("source note refers to an unbound evidence ID")
        return self


def evaluate_engineering_inputs(
    inputs: EngineeringInputs, *, expected_references: set[str], artifact_root: Path
) -> DesignReadinessReport:
    """Replay identical declared-data checks for preview and approval consumers."""
    if set(inputs.reviewed_references) != expected_references:
        raise ValueError("Engineering review does not cover every component")
    comparisons = tuple(
        review_component_alternatives(
            intent=item.intent,
            candidates=item.candidates,
            selected_candidate_id=item.selected_candidate_id,
        )
        for item in inputs.component_alternatives
    )
    report = evaluate_design_readiness(
        stage=DesignReadinessStage.PREDESIGN,
        component_reviews=comparisons,
        support_review=review_support_circuits(
            requirements=inputs.support_requirements,
            observations=inputs.support_observations,
        ),
        power_review=review_power_path(
            source=inputs.power_source,
            loads=inputs.power_loads,
            conversions=inputs.power_conversions,
        ),
    )
    require_readiness_evidence(report, inputs.evidence_files, artifact_root)
    return report


def inspect_engineering_inputs(root: Path, engineering_file: Path | None = None) -> dict[str, Any]:
    """Inspect declarations or report missing inputs; never write a decision."""
    result: dict[str, Any] = {
        "schema_id": "pcbsmith-engineering-input-preview-v1",
        "authority": "diagnostic_only",
        "approval_granted": False,
        "blockers": [],
        "manual_review": [
            "Verify source interpretations, including ratings, geometry and operating conditions.",
            "Retain shared alternative capabilities; distinguish preferences from requirements.",
            "Check applicability; empty support lists do not prove support is unnecessary.",
            "Verify each selected candidate against its intended native component.",
            "Visual observations and physical qualification require their own evidence.",
            "Native inventory, floorplan and approval checks remain in the approval boundary.",
        ],
    }
    try:
        prepared_file = root / "prepared-inputs.json"
        fields = json.loads(prepared_file.read_text(encoding="utf-8"))
        components = fields["amended_brief"]["draft"]["components"]
        references = {item["component_id"] for item in components}
        result["prepared_inputs_sha256"] = file_sha256(prepared_file)
        result["component_worklist"] = [
            {
                "reference": item["component_id"],
                "declared_selection": item.get("selection"),
                "declared_role": item["role"],
                "required_review": "source facts, alternatives, support and native mapping",
            }
            for item in components
        ]
        if engineering_file is None or not engineering_file.is_file():
            result["blockers"].append("Engineering input file is missing; no review was evaluated.")
            return result
        result["engineering_inputs_sha256"] = file_sha256(engineering_file)
        inputs = EngineeringInputs.model_validate_json(engineering_file.read_text(encoding="utf-8"))
        report = evaluate_engineering_inputs(
            inputs, expected_references=references, artifact_root=root
        )
        from pcbsmith.circuit_patterns import require_bound_circuit_patterns

        pattern_checks = require_bound_circuit_patterns(report, inputs.evidence_files, root)
        if pattern_checks is not None:
            result["circuit_pattern_checks"] = pattern_checks
        result["declared_data_checks"] = report.model_dump(mode="json")
        result["blockers"].extend(report.blockers)
        result["source_files"] = {
            key: binding.model_dump(mode="json") for key, binding in inputs.evidence_files.items()
        }
        result["source_notes"] = [note.model_dump(mode="json") for note in inputs.source_notes]
        if not inputs.source_notes:
            result["manual_review"].append("No structured source-page notes were supplied.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["blockers"].append(f"Input validation failed: {exc}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="existing predesign artifact root")
    parser.add_argument("--engineering", type=Path, help="facts only; no reviewer assertion")
    args = parser.parse_args()
    report = inspect_engineering_inputs(args.root, args.engineering)
    print(json.dumps(report, indent=2))
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
