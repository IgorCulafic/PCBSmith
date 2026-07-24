# Pinscope method audit and review-convention integration

**Date:** 2026-07-24
**Status:** first implementation slice complete; provider orchestration and
production caller integration remain open
**Pinscope snapshot:** commit
`b26ad3509f4a19878fb7050aad3da9eacba8d914` (2026-07-17)
**Licensing:** Pinscope is AGPL-3.0; PCBSmith is AGPL-3.0-or-later. The licenses
are compatible, but the current slice is independently written PCBSmith-native
code. The Pinscope repository and prompts were used as method references, not
copied source.

## Executive assessment

Pinscope is a design-review assistant; PCBSmith is an independent generator.
Pinscope is therefore one research specimen, not a target architecture,
dependency, quality authority, or product model. Several of its methods are
still useful as internal safeguards inside generation. Its most relevant work
is the accumulated control logic around an uncertain reviewer:

- build a component/net graph before asking a model questions;
- review one IC and a bounded neighborhood at a time;
- expose every pin, net neighbor, and multi-net support component;
- turn the review into an explicit coverage obligation rather than stopping
  after the first finding;
- require cross-IC claims to consult the other component's evidence;
- cap evidence queries per concern and convert unresolved claims to
  `UNVERIFIED` rather than guessing;
- seed deterministic findings independently of model review;
- retain per-IC traces, recover when the model emits prose instead of the
  required tool call, and isolate component failures;
- normalize and deduplicate conservatively, never allowing a later model pass
  to make a finding more severe without new evidence;
- test deterministic sampling, concurrency bounds, pause/resume persistence,
  excerpt budgets, trace failures, and malformed model output.

PCBSmith is already stronger in physical-board authority, immutable generation,
KiCad read-back, exact routing evidence, evidence applicability, and visual
review packages. The useful Pinscope methods should complement those generator
stages: validate selected components and generated connectivity automatically,
feed findings back into repair/regeneration, and retain evidence for the final
result. They should not create a separate assistant-style workflow or require
routine human per-component review.

## What was inspected

### Claude skills and extraction

Pinscope has three relevant skills:

1. `extract-pintable` extracts package identity, pin count, pin names,
   functions, and taxonomy.
2. `extract-specs` extracts a constrained set of part parameters and SPICE
   values.
3. `extract-pattern` learns passive MPN/ordering-code patterns and decoders.

The prompts are materially stronger than their local validators. In
particular, the pin-table validator checks required fields and duplicate pin
numbers but does not enforce package `pin_count == len(pintable)`. The passive
pattern validator compiles the regular expression and tests examples but does
not fully enforce field-position non-overlap, lookup completeness, or complete
field-to-regex correspondence.

PCBSmith's existing fact extractor is stronger in other areas: it requests only
role-relevant fact names, records conditions and locators, binds the exact part
variant, rejects unrequested facts, and can use provider-enforced JSON schema.
Before this audit it did not have an exact-package pin-table evidence object.

### Graph and component context

Pinscope's context builder:

- orders pins by the extracted datasheet pin table;
- shows each pin's net, net classification, trusted voltage tag, alternate
  functions, and connected components;
- summarizes large supply/ground nets while retaining connected ICs;
- lists components bridging two or more IC nets, which makes feedback,
  sense, bootstrap, termination, and snubber roles visible;
- reconciles likely exposed-pad numbering differences;
- shows datasheet pins absent from the schematic and schematic pins absent from
  the extracted pin table.

This is substantially better than feeding a whole schematic image or flat
netlist to a reviewer. It directly addresses the failure mode where a model
sees a capacitor on one supply pin but misses the second endpoint or a
parallel support component.

### Review prompt and evidence discipline

The strongest prompt rules are:

- enumerate all relevant areas before investigating;
- account for every area as passed, finding, unverified, or not applicable;
- resolve datasheet example designators to the project's real designators;
- report only actual issues; correct checks belong in coverage, not findings;
- permit an `ERROR` only when the stressed object, actual value, applicable
  limit, and strict inequality are all established;
- use the limit for the exact stressed pin, not a nearby supply limit;
- never infer a rail voltage merely from a descriptive net name;
- never guess an upstream regulator reference voltage;
- identify the electrical role of an external part before judging it;
- consult the connected IC's datasheet when an interface claim depends on the
  neighbor's limits;
- distinguish pin-mux feasibility from interface direction;
- recheck pin labels and transceiver truth tables before a polarity/direction
  error;
- collapse one root cause into one finding;
- state that netlist review cannot establish placement, routing, thermal, or
  manufacturability facts.

These rules align with PCBSmith's existing `UNVERIFIED` and applicability
policy. They should become executable review contracts, not merely prompt
prose.

### Reviewer operations and tests

Pinscope also contains useful production lessons:

- temperature zero for repeatability;
- a bounded turn count and forced final submission;
- recovery on a text-only/no-tool turn;
- topic-filtered neighbor datasheet excerpts;
- global, per-neighbor, and fetch-count budgets;
- source hashes and tool-call transcripts in per-IC traces;
- incremental report writes for pause/resume;
- bounded concurrency with private per-IC accounting/logging;
- deterministic checks seeded even if no datasheet is available;
- explicit `not_reviewed` components;
- fail-soft trace storage that does not erase the engineering result.

The tests around these behaviors are more valuable than the exact provider
implementation because they define failure modes that future model changes
must not reintroduce.

## Implemented PCBSmith-native slice

The new implementation is:

- `src/pcbsmith/evidence/component_pin_evidence.py`
- `src/pcbsmith/schematic_review_ir.py`
- `tests/unit/evidence/test_component_pin_evidence.py`
- `tests/unit/test_schematic_review_ir.py`

It provides:

1. **Exact-package pin evidence.** Package variant, pin count, pin names,
   electrical roles, functions, source hash, source file, and per-pin locators
   are typed. Partial extraction, duplicate pins, wrong variants, or missing
   locators fail.
2. **Strict extraction request.** The prompt requires every pin/ball/exposed
   pad, exact ordering variant, verbatim pin identity, and no family-member
   substitution.
3. **Deterministic circuit neighborhood.** PCBSmith builds pins, nets,
   neighbors, unused pins, orphan schematic pins, and bridge components from
   the canonical `BoardNetlist`, not from model prose.
4. **Derived review obligations.** The actual component context activates pin
   mapping, power/decoupling, cross-IC interfaces, absolute maximum,
   configuration, clock, required external components, and unused-pin review.
5. **Applicability-aware outcomes.** Each obligation is `applicable`,
   `not_applicable`, or `unresolved`. Unresolved work cannot be promoted to a
   hard pass or hard failure.
6. **Coverage closure.** The manifest rejects missing, extra, or duplicate
   results. A list of vague `checked_areas` is not sufficient.
7. **Evidence/query discipline.** Passes require cited evidence or a
   deterministic check. Failures require finding identities. Evidence queries
   have an explicit declared budget.
8. **Replay binding.** The neighborhood and complete manifest are bound to the
   exact canonical netlist and pin-evidence fingerprints.

Ten focused tests pass and Ruff passes for this slice.

## Useful methods not yet implemented

Priority order:

1. Integrate the obligation manifest as an automatic validation-and-repair
   stage inside the transactional generator. The automated reviewer can only
   submit typed outcomes; routine per-component human operation is not a
   product requirement.
2. Add retained per-IC traces, no-tool-call recovery, forced final submission,
   and incremental persistence as internal generator telemetry.
3. Add bounded neighbor-evidence retrieval using PCBSmith's source cache and
   evidence locators. Use page/topic selection only as an optimization; a miss
   must remain `UNVERIFIED`, never "not in datasheet."
4. Add deterministic alternate-function feasibility after exact pin-function
   extraction is production-ready.
5. Add conservative normalization and semantic deduplication that cannot
   increase severity or discard evidence/coverage.
6. Add bounded concurrency only after deterministic sequential operation and
   replay are proven.
7. Add passive MPN-pattern extraction only when a real family-volume need
   justifies it; strengthen validation beyond Pinscope's current checker.

## Methods deliberately not copied as rules

- "A larger capacitor always satisfies a smaller capacitor requirement" is
  too broad. Capacitance minima may also depend on DC bias, tolerance, ESR,
  impedance versus frequency, stability range, package, temperature, and
  placement. PCBSmith will accept this only when the cited requirement is
  strictly a minimum effective capacitance under matching conditions.
- Net-name voltage inference is context only, not numerical authority.
- Keyword-trimmed PDFs are a cost optimization, not proof that unmatched pages
  contain no relevant requirement.
- An IC prefix (`U`) is a useful provisional neighbor classifier but must later
  be replaced by exact component taxonomy.
- Model normalization or deduplication may not raise severity, invent evidence,
  merge distinct physical causes, or erase an unresolved obligation.
- A netlist reviewer cannot make layout, thermal, DFM, assembly, EMC, or
  manufacturability claims.

## Integration of the user-supplied review conventions

The supplied excerpt is treated as practitioner review guidance provided by
the user. It is not promoted wholesale into universal electrical law. The
rules are separated by authority.

### Release/checklist requirements

These should become explicit release-review obligations:

- project/board name, revision, date/year, and appropriate authorship/privacy
  treatment on the schematic;
- board name/revision/date or compact equivalent on PCB silkscreen;
- no overlapping text, lines, or symbols and no wires through symbols;
- component values and functional annotations where applicable;
- exact or shortened part identity next to active devices, with full ordering
  identity in the BOM/evidence manifest;
- connector family, pitch when ambiguous, and purpose;
- required polarity, pin-1, orientation, connector voltage, and power-polarity
  indications where applicable;
- reference designators and useful assembly/debug labels remain readable after
  assembly where space permits;
- heatsink/chassis-heatsink relationship is explicitly documented when
  present.

Failure severity still depends on consequence. Missing polarity on an
assembly-critical polarized part can block release; a missing LED color label
is normally review/style.

### Applicability-dependent electrical/layout rules

- trace/current-path capacity requires declared current, waveform, stack-up,
  copper, temperature rise, voltage drop, complete paths, neck-downs, vias,
  pads, zones, and connectors;
- ground floods are preferred only when they preserve intended current return,
  clearance, sensing, isolation, antenna, and switching behavior;
- sensitive-region routing restrictions require a declared crystal, antenna,
  RF, switching, high-current, or sensitive region and exact layer/geometry
  evaluation;
- mounting holes are a reviewed mechanical requirement, not mandatory for
  dongles, castellated modules, edge-clamped boards, or other mounting schemes;
- optoisolator/relay isolation claims require separated domains and power
  sources; shared ground invalidates a galvanic-isolation claim;
- regulator, 555, relay, RS-485, oscillator, and similar subcircuits require
  topology-specific evidence, not visual resemblance alone.

### Presentation conventions

These improve human comprehension but are not universal electrical blockers:

- positive rails above, ground below, negative rails oriented conventionally;
- pull-ups above signals and pull-downs below;
- decouplers visually adjacent to their IC power unit with visible
  connectivity;
- functional symbols instead of package-layout rectangles;
- left-to-right regulator signal flow and conventional relay/timer layouts;
- compact, collision-free reference/value placement;
- contiguous reference numbering for small single-sheet designs.

Reference-number gaps should remain advisory. Renumbering a maintained product
can damage revision continuity, ECO history, service documentation, and BOM
comparability. Large/multi-sheet numbering schemes are explicitly permitted.

## Conclusion

Pinscope does contain useful lessons, especially about controlling model
uncertainty and testing automated review behavior. It remains only one
research input and is not presumed to represent best practice everywhere. The
first complementary segment is now part of PCBSmith in independently written
form. The next narrow step is automatic generator integration and retained
traces, followed by bounded cross-component evidence retrieval. Human input
remains concentrated at initial intent/constraint approval, unresolved or
high-risk escalation, and final-result acceptance. The supplied schematic/PCB
conventions should enter the same obligation system with explicit
applicability and severity, not become one large unconditional checklist.
