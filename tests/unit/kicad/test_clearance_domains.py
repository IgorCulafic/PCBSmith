from __future__ import annotations

import pytest

import pcbsmith.kicad.clearance_domains as clearance_domains
from pcbsmith.kicad.clearance_domains import (
    ConservativeNetClearance,
    build_route_pairwise_clearance_domains,
    conservative_clearance_for_net,
)
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    OrdinaryClearanceRequirement,
    PcbRuleProfile,
)


def _profile_with(*requirements: OrdinaryClearanceRequirement) -> PcbRuleProfile:
    return DEFAULT_PCB_RULE_PROFILE.model_copy(
        update={
            "fab_spacing": DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
                update={"pairwise_clearances": requirements}
            )
        }
    )


def test_shared_builder_preserves_fab_qualified_and_caller_domain_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = OrdinaryClearanceRequirement(
        requirement_id="fab-pair",
        nets_a=("A",),
        nets_b=("B",),
        minimum_clearance_mm=0.7,
    )
    monkeypatch.setattr(
        clearance_domains,
        "qualified_insulation_clearance_groups",
        lambda _profile: (("qualified-pair", ("A",), ("B",), 0.8, ("U1",)),),
    )

    domains = build_route_pairwise_clearance_domains(
        _profile_with(requirement),
        clearance_groups=((("B", "A"), ("D", "C"), 0.9, ("U3", "U2")),),
    )
    repeated = build_route_pairwise_clearance_domains(
        _profile_with(requirement),
        clearance_groups=((("A", "B"), ("C", "D"), 0.9, ("U2", "U3")),),
    )

    assert domains == repeated
    requirement_ids = {domain.requirement_id for domain in domains}
    assert "fab-pair" in requirement_ids
    assert "qualified-insulation:qualified-pair" in requirement_ids
    caller_ids = {
        domain.requirement_id
        for domain in domains
        if domain.requirement_id.startswith("caller-clearance:")
    }
    assert len(caller_ids) == 1
    qualified = next(
        domain
        for domain in domains
        if domain.requirement_id == "qualified-insulation:qualified-pair"
    )
    assert qualified.rule_ids == ("qualified-pair",)
    assert qualified.exempt_component_refs == ("U1",)


def test_conservative_reduction_uses_only_active_pair_endpoints_and_maximum() -> None:
    requirements = (
        OrdinaryClearanceRequirement(
            requirement_id="a-b-low",
            nets_a=("A",),
            nets_b=("B",),
            minimum_clearance_mm=0.5,
            mask_states_a=("masked",),
            exempt_component_refs=("U1",),
        ),
        OrdinaryClearanceRequirement(
            requirement_id="a-b-high",
            nets_a=("A",),
            nets_b=("B",),
            minimum_clearance_mm=0.8,
            roles_a=("via_land",),
        ),
        OrdinaryClearanceRequirement(
            requirement_id="a-c-inactive",
            nets_a=("A",),
            nets_b=("C",),
            minimum_clearance_mm=1.2,
        ),
        OrdinaryClearanceRequirement(
            requirement_id="b-c-foreign",
            nets_a=("B",),
            nets_b=("C",),
            minimum_clearance_mm=1.4,
        ),
    )
    domains = build_route_pairwise_clearance_domains(_profile_with(*requirements))

    result = conservative_clearance_for_net("A", ("A", "B"), 0.2, domains)

    expected = tuple(domain.domain_id for domain in domains if domain.net_names == ("A", "B"))
    assert result == ConservativeNetClearance(0.8, expected)


def test_conservative_reduction_keeps_ordinary_clearance_and_no_inactive_ids() -> None:
    domains = build_route_pairwise_clearance_domains(
        _profile_with(
            OrdinaryClearanceRequirement(
                requirement_id="a-b",
                nets_a=("A",),
                nets_b=("B",),
                minimum_clearance_mm=0.5,
            )
        )
    )

    assert conservative_clearance_for_net("A", ("A",), 0.6, domains) == (
        ConservativeNetClearance(0.6)
    )


@pytest.mark.parametrize("ordinary", [-0.1, float("nan"), float("inf")])
def test_conservative_reduction_rejects_invalid_ordinary_clearance(ordinary: float) -> None:
    with pytest.raises(ValueError, match="ordinary clearance"):
        conservative_clearance_for_net("A", ("A",), ordinary, ())
