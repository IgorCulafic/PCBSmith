# Front-End Contract

Date: 2026-07-06 (hardening plan 4.8)

A UI can be built against this document without reading source. The
backend is complete for a minimal front end: every fact a UI needs is a
file in the revision directory, and every user action maps to a CLI
command. Nothing in the backend needs to change first.

## Revision directory layout

One directory per revision (`outputs/<slug>-rNNN` by convention, but any
path works). Produced by a `design-*-authority` command:

```
<rev-dir>/
  review-bundle-v2.json        # THE status document (schema below)
  revision-plan.json           # written by `revision-plan`
  human-review.json            # written by `review-comment` (optional)
  <Name>.kicad_pro / .kicad_sch / .kicad_pcb
  PCBSmith.kicad_sym, sym-lib-table
  <Name>.svg                   # schematic vector (viewable)
  <Name>-top.png / -bottom.png / -perspective.png   # 3D renders
  <Name>-review.png            # 2D net-level review plot
  <Name>-assembly.png          # assembly diagram (refs + value table)
  fab/<Name>-fab.zip           # written by `fab-package` (optional)
  .pcbsmith/kicad/             # machine reports: drc.json, erc logs,
                               # netlist XML, simulation logs
```

## The bundle (`review-bundle-v2.json`)

Top-level keys: `schema` (id `pcbsmith-circuit-review-bundle-v2`),
`status`, `intent`, `evidence`, `kicad`, `ngspice`, `reconciliation`,
`board`, `design_review`, `revisions`, `artifacts`.

- Every section carries `status` in the shared vocabulary:
  `passed | warning | failed | unavailable | not_run | needs_human_review`.
  Terminal-clean is `needs_human_review` (by policy a generated board is
  never self-approved).
- `artifacts` maps stable keys to file paths: `kicad_schematic_svg`,
  `board_render_top|bottom|perspective`, `board_review_plot`,
  `board_assembly_plot`, `board_file`, `drc_report`, plus per-topology
  extras. Keys are additive; a UI must tolerate unknown keys.
- `design_review.findings[]` are structured: `rule` (id into
  `docs/pcb-design-rules.md`), `severity` (`blocker|warning|style`),
  `scope` (`component|net|region|global`), `where`, `evidence`,
  `suggested_action`, `source` (`check|model_review|human`).

## User actions -> CLI

| UI action                | Command |
| ------------------------ | ------- |
| Create/regenerate design | `pcbsmith design-<topology>-authority <dir> --request ... --name ... [--evidence-manifest ...] [--overwrite]` |
| Add a review comment     | `pcbsmith review-comment <dir> --where <ref> --comment ... --severity ... --scope ...` |
| Ask "what next"          | `pcbsmith revision-plan <dir>` (decision: clean / patch / redo / escalate) |
| Export for fabrication   | `pcbsmith fab-package <dir>` |

Comments become `source: human` findings; the revision planner merges
them, so a UI comment flow is complete with those two commands.

## Click-to-comment mapping

`<Name>-review.png` and `<Name>-assembly.png` are drawn at
`SCALE_PX_PER_MM = 28` with a `IMAGE_MARGIN_PX = 60` margin
(`kicad/preview.py`):

```
mm = (px - 60) / 28        # both axes, board-local coordinates
```

A click at pixel (px, py) therefore addresses board position (mm), which
matches every `pos`/`x_mm` in the machine reports and virtual-DRC
findings. Hit-testing against parts: `review-bundle` does not embed
placements; a UI needing exact hit boxes should read positions from the
fab `positions.csv` (refs with x/y/rotation/side, mm) inside the fab
package, or shell out to a future `layout-json` command (not yet needed
for v1).

## Conventions a UI may rely on

- One revision directory is immutable once reviewed; regeneration into
  the same directory requires `--overwrite` (the UI should default to a
  new `rNNN` directory).
- `drc.json` is KiCad's native DRC JSON; positions are in mm within the
  sheet frame, offset `BOARD_SHEET_ORIGIN_MM = 20` from board-local.
- All CLI commands exit 0 on success and print the bundle path/status on
  the last lines; errors raise with a message on stderr.
