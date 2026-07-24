# Thermometer R005 accepted proof-of-concept verification

The complete 66 x 178 mm thermometer PCB passed electrical, routing,
manufacturing, replay, and visual review. The 60 mm bulb is 2.5 times the
24 mm stem width, with black solder mask, white silkscreen, and ENIG finish
intent.

- Retention: 63 netlisted components, 64 board placements including H1,
  53 nets, and 189 pin nodes.
- Routing: all 53 nets, 567 segments, 99 vias, 2028.65 mm total track length,
  zero unrouted connections, and zero hard violations. The board used the
  legacy router; negotiated R2/R3 resource overuse was not measured and is not
  claimed.
- Replay: R004 and R005 have identical normalized copper SHA-256
  `ee94b7403448c254d02f05d8ca7966c48aa7002c2424d2e1d16ed1e38fbf05af`.
- ERC: zero machine violations and zero reader-schematic violations; reader
  netlist equality passed.
- Simulation: passed (`i_seg=5.58994 mA`, `v_f=1.79072 V`,
  `i_pwled=1.57870 mA`).
- Board checks: virtual DRC passed, all seven design checks passed, and KiCad
  DRC reported zero violations, zero unconnected items, and zero parity items.
- Repeated save: two KiCad save/DRC passes were byte-identical at SHA-256
  `ff466f09e184dee36cd6a6d0f20070d2f2772f1c537196a930d3afc083509ea8`.
- Software gates: 2546 pytest tests passed, 16 optional tests skipped; Ruff
  passed; strict mypy passed across 233 source files.
- Visual review: front, back, perspective, routing, and assembly images were
  inspected. The enlarged bulb, OLED envelopes, sensor isolation moat,
  antenna edge overhang, USB access, and routed copper are visually clean.

Operational reviews remain explicit: verify the purchased OLED modules use
the marked GND/VCC/SCL/SDA pin order, and keep Wi-Fi off or duty-cycled because
the AP2112 thermal budget targets the display workload rather than continuous
worst-case radio transmit. R006's SHT31/OLED 3D assets are visualization proxies,
not exact procurement or enclosure-fit evidence.
