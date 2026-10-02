"""Prepare ordinary routing inputs from retained source records, without approvals.

Native layout synchronization is a separate read-only step before engineering
review. This adapter assembles typed records and replays the existing entry gate;
it never changes a record to make that gate pass or starts a board worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import model_validator

from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.project_dependencies import project_footprint_scope
from pcbsmith.kicad.routing_candidate_transaction import require_saved_layout_matches
from pcbsmith.production_routing import RoutingGateInputs
from pcbsmith.production_workflow import resolve_current_generation
from pcbsmith.routed_copper_graph_ir import require_sha256
from pcbsmith.rule_profiles import PcbRuleProfile
from pcbsmith.semantic_ir import SemanticIrModel


class RoutingInputSource(SemanticIrModel):
    path: Path
    sha256: str
    pointer: str = ""

    @model_validator(mode="after")
    def valid(self) -> Self:
        require_sha256(self.sha256, "routing source SHA-256")
        if self.pointer and not self.pointer.startswith("/"):
            raise ValueError("JSON pointer must be empty or start with /")
        return self

    def read(self) -> Any:
        data = self.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError(f"routing source changed: {self.path}")
        result = json.loads(data)
        for token in self.pointer.split("/")[1:]:
            key = token.replace("~1", "/").replace("~0", "~")
            result = result[int(key)] if isinstance(result, list) else result[key]
        return result


class RoutingPreparationRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-routing-preparation-v1"] = "pcbsmith-routing-preparation-v1"
    transaction_root: Path
    expected_transaction_fingerprint: str
    layout: RoutingInputSource
    netlist: RoutingInputSource
    profile: RoutingInputSource
    examination: RoutingInputSource
    context: RoutingInputSource
    feasibility: RoutingInputSource
    concept_drift: RoutingInputSource
    engineering_gate: RoutingInputSource
    budget_bindings: RoutingInputSource
    pre_route_integrity: RoutingInputSource
    defer_routed_checks: bool = False
    routed_engineering_source: RoutingInputSource | None = None

    @model_validator(mode="after")
    def valid(self) -> Self:
        require_sha256(self.expected_transaction_fingerprint, "expected transaction fingerprint")
        for source in (self.layout, self.netlist, self.profile, self.routed_engineering_source):
            if source is not None and source.pointer:
                raise ValueError("layout, netlist, profile and routed source require whole files")
        return self


def prepare_routing_inputs(request: RoutingPreparationRequest, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("routing preparation output must be new")
    current = resolve_current_generation(request.transaction_root)
    if current.transaction_fingerprint != request.expected_transaction_fingerprint:
        raise ValueError("current generation differs from expected transaction")
    root = request.transaction_root.resolve() / "generations" / current.generation_id
    boards = [a for a in current.artifacts if a.role == "board"]
    if len(boards) != 1:
        raise ValueError("exactly one retained board required")
    board = root / boards[0].relative_path
    sources = {
        key: getattr(request, key)
        for key in type(request).model_fields
        if isinstance(getattr(request, key), RoutingInputSource)
    }
    values = {key: source.read() for key, source in sources.items()}
    # Canonical snapshots are parsed from their actual bytes, never reformatted
    # from caller dictionaries to conceal a stale or malformed snapshot.
    layout_text = request.layout.path.read_text(encoding="utf-8")
    netlist_text = request.netlist.path.read_text(encoding="utf-8")
    layout = parse_canonical_board_layout_snapshot(layout_text)
    netlist = parse_canonical_board_netlist_snapshot(netlist_text)
    profile = PcbRuleProfile.model_validate(values["profile"])
    with project_footprint_scope(board.parent):
        require_saved_layout_matches(board.read_text(encoding="utf-8"), layout, netlist, profile)
    fields = {
        key: value
        for key, value in values.items()
        if key not in {"layout", "netlist", "profile", "routed_engineering_source"}
    }
    fields.update(
        generation_root=str(root),
        generation_sha256=current.generation_sha256,
        saved_board_sha256=boards[0].content_sha256,
        saved_layout_fingerprint=board_layout_snapshot_fingerprint(layout_text),
        placement_review=json.loads((root / "review/manifest.json").read_bytes()),
        committed_review_transaction=current,
        component_review_execution=json.loads(
            (root / "evidence/component-review/execution.json").read_bytes()
        ),
        defer_routed_checks=request.defer_routed_checks,
        routed_engineering_source=None
        if request.routed_engineering_source is None
        else str(request.routed_engineering_source.path.resolve()),
        routed_engineering_source_sha256=None
        if request.routed_engineering_source is None
        else request.routed_engineering_source.sha256,
    )
    gate = RoutingGateInputs.model_validate(fields)
    if (
        gate.engineering_gate.context.board_netlist_snapshot_fingerprint
        != board_netlist_snapshot_fingerprint(netlist_text)
    ):
        raise ValueError("engineering gate targets another netlist snapshot")
    entry = gate.evaluate()
    # Revalidate the exact original inputs after the potentially expensive replay.
    for source in sources.values():
        source.read()
    if resolve_current_generation(request.transaction_root) != current:
        raise ValueError("current generation changed during routing preparation")
    report = dict(
        schema_id="pcbsmith-routing-preparation-result-v1",
        status="ready_inputs" if entry.allowed else "blocked_inputs",
        routing_accepted=False,
        request=request.model_dump(mode="json"),
        entry=entry.model_dump(mode="json"),
        next_action="Use the same live board-job routing operation"
        if entry.allowed
        else "Resolve named gate blockers; no routing attempt is warranted",
    )
    output.mkdir(parents=True)
    (output / "gate-inputs.json").write_text(
        gate.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (output / "preparation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    request = RoutingPreparationRequest.model_validate_json(args.request.read_bytes())
    report = prepare_routing_inputs(request, args.output)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ready_inputs" else 2


if __name__ == "__main__":
    raise SystemExit(main())
