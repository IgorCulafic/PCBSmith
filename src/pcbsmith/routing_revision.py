"""Source-replayed unchanged-copper provenance for qualified part substitutions.

The predecessor routing execution stays bound to its original board. A distinct
revision proof connects the checked edit to it; changed engineering/readiness and
final native/visual checks remain obligations of the publication owner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import TypeAdapter, model_validator

from pcbsmith.component_review_execution import ProjectComponentReviewExecution
from pcbsmith.kicad.check_reports import drc_sections, erc_violations, validate_native_header
from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.routing_candidate_transaction import (
    AcceptedRoutingExecution,
    RoutingCandidateTransactionResult,
)
from pcbsmith.operations.file_transaction import project_path
from pcbsmith.project_engineering_gate_ir import ProjectEngineeringGateResult
from pcbsmith.review.visual_package import _copper_hash
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.routing_ir import RoutingEngineIdentity
from pcbsmith.rule_profiles import PcbRuleProfile
from pcbsmith.semantic_ir import SemanticIrModel


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnchangedCopperRevision(SemanticIrModel):
    schema_id: Literal["pcbsmith-unchanged-copper-revision-v1"] = (
        "pcbsmith-unchanged-copper-revision-v1"
    )
    board_sha256: str
    copper_sha256: str
    predecessor: AcceptedRoutingExecution
    routing_result: Path
    routing_result_sha256: str
    revision_directory: Path
    revision_sha256: str
    candidate_inputs: dict[str, str]
    check_files: dict[str, str]
    receipt_fingerprint: str

    @property
    def engine(self) -> RoutingEngineIdentity:
        return self.predecessor.engine

    @model_validator(mode="after")
    def exact(self) -> Self:
        for name in (
            "board_sha256",
            "copper_sha256",
            "routing_result_sha256",
            "revision_sha256",
            "receipt_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        if self.board_sha256 == self.predecessor.board_sha256:
            raise ValueError("revision must identify changed board bytes")
        if (
            fingerprint(self.model_dump(mode="json", exclude={"receipt_fingerprint"}))
            != self.receipt_fingerprint
        ):
            raise ValueError("unchanged-copper revision fingerprint is stale")
        return self


def derive_unchanged_copper_revision(
    *,
    routing_result: Path,
    routing_result_sha256: str,
    revision_directory: Path,
    revision_sha256: str,
) -> UnchangedCopperRevision:
    from pcbsmith.board_revision import replay_board_revision

    routing_result, revision_directory = routing_result.resolve(), revision_directory.resolve()
    if (
        _sha(routing_result) != routing_result_sha256
        or _sha(revision_directory / "revision.json") != revision_sha256
    ):
        raise ValueError("routing/revision source hash differs from requested predecessor")
    transaction = RoutingCandidateTransactionResult.model_validate_json(routing_result.read_bytes())
    predecessor = AcceptedRoutingExecution.from_transaction(transaction)
    generation = transaction.generation_transaction
    assert generation is not None
    directory = Path(generation.retained_directory)
    for artifact in generation.manifest.artifacts:
        if _sha(project_path(directory, artifact.relative_path)) != artifact.content_sha256:
            raise ValueError("retained routing generation artifact is stale")
    candidate, request, revision = replay_board_revision(revision_directory)
    if not request.substitutions or request.edits or request.validation_stage != "routed":
        raise ValueError("unchanged-copper publication currently requires a qualified substitution")
    before = revision_directory / "before" / candidate.name
    if _sha(before) != predecessor.board_sha256:
        raise ValueError("substitution predecessor is not the accepted routed board")
    copper = _copper_hash(parse_sexpr(before.read_text(encoding="utf-8")))
    if _copper_hash(parse_sexpr(candidate.read_text(encoding="utf-8"))) != copper:
        raise ValueError("substitution changed copper geometry or pad/net meaning")
    checks = revision_directory / "checks"
    summary = json.loads((checks / "summary.json").read_bytes())
    if summary.get("validation_stage") != "routed" or summary.get("passed") is not True:
        raise ValueError("substitution native checks are not a routed pass")
    if not summary.get("native_inputs") or any(
        revision["candidate_inputs"].get(name) != digest
        for name, digest in summary["native_inputs"].items()
    ):
        raise ValueError("substitution native check inputs differ from the exact candidate")
    erc = validate_native_header(
        json.loads((checks / "erc.json").read_bytes()), "ERC", candidate.with_suffix(".kicad_sch")
    )
    drc = validate_native_header(json.loads((checks / "drc.json").read_bytes()), "DRC", candidate)
    if erc_violations(erc) or any(drc_sections(drc).values()):
        raise ValueError("substitution contains native ERC/DRC/connectivity/parity findings")
    if (
        _sha(routing_result) != routing_result_sha256
        or _sha(revision_directory / "revision.json") != revision_sha256
    ):
        raise ValueError("routing/revision sources changed during replay")
    fields: dict[str, Any] = dict(
        board_sha256=_sha(candidate),
        copper_sha256=copper,
        predecessor=predecessor,
        routing_result=routing_result,
        routing_result_sha256=routing_result_sha256,
        revision_directory=revision_directory,
        revision_sha256=revision_sha256,
        candidate_inputs=revision["candidate_inputs"],
        check_files=revision["check_files"],
    )
    provisional = UnchangedCopperRevision.model_construct(**fields, receipt_fingerprint="0" * 64)
    return UnchangedCopperRevision(
        **fields,
        receipt_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"receipt_fingerprint"})
        ),
    )


def require_unchanged_copper_revision(proof: UnchangedCopperRevision, board_payload: bytes) -> None:
    if hashlib.sha256(board_payload).hexdigest() != proof.board_sha256:
        raise ValueError("publication board differs from the checked substitution")
    replay = derive_unchanged_copper_revision(
        routing_result=proof.routing_result,
        routing_result_sha256=proof.routing_result_sha256,
        revision_directory=proof.revision_directory,
        revision_sha256=proof.revision_sha256,
    )
    if replay != proof:
        raise ValueError("unchanged-copper revision does not replay")


class RevisionPublicationAuthority(SemanticIrModel):
    schema_id: Literal["pcbsmith-revision-publication-authority-v1"] = (
        "pcbsmith-revision-publication-authority-v1"
    )
    board_sha256: str
    layout_snapshot_json: str
    profile: PcbRuleProfile
    engineering_gate: ProjectEngineeringGateResult
    component_review: ProjectComponentReviewExecution


def require_revision_publication_authority(
    authority: RevisionPublicationAuthority | None,
    proof: UnchangedCopperRevision,
    board_payload: bytes,
    project_id: str,
    readiness_request: Any,
) -> None:
    from pcbsmith.kicad.board_serialization import (
        board_layout_snapshot_fingerprint,
        parse_canonical_board_layout_snapshot,
        parse_canonical_board_netlist_snapshot,
    )
    from pcbsmith.kicad.project_dependencies import project_footprint_scope
    from pcbsmith.kicad.routing_candidate_transaction import require_saved_layout_matches

    if authority is None or readiness_request is None:
        raise ValueError(
            "revised publication requires fresh engineering, component and readiness inputs"
        )
    context = authority.engineering_gate.context
    component = authority.component_review
    if (
        hashlib.sha256(board_payload).hexdigest() != proof.board_sha256
        or authority.board_sha256 != proof.board_sha256
        or context.project_id != project_id
        or component.project_id != project_id
        or context.inventory_status != "complete_reviewed"
        or authority.engineering_gate.outcome != "ready"
        or not component.ready_for_routing
        or context.board_netlist_snapshot_fingerprint
        != component.board_netlist_snapshot_fingerprint
        or context.board_layout_snapshot_fingerprint
        != board_layout_snapshot_fingerprint(authority.layout_snapshot_json)
    ):
        raise ValueError("revised engineering/component authorities are incomplete or stale")
    netlist = parse_canonical_board_netlist_snapshot(component.board_netlist_snapshot_json)
    layout = parse_canonical_board_layout_snapshot(authority.layout_snapshot_json)
    with project_footprint_scope(proof.revision_directory / "design"):
        require_saved_layout_matches(
            board_payload.decode("utf-8"), layout, netlist, authority.profile
        )
    if set(component.required_component_references) != {
        c.reference for c in netlist.components if c.reference.upper().startswith("U")
    }:
        raise ValueError("fresh component review must cover the exact revised IC obligation set")
    from pcbsmith.manufacturing_lineage import assembly_rows_from_text

    populated = {
        row.reference
        for row in assembly_rows_from_text(board_payload.decode("utf-8"))
        if row.in_bom
    }
    if set(readiness_request.reference_intents) != populated:
        raise ValueError("revised readiness must cover the exact populated component set")
    reviews = {
        r.intent.intent_id: r for r in readiness_request.predesign.readiness.component_reviews
    }
    for part in netlist.components:
        if part.reference not in populated:
            continue
        review = reviews.get(readiness_request.reference_intents.get(part.reference))
        selected = (
            None
            if review is None
            else next(
                (c for c in review.candidates if c.candidate_id == review.selected_candidate_id),
                None,
            )
        )
        if selected is None or selected.manufacturer_part_number != dict(part.fields).get("MPN"):
            raise ValueError("readiness selected parts differ from the checked revised netlist")
    spec = readiness_request.predesign.evidence_files.get("design-spec")
    if spec is None or spec.sha256 != proof.candidate_inputs.get("design-spec.json"):
        raise ValueError("revised readiness must bind the exact updated native specification")


def parse_routing_publication_proof(
    payload: str | bytes,
) -> AcceptedRoutingExecution | UnchangedCopperRevision:
    return TypeAdapter(AcceptedRoutingExecution | UnchangedCopperRevision).validate_json(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("routing-result", "revision-directory", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("routing-result-sha256", "revision-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("revision proof output must be new")
    proof = derive_unchanged_copper_revision(
        routing_result=args.routing_result,
        routing_result_sha256=args.routing_result_sha256,
        revision_directory=args.revision_directory,
        revision_sha256=args.revision_sha256,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(proof.model_dump_json(indent=2) + "\n")
    print(
        "Unchanged copper provenance retained; "
        "refreshed readiness and final checks remain required."
    )


if __name__ == "__main__":
    main()
