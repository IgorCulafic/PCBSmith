"""Run the shared-tree and ground-escape Phase 17 copper topology pilot."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.copper_topology_intent import build_copper_topology_intent
from tools.run_phase17_copper_region_pilot import (
    DEFAULT_CASES,
    _case_dir,
    _drc_metrics,
    _latest_route,
    _manifest,
    _next_attempt,
    _read_json,
    _run,
    _sha256,
    _write_json,
)


def _count_true_records(payload: object, field: str) -> int:
    if not isinstance(payload, dict):
        return 0
    return sum(
        1 for value in payload.values() if isinstance(value, dict) and value.get(field) is True
    )


def _required_escape_counts(payload: object) -> tuple[int, int, int]:
    if not isinstance(payload, dict):
        return 0, 0, 0
    required = [
        value
        for value in payload.values()
        if isinstance(value, dict) and value.get("required") is True
    ]
    satisfied = sum(1 for value in required if value.get("satisfied") is True)
    return len(required), satisfied, len(required) - satisfied


def _semantic_unconnected_signatures(path: Path) -> tuple[str, ...]:
    payload = _read_json(path)
    raw_items = payload.get("unconnected_items", [])
    if not isinstance(raw_items, list):
        raise TypeError(f"Invalid KiCad unconnected-item list: {path}")
    signatures: list[str] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        members = raw.get("items", [])
        semantic_members: list[str] = []
        if isinstance(members, list):
            for member in members:
                if not isinstance(member, dict):
                    continue
                description = str(member.get("description", "unidentified"))
                position = member.get("pos")
                if isinstance(position, dict):
                    x = float(str(position.get("x", 0.0)))
                    y = float(str(position.get("y", 0.0)))
                    description = f"{description}@{x:.4f},{y:.4f}"
                semantic_members.append(description)
        signatures.append(
            "|".join(sorted(semantic_members))
            if semantic_members
            else str(raw.get("description", "unidentified"))
        )
    return tuple(sorted(signatures))


def run_case(
    corpus: Path,
    pilot: Path,
    case_id: str,
    *,
    bridge: Path,
    kicad_python: Path,
    kicad_cli: Path,
    timeout_seconds: int,
    allow_diagnostic_via_in_pad: bool,
) -> dict[str, object]:
    case_dir = _case_dir(corpus, case_id)
    baseline_dir, baseline_board, baseline_evidence = _latest_route(case_dir)
    contract = _read_json(case_dir / "case-contract.json")
    plan = build_copper_topology_intent(
        contract, allow_diagnostic_via_in_pad=allow_diagnostic_via_in_pad
    ).record()
    run_dir = _next_attempt(pilot / "cases" / case_dir.name)
    source = run_dir / "source-width-aware.kicad_pcb"
    baseline_board_copy = run_dir / "baseline-recheck.kicad_pcb"
    baseline_drc = run_dir / "baseline-recheck-drc.json"
    plan_path = run_dir / "copper-topology-intent.json"
    output = run_dir / "copper-topology.kicad_pcb"
    post_drc = run_dir / "drc.json"
    observations_path = run_dir / "copper-topology-observations.json"
    shutil.copy2(baseline_board, source)
    shutil.copy2(baseline_board, baseline_board_copy)
    _write_json(plan_path, plan)

    baseline_exit, baseline_seconds, baseline_error = _run(
        (
            str(kicad_cli),
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(baseline_drc),
            "--refill-zones",
            "--save-board",
            str(baseline_board_copy),
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
            str(baseline_board_copy),
            str(plan_path),
            str(output),
        ),
        cwd=run_dir,
        stdout=run_dir / "apply.stdout.log",
        stderr=run_dir / "apply.stderr.log",
        timeout_seconds=timeout_seconds,
    )
    drc_exit: int | None = None
    drc_seconds = 0.0
    drc_error: str | None = None
    if apply_exit == 0 and output.exists() and output.stat().st_size > 0:
        drc_exit, drc_seconds, drc_error = _run(
            (
                str(kicad_cli),
                "pcb",
                "drc",
                "--format",
                "json",
                "--output",
                str(post_drc),
                "--refill-zones",
                "--save-board",
                str(output),
            ),
            cwd=run_dir,
            stdout=run_dir / "drc.stdout.log",
            stderr=run_dir / "drc.stderr.log",
            timeout_seconds=timeout_seconds,
        )
    inspect_exit: int | None = None
    inspect_seconds = 0.0
    inspect_error: str | None = None
    if drc_exit == 0 and post_drc.exists():
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

    before_violations, before_open, before_nets, before_types = _drc_metrics(baseline_drc)
    before_items = set(_semantic_unconnected_signatures(baseline_drc))
    after_violations: int | None = None
    after_open: int | None = None
    after_nets: set[str] | None = None
    after_types: tuple[str, ...] | None = None
    after_items: set[str] | None = None
    if drc_exit == 0 and post_drc.exists():
        after_violations, after_open, after_nets, after_types = _drc_metrics(post_drc)
        after_items = set(_semantic_unconnected_signatures(post_drc))
    execution_complete = (
        baseline_exit == 0
        and apply_exit == 0
        and drc_exit == 0
        and inspect_exit == 0
        and output.exists()
        and output.stat().st_size > 0
        and observations_path.exists()
    )
    observations = _read_json(observations_path) if observations_path.exists() else {}
    escapes = observations.get("escapes", {})
    paths = observations.get("paths", {})
    via_in_pad_count = _count_true_records(escapes, "via_in_pad_fallback_used")
    required_escapes, satisfied_escapes, unsatisfied_escapes = _required_escape_counts(escapes)
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
                "path_topology_accepted": (
                    net_name not in after_nets and raw.get("topology_support_present") is True
                    if after_nets is not None
                    else False
                ),
            }
    kicad_clean = execution_complete and after_violations == 0 and after_open == 0
    evidence: dict[str, object] = {
        "schema": "pcbsmith-copper-topology-pilot-evidence-v2",
        "case_id": case_id,
        "source_case": case_dir.name,
        "baseline_attempt": baseline_dir.relative_to(case_dir).as_posix(),
        "baseline_board_sha256": _sha256(baseline_board),
        "source_copy_sha256": _sha256(source),
        "plan_sha256": _sha256(plan_path),
        "output_board_sha256": _sha256(output) if output.exists() else None,
        "execution": {
            "baseline": {
                "exit_code": baseline_exit,
                "seconds": baseline_seconds,
                "error": baseline_error,
            },
            "apply": {
                "exit_code": apply_exit,
                "seconds": apply_seconds,
                "error": apply_error,
            },
            "drc": {"exit_code": drc_exit, "seconds": drc_seconds, "error": drc_error},
            "inspect": {
                "exit_code": inspect_exit,
                "seconds": inspect_seconds,
                "error": inspect_error,
            },
        },
        "execution_complete": execution_complete,
        "before": {
            "violations": before_violations,
            "unconnected": before_open,
            "unconnected_nets": sorted(before_nets),
            "violation_types": list(before_types),
            "unconnected_item_signatures": sorted(before_items),
        },
        "after": {
            "available": execution_complete,
            "violations": after_violations,
            "unconnected": after_open,
            "unconnected_nets": sorted(after_nets) if after_nets is not None else None,
            "violation_types": list(after_types) if after_types is not None else None,
            "unconnected_item_signatures": (
                sorted(after_items) if after_items is not None else None
            ),
        },
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
        "application_complete": (
            execution_complete and observations.get("application_complete") is True
        ),
        "region_application_complete": observations.get("region_application_complete", False),
        "escape_application_complete": observations.get("escape_application_complete", False),
        "diagnostic_via_in_pad_count": via_in_pad_count,
        "required_ground_escape_count": required_escapes,
        "satisfied_ground_escape_count": satisfied_escapes,
        "unsatisfied_ground_escape_count": unsatisfied_escapes,
        "path_observations": path_records,
        "kicad_clean": kicad_clean,
        "manufacturing_policy_clean": kicad_clean and via_in_pad_count == 0,
        "qualification_boundary": (
            "A KiCad-clean result using diagnostic via-in-pad fallbacks is not assembly or "
            "release qualified. Continuous width, current, voltage-drop, thermal, via, "
            "stackup, DFM, and assembly evidence remain separate gates."
        ),
        "baseline_evidence_schema": baseline_evidence.get("schema"),
    }
    _write_json(run_dir / "pilot-evidence.json", evidence)
    return evidence


def _metric(case: dict[str, object], cohort: str, metric: str) -> int:
    record = case[cohort]
    if not isinstance(record, dict) or record[metric] is None:
        raise TypeError(f"Missing {cohort}.{metric}")
    return int(str(record[metric]))


def _list_length(case: dict[str, object], key: str) -> int:
    value = case[key]
    return len(value) if isinstance(value, list) else 0


def _write_report(
    root: Path,
    cases: list[dict[str, object]],
    *,
    diagnostic_via_in_pad: bool,
) -> None:
    completed = [case for case in cases if case["execution_complete"] is True]
    before_open = sum(_metric(case, "before", "unconnected") for case in completed)
    after_open = sum(_metric(case, "after", "unconnected") for case in completed)
    before_drc = sum(_metric(case, "before", "violations") for case in completed)
    after_drc = sum(_metric(case, "after", "violations") for case in completed)
    lines = [
        "# Phase 17 shared-tree and ground-escape pilot",
        "",
        "This no-reroute A/B pilot replaces per-sink power rectangles with one shared",
        "placement-resolved tree per multi-terminal power net. It adds short ground",
        "escape tracks and through vias, with an explicitly diagnostic via-in-pad",
        "fallback only when the run explicitly enables that diagnostic mode.",
        f"Diagnostic via-in-pad enabled: {diagnostic_via_in_pad}.",
        "",
        "| Case | DRC before -> after | Open before -> after | Resolved nets | "
        "Via-in-pad | KiCad clean | Manufacturing-policy clean |",
        "|---|---:|---:|---|---:|---|---|",
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
        lines.append(
            f"| {case['case_id']} | {before['violations']} -> {after['violations']} | "
            f"{before['unconnected']} -> {after['unconnected']} | {resolved_text or '-'} | "
            f"{case['diagnostic_via_in_pad_count']} | {case['kicad_clean']} | "
            f"{case['manufacturing_policy_clean']} |"
        )
    resolved_nets: Counter[str] = Counter()
    for case in completed:
        resolved = case["resolved_unconnected_nets"]
        if isinstance(resolved, list):
            resolved_nets.update(str(net) for net in resolved)
    kicad_clean_count = sum(1 for case in cases if case["kicad_clean"] is True)
    required_escape_count = sum(
        int(str(case["required_ground_escape_count"])) for case in completed
    )
    satisfied_escape_count = sum(
        int(str(case["satisfied_ground_escape_count"])) for case in completed
    )
    unsatisfied_escape_count = sum(
        int(str(case["unsatisfied_ground_escape_count"])) for case in completed
    )
    manufacturing_clean_count = sum(
        1 for case in cases if case["manufacturing_policy_clean"] is True
    )
    lines.extend(
        (
            "",
            "## Measured result",
            "",
            f"- Complete executions: {len(completed)}/{len(cases)}.",
            f"- KiCad DRC violations: {before_drc} -> {after_drc}.",
            f"- KiCad unconnected items: {before_open} -> {after_open}.",
            f"- KiCad-clean boards: {kicad_clean_count}/{len(cases)}.",
            f"- Manufacturing-policy-clean boards: {manufacturing_clean_count}/{len(cases)}.",
            f"- Required ground escapes: {required_escape_count}.",
            f"- Satisfied legal ground escapes: {satisfied_escape_count}.",
            f"- Unsatisfied legal ground escapes: {unsatisfied_escape_count}.",
            f"- Resolved complete-net counts: {dict(sorted(resolved_nets.items()))}.",
            "",
            "## Interpretation boundary",
            "",
            "A diagnostic via-in-pad fallback isolates topology feasibility but is not a",
            "budget-assembly solution. Boards using it require component movement, a legal",
            "offset escape, or a fabrication/assembly process that explicitly supports",
            "filled and capped via-in-pad. Four-plus-layer role mappings remain unexercised.",
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
        default=Path("experiments/phase17-routing-corpus-40/copper-topology-pilot-v3-safe"),
    )
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--diagnostic-via-in-pad", action="store_true")
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
    bridge = Path(__file__).with_name("kicad_copper_topology_bridge.py").resolve()
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
                allow_diagnostic_via_in_pad=args.diagnostic_via_in_pad,
            )
        )
    completed = [item for item in results if item["execution_complete"] is True]
    summary = {
        "schema": "pcbsmith-copper-topology-pilot-summary-v2",
        "case_count": len(results),
        "execution_complete_count": len(completed),
        "execution_failed_count": len(results) - len(completed),
        "application_complete_count": sum(
            1 for item in results if item["application_complete"] is True
        ),
        "kicad_clean_count": sum(1 for item in results if item["kicad_clean"] is True),
        "manufacturing_policy_clean_count": sum(
            1 for item in results if item["manufacturing_policy_clean"] is True
        ),
        "diagnostic_via_in_pad_enabled": args.diagnostic_via_in_pad,
        "diagnostic_via_in_pad_count": sum(
            int(str(item["diagnostic_via_in_pad_count"])) for item in completed
        ),
        "required_ground_escape_count": sum(
            int(str(item["required_ground_escape_count"])) for item in completed
        ),
        "satisfied_ground_escape_count": sum(
            int(str(item["satisfied_ground_escape_count"])) for item in completed
        ),
        "unsatisfied_ground_escape_count": sum(
            int(str(item["unsatisfied_ground_escape_count"])) for item in completed
        ),
        "unconnected_before": sum(_metric(item, "before", "unconnected") for item in completed),
        "unconnected_after": sum(_metric(item, "after", "unconnected") for item in completed),
        "violation_before": sum(_metric(item, "before", "violations") for item in completed),
        "violation_after": sum(_metric(item, "after", "violations") for item in completed),
        "disappeared_item_signature_count": sum(
            _list_length(item, "disappeared_unconnected_item_signatures") for item in completed
        ),
        "introduced_item_signature_count": sum(
            _list_length(item, "introduced_unconnected_item_signatures") for item in completed
        ),
        "cases": results,
        "qualification_boundary": (
            "KiCad topology cleanliness is separate from manufacturing-policy, ampacity, "
            "thermal, SI/PDN, DFM, assembly, stackup, and release qualification."
        ),
    }
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "protocol.json",
        {
            "schema": "pcbsmith-copper-topology-pilot-protocol-v2",
            "cases": list(selected),
            "intervention": "Shared power trees plus bounded ground escapes",
            "diagnostic_via_in_pad_fallback": args.diagnostic_via_in_pad,
            "no_reroute": True,
            "future_stackup_support": "Logical roles remain separate from physical layers",
        },
    )
    _write_report(output, results, diagnostic_via_in_pad=args.diagnostic_via_in_pad)
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
