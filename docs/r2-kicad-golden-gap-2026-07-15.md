# R2 serialized-KiCad authority gate: retained gap

Date: 2026-07-15  
Authority version: KiCad CLI 10.0.3

The R2.3b adversarial maze remains a geometry-level routing proof and is not a
legal production-board fixture. Its `~maze-wall` segments deliberately use a
net name absent from `BoardNetlist`; `render_board_from_layout` therefore cannot
assign them a KiCad net number. The walls are also zero-length copper segments
used as point obstacles by the grid test. Converting those points into physical
copper, footprints, or keepouts would change the maze capacities and would no
longer be the same proof. The fixture is consequently not serialized or called
exact KiCad DRC.

The strongest sound R2.4 gate currently feasible is a separate compact board
made from two real KiCad resistor footprints and one negotiated signal net. Its
test pins deterministic `.kicad_pcb` bytes with SHA-256, parses the result with
the repository S-expression and placement readers, verifies that every
non-route `BoardLayout` field survives negotiation, and optionally runs
`kicad-cli pcb drc` without schematic parity. The live result is reported only
when `PCBSMITH_R2_KICAD_GOLDEN=1`, `kicad-cli` is present, and its version is
exactly 10.0.3.

This compact case is a serialization and tool-authority gate. It is not evidence
that negotiated routing outperforms the legacy router, and it does not replace
the R2.3b every-order-fails maze proof. Closing the retained gap requires a new
adversarial fixture expressed entirely with legal board geometry (or a typed
keepout model), followed by a separately pinned KiCad DRC result.
