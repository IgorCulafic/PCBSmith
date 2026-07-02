from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pcbsmith.circuit.models import RevisionRecord

_FAILURE_ROUTES = {
    "evidence_missing": (
        ("Evidence cache or part selection",),
        ("evidence_lookup",),
        "Fetch or request the missing evidence before changing the schematic.",
    ),
    "math_mismatch": (
        ("Circuit object values or deterministic calculators",),
        ("math_gate",),
        "Recalculate values and update the existing circuit object.",
    ),
    "kicad_failed": (
        ("KiCad schematic or symbol mapping",),
        ("kicad_erc", "kicad_spice_export"),
        "Patch the existing KiCad schematic or symbol mapping.",
    ),
    "simulation_failed": (
        ("SPICE model, simulation setup, or circuit values",),
        ("ngspice",),
        "Patch the simulation setup or circuit values and rerun ngspice.",
    ),
    "reconciliation_failed": (
        ("Translation boundary between PCBSmith, KiCad, and ngspice",),
        ("reconciliation",),
        "Patch the mismatched translation layer.",
    ),
    "board_failed": (
        ("Board generator placement, routing, or footprint geometry",),
        ("kicad_drc",),
        "Patch the generated board layout and rerun KiCad DRC.",
    ),
}


def revision_for_authority_failure(
    *,
    revision_id: str,
    parent_revision_id: str | None,
    failure_code: str,
    findings: tuple[str, ...],
) -> RevisionRecord:
    try:
        changed_artifacts, checks, next_action = _FAILURE_ROUTES[failure_code]
    except KeyError as exc:
        raise ValueError(f"Unknown authority failure code: {failure_code}") from exc

    return RevisionRecord(
        revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        changed_artifacts=changed_artifacts,
        authority_checks=checks,
        findings=findings,
        next_action=next_action,
    )


def should_stop_revision_loop(failure_codes: Iterable[str], *, limit: int = 3) -> bool:
    if limit <= 0:
        raise ValueError("Revision loop limit must be positive.")

    counts = Counter(failure_codes)
    return any(count >= limit for count in counts.values())


REVISION_PLAN_SCHEMA = "pcbsmith-revision-plan-v1"

_STAGE_ORDER = ("intent", "composition", "evidence", "schematic", "simulation", "board")

_AUTHORITY_STAGES = {
    "evidence_missing": "evidence",
    "math_mismatch": "composition",
    "kicad_failed": "schematic",
    "simulation_failed": "simulation",
    "board_failed": "board",
    "design_review_failed": "board",
}


def collect_failure_codes(bundle: Mapping[str, Any]) -> tuple[str, ...]:
    """Stable failure codes for one review bundle, for loop detection."""
    codes: list[str] = []
    if _section_status(bundle, "evidence") == "failed":
        codes.append("evidence_missing")
    if (bundle.get("pcbs_internal", {}).get("math", {}) or {}).get("status") == "failed":
        codes.append("math_mismatch")
    if _section_status(bundle, "kicad") == "failed":
        codes.append("kicad_failed")
    if _section_status(bundle, "ngspice") == "failed":
        codes.append("simulation_failed")
    if _section_status(bundle, "board") == "failed":
        codes.append("board_failed")
    for finding in _design_findings(bundle):
        if finding.get("severity") == "blocker":
            codes.append(f"rule:{finding.get('rule', 'unknown')}")
    return tuple(sorted(set(codes)))


def build_revision_plan(
    bundle: Mapping[str, Any],
    history_failure_codes: Sequence[tuple[str, ...]],
    *,
    loop_limit: int = 3,
) -> dict[str, Any]:
    """Decide patch vs redo vs escalate from one bundle plus prior revisions.

    ``history_failure_codes`` is oldest-to-newest and must include the codes
    for the bundle under review as its last entry.
    """
    findings = _design_findings(bundle)
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    warnings = [f for f in findings if f.get("severity") != "blocker"]
    current_codes = collect_failure_codes(bundle)

    components = bundle.get("pcbs_internal", {}).get("components", []) or []
    touched_refs = {
        finding.get("where", "")
        for finding in blockers
        if finding.get("scope") == "component"
    }
    global_findings = [f for f in findings if f.get("scope") == "global"]

    redo_stages = [
        _AUTHORITY_STAGES[code]
        for code in current_codes
        if code in _AUTHORITY_STAGES
    ]
    redo = bool(global_findings) or (
        bool(components) and len(touched_refs) > len(components) / 2
    )
    if global_findings or blockers:
        redo_stages.append("board")

    all_codes = [code for codes in history_failure_codes for code in codes]
    escalate = should_stop_revision_loop(all_codes, limit=loop_limit)

    if escalate:
        decision = "escalate"
    elif redo:
        decision = "redo"
    elif current_codes or warnings:
        decision = "patch"
    else:
        decision = "clean"

    stage = None
    if redo_stages:
        stage = min(redo_stages, key=_STAGE_ORDER.index)

    targets = [
        {
            "rule": finding.get("rule"),
            "where": finding.get("where"),
            "severity": finding.get("severity"),
            "suggested_action": finding.get("suggested_action"),
        }
        for finding in (*blockers, *warnings)
    ]
    for code in current_codes:
        if code.startswith("rule:"):
            continue
        _, _, next_action = _FAILURE_ROUTES.get(code, ((), (), "Review the failure."))
        targets.append(
            {
                "rule": None,
                "where": code,
                "severity": "blocker",
                "suggested_action": next_action,
            }
        )

    rationale: list[str] = []
    if escalate:
        rationale.append(
            f"A failure code recurred {loop_limit}+ times across revisions; "
            "stop iterating and escalate to a human with the finding history."
        )
    if global_findings:
        rationale.append("Global-scope findings invalidate the layout as a whole.")
    if components and len(touched_refs) > len(components) / 2:
        rationale.append(
            f"Blockers touch {len(touched_refs)} of {len(components)} components."
        )
    if decision == "patch":
        rationale.append(
            "Findings are localized; fix only the responsible rules/inputs and "
            "regenerate as the next revision."
        )
    if decision == "clean":
        rationale.append("No failures or findings require action.")

    return {
        "schema": REVISION_PLAN_SCHEMA,
        "decision": decision,
        "stage": stage if decision in {"redo", "escalate"} else None,
        "failure_codes": list(current_codes),
        "targets": targets,
        "rationale": rationale,
    }


def _section_status(bundle: Mapping[str, Any], section: str) -> str | None:
    data = bundle.get(section)
    if isinstance(data, Mapping):
        status = data.get("status")
        return str(status) if status is not None else None
    return None


def _design_findings(bundle: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    design = bundle.get("design_review")
    if not isinstance(design, Mapping):
        return []
    findings = design.get("findings")
    if not isinstance(findings, list):
        return []
    return [finding for finding in findings if isinstance(finding, Mapping)]
