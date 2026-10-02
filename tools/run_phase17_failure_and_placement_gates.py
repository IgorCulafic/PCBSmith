"""Run read-only failure reconciliation and routing-feasible placement gates."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.board_failure_classifier import classify_board_failures
from pcbsmith.kicad.placement_escape_repair import derive_placement_escape_repair_plan
from pcbsmith.kicad.routed_review_bundle import review_bundle_status
from pcbsmith.kicad.routing_candidate_qualification import (
    qualify_routed_candidate,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _classifier_source() -> Path:
    source = inspect.getsourcefile(classify_board_failures)
    if source is None:
        raise RuntimeError("Cannot bind the board-failure classifier source")
    return Path(source).resolve()


def _repair_planner_source() -> Path:
    source = inspect.getsourcefile(derive_placement_escape_repair_plan)
    if source is None:
        raise RuntimeError("Cannot bind the placement-repair planner source")
    return Path(source).resolve()


def _qualification_source() -> Path:
    source = inspect.getsourcefile(qualify_routed_candidate)
    if source is None:
        raise RuntimeError("Cannot bind the routed-candidate qualification source")
    return Path(source).resolve()


def _review_validator_source() -> Path:
    source = inspect.getsourcefile(review_bundle_status)
    if source is None:
        raise RuntimeError("Cannot bind the routed-review validator source")
    return Path(source).resolve()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(
    command: tuple[str, ...], *, cwd: Path, stdout: Path, stderr: Path, timeout: int
) -> tuple[int, float, str | None]:
    started = time.monotonic()
    try:
        process = subprocess.run(
            command, cwd=cwd, capture_output=True, timeout=timeout, check=False
        )
        stdout.write_bytes(process.stdout)
        stderr.write_bytes(process.stderr)
        return process.returncode, time.monotonic() - started, None
    except subprocess.TimeoutExpired as exc:
        stdout.write_bytes(exc.stdout or b"")
        stderr.write_bytes(exc.stderr or b"")
        return 124, time.monotonic() - started, f"timeout after {timeout}s"


def _placement_board(case_dir: Path) -> Path:
    matches = tuple(case_dir.glob("*-placement.kicad_pcb"))
    if len(matches) != 1:
        raise ValueError(f"Expected one placement board in {case_dir}, found {len(matches)}")
    return matches[0]


def _latest_route(case_dir: Path) -> Path:
    root = case_dir / "external" / "freerouting-v2.2.4"
    candidates = []
    for attempt in root.glob("attempt-*"):
        evidence = attempt / "route-evidence.json"
        boards = tuple(attempt.glob("*-freerouting.kicad_pcb"))
        if evidence.exists() and len(boards) == 1:
            payload = _read(evidence)
            if payload.get("routed_board_sha256") == _sha256(boards[0]):
                candidates.append((attempt.name, boards[0]))
    if not candidates:
        raise FileNotFoundError(f"No retained Freerouting candidate in {case_dir}")
    return sorted(candidates)[-1][1]


def _placement_baseline(
    case_dir: Path, output_root: Path, bridge_sha: str
) -> tuple[dict[str, object], dict[str, object]]:
    source_sha = _sha256(_placement_board(case_dir))
    root = output_root / "cases" / case_dir.name / "placement"
    candidates: list[tuple[float, dict[str, object], dict[str, object]]] = []
    for result_path in root.glob("revision-*/gate-result.json"):
        result = _read(result_path)
        observation_path = result_path.parent / "physical-observation.json"
        if (
            result.get("execution_complete") is True
            and result.get("source_board_sha256") == source_sha
            and result.get("bridge_sha256") == bridge_sha
            and observation_path.exists()
        ):
            observation = _read(observation_path)
            if isinstance(observation.get("board_identity"), dict):
                candidates.append((result_path.stat().st_mtime, result, observation))
    if not candidates:
        raise FileNotFoundError("no current hash-bound placement baseline with board identity")
    _mtime, result, observation = max(candidates, key=lambda item: item[0])
    return result, observation


def _visual_evidence_status(case_dir: Path, routed_board_sha256: str) -> str:
    return review_bundle_status(
        case_dir.parent.parent / "review",
        case_id=case_dir.name.split("-", 1)[0],
        board_sha256=routed_board_sha256,
    )


def _case(
    case_dir: Path,
    output_root: Path,
    *,
    board_kind: str,
    bridge: Path,
    kicad_python: Path,
    kicad_cli: Path,
    timeout: int,
) -> dict[str, object]:
    contract_path = case_dir / "case-contract.json"
    contract = _read(contract_path)
    source = _placement_board(case_dir) if board_kind == "placement" else _latest_route(case_dir)
    source_sha = _sha256(source)
    case_id = str(contract["case_id"])
    bridge_sha = _sha256(bridge)
    classifier_sha = _sha256(_classifier_source())
    repair_planner_sha = _sha256(_repair_planner_source())
    qualification_sha = _sha256(_qualification_source())
    review_validator_sha = _sha256(_review_validator_source())
    runner_sha = _sha256(Path(__file__).resolve())
    analyzer_sha = hashlib.sha256(
        (
            f"{bridge_sha}:{classifier_sha}:{repair_planner_sha}:{qualification_sha}:"
            f"{review_validator_sha}:{runner_sha}"
        ).encode()
    ).hexdigest()
    run_dir = (
        output_root
        / "cases"
        / case_dir.name
        / board_kind
        / f"revision-{source_sha[:12]}-analyzer-{analyzer_sha[:12]}"
    )
    result_path = run_dir / "gate-result.json"
    if result_path.exists():
        retained = _read(result_path)
        if retained.get("execution_complete") is True:
            return retained
    run_dir.mkdir(parents=True, exist_ok=True)
    board_copy = run_dir / "source.kicad_pcb"
    shutil.copy2(source, board_copy)
    input_copy_sha = _sha256(board_copy)
    if input_copy_sha != source_sha:
        raise RuntimeError("immutable source copy hash mismatch")
    drc_path = run_dir / "drc.json"
    observation_path = run_dir / "physical-observation.json"
    drc_exit, drc_seconds, drc_error = _run(
        (
            str(kicad_cli),
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(drc_path),
            "--refill-zones",
            "--save-board",
            str(board_copy),
        ),
        cwd=run_dir,
        stdout=run_dir / "drc.stdout.log",
        stderr=run_dir / "drc.stderr.log",
        timeout=timeout,
    )
    bridge_exit: int | None = None
    bridge_seconds = 0.0
    bridge_error: str | None = None
    bridge_diagnostics_clean = False
    if drc_path.exists():
        bridge_command = [
            str(kicad_python),
            str(bridge),
            str(board_copy),
            str(contract_path),
            str(observation_path),
        ]
        if board_kind == "routed":
            bridge_command.append("--skip-placement-audit")
        bridge_exit, bridge_seconds, bridge_error = _run(
            tuple(bridge_command),
            cwd=run_dir,
            stdout=run_dir / "bridge.stdout.log",
            stderr=run_dir / "bridge.stderr.log",
            timeout=timeout,
        )
        bridge_stderr = (run_dir / "bridge.stderr.log").read_text(
            encoding="utf-8", errors="replace"
        )
        bridge_diagnostics_clean = not bridge_stderr.strip()
    execution_complete = (
        drc_exit == 0
        and bridge_exit == 0
        and bridge_diagnostics_clean
        and drc_path.exists()
        and observation_path.exists()
    )
    observed_board_sha = _sha256(board_copy)
    classification = None
    qualification = None
    qualification_error = None
    if execution_complete:
        observation_payload = _read(observation_path)
        repair_plan = derive_placement_escape_repair_plan(
            source_board_sha256=observed_board_sha,
            observation=observation_payload,
        )
        _write(
            run_dir / "placement-repair-plan.json",
            repair_plan.model_dump(mode="json"),
        )
        classification = classify_board_failures(
            board_sha256=observed_board_sha,
            drc_sha256=_sha256(drc_path),
            drc_payload=_read(drc_path),
            observation=observation_payload,
            repair_plan=repair_plan,
        )
        _write(run_dir / "failure-classification.json", classification.model_dump(mode="json"))
        if board_kind == "routed":
            try:
                baseline_result, baseline_observation = _placement_baseline(
                    case_dir, output_root, bridge_sha
                )
                route_evidence = _read(source.parent / "route-evidence.json")
                qualification = qualify_routed_candidate(
                    case_id=case_id,
                    placement_source_board_sha256=str(baseline_result["source_board_sha256"]),
                    routed_source_board_sha256=source_sha,
                    routed_observed_board_sha256=observed_board_sha,
                    baseline_observation=baseline_observation,
                    routed_observation=observation_payload,
                    classification=classification,
                    route_evidence=route_evidence,
                    visual_evidence_status=_visual_evidence_status(case_dir, source_sha),
                )
                _write(
                    run_dir / "routing-candidate-qualification.json",
                    qualification.model_dump(mode="json"),
                )
            except Exception as exc:
                qualification_error = f"{type(exc).__name__}: {exc}"
    result: dict[str, object] = {
        "schema": "pcbsmith-phase17-failure-placement-gate-v1",
        "case_id": case_id,
        "board_kind": board_kind,
        "source_board": source.relative_to(case_dir).as_posix(),
        "source_board_sha256": source_sha,
        "input_copy_sha256": input_copy_sha,
        "observed_board_sha256": observed_board_sha,
        "source_board_preserved": _sha256(source) == source_sha,
        "bridge_sha256": bridge_sha,
        "classifier_sha256": classifier_sha,
        "repair_planner_sha256": repair_planner_sha,
        "qualification_sha256": qualification_sha,
        "review_validator_sha256": review_validator_sha,
        "runner_sha256": runner_sha,
        "analyzer_sha256": analyzer_sha,
        "run_revision": run_dir.relative_to(output_root).as_posix(),
        "execution": {
            "drc": {"exit_code": drc_exit, "seconds": round(drc_seconds, 6), "error": drc_error},
            "bridge": {
                "exit_code": bridge_exit,
                "seconds": round(bridge_seconds, 6),
                "error": bridge_error,
                "diagnostics_clean": bridge_diagnostics_clean,
            },
        },
        "execution_complete": execution_complete,
        "failure_reconciliation_complete": classification.reconciliation_complete
        if classification
        else False,
        "placement_gate_passed": classification.placement_gate_passed if classification else False,
        "two_layer_feasibility": classification.two_layer_feasibility
        if classification
        else "indeterminate",
        "required_pad_escape_count": classification.current_required_escape_count
        if classification
        else None,
        "legal_current_pad_escape_count": classification.current_legal_escape_count
        if classification
        else None,
        "pads_without_current_escape": list(classification.required_pads_without_current_escape)
        if classification
        else None,
        "pads_without_any_rotation_escape": (
            list(classification.required_pads_without_any_rotation_escape)
            if classification
            else None
        ),
        "bounded_repair_evaluated_proposal_count": (
            classification.bounded_repair_evaluated_proposal_count if classification else None
        ),
        "bounded_repair_candidate_count": (
            classification.bounded_repair_candidate_count if classification else None
        ),
        "escape_repair_root_cause": (
            classification.escape_repair_root_cause if classification else None
        ),
        "escape_repair_terminal_reason": (
            classification.escape_repair_terminal_reason if classification else None
        ),
        "candidate_qualification_complete": (
            qualification is not None if board_kind == "routed" else None
        ),
        "candidate_release_qualified": (
            qualification.release_qualified if qualification is not None else None
        ),
        "candidate_qualification_error": qualification_error,
        "protected_parity_mismatch_count": (
            len(qualification.parity.mismatch_ids) if qualification is not None else None
        ),
        "manual_repair_work_item_count": (
            qualification.manual_repair_burden.unresolved_work_item_count
            if qualification is not None
            else None
        ),
        "reference_continuity_disposition": (
            qualification.reference_continuity_disposition if qualification is not None else None
        ),
        "gate_policy": (
            "Fail closed unless every KiCad DRC finding is reconciled and every required SMD "
            "power/return pad has a legal current-pose escape. Rotation alternatives diagnose "
            "placement changes but do not silently rewrite the board."
        ),
    }
    _write(result_path, result)
    return result


def _summarize(results: list[dict[str, object]]) -> dict[str, object]:
    feasibility_counts = Counter(str(item["two_layer_feasibility"]) for item in results)
    return {
        "schema": "pcbsmith-phase17-failure-placement-gate-summary-v1",
        "attempted": len(results),
        "execution_complete": sum(item["execution_complete"] is True for item in results),
        "reconciliation_complete": sum(
            item["failure_reconciliation_complete"] is True for item in results
        ),
        "placement_gate_passed": sum(item["placement_gate_passed"] is True for item in results),
        "feasibility_counts": dict(sorted(feasibility_counts.items())),
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--board-kind", choices=("placement", "routed", "both"), default="both")
    parser.add_argument(
        "--bridge", type=Path, default=Path("tools/kicad_board_feasibility_bridge.py")
    )
    parser.add_argument(
        "--kicad-python", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/python.exe")
    )
    parser.add_argument(
        "--kicad-cli", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Require exactly one routed case and abort after its fail-closed bridge check.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or root / "failure-placement-gate-v1").resolve()
    selected = set(args.cases or ())
    case_dirs = tuple(
        path
        for path in sorted((root / "boards").iterdir())
        if path.is_dir() and (not selected or path.name.split("-", 1)[0] in selected)
    )
    kinds = ("placement", "routed") if args.board_kind == "both" else (args.board_kind,)
    if args.smoke and (len(case_dirs) != 1 or kinds != ("routed",)):
        parser.error("--smoke requires exactly one --cases value and --board-kind routed")
    results = []
    total = len(case_dirs) * len(kinds)
    completed = 0
    for case_dir in case_dirs:
        for kind in kinds:
            completed += 1
            print(f"[{completed}/{total}] {case_dir.name} {kind}", flush=True)
            results.append(
                _case(
                    case_dir,
                    output,
                    board_kind=kind,
                    bridge=args.bridge.resolve(),
                    kicad_python=args.kicad_python.resolve(),
                    kicad_cli=args.kicad_cli.resolve(),
                    timeout=args.timeout,
                )
            )
    summary = _summarize(results)
    _write(output / "summary.json", summary)
    _write(output / f"summary-{args.board_kind}.json", summary)
    if args.board_kind == "both":
        for kind in kinds:
            subset = [item for item in results if item["board_kind"] == kind]
            _write(output / f"summary-{kind}.json", _summarize(subset))
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "attempted",
                    "execution_complete",
                    "reconciliation_complete",
                    "placement_gate_passed",
                    "feasibility_counts",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
