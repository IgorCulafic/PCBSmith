"""Build paper-ready tables and an honest report from all Phase 17 cohorts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return payload


def _attempt(case_dir: Path, number: int) -> dict[str, object]:
    return _read_json(
        case_dir
        / "external"
        / "freerouting-v2.2.4"
        / f"attempt-{number:02d}"
        / "route-evidence.json"
    )


def _latest_attempt(case_dir: Path) -> tuple[int, dict[str, object]]:
    root = case_dir / "external" / "freerouting-v2.2.4"
    candidates = sorted(root.glob("attempt-*/route-evidence.json"))
    if not candidates:
        raise FileNotFoundError(f"No route attempts under {root}")
    path = candidates[-1]
    return int(path.parent.name.removeprefix("attempt-")), _read_json(path)


def _placement_evidence(case_dir: Path, source_hash: str) -> dict[str, object]:
    path = case_dir / "placement-check" / f"revision-{source_hash[:12]}" / "placement-evidence.json"
    return _read_json(path)


def _nested(record: dict[str, object], name: str) -> dict[str, object]:
    value = record[name]
    if not isinstance(value, dict):
        raise TypeError(f"Expected object at {name}")
    return value


def _width_report(record: dict[str, object]) -> dict[str, object]:
    widths = record.get("widths")
    if not isinstance(widths, dict):
        return {}
    report = widths.get("report")
    return report if isinstance(report, dict) else {}


def _attempt_columns(record: dict[str, object], prefix: str) -> dict[str, object]:
    drc = _nested(record, "drc")
    geometry = _nested(record, "geometry")
    router = _nested(record, "router")
    widths = _width_report(record)
    nets = widths.get("nets", {})
    neckdowns = 0
    if isinstance(nets, dict):
        for value in nets.values():
            if isinstance(value, dict):
                neckdowns += int(str(value.get("narrower_segment_count", 0)))
    return {
        f"{prefix}_success": record["success"],
        f"{prefix}_drc_violations": drc["violation_count"],
        f"{prefix}_unconnected": drc["unconnected_count"],
        f"{prefix}_segments": geometry["segment_count"],
        f"{prefix}_vias": geometry["via_count"],
        f"{prefix}_router_seconds": router["seconds"],
        f"{prefix}_width_intent_accepted": widths.get("width_intent_accepted", "not-measured"),
        f"{prefix}_width_driven_nets": widths.get("width_driven_net_count", "not-measured"),
        f"{prefix}_neckdown_segments": neckdowns,
    }


def build_summary(root: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    tier_counts: dict[int, dict[str, int]] = defaultdict(
        lambda: {
            "cases": 0,
            "attempt_1_successes": 0,
            "attempt_2_successes": 0,
            "width_aware_successes": 0,
        }
    )
    failure_types: Counter[str] = Counter()
    latest_attempts: Counter[int] = Counter()
    total_neckdowns = 0
    width_accepted = 0
    for case_dir in sorted((root / "boards").iterdir()):
        if not case_dir.is_dir():
            continue
        contract = _read_json(case_dir / "case-contract.json")
        attempt_1 = _attempt(case_dir, 1)
        attempt_2 = _attempt(case_dir, 2)
        latest_number, width_aware = _latest_attempt(case_dir)
        latest_attempts[latest_number] += 1
        source_hash = str(width_aware["source_board_sha256"])
        placement = _placement_evidence(case_dir, source_hash)
        tier = int(str(contract["tier"]))
        tier_counts[tier]["cases"] += 1
        tier_counts[tier]["attempt_1_successes"] += int(attempt_1["success"] is True)
        tier_counts[tier]["attempt_2_successes"] += int(attempt_2["success"] is True)
        tier_counts[tier]["width_aware_successes"] += int(width_aware["success"] is True)
        width_report = _width_report(width_aware)
        width_accepted += int(width_report.get("width_intent_accepted") is True)
        width_nets = width_report.get("nets", {})
        case_neckdowns = 0
        if isinstance(width_nets, dict):
            case_neckdowns = sum(
                int(str(value.get("narrower_segment_count", 0)))
                for value in width_nets.values()
                if isinstance(value, dict)
            )
        total_neckdowns += case_neckdowns
        if width_aware["success"] is not True:
            drc = _nested(width_aware, "drc")
            types = drc["violation_types"]
            if isinstance(types, list):
                failure_types.update(str(item) for item in types)
            if int(str(drc["unconnected_count"])):
                failure_types["unconnected"] += 1
            if width_report.get("width_intent_accepted") is not True:
                failure_types["width-intent-rejected"] += 1
        placements = contract["placements"]
        nets = contract["nets"]
        if not isinstance(placements, list) or not isinstance(nets, list):
            raise TypeError("Contract placements and nets must be lists")
        widths = [float(str(item["width_mm"])) for item in nets if isinstance(item, dict)]
        row: dict[str, object] = {
            "case_id": contract["case_id"],
            "title": contract["title"],
            "tier": tier,
            "difficulty": contract["difficulty"],
            "component_count": len(placements),
            "net_count": len(nets),
            "maximum_width_mm": max(widths),
            "placement_board_sha256": source_hash,
            "placement_clean": placement["mechanical_clean"],
            "width_aware_attempt": latest_number,
        }
        row.update(_attempt_columns(attempt_1, "attempt_1"))
        row.update(_attempt_columns(attempt_2, "attempt_2"))
        row.update(_attempt_columns(width_aware, "width_aware"))
        rows.append(row)
    summary: dict[str, object] = {
        "schema": "pcbsmith-phase17-routing-comparison-v2",
        "case_count": len(rows),
        "attempt_1_successes": sum(row["attempt_1_success"] is True for row in rows),
        "attempt_2_successes": sum(row["attempt_2_success"] is True for row in rows),
        "width_aware_successes": sum(row["width_aware_success"] is True for row in rows),
        "width_intent_accepted_count": width_accepted,
        "width_aware_neckdown_segments": total_neckdowns,
        "latest_attempt_numbers": {
            str(key): value for key, value in sorted(latest_attempts.items())
        },
        "placement_clean_count": sum(row["placement_clean"] is True for row in rows),
        "tier_results": {str(key): value for key, value in sorted(tier_counts.items())},
        "width_aware_failure_types": dict(sorted(failure_types.items())),
        "authorized_inference": (
            "The corpus measures one pinned Freerouting/KiCad workflow on synthetic "
            "two-layer routing cases. It does not establish router superiority or "
            "electrical, thermal, manufacturing, or current-capacity qualification."
        ),
    }
    return rows, summary


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("No corpus rows")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, rows: list[dict[str, object]], summary: dict[str, object]) -> None:
    tiers = summary["tier_results"]
    if not isinstance(tiers, dict):
        raise TypeError("tier_results must be an object")
    table = [
        "| Tier | Cases | Attempt 1 | Topology-only | Width-aware |",
        "|---:|---:|---:|---:|---:|",
    ]
    for tier, value in sorted(tiers.items()):
        if not isinstance(value, dict):
            raise TypeError("tier result must be an object")
        table.append(
            f"| {tier} | {value['cases']} | {value['attempt_1_successes']} | "
            f"{value['attempt_2_successes']} | {value['width_aware_successes']} |"
        )
    failures = [row for row in rows if row["width_aware_success"] is not True]
    failure_lines = [
        (
            f"- **{row['case_id']} -- {row['title']}**: "
            f"{row['width_aware_drc_violations']} DRC violations, "
            f"{row['width_aware_unconnected']} unconnected items, "
            f"width intent `{row['width_aware_width_intent_accepted']}`, "
            f"{row['width_aware_neckdown_segments']} neck-down segments."
        )
        for row in failures
    ]
    case_count = summary["case_count"]
    first_passes = summary["attempt_1_successes"]
    topology_passes = summary["attempt_2_successes"]
    width_passes = summary["width_aware_successes"]
    report = f"""# Phase 17 forty-board routing corpus report

## Outcome

The retained corpus contains **{summary["case_count"]}** deterministic two-layer
KiCad projects in five tiers. Placement revision 4 passed the placement-only
KiCad gate on **{summary["placement_clean_count"]}/{summary["case_count"]}** cases.

Three immutable routing cohorts are retained:

- attempt 1, before placement correction: **{first_passes}/{case_count}** clean;
- attempt 2, corrected placement but topology-only 0.20 mm routing:
  **{topology_passes}/{case_count}** clean;
- latest width-aware routing: **{width_passes}/{case_count}** accepted.

The latest cohort accepts a case only when KiCad reports zero DRC violations and
zero unconnected items and every width-driven net contains its requested width.
**{summary["width_intent_accepted_count"]}/{case_count}** cases met the
width-intent check. The read-back retained **{summary["width_aware_neckdown_segments"]}**
narrower segments instead of silently presenting them as full-width current paths.

RC25 has an extra retained pilot, so its current cohort is attempt 4; the other 39
cases use attempt 3. No attempt was overwritten or hand-repaired.

## Results by tier

{chr(10).join(table)}

## Remaining width-aware failures

{chr(10).join(failure_lines)}

Freerouting process exit status is not an acceptance signal. Every imported board
is read back and checked by KiCad, and the width-aware run deliberately scores
lower than the topology-only run because wider copper materially changes the
routing problem.

## Corpus design

- Tiers 1-2 progress from sparse SOIC/TSSOP breakouts to QFN/TQFP fanout.
- Tier 3 adds dense fanout, crossed connector banks, and series termination.
- Tier 4 adds repeated MOSFET load channels and benchmark power widths from
  0.5 mm to 2.0 mm.
- Tier 5 combines dense fanout, repeated power channels, and constrained
  two-layer routing stress.
- Widths are benchmark intent only. They are not IPC-2152 current-capacity or
  thermal qualification.

## Review images

`review/representative/` contains current width-aware views for RC01, RC16, RC24,
RC31, RC34, and RC39. The prior topology-only views are retained under
`review/history/topology-only-attempt-02/`. Each set includes top/bottom 3D views
and combined/copper-only layer views.

## Reproduction boundary

- KiCad: 10.0.3
- Freerouting: 2.2.4, pinned JAR and retained SHA-256
- Java: private Eclipse Temurin 25 runtime; system Java was not modified
- Router threads: 1
- Maximum passes: 10
- Per-stage timeout: 120 seconds
- Placement gate: KiCad DRC violations reject; expected unrouted items are recorded
- Route gate: zero KiCad DRC violations, zero unconnected items, and requested
  widths present on every width-driven net

## Authorized inference

{summary["authorized_inference"]}
"""
    path.write_text(report, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    args = parser.parse_args()
    root = args.root.resolve()
    rows, summary = build_summary(root)
    _write_csv(root / "results.csv", rows)
    (root / "attempt-comparison.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_report(root / "EXPERIMENT-REPORT.md", rows, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
