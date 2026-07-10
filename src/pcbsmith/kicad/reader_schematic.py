"""Human-readable ("reader") schematic rendering — Track 9.1.

The row/label-net schematic stays the MACHINE artifact: trivially
generatable, the ERC/parity substrate. This module renders the second,
conventionally drawn schematic for people: VCC rail along the top, GND
along the bottom, signal flow left to right, real drawn wires with
junction dots instead of net-label teleports.

Two drawings, one truth: a reader spec is validated OFFLINE against the
same pin->net table that drives the machine schematic. The validator
derives connectivity purely from the drawn wires (KiCad semantics as
this project has measured them: wires connect at shared ENDPOINTS, so
rails are split at every tap and junction dots emitted; interior-
interior crossings do not connect) and asserts the resulting net
partition AND net names equal the machine table. A label that appears
on two disconnected wire groups is rejected — labels here only NAME
nets, they never carry connectivity. The live gate on top of this is
kicad-cli ERC plus netlist-export equality (``compare_netlists``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import uuid4

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.board import BoardNetlist
from pcbsmith.kicad.export_divider_highpass_led import (
    KICAD_SCHEMATIC_VERSION,
    _format_mm,
    _label,
    _symbol,
)
from pcbsmith.kicad.symbols import (
    _QUARTER_TURNS,
    instance_pin_position_rotated,
    load_symbol,
    render_symbol_for_schematic,
)

Point = tuple[float, float]
Segment = tuple[Point, Point]
PinNets = Mapping[str, Mapping[str, str]]

PWR_FLAG_LIB = "power:PWR_FLAG"


class ReaderSchematicError(ValueError):
    """The drawn schematic does not reproduce the machine connectivity."""


@dataclass(frozen=True)
class ReaderInstance:
    """One placed symbol. Rotation is the KiCad instance angle
    (quarter turns); pin positions come from the measured symbol.
    ``reference_at``/``value_at`` are absolute sheet positions for the
    text fields — a readable drawing places them clear of wires."""

    reference: str
    lib_id: str
    at: Point
    rotation: int = 0
    in_bom: bool = True
    reference_at: Point | None = None
    value_at: Point | None = None


@dataclass(frozen=True)
class ReaderFlag:
    """A PWR_FLAG instance for ERC power sourcing; ``net`` is the net
    the flag's wire is expected to reach (validated)."""

    reference: str
    at: Point
    net: str


@dataclass(frozen=True)
class CustomReaderSymbol:
    """A PCBSmith custom symbol (not loadable via load_symbol): pin
    connection points in symbol coordinates (y UP, like .kicad_sym)
    plus the ready-made lib_symbols entry text."""

    lib_id: str
    pins: tuple[tuple[str, float, float], ...]  # (number, x_mm, y_mm-up)
    library_entry: str


@dataclass(frozen=True)
class ReaderSpec:
    instances: tuple[ReaderInstance, ...]
    wires: tuple[Segment, ...]
    labels: tuple[tuple[str, Point], ...]
    flags: tuple[ReaderFlag, ...] = ()
    customs: tuple[CustomReaderSymbol, ...] = ()
    # (reference, pin) pairs drawn with a no-connect cross - pins the
    # design intentionally leaves open (ERC pin_not_connected).
    no_connects: tuple[tuple[str, str], ...] = ()
    paper: str = "A3"

    def custom(self, lib_id: str) -> CustomReaderSymbol | None:
        for entry in self.customs:
            if entry.lib_id == lib_id:
                return entry
        return None


@dataclass(frozen=True)
class ReaderConnectivity:
    segments: tuple[Segment, ...]
    junctions: tuple[Point, ...]
    findings: tuple[str, ...]
    no_connect_points: tuple[Point, ...] = ()


def _pt(point: Point) -> Point:
    return (round(point[0], 2), round(point[1], 2))


def _on_segment(point: Point, segment: Segment) -> bool:
    (ax, ay), (bx, by) = segment
    px, py = point
    if ax == bx:
        return px == ax and min(ay, by) <= py <= max(ay, by)
    return py == ay and min(ax, bx) <= px <= max(ax, bx)


def _interior(point: Point, segment: Segment) -> bool:
    return _on_segment(point, segment) and point != segment[0] and point != segment[1]


def _normalize_segments(
    wires: tuple[Segment, ...],
) -> tuple[tuple[Segment, ...], tuple[str, ...]]:
    """Split every wire at any other wire endpoint that lies in its
    interior (KiCad connectivity needs shared endpoints — the segmented-
    rail lesson from the ladder builder). Returns findings for
    non-orthogonal wires and collinear overlaps, which make drawn
    connectivity ambiguous."""
    findings: list[str] = []
    segments: list[Segment] = []
    for start, end in wires:
        start, end = _pt(start), _pt(end)
        if start == end:
            findings.append(f"Zero-length wire at {start}.")
            continue
        if start[0] != end[0] and start[1] != end[1]:
            findings.append(f"Diagonal wire {start}-{end}; wires must be orthogonal.")
            continue
        segments.append((start, end))

    changed = True
    while changed:
        changed = False
        endpoints = {point for segment in segments for point in segment}
        split: list[Segment] = []
        for segment in segments:
            cuts = sorted(
                (point for point in endpoints if _interior(point, segment)),
                key=lambda point: (
                    abs(point[0] - segment[0][0]),
                    abs(point[1] - segment[0][1]),
                ),
            )
            if cuts:
                changed = True
                points = [segment[0], *cuts, segment[1]]
                split.extend(
                    (points[index], points[index + 1])
                    for index in range(len(points) - 1)
                )
            else:
                split.append(segment)
        segments = split

    for index, first in enumerate(segments):
        for second in segments[index + 1 :]:
            # After splitting, distinct collinear segments may only touch
            # at endpoints; sharing an interior means duplicated copper.
            if _interior(first[0], second) or _interior(first[1], second) or (
                first == second or first == (second[1], second[0])
            ):
                findings.append(f"Overlapping wires near {first[0]}-{first[1]}.")
    return tuple(segments), tuple(findings)


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, first: int, second: int) -> None:
        self.parent[self.find(first)] = self.find(second)


def analyze_reader_spec(
    spec: ReaderSpec, pin_nets: PinNets
) -> ReaderConnectivity:
    """Derive connectivity from the drawn wires alone and compare it
    against the machine pin->net table. Empty findings == the two
    schematics are one truth (names and partition both)."""
    segments, findings_list = _normalize_segments(spec.wires)
    findings = list(findings_list)

    by_endpoint: dict[Point, list[int]] = defaultdict(list)
    for index, segment in enumerate(segments):
        by_endpoint[segment[0]].append(index)
        by_endpoint[segment[1]].append(index)

    junctions = tuple(
        sorted(
            point
            for point, touching in by_endpoint.items()
            if len(touching) >= 3
        )
    )

    union = _UnionFind(len(segments))
    for touching in by_endpoint.values():
        for other in touching[1:]:
            union.union(touching[0], other)

    def component_of(point: Point) -> int | None:
        touching = by_endpoint.get(point)
        if not touching:
            return None
        return union.find(touching[0])

    # Pins: every pin named by the machine table must sit at a wire
    # endpoint; touching a foreign wire anywhere is a drawn short.
    def pin_tip(instance: ReaderInstance, pin_number: str) -> Point:
        custom = spec.custom(instance.lib_id)
        if custom is not None:
            pin_map = {number: (x, y) for number, x, y in custom.pins}
            px, py = pin_map[pin_number]
            turn = instance.rotation % 360
            if turn not in _QUARTER_TURNS:
                raise ValueError(
                    f"Symbol instance rotation must be a quarter turn "
                    f"(0/90/180/270), got {instance.rotation}"
                )
            cos_r, sin_r = _QUARTER_TURNS[turn]
            return _pt((
                instance.at[0] + px * cos_r - py * sin_r,
                instance.at[1] - (px * sin_r + py * cos_r),
            ))
        return _pt(
            instance_pin_position_rotated(
                load_symbol(instance.lib_id), pin_number,
                instance.at, instance.rotation,
            )
        )

    pin_component: dict[tuple[str, str], int] = {}
    known_references = {instance.reference for instance in spec.instances}
    for instance in spec.instances:
        if instance.reference not in pin_nets:
            findings.append(
                f"{instance.reference} has no pin->net table entry."
            )
            continue
        for pin_number in pin_nets[instance.reference]:
            # Geometry failures (a pin number absent from the symbol or
            # its customs entry, a non-quarter-turn rotation) become
            # findings for the specific ref/pin: this function REPORTS,
            # it does not crash.
            try:
                tip = pin_tip(instance, pin_number)
            except KeyError:
                findings.append(
                    f"{instance.reference} pin {pin_number} does not "
                    f"exist on symbol {instance.lib_id}."
                )
                continue
            except ValueError as exc:
                findings.append(
                    f"{instance.reference} pin {pin_number}: {exc}."
                )
                continue
            component = component_of(tip)
            if component is None:
                # A wire crossing the tip mid-segment WOULD connect in
                # KiCad; the reader model only accepts endpoint contact,
                # so name the hazard precisely.
                if any(_interior(tip, segment) for segment in segments):
                    findings.append(
                        f"{instance.reference} pin {pin_number} at {tip} "
                        "is crossed by a wire mid-segment; KiCad would "
                        "connect them, the reader model does not — end a "
                        "wire on the pin instead."
                    )
                else:
                    findings.append(
                        f"{instance.reference} pin {pin_number} at {tip} "
                        "is not attached to any wire endpoint."
                    )
                continue
            pin_component[(instance.reference, pin_number)] = component
    for reference in sorted(pin_nets.keys() - known_references):
        findings.append(f"{reference} is in the pin->net table but not drawn.")

    flag_component: dict[str, int] = {}
    for flag in spec.flags:
        tip = _pt(flag.at)
        component = component_of(tip)
        if component is None:
            findings.append(
                f"Power flag {flag.reference} at {tip} is not attached to "
                "any wire endpoint."
            )
            continue
        flag_component[flag.reference] = component

    # NOTE: a foreign wire touching an ATTACHED pin's point is not a
    # separate case — normalization splits any segment at that point
    # (it holds the stub's endpoint), the groups merge, and the contact
    # surfaces as a short finding below.

    # Labels attach anywhere along a wire (measured: the ladder rails'
    # mid-segment labels pass ERC and export).
    component_labels: dict[int, set[str]] = defaultdict(set)
    label_components: dict[str, set[int]] = defaultdict(set)
    for name, point in spec.labels:
        point = _pt(point)
        touched = {
            union.find(index)
            for index, segment in enumerate(segments)
            if _on_segment(point, segment)
        }
        if not touched:
            findings.append(f"Label {name} at {point} is not on any wire.")
            continue
        if len(touched) > 1:
            findings.append(
                f"Label {name} at {point} sits on a crossing of two nets."
            )
            continue
        component = touched.pop()
        component_labels[component].add(name)
        label_components[name].add(component)

    # One label name on two disconnected groups would silently merge
    # them in KiCad — the exact teleport this artifact must not use.
    for name, components in sorted(label_components.items()):
        if len(components) > 1:
            findings.append(
                f"Label {name} appears on {len(components)} disconnected "
                "wire groups; the reader schematic must connect them with "
                "drawn wires, not label teleports."
            )

    # Net derivation: each pin's component must carry exactly the
    # machine table's net name.
    component_pins: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for key, component in pin_component.items():
        component_pins[component].append(key)
    for component, pins in sorted(component_pins.items()):
        labels = component_labels.get(component, set())
        expected = {
            pin_nets[reference][pin_number] for reference, pin_number in pins
        }
        if len(expected) > 1:
            members = ", ".join(
                f"{reference}.{pin_number}"
                for reference, pin_number in sorted(pins)
            )
            findings.append(
                f"Drawn wires short nets {sorted(expected)} together "
                f"(pins {members})."
            )
            continue
        expected_name = expected.pop()
        if not labels:
            findings.append(
                f"Net {expected_name} has no label on its drawn wires; "
                "kicad-cli would auto-name it and netlist equality breaks."
            )
        elif labels != {expected_name}:
            findings.append(
                f"Net {expected_name} is labelled {sorted(labels)} instead."
            )
    for flag in spec.flags:
        component = flag_component.get(flag.reference)
        if component is None:
            continue
        labels = component_labels.get(component, set())
        if labels != {flag.net}:
            findings.append(
                f"Power flag {flag.reference} reaches net "
                f"{sorted(labels) or 'unnamed'}, expected {flag.net}."
            )

    # No-connects: a cross on a pin the machine table also leaves
    # unnetted; a wired or netted pin under a cross is a contradiction.
    no_connect_points: list[Point] = []
    for reference, pin_number in spec.no_connects:
        nc_instance = next(
            (one for one in spec.instances if one.reference == reference),
            None,
        )
        if nc_instance is None:
            findings.append(
                f"No-connect for {reference}.{pin_number}: no such symbol."
            )
            continue
        if pin_number in pin_nets.get(reference, {}):
            findings.append(
                f"No-connect on {reference}.{pin_number}, but the machine "
                f"table nets it to {pin_nets[reference][pin_number]}."
            )
            continue
        try:
            tip = pin_tip(nc_instance, pin_number)
        except (KeyError, ValueError):
            findings.append(
                f"No-connect for {reference}.{pin_number}: pin not on "
                f"symbol {instance.lib_id}."
            )
            continue
        if component_of(tip) is not None or any(
            _interior(tip, segment) for segment in segments
        ):
            findings.append(
                f"No-connect pin {reference}.{pin_number} at {tip} "
                "touches a wire."
            )
            continue
        no_connect_points.append(tip)

    # Completeness: every net in the machine table must be drawn.
    expected_nets = {
        net for pins in pin_nets.values() for net in pins.values()
    }
    drawn_nets = {
        name for name, components in label_components.items() if components
    }
    for net in sorted(expected_nets - drawn_nets):
        findings.append(f"Net {net} from the machine table is not drawn.")

    return ReaderConnectivity(
        segments=segments,
        junctions=junctions,
        findings=tuple(findings),
        no_connect_points=tuple(no_connect_points),
    )


def _wire_sexpr(segment: Segment) -> str:
    (ax, ay), (bx, by) = segment
    return f"""  (wire
    (pts
      (xy {_format_mm(ax)} {_format_mm(ay)})
      (xy {_format_mm(bx)} {_format_mm(by)})
    )
    (stroke
      (width 0)
      (type solid)
    )
    (uuid "{uuid4()}")
  )"""


def _no_connect_sexpr(point: Point) -> str:
    return f"""  (no_connect
    (at {point[0]:g} {point[1]:g})
    (uuid {uuid4()})
  )"""


def _junction_sexpr(point: Point) -> str:
    return f"""  (junction
    (at {_format_mm(point[0])} {_format_mm(point[1])})
    (diameter 0)
    (color 0 0 0 0)
    (uuid "{uuid4()}")
  )"""


def render_reader_schematic(
    circuit: CircuitObject,
    spec: ReaderSpec,
    *,
    project_name: str,
    pin_nets: PinNets,
) -> str:
    """Render the human schematic, refusing to emit a drawing whose
    wire connectivity differs from the machine pin->net table."""
    connectivity = analyze_reader_spec(spec, pin_nets)
    if connectivity.findings:
        raise ReaderSchematicError(
            "Reader schematic does not reproduce the machine netlist:\n- "
            + "\n- ".join(connectivity.findings)
        )

    fields = {
        component.reference: (component.value, component.footprint or "")
        for component in circuit.components
    }
    missing = [
        instance.reference
        for instance in spec.instances
        if instance.reference not in fields
    ]
    if missing:
        raise ReaderSchematicError(
            "Reader schematic references unknown components: "
            + ", ".join(missing)
        )

    symbols: list[str] = []
    for instance in spec.instances:
        value, footprint = fields[instance.reference]
        custom = spec.custom(instance.lib_id)
        if custom is not None:
            pin_count = len(custom.pins)
            pin_numbers: tuple[str, ...] | None = tuple(
                number for number, _x, _y in custom.pins
            )
        else:
            pin_count = len(load_symbol(instance.lib_id).pins)
            pin_numbers = None
        symbols.append(
            _symbol(
                instance.lib_id,
                instance.reference,
                value,
                instance.at[0],
                instance.at[1],
                project_name,
                rotation=instance.rotation,
                exclude_from_sim=True,
                footprint=footprint,
                pin_count=pin_count,
                pin_numbers=pin_numbers,
                in_bom=instance.in_bom,
                reference_at=instance.reference_at,
                value_at=instance.value_at,
            )
        )
    for flag in spec.flags:
        symbols.append(
            _symbol(
                PWR_FLAG_LIB,
                flag.reference,
                "PWR_FLAG",
                flag.at[0],
                flag.at[1],
                project_name,
                exclude_from_sim=True,
                footprint="",
                pin_count=1,
                in_bom=False,
                on_board=False,
                # Default value placement (anchor+2.54) lands exactly on
                # the rail the flag taps; park it beside the glyph.
                value_at=(flag.at[0] - 6.35, flag.at[1] - 1.27),
            )
        )

    wires = [_wire_sexpr(segment) for segment in connectivity.segments]
    junctions = [_junction_sexpr(point) for point in connectivity.junctions]
    no_connects = [
        _no_connect_sexpr(point)
        for point in connectivity.no_connect_points
    ]
    labels = [_label(name, *point) for name, point in spec.labels]

    custom_lib_ids = {entry.lib_id for entry in spec.customs}
    lib_ids = sorted(
        ({instance.lib_id for instance in spec.instances} - custom_lib_ids)
        | ({PWR_FLAG_LIB} if spec.flags else set())
    )
    lib_symbols = "\n".join((
        *(
            render_symbol_for_schematic(load_symbol(lib_id))
            for lib_id in lib_ids
        ),
        *(entry.library_entry for entry in spec.customs),
    ))
    items = "\n".join(
        (*symbols, *wires, *junctions, *no_connects, *labels)
    )
    return f"""(kicad_sch
  (version {KICAD_SCHEMATIC_VERSION})
  (generator "PCBSmith")
  (generator_version "0.1")
  (uuid {uuid4()})
  (paper "{spec.paper}")

  (lib_symbols
{lib_symbols}
  )
{items}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def compare_netlists(
    machine: BoardNetlist, reader: BoardNetlist
) -> tuple[str, ...]:
    """Netlist-equality gate between the machine and reader schematics
    as kicad-cli exported them: same components (footprint and value)
    and the same named net -> (ref, pin) partition."""
    findings: list[str] = []

    machine_parts = {
        component.reference: (component.footprint, component.value)
        for component in machine.components
    }
    reader_parts = {
        component.reference: (component.footprint, component.value)
        for component in reader.components
    }
    for reference in sorted(machine_parts.keys() - reader_parts.keys()):
        findings.append(f"{reference} is only in the machine schematic.")
    for reference in sorted(reader_parts.keys() - machine_parts.keys()):
        findings.append(f"{reference} is only in the reader schematic.")
    for reference in sorted(machine_parts.keys() & reader_parts.keys()):
        if machine_parts[reference] != reader_parts[reference]:
            findings.append(
                f"{reference} differs: machine {machine_parts[reference]} "
                f"vs reader {reader_parts[reference]}."
            )

    machine_nets = {net.name: frozenset(net.nodes) for net in machine.nets}
    reader_nets = {net.name: frozenset(net.nodes) for net in reader.nets}
    for name in sorted(machine_nets.keys() - reader_nets.keys()):
        findings.append(f"Net {name} is only in the machine schematic.")
    for name in sorted(reader_nets.keys() - machine_nets.keys()):
        findings.append(f"Net {name} is only in the reader schematic.")
    for name in sorted(machine_nets.keys() & reader_nets.keys()):
        if machine_nets[name] == reader_nets[name]:
            continue
        missing = machine_nets[name] - reader_nets[name]
        extra = reader_nets[name] - machine_nets[name]
        detail: list[str] = []
        if missing:
            detail.append(
                "missing "
                + ", ".join(f"{ref}.{pin}" for ref, pin in sorted(missing))
            )
        if extra:
            detail.append(
                "extra "
                + ", ".join(f"{ref}.{pin}" for ref, pin in sorted(extra))
            )
        findings.append(
            f"Net {name} differs in the reader schematic: "
            + "; ".join(detail) + "."
        )
    return tuple(findings)
