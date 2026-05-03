# PCBSmith Phase 0 Design

Date: 2026-05-03
Status: Approved direction, pending user review of this written spec
Source reference: `C:/Users/pitch/Downloads/PCB_Application_Specification.pdf`

## Project Decisions

PCBSmith is an open-source desktop PCB design application that will eventually let a user describe a circuit in natural language or code-like text and receive a validated schematic and PCB workflow. The first implementation milestone follows the PDF specification's Phase 0 exactly: no GUI and no LLM pipeline until the core domain model, project I/O, netlist derivation, validation, and CLI can run headlessly.

The working product and package name is `PCBSmith`, with the Python package name `pcbsmith`.

The project license will be `AGPL-3.0-or-later`. This matches the PDF's recommended direct use of `gerbonara`, keeps improvements to network-hosted derivatives open, and leaves room for commercial revenue through paid support, hosted services, enterprise features, training, integration work, and possible commercial dual licensing later.

Before accepting outside contributions, the project should add a contribution policy using either a Developer Certificate of Origin (DCO) or a Contributor License Agreement (CLA). A CLA is better if commercial dual licensing becomes a serious goal; a DCO is lighter-weight and more community-friendly.

## Phase 0 Goal

Phase 0 produces a trustworthy, testable foundation for later schematic editing, PCB layout, and LLM-assisted design. The key rule is that the LLM must eventually emit a structured intermediate representation that is validated before project state changes. That only works if the underlying data model and validators already exist.

The milestone is complete when a user can create, inspect, validate, save, load, and derive a netlist for a small PCBSmith project entirely from the command line.

## Scope

Phase 0 includes:

- Repository and Python package skeleton.
- Strict layered architecture: `ui -> services -> core`, with no imports flowing upward.
- Core IDs and geometry primitives using integer nanometre coordinates.
- Pydantic models for library symbols, pins, footprints, pads, schematics, boards, projects, and design rules.
- Pure netlist derivation from schematic objects.
- A small built-in development library of common components.
- Project folder I/O using JSON files.
- Minimal electrical rule checking for unconnected pins and obvious output conflicts.
- CLI commands for `new`, `info`, `netlist`, `erc`, and `validate`.
- Unit, property, snapshot, and integration tests for the Phase 0 behavior.

Phase 0 excludes:

- PySide6 GUI work.
- Natural-language prompting or LLM calls.
- PCB editor interaction.
- Gerber, Excellon, SVG, PDF, BOM, pick-and-place, or KiCad export.
- KiCad library import.
- FreeRouting integration.
- Any custom auto-router.

## Architecture

The codebase follows the PDF's three-layer architecture.

`core/` contains pure domain models and pure functions. It may depend on the Python standard library and Pydantic, but not on Qt, filesystem services, subprocesses, or LLM APIs.

`services/` contains application services and side effects. It may load and save projects, provide the built-in library, run ERC, and adapt core data into CLI-facing results.

`ui/` is reserved for later PySide6 interfaces. In Phase 0 the only user-facing executable surface is the CLI, but the import direction still treats UI as the top layer.

Import boundaries will be enforced by `import-linter` in project configuration so architecture drift is caught early.

## Data Flow

The Phase 0 command-line workflow is:

1. `pcbsmith new <project>` creates a project folder with metadata, a primary schematic, and an empty initial board file.
2. JSON project files are parsed into Pydantic models.
3. Schematic objects are passed to pure netlist derivation.
4. ERC services inspect the schematic and derived netlist.
5. CLI commands report project metadata, netlists, validation errors, and ERC issues without mutating state unless explicitly creating or saving a project.

The data model is the source of truth. SVG, Gerber, PDF, and other manufacturing or documentation outputs remain future exporters only.

## Error Handling

PCBSmith must fail visibly rather than fabricate values. Unknown symbols, missing pins, invalid coordinates, malformed JSON, duplicate references, and unsupported project versions should produce structured errors that can be displayed by the CLI now and by the GUI later.

Phase 0 should prefer typed exceptions or structured result objects over stringly-typed failure paths. User-facing CLI output can be plain text, but services should expose machine-readable issue codes where practical.

## Testing Strategy

Core model and geometry behavior must be covered first because every later phase depends on it.

Phase 0 tests include:

- Unit tests for IDs, geometry, library models, schematic models, board models, project models, netlist derivation, built-in library lookup, project I/O, and ERC.
- Hypothesis property tests for geometry and netlist invariants where useful.
- Snapshot-style tests for stable JSON serialization.
- Integration tests that run CLI commands against fixture projects.

The Phase 0 acceptance test is a small circuit, such as a voltage divider or LED resistor circuit, that can be created as JSON, loaded, validated, converted to a netlist, checked by ERC, saved, reloaded, and compared for stable behavior.

## Acceptance Criteria

Phase 0 is accepted when:

- The repository contains the PDF-aligned package skeleton.
- `python -m pcbsmith.cli new`, `info`, `netlist`, `erc`, and `validate` work on fixture projects.
- A valid sample project round-trips through save/load without semantic changes.
- Netlist derivation correctly joins pins, wires, junctions, and labels for the acceptance fixture.
- ERC reports at least unconnected pins and simple output conflicts.
- Core tests do not import PySide6 or any GUI dependency.
- Import-linter prevents upward imports.
- `pytest` passes for all Phase 0 tests.
- The README states the project purpose, license, Phase 0 status, and the rule that LLM output must be validated IR in later phases.

## Risks And Decisions To Revisit

The PDF is strong but broad. The main project risk is expanding into UI or LLM behavior before the domain model is stable. The design response is to keep Phase 0 headless and acceptance-test driven.

The license choice is intentionally protective. If future commercial dual licensing matters, outside contribution policy must be decided before accepting meaningful third-party patches.

The built-in library is a development crutch only. It should stay small and test-focused until the KiCad library import phase.

The board model exists in Phase 0, but board editing behavior does not. Its purpose is to establish the domain boundary between schematic and PCB early.
