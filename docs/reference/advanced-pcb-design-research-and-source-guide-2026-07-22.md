# Advanced PCB Design Research and Source Guide

**Date:** 2026-07-22
**Status:** Research and acquisition pass complete; production-rule promotion is not implied
**Companions:** `data/advanced-pcb-rule-catalog-2026-07-22.json`, `data/advanced-pcb-source-matrix-2026-07-22.csv`, `data/advanced-pcb-source-intake-2026-07-22.json`

## Executive assessment

The missing knowledge is not one hidden master checklist. Professional PCB work
combines several different authorities:

1. The exact component datasheet, errata, hardware-design guide, and reference
   design.
2. The selected interface, product-safety, fabrication, and assembly standards.
3. The selected fabricator stack-up and assembler process.
4. Calculations and simulations using project-specific electrical and mechanical
   inputs.
5. Post-layout review, measurement, and first-article evidence.

Books and generic application notes teach mechanisms and reusable review
questions. They do not safely supply universal dimensions for every design.
Community reviews and videos are useful discovery channels, especially for
failure modes, but a claim found there must be traced to a primary source or
kept as an advisory hypothesis.

The recommended direction for PCBSmith is therefore a context-gated rule
system, not a larger flat list of magic numbers. Each promoted rule must state:

- its exact applicability predicate;
- required project inputs;
- authority and revision;
- whether it is hard, derived, advisory, or simulation-bound;
- the implementation consumer;
- the verification method;
- confidence and unresolved conflicts.

## What was found locally

The local collection is already unusually strong for foundational PCB work. It
contains IPC-7352, IPC-7093A, IPC-2152, IPC-2221A, IPC-2222, USB 2.0 and USB
Type-C material, Sensirion design-in guidance, ESD and thermal sources, EMC and
signal-integrity books, and substantial existing distillation. The main problem
is utilization: many sources are pinned or summarized but not yet reconciled
with exact parts, converted into typed rules, bound to consumers, firing-tested,
or production-exercised.

The current code also already has partial semantic structures for decoupling
loops, switching hot loops, thermal intent, antenna constraints, oscillator
zones, sensor isolation, and return adjacency. Those are important foundations,
but they do not yet form a complete advanced-board workflow.

## Acquisition result

The approved intake pass selected 18 free official documents across MCU
hardware, PDN, mixed-signal, high-speed, DDR, isolation, motor drive, RF,
hot-swap, switching power, oscillator design, and Ethernet.

- 13 documents were downloaded through the repository's allowlisted intake,
  validated as PDFs, SHA-256 pinned, and stored only in the private cache.
- 5 Analog Devices URLs remained typed `network_error` results after bounded
  retries. Their official pages remain monitored sources, but the payloads were
  not silently replaced by third-party mirrors.
- TI SLVA680A was already local and was not downloaded again.
- The complete public identity projection is in
  `data/advanced-pcb-source-intake-2026-07-22.json`.

This is evidence that automatic source retrieval exists but is not yet robust
enough for unattended production use. It needs retry with jitter, redirect and
content-disposition handling, browser-capable official-host fallback, rate-limit
awareness, and a resumable queue. Typed blocked states must remain visible.

## Rule authority and promotion model

### Authority order

Use the following default precedence, while still checking for project-specific
exceptions:

1. Applicable product safety or regulatory standard.
2. Selected fabricator and assembler capability profile.
3. Exact component datasheet, errata, and manufacturer design guide.
4. Exact manufacturer reference design with matching part, package, and
   topology.
5. Interface or device-family guide.
6. Industry standard.
7. Generic application note or textbook.
8. Community review, forum, or video.

### Promotion ladder

`found -> identity verified -> revision pinned -> relevant section distilled ->
conflicts reconciled -> typed rule proposed -> implementation bound ->
firing-tested -> production-exercised`

Downloading or summarizing stops near the beginning of this ladder. It is not
proof that a board generator uses the information.

### Four rule classes

- **Hard:** fail-closed once its declared applicability context is present.
- **Derived:** a numerical constraint computed from project inputs such as
  stack-up, timing, current, load step, or altitude.
- **Advisory:** a review prompt that needs judgment or measurement.
- **Simulation-bound:** cannot be accepted from geometry alone; requires a
  named model, solver, correlation, or laboratory method.

## Expanded design-rule catalogue

The machine-readable catalogue defines 23 rule families. The most important
findings are summarized below.

### 1. Architecture and exact-part identity

- Resolve every power, ground, exposed pad, reset, boot, programming, reference,
  and unused pin from exact manufacturer evidence.
- Treat package migration and alternate parts as new evidence events. Similar
  names do not imply compatible pin, pad, thermal, or layout requirements.
- Record every reference-design divergence and its likely consequence.
- Create a bring-up and recovery plan while the schematic is still editable.

### 2. Power tree, current budget, sequencing, and reset

- Budget static and transient current by operating mode, not only average
  current.
- Declare rail tolerances, startup order, ramp limits, brownout behavior,
  discharge, and power-good dependencies.
- Check that unpowered domains are not back-powered through I/O, protection
  diodes, pull-ups, or level shifters.
- Re-run the power tree after layout and component selection; plane necks and
  regulator thermal limits can invalidate an earlier schematic budget.

### 3. Power entry, inrush, surge, and fault energy

- Treat connector rating, cable/source impedance, input capacitance, fuse,
  reverse polarity, TVS, hot-swap element, and downstream absolute maximum as
  one protection chain.
- Check MOSFET transient safe operating area and pulse energy. A DC current
  rating is not an inrush proof.
- Model where regenerative or fault energy goes. This is essential for motors,
  inductive loads, long cables, and hot-plug systems.

### 4. PDN and decoupling

- Minimize the complete capacitor-current loop. Straight-line capacitor-to-pin
  distance is only a proxy and can be misleading across vias and planes.
- Derive target impedance from allowed droop divided by load step over a
  declared frequency/time range. Do not use one target for every rail.
- Use capacitor MPN behavior: DC-bias capacitance loss, ESR, ESL, package,
  mounting inductance, and tolerance matter.
- Review anti-resonance, plane resonance, VRM control response, package
  inductance, and power-via current density for complex ICs.

### 5. Stack-up, impedance, and return structure

- Obtain a fabricator-approved stack-up before freezing controlled-impedance
  geometry.
- Recalculate width and spacing when dielectric, copper, plating, solder mask,
  or impedance tolerance changes. Values copied from a vendor reference stack
  are not portable.
- Declare the reference plane for each critical route and provide a nearby
  return transition when the signal changes reference.
- Consider copper roughness, Dk/Df, glass weave, and loss budget when interface
  speed and reach make them material.

### 6. Return current, grounding, and zoning

- Partition by current path, susceptibility, and energy - not by arbitrary
  analog/digital labels.
- Do not route critical signals over plane gaps. A split ground can become a
  slot antenna and force a large return loop.
- If a layer transition changes the reference potential, design the return
  transition intentionally; a distant decoupling capacitor is not equivalent
  to a colocated low-inductance path.
- Keep chassis/shield current paths separate from sensitive logic where the
  interface and product architecture require it.

### 7. Clocks, crystals, PLLs, and jitter

- Select the exact crystal/oscillator and calculate load capacitance including
  pin and board parasitics.
- Check drive level, startup time, negative-resistance or transconductance
  margin, temperature, supply variation, and probe loading.
- Treat SerDes and converter reference clocks as noise-sensitive analog paths
  with explicit phase-noise/jitter and supply-noise budgets.
- Do not invent a universal ground split around a crystal. Follow the exact IC
  and oscillator guidance and preserve a controlled quiet return.

### 8. High-speed digital and SerDes

- Edge rate, not only clock frequency, determines whether a route behaves as a
  transmission line.
- Controlled impedance, continuous reference, pair symmetry, equal transitions,
  connector/package behavior, and protocol-specific loss/skew limits take
  precedence over aesthetic routing.
- Do not maximize differential-pair coupling blindly. Follow the interface and
  stack-up-specific impedance/crosstalk solution.
- Include package delay before board-level length matching.
- At multi-gigabit rates, review via stubs, backdrilling, antipads, AC coupling,
  fiber weave, insertion loss, return loss, crosstalk, and mode conversion.
- Critical-channel test points can be harmful stubs; use planned observation
  methods instead of universal probe pads.

### 9. DDR and source-synchronous memory

- There is no safe universal DDR length-match number. Rules depend on the
  processor, memory, topology, rank count, package delays, ODT/drive settings,
  stack-up, and training behavior.
- Preserve vendor-defined byte lanes, timing groups, topology, placement,
  termination, and keepouts.
- Run pre-layout topology analysis and post-layout timing/SI simulation for
  deviations or advanced data rates.
- Capture training margins during bring-up and compare them with the design
  assumptions.

### 10. Ethernet PHY and transformer interfaces

- Bind the PHY, magnetics, connector shield, center taps, terminations, chassis
  strategy, and ESD path as one interface block.
- Follow the exact PHY checklist for PHY-to-magnetics placement, MDI routing,
  pair separation, clocking, and power.
- Inspect metal keepouts around magnetics and the connector, as well as return
  vias and shield-current paths.

### 11. RF and antennas

- Prefer the exact manufacturer reference layout and record deviations.
- Place antennas with the required board-edge relationship and all-layer
  keepout. Include the enclosure, battery, display, cables, metal, and nearby
  human body in the mechanical/RF review.
- Derive the feed geometry from the selected stack-up and provide an accessible
  matching network.
- Final tuning must use the assembled enclosure. A bare-board 50-ohm trace does
  not prove radiated performance.

### 12. Switching power

- Identify topology-specific high di/dt hot loops before placement and minimize
  their actual copper loop area.
- Bound switch-node copper. Larger copper may help heat spreading while making
  capacitive coupling and EMI worse; the tradeoff must be explicit.
- Use Kelvin feedback and current sense. Keep their reference away from load
  copper voltage drop and switching fields.
- Control gate-source current loops and consider footprints for damping or
  snubbing where evidence supports them.

### 13. Motors and high-current switching

- Calculate stall, startup, regenerative, and fault cases, not only nominal
  running current.
- Separate shunt force and sense connections and check amplifier common-mode
  transients.
- Review phase symmetry, gate loops, dead time, shoot-through, connector/cable
  ratings, thermal spreading, and via arrays.
- Use real copper thickness, plating, temperature rise, voltage drop, and duty
  cycle. Avoid a fixed amps-per-via rule.

### 14. Precision analog and mixed signal

- Build a noise and error budget before turning generic layout advice into
  constraints.
- Control converter sampling-current paths, reference decoupling, high-impedance
  leakage, input protection capacitance, thermal gradients, and digital return
  currents.
- Consider guards, shields, matched thermal placement, and contamination rules
  where the source impedance or accuracy justifies them.
- A single continuous ground plane is often safer than an arbitrary split;
  separation should come from placement and current-path control.

### 15. Sensors and environmental coupling

- Model how the measurand reaches the sensor: airflow, thermal path, pressure
  port, sound aperture, magnetic field, board motion, or strain.
- Check self-heating, duty cycle, nearby heat sources, copper thermal bridges,
  contamination, coating, enclosure openings, and mechanical stress.
- Slots and copper removal are tools, not automatic improvements. They need
  response-time, strength, EMC, and manufacturing review.

### 16. Thermal design and current density

- Treat theta-JA as board- and environment-dependent. Do not apply a package
  table value as a universal temperature prediction.
- Evaluate steady and transient loss, ambient, airflow, copper, vias, enclosure,
  contact paths, component derating, and safe operating area.
- Check both temperature rise and voltage drop. IPC-2152 is useful local
  historical evidence, but it should not become one universal equation.
- Coordinate thermal-via geometry with paste, voiding, assembly, and BGA/BTC
  inspection constraints.

### 17. ESD, EFT, surge, and EMC

- Arrange external connector, protection element, filtering, and protected IC
  in current-flow order.
- Minimize unprotected trace length and the inductance of the discharge return.
- Keep the ESD path from coupling into protected circuitry or forcing shield
  current through logic ground.
- Check protection capacitance and clamping behavior against interface signal
  quality and the actual threat current.

### 18. Isolation and safety

- Derive creepage and clearance from the applicable product standard, working
  and transient voltage, insulation class, pollution degree, material group,
  altitude, and process.
- Check the barrier on every copper and conductive mechanical layer.
- Credit slots or conformal coating only where the selected standard and
  controlled manufacturing process allow it.
- Coordinate isolation with EMI; a capacitive return intended to reduce
  emissions must preserve safety requirements.

### 19. BGA, HDI, microvias, and via-in-pad

- Prove fanout and escape feasibility before locking the package and layer
  count.
- Bind via technology, lamination cycles, fill/cap process, capture lands,
  reliability class, assembly, X-ray, and rework into the board process profile.
- Do not use unfilled via-in-pad under soldered pads unless the exact assembly
  process explicitly supports it.
- Coordinate BGA breakout with return vias, PDN access, decoupling, and channel
  discontinuity rather than solving escape in isolation.

### 20. Fabrication, assembly, and finish

- Replace generic 6/6 mil assumptions with selected fabricator and assembler
  profiles.
- Treat solder mask, paste apertures, stencil thickness, panelization,
  fiducials, breakaways, component overhang, and depanel stress as first-class
  design inputs.
- Select surface finish for pitch, contact use, storage, assembly, and
  reliability. ENIG is not automatically best for every board.
- Run both fabricator and assembler DFM before release.

### 21. Test, debug, programming, and bring-up

- Preserve programming, recovery, reset, and boot visibility.
- Add measurement access for power rails and low-speed controls, but do not add
  stubs to critical channels without a channel budget.
- Consider boundary scan and built-in self-test for BGA-heavy designs.
- Define current-limited first power, rail order, expected readings, and
  stop conditions before hardware arrives.

### 22. Reliability, environment, and lifecycle

- Use a mission profile for temperature, humidity, shock, vibration, duty,
  service life, and allowed failure rate.
- Apply voltage, current, power, temperature, and transient derating by component
  type and environment.
- Include MLCC DC-bias loss and flex cracking, contamination and CAF risk,
  coating compatibility, component lifecycle, PCNs, and replacement strategy.

### 23. CAD assets and 3D models

- Use the cascade: exact manufacturer assets, official KiCad libraries,
  licensed CAD provider, then verified custom asset.
- Reconcile symbol pins with the datasheet and footprint geometry with the
  manufacturer package drawing. A model downloaded by part number is not proof
  of correctness.
- Align STEP models 1:1 in millimeters and label fidelity as exact package,
  complete module, connector-only, or proxy.
- Visually inspect every imported symbol, footprint, and 3D model before it can
  become an authority.

## Complexity escalation for future boards

### L0 - simple low-speed two-layer board

Required: exact-part evidence, support-circuit audit, ERC/DRC, selected
fabrication profile, standard visual review, and a basic bring-up plan.

### L1 - switching, mixed-signal, RF module, motor, or external interfaces

Add: current-path and return-path declarations, topology placement zones,
thermal/transient calculations, focused layer-isolated renders, and a bench
validation plan.

### L2 - controlled impedance, BGA, DDR, isolation, or multi-rail SoC

Add: fabricator stack-up signoff, package escape feasibility, PDN/SI simulation
plan, sequencing, formal bring-up, and assembler DFM.

### L3 - multi-gigabit, FPGA/RFSoC, HDI, safety-critical, or certification-bound

Add: channel and PDN simulation with controlled models, a product-standard
compliance matrix, thermal/airflow simulation, laboratory pre-compliance, and a
formal unresolved-risk register. PCBSmith should generate and audit artifacts
at this level, but it must not claim autonomous engineering signoff.

## Component and document retrieval architecture

### What an API can and cannot provide

Distributor and aggregation APIs can help find:

- exact manufacturer identity and orderable MPN;
- lifecycle and supply information;
- manufacturer datasheet URL;
- product image and sometimes CAD-provider links;
- parametric data for preliminary screening.

They generally do not provide trustworthy, context-specific PCB layout rules.
Those come from the manufacturer datasheet, hardware guide, errata, reference
design, package drawing, and interface documents.

### Recommended cascade

1. Normalize manufacturer and exact MPN.
2. Search the local evidence and asset cache by identity and revision.
3. Query the manufacturer source or approved official URL.
4. Use a distributor API only as a metadata and official-datasheet locator.
5. Search official KiCad libraries for symbols, footprints, and 3D models.
6. Use a licensed CAD provider only after its terms permit the intended cache,
   transformation, and redistribution behavior.
7. Build a custom asset from the package drawing if no safe source exists.
8. Validate pins, dimensions, units, origin, rotation, side, height, and license.
9. Store private payload separately from commit-safe hashes and metadata.

### Provider assessment

| Provider | Useful data | Access | Assessment |
|---|---|---|---|
| DigiKey Product Information V4 | MPN, manufacturer, product data, `DatasheetUrl` | OAuth and organization/account setup | Good metadata and datasheet locator; needs user credentials |
| Mouser Search API | MPN search, datasheet URL, lifecycle, image, availability, pricing | Account and API key; published call limits | Good fallback locator; not a layout-rule source |
| element14 Product Search API | Keyword, product, and MPN search; JSON/XML | API key | Useful additional locator |
| Nexar/Octopart | GraphQL part, supply, technical, and datasheet metadata | Account, application, OAuth, plan limits | Client exists locally but no credentials; terms restrict caching and self-hosting |
| KiCad official libraries | Symbols, footprints, and 3D models | Open GitLab repositories | Preferred generic CAD source; still requires exact-part verification |
| SnapMagic | Symbols, footprints, 3D assets | Commercial terms/API integrations | Conditional; licensing and cache rights must be approved first |
| Ultra Librarian | Symbols, footprints, 3D assets | Registration and terms | Conditional/manual unless a licensed integration is available |

No provider should be called silently with user credentials, and no provider
payload should be committed unless its license permits redistribution.

## Remaining source gaps

### High-value paid or conditional standards not found locally

These are future purchase or user-supplied candidates, not blockers for the
current proof of concept:

- IPC-2226A - HDI and microvia design.
- IPC-7095D with Amendment 1 - BGA design and assembly.
- IPC-4761 - via protection structures.
- IPC-6012F - rigid-board qualification and performance.
- IPC-4552B - ENIG finish requirements.

The 2026-07-22 user intake added the original IPC-2226, IPC-6012C, and
IPC-6013D. These materially improve historical and mechanism coverage, but do
not close the current IPC-2226A, IPC-6012F, or IPC-6013E gaps. It also added an
IPC-7251 first working draft for through-hole land-pattern research; its draft
status must remain attached to every derived claim.

For advanced future directions also monitor the current revisions of
IPC-2222, IPC-2223 for flex/rigid-flex, IPC-6013 for flex/rigid-flex
qualification, IPC-6018 for high-frequency boards, IPC-A-610 and J-STD-001 for
assembly acceptance/process, and applicable automotive, medical, aerospace, or
functional-safety standards. Do not buy all of these preemptively; acquire them
when a concrete project creates an applicability need.

### Free current advanced references to monitor

- AMD UG583 for FPGA/SoC PDN, DDR, transceivers, RFSoC, and interface rules.
- Intel Agilex 5 PCB Design Guidelines for BGA escape, HSSI, EMIF, MIPI, PDN,
  fiber weave, vias, and backdrilling.
- The exact processor/FPGA hardware guide and memory-layout guide selected by a
  future project.
- The exact safety and EMC standards selected by the product category and
  market.

## Proposed implementation sequence

1. Build a revision-aware source registry and resilient retrieval queue.
2. Add exact-part document-role discovery: datasheet, errata, hardware guide,
   package drawing, reference design, simulation model, CAD asset.
3. Introduce context schemas for stack-up, environment, interfaces, power tree,
   timing groups, protection threats, manufacturing process, and validation
   plan.
4. Promote only a small first set of rules with named consumers:
   decoupling-loop topology, connector-to-ESD ordering, oscillator-zone evidence,
   switcher hot-loop membership, and stack-up/reference continuity.
5. Add project complexity classification L0-L3 and require progressively deeper
   gates.
6. Build simulation adapters only after their inputs and acceptance metrics are
   typed: impedance/field solver, IBIS/S-parameter SI, PDN, thermal, and power
   transient.
7. Expand the visual package with stack-up, return-path, power-domain, thermal,
   high-speed, and DFM diagnostic views.
8. Exercise each promoted rule on a materially different board and retain
   failure evidence before default adoption.

## Important non-rules

The following statements must not become unconditional global checks:

- "Put every decoupling capacitor within X millimeters."
- "Always split analog and digital ground."
- "Route every differential pair as tightly coupled as possible."
- "Match all high-speed traces to the same length."
- "A via carries X amps."
- "Use one ounce copper and this trace-width equation for every board."
- "Theta-JA predicts this board temperature."
- "A 50-ohm trace guarantees an antenna will work."
- "Six mil design rules are safe for every fab."
- "A downloaded KiCad footprint or 3D model is correct because the MPN matches."

Each may be a useful heuristic under a declared context. None is a universal
engineering authority.

## Decision

This research should be added as a new sequential roadmap phase rather than
retroactively inserted into completed phases. The research catalogue and source
intake can be marked complete. Rule reconciliation, implementation, simulation,
and production exercise remain open and should advance incrementally with
future project needs.
