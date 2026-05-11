from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from pcbsmith.services.kicad_project import render_kicad_board_file


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
    reference_layer: str = "F.SilkS"
    body_layer: str = "F.Fab"
    reference_offset_mm: tuple[float, float] = (0.0, -1.0)
    body_width_mm: float = 1.6
    body_height_mm: float = 0.8
    pad_offset_mm: float = 0.75
    pad_width_mm: float = 0.75
    pad_height_mm: float = 0.95
    silk_marker: str | None = None
    show_anode_plus: bool = False
    anode_pad: str = "1"
    show_silkscreen_outline: bool = True
    silkscreen_x_margin_mm: float = 0.85
    silkscreen_y_margin_mm: float = 0.5


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
    ) -> None:
        ref_x, ref_y = reference_offset_mm
        self._items.append(
            f"""  (footprint "PCBSmith_POWER_INPUT_PAD"
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(x_mm)} {_mm(y_mm)})
    {_property("Reference", reference, ref_x, ref_y, "F.SilkS", 1.0)}
    {_property("Value", value, 0, 2.2, "F.Fab", 1.0)}
    (attr smd)
{_pad(PadSpec("1", 0, 0, size_mm, size_mm, net, roundrect_ratio=0.2))}
  )"""
        )

    def add_two_pad_smd_footprint(self, spec: TwoPadSmdFootprintSpec) -> None:
        ref_x, ref_y = spec.reference_offset_mm
        marker = _footprint_marker(spec.silk_marker) if spec.silk_marker else ""
        anode_plus = _anode_plus_marker(spec) if spec.show_anode_plus else ""
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
        self._items.append(
            f"""  (footprint {_quote(spec.footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(spec.x_mm)} {_mm(spec.y_mm)})
    {_property("Reference", spec.reference, ref_x, ref_y, spec.reference_layer, 0.8)}
    {_property("Value", spec.value, 0, 1.0, "F.Fab", 0.5)}
    (attr smd)
{_footprint_rect(spec.body_width_mm, spec.body_height_mm, spec.body_layer)}
{silkscreen_outline}
{marker}
{anode_plus}
{_pad(PadSpec("1", -spec.pad_offset_mm, 0, spec.pad_width_mm, spec.pad_height_mm, spec.left_net))}
{_pad(PadSpec("2", spec.pad_offset_mm, 0, spec.pad_width_mm, spec.pad_height_mm, spec.right_net))}
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
    (attr smd)
{_footprint_rect(spec.body_width_mm, spec.body_height_mm, spec.body_layer)}
{silkscreen_outline}
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


def _property(
    name: str,
    value: str,
    x_mm: float,
    y_mm: float,
    layer: str,
    size_mm: float,
) -> str:
    return f"""(property {_quote(name)} {_quote(value)}
      (at {_mm(x_mm)} {_mm(y_mm)} 0)
      (layer {_quote(layer)})
      (uuid {uuid4()})
      (effects (font (size {_mm(size_mm)} {_mm(size_mm)}) (thickness {_mm(size_mm * 0.12)})))
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


def _footprint_marker(marker: str) -> str:
    if marker == "cathode":
        return _footprint_line(0, -0.65, 0, 0.65, "F.SilkS")
    raise ValueError(f"Unsupported footprint marker: {marker}")


def _anode_plus_marker(spec: TwoPadSmdFootprintSpec) -> str:
    if spec.anode_pad == "1":
        x_mm = -spec.pad_offset_mm - 1.0
    elif spec.anode_pad == "2":
        x_mm = spec.pad_offset_mm + 1.0
    else:
        raise ValueError(f"Unsupported anode pad: {spec.anode_pad}")
    return f"""    (fp_text user "+"
      (at {_mm(x_mm)} 1.75 0)
      (layer "F.SilkS")
      (uuid {uuid4()})
      (effects (font (size 0.8 0.8) (thickness 0.12)))
    )"""


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
    "NetRef",
    "PadSpec",
    "ThreePadSmdFootprintSpec",
    "TwoPadSmdFootprintSpec",
]
