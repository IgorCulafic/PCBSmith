# Phase 15 engineering implementation report

Date opened: 2026-07-22

Status: active living report

## Purpose

This report is the durable human/AI handoff for the Phase 15 multi-physics and
engineering-authority implementation. It records what was implemented, why it
was bounded that way, which sources and assumptions were used, what failed
closed, and what work remains. It supplements the checkbox roadmap; it does not
replace machine-readable evidence or verification output.

## Current board exercise

The active exercise is BLDC ESC R002 under
`outputs/bldc-esc-60a-r002/`. The board is a four-layer, unrouted thermal and
mechanical placement candidate. Its exact retained board hash is
`bd82a1372280227947f0568f1aa0097c1863f579d72f570acab5fa4344b6fc22`.
It must not be described as fabrication-ready, thermally adequate, or capable
of 30 A, 60 A, or 100 A operation.

## Completed implementation

### Workflow and evidence

- Shared visual-package conformance and D0-D4 deviation governance are active.
- R002 has a canonical conformant review package while its board-specific
  thermal views remain D0 supplemental evidence.
- Typed source facts retain source identity, SHA-256, page locator, conditions,
  and applicability limits.
- Operating scenarios cover startup, normal, peak, stall, regeneration,
  hot-plug, short-circuit, cooling loss, and shutdown.

### Loss and thermal authority

- Phase-shunt I-squared-R is bounded at 30 A, 60 A, and 100 A under an explicit
  phase-shunt-RMS current interpretation.
- Phase-U MOSFET-pair conduction has a `validation_required` screening interval
  using the guaranteed 25 C RDS(on) maximum, a manually bounded typical-only
  175 C multiplier, and an assumed aggregate six-step conduction fraction.
  A later gate-drive applicability check found that this interval is valid only
  under its stated 10 V VGS condition and cannot be applied across the retained
  9 V minimum-bus scenario.
- The steady thermal network has explicit junction/package/TIM/spreader/sink/
  PCB/ambient nodes and returns `indeterminate` rather than substituting
  nominal values for missing inputs.
- A point-input Foster step solver exists. R002's 100 A/10 s result remains
  `indeterminate` without ambient, total loss, and a reviewed/correlated Zth
  fit.
- A typed cooling-assembly profile distinguishes the exact selected MOSFET from
  geometry-only TIM, heatsink, clamp/support, isolation, and air-mover records.
  Six package interfaces remain incomplete.
- A separate cooling-candidate register retains sourced TIM, extrusion, and fan
  candidates without promoting them to selected parts. Candidate coverage is
  incomplete because no clamp/fastener candidate exists, and all three retained
  candidates require vendor confirmation or system validation.
- A deterministic point-input coupled electrothermal solver iterates
  temperature-dependent resistance, I-squared-R loss, fixed loss, and junction
  temperature. It rejects unresolved/interval inputs and detects an unstable
  linearized feedback loop. The R002 instance remains `indeterminate`.
- A minimum-bus gate-drive profile binds the actual VM-to-BAT_P topology, TI
  driver guarantees, and Infineon's lowest tabulated RDS(on) VGS condition. It
  returns `inadequate` at 9 V input.
- Gate-charge capacity and dead-time authorities now exist separately from the
  VGS check. Gate-charge capacity aggregates Qg-times-frequency by high-side and
  low-side switching-group counts; R002 returns `indeterminate` because the
  retained firmware does not define which devices receive PWM simultaneously.
  IDRIVE remains a separate edge-rate input. Dead time is also `indeterminate`
  without the programmed register value, bounded turn-off, propagation
  mismatch, and reviewed timing margin.
- A typed gate-supply option report compares the retained 9 V topology, a 10 V
  minimum-input amendment, separate regulated 12 V and 15 V VM rails, and a
  native-bus DRV8334 replacement. It recommends the DRV8334 for the next design
  iteration while retaining `selection_state: not_selected`.
- A non-selecting migration authority now fixes the exact reviewed candidate as
  `DRV8334RGZR`, retains all 49 package-pad assignments, and classifies each
  functional change from the DRV8353. The pin map is complete, but the result is
  `conditional_candidate`, not an implemented schematic change.

## Retained source decisions

The current implementation uses these pinned sources:

| Source | SHA-256 | Use |
| --- | --- | --- |
| Infineon IPTC011N08NM5ATMA1 datasheet | `e30473eeb2699eb28ad595b93dac5846efee85ad0364b56eeffd3a42da8a0222` | Exact MOSFET electrical/package facts and typical curves |
| Vishay WSLP2726L5000FEA datasheet | `1c3385e4b14f07808333c026393b88e0da1c23671fbb30e66a3fb86e3960a337` | Shunt resistance and conditional thermal/power facts |
| Infineon package-assembly guide | `577388400a5e888a869b81a7cf9d4f494cdda874a233a2b806ee17b75966ac71` | Contact resistance, TIM, pressure, isolation, and assembly-validation mechanisms |
| Infineon Designing with Power MOSFETs v1.1 | `4b94b144f51a63300da52def2d882b41c2851abf589d81e2cde3514699b52fae` | Loss, temperature, SOA/avalanche, and complete thermal-path applicability |
| Infineon TOLT package application note v1.1 | `1f3e5659896485157124bee19163528b1ca10d2c00c3c34ca23b4a136ccbf3c6` | TOLT top potential, TIM, force, flatness, support, and validation constraints |
| Henkel BERGQUIST SIL PAD TSP A2000 TDS | `f6e3207f2ebdfc0c6a5c263c1c3e2277134606922c80eb105875fa550e71002c` | Isolating TIM candidate; typical/reference values only |
| Boyd MaxClip extrusion catalog, profile 78045 | `331a7fd3e836e27da6bcf8e3decdc413acb73d72fc98b87940c42c2ea12f8314` | Extrusion candidate and condition-specific catalog screening |
| Delta AUB0405VD-00 datasheet | `db4fb38a4a37e03e32e83a600a05dbb6ac97b0ac7fa25019a4fc45af61507b01` | Forced-air candidate and endpoint fan data |
| TI DRV8353 datasheet, Revision D | `f440d3fae4c79d04078679ee6f3122d9aae2e169833a577fd993780204c3849e` | VM-dependent gate-voltage bounds, drive current, dead time, and protection context |
| TI DRV8334 datasheet, Revision B | `cbd131d62e0eb44f1e18b9ded61d296bfd789451674e5305a637c2c0a3fa9ecc` | Native 9 V gate-driver alternative, regulated GVDD, current sensing, diagnostics, and timing |
| Vishay 7KPD10A-7KPD70A datasheet, 05-Dec-2025 | `6b6ac7931656bd87412967f26e2d71455f3f4e578513ea395c639240fea91c90` | Exact 7KPD26A standoff, breakdown, conditional clamp/current, pulse, and thermal context |

Two installed KiCad 10 assets were also hash-pinned as geometry candidates:

| Local asset | SHA-256 | Status |
| --- | --- | --- |
| `Package_DFN_QFN:Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm` | `739d7f90af78d0a6076f7f0d7f699f1729aca5fea3f7e8871c2d3ee9a4732d2f` | Body, pitch, pin count, and exposed-pad geometry candidate; land/paste release review still required |
| `Package_DFN_QFN.3dshapes/Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm.step` | `e9db0afa44d256cc5824b646bd84781f9960a1e23484fcee1060e6055c441674` | Resolved exact-package-style model candidate with zero footprint transform |

Package-specific example clamp-force figures from the general assembly guide
were not copied as requirements for the selected TOLT device. Typical graphs
are not promoted to guaranteed limits.

All newly used manufacturer PDFs were obtained through the repository's
automatic source-intake path. The public manifest is
`docs/reference/data/phase15-cooling-source-intake-2026-07-22.json`; exact
payloads remain in the private local cache according to their rights status.

## Critical gate-drive applicability finding

The retained schematic connects both DRV8353 VM and VDRAIN to BAT_P. At the
specified 9 V minimum input, the driver datasheet guarantees 5.5 V minimum
high-side VGS and 6.5 V minimum low-side VGS. The selected MOSFET's lowest
tabulated RDS(on) condition is 6 V, while the earlier hot-resistance screen used
the 10 V condition. Consequently:

- the high-side device is below even the lowest characterized RDS(on) gate
  voltage in the guaranteed worst case;
- the low-side device clears 6 V with only 0.5 V characterization margin;
- neither channel has authority for the earlier 10 V RDS(on) calculation at
  the 9 V bus point; and
- switching-time and loss calculations remain blocked until actual IDRIVE,
  dead-time configuration, and transition behavior are established.

This does not prove the hardware would immediately fail. It proves that the
present evidence cannot support its loss or current-capability claims over the
requested input range. The design needs a deliberate choice: provide a
regulated gate-driver supply, change driver/device architecture, or narrow the
input specification and re-evaluate all voltage corners. No silent schematic
change has been made because that choice materially changes the product.

## Gate-supply architecture decision

The machine-readable option report is
`outputs/bldc-esc-60a-r002/evidence/gate-supply-decision.json`.
It uses a preliminary one-volt guaranteed margin above the chosen MOSFET
RDS(on) characterization voltage. Its current conclusions are:

| Option | Voltage result | Overall state | Key reason |
| --- | --- | --- | --- |
| Retained DRV8353 at 9 V VM | inadequate | infeasible | High-side worst-case VGS is 0.5 V below the 6 V characterization floor |
| Raise minimum bus to 10 V | inadequate | infeasible | High-side worst case only reaches 6 V, leaving zero policy margin |
| Separate regulated 12 V VM | adequate | conditional candidate | Clears the 6 V condition by 1.5 V but adds a buck-boost rail and its fault/EMI/sequence obligations |
| Separate regulated 15 V VM | adequate | conditional candidate | More margin, but more gate energy/edge risk and still no guaranteed 10 V high-side condition |
| Replace DRV8353 with DRV8334 | adequate | preferred conditional candidate | At 9 V bus, GVDD is bounded 11.5–13.5 V and the 10 mA high-level drop is at most 0.2 V |

The DRV8334 option therefore guarantees at least 11.3 V at the gate-output
high level under the inspected conditions, clearing the MOSFET's 10 V RDS(on)
condition by 1.3 V. It also avoids a separate buck-boost gate rail. This is an
engineering recommendation, not approval to replace U2: the exact orderable
candidate and proposed pin map are now reviewed, but the land/paste pattern,
bootstrap/charge-pump network, CSA range, protection mapping, register defaults,
PWM/dead-time behavior, 60 V transient derating, placement/routing, sourcing,
and validation remain open.

The gate-charge review was also corrected. Qg-times-frequency is an aggregate
average-current check for all simultaneously switching devices served by each
high-side/low-side supply group; it is not a comparison with peak IDRIVE. The
per-switch upper demand is 6.69 mA at 223 nC and 30 kHz, but the aggregate
result cannot pass until the actual six-step PWM strategy bounds the number of
simultaneously switching high-side and low-side devices.

## DRV8353-to-DRV8334 migration feasibility

The exact candidate screen now uses the active-production `DRV8334RGZR` in the
48-pin, 7 mm by 7 mm, 0.5 mm-pitch RGZ VQFN package. Relative to the retained
40-pin, 6 mm by 6 mm DRV8353 package, it adds eight signal pins and increases
nominal body area by about 36.1%. It is therefore explicitly non-drop-in.

The migration profile covers all signal pins plus the exposed pad and records:

- retained/remapped six-phase gate outputs, source/switch-node senses, PWM,
  three CSAs, SPI, fault, supply, and reference functions;
- a behavioral split of the old `ENABLE` function into `nSLEEP` and the new
  independent active-high `DRVOFF` control;
- three new bootstrap networks, a new trickle-charge-pump flying capacitor,
  new GVDD/PVDD/VDRAIN bypass obligations, and changed charge-pump values;
- retirement review for the DRV8353 `DVDD` output; and
- a distinct thermal-ground treatment for the exposed pad.

KiCad 10 already contains a dimensionally compatible Texas RGZ footprint and a
matching resolved STEP model, so this candidate does not require an immediate
third-party CAD download. The footprint is still only a geometry candidate:
its IPC-style land extension and paste strategy must be checked against the
selected assembler and TI's package drawing before release. The complete
machine-readable profile and evaluation are
`gate-driver-migration-profile.json` and `gate-driver-migration-report.json`.
No schematic, PCB, firmware, or BOM was changed.

The first support-network calculation is now explicit. TI's DRV8334 rule is
`CBST > 20 * Qg / (VGHx - VSHx)`. With the retained MOSFET's 223 nC upper gate
charge and the candidate driver's 11.3 V lower gate-amplitude bound, each phase
requires more than 394.69 nF effective bootstrap capacitance. TI's nominal 1 uF
recommendation is plausible, but the machine result remains `indeterminate`
until a selected capacitor retains at least that effective capacitance after
DC bias, tolerance, temperature, and aging. Nominal marking alone cannot pass.

## Gate-driver support-network authority

The DRV8334 redesign now has an explicit ten-capacitor physical inventory:
PVDD and GVDD bypass, main and trickle charge-pump flying capacitors, VCP and
VDRAIN bypass, one bootstrap capacitor per phase, and VREF bypass. Each record
retains its source terminal pair, effective-capacitance requirement, maximum
applied voltage, placement obligations, exact MPN, and footprint.

This is intentionally an `incomplete` definition and `blocked` implementation.
No exact capacitor MPN or footprint has been selected. The PVDD, VCP, and
VDRAIN maximum applied-voltage bounds are also unresolved because regeneration
and hot-plug behavior is not bounded. Consequently, a placement-capacity study
based on assumed 0603/0805 packages would be false precision. It can begin only
after the voltage/derating screen yields exact packages.

## Protection and surge-clamp foundation

The first protection-coordination authority maps nine event requirements to
eight declared paths. It covers stall, shoot-through, phase short, battery or
bus short, reverse polarity, regenerative bus rise, hot plug, gate-drive fault,
and cooling/overtemperature. The paths include DRV8334 VDS, RSENSE, VGS and
thermal functions; MCU current and bus-voltage responses; phase NTC firmware;
and the passive bus TVS. A path qualifies only when its threshold, detection and
shutdown latency, residual energy, required action, and independent domain are
all bounded. Every R002 requirement remains `incomplete`.

Two important absences are now explicit rather than implicit: no battery/bus
fault-current interrupter and no reverse-polarity blocking path are declared.
The existing TVS cannot substitute for either function.

The exact Vishay 7KPD26A datasheet was retrieved through the allowlisted,
hash-verified source-intake service. The part has 26 V reverse standoff, while
the requested 6S fully charged maximum is 25.2 V, leaving only 0.8 V physical
headroom before any tolerance or policy margin. Its 28.9-31.9 V breakdown range
is specified at 5 mA and 25 C. The 42.1 V maximum clamp point is associated
with 166 A under the non-repetitive 10/1000 us qualification waveform.

The new surge-clamp evaluator therefore remains `indeterminate`. It requires a
reviewed normal-voltage margin, the minimum derated voltage limit of every
protected BAT_P component, event current and energy, waveform/temperature
applicability, and repetition behavior. It explicitly refuses to calculate a
universal joule rating by multiplying the 7 kW headline by pulse duration.

## Current machine-readable outcome

- Engineering readiness: `incomplete`
- Scenario coverage: `incomplete`
- Loss coverage: `incomplete`
- Steady electrothermal solve: `indeterminate`
- Cooling assembly: `incomplete`
- Cooling candidates: `incomplete`
- Minimum-bus gate drive: `inadequate`
- Gate-charge capacity: `indeterminate`
- Dead-time adequacy: `indeterminate`
- Gate-supply recommendation: `change-driver-drv8334-native-9v`
- Gate-supply selection: `not_selected`
- Gate-driver migration: `conditional_candidate`
- Exact candidate: `DRV8334RGZR`
- Candidate selection: `not_selected`
- DRV8334 bootstrap sizing: `indeterminate` (selected effective capacitance missing)
- DRV8334 support definition: `incomplete` (ten physical capacitors)
- DRV8334 support implementation: `blocked`
- Protection coordination: `incomplete` (nine requirements, eight declared paths)
- Surge-clamp coordination: `indeterminate`
- Coupled electrothermal solve: `indeterminate`
- Transient thermal solve: `indeterminate`
- Cooling requirements unsatisfied: TIM, heatsink, clamp, isolation, air mover
- Incomplete cooling interfaces: six

The engineering bundle currently contains 34 authority artifacts under
`outputs/bldc-esc-60a-r002/evidence/`.

## Verification checkpoint

The second implementation slice passed:

- Ruff repository-wide;
- 20 focused engineering tests; and
- 2,707 repository tests with 17 skipped and one known Pydantic serialization
  warning in 746.94 seconds.

The current integration checkpoint passed:

- repository-wide Ruff;
- strict mypy across all 271 production source files;
- 30 focused engineering tests plus 32 targeted KiCad/ESC regression tests;
- all 2,734 collected repository tests: 2,717 passed and 17 intentional skips;
  and
- the one previously known Pydantic adversarial-serialization warning only.

The retained full-test log is under
`.pcbsmith/verification/phase15-gate-cooling-coupled-2026-07-22/`.

The gate-driver migration/bootstrap integration checkpoint also passed:

- repository-wide Ruff;
- strict mypy across all 274 production source files;
- 15 focused gate-drive, migration, bootstrap, and evidence tests; and
- all 2,741 collected repository tests: 2,724 passed and 17 intentional skips
  in 731.99 seconds, with the same known adversarial Pydantic serialization
  warning only.

The current logs and collection inventory are under
`.pcbsmith/verification/phase15-driver-migration-2026-07-22/`.

The support-network and protection-foundation checkpoint passed:

- repository-wide Ruff;
- strict mypy across all 277 production source files;
- 23 focused gate-driver, support, protection, surge-clamp, and evidence tests;
- all 2,749 collected repository tests: 2,732 passed and 17 intentional skips
  in 688.12 seconds; and
- the same single known adversarial Pydantic serialization warning only.

The retained full-test logs are under
`.pcbsmith/verification/phase15-support-protection-2026-07-22/`.

The first repository-wide mypy run exposed 25 type errors in four existing
KiCad modules. They were resolved without changing intended behavior by adding
explicit list/type narrowing for parsed S-expressions and GLB JSON, preserving
optional LED-output narrowing, and typing mixed numeric/string custom-symbol
pin maps. Targeted tests were repeated after those corrections.

## Active work

1. Resolve the gate-supply architecture at the 9 V input corner before using a
   MOSFET RDS(on) value in a scenario-wide loss or thermal calculation.
   The current recommendation is the reviewed `DRV8334RGZR` candidate, pending
   user selection and closure of its land-pattern, support-network, placement,
   firmware, protection, sensing, timing, transient, and validation obligations.
2. Convert cooling candidates to selected parts only after exact configuration,
   machining, tolerance, pressure, isolation, pressure-flow, and failure-state
   requirements are closed. Select a clamp/fastener candidate.
3. Supply bounded ambient, applicable hot RDS(on), complete fixed loss, and
   junction-to-ambient authority so the R002 coupled model can run.
4. Extend switching and dead-time screening only where source conditions can be
   represented explicitly. Leave avalanche, fault energy, and release limits
   unresolved when the required motor, waveform, parasitic, or protection data
   is absent.
5. Select and coordinate battery fault interruption and reverse-polarity
   protection; derive TVS current/energy from source impedance, bus capacitance,
   motor regeneration, wiring, and the actual shutdown waveform.

## Standing decisions

- Visual models and envelope dimensions are planning evidence, not thermal or
  mechanical qualification.
- A shared heatsink requires explicit surface-potential mapping, isolation
  construction, withstand/creepage review, clamp-force distribution, and
  common-mode-capacitance consideration.
- Forced airflow requires a fan and system operating point, pressure-flow
  interaction, duct/enclosure definition, and loss-of-airflow behavior.
- Solver output remains unverified until prediction-to-measurement correlation
  is retained with instrumentation and uncertainty records.
- Work proceeds in bounded vertical slices; incomplete physics is exposed as
  missing authority rather than filled with optimistic defaults.

## Change log

- 2026-07-22: Opened after the workflow/scenario/loss, cooling-assembly, and
  steady/transient thermal foundations passed full repository verification.
- 2026-07-22: Added automatic cooling/driver source intake, typed cooling
  candidates, minimum-bus gate-drive adequacy, and coupled electrothermal point
  iteration. Recorded the 9 V high-side VGS blocker and limited the earlier
  10 V conduction calculation to a conditional screen.
- 2026-07-22: Added explicit screening applicability conditions, gate-charge
  capacity, and dead-time authorities; regenerated the 22-file R002 engineering
  evidence bundle; restored strict repository-wide mypy; and passed the full
  2,734-test integration checkpoint.
- 2026-07-22: Corrected Qg-times-frequency authority from a peak-IDRIVE model to
  an aggregate high/low supply-group model; added a sourced five-option
  gate-supply decision; and recommended a native-bus DRV8334 redesign without
  promoting it to selected hardware.
- 2026-07-22: Fixed the exact DRV8334RGZR candidate, added a complete 49-pad
  proposed migration map, classified nine functional migration groups, pinned
  compatible installed KiCad footprint/model assets, and retained the outcome
  as `conditional_candidate` / `not_selected`.
- 2026-07-22: Added bounded bootstrap-capacitance screening. The calculated
  per-phase minimum is 394.69 nF effective; the nominal 1 uF recommendation is
  intentionally not accepted until component derating has a retained lower bound.
- 2026-07-22: Added the ten-capacitor DRV8334 support-network inventory and
  blocked placement until exact voltage-rated MPNs/footprints exist. Added nine-
  event protection-path coordination, explicitly exposed missing battery fault
  interruption and reverse-polarity protection, automatically retrieved and
  pinned the exact 7KPD26A source, and added a condition-aware TVS clamp screen.
