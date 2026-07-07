# FLBACK-001 Rev B (NWES) vs PCBSmith flyback-r001

Reference: Zachariah Peterson / NWES LLC "Flyback Module" PN FLBACK-001
Rev B (2024-02-02), full Altium output pack at
`C:\Users\igori\Downloads\FLBACK-001-RevB` (schematic + fab drawing
PDFs, Gerbers, ODB++, NC drill, BOM). Same architecture as our
`design-flyback-authority` output: UCC28881DR offline switcher, custom
flyback transformer, LMV431 + LTV-817 opto isolated feedback, fusible
resistor + MOV input, RCD clamp, Y-capacitor across the barrier.

Ingested record: `ai_assets/references/flback-001/reference.json`.

## What the reference validates

- **UCC28881 pin map** — GND 1/2, FB 3, VDD 4, HVIN 5, NC 6, DRAIN 8:
  identical to our custom symbol and card.
- **Feedback architecture** — LMV431 (1.24 V) + optocoupler, divider on
  the secondary; theirs regulates 3.3 V with 130K/78.7K
  (1.24 * (1 + 130/78.7) = 3.29 V), ours with 20K/12K (3.31 V). Both
  E-series answers to the same equation.
- **Fusible wirewound resistor as the input protection** (Bourns
  FW30A10R0JA 10R 3W — the exact strategy our composition chose), MOV
  across the filtered line, TVS (SMBJ250A) across the rectified bus,
  RCD clamp with a series diode, single Y-cap bridging the isolation
  barrier. The topology-level choices in flyback-r001 are the ones a
  professional made.

## Design gaps the reference exposes (flyback r002 backlog)

1. **One bulk capacitor, not two.** They buffer 2 W with a single
   Rubycon 450BXW 10 uF / 450 V radial (10 x 16 mm). We placed two
   radial cans totalling 9.4 uF — and the second can is the sole
   reason the board grew to 92 mm during the courtyard crisis. Same
   capacitance, one can, higher voltage rating.
2. **Integrated bridge (HD06-T MiniDIP, 600 V 0.8 A)** instead of our
   four DO-41 diodes: one 4-pin package replaces a 16 x 24 mm diode
   field plus six interconnect traces.
3. **EMI/safety front end we lack entirely**: X2 film cap (Panasonic
   ECQ-UA 100 nF 275 VAC) across the line, two line-to-earth Y-caps
   (VY2 2.2 nF 300 VAC), an EARTH wire pad, and a GDT position (B1,
   unpopulated). Our line filter is only RF1 + RV1.
4. **Clamp parts have power/voltage ratings on their sleeves**: R1 is
   56K **2 W axial**, C1 is 1.5 nF **250 V** X7R, D1 is MURS160
   **600 V ultrafast (50 ns)**. Our composition picks generic-rated
   clamp parts; the calculator does not check clamp dissipation.
5. **Output stage**: 680 uF tantalum (7343 SMD) + 10 uF ceramic + a
   Murata BNX026 EMI filter block before the terminal. We stop at two
   capacitors.
6. **Test points** (TP1 rectified bus, TP2 secondary ground) — we have
   none.
7. **14-gauge wire pads** for mains entry (plus the terminal block only
   on the low-voltage output side).
8. **Dual-side assembly**: all THT/power on top, the entire SMD control
   circuit (U1, U2, U3, D1, D2, BR1, C4, R2-R7...) on the bottom.
   That is how they fit in **80.4 x 36.8 mm** (2958 mm^2) vs our
   92 x 50 (4600 mm^2). Our generator supports `part_flip` but the
   flyback layout never used it.
9. **DNP as a first-class BOM state** (C8, R6 marked "Do Not
   Populate") — frequency-compensation options kept on the board.
10. **The custom transformer is specified in the BOM itself**:
    "Core Type: EFD20/10/7, Core Material: N49, Turns Ratio 69:4".
    We emit a TRANSFORMER_SPEC_FINDING; the spec should also ride the
    BOM row. (Note their ratio 17.25 implies VOR ~ 64 V vs our 26/100 —
    both valid DCM design points; lower VOR trades drain margin for
    higher secondary PIV.)

## Placement intelligence (from the ODB++ component layers)

Exact placements (`ai_assets/references/flback-001/reference.json`,
36 parts, mm from the board origin at the west wire pads):

- **West-to-east power flow on top**: wire pads P1/P2/P3 at x=0 ->
  RF1 (8) -> RV1 (14.7) -> line Y-caps (15.8) -> X-cap (22.4) -> bulk
  C2 (27) -> transformer T1 centred at (42.2, 18.8) -> test points
  (59.7) -> output EMI filter F1 (65.6) -> J1 (71.4) at the east edge.
  One axis, no backtracking - the same discipline our row layouts
  encode, held on a shaped 2-D board.
- **The entire control circuit is on the bottom**: BR1 (21), TV1
  (29.9), U1 (35.4, 4.3), clamp C1/D1 (30.8/30.0), opto U2 (44.0)
  directly under the transformer's barrier region, then the secondary
  cluster D2/C4/U3/divider packed in x=50-59. The top face spends its
  area on the big THT safety parts; the bottom face is a dense SMD
  layout under them. That is how 2958 mm^2 fits what took us 4600.
- **The barrier sits under the transformer body**: primary bottom
  copper ends at U1/C1 (~x38); the opto at x44 and the secondary
  cluster from x50 straddle exactly where the transformer overhangs.
  Our BARRIER_X discipline matches this pattern; theirs simply spends
  no board width on an empty channel.

## Fab-output gaps (theirs vs our fab-package)

- Drill table with per-tool size, tolerance (+/-3 mil), plated state,
  hole count — our drill report has none of this.
- Fabrication notes: material (FR4 IPC-4101/126), thickness with
  tolerance (0.062" +/- 0.007"), finished copper weight, plating
  finish, soldermask spec (IPC-SM-840 Type B Class 3) + color, silk
  color, dimension units, IPC-6012 class. Ours has a fraction.
- Assembly drawing notes: IPC-A-610 class, J-STD-001, ESD handling,
  RoHS, revision marking.
- Board dimensions stated in dual units (mil [mm]).

## Process problems from building flyback-r001 (tooling backlog)

1. **Courtyard geometry was invisible until KiCad ran** — fixed during
   the build (exact F.CrtYd convex hulls in virtual DRC), the fix is
   permanent. Root cause: fp_circle parsed as two points.
2. **Silkscreen was invisible until KiCad ran** — 6+ full KiCad DRC
   round-trips were spent on reference-label overlaps, texts over
   pads, and the barrier line crossing part bodies. Virtual DRC needs
   a silk model (ref labels + board texts vs pads and part bodies).
   -> implemented as `silk_overlap`/`silk_over_pad` virtual checks.
3. **Placement iteration was hand-computed** — pad-by-pad clearance
   arithmetic in a scratchpad. The probe that finally cracked it
   (placed courtyard boxes + pairwise gaps) should be a standing tool,
   and the A* assisted router (plan 2.3) remains the structural fix
   for the 40-waypoint hand-routing sessions v4-v9.
4. **Patch-file fragility** — several patch scripts died on stale
   old-strings after the file had moved on. Smaller patches, or Edit
   directly on the live file, beat accumulating big atomic patch
   scripts.
5. **Reference packs are machine-readable gold** — this folder took
   minutes to mine (BOM xlsx is a zip of XML; DRR/REP are text; PDFs
   text-extract cleanly). -> implemented `pcbsmith ingest-reference`
   so every future pack becomes a stored, comparable record
   (hardening plan 4.3, previously blocked on the 403-walled website —
   local packs sidestep that).

## Disposition

| Item | Action |
| --- | --- |
| Virtual silk checks | DONE this session (virtual_drc) |
| Fab-notes + drill table enrichment | DONE this session (fabrication.py) |
| Reference ingestion CLI | DONE this session (`ingest-reference`) |
| DNP in the BOM model | DONE this session |
| Clamp dissipation check in the calculator | DONE this session (warning) |
| r002: single 450 V bulk cap, integrated bridge, X2+Y+earth front end, test points, dual-side SMD, compaction | NEXT flyback revision |
| Transformer spec into the BOM row | with r002 |
| A* assisted routing | plan 2.3, unchanged priority — now evidenced |
