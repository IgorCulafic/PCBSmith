# PCBSmith Phase 4C RC Filter Demo Design

## Goal

Phase 4C adds a third complete KiCad-native demo circuit: an RC low-pass filter. This broadens the example set with a capacitor-based circuit while staying inside the current supported component catalog.

## Scope

This phase supports deterministic requests for an RC filter or low-pass filter. It does not add arbitrary analog synthesis, frequency cutoff calculations, SPICE simulation, or new component families.

## Behavior

The demo planner emits:

- VCC as the input source;
- R1 with value `10k`;
- C1 with value `100nF`;
- GND;
- wires connecting VCC -> R1 -> OUT -> C1 -> GND;
- labels for `VCC`, `OUT`, and `GND`.

The KiCad exporter should render `OUT` as a visible label, because it is a human-facing signal name. Generated helper labels that use internal-style names such as `LED_A` remain hidden in the schematic preview.

## Testing

Tests should cover:

- RC/low-pass requests select the RC filter demo plan before the generic capacitor fallback;
- KiCad export includes resistor, capacitor, VCC/GND symbols and board footprints;
- `OUT` appears as a visible schematic label;
- the real KiCad review bundle validates and exports schematic and board SVG previews.
