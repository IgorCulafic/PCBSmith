# Multi-physics and engineering-system gap research

**Date:** 2026-07-22
**Status:** research and system decomposition complete; implementation is open
**Companions:**
`data/multiphysics-source-requests-2026-07-22.json`,
`data/multiphysics-source-intake-2026-07-22.json`,
`data/multiphysics-capability-gap-catalog-2026-07-22.json`, and
`../workflow-deviation-governance.md`

## Executive conclusion

PCBSmith does not mainly need more isolated PCB rules. It needs a set of
connected engineering authorities that carry one design through operating
scenarios, losses, fields and temperatures, mechanical construction,
manufacturing variation, faults, ageing, and measured validation.

The existing project has useful foundations:

- component-level deterministic calculators;
- source-bound circuit and exact-part identities;
- current-path, hot-loop, return-path, ESD-order, thermal-intent, sensor, and
  oscillator semantic structures;
- KiCad ERC/DRC, model preflight, visual review, and retained evidence;
- a broad 23-family advanced-board research catalogue.

The present thermal evaluator is intentionally narrower than a thermal solver.
It can describe sources and sensitive regions, check planar separation, and
emit a simple temperature estimate only when a declared theta model exactly
matches its scope. It does not derive component loss, solve a shared heat-flow
network, account for temperature-dependent resistance, select a heatsink or
TIM, calculate contact pressure, find a fan operating point, model an enclosure,
or correlate a prediction with a measurement.

That boundary is correct. The remedy is not to stretch a geometry evaluator
until it makes unsupported thermal claims. The remedy is to add typed systems
and explicit escalation from analytical estimates to network models, solver
results, and laboratory evidence.

## Evidence acquisition result

Fourteen freely available official PDFs were retrieved through PCBSmith's
allowlisted source-intake service. All fourteen passed PDF validation, were
SHA-256 pinned, and were stored in the private `.pcbsmith/evidence/source-cache`
area. No payload is intended for source control. The public identity and
retrieval projection is retained in
`data/multiphysics-source-intake-2026-07-22.json`.

The set includes official Infineon and Nexperia MOSFET/thermal sources, TI
motor-drive, thermal, transient, and PDN sources, TDK capacitor guidance, a TE
connector qualification specification, NASA derating and PCB quality sources,
and ECSS PCB/OTS quality sources. This successful pass also demonstrates that
the automatic retrieval mechanism works for these selected sources; it does
not imply that every manufacturer portal or paid standard is automatically
retrievable.

## The systems PCBSmith is missing

### 1. Operating-scenario and mission-profile authority

Every calculation needs a named scenario rather than one nominal current.
Minimum scenarios include startup, idle, normal duty, peak duty, stall/locked
rotor, regenerative operation, hot plug, brownout, shutdown, short circuit,
sensor or fan failure, and relevant environmental corners. Each scenario binds
voltage, current or torque, duty/PWM frequency, duration/repetition, ambient,
airflow, enclosure state, tolerances, and allowed degradation.

NASA's EEE-INST-002 explicitly treats part selection, qualification, and
derating as retained engineering analysis rather than a single universal
margin ([official NASA source](https://nepp.nasa.gov/pages/EEE-INST-002.cfm)).
ECSS likewise connects derating, thermography, board thermal models,
simulation, and test for relevant equipment
([ECSS-Q-ST-20-10C](https://ecss.nl/wp-content/uploads/standards/ecss-q/ECSS-Q-ST-20-10C8October2010.pdf)).

Required system: a versioned scenario matrix with coverage and missing-input
gates. A component check without scenario coverage remains preliminary.

### 2. Loss and stress ledger

Thermal analysis begins with credible power dissipation. A high-current board
needs, where applicable:

- MOSFET conduction loss using temperature-dependent `RDS(on)`;
- switching overlap, output-capacitance, gate-drive, dead-time/body-diode,
  reverse-recovery, avalanche, and linear-mode energy;
- shunt, copper, via, connector, cable, fuse, inductor, and contact `I²R` loss;
- capacitor ESR/ripple heating and dielectric loss;
- regulator and gate-driver internal dissipation;
- magnetic copper/core loss and saturation for converters;
- processor/FPGA rail power by operating mode;
- fault pulse energy and repetition.

Infineon warns that datasheet maximum drain current does not establish usable
current and that the entire electrical/thermal path must be considered
([Designing with power MOSFETs](https://www.infineon.com/assets/row/public/documents/24/42/infineon-designing-with-power-mosfets-applicationnotes-en.pdf)).
Nexperia distinguishes conduction, switching, and avalanche loss and shows
that board boundary conditions strongly change MOSFET thermal behavior
([AN50019](https://assets.nexperia.com/documents/application-note/AN50019.pdf)).
Its linear-mode guidance also ties SOA to pulse duration and transient thermal
impedance rather than DC current alone
([AN50006](https://assets.nexperia.com/documents/application-note/AN50006.pdf)).

Required system: a source-bound loss/stress record per part and scenario,
including equation/model identity, input ranges, uncertainty, and evidence.

### 3. Electrothermal network and feedback

The first useful thermal engine should be a conservative network, not immediate
full CFD. It needs junction, case/top, exposed pad, PCB territories, vias,
TIM/contact, heatsink, enclosure, and ambient nodes. It must support steady and
transient Foster/Cauer data, multiple heat sources sharing copper or a sink,
and temperature-dependent electrical loss.

TI notes that datasheet `θJA` is PCB- and boundary-condition-dependent and that
ambient air around the PCB can differ from external ambient; cramped enclosures
also invalidate free-convection assumptions
([SLUA566A](https://www.ti.com/lit/an/slua566a/slua566a.pdf)). TI uses Foster
networks for transient inrush heating
([SLVAE30E](https://www.ti.com/lit/an/slvae30e/slvae30e.pdf)). Nexperia provides
PCB Cauer-model concepts because one junction-to-ambient value cannot cover
different boards and environments
([AN50019](https://assets.nexperia.com/documents/application-note/AN50019.pdf)).

Required system: iterative electrothermal solving until loss and temperature
converge, with explicit non-convergence and out-of-model-range results.

### 4. Cooling-assembly and thermal-interface authority

A heatsink is an assembly, not merely a 3D body. The system must bind:

- exact cooled package surface and electrical potential;
- heatsink material, finish, geometry, mass, orientation, and selected part;
- TIM material, thickness, conductivity, dielectric rating, ageing, pump-out,
  puncture risk, and pressure-dependent impedance;
- flatness, roughness, tolerances, contact area, clamp locations, fasteners,
  washers/springs, torque or force, and PCB/package load;
- creepage/clearance, touchable metal, common-mode capacitance, and grounding;
- assembly order, rework, inspection, and replacement.

Infineon identifies insulation, thermal grease, fasteners, mounting torque,
attachment holes, and package stress as coupled assembly concerns
([TO-package assembly guidance](https://www.infineon.com/assets/row/public/documents/24/42/infineon-applicationnote-package-recommendations-assembly-topackages-applicationnotes-en.pdf)).
Its power-MOSFET guidance models thermal insulation/TIM and heatsink as series
parts of the full junction-to-ambient path. Topside cooling also means the
exposed thermal surface may be electrically active; a common plate can add
isolation and common-mode-capacitance concerns.

Required system: an exact mechanical stack declaration plus tolerance/contact
analysis. A visually touching STEP/GLB stack proves geometry continuity only.

### 5. Airflow and enclosure authority

Airflow cannot be represented by an arbitrary `m/s` field. The cooling design
needs inlet temperature, flow direction, obstruction and bypass, recirculation,
filters, altitude/density, natural versus forced convection, fan curve, system
resistance, fan-control law, acoustic limits, dust loading, and fan-failure
behavior. The actual fan operating point is the intersection of the fan and
system curves, not the fan's free-air rating
([ebm-papst explanation](https://www.ebmpapst.com/at/en/campaigns/company-and-image-campaigns/about-ebm-papst.html)).

Commercial electronics-cooling tools explicitly model conduction, convection,
radiation, airflow, enclosure, PCB construction, and electrothermal coupling
([Siemens electronics cooling](https://www.siemens.com/en-gb/products/simcenter/simulation-test/electronics-cooling-simulation/),
[Ansys Icepak](https://www.ansys.com/en-GB/Products/Electronics/ANSYS-Icepak)).
Their existence does not make a solver result correct automatically: boundary
conditions, material data, model fidelity, mesh, convergence, and correlation
must remain part of the evidence.

Required system: analytical natural/forced-convection screening, followed by a
typed CFD adapter only when complexity and inputs justify it.

### 6. Current path, temperature rise, and interconnect authority

Trace width alone is insufficient. The system must follow current through
copper pours, neck-downs, pads, vias, plane transitions, terminals, contacts,
cables, solder joints, and return paths. It must calculate voltage drop and
temperature rise with real copper/plating and local heat sharing, while keeping
IPC-2152 applicability and boundary conditions explicit.

Connector ratings depend on contact temperature rise, wire, position count,
ambient, and PCB design rather than a nameplate current alone
([TE product specification](https://www.te.com/content/dam/te-com/documents/appliances/global/power-tab-assembly-product-specification.pdf)).
TI's high-power motor guidance emphasizes parasitic resistance/inductance,
current-path neck-down, local DC-link placement, Kelvin sensing, and via/copper
effects ([SLVAF66](https://www.ti.com/lit/an/slvaf66/slvaf66.pdf)).

Required system: a graph of force-current paths and low-current sense paths,
with resistance/inductance/loss estimates and post-layout field-solver escalation.

### 7. Protection and fault-energy coordination

The existing connector-to-ESD order check proves ordering, not survival. A
complete protection engine must coordinate source/cable impedance, connector,
fuse/PTC, reverse protection, precharge/hot-swap, TVS, bulk capacitance,
MOSFET/diode SOA, wiring ampacity, regenerative energy, downstream absolute
maximum, shutdown latency, and fault repetition.

For ESD, TVS selection and layout must use clamping at the relevant pulse
current and a low-inductance return, while signal capacitance remains compatible
with the interface
([TI ESD layout guide](https://www.ti.com/lit/an/slva680a/slva680a.pdf)).
For high-power switching, short-to-ground, short-to-battery, shoot-through,
desaturation/VDS monitoring, dead time, and current-limit timing are part of the
system fault response, not isolated component checks.

Required system: event/energy path graphs, device time-response models, and an
explicit protection-coordination report per fault.

### 8. PDN, control stability, and signal/power interaction

Component decoupling placement is only the first layer. Complex boards need
rail target impedance over a declared frequency range, capacitor DC-bias/ESR/
ESL data, mounting inductance, VRM response, anti-resonance, package/plane
models, and post-layout impedance. TI derives target-impedance-based PDN
analysis using the VRM, bulk/ceramic capacitors, mounting, and plane behavior
([SPRACE6](https://www.ti.com/lit/an/sprace6/sprace6.pdf)).

Switching converters and motor control additionally need loop stability,
sampling/PWM timing, blanking, dead time, duty extremes, bootstrap refresh,
current-amplifier settling/common-mode transients, and firmware configuration
matched to the actual hardware.

Required system: PDN and control-loop declarations with typed SPICE/IBIS/
S-parameter/field-solver adapters and retained acceptance metrics.

### 9. EMC and common-mode current authority

Small hot loops and bounded switch nodes are necessary but not sufficient.
Common-mode current can flow through heatsinks, shields, cables, motor phases,
enclosures, isolation capacitance, mounting hardware, and measurement
equipment. Differential symmetry errors, cable resonance, edge slew rate,
return discontinuities, and ESD paths can dominate emissions or immunity.

Required system: intended and parasitic common-mode path declarations,
frequency/edge-aware coupling review, mitigation footprints, and a staged
pre-compliance test plan. Geometry can identify risks; it cannot claim EMC
compliance.

### 10. Mechanical and thermomechanical authority

Mounting-hole clearance and 3D collision checks do not establish mechanical
reliability. The system must consider board bending, heavy-component support,
fastener preload, connector insertion force, vibration modes, shock, CTE
mismatch, solder-joint fatigue, heatsink mass, depanel stress, potting/coating,
and package-specific stress sensitivity.

Analog Devices documents measurable precision-reference error from PCB stress
and the tradeoffs of slotting, stiffening, mounting, and orientation
([AN-82](https://www.analog.com/en/resources/app-notes/an-82f.html)). MEMS
packages can also be affected by PCB layout, soldering, and mounting stress
([MEMS soldering guidance](https://www.analog.com/en/resources/design-notes/soldering-guidelines-for-mems-inertial-sensors.html)).
ECSS PCB qualification guidance treats assembly/rework and environment as
thermomechanical reliability concerns
([ECSS-Q-ST-70-60C](https://ecss.nl/wp-content/uploads/2018/05/ECSS-Q-ST-70-60C%281June2018%29.pdf)).

Required system: mechanical load declarations and escalation from conservative
geometry/beam checks to modal, shock, and thermo-mechanical FEA.

### 11. Component life, environment, and derating authority

Reliability depends on a mission profile and failure mechanism. Examples
include electrolytic dry-out under ripple heating, MLCC bias loss/flex cracks,
MOSFET thermal cycling, connector fretting, humidity/contamination leakage,
CAF, corrosion, fan wear, relay contact life, and semiconductor junction
temperature.

TDK ties electrolytic useful life to rated voltage, ripple current, winding
temperature, ambient, and cooling; dense banks or restricted convection can
reduce life
([TDK technical guide](https://www.tdk-electronics.tdk.com/download/185386/31a5416e653dd6e4e428b8208d65cc2e/pdf-generaltechnicalinformation.pdf)).
NASA's GSFC-STD-8001 connects PCB design, procurement, production, and quality
assurance for high-reliability use
([official standard](https://standards.nasa.gov/standard/GSFC/GSFC-STD-8001)).

Required system: stress-ratio and life-consumption records per scenario, with
part-family-specific models and an `unsupported` result when evidence is absent.

### 12. Manufacturing-variation and inspection authority

Simulation normally assumes ideal geometry. Real boards have copper/plating,
dielectric, via fill, solder void, paste, component, TIM thickness, flatness,
torque, and placement tolerances. These can change electrical, thermal, and
mechanical behavior. The selected fabricator/assembler process therefore
belongs in the model inputs, not only in final Gerber checks.

Required system: process-capability profiles, tolerance/corner generation,
inspection method, acceptance sampling, and DFM/assembly feedback. X-ray,
thermography, impedance coupons, microsections, and torque records must be
triggered by the relevant construction rather than universally required.

### 13. Validation, uncertainty, and model-correlation authority

Every analysis must identify what would falsify it. A thermal result needs a
measurement plan for junction proxy, case, board, heatsink, inlet/outlet air,
ambient, load, duty, and emissivity/contact errors. Electrical models need
probe loading, bandwidth, calibration, and safe instrumentation. First article
results update the model; they do not merely produce a pass screenshot.

Required system: prediction-versus-measurement records, uncertainty budgets,
calibration/probe identity, model revision, acceptance bands, and correlation
status. An uncorrelated solver result remains `simulation_unverified`.

### 14. Workflow conformance and deviation authority

The R002 review-package omission demonstrates a process failure distinct from
engineering physics. The system needs stable requirement identities, additive
extensions, declared equivalent substitutions, approved waivers, and prohibited
authority changes. The normative policy is in
`docs/workflow-deviation-governance.md`.

Required system: a manifest completeness gate at every authoritative stage.

## Cross-domain failures that flat rule lists miss

The following interactions deserve explicit composition tests:

- lowering gate resistance can reduce switching loss time while increasing
  ringing, EMI, false turn-on, and driver dissipation;
- adding switch-node copper can reduce temperature while increasing parasitic
  capacitance and common-mode emissions;
- a common heatsink can improve thermal sharing while adding isolation risk,
  common-mode capacitance, mass, and clamp stress;
- more thermal vias can improve conduction while affecting solder voiding,
  paste loss, escape routing, and fabrication cost;
- a slot can improve thermal or stress isolation while weakening the board,
  interrupting return current, or violating manufacturing limits;
- stronger airflow can cool power devices while biasing environmental sensors,
  moving contaminants, increasing acoustic noise, or accelerating dust loading;
- a larger bulk capacitor can reduce bus ripple while increasing inrush,
  connector arcing, fuse stress, and regenerative overvoltage energy;
- a faster current-limit threshold can protect silicon while nuisance-tripping
  on switching transients; added filtering can then delay a real fault;
- symmetric-looking parallel MOSFET placement can still have unequal dynamic
  current sharing because gate/power inductance, device spread, and thermal
  paths differ;
- a thermally adequate connector can still fail from contact resistance growth,
  vibration/fretting, poor crimp, or PCB pad/via bottlenecks;
- conformal coating can help contamination control while changing creepage
  credit, rework, sensor response, and heat transfer;
- measurement probes, oscilloscope ground leads, or thermal-camera emissivity
  assumptions can create or conceal the failure being measured.

These are best represented as shared objects and composition rules, not copied
warnings in separate checkers.

## Recommended architecture

The common data flow should be:

`requirements/context -> scenarios -> stress/loss ledger -> geometry/path
authority -> analytical/network models -> optional solver adapters ->
manufacturing corners -> validation plan -> measured correlation -> release
claim`

Each stage consumes the exact upstream fingerprint and emits:

- status and scope;
- named inputs with units, ranges, and provenance;
- model/equation/tool version and hash;
- results, uncertainty, and acceptance comparison;
- unsupported or unresolved causes;
- required next evidence.

No downstream result may silently fill an unknown input with a universal
default. Exploratory assumptions are allowed only when labelled and prevented
from becoming release authority.

## Incremental implementation order

Trying to implement all systems together would repeat the earlier oversized-
rule failure. The recommended sequence is:

1. **Workflow conformance first. [IMPLEMENTED 2026-07-22]** Enforce the standard visual/review manifest,
   retain supplemental artifacts, and repair R002 without deleting its custom
   thermal views.
2. **BLDC scenario and loss ledger. [FOUNDATION IMPLEMENTED 2026-07-22]** Model a bounded R002 operating envelope
   and calculate MOSFET, shunt, capacitor, copper, gate-driver, and connector
   stress with uncertainty. Do not claim 60 A yet.
   The retained implementation deliberately leaves MOSFET and routed-path
   mechanisms unresolved until condition-matched inputs exist; only the
   tolerance-bounded shunt calculation is currently numeric.
3. **One-phase electrothermal slice. [FOUNDATION IMPLEMENTED 2026-07-22]** The
   typed Phase-U network, validation-required hot-RDS screening, point steady
   solver, and point Foster step solver now exist. Temperature-dependent
   electrical/thermal iteration, switching/dead-time/recovery estimates,
   reviewed `Zth` fitting, and physical boundary inputs remain open.
4. **Shared sink and cooling assembly. [FAIL-CLOSED FOUNDATION IMPLEMENTED
   2026-07-22]** The exact board hash, selected MOSFET package, geometry proxies,
   six package interfaces, and selection/property requirements are typed. Exact
   heatsink/TIM/clamp/isolation/air-mover parts, tolerances, local ambient, and
   natural/forced-convection screening remain open.
5. **Protection/fault slice.** Add stall, short, regenerative bus rise, hot
   plug, shoot-through, and shutdown-latency energy coordination.
6. **Measurement/correlation slice.** Generate the first-article instrumentation
   plan and require correlated results before thermal or current claims.
7. **Only then broaden.** Add PDN/control, EMC/common-mode, mechanical/FEA,
   reliability/life, and manufacturing-corner adapters when a board triggers
   them.

The first four engineering slices should remain analytical/network based and
deterministic. CFD/FEA/field solvers become optional typed backends with
retained versions and correlation requirements, not mandatory magic boxes.

## Decision

The research supports a new Phase 15 focused on workflow conformance and
multi-physics engineering authority. Research, source acquisition, and system
decomposition are complete. Implementation, production exercise, and model
correlation are not.
