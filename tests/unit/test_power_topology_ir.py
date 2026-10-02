from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.power_topology_ir import (
    BoardPowerTopology,
    CopperRegionDeclaration,
    CopperTopologyRole,
    ElectricalRegionClass,
    IntentionalCopperIsland,
    IslandPolicy,
    NeckdownAllowance,
    OperatingScenarioCurrent,
    PowerPathDeclaration,
    PowerTerminal,
    PowerTerminalRole,
    SignalReturnRelationship,
    TopologyClaimDisposition,
    ZonePadConnection,
    ZonePadConnectionIntent,
    assess_power_topology,
)


def _terminal(identity: str, role: PowerTerminalRole) -> PowerTerminal:
    return PowerTerminal(
        terminal_id=identity,
        component_reference=identity.split(":", 1)[0],
        pad_number=identity.split(":", 1)[1],
        role=role,
    )


def _region(
    *,
    role: CopperTopologyRole = CopperTopologyRole.REFERENCE_POUR,
    connections: tuple[ZonePadConnectionIntent, ...] = (),
) -> CopperRegionDeclaration:
    return CopperRegionDeclaration(
        region_id="gnd-region",
        net_name="GND",
        role=role,
        electrical_class=ElectricalRegionClass.HIGH_CURRENT,
        allowed_layers=("B.Cu",),
        pad_connections=connections,
        island_policy=IslandPolicy.REMOVE_UNREACHABLE,
    )


def _path(
    *,
    current_complete: bool = True,
    neckdowns: tuple[NeckdownAllowance, ...] = (),
) -> PowerPathDeclaration:
    return PowerPathDeclaration(
        path_id="return-path",
        net_name="GND",
        source_terminal_id="J1:2",
        sink_terminal_ids=("U1:8",),
        current_scenarios=(
            OperatingScenarioCurrent(
                scenario_id="maximum-load",
                expected_current_a=0.5 if current_complete else None,
                maximum_current_a=1.0 if current_complete else None,
            ),
        ),
        region_ids=("gnd-region",),
        allowed_layers=("B.Cu",),
        neckdowns=neckdowns,
        requires_ampacity_claim=True,
    )


def _topology(
    *,
    region: CopperRegionDeclaration | None = None,
    path: PowerPathDeclaration | None = None,
    with_return: bool = True,
) -> BoardPowerTopology:
    relationships = (
        SignalReturnRelationship(
            relationship_id="spi-return",
            signal_group_id="spi",
            signal_net_names=("SCLK", "MOSI"),
            reference_region_id="gnd-region",
            required_relation="adjacent_continuous",
        ),
    ) if with_return else ()
    return BoardPowerTopology.build(
        topology_id="fixture-topology",
        board_sha256="a" * 64,
        fabrication_profile_sha256="b" * 64,
        terminals=(
            _terminal("J1:2", PowerTerminalRole.SOURCE),
            _terminal("U1:8", PowerTerminalRole.SINK),
        ),
        regions=(region or _region(),),
        paths=(path or _path(),),
        return_relationships=relationships,
    )


def test_gnd_zone_without_reference_role_cannot_satisfy_return_continuity() -> None:
    with pytest.raises(ValidationError, match="reference-pour role"):
        _topology(region=_region(role=CopperTopologyRole.LOCAL_POUR))


def test_high_current_thermal_spoke_requires_declared_neckdown() -> None:
    thermal = ZonePadConnectionIntent(
        pad_id="U1:8",
        connection=ZonePadConnection.THERMAL,
        neckdown_id="u1-gnd-thermal",
    )
    with pytest.raises(ValidationError, match="undeclared thermal-spoke"):
        _topology(region=_region(connections=(thermal,)))

    declared = NeckdownAllowance(
        neckdown_id="u1-gnd-thermal",
        pad_ids=("U1:8",),
        minimum_width_mm=0.4,
        maximum_length_mm=1.0,
        rationale_authority_id="u1-pad-escape",
    )
    topology = _topology(
        region=_region(connections=(thermal,)),
        path=_path(neckdowns=(declared,)),
    )
    assert topology.paths[0].neckdowns == (declared,)


def test_isolated_shield_island_requires_explicit_source_authority() -> None:
    with pytest.raises(ValidationError):
        IntentionalCopperIsland(
            island_id="shield-tab",
            source_authority_sha256="",
            rationale="connector shield coupling",
        )

    island = IntentionalCopperIsland(
        island_id="shield-tab",
        source_authority_sha256="c" * 64,
        rationale="connector shield coupling",
    )
    region = CopperRegionDeclaration(
        region_id="shield",
        net_name="SHIELD",
        role=CopperTopologyRole.CHASSIS_OR_SHIELD,
        electrical_class=ElectricalRegionClass.NOISY,
        allowed_layers=("F.Cu",),
        island_policy=IslandPolicy.KEEP_DECLARED_ONLY,
        intentional_islands=(island,),
    )
    assert region.intentional_islands == (island,)


def test_missing_current_semantics_blocks_ampacity_claim_not_topology_use() -> None:
    topology = _topology(path=_path(current_complete=False))
    assessment = assess_power_topology(topology)

    assert assessment.ampacity_claim is TopologyClaimDisposition.UNVERIFIED
    assert assessment.return_continuity_claim is (
        TopologyClaimDisposition.READY_FOR_GEOMETRY_EVALUATION
    )
    assert "current semantics are incomplete" in assessment.blockers[0]
