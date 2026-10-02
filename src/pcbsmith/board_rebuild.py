"""Explicit rebuild authority for a native predecessor; never a local-edit fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from pcbsmith.kicad.project_dependencies import native_project_hashes
from pcbsmith.manufacturing_lineage import file_sha256
from pcbsmith.operations.file_transaction import project_path, require_complete_project
from pcbsmith.semantic_ir import SemanticIrModel


class RebuildDecision(SemanticIrModel):
    schema_id: Literal["pcbsmith-rebuild-decision"] = "pcbsmith-rebuild-decision"
    source_inputs: dict[str, str] = Field(min_length=1)
    reason: Literal[
        "architecture_change",
        "interface_or_layer_change",
        "incompatible_packages",
        "invalid_predecessor",
        "exhausted_local_repairs",
    ]
    rationale: str = Field(min_length=20)
    authorization_reference: str = Field(min_length=1)
    invalidated_requirements: tuple[str, ...] = Field(min_length=1)
    local_alternatives: tuple[str, ...] = Field(min_length=1)
    retained_attempts: dict[str, str] = Field(default_factory=dict)


def rebuild_input_hashes(board: Path) -> dict[str, str]:
    return native_project_hashes(board)


def require_generation_mode(schematic: Path, decision: RebuildDecision | None) -> Path | None:
    require_complete_project(schematic.parent)
    predecessor = schematic.with_suffix(".kicad_pcb")
    has_edits = (schematic.parent / ".pcbsmith/accepted-board-edits.json").exists()
    if not predecessor.exists():
        if has_edits or decision is not None:
            raise ValueError(
                "rebuild predecessor is missing; accepted native edits cannot be discarded"
            )
        return None
    if decision is None:
        raise ValueError(
            "existing PCB requires production-edit-board or an explicit rebuild decision"
        )
    if decision.source_inputs != rebuild_input_hashes(predecessor):
        raise ValueError("rebuild decision does not match exact current native inputs")
    if decision.reason == "exhausted_local_repairs" and not decision.retained_attempts:
        raise ValueError("exhausted local repairs require retained attempt evidence")
    for relative, digest in decision.retained_attempts.items():
        evidence = project_path(schematic.parent, relative)
        if not evidence.is_file() or file_sha256(evidence) != digest:
            raise ValueError("rebuild attempt evidence is missing or stale")
        attempt = json.loads(evidence.read_bytes())
        if (
            attempt.get("schema") != "pcbsmith-board-revision-v1"
            or attempt.get("status") not in {"failed", "blocked_candidate"}
            or any(
                attempt.get("source_inputs", {}).get(k) != v
                for k, v in decision.source_inputs.items()
            )
        ):
            raise ValueError("rebuild attempt is not a failed edit of this predecessor")
    return predecessor
