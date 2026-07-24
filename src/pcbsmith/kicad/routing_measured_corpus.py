"""Replayable measured corpus for deterministic negotiated-routing fixtures."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board import BoardLayout, BoardNetlist, render_board_from_layout
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.kicad.negotiated_board import (
    NegotiatedBoardRouteResult,
    exact_route_check_report_fingerprint,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_ir import RoutingIrModel

_AUTHORIZED_INFERENCE = (
    "This corpus establishes deterministic negotiated-routing replay, exact-check "
    "acceptance, and parser-readable KiCad serialization only. It does not establish "
    "routing superiority, manufacturability, or live KiCad DRC."
)


class MeasuredNegotiatedRoutingCase(RoutingIrModel):
    schema_id: Literal["pcbsmith-measured-negotiated-routing-case"] = (
        "pcbsmith-measured-negotiated-routing-case"
    )
    schema_version: Literal[1] = 1
    case_id: str
    source_layout_snapshot_json: str
    source_layout_fingerprint: str
    routed_layout_snapshot_json: str
    routed_layout_fingerprint: str
    netlist_snapshot_json: str
    netlist_fingerprint: str
    run_result_json: str
    run_result_fingerprint: str
    exact_checker_id: str
    exact_report_fingerprint: str
    route_order: tuple[str, ...]
    pass_fingerprints: tuple[str, ...]
    expansion_count: int = Field(ge=0)
    routed_length_mm: tuple[tuple[str, str], ...]
    routed_segment_count: int = Field(ge=0)
    routed_via_count: int = Field(ge=0)
    serialized_board_text: str
    serialized_board_sha256: str
    case_fingerprint: str

    @model_validator(mode="after")
    def case_is_rederivable(self) -> Self:
        require_identity(self.case_id, "case_id")
        require_identity(self.exact_checker_id, "exact_checker_id")
        for field_name in (
            "source_layout_fingerprint",
            "routed_layout_fingerprint",
            "netlist_fingerprint",
            "run_result_fingerprint",
            "exact_report_fingerprint",
            "serialized_board_sha256",
            "case_fingerprint",
        ):
            require_sha256(getattr(self, field_name), field_name)
        source = parse_canonical_board_layout_snapshot(
            self.source_layout_snapshot_json
        )
        routed = parse_canonical_board_layout_snapshot(
            self.routed_layout_snapshot_json
        )
        netlist = parse_canonical_board_netlist_snapshot(
            self.netlist_snapshot_json
        )
        if self.source_layout_fingerprint != board_layout_snapshot_fingerprint(
            self.source_layout_snapshot_json
        ):
            raise ValueError("routing corpus source-layout fingerprint is stale")
        if self.routed_layout_fingerprint != board_layout_snapshot_fingerprint(
            self.routed_layout_snapshot_json
        ):
            raise ValueError("routing corpus routed-layout fingerprint is stale")
        if self.netlist_fingerprint != board_netlist_snapshot_fingerprint(
            self.netlist_snapshot_json
        ):
            raise ValueError("routing corpus netlist fingerprint is stale")
        run_payload = json.loads(self.run_result_json)
        if self.run_result_fingerprint != fingerprint(run_payload):
            raise ValueError("routing corpus run-result fingerprint is stale")
        if tuple(run_payload["route_order"]) != self.route_order:
            raise ValueError("routing corpus route order is stale")
        passes = tuple(run_payload["passes"])
        expected_pass_fingerprints = tuple(
            fingerprint(item) for item in passes
        )
        if self.pass_fingerprints != expected_pass_fingerprints:
            raise ValueError("routing corpus pass fingerprints are stale")
        expected_expansions = sum(int(item["expansion_count"]) for item in passes)
        if self.expansion_count != expected_expansions:
            raise ValueError("routing corpus expansion count is stale")
        expected_lengths = _route_lengths(routed, self.route_order)
        if self.routed_length_mm != expected_lengths:
            raise ValueError("routing corpus routed lengths are stale")
        routed_names = set(self.route_order)
        if self.routed_segment_count != sum(
            item.net_name in routed_names for item in routed.segments
        ):
            raise ValueError("routing corpus segment count is stale")
        if self.routed_via_count != sum(
            item.net_name in routed_names for item in routed.vias
        ):
            raise ValueError("routing corpus via count is stale")
        if render_board_from_layout(netlist, routed) != self.serialized_board_text:
            raise ValueError("routing corpus serialized board is stale")
        if hashlib.sha256(self.serialized_board_text.encode("utf-8")).hexdigest() != (
            self.serialized_board_sha256
        ):
            raise ValueError("routing corpus serialized-board digest is stale")
        if parse_sexpr(self.serialized_board_text)[0] != "kicad_pcb":
            raise ValueError("routing corpus serialized board is not parser-readable")
        expected_case = _case_fingerprint(self)
        if self.case_fingerprint != expected_case:
            raise ValueError("routing corpus case fingerprint is stale")
        if source == routed:
            raise ValueError("routing corpus case did not add routed geometry")
        return self


class MeasuredNegotiatedRoutingCorpus(RoutingIrModel):
    schema_id: Literal["pcbsmith-measured-negotiated-routing-corpus"] = (
        "pcbsmith-measured-negotiated-routing-corpus"
    )
    schema_version: Literal[1] = 1
    cases: tuple[MeasuredNegotiatedRoutingCase, ...] = Field(min_length=2)
    authorized_inference: str = _AUTHORIZED_INFERENCE
    corpus_fingerprint: str

    @model_validator(mode="after")
    def corpus_is_canonical(self) -> Self:
        cases = tuple(sorted(self.cases, key=lambda item: item.case_id))
        ids = tuple(item.case_id for item in cases)
        if len(ids) != len(set(ids)):
            raise ValueError("routing corpus case identities must be unique")
        object.__setattr__(self, "cases", cases)
        if self.authorized_inference != _AUTHORIZED_INFERENCE:
            raise ValueError("routing corpus inference boundary is not exact")
        require_sha256(self.corpus_fingerprint, "corpus_fingerprint")
        expected = fingerprint(
            {
                "schema_id": self.schema_id,
                "schema_version": self.schema_version,
                "case_fingerprints": tuple(
                    item.case_fingerprint for item in cases
                ),
                "authorized_inference": self.authorized_inference,
            }
        )
        if self.corpus_fingerprint != expected:
            raise ValueError("routing corpus fingerprint is stale")
        return self


def build_measured_negotiated_routing_case(
    *,
    case_id: str,
    source_layout: BoardLayout,
    netlist: BoardNetlist,
    result: NegotiatedBoardRouteResult,
) -> MeasuredNegotiatedRoutingCase:
    if (
        not result.run_result.success
        or not result.run_result.accepted
        or result.run_result.resource_overuse
        or result.run_result.unresolved_net_names
        or result.exact_check is None
        or not result.exact_check.accepted
        or result.exact_check_evidence is None
    ):
        raise ValueError(
            "measured routing case requires zero-overuse exact-accepted routing"
        )
    source_json = canonical_board_layout_snapshot_json(source_layout)
    routed_json = canonical_board_layout_snapshot_json(result.layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    run_json = result.run_result.semantic_json()
    run_payload = json.loads(run_json)
    serialized = render_board_from_layout(netlist, result.layout)
    fields: dict[str, Any] = {
        "case_id": case_id,
        "source_layout_snapshot_json": source_json,
        "source_layout_fingerprint": board_layout_snapshot_fingerprint(source_json),
        "routed_layout_snapshot_json": routed_json,
        "routed_layout_fingerprint": board_layout_snapshot_fingerprint(routed_json),
        "netlist_snapshot_json": netlist_json,
        "netlist_fingerprint": board_netlist_snapshot_fingerprint(netlist_json),
        "run_result_json": run_json,
        "run_result_fingerprint": fingerprint(run_payload),
        "exact_checker_id": result.exact_check.checker_id,
        "exact_report_fingerprint": exact_route_check_report_fingerprint(
            result.exact_check
        ),
        "route_order": result.order,
        "pass_fingerprints": tuple(
            fingerprint(item) for item in run_payload["passes"]
        ),
        "expansion_count": sum(
            int(item["expansion_count"]) for item in run_payload["passes"]
        ),
        "routed_length_mm": _route_lengths(result.layout, result.order),
        "routed_segment_count": sum(
            item.net_name in set(result.order) for item in result.layout.segments
        ),
        "routed_via_count": sum(
            item.net_name in set(result.order) for item in result.layout.vias
        ),
        "serialized_board_text": serialized,
        "serialized_board_sha256": hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest(),
    }
    provisional = MeasuredNegotiatedRoutingCase.model_construct(
        **fields, case_fingerprint="0" * 64
    )
    return MeasuredNegotiatedRoutingCase(
        **fields, case_fingerprint=_case_fingerprint(provisional)
    )


def build_measured_negotiated_routing_corpus(
    cases: tuple[MeasuredNegotiatedRoutingCase, ...],
) -> MeasuredNegotiatedRoutingCorpus:
    ordered = tuple(sorted(cases, key=lambda item: item.case_id))
    corpus_fingerprint = fingerprint(
        {
            "schema_id": "pcbsmith-measured-negotiated-routing-corpus",
            "schema_version": 1,
            "case_fingerprints": tuple(
                item.case_fingerprint for item in ordered
            ),
            "authorized_inference": _AUTHORIZED_INFERENCE,
        }
    )
    return MeasuredNegotiatedRoutingCorpus(
        cases=ordered,
        corpus_fingerprint=corpus_fingerprint,
    )


def _route_lengths(
    layout: BoardLayout,
    route_order: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            net_name,
            repr(
                sum(
                    math.hypot(item.x2 - item.x1, item.y2 - item.y1)
                    for item in layout.segments
                    if item.net_name == net_name
                )
            ),
        )
        for net_name in route_order
    )


def _case_fingerprint(case: MeasuredNegotiatedRoutingCase) -> str:
    return fingerprint(
        {
            "schema_id": case.schema_id,
            "schema_version": case.schema_version,
            "case_id": case.case_id,
            "source_layout": case.source_layout_fingerprint,
            "routed_layout": case.routed_layout_fingerprint,
            "netlist": case.netlist_fingerprint,
            "run_result": case.run_result_fingerprint,
            "exact_report": case.exact_report_fingerprint,
            "route_order": case.route_order,
            "pass_fingerprints": case.pass_fingerprints,
            "expansion_count": case.expansion_count,
            "routed_length_mm": case.routed_length_mm,
            "routed_segment_count": case.routed_segment_count,
            "routed_via_count": case.routed_via_count,
            "serialized_board": case.serialized_board_sha256,
        }
    )
