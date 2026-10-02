# B2 — vector-first preparation — 2026-09-07

Status: implemented for the supported generic rectangular, front-side placement adapter. B4 end-to-end acceptance remains open.

## Changes and evidence

- Native project intent now optionally declares signal, return or access corridors by component references and width. The existing concept geometry supplies the editable SVG, dimensioned preview, measured pad markers, orientations and functional role key; it also supplies the native layout input.
- Predesign approval requires floorplan.json, SVG, PNG and an explicit review targeting the exact manifest hash. Inspection, presentation reference and corridor rationale are mandatory. Existing readiness retention owns their hashes and copies.
- New generic production generation rejects missing/stale vector review, alternate coordinate inputs and changed native anchors, angles, side, reference coverage or outline before accepting a producer receipt.
- Text positions are excluded from the geometry identity. A changed component invalidates it; file serialization alone does not.
- Other generator adapters fail closed at this new generation gate pending explicit vector adapters. Frozen historical readiness replay is preserved.

Implementation: src/pcbsmith/kicad/floorplan.py, predesign_preparation.py, native_project.py and production_generators.py. Tests: tests/unit/kicad/test_floorplan.py and existing readiness/generator/job suites.

## Verification

114 tests passed in outputs/bounded-workflow-b2-2026-09-07/tests-final.xml. The workflow audit passed all 196 classified callers; Ruff passed the B2 touched owners. Synthetic inner-contract tests explicitly isolate the outer floorplan gate; dedicated floorplan tests exercise its negative paths.

The retained CornerStep concept generated a real preview and all 32 saved native poses plus the 80 x 65 mm outline matched. The accepted board was read only. Its SHA-256 remains 54652c98f30a697520b8b0c5a0a797264088bf2a1e81e3bfac53bf0764962786.

Inspected both preview revisions. The first crowded the last role against the footer; revision 02 fixes it and is retained alongside the first:
SVG (local reference `../../outputs/bounded-workflow-b2-2026-09-07/cornerstep-regression-02/floorplan.svg`, not included in this public snapshot), PNG (local reference `../../outputs/bounded-workflow-b2-2026-09-07/cornerstep-regression-02/floorplan.png`, not included in this public snapshot).
Four corner LEDs, dimensions, pad-one marks, orientations and role key are visible. This regression intentionally declares no new routing corridors and grants no retrospective engineering approval.

## Limits and next phase

Review assertions record accountable claims; they cannot authenticate human/assistant inspection against arbitrary local file editing. Static caller classification is not an OS sandbox. SVGs are planning evidence, not electrical proof. The native comparison currently covers front-side rectangular layouts; curved outlines and dedicated mechanical-item adapters need separately scoped support. Existing edit/release checks remain responsible for local revision evidence; this is not a universal replacement of those checks.

B3 is next: consistent exact shared resolution, source-intake/install integration and offline reuse tests. B4 must still prove a fresh bounded run and local revision with actual native and engineering evidence.
