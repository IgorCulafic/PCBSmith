# PCBSmith R10-R14 Intelligence Foundation Design

## Context

The metal detector request exposed a serious planning risk: an AI can reuse a
familiar circuit from recent demos instead of selecting the topology that the new
request actually needs. A PCB-coil detector is not "whatever can be built with a
555." It needs circuit-family selection, coil geometry, deterministic math,
component role selection, and validation before layout.

KiCad remains the CAD backend. PCBSmith adds the constrained intelligence layer
around KiCad so hosted and local models operate reliable tools instead of
freehanding electronics.

## Design Rules

- Select topology before parts.
- Select component roles before concrete catalog entries.
- Run deterministic calculators before schematic or board generation when a
  topology declares required math.
- Treat KiCad libraries as CAD metadata, not behavioral proof.
- Treat datasheets, app notes, calculators, examples, ERC/DRC, and PCBSmith
  checks as separate evidence layers.
- Treat local and hosted models as clients of the same tool contracts.

## R10 Circuit Intelligence

Add a topology selector with:

- intent;
- topology id and label;
- component intents;
- required math tools;
- required user inputs;
- do-not-use rules;
- validation gates;
- confidence status.

The first non-demo target is `metal-detector`, with an LC oscillator/sensing
topology using a PCB spiral coil, BJT gain/switching support, trim adjustment,
comparator threshold, buzzer output, LED indication, and terminal power input.

## R11 Deterministic Math

Calculations move into PCBSmith code, including:

- LED current limiting and string grouping;
- resistor power and total current;
- RC and 555 timing;
- MOSFET/BJT drive and bias checks;
- comparator thresholds and hysteresis;
- PCB spiral coil estimates;
- LC resonance estimates;
- trace width, clearance, via, and fabrication-profile checks.

AI may request these calculations and explain the result, but the numbers should
come from deterministic tools.

## R12 Validation And Reporting

Review bundles should converge on one report shape that includes:

- topology choice;
- selected component candidates;
- calculator outputs;
- schematic connectivity status;
- KiCad ERC/DRC status;
- PCBSmith manufacturability and geometry checks;
- fabrication-profile warnings;
- advisory visual/multimodal review findings where available;
- explicit human-review items.

## R13 Component And KiCad Library Expansion

Expand the catalog and library bridge by families, not one-off boards:

- BJTs;
- op-amps and comparators;
- buzzers and speakers;
- terminal blocks and connectors;
- regulators;
- batteries and power entries;
- switches and buttons;
- sensors;
- microcontrollers;
- coils and generated PCB features.

Each entry should keep support status visible. KiCad bindings prove CAD
availability only; behavior still needs datasheet/app-note knowledge.

## Research Notes

- KiCad 10 documentation describes project, schematic, board, symbol library,
  and footprint library files as separate design artifacts:
  https://docs.kicad.org/10.0/en/kicad/kicad.html
- KiCad's developer file-format documentation confirms that schematic and PCB
  files are S-expression based and separate from symbol/footprint library files:
  https://dev-docs.kicad.org/en/file-formats/
- KiCad CLI supports automated schematic, PCB, symbol, footprint, Gerber, drill,
  and SVG-oriented workflows, which is why PCBSmith should keep using KiCad as
  the validation/export backend:
  https://docs.kicad.org/10.0/en/cli/cli.html
- The local KiCad 10 installation was checked for relevant families needed by
  the detector track: `Device`, `Transistor_BJT`, `Comparator`,
  `Amplifier_Operational`, `Package_TO_SOT_SMD`, `Package_SO`,
  `TerminalBlock`, and `Buzzer_Beeper`.

## R14 Local AI Integration

Local models should use the same context and tool loop:

- AI brief;
- planner package;
- topology contract;
- component knowledge/search/selection;
- calculator outputs;
- approval loop;
- KiCad review bundle;
- revision brief.

Model assets, LoRAs, RAG indexes, and KoboldCPP/local runtime data belong under
ignored local asset directories, not source control.

## Acceptance Criteria

- `circuit-topologies metal-detector` returns the LC detector topology and its
  required math/tools.
- AI planner packages expose topology selection before component selection.
- The component catalog includes first-pass detector-related building blocks:
  BJTs, comparator/op-amp, buzzer, and terminal block.
- Roadmap, handoff, decision log, and presentation brief all document the new
  topology/math-first direction.
- No new detector board is generated until the foundation is in place.
