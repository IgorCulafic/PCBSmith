# PCBSmith Reset Handoff - 2026-05-18

This document is the clean starting point for a new PCBSmith chat. It is written
to avoid carrying forward mistaken assumptions from the long prototype thread.

## Project Direction

PCBSmith is intended to become a free, open-source AI companion for KiCad. It
should help a non-expert describe a circuit or PCB goal, then turn that request
into reviewable KiCad artifacts through constrained tools, not through raw LLM
file editing.

The long-term goal is not "make the model know PCB design perfectly." The goal
is "make the model operate PCBSmith tools that know PCB constraints."

## Current Reality

PCBSmith has useful foundations, but it is not yet capable of arbitrary circuit
design.

What is currently useful:

- KiCad-first project generation and validation.
- KiCad CLI integration for ERC, DRC, previews, Gerbers, drill files, and SVG
  exports.
- Review bundles with machine-readable reports.
- Basic component catalog and component selection groundwork.
- Some deterministic calculators under `pcbsmith.calculators`.
- LED-art, ATtiny-controller, 555, and other demo generators that prove KiCad
  file generation can work.
- Local AI endpoint plumbing and a constrained tool-loop concept.
- Documentation and logs for design attempts and failures.

What is not yet reliable:

- Free-form circuit synthesis from arbitrary user requests.
- Automatically choosing the right topology for unfamiliar circuits.
- Automatically finding and applying reference schematics or datasheet example
  circuits.
- Producing schematic-first designs where the KiCad schematic is always the
  real source of truth.
- Running physics/simulation checks before board generation.
- Guaranteeing that board generators follow global routing/style rules.
- Producing production-ready buck converters, metal detectors, RF structures,
  antennas, wireless charging coils, or other sensitive analog/power designs.
- Expecting a local model to succeed on complex circuits without much stronger
  tool contracts.

## Important Correction

The recent LM2596/buck-converter work should not be treated as proof that
PCBSmith can design buck converters. It exposed a deeper architecture problem:
the system can still move from a vague circuit request to board generation
without enough topology evidence, math, simulation, reference validation, and
schematic correctness.

The correct response is not to keep patching one buck board. The correct
response is to build a stronger circuit-intelligence pipeline.

## Required Architecture

The next implementation should move PCBSmith toward this pipeline:

1. **Intent classification**
   - Convert user text into a circuit family and output goal.
   - Example: "buck converter" must become `switching_regulator.buck`, not a
     generic "power board."

2. **Topology selection**
   - Choose a supported topology before choosing components.
   - A buck converter needs a buck topology such as regulator-module,
     monolithic regulator IC, controller-plus-switch, synchronous buck, or a
     clearly marked unsupported path.
   - The AI must not substitute familiar parts such as Arduino chips, 555
     timers, or random ICs unless the topology explicitly requires them.

3. **Reference evidence**
   - Load datasheets, application notes, known reference designs, or verified
     example circuits before generating.
   - KiCad symbol/footprint metadata is not enough. It proves CAD availability,
     not electrical correctness.

4. **Component intelligence**
   - Components need role, package, electrical constraints, pin functions,
     symbol mapping, footprint mapping, and support status.
   - Complex parts should have deep profiles loaded on demand, not dumped into
     every prompt.

5. **Deterministic math layer**
   - PCBSmith code must calculate values such as LED current resistors,
     divider values, RC filters, 555 timing, BJT bias, comparator thresholds,
     coil estimates, LC resonance, buck inductor/current/ripple/feedback
     values, trace width/current estimates, and power dissipation.
   - The AI can request calculations and explain them, but should not freehand
     engineering math as the source of truth.

6. **Simulation layer**
   - Add ngspice as the first serious simulation backend.
   - Generate SPICE netlists from schematic-level intent.
   - Run `.op`, `.dc`, `.ac`, or `.tran` checks depending on circuit family.
   - Save simulation input, raw output, parsed metrics, pass/fail criteria, and
     plots where useful.
   - Falstad/CircuitJS can remain an optional visual/educational simulator, not
     the main verification engine.
   - Xyce can be considered later for larger or more advanced simulations.

7. **Schematic-first generation**
   - For normal circuits, the KiCad schematic should be the authoritative
     electrical source.
   - The board should be generated from the same net/component model, not drawn
     independently as a visually plausible PCB.
   - Exceptions such as LED art, PCB coils, antennas, and board artwork must be
     explicitly modeled as generated geometry with their own checks.

8. **PCB generation and routing**
   - Board generation should consume validated schematic/circuit objects.
   - Routing helpers must be centralized.
   - Global policies such as no vias in SMD pads, consistent same-net widths,
     reasonable clearances, and preferred mitered/45-degree style must be
     checked in shared code.

9. **Validation and revision brief**
   - All generated work should produce one review bundle with:
     - source request;
     - chosen topology;
     - reference evidence;
     - component candidates;
     - math report;
     - simulation report;
     - KiCad ERC/DRC;
     - board policy report;
     - visual artifacts;
     - human-review warnings;
     - `revision-brief.json`.

10. **Local AI tool loop**
    - Local models should call PCBSmith tools through approved contracts.
    - They should not directly edit arbitrary files.
    - They can propose operations, inspect structured reports, request
      calculations/simulations, and iterate through revision briefs.

## Simulator Decision

Use ngspice as the first simulation backend.

Reasons:

- KiCad already integrates ngspice for schematic simulation.
- KiCad CLI can export SPICE netlists.
- ngspice has a command-line and shared-library interface.
- It is mature, open source, and appropriate for analog/mixed-signal circuit
  checks.

Falstad/CircuitJS is useful for interactive visual understanding and possible
educational previews, but it should not be the main correctness gate.

Relevant references:

- KiCad SPICE simulation: https://www.kicad.org/discover/spice/
- KiCad CLI netlist export: https://docs.kicad.org/10.0/en/cli/cli.html
- ngspice shared API: https://nmg.gitlab.io/ngspice-manual/ngspiceassharedlibraryordynamiclinklibrary/sharedngspiceapi.html
- Falstad/CircuitJS JS interface: https://www.falstad.com/circuit/doc/js-interface.html
- Xyce: https://xyce.sandia.gov/

## What The Next Chat Should Do First

Do not start by generating another PCB.

Start by designing and implementing the missing intelligence pipeline:

1. Audit the current repo structure.
2. Mark demo-specific generators separately from reusable core systems.
3. Create a proper architecture plan for topology, references, math,
   simulation, schematic generation, PCB generation, and validation.
4. Implement ngspice integration as a small vertical slice.
5. Prove the slice on a simple circuit first, such as a voltage divider or RC
   filter.
6. Only then retry a buck converter or metal detector.

## First Test After Reset

The first ngspice-backed test should be intentionally simple:

- User request: "Make a voltage divider connected to a high-pass filter and LED
  indicator."
- PCBSmith should:
  - select topology;
  - calculate values;
  - generate a real schematic;
  - export/run SPICE where practical;
  - generate a KiCad PCB only after schematic/math/simulation pass;
  - produce the normal review bundle.

After that works, retry buck converter as a real topology with a reference
design and simulation support.

