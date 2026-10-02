"""Run real KiCad ERC, DRC, and schematic parity on a W10 proof corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pcbsmith.kicad.validate import run_kicad_drc, run_kicad_erc


def validate_w10_root(root: Path) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for case_dir in sorted((root / "boards").iterdir()):
        case_id = case_dir.name.split("-", maxsplit=1)[0]
        schematic = next(case_dir.glob("*.kicad_sch"))
        board = next(
            path
            for path in case_dir.glob("*.kicad_pcb")
            if not path.name.endswith("-placement.kicad_pcb")
            and not path.name.endswith("-reference-routed.kicad_pcb")
        )
        erc = run_kicad_erc(schematic, report_name="upstream-erc.json")
        drc = run_kicad_drc(board, schematic_parity=True)
        records.append(
            {
                "case_id": case_id,
                "schematic": str(schematic),
                "board": str(board),
                "erc_status": erc.status,
                "erc_findings": list(erc.findings),
                "erc_report": erc.erc_report,
                "drc_status": drc.status,
                "drc_findings": list(drc.findings),
                "drc_report": drc.drc_report,
                "schematic_parity_clean": drc.status == "passed"
                and not any(finding.startswith("schematic_parity/") for finding in drc.findings),
            }
        )
    return {
        "schema": "pcbsmith-phase17-w10-upstream-validation-v1",
        "case_count": len(records),
        "erc_clean_count": sum(item["erc_status"] == "passed" for item in records),
        "drc_and_parity_clean_count": sum(item["drc_status"] == "passed" for item in records),
        "cases": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    summary = validate_w10_root(root)
    output = root / "upstream-validation-summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return (
        0
        if (
            summary["erc_clean_count"] == summary["case_count"]
            and summary["drc_and_parity_clean_count"] == summary["case_count"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
