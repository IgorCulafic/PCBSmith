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
layout; spacing; routed tabs; mouse bites; rectangular-only V-cuts; top/bottom
or left/right rails and full frames; fiducials; tooling holes; impedance
coupons; and mandatory panel DRC. Irregular/cutout V-cuts fail before tool
invocation. The adapter writes and retains both requested and KiKit-resolved
configuration.

Both a rectangular V-cut panel and an irregular mouse-bite panel were generated.
They remain rejected proof candidates: KiCad panel DRC reported 19 and 231
violations respectively. The rectangular failures include NPTH/courtyard,
copper-edge, solder-mask-bridge, and invalid-outline findings. The irregular
panel is dominated by 205 mouse-bite hole-clearance findings, plus
NPTH/courtyard, copper-edge, and solder-mask-bridge findings. The Phase 18
roadmap item remains open until both configurations are corrected and the exact
saved panels pass KiCad DRC and visual inspection.

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
