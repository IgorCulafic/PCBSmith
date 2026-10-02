# Contributing

Start with [current state](docs/current-state.md) and [development](docs/development.md).
Use the frozen lockfile and shared verification entry point. Keep fixes bounded,
preserve existing user edits and add behavior-level controls at the failing boundary.
Do not update golden fingerprints merely to silence a failure: first explain the
semantic/schema change and replay the retained control.

Use a new attempt directory for generated evidence. Retain failed attempts and
exact inputs, commands, versions and outputs. Never regenerate cited boards,
manuscript ledgers or accepted proofs in place. Local-only code is valuable source;
being untracked or ignored does not make a file disposable.

Before staging, inspect the exact diff and the [retention policy](docs/repository-retention.md).
Machine configuration, credentials, model weights, raw conversations, private
reference material and unpublished papers require their own access/retention policy.
The software distribution allowlist is intentionally narrower than the checkout.
Do not auto-stage, commit, push, upload or publish the whole workspace.

Describe a change by its trigger, resulting behavior, verification and remaining
limits. A passing software suite cannot establish native board acceptance, physical
qualification, independent CAM agreement or research efficacy. See
[release](docs/release.md) for those separate boundaries.
