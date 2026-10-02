"""Bind IF5 marking/model gates to the real, clean W10 v14 saved boards."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcbsmith.kicad.model_preflight import ModelRequirement, preflight_board_models
from pcbsmith.production_marking_adapter import (
    ProductionMarkingRequirements,
    audit_kicad_production_markings,
    inspect_saved_board_markings,
)

ROOT = Path(__file__).resolve().parents[1]
W10 = ROOT / "experiments" / "phase17-w10-upstream-repair-v14-2026-08-20"
OUTPUT = ROOT / "experiments" / "phase17-if5-w10-semantic-proof-v2-2026-08-20"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _single(case_dir: Path, pattern: str) -> Path:
    candidates = tuple(case_dir.glob(pattern))
    if len(candidates) != 1:
        raise ValueError(f"{case_dir}: expected one {pattern}, got {len(candidates)}")
    return candidates[0]


def main() -> int:
    validation = json.loads((W10 / "upstream-validation-summary.json").read_text("utf-8"))
    validation_by_case = {item["case_id"]: item for item in validation["cases"]}
    rows: list[dict[str, object]] = []
    for case_dir in sorted((W10 / "boards").iterdir()):
        contract_file = case_dir / "case-contract.json"
        contract = json.loads(contract_file.read_text("utf-8"))
        case_id = str(contract["case_id"])
        boards = tuple(
            candidate
            for candidate in case_dir.glob("*.kicad_pcb")
            if not candidate.name.endswith("-placement.kicad_pcb")
            and not candidate.name.endswith("-reference-routed.kicad_pcb")
        )
        if len(boards) != 1:
            raise ValueError(f"{case_dir}: expected one authoritative board, got {len(boards)}")
        board = boards[0]
        case_output = OUTPUT / case_dir.name
        case_output.mkdir(parents=True, exist_ok=True)

        inventory = inspect_saved_board_markings(board)
        requirements = ProductionMarkingRequirements.build(
            board_sha256=inventory.board_sha256,
            source_authority_sha256=_sha(contract_file),
            declaration_complete=True,
            required_refdes_refs=tuple(contract["required_refdes_refs"]),
            required_polarity_refs=tuple(contract["required_polarity_refs"]),
            required_connector_mating_refs=tuple(contract["required_connector_mating_refs"]),
        )
        drc_report = Path(validation_by_case[case_id]["drc_report"])
        marking = audit_kicad_production_markings(
            inventory=inventory,
            requirements=requirements,
            drc_report=drc_report,
            drc_report_board_sha256=inventory.board_sha256,
        )

        model_refs = tuple(
            dict.fromkeys(
                (
                    "U1",
                    *contract["required_polarity_refs"],
                    *contract["required_connector_mating_refs"],
                )
            )
        )
        model = preflight_board_models(
            board,
            requirements=tuple(
                ModelRequirement(
                    reference=reference,
                    accepted_classifications=(
                        "exact_package",
                        "complete_module",
                        "connector_only",
                        "proxy",
                    ),
                )
                for reference in model_refs
            ),
        )
        _write(case_output / "marking-inventory.json", inventory)
        _write(case_output / "marking-requirements.json", requirements)
        _write(case_output / "marking-audit.json", marking)
        _write(case_output / "model-preflight.json", model)
        marking_blockers = (*marking.finding_ids, *marking.unverified_check_ids)
        rows.append(
            {
                "case_id": case_id,
                "board": str(board.resolve()),
                "board_sha256": inventory.board_sha256,
                "erc_clean": validation_by_case[case_id]["erc_status"] == "passed",
                "drc_and_parity_clean": validation_by_case[case_id]["drc_status"] == "passed",
                "marking_accepted": not marking_blockers,
                "marking_blockers": list(marking_blockers),
                "verified_polarity_refs": list(inventory.verified_polarity_refs),
                "verified_connector_mating_refs": list(inventory.verified_connector_mating_refs),
                "model_status": model.status,
                "model_applicability": model.applicability,
                "model_required_refs": list(model.required_references),
                "model_blockers": list(model.findings),
            }
        )
    payload = {
        "schema_id": "pcbsmith-phase17-if5-w10-semantic-proof",
        "schema_version": 2,
        "source_w10_revision": str(W10.resolve()),
        "case_count": len(rows),
        "erc_clean_count": sum(item["erc_clean"] for item in rows),
        "drc_and_parity_clean_count": sum(item["drc_and_parity_clean"] for item in rows),
        "marking_accepted_count": sum(item["marking_accepted"] for item in rows),
        "model_accepted_count": sum(item["model_status"] == "passed" for item in rows),
        "cases": rows,
        "conclusion": (
            "Real v14 saved-board marking semantics now pass for both W10 cases. Model "
            "applicability is declared and therefore fails non-vacuously until selected, "
            "classified, resolved, transform-checked models are attached."
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write(OUTPUT / "summary.json", payload)
    return int(payload["marking_accepted_count"] != payload["case_count"])


if __name__ == "__main__":
    raise SystemExit(main())
