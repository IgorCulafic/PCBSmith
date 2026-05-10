# PCBSmith Phase 4B Voltage Divider Demo Design

## Goal

Phase 4B proves the KiCad-first AI flow can generate more than one complete circuit. The new supported demo request is a voltage divider: VCC into two series resistors, an OUT node between them, and GND at the lower end.

## Scope

This phase adds one deterministic example circuit and improves board rendering enough to support horizontal two-pin chains generically. It does not add arbitrary placement, autorouting, a real LLM provider, or broad circuit synthesis.

## Behavior

When the request mentions a voltage divider, the demo planner emits:

- VCC power symbol;
- R1 with value `10k`;
- R2 with value `10k`;
- GND power symbol;
- wires connecting VCC -> R1 -> OUT -> R2 -> GND;
- labels for `VCC`, `OUT`, and `GND`.

The KiCad exporter should generate:

- a readable native KiCad schematic;
- a board with two resistor footprints, VCC/GND terminal pads, net declarations, and copper segments for every net that connects two generated board pads;
- exported schematic and board SVG previews through the existing review bundle.

## Design Notes

The Phase 4A board renderer had LED-specific segment placement. Phase 4B replaces that with a small net-to-pad routing step:

1. Place non-power footprints in a deterministic horizontal row.
2. Place VCC and GND terminal pads at the left and right edges.
3. Record each generated pad coordinate and its net.
4. For each net with two or more generated pads, draw straight F.Cu segments between adjacent pads.

This remains a simple review layout, not a PCB router. It is enough to generate stable KiCad-native examples and training data while keeping KiCad as the renderer and validator.

## Testing

Tests should cover:

- voltage-divider requests select the voltage-divider demo plan;
- the plan has the expected four symbols, three wires, and three labels;
- exported KiCad board text includes the `OUT` net and an `OUT` copper segment;
- real KiCad review bundle validation passes and exports both SVG previews.
