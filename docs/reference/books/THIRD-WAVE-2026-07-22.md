# Third local standards intake - 2026-07-22

## Outcome

Six user-supplied PDFs were copied from `C:/Users/igori/Downloads` into the
gitignored `Books/` collection. The source files in Downloads were preserved.
Each destination was byte-for-byte verified by SHA-256 after copying.

The filenames were normalized to carry the document identity, revision, year,
and draft status. Drafts and superseded revisions are useful research and
revision-comparison sources, but they must not outrank current final standards,
exact manufacturer data, or the selected fabricator/assembler process.

## Verified additions

| Local filename | Verified identity | Pages | SHA-256 | Authority disposition |
|---|---|---:|---|---|
| `IPC-7251-working-draft-1-2008.pdf` | IPC-7251, *Generic Requirements for Through-Hole Design and Land Pattern Standard*, first working draft, June 2008 | 58 | `5c5e6e83a8e0487af83d2083405a8bf5311edaf5b1d1ab2f0476db2f34cbcdfc` | Draft-only historical source. Useful for through-hole land-pattern terminology, equations, process/courtyard considerations, and comparison with IPC-7352. Never cite as a released standard. |
| `IPC-6013D-2017.pdf` | IPC-6013D, *Qualification and Performance Specification for Flexible/Rigid-Flexible Printed Boards*, September 2017 | 80 | `613a8a033ba0c14099da35ffd21c5cc66992aca8c66b6eb76588b1ce18587e25` | Complete superseded revision. Useful for flex/rigid-flex qualification research and revision comparison. IPC currently lists IPC-6013E as the current revision. |
| `IPC-2221B-working-draft-2-2007.pdf` | IPC-2221 Revision B, second working draft, June 2007 | 138 | `7a3ace17852d6b62aa7d3e17add12938c6ba3c865b0031ea5136d5d59f3f43bb` | Draft-only historical source. The Books collection already contains the final 184-page IPC-2221B, SHA-256 `aab1225c227028819ddda3503519a8b4b117b10e1687ce29835ab975bb2a39ac`; that final copy remains the local revision-B authority. |
| `IPC-standards-tree-2016.pdf` | IPC Standards Tree, April 2016 | 1 | `d34f3807ebe46b1532f537a056feb8cca65b15a8dfbaa5a3467c918f9ea44067` | Historical taxonomy and discovery aid only. It is not a revision-status authority; every listed standard still needs a current official check. |
| `IPC-6012C-2010.pdf` | IPC-6012C, *Qualification and Performance Specification for Rigid Printed Boards*, April 2010 | 60 | `96d1b7cbf9fa7499084571131db3fec1698143e83d5e0fd83d41eefeb4f58f43` | Complete superseded revision. Useful for historical rigid-board qualification and revision comparison. IPC currently lists IPC-6012F as the current base revision. |
| `IPC-2226-original-2003.pdf` | IPC-2226 original, *Sectional Design Standard for High Density Interconnect (HDI) Printed Boards*, April 2003 | 57 | `0ae14bb4a3b8e9a7fa42c945cd8d3f822ea9a76f062da8f89ee2cb2a5e0c0f9b` | Complete scanned original. Useful for HDI architecture and historical comparison; OCR is absent. IPC currently lists IPC-2226A as the current revision. Rule-dense pages require visual inspection until targeted OCR exists. |

## Collection totals after intake

- 1,488 files recursively under `Books/`;
- 147 PDF/EPUB documents recursively;
- 46 top-level documents: 44 PDF and 2 EPUB;
- no exact duplicate among the six new payloads;
- no original Downloads file removed or renamed.

## Effect on the advanced-source gaps

- **IPC-2226:** the collection now has a full original revision, so HDI concepts
  and historical tables can be researched locally. IPC-2226A remains absent and
  is still the preferred current source before production rule promotion.
- **IPC-6012:** the collection now has revision C. This improves historical
  rigid-board qualification coverage, but it does not close the IPC-6012F gap.
- **IPC-6013:** revision D provides meaningful flex/rigid-flex coverage. Revision
  E remains the current-revision acquisition candidate only when a live flex
  project justifies it.
- **IPC-7251:** the draft is valuable for through-hole land-pattern research,
  but released IPC-7352 and exact component/manufacturer geometry remain the
  preferred current authorities.
- **IPC-2221:** the working draft adds revision-development history but does not
  improve current authority because final IPC-2221B is already local.
- **IPC Standards Tree:** useful for source discovery, but the 2016 snapshot
  must not drive present-day revision claims.

## Next use

Do not OCR or distill all six documents wholesale. Use targeted sections when a
named consumer appears:

1. HDI stack-up, microvia, capture-land, and escape rules from IPC-2226.
2. Flex/rigid-flex bend, material, via, transition, and qualification context
   from IPC-6013D.
3. Rigid-board performance and acceptance context from IPC-6012C.
4. Through-hole land-pattern equations and process conditions from the IPC-7251
   draft, reconciled against IPC-7352 and exact lead/hole geometry.
