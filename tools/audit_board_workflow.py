"""Fail when new or changed native-board callers lack an explicit workflow policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pcbsmith.workflow_entrypoint_audit import audit_workflow_callers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_workflow_callers(
        args.repository, args.repository / "docs/board-workflow-entrypoints.json"
    )
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
