"""Execute Phase 17 Part 4 exact-continuity and escape-technology gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from pcbsmith.kicad.escape_technology import (
    EscapeGeometryTrial,
    EscapeTechnologyIntent,
    derive_escape_technology_decision,
)
from pcbsmith.kicad.reference_continuity import parse_reference_continuity


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _placement_board(case_dir: Path) -> Path:
    matches = tuple(case_dir.glob("*-placement.kicad_pcb"))
    if len(matches) != 1:
        raise ValueError(f"expected one placement board in {case_dir}, found {len(matches)}")
    return matches[0]


def _latest_route(case_dir: Path) -> Path:
    root = case_dir / "external" / "freerouting-v2.2.4"
    candidates: list[tuple[str, Path]] = []
    for attempt in root.glob("attempt-*"):
        evidence = attempt / "route-evidence.json"
        boards = tuple(attempt.glob("*-freerouting.kicad_pcb"))
        if evidence.exists() and len(boards) == 1:
            payload = _read(evidence)
            if payload.get("routed_board_sha256") == _sha256(boards[0]):
                candidates.append((attempt.name, boards[0]))
    if not candidates:
        raise FileNotFoundError(f"no retained Freerouting candidate in {case_dir}")
    return sorted(candidates)[-1][1]


def _run_bridge(
    *,
    bridge: Path,
    kicad_python: Path,
    board: Path,
    contract: Path,
    output: Path,
    timeout: int,
    envelope: EscapeTechnologyIntent | None = None,
    skip_placement_audit: bool = False,
) -> tuple[dict[str, object], float]:
    command = [str(kicad_python), str(bridge), str(board), str(contract), str(output)]
    if envelope is not None:
        command.extend(
            (
                "--clearance-mm",
                str(envelope.copper_clearance_mm),
                "--via-diameter-mm",
                str(envelope.via_diameter_mm),
                "--trace-width-mm",
                str(envelope.trace_width_mm),
            )
        )
    if skip_placement_audit:
        command.append("--skip-placement-audit")
    started = time.monotonic()
    completed = subprocess.run(command, capture_output=True, check=False, timeout=timeout)
    seconds = time.monotonic() - started
    output.with_suffix(".stdout.log").write_bytes(completed.stdout)
    output.with_suffix(".stderr.log").write_bytes(completed.stderr)
    if completed.returncode or completed.stderr.strip() or not output.exists():
        raise RuntimeError(
            f"Part 4 bridge failed for {board.name}: exit={completed.returncode}, "
            f"stderr={completed.stderr.decode(errors='replace').strip()}"
        )
    return _read(output), seconds


def _blocked_placement_cases(summary: dict[str, object]) -> dict[str, dict[str, object]]:
    cases = summary.get("cases", [])
    if not isinstance(cases, list):
        raise TypeError("placement summary cases must be a list")
    return {
        str(item["case_id"]): item
        for item in cases
        if isinstance(item, dict)
        and item.get("two_layer_feasibility") == "escape_technology_or_footprint_change_required"
    }


def _geometry_trial(
    *,
    intent: EscapeTechnologyIntent,
    source_board_sha256: str,
    blocked_pad_ids: tuple[str, ...],
    observation: dict[str, object],
    observation_path: Path,
) -> EscapeGeometryTrial:
    audits = observation.get("pad_escape_audits", [])
    if not isinstance(audits, list):
        raise TypeError("pad escape audits must be a list")
    by_id = {
        str(item["pad_id"]): item
        for item in audits
        if isinstance(item, dict) and item.get("pad_id")
    }
    missing = set(blocked_pad_ids) - set(by_id)
    if missing:
        raise ValueError("geometry trial omitted blocked pads: " + ", ".join(sorted(missing)))
    legal = tuple(
        pad_id
        for pad_id in blocked_pad_ids
        if isinstance(by_id[pad_id].get("current_legal_candidates"), list)
        and bool(by_id[pad_id]["current_legal_candidates"])
    )
    blocked = tuple(pad_id for pad_id in blocked_pad_ids if pad_id not in legal)
    return EscapeGeometryTrial(
        candidate_id=intent.candidate_id,
        source_board_sha256=source_board_sha256,
        required_pad_ids=blocked_pad_ids,
        legal_pad_ids=legal,
        blocked_pad_ids=blocked,
        observation_sha256=_sha256(observation_path),
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    output_root = (args.output or root / "part4-v1").resolve()
    policy_path = args.policy.resolve()
    policy = _read(policy_path)
    raw_intents = policy.get("candidates", [])
    if not isinstance(raw_intents, list):
        raise TypeError("Part 4 policy candidates must be a list")
    intents = tuple(EscapeTechnologyIntent.model_validate(item) for item in raw_intents)
    trial_intents = tuple(
        item
        for item in intents
        if item.trace_width_mm is not None
        and item.copper_clearance_mm is not None
        and item.via_diameter_mm is not None
    )
    placement_summary = _read(root / "failure-placement-gate-v1" / "summary-placement.json")
    blocked_cases = _blocked_placement_cases(placement_summary)
    case_dirs = tuple(path for path in sorted((root / "boards").iterdir()) if path.is_dir())
    selected = set(args.cases or ())
    if selected:
        case_dirs = tuple(path for path in case_dirs if path.name.split("-", 1)[0] in selected)
    bridge_sha = _sha256(args.bridge.resolve())
    base_bridge_sha = _sha256(args.bridge.resolve().with_name("kicad_board_feasibility_bridge.py"))
    runner_sha = _sha256(Path(__file__).resolve())
    policy_sha = _sha256(policy_path)
    continuity_results: list[dict[str, object]] = []
    escape_results: list[dict[str, object]] = []
    for case_dir in case_dirs:
        case_id = case_dir.name.split("-", 1)[0]
        contract_path = case_dir / "case-contract.json"
        contract = _read(contract_path)
        routed = _latest_route(case_dir)
        routed_sha = _sha256(routed)
        continuity_dir = output_root / "continuity" / case_dir.name / f"revision-{routed_sha[:12]}"
        continuity_dir.mkdir(parents=True, exist_ok=True)
        continuity_path = continuity_dir / "physical-observation.json"
        observation, seconds = _run_bridge(
            bridge=args.bridge.resolve(),
            kicad_python=args.kicad_python.resolve(),
            board=routed,
            contract=contract_path,
            output=continuity_path,
            timeout=args.timeout,
            skip_placement_audit=True,
        )
        evidence = parse_reference_continuity(observation)
        if _sha256(routed) != routed_sha:
            raise RuntimeError(f"Part 4 changed routed source board {case_id}")
        continuity_result = {
            "case_id": case_id,
            "source_board_sha256": routed_sha,
            "observation_sha256": _sha256(continuity_path),
            "evidence_fingerprint": evidence.evidence_fingerprint,
            "disposition": evidence.disposition,
            "exact_pass_authorized": evidence.exact_pass_authorized,
            "signal_segment_count": evidence.signal_segment_count,
            "exact_supported_segment_count": evidence.exact_supported_segment_count,
            "exact_unsupported_segment_count": evidence.exact_unsupported_segment_count,
            "unsupported_geometry_segment_count": evidence.unsupported_geometry_segment_count,
            "transition_without_nearby_reference_via_count": (
                evidence.transition_without_nearby_reference_via_count
            ),
            "seconds": round(seconds, 6),
        }
        _write(continuity_dir / "result.json", continuity_result)
        continuity_results.append(continuity_result)

        blocked_case = blocked_cases.get(case_id)
        if blocked_case is None:
            continue
        placement = _placement_board(case_dir)
        placement_sha = _sha256(placement)
        blocked_pad_ids = tuple(
            sorted(str(item) for item in blocked_case["pads_without_current_escape"])
        )
        trials: list[EscapeGeometryTrial] = []
        trial_seconds = 0.0
        escape_dir = output_root / "escape" / case_dir.name / f"revision-{placement_sha[:12]}"
        escape_dir.mkdir(parents=True, exist_ok=True)
        for intent in trial_intents:
            observation_path = escape_dir / f"trial-{intent.candidate_id}.json"
            trial_observation, seconds = _run_bridge(
                bridge=args.bridge.resolve(),
                kicad_python=args.kicad_python.resolve(),
                board=placement,
                contract=contract_path,
                output=observation_path,
                timeout=args.timeout,
                envelope=intent,
            )
            trial_seconds += seconds
            trials.append(
                _geometry_trial(
                    intent=intent,
                    source_board_sha256=placement_sha,
                    blocked_pad_ids=blocked_pad_ids,
                    observation=trial_observation,
                    observation_path=observation_path,
                )
            )
        if _sha256(placement) != placement_sha:
            raise RuntimeError(f"Part 4 changed placement source board {case_id}")
        decision = derive_escape_technology_decision(
            case_id=case_id,
            source_board_sha256=placement_sha,
            copper_layer_count=int(contract["board"]["layers"]),
            blocked_pad_ids=blocked_pad_ids,
            intents=intents,
            trials=tuple(trials),
        )
        decision_path = escape_dir / "escape-technology-decision.json"
        _write(decision_path, decision.model_dump(mode="json"))
        escape_result = {
            "case_id": case_id,
            "source_board_sha256": placement_sha,
            "decision_fingerprint": decision.decision_fingerprint,
            "disposition": decision.disposition,
            "blocked_pad_ids": list(decision.blocked_pad_ids),
            "qualified_candidate_ids": list(decision.qualified_candidate_ids),
            "geometry_clean_candidate_ids": [
                item.candidate_id
                for item in decision.candidates
                if item.geometry_trial is not None and not item.geometry_trial.blocked_pad_ids
            ],
            "candidate_blockers": {
                item.candidate_id: list(item.blockers) for item in decision.candidates
            },
            "seconds": round(trial_seconds, 6),
        }
        _write(escape_dir / "result.json", escape_result)
        escape_results.append(escape_result)
    continuity_dispositions = Counter(item["disposition"] for item in continuity_results)
    escape_dispositions = Counter(item["disposition"] for item in escape_results)
    summary: dict[str, object] = {
        "schema": "pcbsmith-phase17-part4-summary-v1",
        "source_binding": {
            "runner_sha256": runner_sha,
            "bridge_sha256": bridge_sha,
            "base_bridge_sha256": base_bridge_sha,
            "policy_sha256": policy_sha,
        },
        "continuity": {
            "cases": len(continuity_results),
            "exact_pass_authorized": sum(
                item["exact_pass_authorized"] is True for item in continuity_results
            ),
            "dispositions": dict(sorted(continuity_dispositions.items())),
            "signal_segments": sum(
                int(item["signal_segment_count"]) for item in continuity_results
            ),
            "exact_supported_segments": sum(
                int(item["exact_supported_segment_count"]) for item in continuity_results
            ),
            "exact_unsupported_segments": sum(
                int(item["exact_unsupported_segment_count"]) for item in continuity_results
            ),
            "unsupported_geometry_segments": sum(
                int(item["unsupported_geometry_segment_count"]) for item in continuity_results
            ),
            "unstitched_signal_transitions": sum(
                int(item["transition_without_nearby_reference_via_count"])
                for item in continuity_results
            ),
            "results": continuity_results,
        },
        "escape_technology": {
            "cases": len(escape_results),
            "qualified_candidates": sum(
                len(item["qualified_candidate_ids"]) for item in escape_results
            ),
            "geometry_option_cases": sum(
                bool(item["geometry_clean_candidate_ids"]) for item in escape_results
            ),
            "dispositions": dict(sorted(escape_dispositions.items())),
            "results": escape_results,
        },
        "part_4_system_complete": len(continuity_results) == len(case_dirs)
        and len(escape_results)
        == len(set(blocked_cases) & {path.name.split("-", 1)[0] for path in case_dirs}),
        "part_4_corpus_release_blocked": any(
            item["exact_pass_authorized"] is not True for item in continuity_results
        )
        or any(not item["qualified_candidate_ids"] for item in escape_results),
        "automatic_board_mutation_authorized": False,
        "limitations": [
            (
                "exact continuity is scoped to straight-track centerline support and "
                "transition-via proximity"
            ),
            (
                "full trace-width reference support, SI, EMC, impedance, current density, "
                "and thermals remain separate authorities"
            ),
            "diagnostic escape geometry does not qualify a process or current path",
            "multilayer boards never receive an automatic pass",
        ],
    }
    _write(output_root / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("experiments/phase17-routing-corpus-40/part4-policy.json"),
    )
    parser.add_argument("--bridge", type=Path, default=Path("tools/kicad_board_part4_bridge.py"))
    parser.add_argument(
        "--kicad-python", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/python.exe")
    )
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
