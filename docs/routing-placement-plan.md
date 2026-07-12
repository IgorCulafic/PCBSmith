# Layout-craft rebuild plan (2026-07-11)

The user's directive after the thermometer board stalled: rebuild trace
and placement craft from researched rules — bus routing, component
compatibility, dual-side placement — "properly, not haphazardly."
Every phase below cites the book notes in `docs/reference/books/`
(rules carry THRESHOLD/WHY/WHERE/MACHINE FORM/APPLICABILITY there);
nothing gets encoded without its applicability range. Execute phases
in order; each ends with the standard gates (ruff, mypy, pytest,
golden) and a commit.

## Phase 0 — finish the knowledge base (first session after this)

- Distill `johnson-hsdd` (446 OCR'd pages) and `ipc-7351` (85 pages)
  from `.book-cache/` with the same agent brief as the other seven
  (see `docs/reference/books/README.md` protocol). Johnson: crosstalk,
  terminations, layer strategy; IPC-7351: courtyard classes — audit
  our courtyard margins against the standard's density levels.
- Write `docs/reference/books/CONSOLIDATED.md`: one table of every
  machine-encodable rule across all nine sources, deduplicated, with
  contradictions resolved EXPLICITLY (e.g. Ott same-value decap arrays
  vs decade-pair lore; Ott 10 MHz 2-layer cap vs our 50 MHz class;
  Bogatin "proximity is weak, loop area is first-order" vs app-note
  "as close as possible"). This table feeds ai-rule-suggestions.md
  entries for user promotion.

## Phase 1 — audit fixes from IPC-2221B (cheap, do immediately)

From `ipc-2221b.md` (all with exact table cites):
1. Fix the citation in `calculators/electronics.py`: the current
   formula is IPC-2221A Fig 6-4 (2221B defers to IPC-2152); add
   k=0.024 internal-layer coefficient for future internal routing.
2. Voltage-aware clearance: `DesignChecksSpec` gains net voltage
   declarations; virtual clearance check upgrades from flat 0.2 mm to
   the Table 6-1 band for the net pair's voltage class (A6 uncoated
   external: 0.25 mm at 16-30 V, 0.4 at 31-50 V, 0.5 at 51-100 V,
   the 171-250 V band for flyback primary nets). Flat 0.2 stays the
   floor for <=15 V logic.
3. Rulebook §10 wording: replace the nonexistent "pollution-degree
   tables" citation with the real Table 6-1 B3 cell; value 6.4 mm is
   confirmed unchanged.
4. New checks: annular-ring minimum (Table 9-2), component-body-to-
   edge 1.5 mm (placement check), residual-laminate-between-holes
   0.5 mm. Fixture tests prove each fires.

## Phase 2 — bus routing (the core machinery; fixes the thermometer)

Design (grounded in the user's example image + Montrose 3-W + Bogatin
crosstalk scaling + TI SPRAAR7 from the research digest):
1. `route_board(bus_groups=...)`: topology data declares ordered net
   groups (e.g. SEG1-8 from U2 to its resistor column). The router
   routes the group LEADER with A*, then generates FOLLOWERS by
   geometric offset at constant pitch (width + clearance + margin),
   with matched bends (offset polyline, mitered at 45-degree
   stations), and per-net pigtails from bundle entry/exit to pads
   (reuse the fine-grid escape machinery for pigtails).
2. Follower legality: offset copies are checked against the SAME
   blocked sets as searched routes; where an offset segment collides,
   the group falls back to A* for that member (log it — no silent
   degradation).
3. Checks: 11.6 bundle coherence (>= X% of member length within one
   pitch of a neighbour, bends at shared stations); 11.8 spacing
   classes — foreign-net-to-bundle >= 3W centerline (Montrose §1.1:
   ~70% flux boundary; APPLIES: <= 4-layer boards, any edge rate),
   clock/periodic nets wider class; intra-bundle pitch may be
   manufacturing minimum for same-bus members (justified: same-cycle
   register outputs, Bogatin crosstalk scaling in bogatin-spi.md
   R11-R16 — our >= 3 ns edges and < 76 mm runs are sub-critical,
   bogatin R4-R6).
4. Pilot: thermometer SEG bundles (16 nets, 2 groups), then the
   stem control trunk (SER/SRCLK/RCLK/OE as a 4-net bundle). This
   plus phase-3 placement is expected to make the board routable;
   do NOT hand-iterate placements again before bus routing exists.

## Phase 3 — placement-compatibility engine

Component cards + DesignChecksSpec gain declarations; placement_search
gains penalty terms; checks enforce (each cites its book rule):
1. Thermal keepouts: sensor-class parts declare heat-source distance
   + thin-trace entry + moat candidacy (Sensirion design-in via
   research digest; Williams T1-T5 §9.6.4: hot parts to board edge,
   away from precision/electrolytics; 1 C = 5 %RH at 90 %RH).
2. Antenna keepout zones: module cards declare the antenna extent;
   checks: antenna over/at board edge, >= 15 mm clearance, no copper
   under (Espressif; thermometer r001 VIOLATES this - U1 antenna
   points into the bulb over copper).
3. Decoupling connection quality: per-IC decap must exist within
   declared distance AND its routed loop (pad->cap->pad) length/via
   count is the graded metric — loop area first-order, proximity
   logarithmic (Bogatin 13.15; Ott D1-D8 with mounting-inductance
   numbers; Williams 0.5 in / 20 nH-per-inch bound).
4. Crystal/oscillator keepout (for future discrete-crystal boards):
   foreign-trace keepout zone, 13 mm I/O separation (Ott), guard ring
   + local ground (ST AN2867 via digest).
5. Hot-loop area metric for switching topologies: computable enclosed
   area of input-cap/switch loop, minimized and reported (ADI AN-139
   via digest; Ott SW1-SW2; Montrose loop-area rules).
6. Connector zoning: all off-board connectors in ONE edge zone
   (Ott IO1 mechanism: inter-connector ground potential drives cable
   CM radiation, ~5 uA at 50 MHz fails FCC B). Rule 1.1 gains its WHY.
7. 2-layer ground discipline: ground-grid/return-adjacency metric —
   grid cell loop area <= 1.5 in^2 (Montrose §5.4) / cells <= 0.5 in
   (Ott GR1-GR5); clock-class nets need parallel ground copper within
   one trace width for the run (checkable on routed layouts).

## Phase 4 — dual-side placement gate

1. Footprint mass/wetted-perimeter table; FLIPPED_REFS gated by the
   SAC305 retention ratio (~0.0269 g/mm, 20% margin — SMTA data via
   research digest; mechanism confirmed Coombs 43.3.3.2.1 which gives
   NO number — keep the SMTA value labeled as the source; IPC-A-610
   R24: no adhesive requirement for reflowed bottom side).
2. Heavy-part rule: transformers/large connectors on last-reflowed
   side only (Coombs 43.3.2); neighbor-gap budgeting adds 0.5*W
   Class-2 side-overhang allowance (IPC-A-610 chip tables).
3. Wire into placement_search side-flip moves (already exist) as a
   hard gate + into design checks as a blocker with the ratio in the
   message.

## Phase 5 — thermometer r002 (apply everything)

1. Rotate/replace U1 so the antenna faces the bulb edge with a
   copper-free zone (or cut the zone per Espressif fallback).
2. Sensor moat: milled slots >= 1.0 mm around the SHT31 bulb area
   (Coombs 38.2.1/38.6.6: routine, router-diameter floor), thin
   sensor traces, minimal copper (Sensirion).
3. Bus-route the SEG groups and control trunk; placement via
   placement_search with the phase-3 penalty matrix, NOT hand
   iteration.
4. Full authority + golden entry (command and tests already exist and
   are committed).

## Standing constraints for whoever executes this

- The pipeline stays 100% deterministic — no LLM in the loop.
- Every rule encoded must carry its applicability range in the
  rulebook; judgment-call rules go through ai-rule-suggestions.md.
- Run the golden suite before any commit touching kicad/ or
  calculators/ — it has caught every regression.
- The books are NOT to be re-read wholesale: the notes in
  docs/reference/books/ are the durable extraction; consult the
  .book-cache text (sha-pinned) only to verify a specific locator.
