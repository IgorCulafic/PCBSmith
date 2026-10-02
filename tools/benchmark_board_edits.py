"""Finite diagnostic replicas through the supported local-edit CLI.

Never edits the retained source project or transfers production acceptance.
Each independent measurement has one job, one edit, no retries. Source copying
and job overhead remain in wall time; native-check time is reported separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import time
from pathlib import Path

from pcbsmith.board_job import BoardJob, run_operation
from pcbsmith.board_revision import BoardRevisionRequest


def hashes(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--board-name", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=6, choices=range(1, 7))
    parser.add_argument("--total-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("benchmark output must be new")
    if Path(args.board_name).name != args.board_name:
        raise ValueError("board name must be local")
    if any(p.is_symlink() for p in args.source_project.rglob("*")):
        raise ValueError("benchmark source may not contain symlinks")
    cases = json.loads(args.cases.read_bytes())
    if len(cases) > 6 or not cases:
        raise ValueError("freeze one to six named cases")
    for name, request in cases.items():
        if not name.replace("-", "").isalnum():
            raise ValueError("unsafe case name")
        BoardRevisionRequest.model_validate(request)
    started = time.monotonic()
    original = hashes(args.source_project)
    args.output.mkdir(parents=True)
    (args.output / "protocol.json").write_text(
        json.dumps(
            dict(
                scope="isolated diagnostic replicas; not new-board acceptance",
                started_utc=time.time(),
                total_seconds=args.total_seconds,
                repetitions=args.repetitions,
                source=str(args.source_project.resolve()),
                source_hashes=original,
                cases=cases,
                execution_seconds_per_replica=180,
                evaluation_seconds_per_replica=120,
                retries=0,
            ),
            indent=2,
        )
        + "\n"
    )
    results = []
    for name, request in cases.items():
        for index in range(args.repetitions):
            if time.monotonic() - started >= args.total_seconds:
                raise RuntimeError("frozen benchmark aggregate allowance exhausted")
            case_started = time.monotonic()
            root = args.output / name / f"replica-{index:02d}"
            job = BoardJob(root)
            job.start(
                complexity="simple",
                rationale=(
                    f"Independent frozen diagnostic {name} replica {index}; "
                    "one local edit, no correction/retry, no production claim"
                ),
                seconds=180,
                evaluation_seconds=120,
            )
            shutil.copytree(args.source_project, root / "source")
            request_file = root / "request.json"
            request_file.write_text(json.dumps(request, indent=2) + "\n")
            operation = [
                "production-edit-board",
                str((root / "source" / args.board_name).resolve()),
                "--request",
                str(request_file.resolve()),
                "--output",
                str((root / "candidate").resolve()),
            ]
            code = run_operation(job, "pcbsmith.cli", operation)
            receipt_file = root / "candidate/revision.json"
            receipt = json.loads(receipt_file.read_bytes()) if receipt_file.is_file() else {}
            summary_file = root / "candidate/checks/summary.json"
            checks = json.loads(summary_file.read_bytes()) if summary_file.is_file() else {}
            delta_file = root / "candidate/delta.json"
            delta = json.loads(delta_file.read_bytes()) if delta_file.is_file() else {}
            row = dict(
                case=name,
                replica=index,
                run_kind="cold_process" if index == 0 else "warm_filesystem_new_worker",
                returncode=code,
                status=receipt.get("status", "failed"),
                wall_seconds=time.monotonic() - case_started,
                cad_workflow_seconds=receipt.get("elapsed_seconds"),
                native_check_seconds=checks.get("elapsed_seconds", 0),
                native_checks_invoked=int(bool(checks)),
                generator_invocations=0,
                router_invocations=0,
                changed_objects=len(delta.get("changed_ids", [])),
                preserved_objects=len(delta.get("protected_ids", [])),
                job_root=str(root.resolve()),
            )
            job.stop(
                "Frozen diagnostic measurement ended; no production acceptance", finished=code == 0
            )
            results.append(row)
            (args.output / "measurements.json").write_text(json.dumps(results, indent=2) + "\n")
            print(json.dumps(row), flush=True)
            if code:
                break  # Preserve one failed case; no polishing/retry loop.
    if hashes(args.source_project) != original:
        raise ValueError("retained source project changed during diagnostic benchmark")
    summaries = {}
    for name in cases:
        rows = [r for r in results if r["case"] == name]
        warm = [r["wall_seconds"] for r in rows if r["replica"] > 0 and r["returncode"] == 0]
        summaries[name] = dict(
            cold_seconds=rows[0]["wall_seconds"] if rows else None,
            warm_count=len(warm),
            warm_median_seconds=statistics.median(warm) if warm else None,
            warm_max_seconds=max(warm) if warm else None,
            all_success=all(r["returncode"] == 0 for r in rows),
            complete=len(rows) == args.repetitions,
        )
    (args.output / "summary.json").write_text(
        json.dumps(
            dict(
                source_preserved=True,
                total_seconds=time.monotonic() - started,
                cases=summaries,
                scope=(
                    "local working-CAD diagnostics; "
                    "no full regeneration/render/export or production acceptance"
                ),
            ),
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
