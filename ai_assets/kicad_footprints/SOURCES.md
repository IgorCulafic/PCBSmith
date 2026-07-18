# Vendored KiCad footprints

Copied verbatim from the official KiCad 10.0.3 footprint library
(`C:\Program Files\KiCad\10.0\share\kicad\footprints`), which is the
reference implementation of polarity silkscreen and courtyard geometry
(rules 8.1/8.4 in docs/pcb-design-rules.md). Licensed under the KiCad
libraries licence (CC-BY-SA 4.0 with exception). File names encode the
library: `<Library>__<Footprint>.kicad_mod`.

Vendored so board generation and tests are deterministic and work without
a KiCad installation; `pcbsmith.kicad.library` falls back to the installed
share directory for footprints not vendored here.

- `Package_TO_SOT_SMD__SOT-23.kicad_mod`, `Connector_PinHeader_2.54mm__PinHeader_1x03_P2.54mm_Vertical.kicad_mod`, `NetTie__NetTie-2_SMD_Pad2.0mm.kicad_mod` - copied from the official KiCad 10.0 footprint library (share/kicad/footprints) for the metal detector slice (BJT, 3-pin header, coil-terminal net tie).
- `Test__ReducedCapacityTwoStemTerminal.kicad_mod` - locally authored minimal
  one-pad SMD fixture matching `tests/fixtures/routing/reduced_capacity_two_stem.py`;
  used only to make the synthetic placement save/read-back acceptance test
  deterministic without live KiCad library access.
