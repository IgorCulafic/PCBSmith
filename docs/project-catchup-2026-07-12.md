# PCBSmith catch-up — 2026-07-12

> **Historical snapshot.** This document predates the successful R005
> thermometer, R006 3D pilot, 41-source intake, and Phases 10-12. Use
> `docs/current-state.md` for current status; retain this file for historical
> failure and research context.

This document reconciles the repository, the July 10–12 Claude session
logs, and the handoff documents after the thermometer challenge and the
layout-craft research wave. It is a current-state supplement, not a
replacement for `CLAUDE.md`, the rulebook, or the active plan.

> **Knowledge amendment (2026-07-14):** Read
> `docs/reference/current-materials-knowledge-base-2026-07-14.md` and
> `docs/reference/standards-table-reverification-2026-07-14.md` as the
> current 31-source synthesis before using the older candidate rules below.
> `docs/reference/books/CONSOLIDATED.md` is historical first-wave candidate
> data and does not override the newer authority/applicability holds.

## Current state

- The pipeline is deterministic. The AI develops topology data and
  reusable machinery; generated designs still pass evidence,
  calculation, schematic, simulation, KiCad, design-check, and review
  gates. Clean output is capped at `needs_human_review`.
- Nine topologies are registered in the live golden suite: divider,
  buck, LED art, MPU-6050, clover, pear, metal detector, flyback, and
  servo555.
- The thermometer is topology ten, but it is **not** a completed board
  and is not in the golden suite. Its machine and reader schematics,
  simulation, authority command, component evidence, and fast tests
  landed. No current routed board exists.
- The source manifest now pins 31 exact sources. The original nine-book
  distillation and 72-rule spot check remain useful provenance, while the
  July 14 synthesis is the current cross-source entry point and separates
  verified statements from applicability and project severity.
- `docs/routing-placement-plan.md` is the active roadmap. Phase 0 is
  complete. Phase 1 (IPC audit fixes), Phase 2 (bus routing), Phase 3
  (placement compatibility), and Phase 4 (dual-side placement gate)
  precede thermometer r002.

## Recovered routing visual criteria

The July 10 comparison between the servo555 board and an older 555 PWM
dimmer was initially misunderstood. The older board was only an example
of the desired 45-degree bend shape; it was never ground truth for the
whole routing strategy.

The actual target is professional river/bus routing:

1. Related pins escape individually for the minimum practical distance.
2. Related nets gather quickly into a uniform-pitch ordered bundle.
3. The bundle uses a shared corridor and takes bends at matched
   stations, normally with 45-degree craft geometry.
4. Nets fan out again only near their destinations.
5. The layout preserves large contiguous free regions instead of
   scattering independent routes across the board.
6. Follower legality is checked against the same obstacles as searched
   routes; degradation to individual routing must be explicit.

The user's example and linked blog motivated research; they are not
normative sources. The research corrected an important misconception:
90-degree corners are not a material signal-integrity problem at this
project's ordinary edge rates. PCBSmith keeps clean 45-degree routing as
craft, readability, and manufacturability, not as false high-speed
physics.

Trace readability is a review requirement, not cosmetics. The existing
Rule 11 pipeline remains route → smooth → merge → prune → check. Useful
quality signals include zero covered/redundant segments, no acute
corners outside pad copper, restrained via count, and long coherent
runs rather than chopped grid artifacts.

## Thermometer acceptance and failure

The brief was for a premium functional-art thermometer: a centered
16-LED mercury column aligned with a traditional 0–50 °C scale, clean
front-side presentation, sensor airflow, two OLEDs, symmetry, and
control electronics and passives primarily on the back. Board
proportions were explicitly allowed to grow for manufacturability; the
scale endpoint at 50 °C was not optional.

The challenge's acceptance criterion was a complete, authoritative PCB,
not merely a calculator, schematic, attractive preview, or collection
of reusable fixes. After more than two hours and seven long routing
attempts, different nets continued to fail in the 24 mm stem. Igor
stopped the run and called the test a failure. A superseded preview that
once completed virtual routing is historical evidence only; it is not a
current authoritative board.

The structural diagnosis is that sequential per-net A* plus reordering
cannot reserve and share a narrow corridor for more than twenty related
nets. Do not resume hand-tuning placements. Thermometer r002 is gated on
bus routing and placement compatibility. Even then, success is a
hypothesis, not a promise; widening the stem or changing component
choices remains a legitimate fallback.

Known r002 corrections include orienting the ESP32-C3 antenna at a board
edge with its copper-free keepout and thermally isolating the SHT31 with
a milled moat, low-copper connection, and suitable spacing from heat
sources.

## Genericity and process lessons

- A challenge board must exercise reusable machinery. Topology-specific
  composition, placements, and artwork are data; geometry, routing,
  validation, and checks must not be hardcoded solely to make one board
  pass.
- Probe feasibility before paying for a full dense-board route. The
  thermometer consumed seven roughly 40-minute attempts; a focused
  corridor/source-pin probe exposed more in roughly ten minutes. After
  the first structural failure, isolate the contested corridor and test
  it directly.
- A rendered artifact can look complete while its current authority
  chain is failed. Report the current board, route, ERC/DRC, and review
  status separately.
- Research technical and primary sources, record applicability, and
  verify user claims independently. A useful example is not automatically
  a rule source.
- Delegate well-specified extraction and mechanical verification work,
  but review load-bearing thresholds and contradiction resolutions
  before encoding them.

## Source and log inventory

- `Books/` and `.book-cache/` are intentionally Git-ignored. The
  cache manifest now pins 31 exact sources. Source-specific notes live under
  `docs/reference/books/`; start with
  `docs/reference/current-materials-knowledge-base-2026-07-14.md` and its linked
  standards re-verification. Treat `CONSOLIDATED.md` and `SECOND-WAVE-2026-07.md`
  as historical extraction layers.
- The raw Claude export is under `Old Chat Logs/` and is currently
  untracked. The engineering session
  `a1240cbf-d4bc-4570-8c80-88e93fef3b96.jsonl` covers July 10–12 and
  includes embedded images, subagent logs, workflows, and tool output.
  The June session `ed22100a-fca5-43f5-8803-c791245bd7f2.jsonl` concerns
  the funding-video mockup GUI rather than PCB engineering.
- Recovered Claude memory files under
  `Old Chat Logs/D--AI-PCB-designer/memory/` preserve the exact routing
  target and trace-craft feedback. Raw logs are supplementary evidence;
  canonical decisions still belong in committed documentation.
- The available logs do not cover the July 6/7 buck-edit conversation.
  The intent behind the user's D1 move by approximately
  `(+0.47, -6.50 mm)` remains unknown. Do not promote it into a placement
  rule without asking the user.

## Preservation risks

At the time of this reconciliation, the branch is 16 commits ahead of
its remote. Those commits contain the thermometer slice, research and
book knowledge base, and handoff work. Push or otherwise back them up
before treating the work as durable.

`Books/`, `.book-cache/`, and the raw chat export are not protected by
Git. Preserve them separately, with checksums where practical. Avoid
committing copyrighted books or raw logs containing embedded images and
large tool traces.

## Verification snapshot

- The repository collects 435 tests. The full default suite completed with
  exit code 0; nine environment-gated golden cases were skipped as designed.
  A focused router/placement/check/reader/thermometer subset passed 56/56.
- Ruff passed on `src`, `tests`, and `tools`. Import-linter analyzed 102 files
  and kept both architecture contracts.
- Strict mypy is clean across 102 source files when checked for the actual
  Python 3.12 runtime. The configured Python-3.11 gate currently fails before
  project analysis because installed NumPy 2.5 stubs contain Python-3.12 type
  statements. Resolve the environment/pin mismatch; do not misreport it as a
  PCBSmith type error.
- The live golden suite was not rerun because this audit changed documentation
  and ignored extraction caches only, not `kicad/` or calculators.
- Implementation inspection confirms only plan Phase 0 is complete. Phase 1
  rules, negotiated congestion/bus routing, compatibility placement, the
  dual-side physical gate, and thermometer r002 remain unimplemented. Detailed
  file/function evidence and primary-source algorithm research are in
  `docs/routing-placement-research-update-2026-07-12.md`.
## Prioritized work

1. Preserve the 16 local commits and separately back up ignored source
   material and the raw chat export.
2. Reconcile the July 14 policy holds into Phase 1, then build shared profile
   authorities. Relabel or deprecate the legacy IPC-2221A current fit; do not
   add the old internal `k=0.024` branch as if it were IPC-2152. Keep ordinary
   PCB/fab electrical spacing separate from a complete IEC/product
   `InsulationProfile`; add profile-aware annular-ring, body-edge, residual-
   laminate, and spacing checks with deliberate-failure fixtures.
3. Add deterministic negotiated congestion around the existing exact obstacle
   kernel: full-net rip-up, present/history costs, zero-overuse acceptance,
   fixed budgets, and explicit telemetry.
4. Add shaped-outline-aware coarse capacity/corridor planning so narrow cuts
   are measured before expensive detailed routing.
5. Add ordered bus terminal/lane assignment and then coherent follower
   geometry. A leader plus offsets is a realization method, not the global
   solution; degraded fallback must be explicit.
6. Make placement probes preserve shaped geometry and all routing options,
   screen candidates with net-separation/capacity surrogates, then add antenna,
   thermal, decoupling, hot-loop, connector, return-path, and dual-side gates.
7. Attempt thermometer r002 only after those probes and gates exist. Correct the
   antenna using the module-specific edge/cutout figure and keep the 15 mm
   enclosure clearance separate. Sensirion's current guide has been
   text-verified online, but needs a local provenance pin and supplies no
   universal moat geometry.
8. Acquire the applicable end-product safety standard, current IEC 60664-1
   including AMD1:2025 plus IEC 60664-4, IPC-2221C/IPC-2222B, and IPC-7093A;
   then current acceptance/process sources where the product claims need them.
   Also pin selected-part drawings, current Sensirion/SMTA sources, USB 2.0
   electrical sources, and selected fab/assembler profiles. IPC-2152 remains
   useful historical model-validation data but is no longer maintained.
9. Backfill seven reader schematics, extract the duplicated authority skeleton,
   make pour analysis polygon-exact, and promote compact flyback only through
   its production authority path.
