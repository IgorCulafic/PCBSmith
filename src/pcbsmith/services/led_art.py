from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

LED_ART_ELECTRICAL_SCHEMA = "pcbsmith-led-art-electrical-v1"

LETTER_PATTERNS = {
    "V": ("10001", "10001", "10001", "10001", "01010", "01010", "00100"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
}

_E12_BASE_VALUES = (10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82)


class LedArtSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(default="VIR-LAB", min_length=1)
    supply_voltage_v: float = Field(default=5.0, gt=0)
    led_forward_voltage_v: float = Field(default=2.0, gt=0)
    target_current_ma: float = Field(default=5.0, gt=0)
    usb_warning_current_ma: float = Field(default=250.0, gt=0)
    x_origin_mm: float = 24.0
    y_origin_mm: float = 24.0
    x_step_mm: float = Field(default=7.5, gt=0)
    y_step_mm: float = Field(default=11.0, gt=0)
    letter_advance_mm: float = Field(default=48.0, gt=0)
    board_margin_mm: float = Field(default=24.0, gt=0)


class LedArtPixel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(gt=0)
    x: float
    y: float
    resistor_ref: str
    led_ref: str
    drive_net: str

    @property
    def resistor_x(self) -> float:
        return self.x - 1.8

    @property
    def led_x(self) -> float:
        return self.x + 1.8

    @property
    def vcc_tap_x(self) -> float:
        return self.x - 2.55

    @property
    def gnd_tap_x(self) -> float:
        return self.x + 2.55


class LedArtString(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(gt=0)
    led_refs: tuple[str, ...]
    resistor_ref: str
    resistor_value_ohms: int = Field(gt=0)
    current_ma: float


class LedArtElectricalReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: str = Field(default=LED_ART_ELECTRICAL_SCHEMA, serialization_alias="schema")
    text: str
    supply_voltage_v: float
    led_forward_voltage_v: float
    target_current_ma: float
    resistor_value_ohms: int
    string_current_ma: float
    total_led_count: int
    string_count: int
    total_current_ma: float
    estimated_power_mw: float
    grouping_strategy: str
    warnings: tuple[str, ...] = ()


class LedArtPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: LedArtSpec
    pixels: tuple[LedArtPixel, ...]
    strings: tuple[LedArtString, ...]
    electrical: LedArtElectricalReport
    board_width_mm: float
    board_height_mm: float


class LedArtReportPaths(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    json_path: Path
    markdown_path: Path


def select_led_resistor_ohms(
    *,
    supply_voltage_v: float,
    led_forward_voltage_v: float,
    target_current_ma: float,
) -> int:
    if led_forward_voltage_v >= supply_voltage_v:
        raise ValueError("LED forward voltage must be below supply voltage")
    raw_ohms = (supply_voltage_v - led_forward_voltage_v) / (target_current_ma / 1000.0)
    return _next_e12_value(raw_ohms)


def build_led_art_plan(spec: LedArtSpec) -> LedArtPlan:
    pixels = _letter_pixels(spec)
    resistor_value = select_led_resistor_ohms(
        supply_voltage_v=spec.supply_voltage_v,
        led_forward_voltage_v=spec.led_forward_voltage_v,
        target_current_ma=spec.target_current_ma,
    )
    string_current_ma = (
        (spec.supply_voltage_v - spec.led_forward_voltage_v) / resistor_value
    ) * 1000.0
    strings = tuple(
        LedArtString(
            index=pixel.index,
            led_refs=(pixel.led_ref,),
            resistor_ref=pixel.resistor_ref,
            resistor_value_ohms=resistor_value,
            current_ma=string_current_ma,
        )
        for pixel in pixels
    )
    total_current_ma = string_current_ma * len(strings)
    warnings = _electrical_warnings(spec, total_current_ma)
    electrical = LedArtElectricalReport(
        text=spec.text.upper(),
        supply_voltage_v=spec.supply_voltage_v,
        led_forward_voltage_v=spec.led_forward_voltage_v,
        target_current_ma=spec.target_current_ma,
        resistor_value_ohms=resistor_value,
        string_current_ma=string_current_ma,
        total_led_count=len(pixels),
        string_count=len(strings),
        total_current_ma=total_current_ma,
        estimated_power_mw=spec.supply_voltage_v * total_current_ma,
        grouping_strategy="one_led_per_resistor",
        warnings=warnings,
    )
    return LedArtPlan(
        spec=spec,
        pixels=pixels,
        strings=strings,
        electrical=electrical,
        board_width_mm=_board_width(spec),
        board_height_mm=spec.y_origin_mm + (7 * spec.y_step_mm) + spec.board_margin_mm,
    )


def write_led_art_reports(plan: LedArtPlan, output_dir: Path) -> LedArtReportPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "led-art-electrical.json"
    markdown_path = output_dir / "led-art-electrical.md"
    json_path.write_text(
        json.dumps(plan.electrical.model_dump(mode="json", by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown_report(plan), encoding="utf-8")
    return LedArtReportPaths(json_path=json_path, markdown_path=markdown_path)


def _letter_pixels(spec: LedArtSpec) -> tuple[LedArtPixel, ...]:
    pixels: list[LedArtPixel] = []
    index = 1
    for letter_index, letter in enumerate(spec.text.upper()):
        try:
            pattern = LETTER_PATTERNS[letter]
        except KeyError as exc:
            supported = ", ".join(sorted(LETTER_PATTERNS))
            message = f"Unsupported LED-art glyph {letter!r}; supported: {supported}"
            raise ValueError(message) from exc
        letter_x = spec.x_origin_mm + letter_index * spec.letter_advance_mm
        for row_index, row in enumerate(pattern):
            for col_index, is_lit in enumerate(row):
                if is_lit != "1":
                    continue
                pixels.append(
                    LedArtPixel(
                        index=index,
                        x=letter_x + col_index * spec.x_step_mm,
                        y=spec.y_origin_mm + row_index * spec.y_step_mm,
                        resistor_ref=f"R{index}",
                        led_ref=f"LED{index}",
                        drive_net=f"LED_{index}",
                    )
                )
                index += 1
    return tuple(pixels)


def _next_e12_value(raw_ohms: float) -> int:
    if raw_ohms <= 0:
        raise ValueError("Raw resistor value must be positive")
    decade = 10 ** math.floor(math.log10(raw_ohms))
    for multiplier in (1, 10):
        for base_value in _E12_BASE_VALUES:
            candidate = int(base_value * decade * multiplier / 10)
            if candidate >= raw_ohms:
                return candidate
    return int(82 * decade)


def _electrical_warnings(spec: LedArtSpec, total_current_ma: float) -> tuple[str, ...]:
    if total_current_ma <= spec.usb_warning_current_ma:
        return ()
    return (
        "Estimated LED current exceeds "
        f"{spec.usb_warning_current_ma:.1f} mA; review USB/input power budget.",
    )


def _board_width(spec: LedArtSpec) -> float:
    return (
        spec.x_origin_mm
        + ((len(spec.text) - 1) * spec.letter_advance_mm)
        + (5 * spec.x_step_mm)
        + spec.board_margin_mm
    )


def _render_markdown_report(plan: LedArtPlan) -> str:
    report = plan.electrical
    warning_lines = (
        "\n".join(f"- {warning}" for warning in report.warnings)
        if report.warnings
        else "- No electrical warnings from this estimate."
    )
    return "\n".join(
        [
            f"# {report.text} LED Art Electrical Report",
            "",
            f"- Supply: {report.supply_voltage_v:g} V",
            f"- LED forward voltage assumption: {report.led_forward_voltage_v:g} V",
            f"- Target current: {report.target_current_ma:g} mA",
            f"- Resistor: {report.resistor_value_ohms} ohm",
            f"- Grouping strategy: {report.grouping_strategy}",
            f"- LED count: {report.total_led_count}",
            f"- String count: {report.string_count}",
            f"- Estimated current per string: {report.string_current_ma:.2f} mA",
            f"- Estimated total current: {report.total_current_ma:.2f} mA",
            f"- Estimated input power: {report.estimated_power_mw:.1f} mW",
            "",
            "## Warnings",
            "",
            warning_lines,
            "",
        ]
    )


__all__ = [
    "LED_ART_ELECTRICAL_SCHEMA",
    "LedArtElectricalReport",
    "LedArtPixel",
    "LedArtPlan",
    "LedArtReportPaths",
    "LedArtSpec",
    "LedArtString",
    "build_led_art_plan",
    "select_led_resistor_ohms",
    "write_led_art_reports",
]
