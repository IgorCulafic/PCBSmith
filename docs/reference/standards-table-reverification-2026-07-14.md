# Standards table re-verification - 2026-07-14

## Scope

This report repeats the standards checks that were left unresolved in the
materials audit:

1. visual verification of IEC 60664-1:2020 Table F.5;
2. visual verification of IPC-7352 dense land-pattern tables, especially BGA
   Table 3-11; and
3. determination of whether the pinned IEC PDF includes COR1:2020.

The complete render/crop evidence is under `tmp/pdfs/standards-reverify/`.

## Sources

| Source | SHA-256 | State |
|---|---|---|
| Local IEC 60664-1:2020 Edition 3.0 | `438E2928531D898FAD38F13FCD8B572FC3256DEFE83171FC063DDA0B8F708F43` | Base May 2020 copy downloaded 2020-06-27; no COR1 or AMD1 |
| Local IPC-7352, May 2023 | `30DF8D0D895DD79A956E05F50CE9B508FCCA0D4B0A888CC4712A24FB92A9CB0A` | 62-page local PDF |
| IEC 60664-1:2020/COR1:2020 | `A7EBE3F13FDB3B2CB4617108880BFF1A041023F81A69129CF2DC4297A8D192E2` | Free corrigendum downloaded and inspected during this audit |

## Method

- Poppler rendered IEC pages 73-74 and IPC page 22 at 600 dpi.
- IPC pages 19-23 were also rendered at 300 dpi.
- `pdfplumber` independently extracted glyph coordinates for exact row and
  column crops.
- High-resolution crops were forwarded directly to the image channel as image
  data because the normal Windows image viewer failed.
- The downloaded IEC corrigendum was independently text-extracted and visually
  compared with the local base.

These are visual checks, not OCR-only inferences.

## Resolved results

### IEC Table F.5 250 V row

The 600 dpi crop confirms the printed 250 V row, in column order:

`250 | 0.560 | 1.000 | 0.56 | 1.25 | 1.80 | 2.50 | 3.20 | 3.60 | 4.00 mm`

IEC uses decimal commas; decimal points above follow project notation.

| Condition at 250 V RMS | Minimum creepage |
|---|---:|
| Printed wiring material, PD1, all material groups | 0.560 mm |
| Printed wiring material, PD2, all groups except IIIb | 1.000 mm |
| General material, PD1, all material groups | 0.56 mm |
| General material, PD2, group I | 1.25 mm |
| General material, PD2, group II | 1.80 mm |
| General material, PD2, group III | 2.50 mm |
| General material, PD3, group I | 3.20 mm |
| General material, PD3, group II | 3.60 mm |
| General material, PD3, group IIIb | 4.00 mm |

This closes the earlier visual-QA question for the local 2020 base table. It
does not create a universal `250 V = 1.0 mm` rule. The applicable value depends
on printed-wiring status, pollution degree, material group, voltage definition,
insulation function, and the separate clearance requirement.

The table footnotes were also checked. Retain these restrictions:

- group IIIb is not recommended for PD3 above 630 V;
- high-voltage values marked `c` are provisional extrapolations;
- bracketed values are conditional rib reductions under 5.3.3.7;
- linear voltage interpolation is allowed under the cited clauses;
- the special printed-wiring PD2 column points to 5.3.3.8;
- footnote `a` changes the controlling RMS/working voltage according to
  insulation context and mains connection.

### IPC-7352 family-dependent courtyards

Representative rows on PDF pages 19-23 were visually checked. They confirm that
a universal Level-B courtyard is false:

| IPC family/table | Level A | Level B | Level C |
|---|---:|---:|---:|
| Table 3-1, flat ribbon/L/gull wing | 0.50 mm | 0.25 mm | 0.10 mm |
| Table 3-4, narrow rectangular/square end | 0.20 mm | 0.15 mm | 0.10 mm |
| Table 3-7, butt and I lead | 1.50 mm | 0.80 mm | 0.20 mm |
| Table 3-14, electrolytic/2-pin crystal | 1.00 mm | 0.50 mm | 0.25 mm |
| Table 3-15, small-outline flat lead | 0.20 mm | 0.15 mm | 0.10 mm |

The generic table values remain subordinate to the selected manufacturer's
package drawing and the assembly process. Manufacturing allowance is separate.

### IPC-7352 BGA Table 3-11

The percentage rows were visually confirmed:

- collapsing ball: A/B/C are 15%/20%/25% reductions below nominal diameter;
- non-collapsing ball, column, or solder bump: A/B/C are 15%/10%/5%
  increases above nominal diameter.

The courtyard row in the local PDF visibly prints:

`2.00 mm | 100 mm | 0.50 mm`

There is no decimal glyph in the middle cell. The earlier theory that OCR lost
the decimal was wrong: the anomaly is printed in the source itself.

Engineering context overwhelmingly suggests that `1.00 mm` was intended. A
KiCad KLC discussion independently describes the nominal BGA courtyard as 1 mm,
but no official IPC erratum or corrected licensed copy was located. Therefore:

- `100 mm` must not become a machine rule;
- `1.00 mm` must not be quoted as an unqualified IPC fact;
- if used temporarily, it must be labeled `inferred_typo_correction`, remain
  overridable, and be superseded by official or process-specific evidence.

### IEC COR1 status

The pinned IEC file does **not** incorporate COR1:2020:

- it was downloaded four months before the corrigendum;
- its front matter has no corrigendum/consolidation marker;
- it contains the original Figure G.1 (2 of 2).

The free COR1 was downloaded and inspected. It replaces informative Figure G.1
(2 of 2), a clearance-selection flowchart. It does **not** modify Table F.5.

The separate edition gap remains: IEC now lists
IEC 60664-1:2020+AMD1:2025 as current. AMD1:2025 was not available locally and
was not compared.

## Safe downstream disposition

1. Close the old visual-QA warning for the literal IEC 250 V base-edition row.
2. Keep the complete IEC applicability context; never reduce F.5 to one
   voltage-distance lookup.
3. Mark the local IEC hash `base_2020_without_COR1_or_AMD1`.
4. Attach the COR1 Figure G.1 replacement requirement.
5. Keep `AMD1:2025_not_compared` open for every safety-critical use.
6. Close the IPC extraction question: `100 mm` is printed, not OCR corruption.
7. Keep the intended BGA Level-B value unresolved at official-authority level.
8. Preserve IPC courtyard values by package family and density level.

## Primary records

- [IEC COR1 official record](https://webstore.iec.ch/en/publication/67718)
- [IEC 60664-1 current product record](https://webstore.iec.ch/en/publication/59671)
- [IPC document revision table](https://www.ipc.org/ipc-document-revision-table)
- [KiCad KLC issue discussing the nominal BGA courtyard](https://gitlab.com/kicad/libraries/klc/-/issues/44)
