# PCBSmith Board Manufacturability Checks Design

PCBSmith already treats KiCad ERC/DRC as the hard validation gate. This feature adds a lightweight PCBSmith-side board review pass that catches issues useful to the AI and the user before a proposal is considered polished.

The checker is advisory-first. It must not replace KiCad DRC, and it must not treat 45-degree routing as an electrical hard rule. It should flag route style and geometry risks in structured form so future AI loops can revise a board with concrete feedback.

## Scope

- Inspect the existing `Board` model without parsing KiCad files.
- Report machine-readable findings with severity, code, message, and location.
- Warn when a trace segment uses a non-cardinal/non-45-degree angle.
- Warn when a route has a very sharp turn.
- Error when same-layer copper traces from different nets are closer than the project clearance rule.
- Provide a CLI command that checks the first board in a PCBSmith project.

## Out of Scope

- Replacing KiCad DRC/ERC.
- Full footprint courtyard, solder mask, thermal, impedance, or current-capacity analysis.
- Autorouting or automatic repair.
- Schematic readability/polish.

## Success Criteria

- Unit tests cover non-preferred angle warnings, sharp-turn warnings, and trace-clearance errors.
- CLI tests cover clean and failing board-check output.
- The current 555 PWM dimmer board reports no blocking manufacturability errors.
- Full development checks still pass.
