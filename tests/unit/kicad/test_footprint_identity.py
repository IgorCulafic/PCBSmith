from __future__ import annotations

import re
from uuid import UUID

import pytest

from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import (
    QuotedString,
    load_footprint,
    parse_sexpr,
    render_embedded_footprint,
)

QFN = "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm"
TO263 = "Package_TO_SOT_SMD:TO-263-5_TabPin3"


def _render(
    library_id: str,
    *,
    reference: str = "U1",
    uuid_path: str = "schematic/u1",
) -> str:
    return render_embedded_footprint(
        load_footprint(library_id),
        reference=reference,
        value="test",
        x_mm=25.4,
        y_mm=30.48,
        rotation=0,
        uuid_path=uuid_path,
        pad_nets={},
        extra_fields=(("Source", "fixture"),),
        extra_silk_texts=(("mark", 0.0, 0.0, 0.0),),
    )


def _uuid_values(text: str) -> list[str]:
    return re.findall(r'\(uuid "([0-9a-f-]+)"\)', text)


def _head(node: object) -> str | None:
    if not isinstance(node, list) or not node:
        return None
    head = node[0]
    if isinstance(head, QuotedString):
        return head.value
    return head if isinstance(head, str) else None


def _direct_nodes(text: str, head: str) -> list[list[object]]:
    tree = parse_sexpr(text)
    return [
        node
        for node in tree[1:]
        if isinstance(node, list) and _head(node) == head
    ]


def test_stable_kicad_uuid_is_boundary_safe_uuid5() -> None:
    value = stable_kicad_uuid("ab", "c")

    assert value == stable_kicad_uuid("ab", "c")
    assert value == "948e1fd2-326d-5575-bec3-65b8b1bbc706"
    assert value != stable_kicad_uuid("a", "bc")
    assert UUID(value).version == 5


def test_stable_kicad_uuid_rejects_missing_or_non_string_identity() -> None:
    with pytest.raises(ValueError, match="at least one"):
        stable_kicad_uuid()
    with pytest.raises(TypeError, match="must be strings"):
        stable_kicad_uuid("pad", 1)  # type: ignore[arg-type]


def test_modern_footprint_render_is_repeatable_and_unique() -> None:
    first = _render(QFN)
    second = _render(QFN)
    uuids = _uuid_values(first)

    assert first == second
    assert len(uuids) > 40
    assert len(uuids) == len(set(uuids))
    path_match = re.search(r'\(path "(/[0-9a-f/-]+)"\)', first)
    assert path_match is not None
    assert all(UUID(atom).version == 5 for atom in path_match.group(1).strip("/").split("/"))


def test_real_schematic_uuid_path_is_preserved_exactly() -> None:
    path = (
        "d6a68031-796c-5475-9145-a56144a4d2c7/"
        "84cb3350-b4c7-576f-9d3a-68b01162c3ae"
    )

    rendered = _render(QFN, uuid_path=path)

    assert f'(path "/{path}")' in rendered


def test_two_instances_rebase_all_source_uuids_into_disjoint_sets() -> None:
    first = set(
        _uuid_values(_render(QFN, reference="U1", uuid_path="sheet/u1"))
    )
    second = set(
        _uuid_values(_render(QFN, reference="U2", uuid_path="sheet/u2"))
    )

    assert first
    assert second
    assert first.isdisjoint(second)


@pytest.mark.parametrize("library_id", (QFN, TO263))
def test_every_pad_has_exactly_one_uuid_and_no_legacy_tstamp(
    library_id: str,
) -> None:
    pads = _direct_nodes(_render(library_id), "pad")

    assert pads
    for pad in pads:
        assert sum(_head(child) == "uuid" for child in pad) == 1
        assert all(_head(child) != "tstamp" for child in pad)


def test_duplicate_numbered_and_unnamed_pads_receive_distinct_uuids() -> None:
    pads = _direct_nodes(_render(TO263), "pad")
    groups: dict[str, list[str]] = {}
    for pad in pads:
        name_node = pad[1]
        name = name_node.value if isinstance(name_node, QuotedString) else str(name_node)
        uuid_node = next(child for child in pad if _head(child) == "uuid")
        uuid_atom = uuid_node[1]
        assert isinstance(uuid_atom, QuotedString)
        groups.setdefault(name, []).append(uuid_atom.value)

    assert len(groups[""]) == 4
    assert len(groups["3"]) == 2
    assert len(groups[""]) == len(set(groups[""]))
    assert len(groups["3"]) == len(set(groups["3"]))
