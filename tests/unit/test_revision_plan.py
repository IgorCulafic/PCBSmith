from __future__ import annotations

from pcbsmith.revision import build_revision_plan, collect_failure_codes


def _bundle(
    *,
    findings: list[dict] | None = None,
    component_count: int = 6,
    board_status: str = "needs_human_review",
) -> dict:
    return {
        "pcbs_internal": {
            "math": {"status": "warning"},
            "components": [{"reference": f"C{i}"} for i in range(component_count)],
        },
        "evidence": {"status": "needs_human_review"},
        "kicad": {"status": "passed"},
        "ngspice": {"status": "passed"},
        "board": {"status": board_status},
        "design_review": {
            "status": "failed" if findings else "passed",
            "findings": findings or [],
        },
    }


def _finding(
    rule: str = "1.1",
    severity: str = "blocker",
    scope: str = "component",
    where: str = "P2",
) -> dict:
    return {
        "rule": rule,
        "severity": severity,
        "scope": scope,
        "where": where,
        "suggested_action": "fix it",
    }


def test_localized_blocker_produces_patch_decision() -> None:
    bundle = _bundle(findings=[_finding()])

    plan = build_revision_plan(bundle, [collect_failure_codes(bundle)])

    assert plan["decision"] == "patch"
    assert plan["targets"][0]["rule"] == "1.1"
    assert plan["targets"][0]["where"] == "P2"


def test_global_finding_forces_redo_at_board_stage() -> None:
    bundle = _bundle(findings=[_finding(scope="global", where="layout")])

    plan = build_revision_plan(bundle, [collect_failure_codes(bundle)])

    assert plan["decision"] == "redo"
    assert plan["stage"] == "board"


def test_majority_touched_components_force_redo() -> None:
    findings = [_finding(where=f"C{i}") for i in range(4)]
    bundle = _bundle(findings=findings, component_count=6)

    plan = build_revision_plan(bundle, [collect_failure_codes(bundle)])

    assert plan["decision"] == "redo"


def test_repeated_failure_code_escalates() -> None:
    bundle = _bundle(findings=[_finding()])
    codes = collect_failure_codes(bundle)

    plan = build_revision_plan(bundle, [codes, codes, codes])

    assert plan["decision"] == "escalate"
    assert any("recurred" in reason for reason in plan["rationale"])


def test_clean_bundle_produces_clean_decision() -> None:
    bundle = _bundle()

    plan = build_revision_plan(bundle, [collect_failure_codes(bundle)])

    assert plan["decision"] == "clean"
    assert plan["failure_codes"] == []
