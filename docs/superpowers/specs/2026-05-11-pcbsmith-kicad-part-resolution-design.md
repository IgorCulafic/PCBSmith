# PCBSmith KiCad Part Resolution Design

## Decision

PCBSmith catalog entries now carry optional KiCad bindings in addition to the current internal `stdlib` symbol and footprint ids.

This lets PCBSmith keep its stable internal command language while beginning to resolve real KiCad symbols and footprints from a KiCad library index.

## Scope

This step does not replace schematic export with direct KiCad library placement yet. It adds the foundation for that work:

- Catalog entries can declare KiCad symbol ids such as `Device:R`.
- Catalog entries can declare KiCad footprint ids such as `Resistor_SMD:R_0603_1608Metric`.
- Virtual power symbols can resolve to KiCad symbols without footprints.
- A resolver checks catalog bindings against a generated KiCad library index.
- The resolver is available from the CLI for debugging and future AI context.

## Warning Cleanup

PCBSmith validation reports filter generated-symbol library mismatch warnings from the stored ERC JSON report. These warnings are expected while the exporter still embeds generated symbols and are not useful for user-facing review bundles. Real KiCad-backed placement remains the next step that will remove this class of warning at the source.

## Acceptance Test

- Resistor, LED, and power catalog entries expose KiCad bindings.
- A library index containing matching KiCad ids resolves a catalog entry as available.
- Missing symbols or footprints are reported clearly.
- Generated proposal bundle reports show zero ERC/DRC violations after filtering known generated-symbol mismatch noise.
