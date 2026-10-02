"""Prototype-only text builder retained from the early GUI/catalog lineage."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from pcbsmith.kicad.kicad_project import render_kicad_board_file


@dataclass(frozen=True)
class NetRef:
    number: int
    name: str


@dataclass(frozen=True)
class PadSpec:
    name: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    net: NetRef
    roundrect_ratio: float = 0.25


@dataclass(frozen=True)
class TwoPadSmdFootprintSpec:
    footprint: str
    reference: str
    value: str
    x_mm: float
    y_mm: float
    left_net: NetRef
    right_net: NetRef
    left_pad_number: str = "1"
    right_pad_number: str = "2"
    reference_layer: str = "F.SilkS"
    body_layer: str = "F.Fab"
    reference_offset_mm: tuple[float, float] = (0.0, -1.0)
    body_width_mm: float = 1.6
    body_height_mm: float = 0.8
    pad_offset_mm: float = 0.75
    pad_width_mm: float = 0.75
    pad_height_mm: float = 0.95
    silk_marker: str | None = None
    cathode_pad: str = "1"
    show_anode_plus: bool = False
    anode_pad: str = "1"
    polarity_semantics: str = ""
    rotation_deg: int = 0
    show_silkscreen_outline: bool = True
    silkscreen_x_margin_mm: float = 0.85
    silkscreen_y_margin_mm: float = 0.5
    description: str = ""


@dataclass(frozen=True)
class ThreePadSmdFootprintSpec:
    footprint: str
    reference: str
    value: str
    x_mm: float
    y_mm: float
    pads: tuple[tuple[str, float, float, float, float, NetRef], ...]
    reference_offset_mm: tuple[float, float] = (0.0, -2.0)
    body_width_mm: float = 4.0
    body_height_mm: float = 3.0
    body_layer: str = "F.Fab"
    description: str = ""


@dataclass(frozen=True)
class MultiPadSmdFootprintSpec:
    footprint: str
    reference: str
    value: str
    x_mm: float
    y_mm: float
    pads: tuple[tuple[str, float, float, float, float, NetRef], ...]
    reference_offset_mm: tuple[float, float] = (0.0, -3.0)
    value_offset_mm: tuple[float, float] = (0.0, 3.0)
    body_width_mm: float = 8.0
    body_height_mm: float = 6.0
    body_layer: str = "F.Fab"
    show_pin_one_marker: bool = True
    show_silkscreen_outline: bool = True
    description: str = ""


@dataclass(frozen=True)
class TwoPadThroughHoleFootprintSpec:
    footprint: str
    reference: str
    value: str
    x_mm: float
    y_mm: float
    first_net: NetRef
    second_net: NetRef
    pad_offset_mm: float = 2.5
    pad_axis: str = "y"
    pad_size_mm: float = 3.2
    drill_mm: float = 1.3
    reference_offset_mm: tuple[float, float] = (0.0, -4.5)
    description: str = ""
    connector_mating_label: str = ""


@dataclass
class KiCadBoardBuilder:
    board_outline_uuid: UUID = field(default_factory=uuid4)
    _items: list[str] = field(default_factory=list, init=False)
    _net_numbers: dict[str, int] = field(default_factory=dict, init=False)

    def net(self, name: str) -> NetRef:
        number = self._net_numbers.get(name)
        if number is None:
            number = len(self._net_numbers) + 1
            self._net_numbers[name] = number
        return NetRef(number=number, name=name)

    def add_text(
        self,
        text: str,
        x_mm: float,
        y_mm: float,
        *,
        layer: str = "F.SilkS",
        size_mm: float = 1.0,
        rotation_deg: int = 0,
    ) -> None:
        self._items.append(
            f"""  (gr_text {_quote(text)}
    (at {_mm(x_mm)} {_mm(y_mm)} {rotation_deg})
    (layer {_quote(layer)})
    (uuid {uuid4()})
    (effects
      (font
        (size {_mm(size_mm)} {_mm(size_mm)})
        (thickness {_mm(size_mm * 0.12)})
      )
    )
  )"""
        )

    def add_rect(
        self,
        start_x_mm: float,
        start_y_mm: float,
        end_x_mm: float,
        end_y_mm: float,
        *,
        layer: str = "F.SilkS",
        width_mm: float = 0.18,
    ) -> None:
        self._items.append(
            f"""  (gr_rect
    (start {_mm(start_x_mm)} {_mm(start_y_mm)})
    (end {_mm(end_x_mm)} {_mm(end_y_mm)})
    (stroke (width {_mm(width_mm)}) (type solid))
    (fill none)
    (layer {_quote(layer)})
    (uuid {uuid4()})
  )"""
        )

    def add_segment(
        self,
        start_x_mm: float,
        start_y_mm: float,
        end_x_mm: float,
        end_y_mm: float,
        *,
        layer: str = "F.Cu",
        width_mm: float,
        net: NetRef,
    ) -> None:
        self._items.append(
            f"""  (segment
    (start {_mm(start_x_mm)} {_mm(start_y_mm)})
    (end {_mm(end_x_mm)} {_mm(end_y_mm)})
    (width {_mm(width_mm)})
    (layer {_quote(layer)})
    (net {net.number})
    (uuid {uuid4()})
  )"""
        )

    def add_via(
        self,
        x_mm: float,
        y_mm: float,
        *,
        net: NetRef,
        size_mm: float = 0.8,
        drill_mm: float = 0.4,
    ) -> None:
        self._items.append(
            f"""  (via
    (at {_mm(x_mm)} {_mm(y_mm)})
    (size {_mm(size_mm)})
    (drill {_mm(drill_mm)})
    (layers "F.Cu" "B.Cu")
    (net {net.number})
    (uuid {uuid4()})
  )"""
        )

    def add_power_pad(
        self,
        reference: str,
        x_mm: float,
        y_mm: float,
        *,
        net: NetRef,
        value: str = "Power Pad",
        size_mm: float = 2.4,
        reference_offset_mm: tuple[float, float] = (0.0, -2.2),
        show_reference: bool = True,
    ) -> None:
        ref_x, ref_y = reference_offset_mm
        self._items.append(
            f"""  (footprint "PCBSmith_POWER_INPUT_PAD"
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(x_mm)} {_mm(y_mm)})
    {_property("Reference", reference, ref_x, ref_y, "F.SilkS", 1.0, hidden=not show_reference)}
    {_property("Value", value, 0, 2.2, "F.Fab", 1.0)}
    (attr smd)
{_pad(PadSpec("1", 0, 0, size_mm, size_mm, net, roundrect_ratio=0.2))}
  )"""
        )

    def add_through_hole_pad(
        self,
        reference: str,
        x_mm: float,
        y_mm: float,
        *,
        net: NetRef,
        value: str = "Through Hole Pad",
        size_mm: float = 1.7,
        drill_mm: float = 0.9,
        reference_offset_mm: tuple[float, float] = (0.0, -2.0),
        show_reference: bool = True,
    ) -> None:
        ref_x, ref_y = reference_offset_mm
        self._items.append(
            f"""  (footprint "PCBSmith_THROUGH_HOLE_PAD"
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(x_mm)} {_mm(y_mm)})
    {_property("Reference", reference, ref_x, ref_y, "F.SilkS", 1.0, hidden=not show_reference)}
    {_property("Value", value, 0, 2.2, "F.Fab", 1.0)}
    (attr through_hole)
{_through_hole_pad(PadSpec("1", 0, 0, size_mm, size_mm, net), drill_mm)}
  )"""
        )

    def add_two_pad_smd_footprint(self, spec: TwoPadSmdFootprintSpec) -> None:
        ref_x, ref_y = spec.reference_offset_mm
        if spec.rotation_deg % 90:
            raise ValueError("rotation_deg must be a multiple of 90 degrees")
        marker = _footprint_marker(spec) if spec.silk_marker else ""
        anode_plus = _anode_plus_marker(spec) if spec.show_anode_plus else ""
        polarity_property = (
            _property(
                "PCBSmith_Polarity",
                spec.polarity_semantics,
                0,
                0,
                "F.Fab",
                0.5,
                hidden=True,
            )
            if spec.polarity_semantics
            else ""
        )
        silkscreen_outline = (
            _footprint_rect(
                spec.body_width_mm + (spec.silkscreen_x_margin_mm * 2),
                spec.body_height_mm + (spec.silkscreen_y_margin_mm * 2),
                "F.SilkS",
                stroke_width_mm=0.1,
            )
            if spec.show_silkscreen_outline
            else ""
        )
        left_pad = _pad(
            PadSpec(
                spec.left_pad_number,
                -spec.pad_offset_mm,
                0,
                spec.pad_width_mm,
                spec.pad_height_mm,
                spec.left_net,
            )
        )
        right_pad = _pad(
            PadSpec(
                spec.right_pad_number,
                spec.pad_offset_mm,
                0,
                spec.pad_width_mm,
                spec.pad_height_mm,
                spec.right_net,
            )
        )
        self._items.append(
            f"""  (footprint {_quote(spec.footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(spec.x_mm)} {_mm(spec.y_mm)} {spec.rotation_deg % 360})
    {_property("Reference", spec.reference, ref_x, ref_y, spec.reference_layer, 0.8)}
    {_property("Value", spec.value, 0, 1.0, "F.Fab", 0.5)}
    {_description_property(spec.description, spec.footprint)}
    {polarity_property}
    (attr smd)
{_footprint_rect(spec.body_width_mm, spec.body_height_mm, spec.body_layer)}
{silkscreen_outline}
{marker}
{anode_plus}
{left_pad}
{right_pad}
  )"""
        )

    def add_two_pad_through_hole_footprint(self, spec: TwoPadThroughHoleFootprintSpec) -> None:
        if spec.pad_axis not in {"x", "y"}:
            raise ValueError("pad_axis must be 'x' or 'y'")
        ref_x, ref_y = spec.reference_offset_mm
        first_x = -spec.pad_offset_mm if spec.pad_axis == "x" else 0.0
        first_y = -spec.pad_offset_mm if spec.pad_axis == "y" else 0.0
        second_x = spec.pad_offset_mm if spec.pad_axis == "x" else 0.0
        second_y = spec.pad_offset_mm if spec.pad_axis == "y" else 0.0
        body_width = (
            spec.pad_offset_mm * 2 + spec.pad_size_mm
            if spec.pad_axis == "x"
            else spec.pad_size_mm + 2.0
        )
        body_height = (
            spec.pad_offset_mm * 2 + spec.pad_size_mm
            if spec.pad_axis == "y"
            else spec.pad_size_mm + 2.0
        )
        description = (
            _property("Description", spec.description, 0, 0, "F.Fab", 0.5, hidden=True)
            if spec.description
            else ""
        )
        mating_property = (
            _property(
                "PCBSmith_Mating",
                spec.connector_mating_label,
                0,
                0,
                "F.Fab",
                0.5,
                hidden=True,
            )
            if spec.connector_mating_label
            else ""
        )
        self._items.append(
            f"""  (footprint {_quote(spec.footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(spec.x_mm)} {_mm(spec.y_mm)})
    {_property("Reference", spec.reference, ref_x, ref_y, "F.SilkS", 0.9)}
    {_property("Value", spec.value, 0, 4.5, "F.Fab", 0.7)}
    {description}
    {mating_property}
    (attr through_hole)
{_footprint_rect(body_width, body_height, "F.Fab")}
{
                _through_hole_pad(
                    PadSpec(
                        "1", first_x, first_y, spec.pad_size_mm, spec.pad_size_mm, spec.first_net
                    ),
                    spec.drill_mm,
                )
            }
{
                _through_hole_pad(
                    PadSpec(
                        "2", second_x, second_y, spec.pad_size_mm, spec.pad_size_mm, spec.second_net
                    ),
                    spec.drill_mm,
                )
            }
  )"""
        )

    def add_rectangular_ic_footprint(
        self,
        *,
        footprint: str,
        reference: str,
        value: str,
        x_mm: float,
        y_mm: float,
        left_pads: tuple[tuple[str, NetRef], ...],
        right_pads: tuple[tuple[str, NetRef], ...],
        body_width_mm: float = 4.8,
        body_height_mm: float = 3.6,
        pad_width_mm: float = 0.7,
        pad_height_mm: float = 1.2,
        pad_x_offset_mm: float = 3.0,
        pin_pitch_mm: float = 0.95,
        pin_one_dot: bool = True,
        description: str = "",
    ) -> None:
        if len(left_pads) != len(right_pads):
            raise ValueError("Rectangular IC footprints require balanced left and right pads")

        pads: list[str] = []
        pad_count_per_side = len(left_pads)
        first_pad_y = -((pad_count_per_side - 1) * pin_pitch_mm) / 2
        for index, (pad_name, net) in enumerate(left_pads):
            pads.append(
                _pad(
                    PadSpec(
                        pad_name,
                        -pad_x_offset_mm,
                        first_pad_y + (index * pin_pitch_mm),
                        pad_width_mm,
                        pad_height_mm,
                        net,
                    )
                )
            )
        for index, (pad_name, net) in enumerate(right_pads):
            pads.append(
                _pad(
                    PadSpec(
                        pad_name,
                        pad_x_offset_mm,
                        first_pad_y + (index * pin_pitch_mm),
                        pad_width_mm,
                        pad_height_mm,
                        net,
                    )
                )
            )

        pin_one_marker = (
            _footprint_circle(
                -body_width_mm / 2,
                -body_height_mm / 2,
                radius_mm=0.28,
                layer="F.SilkS",
            )
            if pin_one_dot
            else ""
        )
        self._items.append(
            f"""  (footprint {_quote(footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(x_mm)} {_mm(y_mm)})
    {_property("Reference", reference, 0, 0, "F.SilkS", 0.8)}
    {_property("Value", value, 0, 2.7, "F.Fab", 0.7)}
    {_description_property(description, footprint)}
    (attr smd)
{_footprint_rect(body_width_mm, body_height_mm, "F.Fab")}
{_footprint_rect(body_width_mm, body_height_mm, "F.SilkS", stroke_width_mm=0.12)}
{pin_one_marker}
{chr(10).join(pads)}
  )"""
        )

    def add_three_pad_smd_footprint(self, spec: ThreePadSmdFootprintSpec) -> None:
        ref_x, ref_y = spec.reference_offset_mm
        pads = "\n".join(
            _pad(
                PadSpec(
                    name,
                    pad_x_mm,
                    pad_y_mm,
                    pad_width_mm,
                    pad_height_mm,
                    net,
                )
            )
            for name, pad_x_mm, pad_y_mm, pad_width_mm, pad_height_mm, net in spec.pads
        )
        silkscreen_outline = _footprint_rect(
            spec.body_width_mm + 1.2,
            spec.body_height_mm + 0.9,
            "F.SilkS",
            stroke_width_mm=0.1,
        )
        self._items.append(
            f"""  (footprint {_quote(spec.footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(spec.x_mm)} {_mm(spec.y_mm)})
    {_property("Reference", spec.reference, ref_x, ref_y, "F.SilkS", 0.8)}
    {_property("Value", spec.value, 0, 2.2, "F.Fab", 0.6)}
    {_description_property(spec.description, spec.footprint)}
    (attr smd)
{_footprint_rect(spec.body_width_mm, spec.body_height_mm, spec.body_layer)}
{silkscreen_outline}
{pads}
  )"""
        )

    def add_multi_pad_smd_footprint(self, spec: MultiPadSmdFootprintSpec) -> None:
        ref_x, ref_y = spec.reference_offset_mm
        value_x, value_y = spec.value_offset_mm
        pads = "\n".join(
            _pad(PadSpec(name, pad_x, pad_y, pad_width, pad_height, net))
            for name, pad_x, pad_y, pad_width, pad_height, net in spec.pads
        )
        pin_one_marker = (
            _footprint_circle(
                -spec.body_width_mm / 2 + 0.8,
                -spec.body_height_mm / 2 + 0.8,
                radius_mm=0.25,
                layer="F.SilkS",
            )
            if spec.show_pin_one_marker
            else ""
        )
        silkscreen_outline = (
            _footprint_rect(
                spec.body_width_mm + 1.2,
                spec.body_height_mm + 0.9,
                "F.SilkS",
                stroke_width_mm=0.12,
            )
            if spec.show_silkscreen_outline
            else ""
        )
        self._items.append(
            f"""  (footprint {_quote(spec.footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(spec.x_mm)} {_mm(spec.y_mm)})
    {_property("Reference", spec.reference, ref_x, ref_y, "F.SilkS", 0.9)}
{_property("Value", spec.value, value_x, value_y, "F.Fab", 0.7)}
    {_description_property(spec.description, spec.footprint)}
    (attr smd)
{_footprint_rect(spec.body_width_mm, spec.body_height_mm, spec.body_layer)}
{silkscreen_outline}
{pin_one_marker}
{pads}
  )"""
        )

    def render(
        self,
        *,
        outline_start_mm: tuple[float, float] = (0.0, 0.0),
        outline_end_mm: tuple[float, float],
    ) -> str:
        net_items = [
            f'  (net {number} "{name}")'
            for name, number in sorted(self._net_numbers.items(), key=lambda item: item[1])
        ]
        return render_kicad_board_file(
            self.board_outline_uuid,
            (*net_items, *self._items),
            outline_start_mm=f"{_mm(outline_start_mm[0])} {_mm(outline_start_mm[1])}",
            outline_end_mm=f"{_mm(outline_end_mm[0])} {_mm(outline_end_mm[1])}",
        )


_FOOTPRINT_DESCRIPTIONS = {
    "PCBSmith_C_0603_REAL": "Generic capacitor",
    "PCBSmith_C_ELEC_REAL": "Generic polarized capacitor",
    "PCBSmith_D_SCHOTTKY_REAL": "Generic diode",
    "PCBSmith_L_POWER_REAL": "Generic inductor",
    "PCBSmith_LED_0603_REAL": "Generic LED",
    "PCBSmith_LM2596_TO263_REAL": "LM2596 adjustable buck regulator",
    "PCBSmith_POWER_CONNECTOR_2P_REAL": "Generic 1x2 connector",
    "PCBSmith_R_0603_REAL": "Generic resistor",
    "PCBSmith_SOIC8_NE555_REAL": "Generic 555 timer IC",
}


def _description_property(description: str, footprint: str) -> str:
    local_name = footprint.partition(":")[2] or footprint
    resolved = description or _FOOTPRINT_DESCRIPTIONS.get(local_name, "")
    if not resolved:
        return ""
    return _property("Description", resolved, 0, 0, "F.Fab", 0.5, hidden=True)


def _property(
    name: str,
    value: str,
    x_mm: float,
    y_mm: float,
    layer: str,
    size_mm: float,
    *,
    hidden: bool = False,
) -> str:
    hide_line = "\n        (hide yes)" if hidden else ""
    return f"""(property {_quote(name)} {_quote(value)}
      (at {_mm(x_mm)} {_mm(y_mm)} 0)
      (layer {_quote(layer)})
      (uuid {uuid4()})
      (effects
        (font
          (size {_mm(size_mm)} {_mm(size_mm)})
          (thickness {_mm(size_mm * 0.12)})
        ){hide_line}
      )
    )"""


def _pad(spec: PadSpec) -> str:
    return f"""    (pad {_quote(spec.name)} smd roundrect
      (at {_mm(spec.x_mm)} {_mm(spec.y_mm)})
      (size {_mm(spec.width_mm)} {_mm(spec.height_mm)})
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio {_mm(spec.roundrect_ratio)})
      (net {spec.net.number} {_quote(spec.net.name)})
      (pinfunction {_quote(spec.name)})
      (pintype "passive")
      (uuid {uuid4()})
    )"""


def _through_hole_pad(spec: PadSpec, drill_mm: float) -> str:
    return f"""    (pad {_quote(spec.name)} thru_hole circle
      (at {_mm(spec.x_mm)} {_mm(spec.y_mm)})
      (size {_mm(spec.width_mm)} {_mm(spec.height_mm)})
      (drill {_mm(drill_mm)})
      (layers "*.Cu" "*.Mask")
      (net {spec.net.number} {_quote(spec.net.name)})
      (pinfunction {_quote(spec.name)})
      (pintype "passive")
      (uuid {uuid4()})
    )"""


def _footprint_rect(
    width_mm: float,
    height_mm: float,
    layer: str,
    *,
    stroke_width_mm: float | None = None,
) -> str:
    half_width = width_mm / 2
    half_height = height_mm / 2
    stroke_width = 0.08 if stroke_width_mm is None else stroke_width_mm
    return f"""    (fp_rect
      (start {_mm(-half_width)} {_mm(-half_height)})
      (end {_mm(half_width)} {_mm(half_height)})
      (stroke (width {_mm(stroke_width)}) (type solid))
      (fill none)
      (layer {_quote(layer)})
      (uuid {uuid4()})
    )"""


def _pad_local_x(spec: TwoPadSmdFootprintSpec, pad: str) -> float:
    if pad == spec.left_pad_number:
        return -spec.pad_offset_mm
    if pad == spec.right_pad_number:
        return spec.pad_offset_mm
    raise ValueError(f"Pad {pad!r} is not declared by the two-pad footprint")


def _footprint_marker(spec: TwoPadSmdFootprintSpec) -> str:
    if spec.silk_marker == "cathode":
        x_mm = _pad_local_x(spec, spec.cathode_pad)
        direction = -1.0 if x_mm < 0 else 1.0
        x_mm += direction * (spec.silkscreen_x_margin_mm + 1.25)
        return _footprint_user_text("K", x_mm, -1.75)
    raise ValueError(f"Unsupported footprint marker: {spec.silk_marker}")


def _footprint_user_text(text: str, x_mm: float, y_mm: float) -> str:
    return f"""    (fp_text user {_quote(text)}
      (at {_mm(x_mm)} {_mm(y_mm)} 0)
      (layer "F.SilkS")
      (uuid {uuid4()})
      (effects (font (size 0.8 0.8) (thickness 0.12)))
    )"""


def _anode_plus_marker(spec: TwoPadSmdFootprintSpec) -> str:
    x_mm = _pad_local_x(spec, spec.anode_pad)
    direction = -1.0 if x_mm < 0 else 1.0
    x_mm += direction * (spec.silkscreen_x_margin_mm + 1.25)
    return _footprint_user_text("+", x_mm, 1.75)


def _footprint_line(
    start_x_mm: float,
    start_y_mm: float,
    end_x_mm: float,
    end_y_mm: float,
    layer: str,
) -> str:
    return f"""    (fp_line
      (start {_mm(start_x_mm)} {_mm(start_y_mm)})
      (end {_mm(end_x_mm)} {_mm(end_y_mm)})
      (stroke (width 0.1) (type solid))
      (layer {_quote(layer)})
      (uuid {uuid4()})
    )"""


def _footprint_circle(
    center_x_mm: float,
    center_y_mm: float,
    *,
    radius_mm: float,
    layer: str,
) -> str:
    return f"""    (fp_circle
      (center {_mm(center_x_mm)} {_mm(center_y_mm)})
      (end {_mm(center_x_mm + radius_mm)} {_mm(center_y_mm)})
      (stroke (width 0.12) (type solid))
      (fill none)
      (layer {_quote(layer)})
      (uuid {uuid4()})
    )"""


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mm(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


__all__ = [
    "KiCadBoardBuilder",
    "MultiPadSmdFootprintSpec",
    "NetRef",
    "PadSpec",
    "ThreePadSmdFootprintSpec",
    "TwoPadSmdFootprintSpec",
    "TwoPadThroughHoleFootprintSpec",
]
