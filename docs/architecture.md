# PCBSmith architecture guide (2026-07-12)

For the AI that inherits this codebase: what each module does, how the
pipeline flows, and where each piece could be improved. Companion
documents: `docs/project-history.md` (narrative), `docs/lessons-and-
pitfalls.md` (the mistake ledger), `docs/pcb-design-rules.md` (the
rulebook), `docs/routing-placement-plan.md` (the active roadmap).

## The pipeline in one paragraph

A plain-language request enters `circuit/intent.py` (keyword
classification into a known intent with typed assumptions), is matched
to a topology (`circuit/topologies.py`), composed into a full
CircuitObject by a per-topology generator (`generation/<name>.py` —
every component gets a ComponentRole with evidence references),
quantified by closed-form calculators (`calculators/electronics.py`),
exported as a KiCad schematic (`kicad/export_<name>.py`), proven by
kicad-cli ERC + a human-readable "reader" schematic with netlist
equality (`kicad/reader_schematic.py`), honestly simulated where
possible (`simulation/ngspice_<name>.py`), laid out
(`kicad/<name>_board.py` placements + `kicad/astar_router.py`), judged
three times (fast `kicad/virtual_drc.py`, semantic
`kicad/design_checks.py`, authoritative kicad-cli DRC via
`kicad/validate.py`), and bundled for human review
(`review/authority_bundle.py`) — always capped at needs_human_review.
The whole chain is deterministic; the CLI entrypoints live in
`cli.py` as `design-<topology>-authority` commands.

## Package map

### circuit/ — what the user asked for
- `intent.py`: keyword → intent id + assumptions dict. Deliberately
  dumb (deterministic); new topologies add keyword sets. IMPROVE: the
  keyword approach will collide as topologies grow; a scoring matrix
  with tie-breaking rules is the next step, still deterministic.
- `topologies.py`: intent → topology record (id, name, support
  status).
- `models.py`: ALL pydantic models — CircuitObject, ComponentRole,
  reports (Evidence/KiCad/Simulation/Board/DesignReview), authority
  status. `support_status` for ComponentRole: draft /
  needs_datasheet_review / supported ("reviewed" is only for
  topologies — a live gotcha).

### calculators/ — every number derived
- `electronics.py`: one solver per topology (flyback energy balance,
  buck, 555 astable, thermometer LED/I2C/LDO chain...). Contract:
  inputs are datasheet worst-case values with source strings, outputs
  a dict with references; hand-check tests assert the physics
  (energy balance), not just golden numbers. Known fix due: the trace
  current formula cites IPC-2221 but is the 2221A Fig 6-4 fit; 2221B
  defers to IPC-2152 (see books KB).
- `passive.py`: E-series snapping, dividers.

### evidence/ — facts carry provenance
- `acquisition.py`/`cache.py`: datasheet fetch + sha256 pinning into
  `ai_assets/datasheets/` + manifests. TI pattern
  `https://www.ti.com/lit/gpn/<part>` works headless.
- `extraction.py`/`llm.py`: the (dormant) LLM extraction path — needs
  ANTHROPIC_API_KEY or local server; NOT part of the design loop.
- `models.py`: component cards — pins with must_tie/nc contracts,
  facts with page-level locators and honest `assumption` status.
  Cards live in `ai_assets/components/*.json`; design_checks verifies
  boards against them (tie_nets, allowed_unconnected_pins).
- `nexar.py`: BOM pricing, dormant (no credentials).

### generation/ — per-topology composition (DATA, not machinery)
- One `compose_<name>()` per topology: full part list with roles,
  block references, findings (assumptions, omissions, firmware
  contracts), test steps. `blocks.py` is the reusable block registry
  (usb-c-power-entry, ldo-3v3-rail, rcd-clamp, isolated-feedback,
  ne555-button-astable, bjt-signal-inverter...) — new topologies
  should compose from blocks where possible and extend the registry.

### kicad/ — the heavy machinery
- `library.py` (~900 lines): parses REAL .kicad_mod files into
  FootprintSpec (pads with kind/shape/drill — including custom-pad
  primitive extents and distinct "npth" kind — courtyard/fab hulls,
  silk marks). LIBRARY_FOOTPRINT_IDS is the roster; add footprints
  there. LAW: never assume geometry, always probe through this.
- `symbols.py`: same for .kicad_sym; `instance_pin_position_rotated`
  is the one true pin-position function (quarter-turn convention was
  probed against kicad-cli renders — do not reimplement).
- `board.py` (1418 lines): BoardLayout/BoardNetlist models, netlist
  XML export/parse, `render_board_from_layout` (embeds footprints
  verbatim, writes nets/tracks/vias/outline/silk), the generic row
  layout used by simple topologies, `FOOTPRINT_LIBRARY` singleton.
  IMPROVE: it has grown into a god-module; rendering, netlist io, and
  the legacy row-placer could split.
- `astar_router.py` (1009): the grid router. GridRouter builds
  blocked-cell sets per layer from `_collect_items` stadium obstacles
  (foreign pads get rect/roundrect/custom corner covers), plus
  outline-aware edge cells (scanline fill, lru_cached) and via
  masks (vias owe their own radius). `route()` connects each net as
  a Steiner-ish tree (tree |= targets after every leg), then
  string-pull smoothing (H/V/45 connectors checked against the same
  blocked sets), collinear merge, redundancy pruning (area
  containment, own vias included as covers). `route_board()`
  orchestrates: fine_pitch_nets phase (0.1 mm grid, declaration-order
  priority, own rip-up-by-reordering budget) then main pass (0.2 mm,
  estimate-length order + net_order override + rip-up). IMPROVE (the
  active roadmap): bus-group routing (leader + offset followers),
  congestion-aware cost, and honesty about its limit — per-net
  sequential A* cannot shepherd 20+ nets through a narrow corridor
  (proven by the thermometer).
- `virtual_drc.py` (1067): the fast pre-filter. Stadium copper model
  (UNDERESTIMATES by design — law 3), checks: clearance (with
  same-owner exemption and ~hole net-less obstacles carrying the
  0.25 mm hole rule), edge clearance vs outline polygon, courtyard
  hulls, pad connectivity per PHYSICAL pad, pour analysis, silk
  model (text metrics deliberately smaller than KiCad's real ~1.9x
  font height — real silk needs the live loop). When it
  false-positives the model is overestimating somewhere — fix the
  geometry, never loosen thresholds.
- `design_checks.py` (900): semantic rules — connector edges (with
  module-socket exemption), trace current (IPC fit), component-card
  contracts, isolation barrier (rule 10: barrier_x, gap, net sets,
  straddlers), net-group clearances, trace craft 11.1/11.2, keepouts.
  DesignChecksSpec is the per-board declaration surface — new rule
  classes get a spec knob, never a hardcode.
- `validate.py`: kicad-cli ERC/DRC wrappers (report_name param,
  sanitized), SVG export. `cli.py` (kicad/): process runner +
  kicad-cli discovery.
- `reader_schematic.py` (661): Track 9.1 — ReaderSpec (instances,
  orthogonal wires, labels, flags, no-connects), offline connectivity
  validator (splits wires at endpoints, union-find, rejects label
  teleports and drawn shorts, re-derives the machine pin→net table),
  renderer, netlist-equality comparator. Every topology needs a
  reader schematic; the validator runs at export so a bad drawing
  cannot ship.
- `shaped_board.py`: outline primitives (arcs, splice_rect_tab),
  silk_text/silk_line/clipped_circle_outline, the shaped Router used
  by hand-routed art boards.
- `placement_search.py`: hill-climbing placement optimizer with
  rotation/side-flip moves and `climb_placements` (proved on the
  flyback compaction). IMPROVE: this is the seed of plan phase 3 —
  wire the compatibility penalty matrix into its score, and couple it
  to routability probes instead of static heuristics.
- `layout_score.py`: whole-layout scoring used by search/judgment.
- `export_<name>.py`: machine schematics — INSTANCES tables
  (ref, lib_id, x, y, {pin: net}), stub wire + label per pin (EVERY
  net labeled or kicad-cli silently drops it), custom symbols only
  when no official one exists, sidecar PCBSmith.kicad_sym +
  sym-lib-table. `_render_project(min_through_hole_mm=)` writes the
  DRC constraint set.
- `<name>_board.py`: per-topology PLACEMENTS + outline + silk +
  checks-spec declarations + generate_<name>_board (netlist from the
  live schematic via kicad-cli, layout, board write, DRC+parity).
- `preview.py`: readable renders (-review.png, -top.png);
  `board_diff.py`: hand-edit learning input; `fabrication.py`:
  gerber/drill export; `spice.py`: kicad netlist export;
  `schematic_builder.py`: legacy ladder builder (superseded by
  label-net exporters but still used by early topologies).

### simulation/ — honest ngspice
- `ngspice.py`: runner (batch, meas parsing via ngspice_buck helper).
- One module per topology simulating ONLY what is honest (op/behav
  models from datasheet points); every report states what is NOT
  simulated. The reconciliation section of the bundle repeats it.

### review/, reporting/, revision.py
- `authority_bundle.py`: the review-bundle-v2 JSON — reports,
  artifacts, revisions; `_authority_bundle_status` caps at
  needs_human_review (law 4 — never weaken).
- `review_pack.py`: human-readable markdown pack + bench test steps.
- `revision.py`: failure-code → revision-plan mapping.

### services/, core/ — the older interactive layer
Project/schematic/board JSON io and a built-in symbol library used by
`new/erc` CLI commands and the frontend contract; mostly stable, not
part of the authority pipeline.

### ai/ — topology forge (offline LLM, optional)
`topology_forge.py` drafts topology specs against a local
llama-server; output is raw material only — it still faces the full
authority chain. Dormant without a local server.

### cli.py (repo root src/pcbsmith/cli.py)
All commands. The authority commands are near-clones per topology —
IMPROVE: extract the shared authority skeleton (evidence → schematic →
ERC → reader → sim → board → checks → bundle) into one driver
parameterized by a topology descriptor; the ten copies have already
drifted subtly (compare error texts).

## Test architecture
- `tests/unit/kicad/`: per-module + per-board fast tests. Fixture
  discipline: every check must have a test where a DELIBERATE
  violation fires it.
- `tests/golden/test_regenerate_all.py`: regenerates every topology
  through the LIVE pipeline (kicad-cli + ngspice), asserts
  terminal-clean. Gated by PCBSMITH_GOLDEN=1, ~10-15 min. It has
  caught every subtle regression — run it before any commit touching
  kicad/ or calculators/. Thermometer is NOT in it yet (board
  unrouted — add with r002).
- Env: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, -p no:cacheprovider, venv
  python only.

## Where the biggest improvements live (ranked)
1. Bus-group routing + congestion awareness (plan phase 2) — the
   proven ceiling of the current router.
2. Placement-compatibility engine on top of placement_search (phase
   3) — placements are still hand-authored data for complex boards.
3. Authority-skeleton extraction in cli.py (ten near-clones).
4. Voltage-aware clearance classes (phase 1, from IPC-2221B audit).
5. board.py decomposition; pour analysis is bbox-based (polygon-exact
   is a standing frontier item).
6. Reader schematics for the pre-Track-9.1 topologies (buck,
   detector, divider, mpu6050, pear, led-art, clover).
