"""Extract feedback-selected U1-to-series escape targets from routed KiCad DRC."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PAD_DESCRIPTION = re.compile(r"Pad\s+\S+\s+\[(?P<net>[^\]]+)\]\s+of\s+(?P<reference>\S+)\s+on\s+")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_feedback(root: Path) -> dict[str, object]:
    summary_path = root / "freerouting-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    targets: dict[str, list[str]] = {}
    evidence: list[dict[str, object]] = []
    for case in summary.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_id = str(case["case_id"])
        case_dir = next(
            path
            for path in sorted((root / "boards").iterdir())
            if path.is_dir() and path.name.startswith(f"{case_id}-")
        )
        attempt_dir = case_dir / str(case["attempt_directory"])
        drc_path = attempt_dir / "drc.json"
        if not drc_path.exists():
            continue
        drc = json.loads(drc_path.read_text(encoding="utf-8"))
        case_targets: set[str] = set()
        for finding in drc.get("unconnected_items", []):
            descriptions = tuple(
                str(item.get("description", ""))
                for item in finding.get("items", [])
                if isinstance(item, dict)
            )
            terminals = tuple(
                match.groupdict()
                for description in descriptions
                if (match := PAD_DESCRIPTION.search(description)) is not None
            )
            nets = {terminal["net"] for terminal in terminals}
            references = {terminal["reference"] for terminal in terminals}
            if (
                len(nets) == 1
                and "U1" in references
                and any(re.fullmatch(r"R\d+", reference) for reference in references)
            ):
                net_name = next(iter(nets))
                case_targets.add(net_name)
                evidence.append(
                    {
                        "case_id": case_id,
                        "net_name": net_name,
                        "descriptions": descriptions,
                        "drc_report": drc_path.relative_to(root).as_posix(),
                        "drc_report_sha256": _sha256(drc_path),
                        "source_board_sha256": case.get("source_board_sha256"),
                        "routed_board_sha256": case.get("routed_board_sha256"),
                    }
                )
        if case_targets:
            targets[case_id] = sorted(case_targets)
    return {
        "schema": "pcbsmith-two-layer-series-escape-feedback-v1",
        "source_root": root.as_posix(),
        "source_summary": summary_path.relative_to(root).as_posix(),
        "source_summary_sha256": _sha256(summary_path),
        "targets": targets,
        "evidence": evidence,
        "qualification_boundary": (
            "Targets are extracted only from exact routed-board KiCad unconnected-item "
            "evidence between U1 and numeric series resistors; they are repair requests, "
            "not proof that a proposed escape is legal or globally routable."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = extract_feedback(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["targets"], sort_keys=True))


if __name__ == "__main__":
    main()
