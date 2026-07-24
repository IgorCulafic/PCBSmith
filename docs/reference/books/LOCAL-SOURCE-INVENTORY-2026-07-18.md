# Local source inventory audit - 2026-07-18

> **Later intake (2026-07-22):** Six additional user-supplied IPC documents
> were identity-checked, visually reviewed, normalized, and copied into the
> local Books collection. The collection now contains 1,488 files recursively,
> 147 PDF/EPUB documents, and 46 top-level documents. See
> `THIRD-WAVE-2026-07-22.md` for hashes, revision status, and authority limits.

## Scope and method

The audit enumerated `D:/AI/PCB designer/Books`, hashed the top-level source
files, inspected PDF metadata/text, and rendered representative cover pages for
visual identity verification. It did not treat filenames or table-of-contents
previews as proof that a full standard is present.

Inventory totals after the second intake and official downloads:

- 1,482 files recursively, most belonging to cached public source-code trees;
- 141 PDF/EPUB documents recursively;
- 40 top-level documents: 38 PDF and 2 EPUB;
- 52 documents beneath `Books/Public Sources`;
- 12 PDFs in the USB Type-C Release 2.5 bundle.
- 37 PDFs in the official USB 2.0 June 2025 bundle.

No duplicate was deleted. `Books/` and `.book-cache/` remain gitignored.

## Important correction

The user was correct that IPC-7352 had already been supplied. It was already
pinned and synthesized before this audit. A second top-level copy was added on
2026-07-18, but both files have identical SHA-256
`30df8d0d895dd79a956e05f50ce9b508fcca0d4b0a888cc4712a24fb92a9cb0a`.
It is the full 62-page IPC-7352, May 2023, not merely the public preview.

IEC 60664-1:2020 is also duplicated byte-for-byte. Both 171-page copies have
SHA-256
`438e2928531d898fad38f13fcd8b572fc3256defe83171fc063dda0b8f708f43`.

## Newly verified top-level additions

| Document | Verified identity | Pages | SHA-256 | Disposition |
|---|---|---:|---|---|
| `[IPC-2222 eng]...pdf` | IPC-2222 original, February 1998, *Sectional Design Standard for Rigid Organic Printed Boards* | 37 | `fe5a20495f3f2e62cd8266184ada50934465f9dd4460e3a4944a7eba1aa88c5c` | Full scanned original; OCR completed for all 37 pages. Useful historical/architectural input, but not IPC-2222A/B; rule-dense tables still require visual verification before promotion. |
| `[IEC 62368-1_2014]...pdf` | IEC 62368-1 Edition 2.0, February 2014, bilingual | 680 | `d04aa68aa8654a4c42cf3cd76f6cf65536356fc276eef81eaff378b2637016d4` | Full older edition; useful for proof-of-concept concepts and historical comparison, not a current compliance claim. |
| `IPC-2152.pdf` | IPC-2152, August 2009, *Standard for Determining Current Carrying Capacity in Printed Board Design* | 108 | `c81e39b9f6c157c48e6ff69ac649c89ff4ddad567188e301ec8bbe42ecf0ee13` | Full historical standard; now pinned for validation and provenance, but IPC lists it as no longer maintained. |
| `IPC-7093.pdf` | IPC-7093 original, March 2011, BTC design/assembly process | 124 | `55030b65c2ac1a41100c6bca43681a35a2793a462db64418f5708159bf4d3b57` | Full superseded original; retained for revision comparison. |
| `IPC-7093A.pdf` | IPC-7093A, October 2020, *Design and Assembly Process Implementation for Bottom Termination Components* | 136 | `c97ce895d9345a5e706ddb1b148b52120f4c8383be8930e30b4fc5f1d199449b` | Full current local BTC authority; identity visually and textually verified, pinned, not yet distilled/promoted. |
| `IPC-TM-650.pdf` | 1,034-page IPC-TM-650 test-method compilation snapshot supplied in 2016 | 1,034 | `ec475504f3c79a5eac3800c0b51d2a4b148e9fae1948f80317d827ce77602d95` | Full searchable compilation snapshot; every invoked method still needs its own revision/applicability check. |
| `IPC-2221A.pdf` | IPC-2221A, May 2003 | 124 | `dcaf0f1af2c624fee7ea9fefad99315420c3869da514b0467b790c226328a235` | Initially supplied under an IPC-2231A filename, then correctly renamed after cover inspection; full historical design standard. |
| `[IPC-7525 eng]...pdf` | IPC-7525 original, May 2000, *Stencil Design Guidelines* | 20 | `ae212fb1279b156715a35e6499358a5316dda4261d31e3335f83d9d35f54c62c` | Full scanned original, not revision C; OCR is currently partial (3 of 20 pages populated). |

## Automatically acquired official sources

After the user challenged the passive audit, Codex retrieved both freely
available primary sources instead of leaving them as wishlist items:

| Source | Official acquisition | Verified result |
|---|---|---|
| Sensirion SHT/STS design-in guide | `https://sensirion.com/media/documents/FC5BED84/662B494D/Sensirion_Humidity_Temperature_Design_Guide.pdf` | Version 2, March 2024, 21 pages; SHA-256 `b7db78c1e8a80000411c258b9a86b2c588fbf6ee5b315cc05c728f3ab2a20662`. Cover, metadata, text, thermal section, and PCB/housing scope verified. |
| USB 2.0 specification bundle | `https://www.usb.org/sites/default/files/usb_20_20250603.zip` | Official June 2025 bundle, 42 ZIP entries / 37 extracted files; archive SHA-256 `5fe9c53c04033818af396e8852b3acbca5c3a76ba92fab549fd81cd0ea7b3692`. Base Revision 2.0 PDF is 650 pages with SHA-256 `d39698a33486c399124af92bd02e4f978fd9a836b5cf4e52e6e4633eb1d89f61`; bundle includes accumulated errata/ECNs through April 2025. |

## Relevant source status

| Requested or important source | Local status | Assessment/action |
|---|---|---|
| IPC-7352 | **Full, current local base, pinned and synthesized** | No acquisition needed. Keep selected-part manufacturer geometry primary. Duplicate may be removed later only with explicit user approval. |
| IEC 60664-1 | **Full 2020 base, pinned and synthesized** | Suitable base for architecture; current safety work still needs AMD1:2025 comparison and applicable product standard. Duplicate present. |
| IPC-2222 | **Full original 1998 only** | Can support historical/mechanism work. Obtain current IPC-2222B only when the fabrication authority needs current contractual use. |
| IEC 62368-1 | **Full Edition 2.0, 2014 only** | Useful older product-safety source; do not claim current conformity from it. |
| IPC-7093A | **Full October 2020 revision present and pinned** | Paid-source gap closed. Distill only the BTC sections needed for SHT31/MPU6050 footprints, paste, voiding, exposed pads, thermal vias, inspection, and process profiles. |
| IPC-2152 | **Full August 2009 standard present and pinned** | Use for historical measured-data validation and comparison with Brooks/Adam. Do not collapse it into a universal equation or describe it as a maintained current standard. |
| IPC-2221C | **Preview only** | Valid 11-page TOC; full local authority remains IPC-2221B. |
| IPC-7351 | **Full original 2005** | Historical only; IPC-7352 and manufacturer data supersede it for current generic land-pattern work. |
| IPC-A-610 | **Full revision G, 2017** | Useful acceptance reference; current revision not present. It does not generate footprints or qualify an assembly process. |
| IPC-7525 | **Full original May 2000 scan present** | Revision C remains absent; the purported C preview is mismatched IPC-1401 content. Use the original historically until a current stencil-rule consumer justifies revision C. |
| IPC-2231A | **Not present in full** | Both the old TOC-labelled file and the newly supplied initial filename were misleading: the preview contains IPC-1401, while the full PDF is actually IPC-2221A and has been renamed accordingly. |
| Sensirion SHT/STS design-in guide | **Official Version 2, March 2024 downloaded and pinned** | Free-source gap closed. Distillation and integration into sensor declarations/checks remain open. |
| Espressif ESP32/ESP32-C3 hardware guides | **Present, pinned, distilled** | Current local generated PDFs dated 2026-07-06 are available. |
| USB Type-C Release 2.5 | **Full bundle present, pinned, targeted distillation complete** | Covers connector/interface mechanics; it is not the USB 2.0 signalling specification. |
| USB 2.0 specification | **Official June 2025 bundle downloaded and pinned** | Acquisition gap closed. The base Revision 2.0 and accumulated errata/ECNs are present; targeted signal-integrity extraction remains open. |
| JLCPCB/PCBWay selected-process capabilities | **Not pinned as a versioned fab profile** | High practical priority before claiming manufacturability against a selected supplier. |
| Archambeault, *PCB Design for Real-World EMI Control* | **Absent** | Valuable later; not the current integration bottleneck. |
| Ritchey, *Right the First Time*, vols. 1-2 | **Absent** | Valuable later for stackup/routing craft; defer until a live design gap calls for it. |
| Johnson, *High-Speed Signal Propagation* | **Absent** | Low priority until interfaces/rise times make it directly applicable. |

## Sufficiency decision

The older IPC-2222 and IEC 62368-1 copies are sufficient for current
proof-of-concept architecture, terminology, historical comparison, and
conservative review if their revision is always carried with the claim. They
are not sufficient for a statement that a future product complies with the
latest standard or a contractual customer/fabricator requirement.

The project should not pause for another broad acquisition wave. The Sensirion,
USB 2.0, IPC-7093A, and IPC-2152 acquisition gaps are now closed. The priority
is targeted distillation and production integration, plus exact selected-part,
fabricator, assembler, and 3D CAD evidence.

## Next intake actions

- [x] Download and pin the current official Sensirion SHT/STS design-in guide.
- [x] Download, extract, visually verify, and pin the official USB 2.0 bundle.
- [x] Register IPC-2222 original, IEC 62368-1:2014, IPC-2152, IPC-7093/7093A,
  IPC-TM-650, IPC-2221A, IPC-7525 original, Sensirion, and USB 2.0 in the local
  extraction manifest.
- [ ] Distill Sensirion and IPC-7093A into the sensor/BTC evidence model before
  promoting new numeric or process rules.
- [ ] Extract only the USB 2.0 signal/launch sections needed by a declared USB
  profile, including applicable ECNs from the 2025 bundle.
- [x] Complete OCR of all 37 scanned IPC-2222 pages; retain visual verification
  for any rule-dense table used by a promoted claim.
- [ ] Complete the remaining IPC-7525 OCR only when a named stencil-rule
  consumer requires it; 3 of 20 pages are currently populated and scan OCR is
  much slower than digital extraction.
- [ ] Quarantine or rename the mismatched IPC-2231A/IPC-7525C preview files so
  automated inventory cannot count them as valid sources.
- [ ] Build selected-fabricator and selected-assembler versioned profiles.
