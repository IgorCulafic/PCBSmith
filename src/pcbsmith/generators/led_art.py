from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

LED_ART_ELECTRICAL_SCHEMA = "pcbsmith-led-art-electrical-v1"
LED_ART_TOPOLOGY_COMPARISON_SCHEMA = "pcbsmith-led-art-topology-comparison-v1"

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
    pixel_indices: tuple[int, ...]
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


class LedArtTopologyOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    supply_voltage_v: float
    series_leds_per_string: int = Field(gt=0)
    resistor_value_ohms: int = Field(gt=0)
    string_count: int = Field(gt=0)
    total_led_count: int = Field(gt=0)
    string_current_ma: float
    total_current_ma: float
    estimated_power_mw: float
    notes: tuple[str, ...] = ()


class LedArtTopologyComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: str = Field(
        default=LED_ART_TOPOLOGY_COMPARISON_SCHEMA,
        serialization_alias="schema",
    )
    text: str
    priority: str
    recommended_option_id: str
    options: tuple[LedArtTopologyOption, ...]


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
    return build_led_art_plan_for_topology(spec, "5v_one_per_led")


def build_led_art_plan_for_topology(spec: LedArtSpec, topology_id: str) -> LedArtPlan:
    topology = _topology_profile(spec, topology_id)
    effective_spec = spec.model_copy(update={"supply_voltage_v": topology.supply_voltage_v})
    pixels = _letter_pixels(spec)
    nominal_resistor_value = select_led_resistor_ohms(
        supply_voltage_v=effective_spec.supply_voltage_v,
        led_forward_voltage_v=effective_spec.led_forward_voltage_v
        * topology.series_leds_per_string,
        target_current_ma=effective_spec.target_current_ma,
    )
    nominal_string_current_ma = (
        (
            effective_spec.supply_voltage_v
            - (effective_spec.led_forward_voltage_v * topology.series_leds_per_string)
        )
        / nominal_resistor_value
    ) * 1000.0
    string_pixel_groups = _string_pixel_groups(
        pixels,
        max_series_leds=topology.series_leds_per_string,
        x_step_mm=effective_spec.x_step_mm,
    )
    strings = tuple(
        _led_art_string(
            string_index,
            chunk,
            effective_spec,
        )
        for string_index, chunk in enumerate(string_pixel_groups, start=1)
    )
    total_current_ma = sum(string.current_ma for string in strings)
    warnings = _electrical_warnings(effective_spec, total_current_ma)
    electrical = LedArtElectricalReport(
        text=effective_spec.text.upper(),
        supply_voltage_v=effective_spec.supply_voltage_v,
        led_forward_voltage_v=effective_spec.led_forward_voltage_v,
        target_current_ma=effective_spec.target_current_ma,
        resistor_value_ohms=nominal_resistor_value,
        string_current_ma=nominal_string_current_ma,
        total_led_count=len(pixels),
        string_count=len(strings),
        total_current_ma=total_current_ma,
        estimated_power_mw=effective_spec.supply_voltage_v * total_current_ma,
        grouping_strategy=topology.id,
        warnings=warnings,
    )
    return LedArtPlan(
        spec=effective_spec,
        pixels=pixels,
        strings=strings,
        electrical=electrical,
        board_width_mm=_board_width(effective_spec),
        board_height_mm=effective_spec.y_origin_mm
        + (7 * effective_spec.y_step_mm)
        + effective_spec.board_margin_mm,
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


def compare_led_art_topologies(
    plan: LedArtPlan,
    *,
    priority: str = "density",
) -> LedArtTopologyComparison:
    options = (
        _topology_option(
            "5v_one_per_led",
            "USB 5V simple, one resistor per LED",
            plan=plan,
            supply_voltage_v=5.0,
            series_leds_per_string=1,
            notes=(
                "Safest and easiest to debug.",
                "Uses the most resistors and board area.",
            ),
        ),
        _topology_option(
            "5v_two_led_dense",
            "USB 5V dense, two red LEDs per resistor branch",
            plan=plan,
            supply_voltage_v=5.0,
            series_leds_per_string=2,
            notes=(
                "Good density improvement for 5V red LED art.",
                "Odd LED counts need one shorter branch.",
            ),
        ),
        _topology_option(
            "12v_dense",
            "12V dense, automatic series branches",
            plan=plan,
            supply_voltage_v=12.0,
            series_leds_per_string=_series_leds_for_density(12.0, plan.spec.led_forward_voltage_v),
            notes=(
                "Fewer resistors and lower total current for dense LED art.",
                "Requires a clearly labeled 12V input and polarity protection review.",
            ),
        ),
    )
    recommended = _recommended_option(options, priority)
    return LedArtTopologyComparison(
        text=plan.electrical.text,
        priority=priority,
        recommended_option_id=recommended.id,
        options=options,
    )


def write_led_art_topology_comparison_reports(
    comparison: LedArtTopologyComparison,
    output_dir: Path,
) -> LedArtReportPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "led-art-topology-comparison.json"
    markdown_path = output_dir / "led-art-topology-comparison.md"
    json_path.write_text(
        json.dumps(comparison.model_dump(mode="json", by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_topology_markdown(comparison), encoding="utf-8")
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


def _series_leds_for_density(supply_voltage_v: float, led_forward_voltage_v: float) -> int:
    return max(1, math.floor((supply_voltage_v - 1.0) / led_forward_voltage_v))


class _TopologyProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    supply_voltage_v: float
    series_leds_per_string: int = Field(gt=0)


def _topology_profile(spec: LedArtSpec, topology_id: str) -> _TopologyProfile:
    if topology_id == "5v_one_per_led":
        return _TopologyProfile(
            id=topology_id,
            supply_voltage_v=5.0,
            series_leds_per_string=1,
        )
    if topology_id == "5v_two_led_dense":
        return _TopologyProfile(
            id=topology_id,
            supply_voltage_v=5.0,
            series_leds_per_string=2,
        )
    if topology_id == "12v_dense":
        return _TopologyProfile(
            id=topology_id,
            supply_voltage_v=12.0,
            series_leds_per_string=_series_leds_for_density(
                12.0,
                spec.led_forward_voltage_v,
            ),
        )
    raise ValueError(f"Unsupported LED-art topology: {topology_id}")


def _led_art_string(
    string_index: int,
    pixels: tuple[LedArtPixel, ...],
    spec: LedArtSpec,
) -> LedArtString:
    resistor_value = select_led_resistor_ohms(
        supply_voltage_v=spec.supply_voltage_v,
        led_forward_voltage_v=spec.led_forward_voltage_v * len(pixels),
        target_current_ma=spec.target_current_ma,
    )
    current_ma = (
        (spec.supply_voltage_v - (spec.led_forward_voltage_v * len(pixels)))
        / resistor_value
    ) * 1000.0
    return LedArtString(
        index=string_index,
        led_refs=tuple(pixel.led_ref for pixel in pixels),
        pixel_indices=tuple(pixel.index for pixel in pixels),
        resistor_ref=f"R{string_index}",
        resistor_value_ohms=resistor_value,
        current_ma=current_ma,
    )


def _ordered_pixels_for_strings(pixels: tuple[LedArtPixel, ...]) -> tuple[LedArtPixel, ...]:
    return tuple(sorted(pixels, key=lambda pixel: (pixel.y, pixel.x, pixel.index)))


def _string_pixel_groups(
    pixels: tuple[LedArtPixel, ...],
    *,
    max_series_leds: int,
    x_step_mm: float,
) -> tuple[tuple[LedArtPixel, ...], ...]:
    if max_series_leds == 1:
        return tuple((pixel,) for pixel in _ordered_pixels_for_strings(pixels))

    return _adjacent_path_groups(
        pixels,
        max_series_leds=max_series_leds,
        x_step_mm=x_step_mm,
    )


def _adjacent_path_groups(
    pixels: tuple[LedArtPixel, ...],
    *,
    max_series_leds: int,
    x_step_mm: float,
) -> tuple[tuple[LedArtPixel, ...], ...]:
    pixel_by_index = {pixel.index: pixel for pixel in pixels}
    neighbors = _adjacent_pixel_neighbors(pixels, x_step_mm=x_step_mm)
    unvisited = set(pixel_by_index)
    groups: list[tuple[LedArtPixel, ...]] = []
    while unvisited:
        best_path: tuple[int, ...] = ()
        for start_index in sorted(unvisited):
            candidate = _longest_path_from(
                start_index,
                neighbors,
                unvisited,
                max_series_leds=max_series_leds,
                pixel_by_index=pixel_by_index,
            )
            if _path_score(candidate, pixel_by_index) > _path_score(
                best_path,
                pixel_by_index,
            ):
                best_path = candidate
        groups.append(tuple(pixel_by_index[index] for index in best_path))
        unvisited.difference_update(best_path)
    return tuple(groups)


def _adjacent_pixel_neighbors(
    pixels: tuple[LedArtPixel, ...],
    *,
    x_step_mm: float,
) -> dict[int, tuple[int, ...]]:
    ordered = _ordered_pixels_for_strings(pixels)
    y_steps = sorted(
        {
            round(abs(left.y - right.y), 6)
            for left in ordered
            for right in ordered
            if abs(left.y - right.y) > 0.001
        }
    )
    y_step_mm = y_steps[0] if y_steps else x_step_mm
    neighbors: dict[int, list[int]] = {pixel.index: [] for pixel in ordered}
    for left in ordered:
        for right in ordered:
            if left.index == right.index:
                continue
            same_row = abs(left.y - right.y) < 0.001
            same_column = abs(left.x - right.x) < 0.001
            adjacent_column = abs(abs(left.x - right.x) - x_step_mm) < 0.001
            adjacent_row = abs(abs(left.y - right.y) - y_step_mm) < 0.001
            if (same_row and adjacent_column) or (same_column and adjacent_row):
                neighbors[left.index].append(right.index)
    return {
        index: tuple(sorted(items, key=lambda item: _pixel_sort_key(ordered, item)))
        for index, items in neighbors.items()
    }


def _pixel_sort_key(pixels: tuple[LedArtPixel, ...], index: int) -> tuple[float, float, int]:
    pixel_by_index = {pixel.index: pixel for pixel in pixels}
    pixel = pixel_by_index[index]
    return (pixel.y, pixel.x, pixel.index)


def _longest_path_from(
    start_index: int,
    neighbors: dict[int, tuple[int, ...]],
    unvisited: set[int],
    *,
    max_series_leds: int,
    pixel_by_index: dict[int, LedArtPixel],
) -> tuple[int, ...]:
    best_path: tuple[int, ...] = (start_index,)

    def walk(path: tuple[int, ...]) -> None:
        nonlocal best_path
        if len(path) == max_series_leds:
            best_path = path
            return
        for neighbor in neighbors[path[-1]]:
            if neighbor not in unvisited or neighbor in path:
                continue
            if len(path) >= 2:
                previous_direction = _edge_direction(
                    pixel_by_index[path[-2]],
                    pixel_by_index[path[-1]],
                )
                next_direction = _edge_direction(
                    pixel_by_index[path[-1]],
                    pixel_by_index[neighbor],
                )
                if next_direction != previous_direction:
                    continue
            candidate = (*path, neighbor)
            if len(candidate) > len(best_path):
                best_path = candidate
            walk(candidate)

    walk(best_path)
    return best_path


def _path_score(
    path: tuple[int, ...],
    pixel_by_index: dict[int, LedArtPixel],
) -> tuple[int, int, int, float, float]:
    if not path:
        return (0, 0, 0, 0.0, 0.0)
    vertical_edges = 0
    horizontal_edges = 0
    turns = 0
    previous_direction: tuple[int, int] | None = None
    for left_index, right_index in zip(path, path[1:], strict=False):
        left = pixel_by_index[left_index]
        right = pixel_by_index[right_index]
        direction = _edge_direction(left, right)
        if direction == (0, 1):
            vertical_edges += 1
        if direction == (1, 0):
            horizontal_edges += 1
        if previous_direction is not None and direction != previous_direction:
            turns += 1
        previous_direction = direction
    first = pixel_by_index[path[0]]
    return (len(path), vertical_edges, horizontal_edges, -turns, -first.y)


def _edge_direction(left: LedArtPixel, right: LedArtPixel) -> tuple[int, int]:
    return (
        0 if abs(left.x - right.x) < 0.001 else 1,
        0 if abs(left.y - right.y) < 0.001 else 1,
    )


def _topology_option(
    option_id: str,
    label: str,
    *,
    plan: LedArtPlan,
    supply_voltage_v: float,
    series_leds_per_string: int,
    notes: tuple[str, ...],
) -> LedArtTopologyOption:
    resistor_value = select_led_resistor_ohms(
        supply_voltage_v=supply_voltage_v,
        led_forward_voltage_v=plan.spec.led_forward_voltage_v * series_leds_per_string,
        target_current_ma=plan.spec.target_current_ma,
    )
    string_current_ma = (
        (
            supply_voltage_v
            - (plan.spec.led_forward_voltage_v * series_leds_per_string)
        )
        / resistor_value
    ) * 1000.0
    string_count = math.ceil(len(plan.pixels) / series_leds_per_string)
    total_current_ma = string_current_ma * string_count
    return LedArtTopologyOption(
        id=option_id,
        label=label,
        supply_voltage_v=supply_voltage_v,
        series_leds_per_string=series_leds_per_string,
        resistor_value_ohms=resistor_value,
        string_count=string_count,
        total_led_count=len(plan.pixels),
        string_current_ma=string_current_ma,
        total_current_ma=total_current_ma,
        estimated_power_mw=supply_voltage_v * total_current_ma,
        notes=notes,
    )


def _recommended_option(
    options: tuple[LedArtTopologyOption, ...],
    priority: str,
) -> LedArtTopologyOption:
    if priority == "density":
        return max(options, key=lambda option: option.series_leds_per_string)
    if priority == "usb":
        return next(option for option in options if option.id == "5v_two_led_dense")
    if priority == "simple":
        return next(option for option in options if option.id == "5v_one_per_led")
    raise ValueError(f"Unsupported LED-art topology priority: {priority}")


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
    resistor_values = ", ".join(
        f"{value} ohm" for value in sorted({string.resistor_value_ohms for string in plan.strings})
    )
    string_lengths = ", ".join(
        str(length) for length in sorted({len(string.led_refs) for string in plan.strings})
    )
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
            f"- Nominal max-string resistor: {report.resistor_value_ohms} ohm",
            f"- Per-string resistor values: {resistor_values}",
            f"- LEDs per physical string: {string_lengths}",
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


def _render_topology_markdown(comparison: LedArtTopologyComparison) -> str:
    lines = [
        f"# {comparison.text} LED Art Topology Comparison",
        "",
        f"Recommended for `{comparison.priority}`: `{comparison.recommended_option_id}`.",
        "",
        "These are planning alternatives for the next physical layout slice. "
        "The current board may still use a simpler resistor-per-LED topology.",
        "",
        "| Option | Supply | LEDs/string | Strings | Resistor | Total current | Notes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for option in comparison.options:
        notes = " ".join(option.notes)
        lines.append(
            "| "
            f"`{option.id}` | "
            f"{option.supply_voltage_v:g} V | "
            f"{option.series_leds_per_string} | "
            f"{option.string_count} | "
            f"{option.resistor_value_ohms} ohm | "
            f"{option.total_current_ma:.1f} mA | "
            f"{notes} |"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "LED_ART_ELECTRICAL_SCHEMA",
    "LED_ART_TOPOLOGY_COMPARISON_SCHEMA",
    "LedArtElectricalReport",
    "LedArtPixel",
    "LedArtPlan",
    "LedArtReportPaths",
    "LedArtSpec",
    "LedArtString",
    "LedArtTopologyComparison",
    "LedArtTopologyOption",
    "build_led_art_plan",
    "build_led_art_plan_for_topology",
    "compare_led_art_topologies",
    "select_led_resistor_ohms",
    "write_led_art_reports",
    "write_led_art_topology_comparison_reports",
]
