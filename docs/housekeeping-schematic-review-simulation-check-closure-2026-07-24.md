# Schematic review, simulation, and check-closure housekeeping

**Date:** 2026-07-24
**Status:** research and audit checkpoint; one silent trace-current omission
corrected; production-wide applicability/execution closure remains open
**Scope:** two-layer workflow only. Four-layer implementation is deliberately
deferred.

## Executive assessment

The next gain will not come from adding another flat checklist. PCBSmith needs
a closed chain:

`declared project context -> applicable requirement -> named check or analysis
-> exact saved input -> retained execution -> result -> unresolved limitation`

The repository already has strong pieces of this chain: source-pinned rules,
typed project contexts, exact aggregate subchecks, KiCad ERC/DRC adapters,
ngspice batch runs, immutable workflow generations, routed-board evidence, and
visual-package conformance. The missing part is a production-wide manifest that
proves every check applicable to one specific board actually executed against
that board revision. A green repository test suite proves the software
contracts passed; it does not prove that a generator invoked every relevant
contract for a project.

The immediate two-layer priorities are:

1. applicability-to-execution closure;
2. IC-by-IC, evidence-backed schematic review;
3. structured ngspice analyses with model provenance;
4. current-path, return-path, trace/via/zone, and voltage-drop authority;
5. connected functional-sheet schematic presentation;
6. practitioner failure cases promoted only after authoritative verification.

## What the linked Pinscope work contributes

The useful architectural ideas in
[Faradworks/Pinscope](https://github.com/Faradworks/Pinscope) are:

- parse the design into a component/net graph;
- review one IC and its bounded electrical neighborhood at a time;
- require a datasheet locator for evidence-backed findings;
- compute deterministic questions deterministically;
- isolate one failed component review from the rest of the run;
- make result normalization conservative rather than allowing a later model
  pass to increase severity;
- publish benchmark misses instead of treating a useful reviewer as an oracle.

The associated
[Reddit discussion](https://www.reddit.com/r/PCB/comments/1uyt638/we_spent_18_months_tuning_a_schematic_reviewer_it/)
is especially valuable because it records a 30/49 seeded-error result and names
the difficult areas: analog configurations without simulation, verified part
data, large-design salience, and auditability.

PCBSmith and Pinscope are both AGPL-compatible. The user chose to reuse the
methods and general engineering knowledge while writing PCBSmith-native code
instead of directly copying implementation segments. The inspected clone
remains under `.tmp/research-pinscope`. PCBSmith already has stronger
physical-board, transaction, KiCad read-back, routing, and visual evidence
layers; Pinscope contributes mature IC-neighborhood and reviewer-control
methods. The detailed audit, exact snapshot, comparison, adoption decisions,
and first implementation slice are recorded in
`docs/pinscope-method-audit-and-review-convention-integration-2026-07-24.md`.
Pinscope remains a design-assistant research specimen; its product workflow is
not the architecture for the independent PCBSmith generator. Selected methods
are used only where they strengthen automatic generation, repair, or evidence.

## Schematic presentation decision

The ESC example reinforces the value of showing the design as connected
functional blocks rather than one crowded sheet. KiCad 10 supports multiple
top-level sheets and hierarchical subsheets, with explicit sheet pins and
hierarchical labels:

<https://docs.kicad.org/master/en/eeschema/eeschema.html#hierarchical_schematics>

The safe implementation is not a second hand-maintained schematic that can
drift. PCBSmith should have one canonical connectivity authority and generate:

- a root architecture sheet;
- functional sheets such as power entry, MCU/control, interface/protection,
  sensing, and repeated channels;
- a whole-project ERC/netlist;
- per-sheet SVG/PDF review exports;
- a manifest binding every sheet export to the canonical schematic and netlist
  hashes.

A separate review-only file is acceptable only when generated from the same
semantic source and checked for connectivity equality. For repeated circuits,
KiCad multi-channel reuse is evaluated only when the board triggers it.

## SPICE decision

### Primary path

ngspice remains the automated simulation authority because it is available
headlessly, integrated with KiCad, and already has replay-bound evidence in
PCBSmith. KiCad can attach standard, unencrypted external `.model` and
`.subckt` files, but commercial-device models normally have to be acquired from
manufacturers:

<https://docs.kicad.org/master/en/eeschema/eeschema.html#simulator>

The next implementation is not merely "run SPICE." Each simulation obligation
needs:

- topology and scenario identity;
- exact KiCad-exported netlist hash;
- simulator and version;
- model file hashes, source URLs, licenses, part/package identities, and pin
  mapping;
- declared idealizations and excluded behavior;
- analyses, sweeps, corners, stimuli, measurements, and thresholds;
- raw output and parsed measurement hashes;
- explicit `passed`, `failed`, `unavailable`, `unverified`, or
  `not_applicable` status.

### LTspice role

[LTspice](https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html)
is worth supporting as an optional process-isolated cross-check, especially for
Analog Devices parts and vendor demo circuits. Its library advantage is
primarily the ADI product ecosystem plus general simulation devices; it is not
a universal verified library for arbitrary board components.

LTspice must therefore not replace ngspice or silently donate models. An
LTspice path requires:

- model license and redistribution review;
- explicit simulator compatibility status;
- isolated execution and version capture;
- equivalent stimuli and measurements where cross-comparison is claimed;
- a discrepancy report rather than choosing whichever solver passes.

## Check-suite audit: the important distinction

The July 20/23 stewardship work established that the roughly 2,800 pytest cases
are expanded software tests, not 2,800 independent PCB checks. The current
aggregate exact-checker policy can require and replay selected virtual DRC,
design checks, KiCad evidence, and simulation evidence. This is a strong narrow
authority, but it is not yet a project-wide inventory of every applicable rule.

The production gap has four parts:

1. **Applicability:** a rule may exist but the project may never declare the
   context that activates it.
2. **Invocation:** a check may be tested and callable but omitted by a legacy
   generator.
3. **Coverage:** a check may run while evaluating zero relevant objects.
4. **Binding:** a result may exist but belong to an older schematic, board,
   policy, model, or tool version.

One concrete coverage defect was corrected during this audit:
`_check_trace_currents()` previously skipped a declared current net with no
routed track segments, while the report still listed `trace_current` under
`checks_run`. It now emits an explicit warning that the capacity was not
evaluated and names the excluded conductor types.

The production-wide closure object should contain, for every candidate rule:

- rule/check identity and version;
- source and locator;
- applicability result and reason;
- required input objects and hashes;
- producer and tool version;
- number and identities of objects evaluated;
- result and finding identities;
- limitations and unresolved model needs;
- final authority and release effect.

Missing applicable executions, zero-object executions without a justified
empty scope, duplicate conflicting authorities, and stale input bindings must
fail closed.

## Trace width, current, routing, and noise

The phrase "wide traces for current and narrow traces for signals" is a useful
starting intuition, not a sufficient rule. The required width depends on at
least current waveform, allowable temperature rise and voltage drop, copper
thickness, layer/environment, length, nearby copper, parallel paths, neck-downs,
vias, pads, planes/zones, connectors, ambient, airflow, and duty/transient
behavior.

The current PCBSmith trace-current check is explicitly limited:

- it runs only when `DesignChecksSpec.net_currents` is populated;
- it uses the narrowest routed track segment;
- it uses a labeled legacy IPC-2221A external-trace fit;
- it does not prove zones, planes, vias, pads, connectors, sharing, pulses,
  voltage drop, or thermal environment.

The local IPC-2152 research correctly rejects replacing this with another
single universal coefficient. Phase 18 must introduce a selected
fabricator/stack-up current-path model, while Phase 20 owns coupled transient
and electrothermal analysis.

Signal routing also needs more precise language than "non-overlapping":

- same-layer cross-net copper must not overlap and is covered by clearance
  checks;
- different-layer signal crossings can be legal, but their coupling and return
  paths depend on geometry and references;
- on a two-layer board, routing that shreds the ground return can be worse than
  a visually untidy route;
- sensitive, clock, USB, switching, gate-drive, sense, and power nets need
  topology-specific loop/reference/spacing declarations rather than one
  universal width.

The bounded two-layer implementation should add:

- per-net current and voltage-drop budgets;
- complete current-path membership including tracks, zones, vias, pads, and
  connectors;
- neck-down and parallel-sharing detection;
- explicit supply/return and gate/return loop pairs;
- continuous-reference/return-adjacency review;
- route-class triggers for USB, clocks, crystals, switching nodes, Kelvin
  sense, and sensitive analog;
- layer-isolated review images that make those paths inspectable.

## Lessons from the ESC discussion

The
[ESC review thread](https://www.reddit.com/r/PCB/comments/1v3zxav/my_first_esc/)
is useful as a failure-mode source, not as engineering authority. Its comments
surface the right questions for future power boards: local ceramic energy
storage, paired gate-drive returns, copper and switching-frequency assumptions,
thermal modeling, clamp/snubber/protection provisions, shunt/sense visibility,
and assembly access. Those questions align with the local advanced rule
catalogue and Phase 20.

No 80-100 A or four-layer implementation should be started from that thread.
Each promoted requirement must be reconciled with the selected MOSFET,
gate-driver, shunt/amplifier, capacitor, connector, stack-up, cooling assembly,
mission profile, manufacturer documentation, and measured validation plan.

## Review-guideline handling

The user supplied the specific convention excerpt they want considered. It is
now classified in the detailed Pinscope/convention audit as release checklist,
applicability-dependent electrical/layout review, or presentation convention.
It is not promoted wholesale into universal blocker rules. Electrical claims
still need exact project applicability and primary/local engineering evidence;
presentation guidance remains review/style unless a concrete assembly, safety,
or functional consequence promotes it.

## Ordered housekeeping implementation

### H1 - close Phase 17 production invocation

- Add the applicability-to-execution manifest and zero-object coverage rule.
- Bind it to the immutable production generation and routed-board release gate.
- Migrate generators so legacy one-off paths cannot bypass it.
- Add a functional-sheet review export without creating a second electrical
  authority.

### H2 - strengthen two-layer current and return authority

- Replace trace-only observations with complete routed-copper current paths.
- Add voltage-drop and via/zone/connector bottleneck records.
- Add return/reference and topology-loop obligations.
- Keep IPC-2152 use context-bound and historical, not universal.

### H3 - structured simulation

- Add a revisioned model registry and compatibility tests.
- Extend ngspice batch runs with measurements, sweeps, corners, and model
  provenance.
- Add LTspice only as an optional ADI-focused cross-check after the primary
  model path is stable.

### H4 - benchmark and external-learning corpus

- Retain independently described failure cases from community reviews.
- Trace each candidate to a primary/local source before promotion.
- Measure true positives, false positives, misses, unresolved cases, runtime,
  and evidence completeness.
- Publish limitations and regressions per board class.

### H5 - defer layer-count escalation

Four-layer and denser boards remain research-only until two materially
different two-layer projects pass the complete default path with the execution
manifest, routed-board evidence, visual acceptance, and structured simulation
where applicable. Layer count is not the only complexity driver; a two-layer
switching, mixed-signal, or USB board can already trigger strict L1 gates.

## Decision

Do not resume new board generation yet. First implement H1, then exercise it on
the corrected protocol analyzer and one existing routed board. H2 and H3 can
then advance as narrow, separately testable slices. This preserves the intended
progression while closing the regression class that allowed missing routing or
unexecuted checks to look successful.
