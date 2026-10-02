# Development and verification

The maintained local configuration is Windows, Python 3.12.12, uv 0.11.23,
KiCad 10.0.6 and ngspice 46. Dependencies are resolved in `uv.lock`; use
`uv sync --frozen --all-extras --python 3.12.12`, not an unpinned pip upgrade.
The `dev` extra contains the test, lint, import and type tools. Geometry and
review tests additionally use `artwork`, `preview` and `review`; all-extras
is the documented complete development environment.

## Keep an existing environment intact

For an independent setup proof, set `UV_PROJECT_ENVIRONMENT` to a new absolute
path before `uv sync`, then run that environment's Python directly. Unset the
variable afterward. Do not remove an apparent cache that contains the base
interpreter named by `.venv/pyvenv.cfg`; this checkout's existing runtime
currently depends on a Python installation beneath `.tmp`.

## One verification authority

`tools/verify.py` calls `standard_verification_gates` and
`VerificationOrchestrator` from `pcbsmith.execution`, also used by
`pcbsmith verify`. Run from the checkout; pick a new output directory.

- `--profile standard`: lock, lint, native-caller audit, types, architecture contracts and all ordinary tests.
- `--profile quick`: the same static gates and a documented focused test subset.
- `--profile deep` (or `--native`): full tests including the live golden lane.
- `--checks lock lint types imports` (or a smaller selection): diagnostic subset;
  the environment record explicitly marks it as an incomplete gate matrix.

The native-caller audit runs in every complete profile and also with `--checks lint`, including the hosted static CI lane. It compares source/tools callers against `docs/board-workflow-entrypoints.json`. Review an added or changed caller before editing that policy; never regenerate it merely to obtain a pass. Quick tests also include the native-edit, revision, rebuild and caller-audit regression suites. The audit is deliberately conservative and cannot discover every dynamic Python write.

Each run contains `environment.json` (wrapper), `verification-run.json`, a
checkpoint after each gate, append-only progress for that run, stdout/stderr
logs, and pytest JUnit output. Reusing a completed output directory is refused.
Failure is never converted to a pass by excluding a failed check. Timeouts and
memory limits are recorded separately; OS enforcement availability appears
in each gate result.

The worker loads pytest-qt and the Hypothesis pytest plugin explicitly with plugin auto-loading disabled,
uses Qt's offscreen platform and Fusion style, and registers a real font.
Default font candidates are Segoe UI on Windows, DejaVu Sans on Linux, and
Arial on macOS. Set `PCBSMITH_TEST_FONT` to a TTF path to override; a missing
or unloadable font is an error, not a substituted visual baseline. Cross-OS
visual parity remains a separate verification task.

## Native dependencies

Set `PCBSMITH_KICAD_CLI` to the KiCad CLI executable and `PCBSMITH_NGSPICE` to
the ngspice console executable when they are not found automatically. Windows
KiCad 10/9 library locations are recognized. Install the full matching KiCad
symbol/footprint collection; the small bundled asset subset does not cover
every board-specific footprint. Footprints now load lazily, with source/revision-scoped caching; untested platforms are not claimed supported by
this Windows validation record.

The deep worker checks for both executables before pytest. Live tests write
to the run's temporary directory and do not confer acceptance on an existing
board. Excluded native rules, footprint suitability, assembly, thermal behavior
and physical measurements still require their own evidence.

## CI scope

`.github/workflows/verify.yml` defines an automatic hosted Windows static
lane and a manually dispatched complete lane for a prepared, trusted Windows
runner labeled `pcbsmith-native`. The latter requires the versions above,
full KiCad libraries and a usable test font. It is not automatically run on
pull requests against a self-hosted machine. Both lanes use the same checked-in
verification command. CI has not been dispatched or observed remotely during
this local implementation; runner provisioning is an external prerequisite.
No unpublished paper, model, private source or entire workspace is uploaded
as an artifact by this workflow. The repository's own visibility and access
controls remain the operator's responsibility.

The pinned actions follow their official documentation:
[checkout](https://github.com/actions/checkout) and
[setup-uv](https://github.com/astral-sh/setup-uv).

## Agent failure evidence

`ai-local-agent-review` stores each attempt under `OUTPUT/attempts/RUN_ID`.
Use the result's paths rather than assuming fixed files at the output root.
Request bodies, redacted responses, actions, tool results and terminal state
are retained in `agent-events.jsonl`; headers are omitted and the configured
API key and structured credential fields are redacted. The transcript is
checkpointed after each completed tool. A later parse or storage error cannot
silently use an earlier candidate. Legacy output files remain historical.
These logs still contain confidential project context: keep them local.

Hypothesis performs source-constant discovery during collection through its pytest
plugin. Omitting that plugin charges cold-cache AST scans to the first timed
input draw and can incorrectly trigger `HealthCheck.too_slow`. Health checks and
property assertions remain enabled.

The deep profile enables the general regeneration lane and the R2, R4, R5 and
PWLED micro-pilot native lanes. Standard/quick explicitly disable these opt-ins.

Phase 1 validation: all five shared gates passed; 3,725 ordinary/general-native
tests plus nine separately enabled KiCad tests passed (3,734 distinct tests).

## Editor controls and asset reload
Editing shortcuts operate while the canvas has focus. Ctrl+K opens component search;
Enter activates a result, Enter on the canvas places the armed component at its center,
and Escape returns to Select. P pans with the left mouse button; middle-button pan
also works. R/C/D/L arm common components; Ctrl+R rotates selected symbols.
Settings without implementations are disabled.

The footprint loader caches at most 256 resolved source revisions using absolute
path, mtime_ns and size. Switching a private asset root or normally saving a changed
asset selects a new entry. A tool that deliberately preserves timestamps and size
must call load_footprint.cache_clear() after the rewrite. Existing generation
invalidation calls remain supported. These cache keys do not replace release hashes.

Private asset roots remain process configuration. Concurrent projects requiring
different roots need explicit resolver instances or separate processes before
multi-project service use; the present cache contract does not isolate environment
variable mutation between threads.
