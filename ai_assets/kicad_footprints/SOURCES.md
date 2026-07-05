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
