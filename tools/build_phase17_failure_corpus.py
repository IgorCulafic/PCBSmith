"""Build the retained Phase 17 failure corpus from executable test evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pcbsmith.failure_corpus import (
    FailureCategory,
    RetainedFailureCase,
    build_phase17_failure_corpus,
)

CaseSpec = tuple[
    str,
    FailureCategory,
    str,
    str,
    str,
    str,
    tuple[str, ...],
]

CASES: tuple[CaseSpec, ...] = (
    (
        "ambiguity-hard-conflict",
        "ambiguity",
        "Prompt claims contain an infeasible hard conflict.",
        "Prompt examination blocks and retains consequences plus alternatives.",
        "Focused test asserts blocked outcome and two alternatives.",
        "tests/unit/test_prompt_examiner.py",
        ("ready_for_concept", "invented requirement"),
    ),
    (
        "capacity-neck-overflow",
        "capacity",
        "Two nets require one capacity-one routing neck.",
        "Pre-route feasibility blocks with named net and blocker.",
        "Focused test asserts exhaustive blocked capacity diagnostic.",
        "tests/unit/test_workflow_feasibility.py",
        ("route_feasible", "capacity_sufficient"),
    ),
    (
        "missing-required-model",
        "missing_asset",
        "Required 3D model preflight fails or transform is shifted.",
        "Required 3D review artifacts are withheld and review generation fails.",
        "Focused tests assert missing renders and shifted-model failure.",
        "tests/unit/kicad/test_model_preflight.py",
        ("model_complete", "camera_alignment_accepted"),
    ),
    (
        "legacy-routing-order-failure",
        "routing",
        "Every sequential net order fails in the adversarial maze.",
        "Legacy routing fails while negotiated routing is separately measured.",
        "Adversarial test asserts both legacy orders fail.",
        "tests/unit/kicad/test_negotiated_board_maze.py",
        ("routing_complete", "ordering_is_sufficient"),
    ),
    (
        "review-omission",
        "review_omission",
        "Placement review is pending, missing, stale, or targets another board.",
        "Routing-entry gate remains blocked.",
        "Focused tests assert exact reviewed-board transaction binding.",
        "tests/unit/test_production_workflow.py",
        ("routing_authorized", "review_complete"),
    ),
    (
        "transaction-pointer-rollback",
        "transaction_rollback",
        "Injected failure occurs after generation promotion but before pointer swap.",
        "Previous CURRENT pointer remains active and failed generation is retained.",
        "Focused test verifies rollback without mixed revisions.",
        "tests/unit/test_production_workflow.py",
        ("generation_committed", "current_revision_replaced"),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--repository-root", default=".")
    args = parser.parse_args()
    root = Path(args.repository_root).resolve()
    cases = []
    for (
        case_id,
        category,
        trigger,
        expected,
        observed,
        locator,
        prevented,
    ) in CASES:
        evidence = root / locator
        cases.append(
            RetainedFailureCase.build(
                case_id=case_id,
                category=category,
                trigger=trigger,
                expected_outcome=expected,
                observed_outcome=observed,
                evidence_locator=locator,
                evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
                prevented_claims=prevented,
            )
        )
    corpus = build_phase17_failure_corpus(tuple(cases))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(corpus.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
