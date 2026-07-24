# Phase 14 project gate and exact-part discovery checkpoint

Date: 2026-07-22

## Outcome

The five promoted Phase 14 evaluators now have one automatic applicability and
completion gate. The gate does not infer applicability from the absence of a
result. It derives a required declaration set from a reviewed engineering
inventory bound to the exact BoardNetlist and layout snapshot.

The same slice adds exact-MPN discovery for nine resource roles: datasheet,
errata, hardware guide, package drawing, reference design, simulation model,
KiCad symbol, KiCad footprint, and 3D model.

## Project context and applicability

A complete context profiles every retained BoardNetlist component, records
exact-MPN/generic/unknown identity status, retains L0-L3 complexity, names the
intended consumer, and requires reviewer plus source-context identities.
Reviewed feature declarations determine which evaluator declaration IDs are
required for each of the five families.

The gate consumes the real replay-valid evaluator result types. It checks exact
declaration-set equality and layout/netlist snapshot equality. Applicable
results cannot return `NOT_APPLICABLE`; undeclared results also make the gate
unverified. An incomplete inventory cannot assert features and makes all five
families unresolved.

The combined outcome is `blocked`, `unverified`, `review`, or `ready` and is
itself replay-derived and fingerprinted. `pcbsmith project-engineering-gate`
writes the retained JSON artifact.

## Exact-part documents and CAD

Discovery uses exact normalized manufacturer/MPN identity and independently
records every requested role. A deterministic candidate-catalog provider
supports API/exported metadata, while an adapter exposes the existing
Nexar-compatible evidence provider for datasheet lookup. Fuzzy or different
MPNs are rejected before download. Multiple exact candidates are also rejected
until a provider/revision is selected explicitly; lexical ordering is not a
substitute for engineering identity selection.

Downloads pass through the existing safe source-intake service, preserving host
allow-list, HTTPS, license, content identity, hash, redirect, retry, private
cache, and redacted public-manifest behavior. A located URL is not a downloaded
file, and a validated CAD download is not an installed asset.

Installed KiCad asset records are now schema v2 and retain optional part number
and source URL. A public, private-path-redacted installation fingerprint binds
an exact symbol, footprint, or 3D model to its MPN. The project gate requires
validated cache state for documents and installed state for required CAD.

## Verification

- 30 focused project-gate, exact-part, source-intake, CLI, and asset-install
  tests passed before the shared run.
- 182 shared tests passed across the new slice and all five promoted semantic
  authorities.
- Ruff passed for the changed production and test files.
- Mypy passed for the changed production modules and CLI.

Coverage includes exact retrieval, fuzzy-MPN rejection, the existing provider
adapter, installed-versus-located CAD, report tampering, missing applicable
results, foreign-board results, undeclared evaluator results, incomplete
inventory, exact-part readiness, CLI artifacts, and result/context tampering.

## Deliberate limits

- The gate is operational but has not yet been exercised through the next
  materially different production-board workflow.
- Applicability facts require a complete reviewed inventory; automatic circuit
  intent extraction cannot silently replace that engineering review.
- Live multi-role provider adapters beyond the existing datasheet path remain
  open pending credentials, terms, cache rights, and API qualification.
- Discovery and installation do not prove that a CAD asset has the correct
  geometry or electrical pin mapping; existing asset validation, component-card
  review, model preflight, ERC/DRC, and visual inspection remain required.

## Next increment

Exercise the gate on the user's new board prompt. Before routing, build its
engineering context and exact-part discovery requests. After routing, run every
derived applicable evaluator, install required CAD, produce the gate artifact,
and retain any missing-result or resource failure evidence. Add new provider or
context types only when that board demonstrates the need.
