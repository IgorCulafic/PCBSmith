# Flyback dual-side compaction experiment (2026-07-10)

Track 8.2 follow-up: shrink the 88 x 50 mm flyback r002 toward the
FLBACK-001 reference (80.4 x 36.8 mm) using the reference's key
construction move — the ENTIRE SMD control circuit on the bottom side —
with `placement_search`'s new rotation/side moves and `route_board`
producing every trace. Experiment script: `tools/flyback_compaction.py`
(deterministic, reproducible; writes the board + a JSON report).

## Result

| | r002 (current golden) | this experiment | FLBACK-001 |
|---|---|---|---|
| Board | 88 x 50 mm (4400 mm²) | **80 x 42 mm (3360 mm²)** | 80.4 x 36.8 mm (2958 mm²) |
| Assembly | single-side | **dual-side** (14 SMD parts on the back) | dual-side |
| Routing | hand waypoints | **100% route_board (A*)**, 665 mm / 8 vias | hand (Altium) |
| Verification | virtual DRC + kicad-cli | virtual DRC 0 findings; **kicad-cli DRC 0 violations, 0 unconnected** (lib_footprint_mismatch excluded — the pipeline's project config ignores that class); isolation-barrier blocker checks clean | n/a |

Back side carries U1/CV1/RP1/D5/D6 (primary control) and
D7/CO1/CO2/U3/RFB1/RFB2/RO1/RO2/CF1 (secondary), exactly the
reference's split. Barrier at x = 51 with the standard 6.4 mm creepage
group; T1/U2/CY1 straddle.

## Why not 36.8 mm tall

Our transformer is a TEZ-22x24 (24.5 x 22.5 mm courtyard); FLBACK-001
uses an EFD20/10/7. The barrier band is fully occupied by T1 from
y = 12.75 to 37.25, and the straddle parts (U2, CY1) must fit above it.
40 mm was achievable for courtyards but left no slack for the 1.5 mm
HV pad clearance class around the through-hole field; 42 mm routes
clean. Matching the reference's height requires adopting an
EFD20-class transformer — a component change, not a layout change.

## What the experiment forced into the permanent machinery

- **fp_rect courtyards were invisible to the virtual DRC**
  (`kicad/library.py`): a rect parses as its two diagonal corners, the
  convex hull of two points is a line, and the hull was discarded —
  so terminal blocks, D9 discs, and solder-wire pads had NO courtyard
  model and kicad-cli caught two overlaps (E1/J1, CC1/BR1) the
  pre-gate had passed. Fixed by expanding fp_rect to four corners;
  regression test in `test_conventions.py`; golden re-run green.
- Unused transformer THT pins wall in SMD pads parked next to them
  (D7, RO1 both hit this) — already a documented rule; the experiment
  re-confirmed it applies to BACK-side SMD against THT annuli.
- Back-side reference labels transform as INVERSE rotation then
  x-mirror; three labels (RFB1/RFB2/D7) needed live-DRC round trips
  because the virtual text model underestimates by design.

## Status and what is left before this can be flyback r003

Experiment only — the golden flyback still generates the 88 x 50
hand-routed r002. To promote:

1. Silkscreen production pass: the barrier line + ISOLATION/DANGER/HV
   markings (rule 10.2) and component value texts are NOT drawn here;
   the r002 board's silk graphics need re-placement for the new floor
   plan, with the probe -> kicad-cli loop for dense silk.
2. `climb_placements` polish run (rotation/side/nudge local search)
   to shave track length and possibly height.
3. Wire into `flyback_board.py` / the authority as r003, regenerate
   the full evidence/review bundle, add to golden.
