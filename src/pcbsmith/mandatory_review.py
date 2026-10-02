"""Prospective review obligations consumed by existing production gates.

This validates coverage and retained evidence, not the truth of engineering
observations. Historical records remain readable; new publication needs current
evidence instead of obtaining a legacy exception by omitting it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

if TYPE_CHECKING:
    from pcbsmith.production_readiness import PredesignReadinessBundle
    from pcbsmith.project_engineering_gate_ir import ProjectEngineeringGateResult
    from pcbsmith.review.visual_package import VisualReviewManifest

EVIDENCE_ID = "mandatory-review"
PHASE_FAMILIES = (
    "decoupling_loop",
    "connector_protection_order",
    "oscillator_zone",
    "switching_hot_loop",
    "return_adjacency",
)
DIAGNOSTICS = (
    "stackup_reference",
    "return_current",
    "power_domain",
    "thermal_current_density",
    "high_speed",
    "bga",
    "dfm",
)
APPLICABILITY_TOPICS = (*PHASE_FAMILIES, *DIAGNOSTICS, "circuit_patterns", "isolation_cam")
COMPONENT_TOPICS = {"part_and_footprint", "pinout_and_polarity", "ratings", "support_circuit"}
RECURRING_DELIVERABLES = frozenset(
    {"pcb", "schematic", "project", "interactive_bom", "floorplan", "floorplan_preview"}
)


class ApplicabilityDecision(SemanticIrModel):
    disposition: Literal["applicable", "not_applicable", "unresolved"]
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class ComponentObservation(SemanticIrModel):
    observations: dict[str, str]
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class RuleException(SemanticIrModel):
    issue_id: str
    rationale: str
    authorization_evidence_id: str


class MandatoryReview(SemanticIrModel):
    schema_id: Literal["pcbsmith-mandatory-review-v1"] = "pcbsmith-mandatory-review-v1"
    brief_sha256: str
    component_readiness_sha256: str
    reviewer: str
    review_reference: str
    applicability: dict[str, ApplicabilityDecision]
    components: dict[str, ComponentObservation]
    # Keys identify requested files by role, values locate the demand in the brief.
    deliverables: dict[str, str]
    required_native_rules: dict[Literal["erc", "drc"], tuple[str, ...]]
    minimum_board_rules: dict[str, float]
    rule_exceptions: tuple[RuleException, ...] = ()

    @model_validator(mode="after")
    def complete(self) -> Self:
        require_sha256(self.brief_sha256, "brief_sha256")
        require_sha256(self.component_readiness_sha256, "component_readiness_sha256")
        if set(self.applicability) != set(APPLICABILITY_TOPICS):
            raise ValueError("mandatory review requires every applicability topic")
        if not self.components or any(
            set(c.observations) != COMPONENT_TOPICS for c in self.components.values()
        ):
            raise ValueError("mandatory review requires every component review topic")
        if not {"pcb", "schematic", "project"} <= self.deliverables.keys():
            raise ValueError("handover requires PCB, schematic and project deliverables")
        if set(self.required_native_rules) != {"erc", "drc"} or any(
            not rules for rules in self.required_native_rules.values()
        ):
            raise ValueError("explicit ERC and DRC rule baselines are required")
        if not {"min_clearance", "min_track_width", "min_copper_edge_clearance"} <= (
            self.minimum_board_rules.keys()
        ) or any(
            not math.isfinite(value) or value <= 0 for value in self.minimum_board_rules.values()
        ):
            raise ValueError("positive copper clearance, track width and edge minima are required")
        strings = [
            self.reviewer,
            self.review_reference,
            *self.deliverables.values(),
            *(n for c in self.components.values() for n in c.observations.values()),
            *(d.rationale for d in self.applicability.values()),
            *(n for rules in self.required_native_rules.values() for n in rules),
            *(
                n
                for e in self.rule_exceptions
                for n in (e.issue_id, e.rationale, e.authorization_evidence_id)
            ),
        ]
        if any(not text.strip() for text in strings):
            raise ValueError("mandatory review observations and references must be nonblank")
        if len({e.issue_id for e in self.rule_exceptions}) != len(self.rule_exceptions):
            raise ValueError("rule exceptions must be unique")
        if self.applicability["isolation_cam"].disposition == "applicable" and (
            "isolation_cam" not in self.deliverables
        ):
            raise ValueError("requested isolation CAM must be a handover deliverable")
        if any(role.startswith("isolation_cam") for role in self.deliverables) and (
            self.applicability["isolation_cam"].disposition != "applicable"
        ):
            raise ValueError("isolation deliverable contradicts applicability")
        return self


def require_recurring_deliverables(review: MandatoryReview) -> None:
    """Prospective entry-point requirement; historical records remain readable."""
    missing = RECURRING_DELIVERABLES - review.deliverables.keys()
    if missing:
        raise ValueError(
            "New preparation/publication requires recurring deliverables: "
            + ", ".join(sorted(missing))
        )


def require_mandatory_review(bundle: PredesignReadinessBundle, root: Path) -> MandatoryReview:
    from pcbsmith.predesign_contract import artifact_sha256
    from pcbsmith.production_readiness import _relative_file

    binding = bundle.evidence_files.get(EVIDENCE_ID)
    if binding is None:
        raise ValueError("new production requires retained mandatory-review evidence")
    path = _relative_file(root, binding.relative_path)
    if file_sha256(path) != binding.sha256:
        raise ValueError("mandatory review evidence changed")
    review = MandatoryReview.model_validate_json(path.read_bytes())
    component = bundle.evidence_files.get("component-readiness")
    if component is None or review.component_readiness_sha256 != component.sha256:
        raise ValueError("mandatory review lacks current component readiness")
    if review.brief_sha256 != artifact_sha256(bundle.approval.amended_brief):
        raise ValueError("mandatory review targets a different brief")
    refs = {c.component_id for c in bundle.approval.amended_brief.draft.components}
    if set(review.components) != refs:
        raise ValueError("mandatory source review must cover every component")
    ids = {key for item in review.components.values() for key in item.evidence_ids}
    ids.update(key for item in review.applicability.values() for key in item.evidence_ids)
    ids.update(e.authorization_evidence_id for e in review.rule_exceptions)
    if EVIDENCE_ID in ids or not ids <= bundle.evidence_files.keys():
        raise ValueError("mandatory observations require independent retained source evidence")
    for key in ids | {"component-readiness"}:
        item = bundle.evidence_files[key]
        if file_sha256(_relative_file(root, item.relative_path)) != item.sha256:
            raise ValueError(f"mandatory review source changed: {key}")
    if any(d.disposition == "unresolved" for d in review.applicability.values()):
        raise ValueError("mandatory applicability inventory is unresolved")
    from pcbsmith.circuit_patterns import PATTERN_EVIDENCE_ID

    patterns_present = PATTERN_EVIDENCE_ID in bundle.evidence_files
    if patterns_present != (review.applicability["circuit_patterns"].disposition == "applicable"):
        raise ValueError("circuit-pattern evidence contradicts or omits reviewed applicability")
    return review


def require_engineering_coverage(
    review: MandatoryReview, gate: ProjectEngineeringGateResult
) -> None:
    families = {f.family.value for f in gate.context.phase14_features}
    for family in PHASE_FAMILIES:
        if (family in families) != (review.applicability[family].disposition == "applicable"):
            raise ValueError(f"engineering feature coverage contradicts applicability: {family}")


def require_diagnostic_coverage(review: MandatoryReview, visual: VisualReviewManifest) -> None:
    for kind in DIAGNOSTICS:
        artifacts = [a for a in visual.artifacts if a.category == "diagnostics/" + kind]
        if review.applicability[kind].disposition == "applicable" and not any(
            a.required and a.state == "generated" for a in artifacts
        ):
            raise ValueError(f"mandatory diagnostic view is missing: {kind}")
        if artifacts and review.applicability[kind].disposition != "applicable":
            raise ValueError(f"diagnostic view contradicts applicability: {kind}")


def native_rule_blockers(
    review: MandatoryReview, project: Path, reports: dict[str, dict[str, Any]]
) -> tuple[str, ...]:
    """Compare actual project settings/report omissions with the reviewed baseline.

    Exception identity includes the actual omitted value; broad type-only waivers
    cannot cover a later exclusion or changed setting.
    """
    data = json.loads(project.read_bytes())
    settings = data.get("board", {}).get("design_settings", {})
    blockers: list[str] = []
    for key, minimum in review.minimum_board_rules.items():
        value = settings.get("rules", {}).get(key)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < minimum
        ):
            blockers.append(f"native rule below reviewed minimum or absent: {key}")
    exceptions = {e.issue_id for e in review.rule_exceptions}
    for kind, report in reports.items():
        if kind not in {"erc", "drc"}:
            raise ValueError("unsupported native check kind")
        severity = (settings if kind == "drc" else data.get("erc", {})).get("rule_severities", {})
        omitted = report.get("ignored_checks", [])
        if not isinstance(omitted, list):
            blockers.append(f"{kind}: malformed ignored-check inventory")
            continue
        rules = review.required_native_rules["drc" if kind == "drc" else "erc"]
        for rule in rules:
            if severity.get(rule) == "ignore" or any(
                (item.get("key") if isinstance(item, dict) else item) == rule for item in omitted
            ):
                blockers.append(f"required native rule is disabled: {kind}:{rule}")
        inventories = {
            "ignored": omitted,
            "disabled": [k for k, v in severity.items() if v == "ignore"],
            "excluded": (
                settings.get("drc_exclusions", [])
                if kind == "drc"
                else data.get("erc", {}).get("erc_exclusions", [])
            ),
        }
        for category, values in inventories.items():
            if not isinstance(values, list):
                blockers.append(f"{kind}: malformed {category} inventory")
                continue
            for value in values:
                issue = f"{kind}:{category}:{fingerprint(value)}"
                if issue not in exceptions:
                    blockers.append(f"unreviewed native rule exception: {issue}")
    return tuple(blockers)


def native_rule_worklist(
    review: MandatoryReview, project: Path, reports: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Collect both native omission inventories; never create review decisions."""
    data = json.loads(project.read_bytes())
    settings = data.get("board", {}).get("design_settings", {})
    decisions = {item.issue_id: item for item in review.rule_exceptions}
    items = []
    blockers = list(native_rule_blockers(review, project, reports))
    for kind in ("erc", "drc"):
        if kind not in reports:
            blockers.append(f"missing native report: {kind}")
            continue
        config = settings if kind == "drc" else data.get("erc", {})
        inventories = {
            "ignored": reports[kind].get("ignored_checks", []),
            "disabled": [k for k, v in config.get("rule_severities", {}).items() if v == "ignore"],
            "excluded": config.get(f"{kind}_exclusions", []),
        }
        for category, values in inventories.items():
            if not isinstance(values, list):
                continue  # The baseline validator has already recorded the error.
            for value in values:
                issue = f"{kind}:{category}:{fingerprint(value)}"
                decision = decisions.get(issue)
                items.append(
                    {
                        "issue_id": issue,
                        "kind": kind,
                        "category": category,
                        "value": value,
                        "decision": decision.model_dump(mode="json") if decision else None,
                    }
                )
    return {
        "schema_id": "pcbsmith-native-rule-worklist-v1",
        "project_sha256": file_sha256(project),
        "mandatory_review_fingerprint": review.semantic_fingerprint(),
        "ready": not blockers,
        "blockers": blockers,
        "items": items,
    }


def require_bound_native_report(board: Path, kind: str, report_file: Path) -> dict[str, Any]:
    """Replay native source/report bindings, including retained pre-hash DRC receipts."""
    from pcbsmith.applicability_execution import CheckExecutionRecord
    from pcbsmith.kicad.check_reports import drc_sections, erc_violations, validate_native_header

    if kind not in {"erc", "drc"}:
        raise ValueError("unsupported native check kind")
    source = board.with_suffix(".kicad_sch") if kind == "erc" else board
    report = validate_native_header(json.loads(report_file.read_bytes()), kind.upper(), source)
    process = json.loads(report_file.with_suffix(".process.json").read_bytes())
    command = process.get("command", [])
    required = {"sch" if kind == "erc" else "pcb", kind, "--severity-all"}
    if kind == "drc":
        required.add("--schematic-parity")
    if process.get("returncode") != 0 or not required <= set(command):
        raise ValueError(f"{kind}: requires successful all-severity native process")
    by_name: dict[str, str] = {}
    for name, digest in process.get("input_sha256s", process.get("native_inputs", {})).items():
        key = Path(name).name
        if key in by_name and by_name[key] != digest:
            raise ValueError(f"{kind}: ambiguous native input binding")
        by_name[key] = digest
    required_paths = [source, board.with_suffix(".kicad_pro")]
    if kind == "drc":
        required_paths.append(board.with_suffix(".kicad_sch"))
    for path in required_paths:
        if by_name.get(path.name) != file_sha256(path):
            raise ValueError(f"{kind}: process does not bind current {path.name}")
    digest = file_sha256(report_file)
    if process.get("report_sha256") != digest:
        # Earlier producer-owned DRC records bind the report through a typed execution.
        if kind != "drc" or process.get("report_sha256") is not None:
            raise ValueError(f"{kind}: process does not bind report bytes")
        execution = CheckExecutionRecord.model_validate_json(
            report_file.with_suffix(".execution.json").read_bytes()
        )
        if (
            execution.check_id != "kicad.drc"
            or execution.producer_id != "kicad-cli.pcb.drc"
            or execution.result_sha256 != digest
            or not set(by_name.values()) <= set(execution.exact_input_sha256s)
        ):
            raise ValueError("drc: execution does not bind report and inputs")
    findings = (
        erc_violations(report)
        if kind == "erc"
        else [item for values in drc_sections(report).values() for item in values]
    )
    if findings:
        raise ValueError(f"{kind}: native report has findings")
    return report


def inspect_native_review(request_file: Path) -> dict[str, Any]:
    """Read-only CLI preflight of both inventories before rendering/publication."""
    from pcbsmith.production_readiness import PublicationReadinessRequest, require_predesign_bundle

    request = json.loads(request_file.read_bytes())

    def location(key: str) -> Path:
        return (request_file.parent / str(request[key])).resolve()

    readiness = PublicationReadinessRequest.model_validate_json(
        location("readiness_request").read_bytes()
    )
    root = location("readiness_root")
    require_predesign_bundle(readiness.predesign, root)
    review = require_mandatory_review(readiness.predesign, root)
    board = location("board")
    from pcbsmith.manufacturing_lineage import native_input_hashes

    if native_input_hashes(board) != readiness.native_inputs:
        raise ValueError("native review targets different publication inputs")
    if "native_rule_review" in request:
        review = require_native_review_completion(
            review,
            readiness.predesign.evidence_files[EVIDENCE_ID].sha256,
            board,
            location("native_rule_review"),
        )
    reports = {}
    errors = []
    bindings = {}
    for kind in ("erc", "drc"):
        try:
            path = location(kind + "_report")
            reports[kind] = require_bound_native_report(board, kind, path)
            bindings[kind] = {
                "report_sha256": file_sha256(path),
                "process_sha256": file_sha256(path.with_suffix(".process.json")),
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{kind}: {exc}")
    result = native_rule_worklist(review, board.with_suffix(".kicad_pro"), reports)
    result["blockers"].extend(errors)
    result["ready"] = not result["blockers"]
    result["bindings"] = bindings
    result["native_inputs"] = readiness.native_inputs
    return result


def require_native_review_completion(
    original: MandatoryReview, original_sha256: str, board: Path, completion_file: Path
) -> MandatoryReview:
    """Add genuine omission decisions without changing a closed CAD generation.

    This is evidence completion only: exact original policy, current native inputs,
    additive decisions and independently hashed observations. It grants no worker,
    reroute, revision, waived required rule or manufacturing acceptance.
    """
    from pcbsmith.manufacturing_lineage import native_input_hashes
    from pcbsmith.production_readiness import _relative_file

    completion = json.loads(completion_file.read_bytes())
    expected_keys = {
        "schema_id",
        "predecessor_review_sha256",
        "native_inputs",
        "reviewer",
        "authorization_reference",
        "rule_exceptions",
        "evidence_files",
    }
    if (
        set(completion) != expected_keys
        or completion["schema_id"] != "pcbsmith-native-review-completion-v1"
    ):
        raise ValueError("invalid native review completion schema")
    if completion["predecessor_review_sha256"] != original_sha256:
        raise ValueError("native review completion has stale predecessor")
    if completion["native_inputs"] != native_input_hashes(board):
        raise ValueError("native review completion has stale native inputs")
    if any(
        not isinstance(completion[k], str) or not completion[k].strip()
        for k in ("reviewer", "authorization_reference")
    ):
        raise ValueError("native review completion requires reviewer and authorization")
    additions = tuple(RuleException.model_validate(item) for item in completion["rule_exceptions"])
    if not additions:
        raise ValueError("native review completion has no decisions")
    old_ids = {item.issue_id for item in original.rule_exceptions}
    if any(item.issue_id in old_ids for item in additions):
        raise ValueError("native review completion cannot replace existing decisions")
    sources = completion["evidence_files"]
    if {item.authorization_evidence_id for item in additions} != set(sources):
        raise ValueError("native review completion requires exact observation sources")
    for binding in sources.values():
        source = _relative_file(completion_file.parent, binding["relative_path"])
        if (
            source.resolve() == completion_file.resolve()
            or file_sha256(source) != binding["sha256"]
        ):
            raise ValueError("native review completion observation source changed")
    return MandatoryReview.model_validate(
        {
            **original.model_dump(mode="json"),
            "rule_exceptions": [
                item.model_dump(mode="json") for item in (*original.rule_exceptions, *additions)
            ],
        }
    )


def require_current_native_checks(board: Path, directory: Path) -> dict[str, str]:
    """Cheap read-only prerequisite for final rendering; stale inputs never trigger reruns."""
    from pcbsmith.kicad.check_reports import erc_violations
    from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report

    paths = {kind: directory / f"{kind}.json" for kind in ("erc", "drc")}
    reports = {kind: require_bound_native_report(board, kind, path) for kind, path in paths.items()}
    from pcbsmith.manufacturing_lineage import native_input_hashes

    process = json.loads(paths["drc"].with_suffix(".process.json").read_bytes())
    recorded = {
        Path(name).name: digest
        for name, digest in process.get("input_sha256s", process.get("native_inputs", {})).items()
    }
    if recorded != native_input_hashes(board):
        raise ValueError("Final rendering has stale native rule/library-table inputs")
    if erc_violations(reports["erc"]) or not inspect_kicad_drc_report(paths["drc"]).clean:
        raise ValueError(
            "Final rendering requires clean current native ERC/DRC/connectivity/parity"
        )
    return {kind: file_sha256(path) for kind, path in paths.items()}
