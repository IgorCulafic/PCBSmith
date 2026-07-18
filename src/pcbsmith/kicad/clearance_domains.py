"""Shared construction and conservative reduction of routing clearance domains."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeAlias

from pcbsmith.kicad.negotiated_resources import (
    PairwiseClearanceDomain,
    build_pairwise_clearance_domains,
)
from pcbsmith.rule_profiles import (
    OrdinaryClearanceRequirement,
    PcbRuleProfile,
    qualified_insulation_clearance_groups,
)

ClearanceGroupInput: TypeAlias = tuple[
    Collection[str],
    Collection[str],
    float,
    Collection[str],
]


@dataclass(frozen=True)
class ConservativeNetClearance:
    """One net's conservative routing clearance over the active demand set."""

    effective_clearance_mm: float
    pairwise_domain_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.effective_clearance_mm) or self.effective_clearance_mm < 0:
            raise ValueError("effective clearance must be finite and non-negative")
        canonical_ids = tuple(sorted(set(self.pairwise_domain_ids)))
        if any(not domain_id for domain_id in canonical_ids):
            raise ValueError("pairwise domain IDs must be non-empty")
        object.__setattr__(self, "pairwise_domain_ids", canonical_ids)


def build_route_pairwise_clearance_domains(
    profile: PcbRuleProfile,
    clearance_groups: Sequence[ClearanceGroupInput] = (),
) -> tuple[PairwiseClearanceDomain, ...]:
    """Canonicalize every executable air-clearance source exactly once."""
    requirements = list(profile.fab_spacing.pairwise_clearances)
    requirements.extend(
        OrdinaryClearanceRequirement(
            requirement_id=f"qualified-insulation:{barrier_id}",
            nets_a=tuple(sorted(set(nets_a))),
            nets_b=tuple(sorted(set(nets_b))),
            minimum_clearance_mm=gap_mm,
            exempt_component_refs=tuple(sorted(set(exempt))),
            rule_ids=(barrier_id,),
        )
        for barrier_id, nets_a, nets_b, gap_mm, exempt in (
            qualified_insulation_clearance_groups(profile)
        )
    )
    for nets_a, nets_b, gap_mm, exempt in clearance_groups:
        normalized_nets_a = tuple(sorted(set(nets_a)))
        normalized_nets_b = tuple(sorted(set(nets_b)))
        normalized_exempt = tuple(sorted(set(exempt)))
        identity = json.dumps(
            {
                "nets_a": normalized_nets_a,
                "nets_b": normalized_nets_b,
                "minimum_clearance_mm": gap_mm,
                "exempt_component_refs": normalized_exempt,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        requirement_id = "caller-clearance:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        requirements.append(
            OrdinaryClearanceRequirement(
                requirement_id=requirement_id,
                nets_a=normalized_nets_a,
                nets_b=normalized_nets_b,
                minimum_clearance_mm=gap_mm,
                exempt_component_refs=normalized_exempt,
            )
        )
    return build_pairwise_clearance_domains(profile.profile_id, requirements)


def conservative_clearance_for_net(
    net_name: str,
    active_net_names: Collection[str],
    ordinary_clearance_mm: float,
    domains: Iterable[PairwiseClearanceDomain],
) -> ConservativeNetClearance:
    """Reduce active pairwise domains without applying selectors or exemptions."""
    if not math.isfinite(ordinary_clearance_mm) or ordinary_clearance_mm < 0:
        raise ValueError("ordinary clearance must be finite and non-negative")
    active = frozenset(active_net_names)
    applicable = tuple(
        domain
        for domain in domains
        if domain.applies_to(net_name) and domain.net_low in active and domain.net_high in active
    )
    return ConservativeNetClearance(
        effective_clearance_mm=max(
            (ordinary_clearance_mm, *(domain.minimum_clearance_mm for domain in applicable))
        ),
        pairwise_domain_ids=tuple(domain.domain_id for domain in applicable),
    )
