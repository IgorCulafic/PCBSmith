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

Corrected live runs produced one self-contained HTML artifact for each proof
board:

- regular 3x3 board: 306,571 bytes,
  SHA-256 `a9eb8ac82cfb5502d40fd017cc4b99b2f935f4a69fb2186a8c7d7758d147fbfe`;
- irregular Retro-Pad board: 260,951 bytes,
  SHA-256 `7fd8986af101b4c0e4301bb7ff4738a8a3d07385957ffae057c3d09fdab8a21f`.

Each live KiCad neutral export also produced 8 ordinary Gerbers, 2 paste
Gerbers, Excellon drill and Gerber drill map, IPC-D-356, front/back assembly
drawings, fabrication drawing, BOM, placement CSV, stack-up notes, and README.
Formal package acceptance remains open because current-path and unsupported
DFM/DFT authorities have not been supplied or approved.
