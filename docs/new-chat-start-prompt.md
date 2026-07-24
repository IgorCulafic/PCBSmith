# Suggested First Prompt For A Fresh PCBSmith Chat

We are continuing an existing project called PCBSmith in `D:\AI\PCB designer`.

Please start by reading:

1. `docs/project-reset-handoff-2026-05-18.md`
2. `docs/project-handoff.md`
3. `docs/roadmap.md`
4. `docs/presentation-brief.md`

Important context:

- PCBSmith is a free, open-source AI companion for KiCad.
- KiCad should remain the authoritative EDA backend.
- The previous long chat produced useful foundations, but it also exposed a
  serious flaw: PCBSmith can still jump from a user request to board generation
  without enough topology evidence, deterministic math, simulation, or
  schematic correctness.
- Do not assume the latest buck-converter output is correct. Treat it as an
  insufficient demo that revealed missing architecture.
- Do not generate a new PCB immediately.

The next goal is to design and implement the missing circuit-intelligence
pipeline:

1. intent classification;
2. topology selection;
3. reference/datasheet evidence;
4. deterministic math tools;
5. ngspice simulation integration;
6. schematic-first generation;
7. PCB generation from validated circuit objects;
8. consolidated validation and revision reports;
9. safe local-AI tool loop support.

Use ngspice as the first serious simulation backend. Falstad/CircuitJS may be
useful later for educational visual previews, but ngspice should be the
correctness/simulation layer because KiCad already integrates with it and can
export SPICE netlists.

Please begin by auditing the current repo and writing a concrete implementation
plan for the next vertical slice. The first vertical slice should be simple:

> Generate and validate a voltage divider connected to a high-pass filter and
> LED indicator using topology selection, deterministic math, schematic-first
> generation, ngspice simulation where practical, KiCad validation, and a single
> review bundle.

Be strict and honest:

- Do not claim something is global unless it is implemented in shared code and
  tested.
- Do not claim a circuit works just because ERC/DRC passed.
- Do not use familiar parts unless the selected topology and references justify
  them.
- If something is demo-only, unsupported, or needs human review, say so.
- Prefer small verified slices over impressive but untrusted generated boards.
