from __future__ import annotations

import re
from uuid import UUID

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    mounting_hole_placements,
    parse_board_netlist,
    render_board,
    render_board_from_layout,
)

RESISTOR = "Resistor_SMD:R_0603_1608Metric"
UUID_PATTERN = re.compile(
    r'\(uuid\s+"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
    r'[0-9a-f]{4}-[0-9a-f]{12})"?\)'
)


def _uuid_values(text: str) -> list[str]:
    return UUID_PATTERN.findall(text)


def _single_resistor_netlist() -> BoardNetlist:
    return BoardNetlist(
        components=(
            BoardComponent(
                reference="R1",
                value="10k",
                footprint=RESISTOR,
                uuid_path="sheet/r1",
            ),
        ),
        nets=(),
    )


def _copper_layout(
    segments: tuple[TrackSegment, ...],
    *,
    vias: tuple[ViaSpec, ...] = (),
    zones: tuple[
        tuple[str, str, tuple[float, float, float, float]], ...
    ] = (),
) -> BoardLayout:
    return BoardLayout(
        placements=(),
        segments=segments,
        vias=vias,
        width_mm=20.0,
        height_mm=20.0,
        zones=zones,
    )


def test_mounting_hole_component_paths_are_repeatable_unique_uuid5() -> None:
    first = mounting_hole_placements(50.0, 40.0)
    second = mounting_hole_placements(50.0, 40.0)
    first_paths = [component.uuid_path for component, _x, _y in first]
    second_paths = [component.uuid_path for component, _x, _y in second]

    assert first_paths == second_paths
    assert len(first_paths) == len(set(first_paths)) == 4
    assert all(UUID(value).version == 5 for value in first_paths)


def test_missing_netlist_tstamp_gets_stable_fallback_identity() -> None:
    xml = f"""<export>
  <components>
    <comp ref="R1">
      <value>10k</value>
      <footprint>{RESISTOR}</footprint>
    </comp>
  </components>
  <nets/>
</export>"""

    first = parse_board_netlist(xml).components[0].uuid_path
    second = parse_board_netlist(xml).components[0].uuid_path

    assert first == second
    assert UUID(first).version == 5


def test_complete_board_render_is_byte_repeatable_with_unique_uuids() -> None:
    netlist = _single_resistor_netlist()

    first = render_board(netlist)
    second = render_board(netlist)
    uuids = _uuid_values(first)

    assert first == second
    assert uuids
    assert len(uuids) == len(set(uuids))
    assert all(UUID(value).version == 5 for value in uuids)


def test_duplicate_copper_items_use_stable_distinct_occurrence_ids() -> None:
    netlist = BoardNetlist(
        components=(),
        nets=(BoardNet(name="/N", nodes=()),),
    )
    forward = TrackSegment(1.0, 2.0, 8.0, 2.0, "F.Cu", "/N")
    reverse = TrackSegment(8.0, 2.0, 1.0, 2.0, "F.Cu", "/N")
    via = ViaSpec(4.0, 2.0, "/N")
    zone = ("/N", "B.Cu", (1.0, 1.0, 9.0, 9.0))
    layout = _copper_layout(
        (forward, reverse),
        vias=(via, via),
        zones=(zone, zone),
    )

    first = render_board_from_layout(netlist, layout)
    second = render_board_from_layout(netlist, layout)
    uuids = _uuid_values(first)

    assert first == second
    assert len(uuids) == 7
    assert len(uuids) == len(set(uuids))
    assert all(UUID(value).version == 5 for value in uuids)


def test_reversed_segment_endpoints_share_the_canonical_base_identity() -> None:
    netlist = BoardNetlist(
        components=(),
        nets=(BoardNet(name="/N", nodes=()),),
    )
    forward = TrackSegment(1.0, 2.0, 8.0, 2.0, "F.Cu", "/N")
    reverse = TrackSegment(8.0, 2.0, 1.0, 2.0, "F.Cu", "/N")

    forward_text = render_board_from_layout(
        netlist,
        _copper_layout((forward,)),
    )
    reverse_text = render_board_from_layout(
        netlist,
        _copper_layout((reverse,)),
    )
    forward_uuid = re.search(r"\(segment .+\(uuid ([0-9a-f-]+)\)\)", forward_text)
    reverse_uuid = re.search(r"\(segment .+\(uuid ([0-9a-f-]+)\)\)", reverse_text)

    assert forward_uuid is not None
    assert reverse_uuid is not None
    assert forward_uuid.group(1) == reverse_uuid.group(1)
