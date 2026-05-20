# Evidence-Backed Component Selection Plan

Date: 2026-05-19

## Objective

Implement the first cache-first component evidence path for the
divider/high-pass/LED authority slice.

## Architecture

Add a new `pcbsmith.evidence` package for manifest parsing, local cache lookup,
and deterministic component selection. Keep schematic generation and KiCad/ngspice
authority checks unchanged except for receiving a circuit object whose components
may now carry evidence-backed support status.

## Tasks

### Task 1: Evidence Models

- Add unit tests for evidence locators, facts, cached files, component evidence,
  selection reports, and manifest validation.
- Implement immutable Pydantic models under `src/pcbsmith/evidence/models.py`.
- Export the models from `src/pcbsmith/evidence/__init__.py`.

### Task 2: Cache Reader

- Add tests that load a manifest, find components by role/reference-compatible
  data, report cached files, and reject malformed schema.
- Implement `EvidenceCache` under `src/pcbsmith/evidence/cache.py`.
- Keep the cache read-only in this slice.

### Task 3: Divider/High-Pass/LED Selector

- Add tests for a complete manifest selecting all five parts.
- Add tests for missing role evidence.
- Add tests for under-rated resistor, capacitor, and LED facts.
- Implement deterministic role requirements and selection under
  `src/pcbsmith/evidence/divider_highpass_led.py`.

### Task 4: Circuit Integration

- Add tests that selected evidence converts component roles from `demo_only` to
  `supported`.
- Add tests that failed evidence leaves roles in `needs_datasheet_review` or
  `unsupported`.
- Update `compose_divider_highpass_led` to accept optional component overrides or
  add a helper that returns an evidence-enriched circuit object.
- Preserve current schematic generation behavior.

### Task 5: CLI And Bundle Integration

- Add integration tests for `--evidence-manifest`.
- Verify that a complete evidence manifest removes the `evidence_missing`
  revision.
- Verify that a missing/failed evidence manifest keeps the evidence revision and
  names the missing role or rating failure.
- Extend `EvidenceReport.cached_files` and findings from the selector output.

### Task 6: Fixtures

- Add local evidence fixtures under `tests/fixtures/evidence/`.
- Add one small repository fixture under `data/evidence/` if useful for CLI smoke
  tests.
- Mark fixture facts clearly as fixture evidence, not real vendor datasheets.

### Task 7: Verification

- Run:
  - `python -m ruff check src tests`
  - `python -m mypy src`
  - `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; python -m pytest tests\unit tests\integration -q -p no:cacheprovider`
- Run the KiCad/ngspice authority smoke with the evidence manifest.
- Inspect the review bundle manually enough to confirm evidence, KiCad, ngspice,
  reconciliation, and revisions are distinct.

## Acceptance Criteria

- Cache-first evidence lookup exists in shared code and is covered by tests.
- The selector attaches locator-backed evidence refs to all five component roles
  when fixture evidence is complete.
- Missing or insufficient evidence blocks support status and produces explicit
  review findings.
- The CLI can run with and without an evidence manifest.
- The review bundle no longer claims generic evidence is missing when complete
  manifest-backed evidence is selected.
- No live network/API dependency is required.
- KiCad and ngspice remain separate authority checks.

## Implementation Status Ledger

Implemented in this slice:

- Read-only local JSON evidence manifest parsing.
- Cache-first component lookup in shared `pcbsmith.evidence` code.
- Locator-backed fixture facts for the divider/high-pass/LED roles.
- Deterministic selection checks for resistor value and power rating, capacitor
  value and voltage rating, and LED forward-voltage/current facts.
- Authority CLI support for `--evidence-manifest`.
- Review bundle evidence status and conditional evidence revision routing.
- Unit/integration tests plus a real KiCad/ngspice authority smoke using the
  fixture manifest.

Not a full implementation yet:

- The fixture manifest is synthetic test evidence, not real vendor datasheet
  evidence.
- No Octopart, Nexar, manufacturer, or KiCad-library metadata provider exists.
- No datasheet PDF/model downloader exists.
- No PDF text extraction, table extraction, OCR, or multimodal figure extraction
  exists.
- No human-reviewed evidence workflow exists.
- No SPICE model evidence selection exists beyond the current generic KiCad LED
  model.
- No footprint/package validation against real KiCad footprints exists.
- No board/layout authority checks are connected to this evidence path.
- The divider/high-pass/LED circuit can still require human review even when
  evidence, KiCad ERC, KiCad SPICE export, and ngspice pass.

Concrete follow-up work:

1. Add a provider interface with cache-first semantics, then implement a mocked
   provider test before any live API integration.
2. Add Octopart/Nexar metadata lookup behind that provider once credentials and
   rate-limit behavior are known.
3. Add manufacturer datasheet/model URL resolution and cache writes with source
   URL, retrieval date, checksum, and license status.
4. Add extracted-fact JSON generation from cached PDFs, starting with text/table
   extraction before OCR or multimodal review.
5. Add a human-review status for extracted facts so fixture/machine-extracted
   facts cannot be mistaken for reviewed vendor evidence.
6. Add KiCad footprint/package validation and keep board generation blocked until
   evidence, schematic, simulation, and layout checks agree.
