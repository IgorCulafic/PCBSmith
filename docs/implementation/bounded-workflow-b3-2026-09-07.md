# B3 — exact shared asset reuse — 2026-09-07

Status: scoped software implementation passes; fresh-board delivery and timing remain B4 acceptance work.

## Changes

- Added AssetPin (kind, exact Library:Name, SHA-256 and optional local file) and asset-resolve. Native preparation accepts asset_pins, rejects stale explicit pins, resolves shared symbols before installed libraries, retains local dependencies and records local/pinned hits with zero fetch count.
- Lookup order is explicit board pin, repository, configured private collection, then installed KiCad. A conflicting selected local revision stops resolution. An empty new output directory is never a cache miss.
- A genuine miss can use the existing approved SourceIntakeService, with a required source hash, followed by the existing installer. The pin checks normalized installed bytes before publication; source and installed hashes stay separate.
- The existing installer now shares one normalization function, validates package/name and confined identifiers, refuses conflicting replacements and writes atomically under an OS lock. Resolver locks serialize concurrent misses within repository/private scope. Lock contention is bounded at ten seconds per acquired lock; the board supervisor also bounds aggregate runtime.
- Project-local footprint contexts cover predesign generation, approval and native generation. They validate retained source hashes and prevent a missing member of a declared local library from silently falling through to shared assets. Contexts do not leak between concurrent workers.
- Symbols use the same repository/private precedence, and the shared loader verifies the requested symbol rather than accepting the first symbol in a file. Board-local KiCad symbol/footprint tables continue to provide native portability.
- asset-resolve is a supervised board-job operation. It inherits the existing retry/deadline allowance. Raw SourceIntakeService and asset-install remain general platform tools, not proof of an ordinary board workflow.

Owners: kicad/asset_resolution.py, asset_install.py, library.py, symbols.py, project_dependencies.py; native_project.py, predesign_preparation.py, production_generators.py, cli.py and board_job.py.

## Verification and retained failures

150 integrated B1–B3 tests passed: outputs/bounded-workflow-b3-2026-09-07/tests-final-03.xml. Tests cover a true miss followed by an offline hit, repository/private symbols and footprints, concurrent misses fetching once, conflicting revisions, corrupt local copies, wrong normalized hash, package/name mismatch, missing approval, missing supervision, and relocation with a changed shared footprint. Existing intake, native pin-intent and readiness suites were included.

Repository Ruff passes. The workflow audit passes all 196 callers: workflow-audit-final.json. Focused mypy checks pass for the new floorplan/resolution modules and board_job. Failed attempts remain retained: tests-final.xml caught a relocation fixture with no measurable geometry; the fixture was corrected, not the real loader weakened. Earlier tests-attempt-* and tests-final-02.xml remain available.

## Limits

These are synthetic acquisition tests using a recording downloader, not live supplier-download or license qualification. Existing model intake/preflight remains authoritative for 3D models; the new pin resolver supports symbols and footprints only. Matching names/pad sets and hashes do not establish a manufacturer's electrical or physical package qualification.

A portable KiCad project is not a portable approval history: retained audit records can contain original absolute provenance paths. Moving a board requires fresh evidence for further production edits; old approval is not silently rebound. The new CLI handles one asset per invocation and obeys the job's existing operation limits; larger intake catalogs need separately scoped batching rather than allowance resets.

No accepted board was changed or cleared. B4 still needs a real supervised fresh-board run, required native/engineering checks, timing records and a local revision. This report does not close B4, DR7 or manufacturing/physical holds.

## B4-exposed replay correction

The first B4 generation stopped before writing a PCB because CLI model loading replayed concept geometry before entering the project-local context. The shared predesign contract now replays its fingerprinted retained footprint source paths; native hash checks remain independent. The actual B4 bundle loads without a project context, and 83 replay/asset/readiness tests pass (replay-boundary-tests-02.xml). The failed fixture run is retained; its initial integer outline inputs were corrected to canonical floating-point coordinates.

Retry identity also now includes shared Python implementation bytes. This permits a diagnosed code fix to be an effective input change while preserving the same deadline/correction cap; output-directory changes still do not count. The child-deadline test isolates source inventory cost because preflight expiry has separate coverage.

## Final integrated gate

188 tests passed, zero failures/errors/skips (final-integrated-tests.xml). Final repository Ruff and focused four-module mypy pass. verification.json records source hashes and exact scope. B4 stopped after 18 min 26 s with a valid placement candidate and remaining silkscreen/routing/review work; see its separate report.
