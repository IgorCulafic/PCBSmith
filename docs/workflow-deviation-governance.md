# PCBSmith workflow deviation governance

**Status:** normative design policy; enforcement integration is open
**Date:** 2026-07-22

## Purpose

PCBSmith must support board-specific evidence without allowing each generator or
model to silently reinterpret the shared workflow. A system requirement is not
a suggestion. Extra evidence is welcome; missing or substituted required
evidence must remain visible and must not be called complete.

The governing distinction is:

> Addition is extensibility. Undeclared replacement or omission is deviation.

The BLDC ESC R002 custom `review-images/` package is the motivating failure. Its
heatsink-installed and heatsink-hidden views were useful additions, but the
custom generator bypassed the standard `review/` hierarchy, manifest, report,
back/combined routing views, complete camera set, and comparison evidence. The
addition was valid; treating it as a replacement was not.

## Stable requirement identities

Requirements are identified by semantic IDs, not filenames or directory
accidents. For example:

- `visual.overview.front-design`
- `visual.routing.back-copper`
- `visual.3d.populated.rear-low`
- `visual.review.manifest`
- `verification.kicad.drc`
- `thermal.loss-ledger.declared-operating-points`

A path is a versioned serialization of an identity. Renaming a file does not
satisfy a different requirement. A new renderer may change implementation, but
it must emit the same identities and prove equivalent scope.

Every authoritative output package declares:

- base workflow/profile ID and version;
- board and source-authority hashes;
- applicable required and conditional requirement IDs;
- artifact/result satisfying each ID;
- state: `generated`, `inspected`, `accepted`, `attention_required`, `waived`,
  `missing`, or `not_applicable`;
- additions that satisfy no baseline requirement;
- substitutions and waivers with approval evidence.

## Deviation levels

| Level | Meaning | Default disposition |
|---|---|---|
| D0 | Additive evidence: extra image, detail crop, diagnostic, simulation, or report | Automatically allowed; must be labelled supplemental |
| D1 | Parameter refinement inside the profile contract: higher resolution, more tiles, tighter tolerance, additional operating point | Allowed when recorded in the manifest and no baseline coverage is weakened |
| D2 | Equivalent substitution: a different artifact or tool claims the same requirement identity | Conditional; requires machine-checkable coverage and reviewer acceptance |
| D3 | Omission or reduced coverage of an applicable requirement | Fail-closed unless an explicit scoped waiver is approved |
| D4 | Authority or safety-boundary change: weaker standard, changed applicability, suppressed finding, or unsupported claim of signoff | Prohibited in an ordinary generator; requires a new workflow version and human engineering decision |

## What counts as equivalent

A D2 substitution must preserve every material property of the original
requirement. Depending on the artifact, that includes:

- board/source hash and generation stage;
- side, mirroring, camera, population state, layer set, physical scale, bounds,
  and resolution;
- required model fidelity and unresolved-model treatment;
- calculation inputs, units, environmental conditions, model/solver version,
  tolerances, and acceptance metric;
- inspection mechanism and retained findings.

An installed-heatsink top render therefore cannot replace a bare-board top
render, and a front copper plot cannot replace a combined-copper plot. They
answer different questions.

## Waivers

A D3 waiver is a retained risk decision, not a hidden skip. It requires:

- exact requirement ID and affected revision;
- reason the requirement cannot or should not be met;
- consequence and residual risk;
- compensating evidence, if any;
- owner/approver identity;
- issue date and expiry or closure condition;
- whether the waiver blocks routing, fabrication, energization, or only a
  particular review claim.

The AI may propose a waiver but may not self-approve safety, regulatory,
isolation, high-energy, thermal-signoff, or production-release waivers.

## Generator and pipeline rules

1. Shared workflow APIs own mandatory packages. Board-specific generators may
   supply features, regions, overlays, and supplemental render jobs, but may not
   recreate a partial mandatory package privately.
2. The package gate compares requirement IDs, not only whether a directory is
   non-empty.
3. Missing required output is `missing`, not silently absent. Unknown
   applicability is `unresolved`, not `not_applicable`.
4. Supplemental files never make a deficient baseline package pass.
5. A revision with a predecessor automatically evaluates comparison
   requirements unless explicitly not applicable or waived.
6. Output status cannot become `accepted` while any applicable requirement is
   `missing`, `uninspected`, `attention_required`, or unapproved `waived`.
7. A generator may produce an exploratory package, but it must use an
   exploratory status and cannot overwrite the canonical review authority.
8. Completed roadmap phases are not edited to hide later defects. A defect
   receives a dated erratum and a new sequential repair item.

## Enforcement tests

The implementation must include:

- a profile-to-manifest completeness test;
- tests that additions do not change baseline requirement coverage;
- adversarial tests for renamed, substituted, mirrored, stale-board, wrong-
  camera, wrong-layer, and wrong-population artifacts;
- a test proving a generator cannot report completion without the shared
  package manifest and review report;
- a predecessor-comparison trigger test;
- waiver schema, expiry, approval-boundary, and status-reduction tests;
- at least one live failure corpus item retaining the BLDC R002 omission.

## Immediate application to BLDC ESC R002

The existing `review-images/` directory is retained as D0 supplemental thermal-
mechanical evidence. It is not deleted or renamed. R002 remains incomplete
against the standardized visual package until the shared generator creates the
canonical `review/` hierarchy and passes the completeness/inspection gate.

That correction is Phase 15 work. The current thermal-mechanical placement can
still be discussed, but it must not be described as having a complete standard
visual package until the missing authority is generated and inspected.
