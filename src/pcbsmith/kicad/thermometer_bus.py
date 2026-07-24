"""Ordered routing declarations for the full thermometer display board."""

from __future__ import annotations

from pcbsmith.bus_ir import (
    BoundaryMemberRef,
    BusBoundary,
    BusGroup,
    BusLayerPolicy,
    BusMember,
    BusPermutationPolicy,
    BusTerminalRef,
    BusViaPolicy,
)
from pcbsmith.kicad.board import BoardGenerationError, BoardNetlist

_SEGMENT_SOURCE_PADS = (
    "15", "1", "2", "3", "4", "5", "6", "7",
    "15", "1", "2", "3", "4", "5", "6", "7",
)


def _two_terminal_bus(
    *,
    bus_id: str,
    prefix: str,
    source_refs: tuple[str, ...],
    source_pads: tuple[str, ...],
    sink_refs: tuple[str, ...],
    sink_pad: str,
    preferred_layer: str,
) -> BusGroup:
    members: list[BusMember] = []
    for index, (source_ref, source_pad, sink_ref) in enumerate(
        zip(source_refs, source_pads, sink_refs, strict=True), start=1
    ):
        member_id = f"{prefix.lower()}-{index:02d}"
        net_name = f"/{prefix}{index}"
        members.append(
            BusMember(
                member_id=member_id,
                net_name=net_name,
                terminals=(
                    BusTerminalRef(
                        terminal_id=f"{member_id}-source",
                        net_name=net_name,
                        component_ref=source_ref,
                        pad_number=source_pad,
                        role="source",
                    ),
                    BusTerminalRef(
                        terminal_id=f"{member_id}-sink",
                        net_name=net_name,
                        component_ref=sink_ref,
                        pad_number=sink_pad,
                        role="sink",
                    ),
                ),
                width_mm=0.2,
            )
        )
    source_order = tuple(
        BoundaryMemberRef(
            member_id=member.member_id,
            terminal_ids=(f"{member.member_id}-source",),
        )
        for member in members
    )
    sink_order = tuple(
        BoundaryMemberRef(
            member_id=member.member_id,
            terminal_ids=(f"{member.member_id}-sink",),
        )
        for member in members
    )
    return BusGroup(
        bus_id=bus_id,
        members=tuple(members),
        boundaries=(
            BusBoundary(
                boundary_id=f"{bus_id}-source",
                corridor_portal_id=f"{bus_id}-source-portal",
                orientation="forward",
                ordered_members=source_order,
            ),
            BusBoundary(
                boundary_id=f"{bus_id}-sink",
                corridor_portal_id=f"{bus_id}-sink-portal",
                orientation="forward",
                ordered_members=sink_order,
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            preferred_layers=(preferred_layer,),
            via_policy=BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=4,
                maximum_via_count_spread=4,
            ),
        ),
        rule_profile_id="thermometer-default-2-layer",
    )


def thermometer_bus_groups() -> tuple[BusGroup, ...]:
    """Return deterministic SEG/LK ordering and shift-control semantics."""
    segment_sources = tuple("U2" if index <= 8 else "U3" for index in range(1, 17))
    segment = _two_terminal_bus(
        bus_id="thermometer-segment-drive",
        prefix="SEG",
        source_refs=segment_sources,
        source_pads=_SEGMENT_SOURCE_PADS,
        sink_refs=tuple(f"R{index}" for index in range(1, 17)),
        sink_pad="1",
        preferred_layer="B.Cu",
    )
    led = _two_terminal_bus(
        bus_id="thermometer-led-column",
        prefix="LK",
        source_refs=tuple(f"R{index}" for index in range(1, 17)),
        source_pads=("2",) * 16,
        sink_refs=tuple(f"D{index}" for index in range(1, 17)),
        sink_pad="2",
        preferred_layer="F.Cu",
    )

    control_spec = (
        ("ser", "/SER", "10", (("U2", "14"),)),
        ("srclk", "/SRCLK", "18", (("U2", "11"), ("U3", "11"))),
        ("rclk", "/RCLK", "17", (("U2", "12"), ("U3", "12"))),
        ("oe", "/OE", "15", (("U2", "13"), ("U3", "13"), ("ROE1", "2"))),
    )
    control_members: list[BusMember] = []
    for member_id, net_name, source_pad, sinks in control_spec:
        terminals = [
            BusTerminalRef(
                terminal_id=f"control-{member_id}-source",
                net_name=net_name,
                component_ref="U1",
                pad_number=source_pad,
                role="source",
            )
        ]
        terminals.extend(
            BusTerminalRef(
                terminal_id=f"control-{member_id}-sink-{index}",
                net_name=net_name,
                component_ref=reference,
                pad_number=pad,
                role="sink" if reference.startswith("U") else "tap",
            )
            for index, (reference, pad) in enumerate(sinks, start=1)
        )
        control_members.append(
            BusMember(
                member_id=f"control-{member_id}",
                net_name=net_name,
                terminals=tuple(terminals),
                width_mm=0.2,
            )
        )
    source_refs = tuple(
        BoundaryMemberRef(
            member_id=member.member_id,
            terminal_ids=(f"{member.member_id}-source",),
        )
        for member in control_members
    )
    sink_refs = tuple(
        BoundaryMemberRef(
            member_id=member.member_id,
            terminal_ids=tuple(
                terminal.terminal_id
                for terminal in member.terminals
                if terminal.role != "source"
            ),
        )
        for member in control_members
    )
    control = BusGroup(
        bus_id="thermometer-shift-control",
        members=tuple(control_members),
        boundaries=(
            BusBoundary(
                boundary_id="thermometer-control-source",
                corridor_portal_id="thermometer-control-module-portal",
                orientation="forward",
                ordered_members=source_refs,
            ),
            BusBoundary(
                boundary_id="thermometer-control-sinks",
                corridor_portal_id="thermometer-control-register-portal",
                orientation="forward",
                ordered_members=sink_refs,
            ),
        ),
        permutation_policy=BusPermutationPolicy(),
        layer_policy=BusLayerPolicy(
            allowed_layers=("F.Cu", "B.Cu"),
            preferred_layers=("B.Cu",),
            via_policy=BusViaPolicy(
                mode="independent_bounded",
                maximum_vias_per_member=4,
                maximum_via_count_spread=4,
            ),
        ),
        rule_profile_id="thermometer-default-2-layer",
    )
    return segment, led, control


def validate_thermometer_bus_groups(netlist: BoardNetlist) -> tuple[BusGroup, ...]:
    """Fail closed when semantic bus terminals drift from the live netlist."""
    live = {net.name: set(net.nodes) for net in netlist.nets}
    groups = thermometer_bus_groups()
    for group in groups:
        for member in group.members:
            actual = live.get(member.net_name)
            expected = {
                (terminal.component_ref, terminal.pad_number)
                for terminal in member.terminals
            }
            if actual != expected:
                raise BoardGenerationError(
                    f"{group.bus_id} member {member.net_name} terminal drift: "
                    f"expected {sorted(expected)}, found {sorted(actual or set())}"
                )
    return groups
