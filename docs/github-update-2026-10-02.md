# Public repository update — 2026-10-02

This software snapshot advances the public `main` branch from `8986a8e` while
leaving unpublished manuscript and experiment history local. It includes the
current production KiCad workflow, automatic Freerouting integration, mandatory
component/visual review and handover, SMD substitution, interactive BOM delivery,
vector planning, laser CAM and the associated regression tests and documentation.
Machine configuration, model weights and generated board delivery archives are
outside this software update. This is a repository update, not a tagged release
or a new physical manufacturing qualification.

## Clean-checkout portability

Fourteen tests depended on historical files under local output and experiment
directories. Their unit-level assertions now use explicit synthetic fixtures:
legacy approval byte locks and migration, marking classification and bounded
repair planning, qualification blocker membership, final-fill connectivity and
DRC revision binding. No test was skipped to obtain a pass. Production approval
constants and rules are unchanged; an added regression checks the original legacy
hash allowlist. Synthetic results do not constitute approval or native evidence
for any real board. Historical source tests and raw project evidence remain local.

The public caller-audit policy omits the two private paper-tool entry points that
are absent from this checkout. All present production callers remain classified.
Documentation links to retained local-only evidence are explicitly identified.

## Verification

Validation used Windows, Python 3.12.12 and uv 0.11.23, with the isolated public
checkout's `src` explicitly selected rather than the original editable install.

- The full ordinary run collected 4,674 tests: 4,632 passed, 14 failed on missing
  historical fixtures, and 28 were skipped by their existing conditions.
- After the fixture repair, all 29 tests in the five affected modules passed,
  including the added legacy-allowlist check. The full suite was not rerun after
  this test-only change; its initial failed report is retained, not relabeled.
- Final dependency-lock, Ruff, producer-boundary audit, strict mypy and import
  contract checks passed. The audit covers 211 public callers.
- Source distribution and wheel builds passed their archive-content checks
  (518 source archive entries and 517 wheel entries). These archives were checked
  locally and were not published as a package release.
- The staged diff passed whitespace checks; changed documentation had no missing
  relative Markdown targets. The selected content passed a scoped credential
  pattern scan, and no private manuscript/experiment/output paths were staged.

The manually dispatched deep/native CI lane and physical board tests were not
run as part of this repository update. See [development](development.md) and
[current scope](current-state.md) for reproducible commands and limits.
