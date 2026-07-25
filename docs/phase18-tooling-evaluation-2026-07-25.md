# Phase 18 manufacturing-tool evaluation — 2026-07-25

## Decision

PCBSmith keeps KiCad outputs and its neutral package manifest as the canonical
authority. KiKit and InteractiveHtmlBom are optional, version-pinned producers.
Their files cannot promote a package unless the exact executable version is
retained and all output is independently hashed and checked.

## KiKit

- pinned version: `1.8.0`;
- upstream release: <https://github.com/yaqwsx/KiKit/releases/tag/v1.8.0>;
- panelization CLI:
  <https://yaqwsx.github.io/KiKit/latest/panelization/cli/>;
- local status on 2026-07-25: pinned package installed in the ignored,
  project-local `.pcbsmith/runtime/phase18` runtime under KiCad Python 3.11.

The typed panel profile covers regular, irregular, and cutout sources; grid
layout; automatic or exact annotated tabs; mouse bites; rectangular-only
V-cuts; top/bottom or left/right rails and full frames; explicit non-overlapping
fiducial/tooling geometry; coupon identity declarations; and mandatory panel
DRC. Irregular/cutout V-cuts fail before tool invocation. Actual impedance
coupon geometry is not yet produced and remains a separate open item.

The first rectangular V-cut and irregular mouse-bite configurations remain
retained failure candidates. Their failures exposed three real defects:

- default zero offsets placed tooling holes and fiducials on top of each other
  and on the panel edge;
- automatic tab spacing placed breakaway holes through component courtyards,
  routing, and copper; and
- a board file without its matching `.kicad_pro` silently changed the DRC
  rules used for the generated panel.

The production adapter now requires the matching KiCad project rule authority,
hashes source and output project/custom-rule files, emits exact feature
geometry, supports board-specific tab annotation identities, runs panel DRC,
and atomically retains a fail-closed proof manifest. No DRC exclusions were
added.

Three corrected live proofs pass KiCad 10.0.3 DRC with zero violations and zero
unconnected items:

- regular Retro-Pad 3x3, two-board mouse-bite/full-frame panel;
- irregular Lucky Clover, two-board mouse-bite/full-frame panel; and
- regular Retro-Pad 3x3, two-board V-cut/top-bottom-rail panel.

Top and bottom 1920×1080 renders and front/back SVGs were inspected. Board
outlines, tabs/cuts, rails, tooling holes, fiducials, copper, and component
orientation are coherent in those views. Exact hashes and the failure
progression are recorded in
`docs/phase18-panelization-proof-2026-07-25.md`.

## InteractiveHtmlBom

- pinned version: `2.11.2`;
- upstream release:
  <https://github.com/openscopeproject/InteractiveHtmlBom/releases/tag/v2.11.2>;
- pinned CLI source:
  <https://github.com/openscopeproject/InteractiveHtmlBom/blob/v2.11.2/InteractiveHtmlBom/core/config.py>;
- local status on 2026-07-25: pinned package installed in the ignored,
  project-local `.pcbsmith/runtime/phase18` runtime under KiCad Python 3.11.

The adapter declares front/back inclusion, bottom-side rotation convention,
DNP references, variant whitelist, BOM grouping fields, and optional
track/net rendering. It requires exactly one newly generated self-contained
HTML output. The neutral package checks for recognizable HTML and hashes the
exact file.

The first launcher incorrectly set only `INTERACTIVE_HTML_BOM_NO_DISPLAY`.
Because the package `__init__` also requires
`INTERACTIVE_HTML_BOM_CLI_MODE`, KiCad attempted to register an action plugin
without a running application and raised a wxWidgets `PgmOrNull()` assertion.
That invocation was stopped. The production launcher now always sets both
variables; a regression test verifies them.

Corrected live runs produced one self-contained HTML artifact for each final
schema-v2 proof package:

- regular 3x3 board: 304,455 bytes,
  SHA-256 `05644d1c7e656319818d60af75c9c797832a5cc36717001d4c25645dbb6cccc4`;
- irregular Retro-Pad board: 259,215 bytes,
  SHA-256 `a48ca3c5a646e58724a07841f04d66ec4291a7beaadbf4347ff95e119d9c780a`.

Each live KiCad neutral export also produced 8 ordinary Gerbers, 2 paste
Gerbers, Excellon drill and PDF drill map, IPC-D-356, front/back assembly
drawings, a prototype drill/fabrication sheet, drill report, BOM, placement
CSV, stack-up notes, and README. The final schema-v2 package also embeds its
exact fabrication profile, manufacturing identity registry, current-path
record, and DFM/DFT report. Independent ZIP/hash/model and visual checks are
recorded in `docs/phase18-neutral-package-proof-2026-07-25.md`. Formal package
acceptance remains blocked because current-path and unsupported DFM/DFT
authorities have not been supplied or approved.
