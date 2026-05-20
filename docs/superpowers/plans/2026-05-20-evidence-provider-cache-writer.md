# Evidence Provider And Cache Writer Plan

Date: 2026-05-20

## Objective

Add the first real evidence acquisition boundary after the cache-backed fixture
selection slice. This slice creates provider and cache-writer plumbing without
using live API calls or trusting downloaded documents as facts.

## Architecture

Add a small acquisition layer under `pcbsmith.evidence`:

- `EvidenceAcquisitionRequest`: role, query, optional manufacturer and part
  number.
- `EvidenceSourceCandidate`: provider metadata containing manufacturer, part
  number, role, optional symbol/value/footprint metadata, datasheet URL, source
  URL, and license status.
- `EvidenceProvider`: protocol that returns candidates for a request.
- `EvidenceDownloader`: protocol that returns bytes for an explicit URL.
- `EvidenceAcquisitionService`: checks the manifest/cache first, calls a provider
  only when needed, downloads only a selected URL, writes local cache files, and
  updates the manifest.

The existing selector remains unchanged: it still consumes extracted facts. This
new layer only acquires source material and records where it came from.

## Non-Goals

- No Octopart/Nexar live calls in this slice.
- No manufacturer scraping.
- No PDF parsing, OCR, table extraction, or multimodal extraction.
- No claim that a downloaded PDF proves any component fact.
- No automatic component support status upgrade from downloaded files alone.
- No board or schematic generation changes.

## Tasks

### Task 1: Acquisition Models

- Add tests for request, provider candidate, and acquisition report validation.
- Add immutable Pydantic models in `src/pcbsmith/evidence/models.py`.

### Task 2: Cache-First Acquisition

- Add a test showing an exact cached manufacturer/part-number request returns a
  cache hit and does not call provider or downloader.
- Implement cache lookup helpers over the existing manifest.

### Task 3: Provider Miss And No-Download Behavior

- Add tests showing provider miss returns `missing`.
- Add tests showing a candidate without a datasheet URL returns `missing` and
  does not call downloader.

### Task 4: Download And Manifest Write

- Add a test with a mocked provider and mocked downloader.
- Verify the service writes one local cached file, records sha256/source URL,
  adds a manifest component, and returns `downloaded`.
- Verify a second request for the exact same part is a cache hit and does not
  redownload.

### Task 5: Verification

- Run targeted evidence tests.
- Run `python -m ruff check src tests`.
- Run `python -m mypy src`.
- Run the full unit/integration suite with plugin autoload disabled.

## Status Ledger

Expected implementation after this slice:

- Cache-first acquisition boundary exists in shared code.
- Manifest writer can record newly acquired source files.
- Provider and downloader are injectable, so live APIs can be added later without
  changing selection logic.

Still not implemented after this slice:

- Real Octopart/Nexar provider.
- Real network downloader default.
- Datasheet fact extraction.
- Human-reviewed fact approval.
- Real vendor-backed component selection.

