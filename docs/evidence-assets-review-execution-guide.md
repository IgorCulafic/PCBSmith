# Evidence, KiCad assets, visual review, and execution guide

Status: implemented foundation, 2026-07-20

This is the operating guide for the Phase 11 and Phase 12 infrastructure. It
does not make a board production-ready by itself. The final proof is the next
unseen, user-selected two-layer board containing ICs and sensors, a PNG outline,
and explicitly positioned silkscreen artwork.

## 1. Source intake

`pcbsmith source-intake` is local-first and fail-closed. It accepts only an
explicit HTTPS URL on the request's approved-host list, requires a named
consumer and cache/license disposition, identifies the content by magic bytes,
checks an optional SHA-256, verifies ZIP integrity and required archive members,
and writes two records:

- a private manifest containing the absolute cache path;
- a commit-safe manifest containing metadata, hashes, status, and findings but
  no private path or source payload.

Example request:

```json
{
  "source_id": "selected-sensor-datasheet",
  "source_url": "https://manufacturer.example/sensor.pdf",
  "approved_hosts": ["manufacturer.example"],
  "intended_consumer": "U3 pinout, footprint, placement, and model selection",
  "expected_kind": "pdf",
  "license_status": "local_cache_only",
  "expected_sha256": null,
  "expected_archive_members": []
}
```

```powershell
pcbsmith source-intake request.json `
  --private-manifest .pcbsmith-private/sources.json `
  --public-manifest evidence/source-metadata.json `
  --cache-dir .pcbsmith-private/source-cache
```

`downloaded` and `cache_hit` are successful intake states. `blocked` records
host, transport, license, or empty-payload problems. `failed` records an
identity mismatch. Downloaded does not mean distilled or production-exercised.

The downloader makes three attempts by default. Retryable HTTP and transport
failures use deterministic capped exponential backoff; a numeric `Retry-After`
value can extend the delay up to the configured cap. The final attempt may use
browser-compatible headers, but the original URL and the final redirected URL
must both remain HTTPS and inside the explicit approved-host set. Response
status, delay, header profile, final URL, and content disposition are retained
as metadata; content disposition never overrides magic-byte and hash checks.
HTTP 401/403 is recorded as `authentication_required`, separately from an
ordinary network failure.

For a catalog, use the resumable batch command:

```powershell
pcbsmith source-intake-batch `
  docs/reference/data/advanced-pcb-source-requests-2026-07-22.json `
  --private-manifest .pcbsmith-private/research-2026-07-22/source-intake-private.json `
  --public-manifest docs/reference/data/advanced-pcb-source-intake-2026-07-22.json `
  --cache-dir .pcbsmith-private/research-2026-07-22/cache
```

Each catalog entry is committed to both manifests before the next entry begins.
Rerunning the same catalog therefore resumes from validated cache hits instead
of restarting completed downloads. Research-only annotation fields such as
`title` and `category` are ignored by the intake request validator. Duplicate
`source_id` values and malformed entries stop the batch before network access.
Manifest v2 adds retrieval telemetry; v1 manifests remain readable and are
upgraded on the next write.

### 1.1 Exact-part multi-role discovery

`pcbsmith part-discover` takes an exact manufacturer/MPN request plus a
provider/API candidate catalog. It resolves datasheet, errata, hardware guide,
package drawing, reference design, simulation model, KiCad symbol, KiCad
footprint, and 3D-model roles independently. Candidate identity is normalized
only for punctuation/case; a different or fuzzy MPN is rejected. Multiple
exact candidates require explicit provider/revision selection rather than an
arbitrary first-result choice. Document readiness also requires the selected
revision to be retained in the discovery record.

```powershell
pcbsmith part-discover exact-part-request.json provider-candidates.json `
  --private-manifest .pcbsmith-private/part-sources.json `
  --public-manifest evidence/part-sources.json `
  --cache-dir .pcbsmith-private/part-cache `
  --installed installed-part-resources.json `
  --output exact-part-discovery.json
```

Official URLs are still retrieved through `source-intake`, including approved-
host, licensing, magic-byte, archive, hash, redirect, retry, and redaction
rules. A retrieved symbol, footprint, or model is only `validated_cache`; it is
not usable CAD until `asset-install` validates and installs it. Installed asset
records now retain optional exact part number and source URL, allowing a public,
path-redacted installation fingerprint to bind the asset back to the exact MPN.

The implemented adapter can use the existing credentialed Nexar-compatible
provider for datasheet candidates. Other live multi-role services remain
conditional on their API terms, credentials, cache rights, and verified asset
mapping; exported candidate catalogs can be used in the meantime.

## 2. Installing KiCad assets

`pcbsmith asset-install` validates a previously acquired symbol, footprint, or
STEP/WRL model before installation. It never mutates the global KiCad program
directory.

- Redistributable assets may enter `ai_assets/kicad_symbols`,
  `ai_assets/kicad_footprints`, or `ai_assets/kicad_models`.
- Other assets enter the ignored `.pcbsmith-private/kicad-assets` tree.
- Set `PCBSMITH_PRIVATE_ASSET_ROOT` to that private root when loading private
  symbols and footprints.
- A model installation produces a registry entry that maps the board's raw
  KiCad model path to the validated local file. Review rendering substitutes
  that resolved path only in a derived render input; it does not alter the
  authoritative board or copper.

Every model must be classified as `exact_package`, `complete_module`,
`connector_only`, `proxy`, or `unknown`. A proxy is never silently accepted for
an exact-package requirement.

```powershell
pcbsmith asset-install asset-request.json `
  --private-asset-root .pcbsmith-private/kicad-assets `
  --public-record evidence/assets/selected-sensor-model.json
```

## 3. PNG outline and silkscreen inputs

The raster adapters are deterministic and source-hashed:

- `trace_board_outline` extracts the largest external silhouette, validates and
  simplifies it, scales it to the requested physical width and margin, and
  returns board-local millimetre coordinates.
- `trace_silkscreen_artwork` traces every usable contour, including internal
  holes as visible contour lines, then applies explicit width, anchor, side,
  rotation, mirror convention, and line width.

Silkscreen placement is not inferred from the image. For each artwork image the
board request must specify at least:

- front or back side;
- centre anchor or an agreed named region;
- physical width;
- rotation;
- whether it should be mirrored;
- whether outline-style tracing is acceptable.

The resulting source hash and transform belong in the board evidence. This
prevents a later replacement PNG or changed scale from masquerading as the
reviewed artwork.

## 4. 3D preflight

```powershell
pcbsmith model-preflight board.kicad_pcb `
  --registry model-registry.json `
  --requirements model-requirements.json `
  --output model-preflight.json
```

The preflight parses each footprint model clause, resolves KiCad variables and
registered private overrides, hashes files, retains offset/scale/rotation, and
evaluates reference-specific required classifications. Missing required models,
wrong classifications, and hash mismatches fail. Unresolved optional or
unregistered models produce `attention_required` rather than disappearing.

## 5. Visual evidence package

```powershell
pcbsmith visual-review board.kicad_pcb output-directory `
  --stage placement `
  --features review-features.json `
  --model-preflight model-preflight.json
```

Run it once after placement and again after final routing. It creates
`review/manifest.json`, `review/review-report.md`, vector and PNG layer views,
physical-scale-aware tiles and detail crops, declared electrical-class
overlays, diagnostic images, fixed populated and bare-board 3D cameras, and
previous/current comparisons when a predecessor is declared.

Full-board 2D renders use a minimum 3,840-pixel long edge and 20-40 px/mm;
details use 80-120 px/mm. Large views receive deterministic overlapping tiles.
All output files are hashed. Bottom views record their mirror convention.

Declared electrical classes require an overlay from their existing semantic or
routing authority. Declared diagnostics, predecessor comparisons, required
models, or required images fail the generation gate when missing.

Generation ends at `generated_pending_inspection`. Rendering is not inspection.
A reviewer or inspection mechanism must submit a decision for every required
artifact through `pcbsmith visual-inspect`; only then may the package become
`accepted`. Any required `attention_required` decision keeps the gate open.

## 6. Execution and verification

```powershell
pcbsmith verify .pcbsmith/verification/quick --profile quick
pcbsmith verify .pcbsmith/verification/standard --profile standard
pcbsmith verify .pcbsmith/verification/deep --profile deep --timeout-scale 1.5
```

The three profiles reuse `uv lock --check`, Ruff, strict mypy, pytest, and the
existing golden selection. They do not create parallel one-off rule systems.
Each gate has:

- an OS-enforced memory ceiling;
- a configurable per-gate wall-time limit;
- heartbeat events in `progress.jsonl`;
- typed termination (`passed`, `failed`, `unavailable`, `timeout`,
  `memory_limit`, or `interrupted`);
- stdout/stderr files and hashes;
- a checkpoint written only after a complete verification gate.

Routing and placement engines use their own deterministic expansion/pass
budgets. `execution.py` also exposes a generic ledger, but the execution
profiles do not yet bind or aggregate every engine's native counters. A timeout
is an operator/machine policy, not an algorithmic proof. The checkpoint format
currently proves completed repository-verification gates only; it does not
claim mid-gate resume equivalence or board-stage resume.

### 6.1 Phase 14 project-engineering gate

The project gate prevents an applicable promoted evaluator from disappearing
between board generation and completion:

```powershell
pcbsmith project-engineering-gate project-context.json phase14-results.json `
  --discovery-report exact-part-u1.json `
  --discovery-report exact-part-u2.json `
  --output project-engineering-gate.json
```

The context is bound to exact layout/netlist snapshots and contains an
exhaustive reviewed component inventory plus feature declarations. Those
features derive applicability for decoupling loops, connector-to-protection
order, oscillator zones, switching hot loops, and return adjacency. The result
bundle contains the actual replay-valid evaluator result types, not caller-
supplied pass/fail summaries.

For each applicable family the supplied declaration IDs must exactly equal the
required IDs and belong to the same board snapshots. Missing, extra, foreign-
board, or inapplicable results become `UNVERIFIED`. A complete reviewed
inventory can derive `NOT_APPLICABLE`; an incomplete inventory leaves every
family unresolved. Required exact-part documents must be validated in cache,
while symbols, footprints, and 3D models must have installed-asset evidence.

This is now an operational CLI gate, but it has not yet been exercised through
the next materially different board workflow. That production proof remains a
separate acceptance step.

## 7. What remains board-specific

The generic callable infrastructure passed its 2026-07-20 repository
regression, but the later Retro-Pad pilot showed that automatic board-workflow
integration was incomplete. A new board brief should still provide:

- circuit purpose, power source, interfaces, and operating limits;
- required sensors/ICs or functional preferences;
- the outline PNG;
- each silkscreen PNG plus its placement/size/orientation instructions;
- connector and mounting constraints;
- any enclosure, fabrication, or assembly constraints.

Component count and routing difficulty can remain unspecified. PCBSmith must
derive them from the design rather than asking the benchmark to pre-solve the
layout.
