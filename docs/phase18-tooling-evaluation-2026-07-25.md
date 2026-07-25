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
- local status on 2026-07-25: not installed.

The typed panel profile covers regular, irregular, and cutout sources; grid
layout; spacing; routed tabs; mouse bites; rectangular-only V-cuts; top/bottom
or left/right rails and full frames; fiducials; tooling holes; impedance
coupons; and mandatory panel DRC. Irregular/cutout V-cuts fail before tool
invocation. The adapter writes and retains both requested and KiKit-resolved
configuration.

This is an evaluated, pinned adapter, not a live panel proof. The Phase 18
roadmap item remains open until the pinned runtime is installed and both a
regular and an irregular/cutout panel pass saved-panel KiCad DRC and visual
inspection.

## InteractiveHtmlBom

- pinned version: `2.11.2`;
- upstream release:
  <https://github.com/openscopeproject/InteractiveHtmlBom/releases/tag/v2.11.2>;
- pinned CLI source:
  <https://github.com/openscopeproject/InteractiveHtmlBom/blob/v2.11.2/InteractiveHtmlBom/core/config.py>;
- local status on 2026-07-25: not installed.

The adapter declares front/back inclusion, bottom-side rotation convention,
DNP references, variant whitelist, BOM grouping fields, and optional
track/net rendering. It requires exactly one newly generated self-contained
HTML output. The neutral package checks for recognizable HTML and hashes the
exact file.

This item remains open until the pinned runtime is installed and outputs from
both proof boards are compared against the BOM and placement identities.
