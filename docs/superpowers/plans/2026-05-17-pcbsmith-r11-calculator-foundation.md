# PCBSmith R11 Calculator Foundation Plan

## Goal

Create a dedicated calculator layer so engineering math lives in source-controlled
tools instead of one-off board scripts or LLM freehand arithmetic.

## Scope

- Add `src/pcbsmith/calculators/` as the calculator package.
- Add `tests/unit/calculators/` as the matching test home.
- Implement first metal-detector-critical calculators:
  - `pcb-spiral-coil-estimate`;
  - `lc-resonance`.
- Expose calculators through the CLI and AI planner/context packages.
- Update docs so future work uses the calculator package rather than duplicating
  math in generators.

## Formula Notes

`pcb-spiral-coil-estimate` uses the modified Wheeler expression from Mohan,
Hershenson, Boyd, and Lee's planar spiral inductor paper:

`L = K1 * mu0 * n^2 * d_avg / (1 + K2 * rho)`

where `rho = (d_outer - d_inner) / (d_outer + d_inner)`. The initial coefficient
table supports square, hexagonal, octagonal, and circular spirals. The returned
inductance is an estimate, not a substitute for empirical validation.

`lc-resonance` uses the ideal LC relation:

`f = 1 / (2 * pi * sqrt(L * C))`

## Verification

- Unit tests cover valid spiral output, impossible geometry, LC frequency, LC
  capacitance solve, AI tool contract, and CLI formatting.
- Integration test covers `pcbsmith calculator pcb-spiral-coil-estimate`.
