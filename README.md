# PCBSmith

PCBSmith is an open-source PCB design application foundation. The long-term goal is to let users describe circuits in natural language or code-like text, validate that intent as structured intermediate data, and turn it into schematic and PCB project data.

Phase 0 is deliberately headless. It builds the data model, project I/O, netlist derivation, minimal ERC, and CLI before any GUI or LLM workflow.

## Hard Rules

- Schematic and PCB are separate domains linked by a netlist.
- The data model is structured JSON/Pydantic. SVG, Gerber, PDF, and manufacturing files are export-only.
- Future LLM features must emit validated intermediate representation before project state changes.
- Core code has no UI or service imports.
- Coordinates are stored as signed integer nanometres.
- Unknown parts, pins, and values are surfaced as errors instead of fabricated.

## License

PCBSmith is licensed under AGPL-3.0-or-later.
