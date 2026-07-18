# PCBSmith Circuit Intelligence Roadmap

> **Historical document.** This May 18 reset roadmap preserves the
> rationale for the circuit-first architecture, but its "Current Repo
> Reality," phases, and immediate actions are no longer current. Use
> `docs/project-catchup-2026-07-12.md` for status and
> `docs/routing-placement-plan.md` for active execution order.
Date: 2026-05-18

Status: Internal engineering roadmap after the reset from demo-first board generation to circuit-first validation.

Known local tools:

- KiCad CLI: `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`
- KiCad version checked locally on 2026-07-18: `10.0.3`
- Standalone ngspice: `D:\AI\PCB designer\Spice64\bin\ngspice_con.exe`
- Standalone ngspice version checked locally: `ngspice-46`, creation date `Mar 29 2026`
- Project venv Python checked locally on 2026-07-18: `3.12.12`

## Purpose

PCBSmith should become a free, open-source AI companion for KiCad that can turn a user request into a reviewable circuit design without skipping the hard parts: topology evidence, deterministic math, simulation, schematic correctness, KiCad validation, and revision reports.

The previous demo work proved that PCBSmith can generate visible KiCad outputs. It also exposed the core flaw: a generated board can look plausible and pass ERC/DRC while the circuit reasoning is incomplete. This roadmap corrects that by making circuit intelligence the primary path and board generation a downstream artifact.

## Non-Negotiable Principles

- KiCad remains the authoritative EDA backend for schematic, board, ERC, DRC, library, and fabrication workflows.
- PCBSmith must not jump from user request to PCB generation.
- A circuit is not proven because ERC/DRC passed.
- Familiar parts are not acceptable just because they are common. Parts need topology fit, symbol and footprint mapping, and evidence appropriate to the risk.
- Every generated artifact must carry a status: supported, demo-only, unsupported, needs datasheet review, simulation failed, KiCad failed, or needs human review.
- Local and hosted AI output is a proposal only. It must pass PCBSmith validation and user approval before changing project files.
- Small verified vertical slices are more valuable than impressive untrusted boards.

## Current Repo Reality

### Live Code

The current live source under `src/pcbsmith` is effectively a Phase 0 foundation:

- Core models for projects, schematics, boards, library symbols, footprints, geometry, and netlists.
- Minimal project JSON I/O.
- Minimal ERC for unconnected pins and multiple power outputs.
- Built-in development library for resistors, capacitors, LEDs, VCC, GND, and a 1x2 connector.
- CLI commands: `new`, `info`, `validate`, `netlist`, and `erc`.
- Unit and integration tests for the Phase 0 behavior.

### Archived Prototype Code

The directory `old_files/r8-pre-restructure-snapshot-20260517-142339` contains useful prior modules for KiCad export, preview, validation, AI context, component selection, circuit rules, revision briefs, board intelligence, LED art, and local AI. These are reference material, not live implementation.

The current source tree also contains many stale `__pycache__` folders for modules that no longer exist as `.py` files. Do not treat those bytecode files as implemented features.

### Generated Outputs

The `outputs/` directory includes generated KiCad demos, including:

- simple voltage divider plus high-pass plus LED;
- buck converter prototype;
- local AI comparison diagnostics.

These outputs are historical evidence and regression material. They are not proof that the current live code has a trustworthy circuit intelligence pipeline.

### Immediate Environment Gaps

- This subsection described the May reset and is superseded. The project venv
  collects the current suite successfully; use
  `.\.venv\Scripts\python.exe`, disable ambient pytest-plugin autoload, and add
  `-p no:cacheprovider` as shown in `docs/handoff-prompt.md`.
- KiCad CLI 10.0.3 and standalone ngspice-46 are available.
- Root handoff, project-history, active routing/placement, completion-audit, and
  review-supplement documents now exist. Archived copies remain historical only.

## Target Architecture

The corrected pipeline should be:

```text
User request
  -> intent classification
  -> topology selection
  -> evidence retrieval
  -> deterministic calculators
  -> validated circuit object
  -> schematic-first generation
  -> SPICE netlist and ngspice simulation
  -> KiCad schematic export
  -> KiCad ERC
  -> PCB generation from validated circuit object
  -> KiCad DRC and fabrication outputs
  -> consolidated review bundle
  -> AI/user revision loop
```

Board generation is intentionally late in the flow. The board is generated only after PCBSmith has enough topology, math, simulation, schematic, and validation evidence to justify it.

## Major Missing Systems

### 1. Circuit Intent Layer

Current state:

- No live intent classifier for circuit requests.
- Old AI brief output shows useful categories, but the live CLI cannot classify requests beyond basic project commands.

Needed:

- A deterministic classifier for supported request families.
- Explicit unsupported results for anything outside known scope.
- Confidence and missing-information fields.
- A one-action local-AI contract that lets a model ask for classification without touching project files.

First supported intent:

- `divider_highpass_led_indicator`

Later supported intents:

- LED current-limited indicator.
- RC low-pass and high-pass filters.
- 555 astable LED blinker.
- 555 PWM LED dimmer.
- MOSFET low-side switch.
- Linear regulator support circuit.
- Buck converter only after regulator-specific evidence, simulation, and layout rules exist.

Definition of done:

- Unsupported requests never generate project files.
- Supported requests produce structured intent JSON with assumptions and missing facts.
- Tests include at least one supported simple request and one rejected buck request.

### 2. Topology Selection Layer

Current state:

- Archived code had some circuit rules and topology ideas.
- Live code has no topology catalogue.

Needed:

- A topology registry with supported topologies, required inputs, required calculators, required evidence, and do-not-use rules.
- Topology selection before part selection.
- Evidence attached to topology decisions, not only prose in a README.

First topology:

- Voltage divider feeding an AC-coupled RC high-pass node with an LED indicator path.

Definition of done:

- The topology object says what it is, why it was chosen, what assumptions it uses, what it does not prove, and what requires human review.
- The selected topology lists calculators and simulation checks that must run before generation.

### 3. Evidence And Datasheet System

Current state:

- KiCad symbols can carry datasheet fields, but live PCBSmith does not parse or index them.
- No component evidence registry exists.
- No datasheet downloader or cache exists.
- No cache-first lookup path exists, so a future downloader could waste API calls or redownload files already present.
- No document-understanding layer exists for extracting facts, tables, diagrams, pinouts, application circuits, or layout guidance from cached files.
- No formal distinction exists between a generic role, real part, datasheet-backed part, and simulation-backed part.

Needed:

- A component evidence registry.
- A cache-first local datasheet, app-note, reference-design, and SPICE-model store.
- API-backed on-demand retrieval for candidate parts instead of bulk downloading.
- A source policy that prefers manufacturer documentation and official KiCad metadata.
- A fact extraction layer that records where each claim came from.
- A multimodal document-understanding layer for images, pinout diagrams, application schematics, layout examples, and tables that text extraction cannot read reliably.
- A support status per component and per fact.

Proposed evidence model:

```json
{
  "schema": "pcbsmith-component-evidence-v1",
  "manufacturer": "Example Manufacturer",
  "part_number": "EXAMPLE123",
  "role": "indicator_led",
  "source_url": "https://manufacturer.example/example123.pdf",
  "local_file": "ai_assets/datasheets/example123.pdf",
  "sha256": "recorded checksum",
  "retrieved_at": "2026-05-18",
  "cache_status": "present",
  "license_status": "local_cache_only",
  "facts": [
    {
      "name": "forward_voltage_v_typ",
      "value": 2.0,
      "conditions": "IF=5mA",
      "source_locator": "datasheet page 3 table 1",
      "confidence": "human_reviewed"
    }
  ]
}
```

Source priority:

1. Manufacturer product page, datasheet, SPICE model, app note, reference design, or eval-board design files.
2. KiCad library metadata, including symbol fields and datasheet URLs.
3. Distributor pages only as discovery aids, not as primary evidence.
4. User-provided datasheets, board PDFs, KiCad projects, or reference designs.

Cache-first retrieval:

1. Normalize the requested identity:
   - manufacturer part number;
   - manufacturer name;
   - package;
   - role;
   - known aliases and distributor SKUs.
2. Search the local evidence manifest for an exact part match.
3. If no exact match exists, search by alias and checksum.
4. If metadata exists but the PDF/model file is missing, re-download only that missing file.
5. If no local evidence exists, query external APIs for metadata and datasheet URLs.
6. Download only shortlisted or selected datasheets/models, never broad result sets.
7. Record source URL, retrieval time, checksum, and license/reuse status.
8. Extract facts into structured JSON and keep raw files in ignored local cache.

Local storage:

- Store downloaded PDFs and model files under an ignored local cache such as `ai_assets/datasheets/` and `ai_assets/spice_models/`.
- Commit only metadata manifests, checksums, source URLs, and extracted facts when licensing allows.
- Do not redistribute vendor PDFs or models unless their license clearly permits it.

Document understanding:

- Use text extraction first for searchable PDF text.
- Use table extraction for electrical characteristics, recommended operating conditions, pin tables, package dimensions, and ordering information.
- Use OCR when PDFs are scans or tables render as images.
- Use multimodal review for:
  - pinout diagrams;
  - typical application circuits;
  - layout recommendation figures;
  - package/mechanical drawings;
  - eval-board screenshots and board diagrams;
  - charts where axes and curves matter.
- Every extracted fact must keep a locator such as page, table, figure, section, or bounding-box reference.
- Multimodal extraction is advisory until the fact is validated by deterministic parsing, a second source, or human review.

Board and module specs:

- Treat development boards and modules as component families with extra evidence:
  - schematic;
  - pinout;
  - mechanical dimensions;
  - connector positions;
  - power limits;
  - mounting holes;
  - official KiCad/STEP files if available.

Definition of done:

- PCBSmith can answer "what evidence justifies this part?" with source URL, local file, checksum, extracted facts, and review status.
- PCBSmith checks the local evidence cache before making any network or API request.
- Datasheet facts are not treated as trusted until they are parsed and tied to a locator.
- Pinouts, typical application circuits, and layout figures are represented as extracted evidence items, not hidden in unstructured PDFs.
- High-risk parts can require human-reviewed evidence before automated generation.

### 3.5 Circuit Research And Dependency Planner

Current state:

- A user request such as "build a sensor board" can imply many hidden support circuits.
- Live PCBSmith has no dependency planner that expands a main functional block into power, protection, biasing, signal conditioning, connectors, decoupling, programming/debug, and layout requirements.
- The old demos sometimes jumped from a part idea directly to a board, which is exactly what this reset is correcting.

Needed:

- A circuit research planner that decomposes a requested function into required electrical roles before part selection.
- Role-level topology requirements that can say "this block needs additional support components."
- Evidence-backed dependency rules for common families.
- Explicit "missing role" findings before schematic generation.

Research flow:

```text
User request
  -> functional intent
  -> block decomposition
  -> required roles
  -> topology candidates per role
  -> evidence queries per role
  -> part candidates
  -> compatibility checks between roles
  -> schematic-first circuit object
```

Example: sensor board dependency expansion:

- Sensor core:
  - sensor part;
  - supply voltage;
  - interface type;
  - output signal range;
  - required pull-ups, biasing, or excitation.
- Power:
  - input connector;
  - reverse-polarity protection where user-facing;
  - regulator or level shifting if sensor and controller voltages differ;
  - decoupling capacitors from datasheet recommendations.
- Signal conditioning:
  - filter;
  - op-amp or buffer if source impedance or signal level requires it;
  - ADC input protection or scaling;
  - reference voltage if required.
- Digital interface:
  - I2C pull-ups;
  - SPI chip-select and series resistors where appropriate;
  - UART level shifting if voltage domains differ.
- Protection and reliability:
  - ESD protection for external connectors;
  - current limiting;
  - fuse or resettable fuse for user-facing power;
  - test points.
- Mechanical and user interface:
  - mounting holes;
  - connector orientation;
  - silkscreen pin labels;
  - polarity and pin-1 markings.

Compatibility checks:

- Voltage domain compatibility.
- Logic threshold compatibility.
- Current budget.
- Input/output impedance.
- Frequency bandwidth.
- Thermal dissipation.
- Package and footprint availability.
- SPICE model availability where simulation is required.
- KiCad symbol, footprint, and pin mapping availability.

Definition of done:

- PCBSmith can produce a required-role checklist before choosing parts.
- Missing supporting components block schematic generation.
- The review bundle explains why each non-obvious support component exists.
- The AI cannot connect "sensor to IC" directly unless the dependency planner says no intermediate roles are required.

### 4. Deterministic Calculator Layer

Current state:

- Live code has no calculator module.
- Archived reports had circuit rules, but they are not in the active source.

Needed:

- Small pure functions for calculations.
- Inputs and outputs with units.
- Structured warnings and errors.
- Tests for every formula.

Initial calculators:

- Voltage divider output and divider current.
- RC high-pass and low-pass cutoff frequency.
- LED current-limit resistor current and resistor power.
- Resistor power derating check.
- Capacitor impedance at frequency.
- Pull-up/pull-down current and RC time constant.

Later calculators:

- MOSFET conduction loss and gate-drive margin.
- Linear regulator dissipation and thermal margin.
- Buck converter duty cycle, inductor ripple, saturation current, diode current, capacitor ripple, and feedback divider.
- Trace width/current estimates.
- Battery runtime estimates.

Definition of done:

- AI never freehands calculator math for supported quantities.
- Calculator warnings become review bundle items.
- Calculator tests include normal values, boundary values, and invalid values.

### 5. ngspice Simulation Layer

Current state:

- KiCad includes ngspice integration DLLs.
- Standalone ngspice is now installed at `D:\AI\PCB designer\Spice64\bin\ngspice_con.exe`.
- Live PCBSmith has no simulation runner.

Needed:

- ngspice discovery:
  - `PCBSMITH_NGSPICE` environment variable;
  - known local path `D:\AI\PCB designer\Spice64\bin\ngspice_con.exe`;
  - PATH lookup;
  - explicit unavailable report if missing.
- SPICE netlist renderer for validated circuit objects.
- Batch-mode runner using `ngspice_con.exe -b -o output.log input.cir`.
- Parser for `.print` output or generated raw/log files.
- Simulation measurements tied to pass/fail thresholds.

First simulation checks:

- Divider DC operating point near expected value.
- RC high-pass AC response around cutoff.
- LED path current or conduction state, with a warning if the indicator behavior is signal-dependent.

Definition of done:

- A missing ngspice binary is reported as `simulation_unavailable`, not hidden.
- A failed simulation blocks "ready" status.
- A successful ngspice run does not mean the board is ready unless thresholds pass and the review bundle records exactly what was measured.

### 6. Schematic-First Generation

Current state:

- Live Phase 0 can represent schematic JSON and derive a netlist.
- Live code does not generate the requested circuit from a validated circuit object.
- Old generated KiCad demos exist, but they are not shared live code.

Needed:

- Generate PCBSmith schematic JSON first.
- Validate netlist and ERC before KiCad export.
- Attach circuit object IDs to generated schematic elements so review reports can map issues back to intent/topology/math.
- Export KiCad schematic only from a validated PCBSmith schematic or directly from a validated circuit object.

Definition of done:

- The first vertical slice creates a PCBSmith schematic that passes live PCBSmith ERC.
- The schematic includes meaningful net names, values, and component roles.
- No PCB is generated until the schematic and simulation status are recorded.

### 7. KiCad Export And Validation

Current state:

- Archived code had KiCad skeleton, export, validation, preview, and review bundle modules.
- Live code does not have these modules.
- KiCad CLI is installed and can run ERC/DRC commands.

Needed:

- Restore or rebuild only the narrow KiCad modules needed for the first slice.
- KiCad schematic export with real symbols and embedded library symbols where needed.
- KiCad ERC through `kicad-cli sch erc --format json`.
- KiCad PCB generation only after the schematic-first circuit object is validated.
- KiCad DRC through `kicad-cli pcb drc --format json --schematic-parity`.
- Preview and fabrication exports as downstream artifacts, not proof of correctness.

Definition of done:

- KiCad validation reports are machine-readable and included in the review bundle.
- KiCad ERC/DRC failures block "ready" status.
- Passing ERC/DRC is described as EDA validation, not analog correctness.

### 8. PCB Generation From Validated Circuit Objects

Current state:

- Live board model exists but no serious board-generation logic is active.
- Historical outputs include board demos, including an insufficient buck converter.

Needed:

- Board generator that consumes validated circuit objects and schematic/netlist data.
- Net role classification:
  - power;
  - ground;
  - signal;
  - analog high impedance;
  - switching/high di/dt;
  - LED/load.
- Placement rules tied to topology:
  - keep RC filter components close when appropriate;
  - keep feedback and high impedance nodes short;
  - keep switching loops small when power converters are eventually supported.
- Routing rules:
  - KiCad DRC wins over style preferences;
  - trace width and clearance from design rules;
  - 45-degree routing as polish, not a false electrical law.

Definition of done:

- A board is generated only after the circuit object is valid.
- The board report records which circuit assumptions affected placement/routing.
- For the first slice, a simple board may remain `needs_human_review`.

### 9. Consolidated Review And Revision Loop

Current state:

- Archived code had `revision-brief.json`.
- Live code has no consolidated review bundle.
- Local AI comparison outputs show the refusal path worked when the model returned invalid tool-call shapes.

Needed:

- One review bundle for every generated design.
- A normalized revision queue that combines:
  - intent classification;
  - topology evidence;
  - datasheet/evidence status;
  - deterministic math;
  - ngspice simulation;
  - PCBSmith ERC;
  - KiCad ERC/DRC;
  - manufacturability checks;
  - visual preview checks;
  - human-review blockers.
- Stable error codes and next actions.

Example review item:

```json
{
  "severity": "blocker",
  "code": "simulation_unavailable",
  "message": "ngspice was not found or failed to run.",
  "next_action": "Set PCBSMITH_NGSPICE or install standalone ngspice before claiming circuit behavior.",
  "authority": "simulation"
}
```

Revision loop:

1. AI proposes exactly one action.
2. PCBSmith validates the action schema.
3. PCBSmith applies it to a temporary proposal state.
4. Deterministic checks run.
5. Simulation runs where relevant.
6. KiCad validation runs where relevant.
7. A new review bundle is written.
8. The AI can propose another revision only against the structured review items.
9. User approval is required before merging changes into the project.

Definition of done:

- No scattered logs are required for the AI to know what to fix next.
- Every blocking finding has a code, authority, message, and next action.
- The review bundle can represent "not run" separately from "passed."

### 10. AI Tool Loop And Error Messages

Current state:

- Existing local AI assets and output diagnostics show an OpenAI-compatible local runtime path.
- The local model previously returned arrays of invented tool calls and PCBSmith refused them.

Needed:

- Smaller tool contracts.
- One action per model turn.
- Strict JSON object shape.
- Repair adapter for common local-model mistakes:
  - JSON inside markdown fences;
  - array of tool calls instead of one object;
  - wrong top-level key;
  - invented tool name;
  - missing parameters.
- Safe refusal messages that tell the AI what was wrong and what exact shape to return next.

Example AI-facing error:

```json
{
  "schema": "pcbsmith-ai-error-v1",
  "code": "invalid_tool_shape",
  "message": "Expected one JSON object with action and parameters. Received an array.",
  "allowed_actions": ["classify_intent", "select_topology", "run_calculator"],
  "retry_allowed": true
}
```

Definition of done:

- Bad model output never mutates project files.
- The AI gets structured correction messages.
- Every accepted AI action is logged with before/after artifact paths.

## Phased Roadmap

### Phase A: Stabilize The Foundation

Goal: Make the current repo honest, runnable, and ready for circuit intelligence.

Work:

- Restore root docs or create new root docs that supersede archived handoff material.
- Add `.gitignore` entries for `ai_assets/models`, `ai_assets/datasheets`, generated outputs, caches, and ngspice distribution if it should remain local-only.
- Add pytest instructions that avoid global plugin pollution:
  - use project venv; or
  - set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- Add a `doctor` command that reports Python, KiCad, ngspice, and writable output paths.
- Mark archived prototype code and generated outputs as reference material.

Acceptance:

- A new contributor can run Phase 0 tests.
- The docs say what is live, archived, generated, and local-only.
- `doctor` finds KiCad and `D:\AI\PCB designer\Spice64\bin\ngspice_con.exe`.

### Phase B: First Circuit Intelligence Slice

Goal: Implement one small end-to-end circuit pipeline without pretending it is general.

Vertical slice:

- Voltage divider connected to high-pass filter and LED indicator.

Work:

- Intent classifier.
- Topology selector.
- Evidence model with formula references and demo-only component flags.
- Passive calculators.
- Circuit object model.
- PCBSmith schematic generation.
- PCBSmith ERC.
- ngspice netlist generation and simulation.
- Review bundle.
- CLI command.

Acceptance:

- Supported request writes a review bundle.
- Unsupported buck request does not generate a board.
- ngspice runs from the local standalone path.
- Review bundle says `needs_human_review` until component evidence and KiCad-native export are stronger.

### Phase C: KiCad Schematic And Validation Integration

Goal: Make KiCad-native schematic output part of the first slice.

Work:

- Restore/adapt minimal KiCad project skeleton writer.
- Export KiCad schematic from the validated circuit object.
- Include SPICE directives/model fields where practical.
- Run KiCad ERC.
- Export schematic SVG for review.

Acceptance:

- KiCad schematic opens in KiCad.
- KiCad ERC report is included in the review bundle.
- Schematic SVG is nonblank and linked from the review bundle.
- KiCad ERC pass is not described as proof of analog behavior.

### Phase D: Evidence And Datasheet Library

Goal: Stop relying on generic components for everything.

Work:

- Parse KiCad library symbol fields and datasheet URLs.
- Create `component-evidence-index` command.
- Create `evidence-cache-lookup` so local files and extracted facts are checked before any API call.
- Create downloader/cache for manufacturer datasheets and SPICE models with checksums.
- Add API adapters for on-demand metadata and datasheet URL retrieval, starting with one broad search provider and one manufacturer/distributor provider.
- Add a document-understanding pipeline:
  - PDF text extraction;
  - table extraction;
  - OCR fallback;
  - multimodal figure review for pinouts, typical application circuits, and layout diagrams.
- Add a manually curated seed set:
  - generic 0603 resistor family;
  - generic 0603 capacitor family;
  - one real red LED;
  - one NE555-family timer;
  - one logic-level NMOS;
  - one LDO;
  - one buck regulator later, after simpler power circuits are stable.
- Extract facts into structured JSON.
- Link facts to pages/tables/locators.
- Record fact confidence as `api_metadata`, `text_extracted`, `ocr_extracted`, `multimodal_extracted`, or `human_reviewed`.

Acceptance:

- Component selection can say whether a chosen part is generic, datasheet-backed, simulation-backed, or needs review.
- Existing cached files are reused before API calls or downloads.
- Datasheet and model files are cached locally without accidental redistribution.
- Extracted facts include source locators and confidence.
- The review bundle names the exact missing evidence for demo-only parts.

### Phase D.5: Circuit Dependency Research Planner

Goal: Make PCBSmith research the complete circuit around a requested function, not only the headline part.

Work:

- Add `research-plan` command that turns functional intent into required roles.
- Add role templates for:
  - sensor front ends;
  - LED indicators;
  - digital interfaces;
  - power entry;
  - regulators;
  - MOSFET switching;
  - analog filtering;
  - microcontroller support circuits.
- Add dependency rules that require supporting components before schematic generation:
  - decoupling capacitors;
  - pull-ups/pull-downs;
  - bias resistors;
  - current limits;
  - level shifters;
  - regulators;
  - ESD/protection;
  - connectors and test points.
- Connect dependency roles to evidence lookup and calculators.
- Add missing-role findings to the review bundle.

Acceptance:

- A broad request produces a role checklist before parts are chosen.
- The checklist names required, optional, and human-review roles.
- PCBSmith blocks schematic generation when a required support role is unresolved.
- The AI receives structured problem messages such as `missing_i2c_pullups`, `missing_decoupling_capacitor`, or `voltage_domain_mismatch`.

### Phase E: KiCad PCB Generation From Circuit Objects

Goal: Generate a simple PCB only after the circuit object, schematic, and simulation path are valid.

Work:

- Board placement from circuit roles.
- Footprint selection from component evidence.
- Net role classification.
- Simple routing and board outline.
- KiCad DRC and schematic parity.
- Board SVG and fabrication exports.

Acceptance:

- First slice produces a KiCad PCB that passes DRC.
- Review bundle includes both circuit-level and board-level status.
- Board output remains `needs_human_review` until component evidence and visual review pass.

### Phase F: Revision Engine

Goal: Make back-and-forth improvements systematic.

Work:

- Normalize all findings into `revision-brief.json`.
- Add revision proposals that target specific findings by code.
- Keep proposal state separate from approved project state.
- Record action log entries.
- Add regression tests for failed revisions.

Acceptance:

- AI can ask "what should I fix next?" and receive a small structured list.
- PCBSmith can reject a proposed fix with a specific error code.
- User approval remains explicit.

### Phase G: Local AI Tool Loop

Goal: Make local models useful without trusting them.

Work:

- One-action JSON contracts.
- Contract repair layer.
- Model output diagnostics.
- Smaller context packages with only relevant tools.
- Local RAG over component evidence and roadmap docs.
- Optional multimodal visual review later.

Acceptance:

- The previous local model failure shape is handled or rejected with a clear repair prompt.
- Local model output cannot invent new tools without being rejected.
- Every local-AI run writes raw response, parsed response, validation result, and artifacts.

### Phase H: More Topologies

Goal: Grow breadth only after the pipeline is proven.

Order:

1. LED current limiter.
2. RC low-pass and high-pass filters.
3. 555 astable.
4. 555 PWM dimmer.
5. MOSFET low-side switch.
6. Linear regulator support circuit.
7. Sensor breakout.
8. Buck converter.

Buck converter entry criteria:

- Specific regulator selected.
- Datasheet and reference design available.
- Feedback math implemented.
- Inductor saturation/ripple checks implemented.
- Diode/switch current and thermal checks implemented.
- Input/output capacitor requirements implemented.
- ngspice or vendor-model simulation path defined.
- Layout loop-area rules implemented.
- Human-review warning remains mandatory.

## Tooling Roadmap

Near-term CLI tools:

- `pcbsmith doctor`
- `pcbsmith circuit-intent`
- `pcbsmith topology-select`
- `pcbsmith calculate`
- `pcbsmith simulate-ngspice`
- `pcbsmith design-divider-highpass-led`
- `pcbsmith review-bundle`

Evidence tools:

- `pcbsmith component-evidence-index`
- `pcbsmith evidence-cache-lookup`
- `pcbsmith datasheet-fetch`
- `pcbsmith datasheet-facts`
- `pcbsmith spice-model-index`
- `pcbsmith research-plan`

Revision tools:

- `pcbsmith revision-brief`
- `pcbsmith proposal-apply --dry-run`
- `pcbsmith proposal-validate`

AI tools:

- `pcbsmith ai-tool-contract`
- `pcbsmith local-agent-review`
- `pcbsmith ai-repair-response`

## Testing Roadmap

### Test Categories

- Unit tests for pure models and calculators.
- Snapshot tests for circuit objects and review bundles.
- Golden SPICE netlist tests.
- ngspice integration tests behind a `requires_ngspice` marker.
- KiCad CLI integration tests behind a `requires_kicad` marker.
- CLI smoke tests.
- Local AI contract tests with malformed model outputs.
- Regression tests using the old buck failure as an unsupported request.

### Required Test Fixtures

- Valid voltage divider fixture.
- Valid divider/high-pass/LED circuit object.
- Invalid unsupported buck request.
- Evidence cache hit fixture.
- Evidence cache miss fixture with mocked API response.
- Cached PDF fact extraction fixture.
- OCR/multimodal-required datasheet fixture marked advisory until reviewed.
- Sensor-board research plan fixture with required support roles.
- Missing support role fixture that blocks schematic generation.
- Missing ngspice fixture.
- Failed ngspice fixture.
- KiCad ERC fail fixture.
- KiCad DRC fail fixture.
- Malformed AI output fixtures.

### Environment Variables

- `PCBSMITH_KICAD_CLI`
- `PCBSMITH_NGSPICE`
- `PCBSMITH_DISABLE_PLUGIN_AUTOLOAD`
- `PCBSMITH_LOCAL_AI_BASE_URL`
- `PCBSMITH_LOCAL_AI_MODEL`

## Error And Status Vocabulary

Core statuses:

- `supported`
- `unsupported`
- `demo_only`
- `needs_datasheet_review`
- `needs_simulation`
- `simulation_unavailable`
- `simulation_failed`
- `pcbs_erc_failed`
- `kicad_erc_failed`
- `kicad_drc_failed`
- `needs_human_review`
- `ready_for_user_review`

Never use:

- `works` unless the specific validation authority and scope are named.
- `global` unless the behavior is implemented in shared code and tested.
- `production_ready` for any generated circuit in the near term.

## Research Anchors

These sources guide the roadmap:

- KiCad 10 CLI documentation: `kicad-cli` supports automated schematic ERC, PCB DRC, exports, and JSON/report output where relevant. Source: https://docs.kicad.org/10.0/en/cli/cli.html
- KiCad SPICE overview: KiCad integrates ngspice for schematic-editor simulation. Source: https://www.kicad.org/discover/spice/
- KiCad schematic documentation: KiCad can export Spice netlists, store datasheet fields, embed datasheets, assign SPICE models, and load external SPICE models. Source: https://docs.kicad.org/master/tr/eeschema/eeschema.html
- ngspice manual: batch mode supports command-line simulation and output logs. Source: https://nmg.gitlab.io/ngspice-manual/analysesandoutputcontrol_batchmode/batchoutput.html
- ngspice overview: ngspice is netlist/file based and can use device models from manufacturers and related SPICE formats. Source: https://ngspice.sourceforge.io/index.html

## Immediate Next Actions

These May reset actions are complete or superseded. Current execution order is
maintained in `docs/routing-placement-plan.md`. As of 2026-07-18 the immediate
work is to apply the accepted generic R2-R6 authority chain to bounded,
source-bound real thermometer inputs; close its complete geometry, escape,
BusGroup/order, policy/budget, live-ngspice, and semantic declarations; persist
and read back an accepted artifact only after exact acceptance; then run the R7
full regression and visual review. Do not infer a production/default migration
or a routed full-board golden from the bounded input slice.

## Done Means

The roadmap is working when a generated design can answer these questions with files, not vibes:

- What did the user ask for?
- What intent did PCBSmith classify?
- What topology was selected, and why?
- What evidence supports the topology and parts?
- What deterministic math was run?
- What simulation was run, and what did it measure?
- What schematic was generated?
- What did PCBSmith ERC say?
- What did KiCad ERC/DRC say?
- What is still demo-only or unsupported?
- What should the AI or user fix next?
