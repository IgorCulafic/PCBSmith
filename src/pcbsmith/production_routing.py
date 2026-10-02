"""Ordinary saved-placement routing through the existing H0 candidate transaction.

This owner replays the full entry gate, preserves native inputs, and runs actual
KiCad checks. Missing post-route engineering remains blocked; a generated candidate
is never promoted by substituting caller-supplied positive validation records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pcbsmith.applicability_execution import (
    ApplicableCheckRequirement,
    CheckExecutionRecord,
    ProjectApplicabilityExecutionManifest,
    ProjectCheckApplicability,
    ProjectCheckDisposition,
)
from pcbsmith.component_review_execution import ProjectComponentReviewExecution
from pcbsmith.decoupling_loop_ir import DecouplingLoopEvaluationResult
from pcbsmith.execution import EXECUTION_PROFILES
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.final_fill_adapter import refill_and_read_kicad_board
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.placement_readback import (
    KiCadBoardReadbackSnapshot,
    extract_kicad_board_readback,
)
from pcbsmith.kicad.project_dependencies import native_project_hashes
from pcbsmith.kicad.routing_candidate_adapter import (
    NativePlanePour,
    native_source_route_objects,
    route_native_candidate,
    stable_route_terminal_object_id,
)
from pcbsmith.kicad.routing_candidate_transaction import (
    RoutingCandidateInputSnapshot,
    RoutingCandidateTransactionResult,
    RoutingCandidateValidationBundle,
    apply_declared_route_deltas,
    freeze_native_routing_inputs,
    immutable_readback_matches,
    require_saved_layout_matches,
    run_routing_candidate_transaction,
)
from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report, inspect_saved_board_routing
from pcbsmith.pre_route_integrity import PreRouteIntegrityEvidence
from pcbsmith.production_decoupling import (
    execute_native_loops,
    read_engineering_source,
    read_envelope_revision,
)
from pcbsmith.production_generators import generate_nonmutating_kicad_drc
from pcbsmith.production_workflow import (
    AlgorithmBudgetBinding,
    ArtifactRole,
    GenerationTransactionManifest,
    RoutedBoardVerificationEvidence,
    RoutedVerificationKind,
    RoutedVerificationRecord,
    RoutingEntryGateReport,
    bind_execution_profile,
    evaluate_routing_entry_gate,
)
from pcbsmith.project_engineering_gate import evaluate_project_engineering_gate
from pcbsmith.project_engineering_gate_ir import (
    Phase14EvaluationBundle,
    ProjectEngineeringContext,
    ProjectEngineeringGateResult,
)
from pcbsmith.prompt_examiner import PromptExamination
from pcbsmith.review.visual_package import VisualReviewManifest
from pcbsmith.routing_ir import (
    DeterministicRoutingConfiguration,
    ProtectedRouteObjectPolicy,
    RouteCandidateResult,
    RouteClearanceConstraint,
    RouteRequest,
    RouteTopologyConstraint,
    RouteViaTechnology,
    RouteWidthConstraint,
    RoutingBudget,
    TargetRouteDomain,
    TargetRouteNet,
)
from pcbsmith.rule_profiles import PcbRuleProfile
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.workflow_authority import ProjectContextBundle
from pcbsmith.workflow_feasibility import ConceptDriftReport, PreRouteFeasibilityReport


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json", by_alias=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class RoutingGateInputs(SemanticIrModel):
    generation_root: str
    generation_sha256: str
    saved_board_sha256: str
    saved_layout_fingerprint: str
    examination: PromptExamination
    context: ProjectContextBundle
    feasibility: PreRouteFeasibilityReport
    concept_drift: ConceptDriftReport
    placement_review: VisualReviewManifest
    committed_review_transaction: GenerationTransactionManifest
    engineering_gate: ProjectEngineeringGateResult
    component_review_execution: ProjectComponentReviewExecution
    budget_bindings: tuple[AlgorithmBudgetBinding, ...]
    pre_route_integrity: PreRouteIntegrityEvidence
    defer_routed_checks: bool = False
    routed_engineering_source: str | None = None
    routed_engineering_source_sha256: str | None = None

    def evaluate(self) -> RoutingEntryGateReport:
        values = {
            key: getattr(self, key)
            for key in type(self).model_fields
            if key not in {"routed_engineering_source", "routed_engineering_source_sha256"}
        }
        values["generation_root"] = Path(self.generation_root)
        return evaluate_routing_entry_gate(**values)


def _pin_nets(board: Path) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    for footprint in _children(tree, "footprint"):
        props = {_atom(n[1]): _atom(n[2]) for n in _children(footprint, "property")}
        for pad in _children(footprint, "pad"):
            names = _children(pad, "net")
            if not names or len(names[0]) < 2:
                continue
            name = _atom(names[0][-1])
            if not name:
                continue
            key = (props["Reference"], _atom(pad[1]))
            if key in result and result[key] != name:
                raise ValueError("stacked native pads disagree on their net")
            result[key] = name
    return result


def native_save_readback_matches(
    before: KiCadBoardReadbackSnapshot, after: KiCadBoardReadbackSnapshot
) -> bool:
    """Accept only native-added IDs and explicit zero angles after a native save.

    All geometry/electrics and every pre-existing UUID with its owning object
    must match. Newly assigned IDs may fill previously anonymous native items.
    Native rotated annotation coordinates use 10nm quantization; copper and
    component/pad coordinates remain exact.
    """

    def normalized(node: Any, *, annotation: bool = False) -> Any:
        if not isinstance(node, list):
            return node
        result = [
            normalized(
                n,
                annotation=bool(
                    node
                    and node[0] in ({"atom": "property"}, {"atom": "fp_text"}, {"atom": "gr_text"})
                ),
            )
            for n in node
            if not (isinstance(n, list) and n and n[0] == {"atom": "uuid"})
        ]
        if annotation and len(result) >= 3 and result[0] == {"atom": "at"}:
            from decimal import Decimal

            for index in (1, 2):
                result[index] = {
                    "atom": format(
                        Decimal(result[index]["atom"]).quantize(Decimal("0.00001")).normalize(), "f"
                    )
                }
        if len(result) == 4 and result[0] == {"atom": "at"}:
            from decimal import Decimal

            angle = (Decimal(result[-1]["atom"]) % 360 + 360) % 360
            if angle == 0:
                result.pop()
            else:
                result[-1] = {"atom": format(angle.normalize(), "f")}
        return result

    def inspect(
        snapshot: KiCadBoardReadbackSnapshot,
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        semantics: dict[str, list[str]] = {}
        identities: dict[str, str] = {}

        def visit(node: Any) -> None:
            if not isinstance(node, list):
                return
            ids = [
                n[1]["quoted"]
                for n in node
                if isinstance(n, list) and len(n) == 2 and n[0] == {"atom": "uuid"}
            ]
            for identity in ids:
                if identity in identities:
                    raise ValueError("duplicate native object identity")
                identities[identity] = json.dumps(normalized(node), sort_keys=True)
            for child in node:
                visit(child)

        for key, rows in snapshot.model_dump().items():
            if key in {"schema_id", "schema_version"}:
                continue
            values = [json.loads(row) for row in rows]
            semantics[key] = sorted(json.dumps(normalized(v), sort_keys=True) for v in values)
            for value in values:
                visit(value)
        return semantics, identities

    old_semantics, old_ids = inspect(before)
    new_semantics, new_ids = inspect(after)
    return old_semantics == new_semantics and all(new_ids.get(k) == v for k, v in old_ids.items())


def _request(
    snapshot: RoutingCandidateInputSnapshot,
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
    entry: RoutingEntryGateReport,
    net_order: Sequence[str] = (),
    net_widths: Mapping[str, float] | None = None,
    plane_pour: NativePlanePour | None = None,
) -> RouteRequest:
    names = tuple(n.name for n in netlist.nets if len(n.nodes) > 1)
    order = tuple(net_order) if net_order else tuple(sorted(names))
    if len(order) != len(set(order)) or set(order) != set(names):
        raise ValueError("route order must cover every routable net exactly once")
    widths = dict(net_widths or {})
    if not set(widths).issubset(names):
        raise ValueError("width override targets an absent routable net")
    nets = {n.name: n for n in netlist.nets}
    terminals = {
        name: tuple(
            stable_route_terminal_object_id(net_name=name, reference=r, pin=p)
            for r, p in nets[name].nodes
        )
        for name in names
    }
    from pcbsmith.kicad.astar_router import routing_copper_layers

    layers = routing_copper_layers(profile)
    geometry = profile.geometry
    budget = next(
        b
        for b in bind_execution_profile(EXECUTION_PROFILES[entry.budget_profile_name])
        if b.algorithm.value == "routing"
    )
    return RouteRequest(
        request_id="ordinary-saved-placement:" + snapshot.identity.board_sha256[:16],
        inputs=snapshot.identity,
        target_domains=(
            TargetRouteDomain(
                domain_id="ordinary",
                priority=0,
                nets=tuple(
                    TargetRouteNet(net_name=n, terminal_object_ids=terminals[n]) for n in names
                ),
            ),
        ),
        source_route_objects=native_source_route_objects(
            layout, source_board_sha256=entry.saved_board_sha256
        ),
        protected_policy=ProtectedRouteObjectPolicy(),
        allowed_layers=layers,
        additional_constraint_ids=() if plane_pour is None else (plane_pour.constraint_id,),
        width_constraints=tuple(
            RouteWidthConstraint(
                constraint_id="width:" + n,
                net_names=(n,),
                minimum_width_mm=geometry.minimum_trace_width_mm,
                preferred_width_mm=widths.get(n, geometry.default_signal_trace_width_mm),
                maximum_width_mm=widths.get(n, geometry.default_signal_trace_width_mm),
            )
            for n in names
        ),
        clearance_constraints=tuple(
            RouteClearanceConstraint(
                constraint_id="clearance:" + n,
                net_names=(n,),
                other_net_names=tuple(x.name for x in netlist.nets if x.name != n),
                minimum_clearance_mm=profile.fab_spacing.minimum_copper_clearance_mm,
            )
            for n in names
        ),
        via_technologies=(
            RouteViaTechnology(
                constraint_id="via:through",
                technology_id="manual-through",
                start_layer="F.Cu",
                end_layer="B.Cu",
                diameter_mm=geometry.routing_via_diameter_mm,
                drill_mm=geometry.routing_via_drill_mm,
            ),
        )
        if len(layers) == 2
        else (),
        topology_constraints=tuple(
            RouteTopologyConstraint(
                constraint_id="topology:" + n,
                domain_id="ordinary",
                net_name=n,
                topology_kind="any_tree",
                ordered_terminal_object_ids=terminals[n],
            )
            for n in names
        ),
        budget=RoutingBudget(
            max_passes=budget.maximum_passes,
            max_expansions=budget.maximum_expansions,
            max_expansions_per_net=budget.maximum_expansions,
            max_stagnant_passes=2,
            max_exact_check_rejections=0,
        ),
        deterministic=DeterministicRoutingConfiguration(
            seed=0, route_order=order, tie_break_policy="pcbsmith-native-lexical-v1"
        ),
    )


def _retained_routing_parameters(
    result_file: Path, expected_sha256: str | None
) -> tuple[dict[str, bytes], RoutingBudget]:
    """Recover original policy/settings for verification without executing an engine."""
    raw = result_file.read_bytes()
    if _sha(raw) != expected_sha256:
        raise ValueError("retained routing result changed")
    prior = RoutingCandidateTransactionResult.model_validate_json(raw)
    root = Path(prior.retained_directory)
    request = RouteRequest.model_validate_json((root / "request.json").read_bytes())
    snapshot = RoutingCandidateInputSnapshot.model_validate_json(
        (root / "input-snapshot.json").read_bytes()
    )
    if (
        request.semantic_fingerprint() != prior.request_fingerprint
        or snapshot.snapshot_fingerprint != prior.input_snapshot_fingerprint
    ):
        raise ValueError("retained routing parameters changed")
    metadata = {}
    for item in snapshot.artifacts:
        if item.relative_path in {
            "evidence/freerouting-config.json",
            "evidence/routing-policy.json",
        }:
            data = (root / "inputs" / item.relative_path).read_bytes()
            if _sha(data) != item.content_sha256:
                raise ValueError("retained routing settings changed")
            metadata[item.relative_path] = data
    return metadata, request.budget


def _dispatch_routing_candidate(
    req: RouteRequest,
    work: Path,
    *,
    board: Path,
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
    external: Any,
    plane_pour: NativePlanePour | None = None,
    legacy_native_reason: str | None = None,
) -> RouteCandidateResult:
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    if external is not None:
        from pcbsmith.kicad.freerouting_production import route_freerouting_production

        print("Freerouting 2.3.0: bounded external process and native checks", flush=True)
        candidate = route_freerouting_production(
            board=board,
            layout=layout,
            request=req,
            profile=profile,
            config=external,
            work=work / "freerouting",
        )
        # The transaction owns the canonical engine evidence paths. Keep the
        # adapter's isolated interchange directory and retain its exact logs.
        (work / "engine").mkdir(parents=True, exist_ok=True)
        for stream in ("stdout", "stderr"):
            raw = (work / "freerouting" / "engine" / f"{stream}.log").read_bytes()
            (work / "engine" / f"{stream}.log").write_bytes(raw)
        return candidate
    if not legacy_native_reason:
        raise ValueError(
            "Native routing requires explicit --legacy-native-reason; no automatic fallback"
        )
    print("H0 native routing started; bounded passes and expansions are retained.", flush=True)
    candidate = route_native_candidate(
        request=req,
        layout=layout,
        netlist=netlist,
        profile=profile,
        native_serialization=True,
        plane_pour=plane_pour,
    )
    print("H0 route search: " + candidate.partial_status.value, flush=True)
    return candidate


def route_saved_placement_candidate(
    *,
    board: Path,
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
    gate_inputs: RoutingGateInputs,
    output: Path,
    freerouting_config: Path | None = None,
    legacy_native_reason: str | None = None,
    manual_routing_authorization: str | None = None,
    net_order: Sequence[str] = (),
    net_widths: Mapping[str, float] | None = None,
    plane_pour: NativePlanePour | None = None,
    revalidate_result: Path | None = None,
    revalidate_sha256: str | None = None,
    repair_plane_clearance_mm: float | None = None,
    native_repair_file: Path | None = None,
    engineering_revision: Path | None = None,
    engineering_revision_sha256: str | None = None,
) -> RoutingCandidateTransactionResult:
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    from pcbsmith.kicad.project_dependencies import project_footprint_scope

    # Keep every layout/candidate readback bound to the retained project assets.
    with project_footprint_scope(board.parent):
        if output.exists():
            raise ValueError("routing candidate output must be fresh")
        from pcbsmith.kicad.freerouting_production import FreeroutingProductionConfig
        from pcbsmith.routing_policy import (
            require_manual_routing_authorization,
            resolve_freerouting_config,
        )

        if legacy_native_reason is not None and (
            not legacy_native_reason.strip() or freerouting_config is not None
        ):
            raise ValueError(
                "Legacy native routing requires an explicit reason and no Freerouting config"
            )
        if native_repair_file is not None:
            require_manual_routing_authorization(manual_routing_authorization)
            if revalidate_result is None:
                raise ValueError(
                    "Manual retained repair requires an existing routing result; "
                    "no automatic fallback"
                )
        external = None
        external_payload = None
        if revalidate_result is None and legacy_native_reason is None:
            external_path = resolve_freerouting_config(board, freerouting_config)
            external_payload = external_path.read_bytes()
            external = FreeroutingProductionConfig.model_validate_json(external_payload)
            external.preflight()
            if plane_pour is not None:
                raise ValueError(
                    "Freerouting requires routing nets first; "
                    "native plane constraints do not select a fallback engine"
                )
        elif revalidate_result is not None and freerouting_config is not None:
            raise ValueError("Retained-candidate revalidation does not launch Freerouting")
        entry = gate_inputs.evaluate()
        if not entry.allowed:
            raise ValueError("routing entry blocked: " + "; ".join(entry.blockers))
        if _sha(board.read_bytes()) != entry.saved_board_sha256:
            raise ValueError("routing entry targets another saved board")
        if (
            board_layout_snapshot_fingerprint(canonical_board_layout_snapshot_json(layout))
            != entry.saved_layout_fingerprint
        ):
            raise ValueError("routing entry targets another layout")
        if (
            canonical_board_netlist_snapshot_json(netlist)
            != gate_inputs.engineering_gate.context.board_netlist_snapshot_json
        ):
            raise ValueError("routing entry targets another netlist")
        from pcbsmith.kicad.retained_native_repair import RetainedNativeRepair

        native_repair = (
            RetainedNativeRepair.model_validate_json(native_repair_file.read_bytes())
            if native_repair_file
            else None
        )
        source_raw = (
            native_repair.apply(board.read_bytes(), source_only=True)[0]
            if native_repair
            else board.read_bytes()
        )
        source = extract_kicad_board_readback(source_raw.decode("utf-8"))
        if (
            source.segments
            or source.vias
            or source.zones
            or layout.segments
            or layout.vias
            or layout.zones
        ):
            raise ValueError(
                "initial routing accepts only an unrouted placement; "
                "use iterative repair for existing copper"
            )
        require_saved_layout_matches(board.read_text(encoding="utf-8"), layout, netlist, profile)
        engineering_source = None
        engineering_payload = None
        if entry.deferred_routed_features:
            if (
                not gate_inputs.routed_engineering_source
                or not gate_inputs.routed_engineering_source_sha256
            ):
                raise ValueError(
                    "deferred routed checks require pinned engineering requirements before routing"
                )
            source_file = Path(gate_inputs.routed_engineering_source)
            engineering_source = read_engineering_source(
                source_file,
                gate_inputs.routed_engineering_source_sha256,
                gate_inputs.context.project_id,
                entry.deferred_routed_features,
            )
            engineering_payload = source_file.read_bytes()
            if _sha(engineering_payload) != gate_inputs.routed_engineering_source_sha256:
                raise ValueError("engineering source changed during preflight")
        closure = native_project_hashes(board)
        payloads = {"design/" + name: (board.parent / name).read_bytes() for name in closure}
        payloads["evidence/routing-entry.json"] = (entry.model_dump_json(indent=2) + "\n").encode()
        payloads["evidence/routing-entry-inputs.json"] = (
            gate_inputs.model_dump_json(indent=2) + "\n"
        ).encode()
        if engineering_payload is not None:
            payloads["evidence/routed-engineering-source.json"] = engineering_payload
        if plane_pour is not None:
            payloads["evidence/plane-pour.json"] = plane_pour.model_dump_json(indent=2).encode()
        retained_budget = None
        if revalidate_result is not None:
            metadata, retained_budget = _retained_routing_parameters(
                revalidate_result, revalidate_sha256
            )
            payloads.update(metadata)
        else:
            if external_payload is not None:
                payloads["evidence/freerouting-config.json"] = external_payload
            payloads["evidence/routing-policy.json"] = json.dumps(
                {
                    "backend": external.backend if external else "legacy-native",
                    "legacy_native_reason": legacy_native_reason,
                    "automatic_fallback": False,
                },
                sort_keys=True,
            ).encode()
        roles: dict[str, ArtifactRole] = {
            name: "board"
            if name == "design/" + board.name
            else "schematic"
            if name.endswith(".kicad_sch")
            else "evidence"
            for name in payloads
        }
        snapshot = freeze_native_routing_inputs(
            payloads=payloads,
            roles=roles,
            board_relative_path="design/" + board.name,
            schematic_relative_paths=tuple(n for n in payloads if n.endswith(".kicad_sch")),
            layout=layout,
            netlist=netlist,
            profile=profile,
        )
        request = _request(
            snapshot, layout, netlist, profile, entry, net_order, net_widths, plane_pour
        )
        if external is not None:
            request = RouteRequest.model_validate(
                {
                    **request.model_dump(),
                    "budget": {
                        "max_passes": external.max_passes,
                        "max_expansions": 0,
                        "max_expansions_per_net": 0,
                        "max_stagnant_passes": 0,
                        "max_exact_check_rejections": 0,
                        "external_process_seconds": external.process_seconds,
                    },
                }
            )
        if retained_budget is not None:
            request = request.model_copy(update={"budget": retained_budget})
        if native_repair is not None and engineering_source is not None:
            raise ValueError(
                "local retained repair needs refreshed placement-dependent engineering closure"
            )
        validation_source_sha256 = gate_inputs.routed_engineering_source_sha256
        revision = None
        revision_payload = None
        if engineering_revision is not None:
            if (
                revalidate_result is None
                or revalidate_sha256 is None
                or engineering_revision_sha256 is None
                or engineering_source is None
                or validation_source_sha256 is None
            ):
                raise ValueError(
                    "engineering revision requires exact retained-candidate revalidation"
                )
            revision = read_envelope_revision(
                engineering_revision,
                engineering_revision_sha256,
                original=engineering_source,
                original_sha256=validation_source_sha256,
                retained_result_sha256=revalidate_sha256,
            )
            revision_payload = engineering_revision.read_bytes()
            if _sha(revision_payload) != engineering_revision_sha256:
                raise ValueError("engineering revision changed during preflight")
            engineering_source = revision.source
            validation_source_sha256 = _sha(engineering_source.model_dump_json(indent=2).encode())
        elif engineering_revision_sha256 is not None:
            raise ValueError("engineering revision hash requires its source file")

        def engine(req: RouteRequest, work: Path) -> RouteCandidateResult:
            return _dispatch_routing_candidate(
                req,
                work,
                board=board,
                layout=layout,
                netlist=netlist,
                profile=profile,
                external=external,
                plane_pour=plane_pour,
                legacy_native_reason=legacy_native_reason,
            )

        def validator(
            candidate_board: Path,
            req: RouteRequest,
            readback: KiCadBoardReadbackSnapshot,
            work: Path,
        ) -> RoutingCandidateValidationBundle:
            for relative, data in payloads.items():
                if not relative.startswith("design/") or relative == "design/" + board.name:
                    continue
                target = candidate_board.parent / relative[len("design/") :]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            checks = work / "verification"
            checks.mkdir(exist_ok=True)
            drc_path = checks / "drc.json"
            generate_nonmutating_kicad_drc(candidate_board, drc_path)
            drc = inspect_kicad_drc_report(drc_path)
            saved = inspect_saved_board_routing(candidate_board)
            native, fill = refill_and_read_kicad_board(
                candidate_board, work / "native-save-readback"
            )
            _write(checks / "native-fill.json", fill)
            reloaded = extract_kicad_board_readback(native.read_text(encoding="utf-8"))
            expected = {(r, p): n.name for n in netlist.nets for r, p in n.nodes}
            actual = _pin_nets(candidate_board)
            pins_equal = actual == expected
            _write(
                checks / "pin-net-equivalence.json",
                {
                    "accepted": pins_equal,
                    "expected": sorted((r, p, n) for (r, p), n in expected.items()),
                    "actual": sorted((r, p, n) for (r, p), n in actual.items()),
                },
            )
            sha = _sha(candidate_board.read_bytes())
            records = []
            for kind, ok, report in [
                (RoutedVerificationKind.EXACT_ROUTE, drc.clean, drc_path),
                (
                    RoutedVerificationKind.KICAD_READBACK,
                    native_save_readback_matches(readback, reloaded),
                    checks / "native-fill.json",
                ),
                (
                    RoutedVerificationKind.NETLIST_EQUIVALENCE,
                    pins_equal,
                    checks / "pin-net-equivalence.json",
                ),
            ]:
                records.append(
                    RoutedVerificationRecord.build(
                        kind=kind,
                        board_sha256=sha,
                        producer_id="pcbsmith.production_routing",
                        tool_version="1",
                        input_sha256s=tuple(sorted({sha, _sha(report.read_bytes())})),
                        accepted=ok,
                        result_code="accepted" if ok else "rejected",
                        limitations=("Physical circuit operation is not verified by CAD checks.",),
                    )
                )
            verification = RoutedBoardVerificationEvidence.build(
                board_sha256=sha, records=tuple(records)
            )
            loop_results: tuple[DecouplingLoopEvaluationResult, ...] = ()
            if engineering_source is not None:
                assert validation_source_sha256 is not None
                if revision is not None:
                    if sha != revision.candidate_board_sha256:
                        raise ValueError(
                            "engineering revision belongs to different candidate bytes"
                        )
                    assert revision_payload is not None
                    (checks / "engineering-revision.json").write_bytes(revision_payload)
                    (checks / "routed-engineering-source.json").write_bytes(
                        engineering_source.model_dump_json(indent=2).encode()
                    )
                candidate = RouteCandidateResult.model_validate_json(
                    (work / "candidate-result.json").read_bytes()
                )
                routed_layout = apply_declared_route_deltas(
                    request=req, candidate=candidate, source_layout=layout
                )
                loop_results = execute_native_loops(
                    board=candidate_board,
                    layout=routed_layout,
                    netlist=netlist,
                    profile=profile,
                    source=engineering_source,
                    source_sha256=validation_source_sha256,
                )
                original = gate_inputs.engineering_gate
                final_context = ProjectEngineeringContext.build(
                    project_id=original.context.project_id,
                    complexity_level=original.context.complexity_level,
                    board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(
                        canonical_board_layout_snapshot_json(routed_layout)
                    ),
                    board_netlist=netlist,
                    inventory_status=original.context.inventory_status,
                    component_profiles=original.context.component_profiles,
                    phase14_features=original.context.phase14_features,
                    source_context_ids=original.context.source_context_ids,
                    reviewer_record_id=original.context.reviewer_record_id,
                    intended_consumer=original.context.intended_consumer,
                )
                final_gate = evaluate_project_engineering_gate(
                    final_context,
                    Phase14EvaluationBundle(decoupling_loops=loop_results),
                    original.discovery_reports,
                )
                _write(checks / "engineering-gate.json", final_gate)
            requirements = []
            executions = []
            for record in records:
                requirements.append(
                    ApplicableCheckRequirement.build(
                        check_id=record.kind.value,
                        rule_ids=(record.kind.value,),
                        applicability=ProjectCheckApplicability.APPLICABLE,
                        applicability_authority_id="native-routed-board",
                        exact_input_sha256s=(sha,),
                        minimum_evaluated_objects=1,
                        rationale="Actual native candidate validation.",
                    )
                )
                executions.append(
                    CheckExecutionRecord.build(
                        check_id=record.kind.value,
                        exact_input_sha256s=(sha,),
                        producer_id=record.producer_id,
                        tool_version=record.tool_version,
                        evaluated_object_count=1,
                        disposition=ProjectCheckDisposition.PASS
                        if record.accepted
                        else ProjectCheckDisposition.FAIL,
                        result_sha256=record.record_fingerprint,
                    )
                )
            for feature in entry.deferred_routed_features:
                requirements.append(
                    ApplicableCheckRequirement.build(
                        check_id=feature.feature_id,
                        rule_ids=feature.required_declaration_ids,
                        applicability=ProjectCheckApplicability.APPLICABLE,
                        applicability_authority_id=entry.report_fingerprint,
                        exact_input_sha256s=(sha,),
                        minimum_evaluated_objects=1,
                        rationale=feature.rationale
                        + " Requires actual post-route execution before acceptance.",
                    )
                )
            for result in loop_results:
                feature = next(
                    f
                    for f in entry.deferred_routed_features
                    if result.declaration.declaration_id in f.required_declaration_ids
                )
                executions.append(
                    CheckExecutionRecord.build(
                        check_id=feature.feature_id,
                        exact_input_sha256s=(sha,),
                        producer_id="pcbsmith.production_decoupling",
                        tool_version="1",
                        evaluated_object_count=2 if result.metrics is not None else 0,
                        disposition=ProjectCheckDisposition.PASS
                        if result.disposition.value == "pass"
                        else ProjectCheckDisposition.FAIL,
                        result_sha256=result.result_fingerprint,
                    )
                )
            applicability = ProjectApplicabilityExecutionManifest.build(
                project_id=gate_inputs.context.project_id,
                saved_design_sha256=sha,
                requirements=tuple(requirements),
                executions=tuple(executions),
            )
            validation = RoutingCandidateValidationBundle.build(
                board_sha256=sha,
                saved_board_routing=saved,
                kicad_drc=drc,
                verification=verification,
                applicability_execution=applicability,
                semantic_readback_accepted=immutable_readback_matches(source, readback),
            )
            _write(checks / "candidate-validation.json", validation)
            return validation

        result = run_routing_candidate_transaction(
            transaction_root=output,
            project_id=gate_inputs.context.project_id,
            candidate_id="candidate-01",
            generation_id="routed-01",
            request=request,
            input_snapshot=snapshot,
            input_payloads=payloads,
            source_layout=layout,
            netlist=netlist,
            engine_runner=engine,
            validator=validator,
            profile=profile,
            revalidate_result=revalidate_result,
            revalidate_sha256=revalidate_sha256,
            repair_plane_clearance_mm=repair_plane_clearance_mm,
            native_repair=native_repair,
        )
        if native_project_hashes(board) != closure:
            raise ValueError("routing changed source project inputs")
        _write(output / "result.json", result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("board", "layout", "netlist", "profile", "gate_inputs", "output"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--routing-options", type=Path)
    parser.add_argument(
        "--freerouting-config",
        type=Path,
        help="Pinned Freerouting settings; defaults to the installed configuration",
    )
    parser.add_argument(
        "--legacy-native-reason",
        help="Explicit legacy/research purpose; never an automatic fallback",
    )
    parser.add_argument(
        "--manual-routing-authorization",
        help="User authorization for an explicitly requested retained manual repair",
    )
    parser.add_argument("--revalidate-result", type=Path)
    parser.add_argument("--revalidate-sha256")
    parser.add_argument("--repair-plane-clearance-mm", type=float)
    parser.add_argument("--native-repair", type=Path)
    parser.add_argument("--engineering-revision", type=Path)
    parser.add_argument("--engineering-revision-sha256")
    args = parser.parse_args()
    import sys

    from pcbsmith.board_job import require_worker

    require_worker("pcbsmith.production_routing", sys.argv[1:])

    options = (
        {}
        if args.routing_options is None
        else json.loads(args.routing_options.read_text(encoding="utf-8"))
    )
    if set(options) - {"net_order", "net_widths", "plane_pour"}:
        raise ValueError("unsupported routing option")
    if "plane_pour" in options:
        options["plane_pour"] = NativePlanePour.model_validate(options["plane_pour"])
    result = route_saved_placement_candidate(
        board=args.board,
        freerouting_config=args.freerouting_config,
        legacy_native_reason=args.legacy_native_reason,
        manual_routing_authorization=args.manual_routing_authorization,
        layout=parse_canonical_board_layout_snapshot(args.layout.read_text(encoding="utf-8")),
        netlist=parse_canonical_board_netlist_snapshot(args.netlist.read_text(encoding="utf-8")),
        profile=PcbRuleProfile.model_validate_json(args.profile.read_bytes()),
        gate_inputs=RoutingGateInputs.model_validate_json(args.gate_inputs.read_bytes()),
        output=args.output,
        engineering_revision=args.engineering_revision,
        engineering_revision_sha256=args.engineering_revision_sha256,
        revalidate_result=args.revalidate_result,
        revalidate_sha256=args.revalidate_sha256,
        repair_plane_clearance_mm=args.repair_plane_clearance_mm,
        native_repair_file=args.native_repair,
        **options,
    )
    print(result.status.value)
    if result.status.value != "accepted":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
