# Claude takeover review — 2026-11-13

Written by Claude (Opus 5.5) on taking the project back over from the
GPT/Codex sessions. This file records what was actually found and what is
recommended. It does not replace `docs/current-state.md`, which remains the
scope authority. All recommendations below await the user's approval.

## What was reviewed

| Source | Coverage |
| --- | --- |
| Codex (GPT) session logs, `~/.codex/sessions` (zstd) | 968 rollouts scanned; 13 user-driven PCBSmith threads, 2026-07-02 → 2026-10-21; all 419 user messages plus GPT's final turn reports read. Automatic "Guardian review" sub-threads were skipped. |
| Claude logs | `Old Chat Logs/` (2 transcripts, July) plus this project's Claude store; GPT already reconciled these in `docs/project-catchup-2026-07-12.md`. |
| Repository | `current-state.md`, `handoff-prompt.md`, `development.md`, `AGENTS.md`, git state, module and test inventory, the October 21 schematic work and its outputs. |
| Reference material | `Books/` (≈50 sources incl. IPC, IEC, Ott, Bogatin, Montrose, Johnson, USB specs); Reddit E30 antenna-driver images in `Downloads/` (7 files, still present). |
| Gates | `tools/verify.py --profile standard`: lock, ruff, workflow audit, strict mypy and import contracts **pass**; full pytest result is recorded at the end of this file. |

Not reachable: claude.ai/ChatGPT web chats (not stored locally), and the
external backups `D:/AI/PCB designer.zip` (Sep 4) and
`claude-chats-backup-2026-07-10.zip`, which were inventoried but not opened.

## Timeline in one paragraph

July: Claude built the deterministic core and thermometer (R005). GPT
re-onboarded (Jul 12), distilled the books, ran bunny/Dejan/Retro-Pad/
protocol-analyzer/AeroSense tests and wrote Papers 1–2. On Jul 26 the user
redirected routing to external autorouters, and Freerouting became the
default on Sep 12. August: 40-board corpus, W0–W10, iterative-fixing IF0–IF6,
Montenegro. September: a new GPT model ("Astra") produced a large
governance layer: bounded jobs, timers, receipts, publication transactions
and mandatory handover. A very slow simple board (Sep 11–12) led to a
workflow reset, followed by many small delivered boards. Oct 1–4: **physical
laser-etched boards built by the user work**, including the trace stress
test. Oct 10: four-layer plane machinery and LogicBridge placement. Oct 21:
connected functional schematics. GPT hit its usage limit mid-turn.

## Findings, most important first

### 1. Two months of work is not committed (confirmed, high risk)

- Last local commit: `fbb3c52`, **2026-08-21**. The working tree has 165
  modified, 774 untracked and 1 deleted path. `tools/verify.py`, the
  verification authority itself, is untracked.
- `origin/main` was updated on Oct 2 via a separate worktree sync
  (`cee4447`, `1a962ca`). Everything after Oct 2 exists **only on this
  disk**: the two-sided boards, power boards, four-layer planes, LogicBridge
  and the schematic renderer. The user has reported PC crashes and a power
  outage during this project.
- Local `main` (Jul 27), `origin/main` (Oct 2) and the working branch
  (Aug 21 + dirty) have diverged. `.git` is 4.8 GB.
- On Jul 24 the user asked for commits with every change. That instruction
  was not followed after Aug 21.

**Recommendation:** commit the current tree in a few logical commits on a
fresh branch, push, then reconcile with `origin/main`. Decide what generated
output belongs in git; large `outputs/`/`experiments/` trees should probably
move to LFS or release archives. Needs the user's go-ahead.

**Resolved 2026-11-13 (user-approved):**

- **Cause:** a stale `.git/index.lock` dated Sep 5 had blocked every commit
  since then. It was removed, and `core.longpaths` was enabled.
- **Local checkpoint:** all work was committed on the local-only branch
  `codex/controlled-evaluation-v2` in six commits. Those include private
  papers, experiments and deliverables, so that branch must never be pushed
  to the public repository.
- **Public sync:** a filtered public sync was built on `origin/main` as branch
  `claude/sync-2026-11-13`. It follows the Oct 2 curation:
  - Excluded: no papers, experiments, deliverables, paper tools, confidential
    docs, or files the Oct 2 sync deliberately left out.
  - Kept as published: the public `current-state.md` and follow-up register.
  - Preserved: the public-only portability test fixtures.

### 2. The October 21 schematic work is further along than the docs say

`current-state.md` still says "implementation pending". In fact GPT
implemented a first slice before its quota ran out and never reported it:

- `src/pcbsmith/schematic_presentation.py` (326 lines),
  `tests/unit/test_schematic_presentation.py`, a fixture, and
  `docs/implementation/schematic-presentation-2026-10-21.md`.
- A real KiCad run shows titled blocks, notes, real local wires, junctions
  and labels between blocks. ERC 0, netlist identical to the stub version,
  parity 0. See `outputs/schematic-presentation-2026-10-21/native-final/…/preview.png`.

Gaps compared with the Reddit reference (`e30_antenna_timer_2.0`):

| Reference does | Current slice |
| --- | --- |
| Blocks sized to their content and packed on the sheet | Hand-declared `bounds_mm`; demo has large empty regions |
| Symbols arranged by signal flow automatically by the author | Every symbol position **and every wire waypoint** is hand-authored in the spec. That is impractical for 30–60 part boards and is exactly the work an AI does inconsistently |
| Equations, truth tables, test points, power symbols, filled title block (rev/date) | Plain wrapped text; PWR_FLAG symbols visible; empty title block |
| One schematic everywhere | Only the fixture uses it; no production board generator emits it |

Duplication: this is now the **fourth** schematic emitter. The others are
Claude's July `kicad/reader_schematic.py` (conventional drawing plus a
wire-connectivity validator, used by servo555/flyback/thermometer),
`kicad/circuit_schematic.py` (fixed grid, stubs) and the native stub emitter.
The new module does not reuse `reader_schematic.py`.

**Recommendation (next schematic slice):**
1. Derive blocks automatically from existing roles/topology (power input,
   protection, regulation, MCU and its decoupling, connectors, indicators…),
   with the spec able to override.
2. Add a deterministic in-block placer: signal flow left→right, positive rail
   above, return below, decoupling caps beside their IC pins.
3. Add an orthogonal grid router *for schematic wires* within a block. This
   is much easier than PCB routing, so wires can fall back to labels when
   crowded rather than being hand-specified.
4. Pack the blocks onto the sheet. Use power symbols instead of visible
   flags. Fill the title block. Generate notes from calculator outputs
   (e.g. the 555 timing equation from `calculators/`), not free text.
5. Merge `reader_schematic.py` and `schematic_presentation.py` into one owner,
   then wire it into the normal board path so every new board gets it.

### 3. Required steps keep being "forgotten" because they are instructions, not code

The user had to restate the same thing many times:

- Use the autorouter: Jul 28, Aug 1, Sep 12.
- Make the vector floorplan: Sep 6, Sep 22.
- Look at the renders: Jul 18, Jul 21.
- Don't rebuild the whole board for small changes: Jul 26, Aug 20, Sep 5.

Each fix was a longer `AGENTS.md`, which is now 14.6 KB per injection (`current-state.md` is 41 KB),
plus another doc. CLAUDE.md's Law 1 ("a rule that is not a check is a wish")
applies to the *workflow itself*. **Recommendation:** one
`pcbsmith build <brief>` entry point whose stages run in a fixed order:
brief check → parts → vector floorplan → placement → Freerouting → checks →
renders → package. The stages should be impossible to skip, so the agent
fills in decisions rather than remembering procedure.

### 4. The governance layer now costs more than it protects (opinion, backed by evidence)

Docs total ≈457 k words across 297 Markdown files. `src` has 141
top-level modules, 55 of them `*_ir.py`, plus a 213-caller audit.
Simple-board handovers require "37 visual decisions" and "17-role
mandatory handover". `current-state.md` is a wall of receipts that a human
cannot scan.

Concrete harm:

- LogicBridge stopped twice on Oct 10 to ask permission. `AGENTS.md:34` makes
  any post-diagnostic continuation need "a new explicit user decision", even
  though the user said "don't ask for approval" on Sep 11, Sep 28, Oct 4 and
  Oct 10.
- The Sep 11 board took more than 2 h, then 9 h.

**Recommendations:**
- Keep the real safety properties: KiCad ERC/DRC authority, never
  self-approving, honest physical holds, preserving history.
- Drop the approval latch for routine continuation inside a user-requested
  board job.
- Rewrite `current-state.md` as one screen: what works, what's next, holds.
  Move receipts to `implementation/`.
- Audit the `_ir` modules for ones that have no production caller.

### 5. Placement intelligence is still the weak link (confirmed by user feedback)

User feedback examples:

- Aug 16: C1/C2 were badly placed.
- Montenegro used oversized LEDs and left out the sensor.
- The USB-C connector was flipped on Jul 24.
- Pin headers stuck out of the board on Jul 21.

Routing quality improved once Freerouting took over. Placement is still the AI
hand-writing coordinates and then checking them afterwards. **Recommendation:**
turn the existing role knowledge (decoupling-to-pin, connector-on-edge with
mating direction, crystal-near-MCU, keep-outs) into a constructive placer
that proposes placements, rather than only into post-hoc checks.

### 6. Board-specific code in the library (confirmed)

`src/pcbsmith/kicad/` contains about 40 `export_*`/`*_board.py` modules for
individual boards (thermometer, Montenegro, AeroSense, protocol analyzer…).
`generation/bldc_esc_engineering.py` is 3.2 k lines and `cli.py` is 4.8 k
lines. Newer boards correctly use data (`design-spec.json`) through
`native_project`. Old per-board modules should be frozen as fixtures, not
grown.

## What is genuinely strong

- **Physical proof:** the user's laser-etched single- and two-sided boards
  work. That includes the 0.15–1.0 mm TraceLimits stress coupon.
- **Autorouting:** Freerouting integration with KiCad read-back, iBOM,
  isolation/pad-mask CAM and editable vector floorplans form a usable
  home-fab pipeline.
- **Static gates:** clean ruff/strict-mypy/import contracts across about
  203 k source lines and 120 k test lines.
- **Reference base:** the distilled book knowledge in `docs/reference/` is a
  real asset.

## Suggested order

1. Secure the work (commit/push plan, user approval).
2. Fix stale status: mark the schematic slice as implemented-in-scope.
3. Schematic slice 2: automatic blocks, placement, wires and notes, merged
   with `reader_schematic`, wired into the normal path. Prove it on an
   existing delivered board (e.g. DualLaser3 or PowerSwitch) without changing
   its PCB.
4. Single `build` entry point; remove the continuation approval latch.
5. Then resume LogicBridge routing and TriggerLeaf as already queued.

## Verification run (this review)

`tools/verify.py --profile standard`, run 2026-11-13 on the uncommitted tree
(output retained in the session scratchpad only):

- lock, ruff, board-workflow audit, strict mypy, import contracts: **pass**.
- pytest-full: **4922 tests, 4869 passed, 3 failed, 50 skipped** (879 s).
  **Gate status: FAILED.**
- The 3 failures are all
  `tests/unit/kicad/test_final_fill_adapter.py::test_snapshot_rejects_region_from_another_authority`
  (layer / net_name / source_sha parameters). Cause:
  `KiCadFilledCopperRegion.build()` (`src/pcbsmith/kicad/final_fill_adapter.py:111`)
  fingerprints a `model_construct` copy of raw input. Point dicts that were
  never validated into `ExactFillPoint` trigger a Pydantic serializer warning,
  and the test warning policy turns it into an error before the expected
  `ValueError`.
- This is a small real defect in the October four-layer fill code: it hashes
  unvalidated input. The fix is to validate before fingerprinting. That makes
  the September 22 "all gates pass" statement stale for the current tree.
