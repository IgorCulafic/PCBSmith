"""R6.7 sourced switch-node copper-area policy and exact pi enclosure."""

from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist, ViaSpec
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph
from pcbsmith.kicad.switch_node_area_policy import (
    PI_LOWER,
    PI_UPPER,
    evaluate_switch_node_area_policy,
)
from pcbsmith.kicad.switch_node_copper import (
    build_exact_placed_pad_copper,
    build_switch_node_copper_union,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.routed_copper_graph_ir import ExactRational
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticVerification,
)
from pcbsmith.switch_node_area_policy_ir import (
    SwitchNodeAreaLimitPolicy,
    SwitchNodeAreaPolicyResult,
    switch_node_area_policy_context_fingerprint,
)
from pcbsmith.switch_node_copper_ir import SwitchNodeCopperDeclaration


def _rat(value: int | Fraction) -> ExactRational:
    return ExactRational.build(Fraction(value))


def _netlist() -> BoardNetlist:
    component = BoardComponent("U1", "fixture", "Fixture:Pad", "uuid:U1")
    return BoardNetlist(components=(component,), nets=(BoardNet("SW", (("U1", "1"),)),))


def _union(*, symbolic: bool = False, complete: bool = True):
    netlist = _netlist()
    layout = BoardLayout(
        placements=((netlist.components[0], 0.0),),
        segments=(),
        vias=(ViaSpec(5, 0, "SW", 2, 1),) if symbolic else (),
        width_mm=20,
        height_mm=10,
    )
    graph = build_routed_copper_graph(layout, netlist, ())
    declaration = SwitchNodeCopperDeclaration(
        declaration_id="switch-node:SW",
        graph_fingerprint=graph.graph_fingerprint,
        board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
        net_names=("SW",),
        layers=("F.Cu", "B.Cu") if symbolic else ("F.Cu",),
        complete_pad_authority=complete,
    )
    pad = build_exact_placed_pad_copper(
        component_reference="U1",
        pad_number="1",
        net_name="SW",
        layer="F.Cu",
        graph=graph,
        copper=ExactPlanarCompound(
            polygons=(ExactPlanarPolygon(outer=((0, 0), (1, 0), (1, 1), (0, 1))),)
        ),
    )
    return build_switch_node_copper_union(graph, declaration, (pad,))


def _evidence(*, suffix: str = "a", **updates) -> EvidenceRef:
    fields = {
        "kind": "manufacturer_design_guide",
        "title": f"Switching regulator layout guide {suffix}",
        "locator": f"page 7 figure {suffix}",
        "source_id": f"guide:{suffix}",
        "local_sha256": suffix * 64,
        "source_status": "pinned",
        "locator_status": "figure_verified",
        "applicability_status": "confirmed",
        "required_conditions": ("same converter family",),
        **updates,
    }
    return EvidenceRef(**fields)


def _hard_policy(
    union,
    maximum: ExactRational,
    *,
    evidence: tuple[EvidenceRef, ...] | None = None,
    required: tuple[str, ...] = ("same converter family",),
    matched: tuple[str, ...] | None = None,
    unmatched: tuple[str, ...] = (),
    reviewer: str | None = "review:area-limit",
    claim: str = "limit:switch-node-area",
    context: str | None = None,
    context_maximum: ExactRational | None = None,
) -> SwitchNodeAreaLimitPolicy:
    limit_id = "limit:switch-node-area"
    context_fp = context or switch_node_area_policy_context_fingerprint(
        union,
        limit_id=limit_id,
        mode="sourced_hard",
        maximum_area_mm2=maximum if context_maximum is None else context_maximum,
    )
    binding = EvidenceApplicabilityBinding(
        binding_id="binding:switch-node-area",
        evidence=evidence or (_evidence(),),
        claim_id=claim,
        applicability_record_id="applicability:switch-node-area",
        required_conditions=required,
        excluded_conditions=(),
        matched_conditions=required if matched is None else matched,
        unmatched_conditions=unmatched,
        geometry_source_fingerprint=context_fp,
        reviewer_record_id=reviewer,
    )
    return SwitchNodeAreaLimitPolicy(
        limit_id=limit_id,
        mode="sourced_hard",
        maximum_area_mm2=maximum,
        applicability_binding=binding,
    )


def test_rational_equality_passes_and_one_exact_unit_over_limit_fails() -> None:
    union = _union()
    assert union.rational_mm2 is not None and union.rational_mm2.fraction() == 1
    assert union.pi_coefficient_mm2 is not None
    assert union.pi_coefficient_mm2.fraction() == 0

    equal = evaluate_switch_node_area_policy(union, _hard_policy(union, _rat(1)))
    over = evaluate_switch_node_area_policy(union, _hard_policy(union, _rat(0)))

    assert equal.area_lower_bound_mm2 == equal.area_upper_bound_mm2 == _rat(1)
    assert equal.comparator_disposition == "within_limit"
    assert equal.disposition is SemanticDisposition.PASS
    assert over.comparator_disposition == "exceeds_limit"
    assert over.disposition is SemanticDisposition.FAIL
    assert over.violation_ids == ("maximum_switch_node_area_exceeded",)


def test_symbolic_pi_is_definitely_passed_or_failed_only_from_exact_bounds() -> None:
    union = _union(symbolic=True)
    assert union.pi_coefficient_mm2 is not None
    assert union.pi_coefficient_mm2.fraction() > 0
    definitely_pass = evaluate_switch_node_area_policy(union, _hard_policy(union, _rat(20)))
    definitely_fail = evaluate_switch_node_area_policy(union, _hard_policy(union, _rat(1)))

    assert definitely_pass.disposition is SemanticDisposition.PASS
    assert definitely_fail.disposition is SemanticDisposition.FAIL
    assert definitely_pass.pi_lower_bound == _rat(PI_LOWER)
    assert definitely_pass.pi_upper_bound == _rat(PI_UPPER)


def test_threshold_inside_retained_pi_enclosure_is_unverified() -> None:
    union = _union(symbolic=True)
    assert union.rational_mm2 is not None and union.pi_coefficient_mm2 is not None
    midpoint_pi = (PI_LOWER + PI_UPPER) / 2
    threshold = _rat(
        union.rational_mm2.fraction() + union.pi_coefficient_mm2.fraction() * midpoint_pi
    )

    result = evaluate_switch_node_area_policy(union, _hard_policy(union, threshold))

    assert result.comparator_disposition == "indeterminate_enclosure"
    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.unverified_reasons == ("pi_enclosure_comparison_indeterminate",)
    assert not result.violation_ids


def test_advisory_over_limit_never_becomes_a_hard_comparison() -> None:
    union = _union(symbolic=True)
    policy = SwitchNodeAreaLimitPolicy(
        limit_id="advice:switch-node-area",
        mode="advisory",
        maximum_area_mm2=_rat(0),
        applicability_binding=None,
    )

    result = evaluate_switch_node_area_policy(union, policy)

    assert result.comparator_disposition == "advisory_not_applied"
    assert result.disposition is SemanticDisposition.ADVISORY
    assert not result.violation_ids


@pytest.mark.parametrize(
    ("variant", "reason"),
    (
        ("missing", "hard_limit_evidence_missing"),
        ("no_conditions", "hard_limit_applicability_incomplete"),
        ("unmatched", "hard_limit_applicability_incomplete"),
        ("unpinned", "hard_limit_evidence_not_pinned_verified_applicable"),
        ("no_sha", "hard_limit_evidence_not_pinned_verified_applicable"),
        ("wrong_locator", "hard_limit_evidence_not_pinned_verified_applicable"),
        ("inapplicable", "hard_limit_evidence_not_pinned_verified_applicable"),
        ("no_reviewer", "hard_limit_applicability_incomplete"),
        ("wrong_claim", "hard_limit_claim_identity_mismatch"),
        ("wrong_context", "hard_limit_context_fingerprint_mismatch"),
        ("wrong_threshold_context", "hard_limit_context_fingerprint_mismatch"),
    ),
)
def test_incomplete_or_stale_sourced_authority_is_unverified(variant: str, reason: str) -> None:
    union = _union()
    maximum = _rat(2)
    if variant == "missing":
        policy = SwitchNodeAreaLimitPolicy(
            limit_id="limit:switch-node-area",
            mode="sourced_hard",
            maximum_area_mm2=maximum,
            applicability_binding=None,
        )
    elif variant == "no_conditions":
        policy = _hard_policy(union, maximum, required=(), matched=())
    elif variant == "unmatched":
        policy = _hard_policy(
            union,
            maximum,
            required=("same converter family", "same stackup"),
            matched=("same converter family",),
            unmatched=("same stackup",),
        )
    elif variant == "unpinned":
        policy = _hard_policy(
            union,
            maximum,
            evidence=(_evidence(source_status="unpinned", local_sha256=None),),
        )
    elif variant == "no_sha":
        policy = _hard_policy(union, maximum, evidence=(_evidence(local_sha256=None),))
    elif variant == "wrong_locator":
        policy = _hard_policy(union, maximum, evidence=(_evidence(locator_status="unverified"),))
    elif variant == "inapplicable":
        policy = _hard_policy(
            union,
            maximum,
            evidence=(_evidence(applicability_status="conditional"),),
        )
    elif variant == "no_reviewer":
        policy = _hard_policy(union, maximum, reviewer=None)
    elif variant == "wrong_claim":
        policy = _hard_policy(union, maximum, claim="claim:someone-else")
    elif variant == "wrong_context":
        policy = _hard_policy(union, maximum, context="f" * 64)
    else:
        policy = _hard_policy(union, maximum, context_maximum=_rat(3))

    result = evaluate_switch_node_area_policy(union, policy)

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.comparator_disposition == "authority_unverified"
    assert reason in result.unverified_reasons
    assert not result.violation_ids


def test_missing_hard_threshold_is_unverified_without_numeric_failure() -> None:
    union = _union()
    policy = SwitchNodeAreaLimitPolicy(
        limit_id="limit:switch-node-area",
        mode="sourced_hard",
        maximum_area_mm2=None,
        applicability_binding=None,
    )
    result = evaluate_switch_node_area_policy(union, policy)
    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert "hard_limit_threshold_missing" in result.unverified_reasons


def test_unsupported_union_propagates_without_area_bounds_or_advisory_override() -> None:
    union = _union(complete=False)
    assert union.verification is SemanticVerification.UNSUPPORTED
    policy = SwitchNodeAreaLimitPolicy(
        limit_id="advice:switch-node-area",
        mode="advisory",
        maximum_area_mm2=_rat(0),
        applicability_binding=None,
    )

    result = evaluate_switch_node_area_policy(union, policy)

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.comparator_disposition == "unsupported_metric"
    assert result.area_lower_bound_mm2 is None
    assert result.area_upper_bound_mm2 is None
    assert result.pi_lower_bound is None and result.pi_upper_bound is None


@pytest.mark.parametrize(
    "field",
    (
        "per_layer_areas",
        "rational_mm2",
        "source_coverage_ids",
        "evidence_fingerprint",
    ),
)
def test_nested_union_per_layer_total_and_source_tamper_is_rejected(field: str) -> None:
    result = evaluate_switch_node_area_policy(_union(), _hard_policy(_union(), _rat(2)))
    payload = json.loads(result.model_dump_json())
    if field == "per_layer_areas":
        payload["union"][field][0]["rational_mm2"]["numerator"] = 9
    elif field == "rational_mm2":
        payload["union"][field]["numerator"] = 9
    elif field == "source_coverage_ids":
        payload["union"][field].append("invented:source")
    else:
        payload["union"][field] = "0" * 64
    with pytest.raises(ValidationError):
        SwitchNodeAreaPolicyResult.model_validate(payload)


def test_policy_evidence_and_outer_fingerprint_tamper_is_rejected() -> None:
    union = _union()
    result = evaluate_switch_node_area_policy(union, _hard_policy(union, _rat(2)))
    payload = json.loads(result.model_dump_json())
    payload["policy"]["applicability_binding"]["evidence"][0]["local_sha256"] = "b" * 64
    with pytest.raises(ValidationError):
        SwitchNodeAreaPolicyResult.model_validate(payload)

    payload = json.loads(result.model_dump_json())
    payload["policy"]["maximum_area_mm2"]["numerator"] = 3
    with pytest.raises(ValidationError):
        SwitchNodeAreaPolicyResult.model_validate(payload)

    payload = json.loads(result.model_dump_json())
    payload["result_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError):
        SwitchNodeAreaPolicyResult.model_validate(payload)


def test_json_replay_canonical_evidence_order_and_immutability() -> None:
    union = _union()
    maximum = _rat(2)
    first = _hard_policy(union, maximum, evidence=(_evidence(suffix="a"), _evidence(suffix="b")))
    second = _hard_policy(union, maximum, evidence=(_evidence(suffix="b"), _evidence(suffix="a")))
    one = evaluate_switch_node_area_policy(union, first)
    two = evaluate_switch_node_area_policy(union, second)

    assert one.model_dump_json() == two.model_dump_json()
    assert SwitchNodeAreaPolicyResult.model_validate_json(one.model_dump_json()) == one
    before = deepcopy(one.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        one.policy = second  # type: ignore[misc]
    assert one.model_dump(mode="json") == before
