"""Reader (human) schematic — Track 9.1.

The offline connectivity validator is the netlist-equality gate that
needs no kicad-cli: it derives nets purely from the drawn wires and
compares them against the machine pin->net table. Per the project's
first law, every check is proven to FIRE by a deliberate violation.
"""

from __future__ import annotations

from pcbsmith.kicad.export_servo555_reader import (
    PIN_NETS,
    SERVO555_READER_SPEC,
)
from pcbsmith.kicad.reader_schematic import (
    ReaderFlag,
    ReaderInstance,
    ReaderSpec,
    analyze_reader_spec,
    compare_netlists,
)

RESISTOR = "Device:R"


def _two_resistor_spec(
    wires: tuple[tuple[tuple[float, float], tuple[float, float]], ...],
    labels: tuple[tuple[str, tuple[float, float]], ...],
) -> ReaderSpec:
    """R1 between VCC (top wire) and MID; R2 between MID and GND.
    Device:R pins sit at (x, y-3.81) and (x, y+3.81)."""
    return ReaderSpec(
        instances=(
            ReaderInstance("R1", RESISTOR, (50.8, 50.8)),
            ReaderInstance("R2", RESISTOR, (50.8, 76.2)),
        ),
        wires=wires,
        labels=labels,
    )


_GOOD_WIRES = (
    ((50.8, 46.99), (50.8, 40.64)),  # R1.1 up to VCC stub
    ((50.8, 54.61), (50.8, 72.39)),  # R1.2 - R2.1 = MID
    ((50.8, 80.01), (50.8, 88.9)),   # R2.2 down to GND stub
)
_GOOD_LABELS = (
    ("VCC", (50.8, 40.64)),
    ("MID", (50.8, 63.5)),
    ("GND", (50.8, 88.9)),
)
_PIN_NETS = {
    "R1": {"1": "VCC", "2": "MID"},
    "R2": {"1": "MID", "2": "GND"},
}


def test_valid_two_resistor_drawing_has_no_findings() -> None:
    connectivity = analyze_reader_spec(
        _two_resistor_spec(_GOOD_WIRES, _GOOD_LABELS), _PIN_NETS
    )
    assert connectivity.findings == ()


def test_rails_split_at_taps_and_junctions_emitted() -> None:
    # A rail with two taps must split into three segments and carry a
    # junction dot at each T (the segmented-rail lesson).
    spec = ReaderSpec(
        instances=(
            ReaderInstance("R1", RESISTOR, (50.8, 50.8)),
            ReaderInstance("R2", RESISTOR, (76.2, 50.8)),
        ),
        wires=(
            ((25.4, 25.4), (101.6, 25.4)),   # rail
            ((50.8, 46.99), (50.8, 25.4)),   # R1.1 tap
            ((76.2, 46.99), (76.2, 25.4)),   # R2.1 tap
            ((50.8, 54.61), (76.2, 54.61)),  # R1.2 - R2.2 wait: pins are
            # at (x, y+3.81) = 54.61; a single wire between them.
        ),
        labels=(("VCC", (33.02, 25.4)), ("OUT", (63.5, 54.61))),
    )
    pin_nets = {
        "R1": {"1": "VCC", "2": "OUT"},
        "R2": {"1": "VCC", "2": "OUT"},
    }
    connectivity = analyze_reader_spec(spec, pin_nets)
    assert connectivity.findings == ()
    rail_segments = [
        segment for segment in connectivity.segments if segment[0][1] == 25.4
    ]
    assert len(rail_segments) == 3
    assert (50.8, 25.4) in connectivity.junctions
    assert (76.2, 25.4) in connectivity.junctions


def test_unattached_pin_fires() -> None:
    wires = (_GOOD_WIRES[0], _GOOD_WIRES[1])  # R2.2 wire removed
    connectivity = analyze_reader_spec(
        _two_resistor_spec(wires, _GOOD_LABELS[:2]), _PIN_NETS
    )
    assert any(
        "R2 pin 2" in finding and "not attached" in finding
        for finding in connectivity.findings
    )


def test_short_between_nets_fires() -> None:
    # An extra wire tying MID to the GND stub is a drawn short.
    wires = (
        *_GOOD_WIRES,
        ((50.8, 63.5), (63.5, 63.5)),
        ((63.5, 63.5), (63.5, 88.9)),
        ((63.5, 88.9), (50.8, 88.9)),
    )
    connectivity = analyze_reader_spec(
        _two_resistor_spec(wires, _GOOD_LABELS), _PIN_NETS
    )
    assert any("short" in finding for finding in connectivity.findings)


def test_label_teleport_fires() -> None:
    # Two disconnected wire groups carrying the same label would merge
    # in KiCad - the reader schematic must refuse that.
    wires = (
        ((50.8, 46.99), (50.8, 40.64)),
        ((50.8, 54.61), (50.8, 63.5)),   # R1.2 island
        ((50.8, 72.39), (50.8, 63.51)),  # R2.1 island - ALMOST touching
        ((50.8, 80.01), (50.8, 88.9)),
    )
    labels = (
        ("VCC", (50.8, 40.64)),
        ("MID", (50.8, 58.42)),
        ("MID", (50.8, 68.58)),
        ("GND", (50.8, 88.9)),
    )
    connectivity = analyze_reader_spec(
        _two_resistor_spec(wires, labels), _PIN_NETS
    )
    assert any("teleport" in finding for finding in connectivity.findings)


def test_wrong_label_name_fires() -> None:
    labels = (
        ("VCC", (50.8, 40.64)),
        ("WRONG", (50.8, 63.5)),
        ("GND", (50.8, 88.9)),
    )
    connectivity = analyze_reader_spec(
        _two_resistor_spec(_GOOD_WIRES, labels), _PIN_NETS
    )
    assert any(
        "labelled" in finding and "WRONG" in finding
        for finding in connectivity.findings
    )


def test_unlabelled_net_fires() -> None:
    connectivity = analyze_reader_spec(
        _two_resistor_spec(_GOOD_WIRES, _GOOD_LABELS[:1] + _GOOD_LABELS[2:]),
        _PIN_NETS,
    )
    assert any("no label" in finding for finding in connectivity.findings)


def test_foreign_wire_through_attached_pin_becomes_a_short() -> None:
    # A GND-side wire routed straight through R1 pin 1's stub endpoint
    # splits there during normalization, merges the groups, and
    # surfaces as a drawn short (exactly what KiCad would do).
    wires = (
        *_GOOD_WIRES,
        ((25.4, 46.99), (76.2, 46.99)),  # passes through R1.1 tip
        ((76.2, 46.99), (76.2, 88.9)),
        ((76.2, 88.9), (50.8, 88.9)),
    )
    connectivity = analyze_reader_spec(
        _two_resistor_spec(wires, _GOOD_LABELS), _PIN_NETS
    )
    assert any("short" in finding for finding in connectivity.findings)


def test_wire_crossing_unattached_pin_tip_fires() -> None:
    # No stub on R1.1; a wire crosses its connection point mid-segment.
    # KiCad would connect them - the model flags the hazard by name.
    wires = (
        _GOOD_WIRES[1],
        _GOOD_WIRES[2],
        ((25.4, 46.99), (76.2, 46.99)),  # crosses R1.1 tip mid-segment
    )
    labels = (
        ("VCC", (25.4, 46.99)),
        ("MID", (50.8, 63.5)),
        ("GND", (50.8, 88.9)),
    )
    connectivity = analyze_reader_spec(
        _two_resistor_spec(wires, labels), _PIN_NETS
    )
    assert any(
        "crossed by a wire mid-segment" in finding
        for finding in connectivity.findings
    )


def test_diagonal_wire_fires() -> None:
    wires = (*_GOOD_WIRES, ((10.0, 10.0), (20.0, 20.0)))
    connectivity = analyze_reader_spec(
        _two_resistor_spec(wires, _GOOD_LABELS), _PIN_NETS
    )
    assert any("Diagonal" in finding for finding in connectivity.findings)


def test_missing_net_from_machine_table_fires() -> None:
    pin_nets = {
        "R1": {"1": "VCC", "2": "MID"},
        "R2": {"1": "MID", "2": "GND"},
        "R9": {"1": "VCC", "2": "EXTRA"},
    }
    connectivity = analyze_reader_spec(
        _two_resistor_spec(_GOOD_WIRES, _GOOD_LABELS), pin_nets
    )
    assert any("R9" in finding for finding in connectivity.findings)


def test_servo555_reader_spec_reproduces_the_machine_table() -> None:
    # THE Track 9.1 gate, offline: the pilot drawing derives exactly
    # the machine schematic's pin->net table from its wires.
    connectivity = analyze_reader_spec(SERVO555_READER_SPEC, PIN_NETS)
    assert connectivity.findings == ()
    # Every drawn T carries a junction dot.
    assert len(connectivity.junctions) >= 20


def test_compare_netlists_flags_partition_and_name_differences() -> None:
    from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist

    def component(reference: str) -> BoardComponent:
        return BoardComponent(
            reference=reference, value="10k", footprint="R_0603",
            uuid_path=reference, fields=(),
        )

    machine = BoardNetlist(
        components=(component("R1"), component("R2")),
        nets=(
            BoardNet(name="/A", nodes=(("R1", "1"), ("R2", "1"))),
            BoardNet(name="/B", nodes=(("R1", "2"), ("R2", "2"))),
        ),
    )
    same = BoardNetlist(
        components=(component("R1"), component("R2")),
        nets=(
            BoardNet(name="/B", nodes=(("R2", "2"), ("R1", "2"))),
            BoardNet(name="/A", nodes=(("R1", "1"), ("R2", "1"))),
        ),
    )
    assert compare_netlists(machine, same) == ()

    swapped = BoardNetlist(
        components=(component("R1"), component("R2")),
        nets=(
            BoardNet(name="/A", nodes=(("R1", "1"), ("R2", "2"))),
            BoardNet(name="/B", nodes=(("R1", "2"), ("R2", "1"))),
        ),
    )
    findings = compare_netlists(machine, swapped)
    assert any("/A" in finding for finding in findings)

    renamed = BoardNetlist(
        components=(component("R1"), component("R2")),
        nets=(
            BoardNet(name="/A2", nodes=(("R1", "1"), ("R2", "1"))),
            BoardNet(name="/B", nodes=(("R1", "2"), ("R2", "2"))),
        ),
    )
    findings = compare_netlists(machine, renamed)
    assert any("only in the machine" in finding for finding in findings)
    assert any("only in the reader" in finding for finding in findings)


def test_reader_flag_reaches_its_net() -> None:
    spec = ReaderSpec(
        instances=(ReaderInstance("R1", RESISTOR, (50.8, 50.8)),),
        wires=(
            ((50.8, 46.99), (50.8, 40.64)),
            ((50.8, 54.61), (50.8, 63.5)),
            ((45.72, 40.64), (50.8, 40.64)),
        ),
        labels=(("VCC", (50.8, 40.64)), ("OUT", (50.8, 63.5))),
        flags=(ReaderFlag("#FLG01", (45.72, 40.64), "OUT"),),
    )
    connectivity = analyze_reader_spec(spec, {"R1": {"1": "VCC", "2": "OUT"}})
    assert any(
        "#FLG01" in finding and "expected OUT" in finding
        for finding in connectivity.findings
    )
