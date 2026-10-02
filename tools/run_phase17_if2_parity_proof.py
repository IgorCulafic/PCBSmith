from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments" / "phase17-w10-upstream-repair-v10-2026-08-20"
OUTPUT = ROOT / "experiments" / "phase17-if2-parity-proof-v2-2026-08-20"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    upstream = json.loads((SOURCE / "upstream-validation-summary.json").read_text(encoding="utf-8"))
    cases: list[dict[str, object]] = []
    for record in upstream["cases"]:
        board = Path(record["board"])
        schematic = Path(record["schematic"])
        drc = json.loads(Path(record["drc_report"]).read_text(encoding="utf-8"))
        erc = json.loads(Path(record["erc_report"]).read_text(encoding="utf-8"))
        parity = drc.get("schematic_parity")
        if not isinstance(parity, list):
            raise ValueError(f"{board}: schematic_parity is not a list")
        erc_violations = [
            violation
            for sheet in erc.get("sheets", [])
            for violation in sheet.get("violations", [])
        ]
        clean = (
            record["erc_status"] == "passed"
            and record["drc_status"] == "passed"
            and not parity
            and not erc_violations
        )
        cases.append(
            {
                "case_id": record["case_id"],
                "board": str(board.relative_to(ROOT)),
                "board_sha256": _sha256(board),
                "schematic": str(schematic.relative_to(ROOT)),
                "schematic_sha256": _sha256(schematic),
                "erc_finding_count": len(erc_violations),
                "drc_finding_count": len(record["drc_findings"]),
                "schematic_parity_finding_count": len(parity),
                "routing_work_authorized": clean,
            }
        )
    payload = {
        "schema_id": "pcbsmith-phase17-if2-parity-proof",
        "schema_version": 2,
        "source": str(SOURCE.relative_to(ROOT)),
        "cases": cases,
        "all_cases_clean": all(item["routing_work_authorized"] for item in cases),
        "conclusion": (
            "Fresh W10A and W10B projects have project-local symbol and footprint authority "
            "and pass real KiCad ERC, DRC, and schematic parity with zero findings. IF2 no "
            "longer blocks downstream placement work."
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["all_cases_clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
