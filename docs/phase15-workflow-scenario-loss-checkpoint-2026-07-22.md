# Phase 15 workflow, scenario, and loss checkpoint

Date: 2026-07-22

Status: second implementation slice complete; engineering release remains blocked

## Outcome

The first Phase 15 implementation slice is complete. It replaces informal
workflow expectations and isolated arithmetic with four reusable authorities:

1. a versioned workflow-conformance profile with D0-D4 deviation handling;
2. a typed engineering-evidence register with source hash, page locator, test
   conditions, and applicability notes;
3. a typed operating-scenario/mission-profile matrix and coverage gate; and
4. a physical-identity loss/stress ledger that prevents double counting and
   refuses to turn missing inputs into zero watts.

The shared visual-review generator now emits and audits `review/conformance.json`.
Objective board facts strengthen caller declarations, so bottom population,
holes, vias, zones, and keepouts cannot be hidden by a false feature flag.
Inspection cannot accept a nonconformant package.

## R002 exercise

BLDC ESC R002 retains its custom `review-images/` as D0 supplemental evidence
and now also has the canonical `review/` package. The canonical package has 46
indexed artifacts and is workflow-conformant. Visual inspection marked six
back-side design/assembly/tile artifacts for crowded overlapping component text,
so the authoritative manifest remains `attention_required`.

The engineering bundle under `outputs/bldc-esc-60a-r002/evidence/` contains:

- `engineering-evidence-register.json`;
- `operating-scenarios.json`;
- `scenario-coverage.json`;
- `loss-stress-ledger.json`;
- `loss-coverage.json`;
- `electrothermal-network.json`;
- `electrothermal-result.json`;
- `cooling-assembly-profile.json`;
- `cooling-assembly-evaluation.json`;
- `transient-thermal-model.json`;
- `transient-thermal-result.json`; and
- `engineering-readiness.json`.

The mission profile contains startup, 30 A prototype, 60 A continuous target,
100 A/10 s peak target, stall, regenerative overvoltage, hot plug, short
circuit, cooling loss, and shutdown scenarios. Target numbers are not treated
as released capabilities. Ambient, airflow velocity, enclosure, orientation,
mission duty, fault magnitude, and clearing-time gaps remain explicit.

## Retained component facts

The exact retained PDFs were resolved by their existing authority hashes and
visually inspected before facts were encoded:

- Infineon IPTC011N08NM5 Rev. 2.0, SHA-256
  `e30473eeb2699eb28ad595b93dac5846efee85ad0364b56eeffd3a42da8a0222`;
- Vishay WSLP2726 Rev. 29-Jun-2026, SHA-256
  `1c3385e4b14f07808333c026393b88e0da1c23671fbb30e66a3fb86e3960a337`.

Two retained Infineon application guides were also visually inspected for the
cooling-assembly and MOSFET-applicability rules:

- Package and mounting-assembly guide, SHA-256
  `577388400a5e888a869b81a7cf9d4f494cdda874a233a2b806ee17b75966ac71`;
- Designing with power MOSFETs, SHA-256
  `4b94b144f51a63300da52def2d882b41c2851abf589d81e2cde3514699b52fae`.

They support the need to model contact resistance, TIM, mounting pressure,
isolation, complete junction-to-ambient paths, avalanche margin, and practical
loss/temperature limits. Package-specific example clamp-force numbers were not
copied into R002 because they are not an exact requirement for the selected
TOLT device and assembly.

The register includes MOSFET breakdown minimum, 25 C/10 V RDS(on), total gate
charge, junction-to-case thermal resistance, reverse-diode forward voltage,
and shunt resistance tolerance, element-to-terminal thermal resistance, and
conditional power rating. Every fact carries the datasheet conditions. In
particular, room-temperature RDS(on) is not relabelled as hot RDS(on), the
typical-only temperature curve is not promoted to a guaranteed maximum, and
the shunt's 12 W class is not an unconditional operating limit.

## Numeric scope and newly exposed ambiguity

The original request says 60 A continuous and 100 A peak, but does not define
DC-bus current, motor line RMS, or phase peak current. Earlier shunt arithmetic
silently interpreted those values as current through one inline phase shunt.
The new authority preserves that only as the named conservative assumption
`assumption:esc-current-is-phase-shunt-rms-r1`.

With the selected 0.5 milliohm, +/-1% shunt at its room-temperature tolerance,
the retained I-squared-R intervals are:

| Assumed phase-shunt RMS current | Loss interval |
| --- | --- |
| 30 A | 0.4455 W to 0.4545 W |
| 60 A | 1.782 W to 1.818 W |
| 100 A | 4.95 W to 5.05 W |

These numbers do not prove shunt temperature or rating. Hot resistance, PCB
heat rejection, pad/terminal temperature, and mission duty remain unresolved.

MOSFET conduction now has a deliberately provisional numeric screen. The
guaranteed 25 C maximum RDS(on) is multiplied by a manually bounded 1.9-2.0
reading of the datasheet's typical-only 175 C curve, then by an explicit 2/3
aggregate phase-leg-pair conduction fraction for preliminary six-step
commutation. This produces:

| Assumed phase RMS current | Phase-U MOSFET-pair conduction screen |
| --- | --- |
| 30 A | 1.254 W to 1.320 W |
| 60 A | 5.016 W to 5.280 W |
| 100 A | 13.933 W to 14.667 W |

These entries are `validation_required`, not computed release losses, and
therefore cannot satisfy loss coverage. The current definition, PWM/commutation
waveform, guaranteed hot resistance, and electrothermal convergence still have
to be established. Switching, gate-drive, and body-diode/dead-time losses
remain non-numeric. Connector, PCB copper, and capacitor ESR losses likewise
wait for routed geometry and condition-matched part data.

## Cooling and transient authority

The retained R002 board hash now binds a typed cooling profile. The exact
Infineon power package is distinguished from six geometry-only TIM envelopes,
one geometry-only heatsink, four support-hole/clamp proxies, an unselected
isolation system, and an unselected air mover. Six package-to-TIM interfaces
explicitly require contact Rth, clamp force, electrical isolation, and
withstand authority. The evaluation correctly remains `incomplete`; visual
solids and hole locations cannot establish an orderable or qualified assembly.

A deterministic point-valued Foster step-response solver is implemented and
unit-tested. The R002 100 A/10 s model remains `indeterminate`: ambient and
total switch-pair loss are unresolved, and no reviewed Zth graph digitization,
Foster fit, or correlated assembly transient model exists. The solver never
substitutes interval nominal values or invents a Zth fit.

## Verification

The existing 46-test first-slice verification remains green. The second slice
adds 20 focused passing tests across loss screening, cooling assembly,
steady/transient thermal solving, and the BLDC evidence writer. Repository-wide
verification passed 2,707 tests with 17 skipped and one known Pydantic
serialization warning in 746.94 seconds. Ruff passed repository-wide.

## Next bounded slice

The deterministic point-input nodal engine and explicit Phase-U topology are
now implemented. Its unit fixture solves a known 4 W, 2 K/W plus 3 K/W series
path from 25 C to a 45 C junction. The R002 instance correctly returns
`indeterminate` without node temperatures because its loss and physical
boundary inputs are incomplete.

The Phase-U nodes and fail-closed steady/transient solver foundations now exist.
Complete the electrical and physical inputs and couple loss to temperature. It
must:

1. consume the mission-profile and loss-ledger fingerprints;
2. keep every resistance/capacitance and boundary condition source-bound or
   explicitly assumed;
3. iterate temperature-dependent loss and temperature to convergence;
4. support steady-state and the 10 s peak using transient impedance only when
   its applicability is encoded;
5. return indeterminate when airflow, clamp pressure, TIM thickness/contact,
   routed copper, or loss inputs are missing; and
6. remain unable to release current or thermal claims until correlated test
   evidence exists.
