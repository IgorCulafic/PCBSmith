# Thermometer R006 3D-model pilot

Status: **visualization test passed; proxy geometry, not exact mechanical-fit evidence**.

R006 is a 3D-metadata-only derivative of the accepted R005 board. R005 remains
the production authority. The normalized copper SHA-256 is unchanged:
`ee94b7403448c254d02f05d8ca7966c48aa7002c2424d2e1d16ed1e38fbf05af`.

## Models

- U4 SHT31: the footprint's original Sensirion STEP reference does not exist in
  the installed KiCad 10.0.3 model library. R006 substitutes the bundled
  `DFN-8-1EP_3x3mm_P0.5mm_EP1.66x2.38mm.step`, scaled to 0.833333 in X/Y so
  the visible body is approximately 2.5 x 2.5 mm. This is a package proxy.
- J2/J3 OLEDs: each connector retains its exact 1x04 header model and adds the
  bundled `Adafruit_SSD1306.step` complete-module model. The module is scaled
  uniformly to 0.42 and offset by `(1.7, -1.2, 8)` mm to sit above the header
  inside the intended display area. The source model is for a larger Adafruit
  module and is therefore a visualization proxy, not the selected 0.49-inch
  module's exact mechanical model.

## Verification

- KiCad DRC: 0 violations.
- Unconnected items: 0.
- Schematic parity findings: 0.
- Preview generation: no findings.
- R005/R006 copper comparison: 666 copper objects, identical normalized hash.
- Visual inspection: both OLED boards/screens are visible in top and
  perspective renders; U4 now resolves and is visible when zoomed near the
  sensor isolation slot.

## Artifacts

- `Thermometer_R006.kicad_pro`
- `Thermometer_R006.kicad_sch`
- `Thermometer_R006.kicad_pcb`
- `Thermometer_R006-top.png`
- `Thermometer_R006-bottom.png`
- `Thermometer_R006-perspective.png`
- `drc.json`

Before using 3D geometry for enclosure or assembly clearance, replace both
proxy assets with exact manufacturer/module STEP files and retain their source,
license, SHA-256, dimensions, and deterministic transform in the component-card
3D asset contract defined by roadmap Track 6.5.
