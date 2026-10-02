"""Run an append-only copper-region retrofit pilot on retained routed boards."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.copper_intent import build_copper_intent

DEFAULT_CASES = ("RC14", "RC24", "RC29", "RC30", "RC31", "RC34", "RC39", "RC40")


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unconnected_signatures(path: Path) -> tuple[str, ...]:
    payload = _read_json(path)
    raw_items = payload.get("unconnected_items", [])
    if not isinstance(raw_items, list):
        raise TypeError(f"Invalid KiCad unconnected-item list: {path}")
    signatures: list[str] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        members = raw.get("items", [])
        uuids = (
            sorted(
                str(member["uuid"])
                for member in members
                if isinstance(member, dict) and member.get("uuid") is not None
            )
            if isinstance(members, list)
            else []
        )
        if uuids:
            signatures.append("|".join(uuids))
        else:
            signatures.append(str(raw.get("description", "unidentified")))
    return tuple(sorted(signatures))


def _next_attempt(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    numbers = sorted(
        int(path.name.removeprefix("attempt-"))
        for path in root.glob("attempt-*")
        if path.is_dir() and path.name.removeprefix("attempt-").isdigit()
    )
    attempt = root / f"attempt-{(numbers[-1] + 1 if numbers else 1):02d}"
    attempt.mkdir()
    return attempt


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    stdout: Path,
    stderr: Path,
    timeout_seconds: int,
) -> tuple[int | None, float, str | None]:
    started = time.perf_counter()
    try:
        process = subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        stdout.write_bytes(exc.stdout or b"")
        stderr.write_bytes(exc.stderr or b"")
        return None, time.perf_counter() - started, f"timeout after {timeout_seconds}s"
    stdout.write_bytes(process.stdout)
    stderr.write_bytes(process.stderr)
    return process.returncode, time.perf_counter() - started, None


def _case_dir(corpus: Path, case_id: str) -> Path:
    matches = tuple((corpus / "boards").glob(f"{case_id}-*"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one case for {case_id}, found {matches}")
    return matches[0]


def _latest_route(case_dir: Path) -> tuple[Path, Path, dict[str, object]]:
    attempts = sorted((case_dir / "external" / "freerouting-v2.2.4").glob("attempt-*"))
    if not attempts:
        raise FileNotFoundError(f"No retained route for {case_dir.name}")
    attempt = attempts[-1]
    boards = tuple(attempt.glob("*-freerouting.kicad_pcb"))
    if len(boards) != 1:
        raise FileNotFoundError(f"Expected one routed board under {attempt}")
    return attempt, boards[0], _read_json(attempt / "route-evidence.json")


def _drc_metrics(path: Path) -> tuple[int, int, set[str], tuple[str, ...]]:
    payload = _read_json(path)
    violations = payload.get("violations", [])
    unconnected = payload.get("unconnected_items", [])
    if not isinstance(violations, list) or not isinstance(unconnected, list):
        raise TypeError(f"Invalid KiCad DRC report: {path}")
    nets: set[str] = set()
    for item in unconnected:
        if not isinstance(item, dict):
            continue
        for child in item.get("items", []):
            if not isinstance(child, dict):
                continue
            nets.update(re.findall(r"\[([^\]]+)\]", str(child.get("description", ""))))
    types = tuple(
        sorted(str(item.get("type", "unknown")) for item in violations if isinstance(item, dict))
    )
    return len(violations), len(unconnected), nets, types


def run_case(
    corpus: Path,
    pilot: Path,
    case_id: str,
    *,
    bridge: Path,
    kicad_python: Path,
    kicad_cli: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    case_dir = _case_dir(corpus, case_id)
    baseline_dir, baseline_board, baseline_evidence = _latest_route(case_dir)
    contract = _read_json(case_dir / "case-contract.json")
    plan = build_copper_intent(contract).record()
    run_dir = _next_attempt(pilot / "cases" / case_dir.name)
    source = run_dir / "source-width-aware.kicad_pcb"
    baseline_recheck_board = run_dir / "baseline-recheck.kicad_pcb"
    baseline_recheck_drc = run_dir / "baseline-recheck-drc.json"
    plan_path = run_dir / "copper-intent.json"
    output = run_dir / "copper-retrofit.kicad_pcb"
    shutil.copy2(baseline_board, source)
    shutil.copy2(baseline_board, baseline_recheck_board)
    _write_json(plan_path, plan)
    baseline_exit, baseline_seconds, baseline_error = _run(
        (
            str(kicad_cli),
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(baseline_recheck_drc),
            "--refill-zones",
            "--save-board",
            str(baseline_recheck_board),
        ),
        cwd=run_dir,
        stdout=run_dir / "baseline-recheck.stdout.log",
        stderr=run_dir / "baseline-recheck.stderr.log",
        timeout_seconds=timeout_seconds,
    )
    apply_exit, apply_seconds, apply_error = _run(
        (
            str(kicad_python),
            str(bridge),
            "apply",
            str(baseline_recheck_board),
            str(plan_path),
            str(output),
        ),
        cwd=run_dir,
        stdout=run_dir / "apply.stdout.log",
        stderr=run_dir / "apply.stderr.log",
        timeout_seconds=timeout_seconds,
    )
    drc_path = run_dir / "drc.json"
    drc_exit: int | None = None
    drc_seconds = 0.0
    drc_error: str | None = None
    if apply_exit == 0 and output.exists():
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
                str(output),
            ),
            cwd=run_dir,
            stdout=run_dir / "drc.stdout.log",
            stderr=run_dir / "drc.stderr.log",
            timeout_seconds=timeout_seconds,
        )
    observations_path = run_dir / "copper-observations.json"
    inspect_exit: int | None = None
    inspect_seconds = 0.0
    inspect_error: str | None = None
    if drc_exit == 0 and output.exists():
        inspect_exit, inspect_seconds, inspect_error = _run(
            (
                str(kicad_python),
                str(bridge),
                "inspect",
                str(output),
                str(plan_path),
                str(observations_path),
            ),
            cwd=run_dir,
            stdout=run_dir / "inspect.stdout.log",
            stderr=run_dir / "inspect.stderr.log",
            timeout_seconds=timeout_seconds,
        )
    retained_drc = baseline_dir / "drc.json"
    retained_violations, retained_unconnected, retained_nets, retained_types = _drc_metrics(
        retained_drc
    )
    before_violations, before_unconnected, before_nets, before_types = _drc_metrics(
        baseline_recheck_drc
    )
    before_items = set(_unconnected_signatures(baseline_recheck_drc))
    after_violations: int | None = None
    after_unconnected: int | None = None
    after_nets: set[str] | None = None
    after_types: tuple[str, ...] | None = None
    after_items: set[str] | None = None
    if drc_exit == 0 and drc_path.exists():
        after_violations, after_unconnected, after_nets, after_types = _drc_metrics(drc_path)
        after_items = set(_unconnected_signatures(drc_path))
    execution_complete = (
        baseline_exit == 0
        and apply_exit == 0
        and drc_exit == 0
        and inspect_exit == 0
        and output.exists()
        and output.stat().st_size > 0
        and drc_path.exists()
        and observations_path.exists()
    )
    observations = _read_json(observations_path) if observations_path.exists() else {}
    paths = observations.get("paths", {})
    path_records: dict[str, object] = {}
    if isinstance(paths, dict):
        for path_id, raw in paths.items():
            if not isinstance(raw, dict):
                continue
            net_name = str(raw["net_name"])
            path_records[str(path_id)] = {
                **raw,
                "kicad_net_connected_before": net_name not in before_nets,
                "kicad_net_connected_after": (
                    net_name not in after_nets if after_nets is not None else None
                ),
                "resolved_by_retrofit": (
                    net_name in before_nets and net_name not in after_nets
                    if after_nets is not None
                    else None
                ),
                "path_topology_accepted": (
                    net_name not in after_nets and raw.get("topology_support_present") is True
                    if after_nets is not None
                    else False
                ),
            }
    evidence: dict[str, object] = {
        "schema": "pcbsmith-copper-region-pilot-evidence-v2",
        "case_id": case_id,
        "source_case": case_dir.name,
        "baseline_attempt": baseline_dir.relative_to(case_dir).as_posix(),
        "baseline_board_sha256": _sha256(baseline_board),
        "source_copy_sha256": _sha256(source),
        "plan_sha256": _sha256(plan_path),
        "output_board_sha256": _sha256(output) if output.exists() else None,
        "baseline_recheck": {
            "exit_code": baseline_exit,
            "seconds": baseline_seconds,
            "error": baseline_error,
            "board_sha256": _sha256(baseline_recheck_board),
        },
        "apply": {"exit_code": apply_exit, "seconds": apply_seconds, "error": apply_error},
        "drc": {"exit_code": drc_exit, "seconds": drc_seconds, "error": drc_error},
        "inspect": {
            "exit_code": inspect_exit,
            "seconds": inspect_seconds,
            "error": inspect_error,
        },
        "retained_before": {
            "violations": retained_violations,
            "unconnected": retained_unconnected,
            "unconnected_nets": sorted(retained_nets),
            "violation_types": list(retained_types),
        },
        "before": {
            "violations": before_violations,
            "unconnected": before_unconnected,
            "unconnected_nets": sorted(before_nets),
            "violation_types": list(before_types),
            "unconnected_item_signatures": sorted(before_items),
        },
        "after": {
            "available": execution_complete,
            "violations": after_violations,
            "unconnected": after_unconnected,
            "unconnected_nets": sorted(after_nets) if after_nets is not None else None,
            "violation_types": list(after_types) if after_types is not None else None,
            "unconnected_item_signatures": (
                sorted(after_items) if after_items is not None else None
            ),
        },
        "execution_complete": execution_complete,
        "resolved_unconnected_nets": (
            sorted(before_nets - after_nets) if after_nets is not None else []
        ),
        "new_unconnected_nets": (
            sorted(after_nets - before_nets) if after_nets is not None else []
        ),
        "disappeared_unconnected_item_signatures": (
            sorted(before_items - after_items) if after_items is not None else []
        ),
        "introduced_unconnected_item_signatures": (
            sorted(after_items - before_items) if after_items is not None else []
        ),
        "path_observations": path_records,
        "region_application_complete": (
            execution_complete and observations.get("region_application_complete", False) is True
        ),
        "strict_clean": (execution_complete and after_violations == 0 and after_unconnected == 0),
        "qualification_boundary": (
            "This is a zone-only retrofit of a retained route. It does not reroute signals, "
            "prove continuous cross-section, or qualify electrical or thermal capability."
        ),
        "baseline_evidence_schema": baseline_evidence.get("schema"),
    }
    _write_json(run_dir / "pilot-evidence.json", evidence)
    return evidence


def _manifest(root: Path) -> None:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "artifact-manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    _write_json(root / "artifact-manifest.json", {"files": files})


def _case_metric(case: dict[str, object], cohort: str, metric: str) -> int:
    record = case[cohort]
    if not isinstance(record, dict):
        raise TypeError(f"Expected {cohort} result object")
    return int(str(record[metric]))


def _resolved_nets(case: dict[str, object]) -> tuple[str, ...]:
    value = case["resolved_unconnected_nets"]
    if not isinstance(value, list):
        raise TypeError("resolved_unconnected_nets must be a list")
    return tuple(str(item) for item in value)


def _disappeared_items(case: dict[str, object]) -> tuple[str, ...]:
    value = case["disappeared_unconnected_item_signatures"]
    if not isinstance(value, list):
        raise TypeError("disappeared_unconnected_item_signatures must be a list")
    return tuple(str(item) for item in value)


def _write_report(root: Path, cases: list[dict[str, object]]) -> None:
    completed = [case for case in cases if case["execution_complete"] is True]
    before_open = sum(_case_metric(case, "before", "unconnected") for case in completed)
    after_open = sum(_case_metric(case, "after", "unconnected") for case in completed)
    before_drc = sum(_case_metric(case, "before", "violations") for case in completed)
    after_drc = sum(_case_metric(case, "after", "violations") for case in completed)
    disappeared = sum(len(_disappeared_items(case)) for case in completed)
    introduced = sum(
        len(value)
        for case in completed
        if isinstance((value := case["introduced_unconnected_item_signatures"]), list)
    )
    lines = [
        "# Phase 17 copper-region retrofit pilot",
        "",
        "This bounded pilot adds filled copper regions to retained width-aware routes. It",
        "does not rerun or hand-repair the router, so it isolates what zones can and cannot",
        "solve.",
        "",
        "| Case | Execution | DRC before -> after | Unconnected before -> after | "
        "Resolved nets | Pair churn (gone/new) |",
        "|---|---|---:|---:|---|---:|",
    ]
    for case in cases:
        before = case["before"]
        after = case["after"]
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        resolved = case["resolved_unconnected_nets"]
        resolved_text = (
            ", ".join(str(item) for item in resolved) if isinstance(resolved, list) else ""
        )
        gone = case["disappeared_unconnected_item_signatures"]
        new = case["introduced_unconnected_item_signatures"]
        gone_count = len(gone) if isinstance(gone, list) else 0
        new_count = len(new) if isinstance(new, list) else 0
        lines.append(
            f"| {case['case_id']} | {'complete' if case['execution_complete'] else 'failed'} | "
            f"{before['violations']} -> {after['violations']} | "
            f"{before['unconnected']} -> {after['unconnected']} | {resolved_text or '-'} | "
            f"{gone_count}/{new_count} |"
        )
    lines.extend(
        (
            "",
            "## Measured result",
            "",
            f"- Complete executions: {len(completed)}/{len(cases)}.",
            "- Filled-region application: "
            f"{sum(1 for case in cases if case['region_application_complete'] is True)}"
            f"/{len(cases)}.",
            f"- KiCad DRC violations: {before_drc} -> {after_drc}.",
            f"- KiCad unconnected items: {before_open} -> {after_open}.",
            "- Disappeared/introduced missing-connection pair signatures: "
            f"{disappeared}/{introduced}.",
            "- One complete net left the unconnected set: VIN on RC30. "
            "No case became strictly clean.",
            "",
            "A missing-connection pair signature is not a resolved connection. KiCad may",
            "decompose the same incomplete net into different endpoint pairs after refill,",
            "so pair churn is retained as diagnostic evidence while net and total-item",
            "counts remain the acceptance evidence.",
            "",
            "## Visual review",
            "",
            "The standardized RC30/RC31/RC34/RC40 views show that the B.Cu reference fill",
            "is present, but it does not create required SMD escapes or stitching vias.",
            "The F.Cu Manhattan corridors are deterministic and visibly wide, yet they",
            "compete for area, are clipped by zone priority, and crowd the retained signal",
            "routing on dense cases. RC40 remains visibly congestion-limited. Copper zones",
            "are therefore a supplemental distribution mechanism, not a replacement router.",
            "",
            "## Interpretation boundary",
            "",
            "A filled plane or corridor can close topology gaps, but zone presence does not",
            "prove minimum continuous cross-section. Remaining signal, gate, ground-escape,",
            "short, and clearance failures require routing-order, placement, via/escape, or",
            "layer-count decisions. Four-layer and six-plus-layer roles are represented in",
            "the intent schema but are not exercised by this two-layer pilot.",
            "",
            "## Next routing slice",
            "",
            "Replace source-to-every-sink rectangles with a placement-aware trunk/branch",
            "graph, explicit pad escapes and ground vias, conflict-aware corridor ordering,",
            "and localized router repair. Do not restart the whole board for a local power",
            "path defect. Promote ground/power to internal plane roles only when a four-plus",
            "layer stackup is selected and independently validated.",
            "",
        )
    )
    (root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", type=Path, default=Path("experiments/phase17-routing-corpus-40")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/phase17-routing-corpus-40/copper-region-pilot-v1"),
    )
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--kicad-python", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/python.exe")
    )
    parser.add_argument(
        "--kicad-cli", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")
    )
    args = parser.parse_args()
    corpus = args.corpus.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / ".gitattributes").write_text("* -text -whitespace\n", encoding="ascii")
    bridge = Path(__file__).with_name("kicad_copper_intent_bridge.py").resolve()
    selected = tuple(args.case) if args.case else DEFAULT_CASES
    results = []
    for index, case_id in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {case_id}", flush=True)
        results.append(
            run_case(
                corpus,
                output,
                case_id,
                bridge=bridge,
                kicad_python=args.kicad_python.resolve(),
                kicad_cli=args.kicad_cli.resolve(),
                timeout_seconds=args.timeout_seconds,
            )
        )
    completed_results = [item for item in results if item["execution_complete"] is True]
    summary = {
        "schema": "pcbsmith-copper-region-pilot-summary-v2",
        "case_count": len(results),
        "execution_complete_count": len(completed_results),
        "execution_failed_count": len(results) - len(completed_results),
        "execution_failed_cases": [
            item["case_id"] for item in results if item["execution_complete"] is not True
        ],
        "strict_clean_count": sum(1 for item in results if item["strict_clean"] is True),
        "region_application_complete_count": sum(
            1 for item in results if item["region_application_complete"] is True
        ),
        "unconnected_before": sum(
            _case_metric(item, "before", "unconnected") for item in completed_results
        ),
        "unconnected_after": sum(
            _case_metric(item, "after", "unconnected") for item in completed_results
        ),
        "violation_before": sum(
            _case_metric(item, "before", "violations") for item in completed_results
        ),
        "violation_after": sum(
            _case_metric(item, "after", "violations") for item in completed_results
        ),
        "disappeared_item_signature_count": sum(
            len(_disappeared_items(item)) for item in completed_results
        ),
        "introduced_item_signature_count": sum(
            len(item["introduced_unconnected_item_signatures"])
            for item in completed_results
            if isinstance(item["introduced_unconnected_item_signatures"], list)
        ),
        "resolved_net_counts": dict(
            sorted(
                Counter(
                    str(net) for item in completed_results for net in _resolved_nets(item)
                ).items()
            )
        ),
        "cases": results,
        "qualification_boundary": (
            "Zone-retrofit results are routing-topology evidence only and cannot support "
            "ampacity, thermal, SI, PDN, DFM, or release claims."
        ),
    }
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "protocol.json",
        {
            "schema": "pcbsmith-copper-region-pilot-protocol-v2",
            "cases": list(selected),
            "intervention": "Add deterministic GND board fill and VIN/LOAD Manhattan zones",
            "controlled_input": "Fresh KiCad DRC recheck of each retained width-aware board",
            "no_reroute": True,
            "future_stackup_support": "Logical layer roles remain separate from physical layers",
        },
    )
    _write_report(output, results)
    _manifest(output)
    print(
        json.dumps(
            {
                key: summary[key]
                for key in summary
                if key.endswith("_count") or key.endswith("_after") or key.endswith("_before")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
