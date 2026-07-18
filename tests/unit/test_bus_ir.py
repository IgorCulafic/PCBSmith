from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from pcbsmith.bus_ir import (
    BoundaryMemberRef,
    BusBoundary,
    BusCertificateContext,
    BusCertificateHandshakeReason,
    BusCoherencePolicy,
    BusCouplingBudget,
    BusFallbackPolicy,
    BusGroup,
    BusLayerPolicy,
    BusMember,
    BusPermutationPolicy,
    BusSwapWindow,
    BusTerminalOwnership,
    BusTerminalRef,
    BusTerminalRole,
    BusTimingBudget,
    BusViaPolicy,
    CertifiedCorridorSection,
    CertifiedLaneSlot,
    ConstraintAuthority,
    CorridorCapacityCertificate,
    validate_bus_certificate,
)
from pcbsmith.circuit.models import EvidenceRef


def _terminal(
    terminal_id: str,
    net_name: str,
    role: BusTerminalRole,
) -> BusTerminalRef:
    return BusTerminalRef(
        terminal_id=terminal_id,
        net_name=net_name,
        component_ref=f"U-{terminal_id}",
        pad_number="1",
        role=role,
    )


def _member(member_id: str, net_name: str) -> BusMember:
    return BusMember(
        member_id=member_id,
        net_name=net_name,
        terminals=(
            _terminal(f"{member_id}-source", net_name, "source"),
            _terminal(f"{member_id}-sink", net_name, "sink"),
        ),
        width_mm=0.2,
    )


def _bus() -> BusGroup:
    members = (_member("data0", "/D0"), _member("data1", "/D1"))
    return BusGroup(
        bus_id="display-data",
        members=members,
        boundaries=(
            BusBoundary(
                boundary_id="entry",
                corridor_portal_id="portal:entry",
                orientation="forward",
                ordered_members=(
                    BoundaryMemberRef(
                        member_id="data0",
                        terminal_ids=("data0-source",),
                    ),
                    BoundaryMemberRef(
                        member_id="data1",
                        terminal_ids=("data1-source",),
                    ),
                ),
            ),
            BusBoundary(
                boundary_id="exit",
                corridor_portal_id="portal:exit",
                orientation="forward",
                ordered_members=(
                    BoundaryMemberRef(
                        member_id="data0",
                        terminal_ids=("data0-sink",),
                    ),
                    BoundaryMemberRef(
                        member_id="data1",
                        terminal_ids=("data1-sink",),
                    ),
                ),
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        rule_profile_id="default-two-layer",
    )


def _slot(
    section_id: str,
    slot_id: str,
    order_index: int,
    *,
    reverse_domains: bool = False,
) -> CertifiedLaneSlot:
    domains = ("pair:data", "ordinary") if reverse_domains else ("ordinary", "pair:data")
    return CertifiedLaneSlot(
        slot_id=slot_id,
        section_id=section_id,
        layer="F.Cu",
        order_index=order_index,
        centerline_geometry_id=f"centerline:{slot_id}",
        maximum_track_width_mm=0.4,
        supported_clearance_domain_ids=domains,
    )


def _certificate(*, reverse_sets: bool = False) -> CorridorCapacityCertificate:
    reserved = ("fixed-power", "fixed-ground")
    section = CertifiedCorridorSection(
        section_id="trunk",
        entry_portal_id="portal:entry",
        exit_portal_id="portal:exit",
        lane_slots=(
            _slot("trunk", "lane:0", 0, reverse_domains=reverse_sets),
            _slot("trunk", "lane:1", 1, reverse_domains=reverse_sets),
        ),
        swap_window_ids=tuple(reversed(("swap:b", "swap:a")))
        if reverse_sets
        else ("swap:a", "swap:b"),
        transition_window_ids=("transition:a",),
    )
    return CorridorCapacityCertificate(
        certificate_id="certificate:display-data",
        board_geometry_fingerprint="a" * 64,
        static_obstacle_fingerprint="b" * 64,
        rule_profile_fingerprint="c" * 64,
        demand_fingerprint="d" * 64,
        corridor_graph_fingerprint="e" * 64,
        grid_mm=0.5,
        sections=(section,),
        reserved_demand_ids=tuple(reversed(reserved)) if reverse_sets else reserved,
        exact_capacity_proof_id="r3-exact-capacity-v1",
    )


def test_valid_straight_bus_is_frozen_versioned_and_fingerprinted() -> None:
    bus = _bus()
    repeated = BusGroup.model_validate_json(bus.semantic_json())

    assert bus.schema_id == "pcbsmith-bus-group"
    assert bus.schema_version == 1
    assert tuple(member.member_id for member in bus.members) == ("data0", "data1")
    assert tuple(ref.member_id for ref in bus.boundaries[0].ordered_members) == (
        "data0",
        "data1",
    )
    assert repeated == bus
    assert (
        bus.semantic_fingerprint()
        == "ca56a84bb5c293390343f18b506922ba215b770930b2f1b6ef106974d59f334d"
    )
    with pytest.raises(ValidationError, match="frozen"):
        bus.bus_id = "changed"  # type: ignore[misc]


def test_member_and_terminal_identity_sets_canonicalize_without_reordering_boundaries() -> None:
    first = _bus()
    reversed_members = tuple(
        member.model_copy(update={"terminals": tuple(reversed(member.terminals))})
        for member in reversed(first.members)
    )
    rebuilt = BusGroup.model_validate(
        {
            **first.model_dump(),
            "members": reversed_members,
        }
    )

    assert rebuilt == first
    assert rebuilt.semantic_fingerprint() == first.semantic_fingerprint()
    assert rebuilt.boundaries == first.boundaries
    assert tuple(ref.member_id for ref in rebuilt.boundaries[0].ordered_members) == (
        "data0",
        "data1",
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda bus: bus.model_copy(update={"members": (bus.members[0], bus.members[0])}),
            "member identities",
        ),
        (
            lambda bus: bus.model_copy(
                update={
                    "members": (
                        bus.members[0],
                        _member("data1", "/D0"),
                    )
                }
            ),
            "member nets",
        ),
        (
            lambda bus: bus.model_copy(
                update={
                    "members": (
                        bus.members[0],
                        bus.members[1].model_copy(
                            update={
                                "terminals": (
                                    bus.members[1]
                                    .terminals[0]
                                    .model_copy(update={"terminal_id": "data0-source"}),
                                    bus.members[1].terminals[1],
                                )
                            }
                        ),
                    )
                }
            ),
            "terminal identities",
        ),
        (
            lambda bus: bus.model_copy(
                update={"boundaries": (bus.boundaries[0], bus.boundaries[0])}
            ),
            "boundary identities",
        ),
    ),
)
def test_duplicate_bus_identities_are_rejected(
    mutate: Callable[[BusGroup], BusGroup],
    message: str,
) -> None:
    changed = mutate(_bus())
    with pytest.raises(ValidationError, match=message):
        BusGroup.model_validate(changed.model_dump())


def test_member_cannot_disappear_without_declared_terminal_or_tap() -> None:
    member = BusMember(
        member_id="clock",
        net_name="/CLK",
        terminals=(
            _terminal("clock-source", "/CLK", "source"),
            _terminal("clock-tap", "/CLK", "tap"),
        ),
        width_mm=0.2,
    )
    common = {
        "bus_id": "clock-trunk",
        "members": (member,),
        "permutation_policy": BusPermutationPolicy(),
        "layer_policy": BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        ),
        "rule_profile_id": "default-two-layer",
    }
    first = BusBoundary(
        boundary_id="entry",
        corridor_portal_id="portal:entry",
        orientation="forward",
        ordered_members=(BoundaryMemberRef(member_id="clock"),),
    )
    ended = BusBoundary(
        boundary_id="after-tap",
        corridor_portal_id="portal:after-tap",
        orientation="forward",
        ordered_members=(),
        inactive_member_ids=("clock",),
    )

    with pytest.raises(ValidationError, match="disappearance requires"):
        BusGroup(**common, boundaries=(first, ended))

    declared = first.model_copy(
        update={
            "ordered_members": (BoundaryMemberRef(member_id="clock", terminal_ids=("clock-tap",)),)
        }
    )
    assert BusGroup(**common, boundaries=(declared, ended)).members == (member,)


def test_member_cannot_activate_only_on_the_final_boundary() -> None:
    bus = _bus()
    final = _member("final", "/FINAL")
    final_boundary = bus.boundaries[-1].model_copy(
        update={
            "ordered_members": (
                *bus.boundaries[-1].ordered_members,
                BoundaryMemberRef(member_id="final", terminal_ids=("final-source",)),
            )
        }
    )
    with pytest.raises(ValidationError, match="active on at least one corridor section"):
        BusGroup.model_validate(
            {
                **bus.model_dump(),
                "members": (*bus.members, final),
                "boundaries": (*bus.boundaries[:-1], final_boundary),
            }
        )


def test_member_width_must_be_finite_and_positive() -> None:
    for width in (0.0, -0.1, math.inf, math.nan):
        with pytest.raises(ValidationError):
            BusMember.model_validate({**_member("data", "/D").model_dump(), "width_mm": width})


def test_certificate_canonicalizes_sets_and_has_literal_fingerprint() -> None:
    first = _certificate()
    reversed_sets = _certificate(reverse_sets=True)

    assert first == reversed_sets
    assert first.reserved_demand_ids == ("fixed-ground", "fixed-power")
    assert first.sections[0].swap_window_ids == ("swap:a", "swap:b")
    assert first.sections[0].lane_slots[0].supported_clearance_domain_ids == (
        "ordinary",
        "pair:data",
    )
    assert (
        first.semantic_fingerprint()
        == "487ad17f3188c67c2886110b39cf1f300a317cebe2957972757ec8205403b71e"
    )


def test_certificate_rejects_bad_fingerprints_slots_and_disconnected_sections() -> None:
    certificate = _certificate()
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        CorridorCapacityCertificate.model_validate(
            {**certificate.model_dump(), "board_geometry_fingerprint": "A" * 64}
        )

    bad_slot = certificate.sections[0].lane_slots[1].model_copy(update={"order_index": 3})
    with pytest.raises(ValidationError, match="consecutive order"):
        CertifiedCorridorSection.model_validate(
            {
                **certificate.sections[0].model_dump(),
                "lane_slots": (certificate.sections[0].lane_slots[0], bad_slot),
            }
        )

    second = certificate.sections[0].model_copy(
        update={
            "section_id": "second",
            "entry_portal_id": "wrong-entry",
            "exit_portal_id": "portal:end",
            "lane_slots": (
                _slot("second", "second:0", 0),
                _slot("second", "second:1", 1),
            ),
        }
    )
    with pytest.raises(ValidationError, match="connected portal chain"):
        CorridorCapacityCertificate.model_validate(
            {**certificate.model_dump(), "sections": (*certificate.sections, second)}
        )


def _context(certificate: CorridorCapacityCertificate | None = None) -> BusCertificateContext:
    certificate = certificate or _certificate()
    return BusCertificateContext(
        board_geometry_fingerprint=certificate.board_geometry_fingerprint,
        static_obstacle_fingerprint=certificate.static_obstacle_fingerprint,
        rule_profile_fingerprint=certificate.rule_profile_fingerprint,
        demand_fingerprint=certificate.demand_fingerprint,
        corridor_graph_fingerprint=certificate.corridor_graph_fingerprint,
        grid_mm=certificate.grid_mm,
    )


def _ownership(bus: BusGroup | None = None) -> dict[str, BusTerminalOwnership]:
    bus = bus or _bus()
    return {
        terminal.terminal_id: BusTerminalOwnership(
            terminal_id=terminal.terminal_id,
            net_name=terminal.net_name,
            component_ref=terminal.component_ref,
            pad_number=terminal.pad_number,
        )
        for member in bus.members
        for terminal in member.terminals
    }


def _verified_evidence() -> EvidenceRef:
    return EvidenceRef(
        kind="simulation",
        title="Pinned interface simulation",
        locator="run:bus-coupling-001",
        source_id="simulation:bus-coupling-001",
        local_sha256="f" * 64,
        source_status="pinned",
        locator_status="figure_verified",
        applicability_status="confirmed",
        required_conditions=("interface=74HC595", "stackup=two-layer-v1"),
    )


def _hard_authority() -> ConstraintAuthority:
    return ConstraintAuthority(
        enforcement="hard",
        evidence=(_verified_evidence(),),
        applicability_conditions=("stackup=two-layer-v1", "interface=74HC595"),
        validation_method_ids=("solver:field-v1",),
    )


def test_permutation_and_layer_policy_sets_canonicalize_but_orders_remain_semantic() -> None:
    permutation = BusPermutationPolicy(
        allow_whole_bundle_reversal=True,
        allowed_boundary_permutations=(
            ("exit", ("data1", "data0")),
            ("entry", ("data0", "data1")),
        ),
        swap_windows=(
            BusSwapWindow(
                window_id="swap:b",
                corridor_region_id="trunk",
                allowed_adjacent_pairs=(("data1", "data0"),),
                allowed_layers=("F.Cu", "B.Cu"),
                maximum_swaps=1,
            ),
            BusSwapWindow(
                window_id="swap:a",
                corridor_region_id="trunk",
            ),
        ),
    )
    layer = BusLayerPolicy(
        allowed_layers=("F.Cu", "B.Cu"),
        preferred_layers=("F.Cu",),
        via_policy=BusViaPolicy(
            mode="synchronous",
            transition_window_ids=("transition:b", "transition:a"),
            maximum_vias_per_member=2,
            maximum_via_count_spread=0,
        ),
    )
    base = _bus()
    bus = BusGroup.model_validate(
        {
            **base.model_dump(),
            "permutation_policy": permutation,
            "layer_policy": layer,
        }
    )

    assert tuple(item[0] for item in bus.permutation_policy.allowed_boundary_permutations) == (
        "entry",
        "exit",
    )
    assert bus.permutation_policy.allowed_boundary_permutations[1][1] == (
        "data1",
        "data0",
    )
    assert tuple(item.window_id for item in bus.permutation_policy.swap_windows) == (
        "swap:a",
        "swap:b",
    )
    assert bus.permutation_policy.swap_windows[1].allowed_adjacent_pairs == (("data0", "data1"),)
    assert bus.layer_policy.allowed_layers == ("B.Cu", "F.Cu")
    assert bus.layer_policy.via_policy.transition_window_ids == (
        "transition:a",
        "transition:b",
    )
    assert tuple(boundary.boundary_id for boundary in bus.boundaries) == ("entry", "exit")
    assert tuple(ref.member_id for ref in bus.boundaries[1].ordered_members) == (
        "data0",
        "data1",
    )


@pytest.mark.parametrize(
    ("permutation", "message"),
    (
        (
            BusPermutationPolicy(allowed_boundary_permutations=(("missing", ("data0", "data1")),)),
            "unknown boundary",
        ),
        (
            BusPermutationPolicy(allowed_boundary_permutations=(("entry", ("data0",)),)),
            "exactly the boundary's active members",
        ),
        (
            BusPermutationPolicy(
                swap_windows=(
                    BusSwapWindow(
                        window_id="swap",
                        corridor_region_id="trunk",
                        allowed_adjacent_pairs=(("data0", "missing"),),
                        allowed_layers=("F.Cu",),
                        maximum_swaps=1,
                    ),
                )
            ),
            "unknown bus member",
        ),
        (
            BusPermutationPolicy(
                swap_windows=(
                    BusSwapWindow(
                        window_id="swap",
                        corridor_region_id="trunk",
                        allowed_adjacent_pairs=(("data0", "data1"),),
                        allowed_layers=("B.Cu",),
                        maximum_swaps=1,
                    ),
                )
            ),
            "layer must be allowed",
        ),
    ),
)
def test_bus_rejects_incompatible_permutation_declarations(
    permutation: BusPermutationPolicy,
    message: str,
) -> None:
    bus = _bus()
    with pytest.raises(ValidationError, match=message):
        BusGroup.model_validate({**bus.model_dump(), "permutation_policy": permutation})


@pytest.mark.parametrize(
    "payload",
    (
        {"mode": "forbidden", "maximum_vias_per_member": 1},
        {"mode": "escape_only", "maximum_vias_per_member": 0},
        {"mode": "declared_transition_windows", "maximum_vias_per_member": 1},
        {
            "mode": "independent_bounded",
            "transition_window_ids": ("transition",),
            "maximum_vias_per_member": 1,
        },
        {
            "mode": "synchronous",
            "transition_window_ids": ("transition",),
            "maximum_vias_per_member": 1,
            "maximum_via_count_spread": 2,
        },
    ),
)
def test_via_policy_rejects_incoherent_modes_and_limits(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BusViaPolicy.model_validate(payload)


def test_layer_and_fallback_policies_reject_incoherent_declarations() -> None:
    with pytest.raises(ValidationError, match="preferred layers"):
        BusLayerPolicy(
            allowed_layers=("F.Cu",),
            preferred_layers=("B.Cu",),
            via_policy=BusViaPolicy(mode="forbidden"),
        )
    with pytest.raises(ValidationError, match="single-layer"):
        BusLayerPolicy(
            allowed_layers=("F.Cu",),
            via_policy=BusViaPolicy(
                mode="synchronous",
                transition_window_ids=("transition",),
                maximum_vias_per_member=1,
            ),
        )
    with pytest.raises(ValidationError, match="coherent positive limit"):
        BusFallbackPolicy(allow_individual_fallback=True)
    bus = _bus()
    with pytest.raises(ValidationError, match="cannot exceed"):
        BusGroup.model_validate(
            {
                **bus.model_dump(),
                "fallback_policy": BusFallbackPolicy(
                    allow_individual_fallback=True,
                    maximum_fallback_members=3,
                ),
            }
        )


def test_hard_evidence_promotion_is_canonical_and_requires_complete_applicability() -> None:
    authority = _hard_authority()
    repeated = ConstraintAuthority(
        enforcement="hard",
        evidence=tuple(reversed(authority.evidence)),
        applicability_conditions=tuple(reversed(authority.applicability_conditions)),
        validation_method_ids=tuple(reversed(authority.validation_method_ids)),
    )

    assert repeated == authority
    assert authority.applicability_conditions == (
        "interface=74HC595",
        "stackup=two-layer-v1",
    )
    assert ConstraintAuthority(enforcement="advisory").evidence == ()
    with pytest.raises(ValidationError, match="non-empty applicability"):
        ConstraintAuthority(
            enforcement="hard",
            evidence=(_verified_evidence(),),
        )
    with pytest.raises(ValidationError, match="all required conditions"):
        ConstraintAuthority(
            enforcement="hard",
            evidence=(_verified_evidence(),),
            applicability_conditions=("interface=74HC595",),
        )


@pytest.mark.parametrize(
    "evidence",
    (
        _verified_evidence().model_copy(update={"source_status": "unpinned"}),
        _verified_evidence().model_copy(update={"local_sha256": None}),
        _verified_evidence().model_copy(update={"locator_status": "unverified"}),
        _verified_evidence().model_copy(update={"applicability_status": "conditional"}),
    ),
)
def test_hard_authority_rejects_incomplete_evidence(evidence: EvidenceRef) -> None:
    with pytest.raises(ValidationError, match="hard authority requires"):
        ConstraintAuthority(
            enforcement="hard",
            evidence=(evidence,),
            applicability_conditions=("interface=74HC595", "stackup=two-layer-v1"),
        )


def test_hard_budgets_require_machine_operative_limits() -> None:
    authority = _hard_authority()
    with pytest.raises(ValidationError, match="hard timing authority"):
        BusTimingBudget(driver_rise_time_ns=3.0, authority=authority)
    with pytest.raises(ValidationError, match="hard coupling authority"):
        BusCouplingBudget(signal_swing_v=3.3, authority=authority)

    assert BusTimingBudget(maximum_length_spread_mm=1.0, authority=authority)
    assert BusCouplingBudget(adjacent_member_clearance_mm=0.3, authority=authority)
    assert BusCoherencePolicy(maximum_order_violations=0, authority=authority)


def test_certificate_handshake_ready_and_missing_states_are_fingerprinted() -> None:
    bus = _bus()
    certificate = _certificate()
    context = _context(certificate)
    ready = validate_bus_certificate(bus, certificate, context, _ownership(bus), 0.2)
    missing = validate_bus_certificate(bus, None, context, _ownership(bus), 0.2)

    assert ready.ready
    assert ready.reason is BusCertificateHandshakeReason.READY
    assert ready.certificate_fingerprint == certificate.semantic_fingerprint()
    assert ready.detail_ids == ()
    assert missing.reason is BusCertificateHandshakeReason.MISSING_CERTIFICATE
    assert not missing.ready
    assert missing.certificate_fingerprint is None
    assert (
        ready.semantic_fingerprint()
        == "cb3080a69ce2db9dff823d169a3245cea80bc9ed8173605f56ae00284483b245"
    )


@pytest.mark.parametrize(
    ("field_name", "reason"),
    (
        ("board_geometry_fingerprint", BusCertificateHandshakeReason.STALE_BOARD_GEOMETRY),
        ("static_obstacle_fingerprint", BusCertificateHandshakeReason.STALE_STATIC_OBSTACLES),
        ("rule_profile_fingerprint", BusCertificateHandshakeReason.STALE_RULE_PROFILE),
        ("demand_fingerprint", BusCertificateHandshakeReason.STALE_DEMAND),
        ("corridor_graph_fingerprint", BusCertificateHandshakeReason.STALE_CORRIDOR_GRAPH),
    ),
)
def test_certificate_handshake_rejects_each_stale_authority_input(
    field_name: str,
    reason: BusCertificateHandshakeReason,
) -> None:
    bus = _bus()
    certificate = _certificate()
    context = BusCertificateContext.model_validate(
        {**_context(certificate).model_dump(), field_name: "0" * 64}
    )

    result = validate_bus_certificate(bus, certificate, context, _ownership(bus), 0.2)

    assert not result.ready
    assert result.reason is reason
    assert result.detail_ids == ()


def test_certificate_handshake_rejects_wrong_grid_before_terminal_checks() -> None:
    bus = _bus()
    certificate = _certificate()
    context = BusCertificateContext.model_validate(
        {**_context(certificate).model_dump(), "grid_mm": 0.25}
    )

    result = validate_bus_certificate(bus, certificate, context, {}, 0.2)

    assert result.reason is BusCertificateHandshakeReason.WRONG_GRID


def test_certificate_handshake_rejects_missing_and_mismatched_terminal_ownership() -> None:
    bus = _bus()
    certificate = _certificate()
    ownership = _ownership(bus)
    ownership.pop("data0-source")
    ownership["data1-sink"] = ownership["data1-sink"].model_copy(update={"pad_number": "99"})

    result = validate_bus_certificate(bus, certificate, _context(certificate), ownership, 0.2)

    assert result.reason is BusCertificateHandshakeReason.TERMINAL_OWNERSHIP_MISMATCH
    assert result.detail_ids == ("data0-source", "data1-sink")


def test_certificate_handshake_enforces_profile_minimum_width_without_rounding() -> None:
    bus = _bus()
    certificate = _certificate()

    accepted = validate_bus_certificate(
        bus, certificate, _context(certificate), _ownership(bus), 0.2
    )
    rejected = validate_bus_certificate(
        bus,
        certificate,
        _context(certificate),
        _ownership(bus),
        0.2000000001,
    )

    assert accepted.reason is BusCertificateHandshakeReason.READY
    assert rejected.reason is BusCertificateHandshakeReason.TRACK_WIDTH_BELOW_PROFILE_MINIMUM
    assert rejected.detail_ids == ("data0", "data1")
    for minimum_width in (0.0, -0.1, math.inf, math.nan):
        with pytest.raises(ValueError, match="finite and positive"):
            validate_bus_certificate(
                bus,
                certificate,
                _context(certificate),
                _ownership(bus),
                minimum_width,
            )


def test_certificate_handshake_rejects_unbound_portals_and_windows() -> None:
    bus = _bus()
    certificate = _certificate()
    bad_boundary = bus.boundaries[0].model_copy(update={"corridor_portal_id": "missing"})
    portal_bus = BusGroup.model_validate(
        {**bus.model_dump(), "boundaries": (bad_boundary, bus.boundaries[1])}
    )
    portal_result = validate_bus_certificate(
        portal_bus,
        certificate,
        _context(certificate),
        _ownership(portal_bus),
        0.2,
    )
    assert portal_result.reason is BusCertificateHandshakeReason.CERTIFICATE_REFERENCE_MISMATCH
    assert portal_result.detail_ids == ("boundary:entry",)

    swap_policy = BusPermutationPolicy(
        swap_windows=(
            BusSwapWindow(
                window_id="swap:a",
                corridor_region_id="trunk",
                allowed_adjacent_pairs=(("data0", "data1"),),
                allowed_layers=("F.Cu",),
                maximum_swaps=1,
            ),
        )
    )
    swap_bus = BusGroup.model_validate({**bus.model_dump(), "permutation_policy": swap_policy})
    assert (
        validate_bus_certificate(
            swap_bus,
            certificate,
            _context(certificate),
            _ownership(swap_bus),
            0.2,
        ).reason
        is BusCertificateHandshakeReason.READY
    )

    transition_bus = BusGroup.model_validate(
        {
            **bus.model_dump(),
            "layer_policy": BusLayerPolicy(
                allowed_layers=("F.Cu", "B.Cu"),
                via_policy=BusViaPolicy(
                    mode="synchronous",
                    transition_window_ids=("transition:missing",),
                    maximum_vias_per_member=1,
                ),
            ),
        }
    )
    transition_result = validate_bus_certificate(
        transition_bus,
        certificate,
        _context(certificate),
        _ownership(transition_bus),
        0.2,
    )
    assert transition_result.reason is BusCertificateHandshakeReason.CERTIFICATE_REFERENCE_MISMATCH
    assert transition_result.detail_ids == ("transition-window:transition:missing",)
