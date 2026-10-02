# Automatic routing workflow - 2026-09-12

Implemented the user's approved change after CircleBlink: ordinary routing uses the installed pinned Freerouting; manual/native fallback is removed from the ordinary workflow. Manual copper edits remain available only for an explicit user request. This is separately scoped platform work, with no board operation or reopened board job.

## Behavior and shared owners

- `production_routing` resolves the explicit, environment, project or installation Freerouting configuration, verifies its pinned executable, and selects the external adapter. Exceptions and partial results propagate without invoking another engine. Explicit legacy native research remains available with `--legacy-native-reason`.
- `board_job` records `freerouting-one-retry-v1` for new jobs, with at most two lifetime routing attempts. A retry must change placement/footprints or electrical connectivity. Cosmetic/value/order/budget/output changes do not qualify. Existing timers, diagnostics, correction bounds and supervision still apply. Old serialized jobs omit the new fields and retain their exact behavior.
- `board_revision` rejects newly requested segment/via edits and copper-cutting zero-ohm-link edits without `manual_routing_authorization`. Historical accepted revisions can replay unchanged. Retained repair has the equivalent CLI gate; caller declarations record, but do not independently authenticate, user authorization.
- `freerouting_production` constrains rectangular front-only or two-layer DSN data. It prohibits vias on single-sided jobs and enforces the declared two-layer through-via geometry. Native import verifies unchanged placement/dependencies and required route geometry before DRC and transaction checks.
- `production_generators` recognizes the pinned Freerouting 2.3.0 adapter/version/source/executable identity alongside historical native receipts. Readiness, exact execution evidence and downstream release requirements remain in place.
- Retained-candidate validation restores the original hash-bound router settings and budget. It never launches the engine and remains compatible with older snapshots without policy metadata.
- `AGENTS.md`, current state and production usage now require engineering placement, bounded automatic routing, actual native/visual checks and requested isolation CAM. A blocker gets a bounded diagnosis and placement/jumper recommendation, not another router or board-specific framework work.

Local configuration: `.pcbsmith/freerouting.json`, Freerouting 2.3.0, maximum 600 process seconds and 30 passes. It references the already downloaded JAR and installed runtimes; it is a machine-local configuration, not a portable binary distribution.

## Verification

- Final combined regression: **297 passed**, zero failures/errors. Exact command and JUnit/log evidence: `outputs/automatic-routing-workflow-2026-09-12/final-regression-*` and `final-regression.xml`.
- Six changed source modules pass strict mypy with imported modules treated silently. Routing policy/dispatch/adapter and their focused tests pass Ruff. No repository-wide lint claim is made for unrelated pre-existing edits.
- Workflow audit: passed, 209 classified callers, no unclassified/stale/changed call declarations. Shared producer categories remain unchanged; this is a static classification check, not board acceptance.
- Read-only installed configuration/JAR integrity/runtime preflight passed. No router process was launched by this platform task.
- Exact completed CircleBlink native board SHA-256 remains `3b4f4e7fc0bb8f38a4bb6e595a8af7314f0a873c84e96d7dc2de6dc94c4ffabc`. No finished board, package or historical job ledger was changed.
- Earlier checks caught canonical two-layer ordering, a missing test import and retained-settings identity issues; they were corrected before the final run. Pre-change backups and deltas remain in the scoped output directory.

Existing frozen board-job test modules explicitly construct their historical policy fixtures. New policy tests separately exercise real new-job defaults, effective input hashing, one retry after placement change, exhaustion, manual authorization, no fallback, publication gates and exact retained-settings restoration. This does not edit actual historical ledgers.

## Limits and timing

No new end-to-end board benchmark or manufacturing qualification is claimed. Nonrectangular outlines, cutouts, pre-routed copper/zones and native plane-pour routing constraints remain explicit adapter blockers. Requested isolation channels still use the established post-routing CAM and inspection owners. Automatic routing does not itself establish circuit operation or fabrication readiness.

Platform estimate was 30 minutes; observed implementation/verification wall time at recording was 22.67 minutes. Board evaluation/execution allowances were not consumed or reset because no board work was performed. Source hashes and verification identities are retained in `completion.json`.
