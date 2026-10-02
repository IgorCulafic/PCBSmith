"""Revision-bound KiCad ERC and schematic-parity authority before routing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report
from pcbsmith.kicad.validate import kicad_erc_findings_from_json_text
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class PreRouteIntegrityEvidence(SemanticIrModel):
    """Fail-closed ERC/parity evidence for one exact placement revision."""

    schema_id: Literal["pcbsmith-pre-route-integrity-evidence"] = (
        "pcbsmith-pre-route-integrity-evidence"
    )
    schema_version: Literal[1] = 1
    board_file: str
    schematic_file: str
    board_sha256: str
    schematic_sha256: str
    erc_report_sha256: str
    drc_report_sha256: str
    erc_finding_count: int = Field(ge=0)
    drc_violation_count: int = Field(ge=0)
    drc_unconnected_item_count: int = Field(ge=0)
    schematic_parity_count: int = Field(ge=0)
    schematic_parity_evaluated: bool
    accepted: bool
    blockers: tuple[str, ...]
    evidence_fingerprint: str

    @model_validator(mode="after")
    def evidence_is_coherent(self) -> Self:
        for field_name in (
            "board_sha256",
            "schematic_sha256",
            "erc_report_sha256",
            "drc_report_sha256",
            "evidence_fingerprint",
        ):
            require_sha256(getattr(self, field_name), field_name)
        expected_blockers = _blockers(
            erc=self.erc_finding_count,
            drc=self.drc_violation_count,
            unconnected=self.drc_unconnected_item_count,
            parity=self.schematic_parity_count,
            parity_evaluated=self.schematic_parity_evaluated,
        )
        if self.blockers != expected_blockers:
            raise ValueError("pre-route integrity blockers are stale")
        if self.accepted != (not expected_blockers):
            raise ValueError("pre-route integrity disposition is stale")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != fingerprint(payload):
            raise ValueError("pre-route integrity evidence is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> PreRouteIntegrityEvidence:
        fields = dict(values)
        fields["blockers"] = _blockers(
            erc=fields["erc_finding_count"],
            drc=fields["drc_violation_count"],
            unconnected=fields["drc_unconnected_item_count"],
            parity=fields["schematic_parity_count"],
            parity_evaluated=fields["schematic_parity_evaluated"],
        )
        fields["accepted"] = not fields["blockers"]
        provisional = cls.model_construct(**fields, evidence_fingerprint="0" * 64)
        return cls(
            **fields,
            evidence_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
            ),
        )


def inspect_pre_route_integrity(
    *,
    board_file: Path,
    schematic_file: Path,
    erc_report: Path,
    drc_report: Path,
) -> PreRouteIntegrityEvidence:
    """Bind retained KiCad reports to their named sources and live file hashes."""

    board = board_file.resolve()
    schematic = schematic_file.resolve()
    erc_path = erc_report.resolve()
    drc_path = drc_report.resolve()
    erc_text = erc_path.read_text(encoding="utf-8")
    drc_text = drc_path.read_text(encoding="utf-8")
    erc_payload = _object(erc_text, "ERC")
    drc_payload = _object(drc_text, "DRC")
    if erc_payload.get("source") != schematic.name:
        raise ValueError("ERC report source does not name the supplied schematic")
    if drc_payload.get("source") != board.name:
        raise ValueError("DRC report source does not name the supplied board")
    parity_evaluated = "schematic_parity" in drc_payload and isinstance(
        drc_payload.get("schematic_parity"), list
    )
    drc_evidence = inspect_kicad_drc_report(drc_path)
    return PreRouteIntegrityEvidence.build(
        board_file=str(board),
        schematic_file=str(schematic),
        board_sha256=_sha(board),
        schematic_sha256=_sha(schematic),
        erc_report_sha256=_sha(erc_path),
        drc_report_sha256=_sha(drc_path),
        erc_finding_count=len(kicad_erc_findings_from_json_text(erc_text)),
        drc_violation_count=drc_evidence.violation_count,
        drc_unconnected_item_count=drc_evidence.unconnected_item_count,
        schematic_parity_count=drc_evidence.schematic_parity_count,
        schematic_parity_evaluated=parity_evaluated,
    )


def _object(text: str, name: str) -> dict[str, object]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"KiCad {name} report root is not an object")
    return payload


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blockers(
    *, erc: int, drc: int, unconnected: int, parity: int, parity_evaluated: bool
) -> tuple[str, ...]:
    blockers: list[str] = []
    if erc:
        blockers.append(f"erc_findings:{erc}")
    if drc:
        blockers.append(f"placement_drc_findings:{drc}")
    # Unconnected items are expected on an unrouted placement revision. Retain
    # their count for provenance, but close them only in the post-route gate.
    if not parity_evaluated:
        blockers.append("schematic_parity:not_evaluated")
    elif parity:
        blockers.append(f"schematic_parity_findings:{parity}")
    return tuple(blockers)


__all__ = ["PreRouteIntegrityEvidence", "inspect_pre_route_integrity"]
