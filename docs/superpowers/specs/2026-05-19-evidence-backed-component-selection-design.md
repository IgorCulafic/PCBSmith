# Evidence-Backed Component Selection Design

Date: 2026-05-19

Status: Approved for the next PCBSmith vertical slice.

## Goal

Replace the demo-only component evidence in the divider/high-pass/LED authority
slice with a cache-first component evidence and deterministic selection path.

This slice does not implement live Octopart, Nexar, distributor, or manufacturer
downloads. It creates the stable local architecture those providers will plug into
later.

## Scope

Supported topology:

- `divider_highpass_led_indicator`

Supported component roles:

- `R1`: divider top resistor
- `R2`: divider bottom resistor
- `C1`: high-pass series capacitor
- `R3`: LED current-limit resistor
- `D1`: indicator LED

Supported evidence source:

- Local JSON evidence manifest plus local cached-file metadata.

Out of scope for this slice:

- Live API calls.
- PDF downloading.
- OCR or multimodal datasheet extraction.
- Trusting distributor pages as primary evidence.
- General component search.
- Final proof that a circuit works.

## Design Principles

- Check local evidence before any future fetch path.
- Treat part evidence as support for component selection, not as validation that
  the finished circuit works.
- Every selected fact must include a locator.
- A part can be selected only when required facts and ratings satisfy the
  deterministic requirements for its role.
- Missing evidence returns review findings and revision records. It must not be
  silently filled with familiar parts.
- The authority review bundle stays conservative. KiCad ERC and ngspice passing
  are necessary checks, not proof of complete correctness.

## Data Model

New package:

- `pcbsmith.evidence`

Core models:

- `EvidenceLocator`: source file, source URL, page or section, and optional table
  or figure label.
- `EvidenceFact`: name, value, unit, conditions, locator, and confidence.
- `CachedEvidenceFile`: local path, sha256, source URL, retrieved date, and
  license status.
- `ComponentEvidence`: manufacturer, part number, role, symbol, value,
  footprint, files, and facts.
- `ComponentSelection`: mapping from circuit reference to selected evidence.
- `EvidenceSelectionReport`: authority status, findings, cached files, selected
  parts, and missing facts.

Existing `ComponentRole.evidence` remains the review-facing evidence summary.
The new evidence models preserve the richer extracted facts used by selection.

## Cache Manifest

The manifest is local JSON with schema:

```json
{
  "schema": "pcbsmith-evidence-manifest-v1",
  "components": [
    {
      "manufacturer": "Example",
      "part_number": "EXAMPLE-10K-0603",
      "role": "divider_top",
      "symbol_id": "stdlib:R",
      "value": "10k",
      "footprint": "Resistor_SMD:R_0603_1608Metric",
      "files": [],
      "facts": []
    }
  ]
}
```

For this slice, test fixtures and one repository fixture can use synthetic
datasheet metadata. They must be labeled as fixtures, not vendor truth.

## Selection Rules

The divider/high-pass/LED selector receives a `CircuitObject` and an
`EvidenceCache`.

Required facts:

- Resistors: resistance, tolerance, power rating, package or footprint evidence.
- Capacitor: capacitance, voltage rating, dielectric or package evidence.
- LED: forward voltage, recommended or rated forward current, package or
  footprint evidence.

Deterministic checks:

- `R1` and `R2` resistance must match the requested divider values.
- `R1` and `R2` power rating must exceed calculated divider dissipation with
  margin.
- `C1` capacitance must match the requested high-pass capacitor value.
- `C1` voltage rating must exceed the supply voltage.
- `R3` resistance must match the calculated current-limit value.
- `R3` power rating must exceed calculated resistor power with margin.
- `D1` forward-current evidence must cover the nominal LED current.
- `D1` forward-voltage evidence must be compatible with the LED current-limit
  calculation assumptions.

If all checks pass, component roles become `supported` and receive evidence refs
with locators.

If any role is missing evidence or fails a rating check, it stays
`needs_datasheet_review` or `unsupported`, the evidence report is not `passed`,
and the authority bundle includes an evidence revision.

## CLI Integration

The authority CLI adds an optional evidence manifest argument:

```text
pcbsmith design-divider-highpass-led-authority OUT --name Slice --request ... --evidence-manifest PATH
```

If no manifest is supplied, the CLI runs with no component evidence and remains
honest: generic component evidence is still missing.

When a manifest is supplied:

- The CLI checks the cache before project generation.
- The selected evidence is attached to the `CircuitObject`.
- The review bundle includes evidence cached files and findings.
- The `evidence_missing` revision appears only when evidence is incomplete or
  failed.

## Review Status

This slice may still produce top-level `needs_human_review` even with component
evidence selected, because:

- The current LED path after AC coupling is signal-dependent.
- Fixture facts are not human-reviewed vendor datasheets.
- Schematic, SPICE, and KiCad checks remain separate authorities.

The success condition is narrower: PCBSmith can explain exactly which cached
evidence supports each selected component and exactly why a missing or under-rated
part blocks selection.

