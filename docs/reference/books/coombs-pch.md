# Coombs & Holden — Printed Circuits Handbook, 7th edition (distilled rules)

- Book: Clyde F. Coombs Jr. & Happy T. Holden, *Printed Circuits Handbook*, 7th ed., McGraw-Hill Education, 2016
- Source copy: EPUB, sha256 `04a939f09a9fc560ee1e4f7ed79d8a12bc954a7c2613c8db838d68c548920608` (`.book-cache/manifest.json`, slug `coombs-pch`, 108 cache files)
- Distilled: 2026-07-11 by Claude (Fable 5). Locators are chapter.section numbers as printed in the text.
- Scope filter: this is a 71-chapter fabrication/assembly encyclopedia; only rules that constrain PCBSmith's DESIGN output are extracted. Process-operation content (etchant chemistry control, oven maintenance, plating bath analysis) is deliberately skipped.

Rule fields: **THRESHOLD** (as stated) / **WHY** (process mechanism) / **WHERE** (ch.sec) / **MACHINE** (PCBSmith check or knob) / **APPLIES** (process class).

---

## 1. Etching: minimum feature capability and the "acid trap" question

### 1.1 The acid-trap verdict (the live question — settled)

The book never uses the phrase "acid trap." What it says instead:

- **Mechanism exists**: etchant flow in the microchannels between resist walls is diffusion-limited; "the narrower and deeper the channel, the slower the flow" — the middle of a group of closely spaced parallel lines etches slower than the outside lines, and "a sharp 90° angle has a slower-etching section in the inside edge of the bend." WHERE: 37.7.2.2. So acute/tight inside corners DO etch differently — the physical basis of the acid-trap folklore is real, but the failure mode described is *under*-etch (slivers/shorts risk in the pocket), not the folklore's over-etch of the acute point.
- **Largely obsolete at normal geometry**: uneven etch-out across the panel "occurs when etch action is more rapid at the edges of printed areas than in a broad expanse of copper … Modern etchers with reduced pooling of etchant have reduced this problem." WHERE: 37.6 (etching problems discussion, para. at "A problem common to etching"). Modern conveyorized spray etchers with controlled nozzle arrays (37.8.1.3) drive the microchannel flow deliberately; corner-angle effects only matter as features approach the fine-line limit (§1.2 below).
- **The residual design rule the book actually states**: "Trace entry into pads should not leave an acute angle which may cause fabrication issues." WHERE: 21.10 (routing tips list).

**Verdict for PCBSmith**: keep `trace_corner_angle` (no acute joints outside pad copper) as a fabrication-craft blocker — the book supports exactly that rule at the pad-entry/junction level — but do NOT add any further "acid trap" geometry checks (e.g. banning 90° corners); modern spray etch chemistry makes them a non-issue at our 0.2 mm-class geometry.
- MACHINE: existing `trace_corner_angle` check is the correct and sufficient enforcement; document rationale in rulebook.
- APPLIES: all subtractive-etch boards (i.e., everything PCBSmith emits).

### 1.2 Fine-line practical limit

- THRESHOLD: minimum reliable trace = minimum reliable gap ≈ resist thickness + foil thickness. For 1.2 mil dry film over 1 oz (1.4 mil) copper: 2.6 mil (0.066 mm) trace/gap floor; at R/B=1 the 2.6-mil trace bottom has only a 1.1-mil top surface.
- WHY: etchant in the channel between resist walls goes stagnant when channel depth (resist+foil) exceeds its width; undercut (≈0.5 mil per side on 1 oz) consumes the trace top.
- WHERE: 37.7.4.2 (Limitations—Practical Rule of Thumb), Table 37.2.
- MACHINE: min-trace/min-gap audit knob per copper weight: floor_mm ≈ (resist 0.030 + cu_thickness) with cu 1 oz = 0.035 mm → ≈ 0.066 mm. Our standard 0.2 mm trace/clearance has ~3x margin on 1 oz — no new check needed, but a `heavy_copper` variant must scale minimums with foil thickness.
- APPLIES: subtractive etch; thicker copper directly degrades achievable line/space (see §1.3).

### 1.3 Thick copper vs. fine features

- THRESHOLD: none numeric; stated as a yield cliff — "production yields are lower when trying to etch small features with thick copper"; standard is ½ oz outer / 1 oz inner.
- WHY: same channel-depth mechanism; more foil to etch through = more undercut and longer dwell.
- WHERE: 4.4.2 (Conductors), 4.4.3 (dedicated vs mixed layers).
- MACHINE: if a design ever specifies >1 oz copper, tighten min trace/gap proportionally (gap floor ≈ resist + foil per §1.2); prefer wider-than-minimum traces everywhere density permits ("use narrow conductors only where necessary" — 4.4.2).
- APPLIES: all boards; acute for ≥2 oz power boards.

### 1.4 Minimize minimum-width run length

- THRESHOLD: none numeric; probability statement.
- WHY: "The probability of an open or short increases with the length of the minimum width conductor."
- WHERE: 4.4.2.
- MACHINE: router policy (already partially embodied): use design-rule minimum width only in congested corridors; a post-route pass could widen traces where clearance allows. Candidate `min_width_run_length` metric in board stats, not a blocker.
- APPLIES: all boards.

## 2. Double-sided reflow assembly (two-pass process)

### 2.1 Which side reflows first / part retention upside down

- THRESHOLD: qualitative mass gate — components stay on the underside during pass 2 only while "the package weight exceeds the surface tension force of the molten solder" is NOT true; the book gives no g/mm² number (the industry 30 g/in² heuristic is NOT in this text).
- WHY: during the second reflow the first side's joints re-melt while facing down; molten-solder surface tension is the only retention unless adhesive is used.
- WHERE: 43.3.2 ("larger components should be placed on the side of the circuit board that is soldered last. If placed on the first side … large packages may fall off … unless those devices are secured in place with an adhesive or 'staking' compound"); 43.3.3.2.1 (adhesives when package weight exceeds surface-tension force).
- MACHINE: FLIPPED_REFS gate: (a) put the heavy/large side LAST in the reflow order — i.e. the back/first-pass side of a dual-side layout carries only small passives and low-mass SMDs; (b) flag any first-pass-side part above a mass/pad-area ratio threshold as `needs_adhesive` (threshold value must come from IPC/assembler data, not this book — mark as assumption); (c) BGAs/large ICs never on the first-pass side.
- APPLIES: double-sided SMT reflow (our flyback dual-side compaction and any future dual-side board).

### 2.2 Process sequences that constrain placement

- Double-sided SMT-only: bottom side is printed/placed/reflowed FIRST (paste + optional adhesive dispense + reflow), then top side. WHERE: 43.3.2 process list ("Double-sided, surface-mount only").
- Mixed technology with wave: bottom-side SMDs are ADHESIVE-BONDED and cured, top side reflowed, then through-hole + bottom SMDs wave-soldered together. Bottom-side SMDs exposed to the wave must tolerate immersion; parts that can't must be hand-soldered. WHERE: 43.2.4, 43.3.2.
- Step-solder alternative (high-temp alloy first pass) is "all but eliminated" for Pb-free (no higher-melting first-pass alloy above SAC). WHERE: 43.3.2.
- MACHINE: board metadata knob `assembly_sequence` (single_reflow / dual_reflow / mixed_wave); side assignment rules per §2.1; if mixed_wave, bottom-side SMD selection restricted to wave-tolerant chip parts (see §2.3).
- APPLIES: any dual-side or mixed THT+SMT design.

### 2.3 Adhesive side effects that touch pad design

- THRESHOLD: none numeric; constraint is geometric — adhesive dot must fit under the body between the pads.
- WHY: excess adhesive "run-out onto the solder pad or component I/O" ruins solderability; bleeding contaminates neighboring pads on dense boards.
- WHERE: 43.3.3.2.1.
- MACHINE: for parts flagged `needs_adhesive`, require a clear under-body gap between pads (body length − pad extent) ≥ dot diameter; practically: don't shrink pad-to-pad gaps below footprint nominal on glue-side parts.
- APPLIES: wave-soldered bottom-side SMDs and heavy first-pass reflow parts.

### 2.4 Reflow conveyor edge keep-out and thermal balance

- THRESHOLD: none numeric in text; "an edge keep-out area must be designed into the board" for pin-chain conveyors — with tolerance for board movement and machine-to-machine chain variation.
- WHY: pin-chain conveyors hold the board by its edges (mandatory for double-sided assemblies so bottom parts touch nothing); components too close interfere mechanically.
- WHERE: 49.3.1.2.1 (pin-chain), 49.3.6.5 (board design for oven reflow).
- MACHINE: `edge_component_keepout` knob (default 3–5 mm along the two conveyor edges, mark as assumption pending assembler data); design check: distribute thermally massive parts, don't cluster them at one board region (49.3.6.5) — advisory finding, not blocker.
- APPLIES: reflow-assembled boards, mandatory for double-sided (mesh belt needs a pallet otherwise, 49.3.1.2.2).

### 2.5 Tombstoning (small passives)

- THRESHOLD: none numeric; risk elevated for smallest chips with Pb-free pastes.
- WHY: higher surface tension of Sn-based Pb-free solder lifts one termination when the two ends reach liquidus unevenly.
- WHERE: 43.3.1 (Pb-free SMT effects), 49.3.5.3.2.
- MACHINE: keep the two pads of a chip part thermally symmetric: flag a chip passive with one pad tied to a plane/pour and the other to a thin trace (`thermal_asymmetry` candidate check); thermal-relief spokes on plane-connected chip pads.
- APPLIES: reflowed chip passives, worst for 0402 and below (we use 0805/0603 — low risk, keep advisory).

## 3. Solder paste / stencil constraints on pad design

### 3.1 Stencil transfer efficiency floor

- THRESHOLD: transfer factor 60% for very small apertures up to ~100% for large ones; stencil thickness is tailored to the finest-pitch part on the board.
- WHY: paste sticks to aperture walls; small aperture volume-to-wall ratio (area ratio) loses paste.
- WHERE: 43.3.3.2.3 (screen/stencil dispensing), 49.3.9.2.
- MACHINE: pad-design audit: one stencil thickness serves the whole side, sized by the finest-pitch device — so avoid mixing very fine pitch (<0.5 mm) with paste-hungry large THT/PiP joints on the same side unless a step stencil is acceptable (cost adder, 43.3.3.2.3). `stencil_conflict` advisory when min-pitch part and pin-in-paste coexist.
- APPLIES: all reflow boards.

### 3.2 Solder mask dams between pads

- THRESHOLD: dam width typically 2.5–3.0 mil (0.064–0.076 mm); capable fabs to 1.0–1.5 mil; LPI photoimageable mask required below ~3 mil.
- WHY: dams between fine-pitch pads block bridging during reflow; screen-printed masks can't resolve or register them.
- WHERE: 36.3 (webs "as narrow as 0.003 in"), 36.4.4.2.
- MACHINE: mask-slice audit: if the gap between adjacent mask openings < 0.1 mm, merge the openings (gang relief) rather than leave a sliver dam the fab will lose. Knob `min_mask_dam_mm = 0.1` (conservative vs the 0.076 typical).
- APPLIES: fine-pitch SMD footprints (0.5 mm-pitch and below is where it bites).

### 3.3 Trace-into-pad width ratio

- THRESHOLD: trace width ≤ ~60% of the pad width it enters.
- WHY: a wide trace heat-sinks the pad during soldering (uneven melt, opens) and can wick paste off-pad.
- WHERE: 21.10 (routing tips).
- MACHINE: `pad_entry_width_ratio` check: copper entering an SMD pad must be ≤0.6 × pad width (our 0.2–0.3 mm traces into ≥0.5 mm pads already comply; matters for power polygons taps — neck down before pad entry).
- APPLIES: reflowed SMD pads; THT exempt.

### 3.4 Via-in-pad

- THRESHOLD: not allowed open; requires filled + planarized + plated-over ("cap plating") with copper wrap ≥25 μm past the drilled edge; plugging material must not dimple.
- WHY: open via in a pad wicks paste/solder down the barrel (starved joint); one-sided plugging traps corrosives at the barrel-plug ring void — IPC-4761: protect vias from BOTH sides.
- WHERE: 36.6 (via protection; single-sided protection ring-void warning), 36.6.3.1–36.6.3.2, 53.11.2.5.11 (cap plating acceptance).
- MACHINE: existing practice holds: never place a via inside an SMD paste pad unless the process explicitly specifies fill+cap (cost adder); dog-bone fanout is the default. `via_in_pad` blocker check (via barrel intersecting a paste-stencil opening) — candidate for virtual DRC.
- APPLIES: all reflowed boards; exception path only for BGA fields we don't yet generate.

## 4. Board outline, routing (mechanical), slots, and panelization

### 4.1 Milled slots and internal cutouts — feasibility and geometry

- Feasibility: internal cutouts/slots are standard CNC routing operations: "routing of plated slots (instead of slot drilling)," big holes, cavities; slots can also be made on drill machines by overlapping hits (slot drilling) — overlap method for slots < 2–3× tool diameter, alternating method for longer slots. WHERE: 38.1, 29.6.3.
- THRESHOLD (slot width): minimum = router/drill tool diameter; the routing parameter example runs tools from 3.175 mm shank down to 0.6–0.7 mm diameter (below 0.7 mm the 100 kRPM spindle ceiling forces off-nominal cutting speed — i.e. 0.7 mm is the comfortable floor, 0.6 mm marginal). Cutter compensation means the slot CAN'T be narrower than the tool. WHERE: 38.6.6 (parameter example, Fig. 38.7), 38.2.1 (radius compensation).
- THRESHOLD (edge quality/tolerance): router deflection is product-specific and compensated per-product in a pre-run (38.2.1); the "good" side is the conventional-milling side — outlines are cut counterclockwise, internal cutouts CLOCKWISE so the product edge always gets the good side (38.2.1, Fig. 38.4). Copper-to-routed-edge distance is not stated numerically in this book — take from IPC-2221 (our knob stays; book confirms mechanism: routed edges expose glass fiber and can burr).
- MACHINE: sensor-isolation moat generator: `min_slot_width_mm = 1.0` (safe; 0.8 acceptable; never <0.7), slot ends get full radius = tool radius (no square-ended slots), keep existing copper-to-edge clearance knob applied to slot edges same as outline edges, and vias respect the shaped-outline edge margin (already implemented for the thermometer).
- APPLIES: any board with internal milled features (thermal/humidity isolation moats around the SHT31 is exactly this).

### 4.2 V-scoring constraints

- THRESHOLD: score angle 20–30° (also 90°); groove width — and hence the minimum distance from score line to the nearest feature — is set by angle × depth; web thickness (remaining material) sets break force; grooves run only in straight lines across the panel (jump-scoring can interrupt them; curves require routing instead).
- WHY: two rotating blades cut top and bottom simultaneously; an off-center web widens one groove and can violate feature clearance (38.8.6, Fig. 38.11).
- WHERE: 38.8, 38.8.1, 38.8.6.
- MACHINE: if PCBSmith ever emits panels: keep copper and components away from score lines by ≥ groove half-width + offset tolerance; separated-part edges grow slightly ("parts turn out to be bigger than the inner edge" — broken web exposes glass, 38.8.4) so score-line-to-copper clearance must include the web burr. Knob `vscore_clearance_mm` (assumption: 0.5 mm to copper, 1 mm to SMD pads, pending fab data). Note the I/U-shaped scored test-coupon trick (electrical open proves scoring happened, 38.8.5) as an optional panel feature.
- APPLIES: panelized production only; single-board prototypes unaffected.

### 4.3 Breakaway/tabs and subpanels

- Rationale only: small PCBs ship in subpanels with "pre-cuts with tabs or other break-away features"; combining routing (corners, complex features) with scoring (straight runs) is "very effective." No tab-width numbers given. WHERE: 38.1, 38.8.4, Fig. 38.10.
- MACHINE: no check; panelization layout is a fab decision. Record: perforated tabs near copper need the same routed-edge clearance as the outline.
- APPLIES: panel design (out of current scope).

### 4.4 Panel utilization drives cost

- THRESHOLD: fab standard panel 18×24 in; cost scales with boards-per-panel (the worked example: shaving 14 in² off a board took it from 6-up to 8-up and cut price ~25%).
- WHY: every process step is priced per panel.
- WHERE: 4.2.1.2, 16.6.3.4, Fig. 16.16.
- MACHINE: advisory only: when the outline is negotiable, prefer dimensions that tile an 18×24 in (457×610 mm) or half-panel working area efficiently. Not a check — record in the design-notes section of bundles.
- APPLIES: production cost optimization.

## 5. Holes and vias: drilling and plating limits

### 5.1 Through-hole aspect ratio vs. plating throwing power

- THRESHOLD: throwing power ≈100% at 3:1 aspect ratio (board thickness : hole dia); only ~33% at 15:1 — hole-center copper gets ⅓ of surface thickness. To get 1.0 mil in the barrel middle of a 15:1 hole you must plate 3.0 mil on the surface.
- WHY: mass-transfer limits in the barrel; knee of the hole over-plates ("dog bone").
- WHERE: 33.3.1.2, 4.4.2 (vias: "more difficult to achieve the required plating thickness … especially for thicker boards (high aspect ratio)").
- MACHINE: `drill_aspect_ratio` audit: board_thickness / min_finished_drill ≤ 8 standard (flag), ≤ 10 hard cap without special process. For 1.6 mm boards: min drill 0.2 mm ⇒ AR 8 — exactly at the flag line; our existing `min_through_hole` constraint (0.2 mm) is consistent. Thicker boards must scale min drill up.
- APPLIES: mechanically drilled PTH; thick boards (≥2.4 mm) most affected.

### 5.2 Blind/buried vias and microvias

- Mechanical blind vias: metallization capability caps the depth:diameter ratio; a minimum dielectric distance to the next innerlayer under the target layer is mandatory for depth tolerance. WHERE: 29.6.1.1.
- Laser vs mechanical: vias deeper than 0.016 in (0.41 mm) should be mechanically drilled, not lasered. WHERE: 29.2 (aspect ratio determination; the text's "(6.3 mm)" parenthetical is an obvious unit misprint for 0.4 mm).
- Blind-via fill plating: reliable to 1:1 aspect ratio, up to 1.2:1 possible. WHERE: 33.3.3.6.2.
- Microvia definition: IPC ≤150 μm dia; L1–L3 skip vias need ~250 μm and laser only. WHERE: 25.1, 25.4.1.
- Reliability (design-relevant): **staggered microvias are two orders of magnitude more robust than stacked**; copper-filled stacked microvias show the greatest corner-crack tendency; the most robust single interconnect is an unfilled surface microvia. WHERE: 61.5 (and summary list, 61.7).
- MACHINE: HDI is out of current scope; when it lands: `microvia_aspect ≤ 1:1` (warn to 1.2:1), prefer staggered over stacked in the via planner, min dielectric-below-target-layer knob.
- APPLIES: HDI/build-up boards only.

### 5.3 Drilling cost/fragility gradient

- THRESHOLD: smaller drills ⇒ shorter stack heights (cost/hole rises) and fragile bits (breakage damages the board); retract rates must drop below 0.0135 in dia. Minimum hole size and total hole count are both standard price-matrix lines.
- WHY: bit stiffness and debris evacuation.
- WHERE: 4.3 (drilling cost per hole × stack height), 4.4.2, 28.4.3.2.
- MACHINE: keep vias at the largest diameter routing allows (already our default 0.6/0.3); `via_count` in board stats; don't gratuitously mix many drill sizes (each size is a tool change — advisory).
- APPLIES: all drilled boards.

### 5.4 Annular ring / breakout

- THRESHOLD: minimum annular ring is user-defined (procurement doc), but breakout (zero ring) is NEVER acceptable "in the area where the circuit enters the pad (conductor-to-land junction)."
- WHY: junction breakout reduces current-carrying capacity at the neck; ring anchors the land.
- WHERE: 53.11.1.3.3, 53.11.2.5.1; 4.4.2 trade-off (bigger hole = easier plating but smaller ring margin, Fig. 4.18).
- MACHINE: our pad geometry comes from probed footprints so ring is fixed by the library; the design-relevant residue: trace entry direction into a THT pad should not aim at the thinnest ring sector when pads are ovalized. No new check now; record for a future `annular_entry` refinement.
- APPLIES: PTH lands.

## 6. Electrical/thermal design parameters (constraining numbers only)

### 6.1 Trace current capacity — use IPC-2152, and the internal-layer myth

- THRESHOLD: the pre-2152 internal-conductor chart was fabricated as ½ the external current — not measured. Measurement shows "internal conductors operate at a similar temperature, but slightly cooler than external conductors."
- WHY: dielectric conducts heat better than air; planes near a trace dramatically cut its temperature rise; thin cores (<1/32 in) REDUCE capacity.
- WHERE: 22.1–22.3.
- MACHINE: `calculators/electronics.py` trace-width sizing must cite IPC-2152 baselines, not IPC-2221 charts; do NOT derate internal layers ×2; DO flag traces on thin flex-class cores. (Cross-check against the ipc-2221b distillation when written — record as a books-contradiction if that doc encodes the old chart.)
- APPLIES: current-carrying trace sizing everywhere.

### 6.2 Crosstalk spacing floor

- THRESHOLD: 4 mil/4 mil width/space autorouting yields 20–60 mV crosstalk; NEXT/FEXT curves flatten at ~7 mil spacing — >6 mil separation for noise-sensitive victims.
- WHERE: 20.4 (Fig. 20.19).
- MACHINE: our 0.2 mm (7.9 mil) default clearance already sits at the knee — record as the evidence line for the default; high-speed nets keep ≥3×W spacing (existing craft rule).
- APPLIES: digital signals with fast edges; not relevant to slow analog.

### 6.3 Stackup rules (multilayer, future)

- Even layer count, symmetric about center (warp); power/ground plane pair 3–10 mil apart at stack center for interplane capacitance; never more than two adjacent signal layers (and only with planes both sides); no signal-crossing of plane splits; pour unused areas and tie to a plane (etch balance + capacitance). WHERE: 21.9, 21.8, 20.3.
- MACHINE: stackup generator invariants when PCBSmith goes >2 layers.
- APPLIES: 4+ layer boards.

### 6.4 CAF (conductive anodic filament) spacing

- THRESHOLD: no single number; failure time scales as L⁴/V² (spacing to the 4th power); susceptibility ordering hole-to-hole > hole-to-line > line-to-line; buried layers fail first.
- WHY: copper salts wick along glass-fiber/resin interfaces under DC bias and humidity.
- WHERE: 59.4 (Ready/Turbini, Eq. 59.14), 59.5.
- MACHINE: for high-DC-bias nets (>48 V), add margin to hole-to-hole spacing beyond DRC electrical clearance; candidate knob `caf_hole_spacing_high_v` (assumption pending IPC-2221 cross-check).
- APPLIES: mains/high-voltage boards in humid service — ties into rulebook §10 isolation machinery.

## 7. Silkscreen / legend and finishing (confirmations)

- Legend and reference text must not fall on pads or vias — "it will be deleted during the fabrication processes and so will be useless." WHERE: 21.11. Confirms our silk checks; adds the rationale (mask-clipping, not just DRC cosmetics).
- Text aligned readable with the board's top edge in operation. WHERE: 21.6. Advisory; matches `part_reference_at` craft.
- Fiducials: global + fine-pitch local fiducials are analyzed at assembly tooling; multiple light sources needed to see them on various finishes. WHERE: 27.4.2.2, 38.8.2. MACHINE: boards for automated assembly should carry ≥2 (prefer 3) global fiducials — candidate `fiducial_presence` advisory for automation-first boards.
- Surface finish: cost is roughly flat across common finishes except gold (4.2.1.2, Figs. 4.13–4.14); no design-geometry constraint extracted. HASL's poor planarity for fine pitch is implied but not quantified here — leave to IPC-7351 notes.

## 8. Cost-model heuristics worth encoding as advisories

- More layers vs bigger board: bigger board usually wins if size is free (4.4.3).
- Double-sided assembly vs bigger board: double-sided usually wins — second print/place/reflow pass is cheap (4.4.3) — provided §2.1 side-assignment rules hold.
- Nonstandard anything (hole plugging, beveling, plated slots, tight thickness/hole/impedance tolerance) = price adder (4.3). Plated slots specifically are a special process — the sensor moat in §4.1 should be UNPLATED unless a shielding requirement forces plating.
- Complexity Index (area, hole count, min trace, layers, min tolerance → first-pass yield regression): 16.6.2, Eq. 16.11 — the quantitative frame behind all of the above; candidate future `complexity_index` metric in board stats.

---

## Top 10 most design-relevant rules (ranked)

1. **Two-pass reflow side assignment** — heavy/large parts on the last-reflowed side; first-pass-side parts above the surface-tension mass limit need adhesive; BGAs never on pass-1 side (43.3.2). → FLIPPED_REFS gate for every dual-side board.
2. **Milled slot floor** — internal slots are routine; width ≥ router diameter, comfortable floor 0.7 mm (use ≥1.0 mm), rounded ends, cut clockwise for good product-side edge (38.2.1, 38.6.6). → unblocks the sensor isolation moat with `min_slot_width_mm`.
3. **Acid-trap question settled** — under-etch in tight inside corners is real physics (37.7.2.2) but modern spray etch neutralizes it at our geometry; the surviving rule is "no acute trace-to-pad entry" (21.10) — exactly our `trace_corner_angle` check. No new corner bans.
4. **Fine-line floor = resist + foil thickness** (2.6 mil on 1 oz; 37.7.4.2) and thick copper scales it up — the mechanism behind every min-trace/gap capability number.
5. **Through-hole aspect ratio ≤ ~8:1** (throwing power 100% at 3:1 → 33% at 15:1; 33.3.1.2) → `drill_aspect_ratio` audit keyed to board thickness.
6. **Via-in-pad forbidden unless filled+capped from both sides** (IPC-4761 via 36.6; wrap ≥25 μm, 53.11.2.5.11) → `via_in_pad` blocker.
7. **Trace ≤60% of pad width at SMD pad entry** (21.10) → `pad_entry_width_ratio` check; neck polygons before pads.
8. **Solder-mask dam ≥0.1 mm between openings or merge them** (2.5–3.0 mil typical capability, 36.4.4.2) → mask-sliver audit.
9. **IPC-2152 supersedes the internal-trace ×½ derating myth** — internal traces run slightly cooler; planes near traces cut temperature rise (22.2–22.3) → calculator evidence line.
10. **Breakout never at the conductor-to-land junction** (53.11.2.5.1) and reflow edge keep-out for pin-chain conveyors (49.3.1.2.1) — paired land/outline constraints for assembly-ready boards.

## Coverage log

Deep-read: ch 4 (DFM), 16 (planning/complexity), 21 (design basics), 36 (solder mask), 37 (etching §37.6–37.8), 38 (routing/V-scoring, full), 43 (assembly processes §43.2–43.3), 49 (soldering techniques §49.3); targeted extracts: ch 17, 20, 22, 25, 27, 28, 29, 33, 53, 59, 61. Skimmed/skipped as non-design: ch 1–3, 5–15 (supply chain, base materials chemistry), 18–19, 23–24, 26, 30–32, 34–35, 39–42 (bare-board test), 44–48, 50–52, 54–58 (acceptance/inspection detail), 60, 62–71 (reliability physics, flex). Extraction issues: EPUB text drops all figures/tables (thresholds living only in figures — e.g. complexity-matrix points, routing parameter table — are described but not numeric here); one unit misprint noted at 29.2 ("0.016 in (6.3 mm)"); no numeric copper-to-routed-edge or tab-width values anywhere in the book — defer to IPC-2221B.
