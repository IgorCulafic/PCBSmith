# Connected functional schematic presentation

Implemented the first user-requested presentation slice in the shared native
project owner. New preparations can render editable functional regions with
titles, wrapped explanations, real local wiring, branch junctions and labels
between regions. This is an explicit presentation of reviewed circuit intent;
it does not infer a circuit or automatically place its symbols.

## Implementation

- `native_project.NativeProjectSpec.schematic_presentation` accepts blocks and
  wires through `schematic_presentation.SchematicPresentation`.
- Each block declares an ID, title, explanation, exact component membership
  and sheet bounds. Every project component belongs to exactly one block.
- A wire references real `(reference, pin)` endpoints and optional orthogonal
  waypoints. Both endpoints must be on the same declared net and in the same
  block. Same-net pins within a block must be geometrically connected.
- The compiler normalizes overlapping same-net segments and splits branches
  at actual junctions. Different-net crossings/touches, accidental NC contact,
  diagonal/zero-length segments, invalid endpoints, backwards pin entry and
  wiring outside the block/through its annotation region are rejected.
- Labels name the exact existing nets. Open stubs terminate at labels; local
  net labels prefer wire space away from pins and use left/bottom alignment.
- Optional symbol rotations and reference/value positions support presentation
  without changing PCB placement. Electrical pin positions rotate with symbols.
- New default fields are omitted from serialization. Legacy specification
  identities and the old labelled-stub rendering mode remain available.

The compiler is pure: no files, board-job state or acceptance records are written.
The existing guarded `prepare_native_project` resolves actual symbol pins,
prevalidates the presentation before creating output, emits the native schematic,
upgrades its format and verifies native XML against the full declared circuit.
The board workflow audit still finds the same 213 classified callers; no new
producer boundary, manual PCB router or bypass was added.

## Verification and inspected example

The retained run is `outputs/schematic-presentation-2026-10-21/`.

- **66 focused tests passed**, including native input closure, legacy identity,
  geometry fault controls and stable schematic object identity.
- The real KiCad 10.0.6 demonstration compares labelled-stub and connected
  versions of an eight-part power-input / divider-filter / indicator circuit.
  All exported component identities and per-net terminal sets agree.
- A PCB generated from the baseline is byte-identical when checked against
  the connected schematic. Native ERC: **0**; DRC violations: **0**;
  schematic/PCB parity findings: **0**. Its **12 unrouted connections are
  expected fixture scope**, not a routed-board completion claim.
- Actual native SVG export and the existing shared SVG rasterizer produced
  the final preview. It was viewed after the final native run: three readable
  titled regions, nearby wrapped notes, connected local circuits, visible
  junctions, references/values clear of the reviewed wires, and distinct input,
  filtered-output and LED-current paths. `visual-inspection.json` records exact
  artifact bindings and observations. The SVG retains the full drawing sheet;
  the PNG is a viewport of the circuit region.
- Ruff, focused strict mypy and the 213-caller workflow audit pass.
- Read-only replay of LogicBridge's retained specification serialization
  preserves its recorded SHA-256. Its CAD/job state was not changed or resumed.

Evidence: `tests-final.xml`, `workflow-audit-final.json`, and
`native-final/test_real_kicad_connected_shee0/evidence.json`, with native process
receipts and reports in that fixture's `checks/` directory. The earlier evidence
JSON's pending visual field is completed by the separate inspection record;
it was not retrospectively rewritten.

## Failures retained and corrected

The first combined run lacked its pytest temporary parent directory; its XML
retains 31 setup errors. An initial geometry negative test expected a later
crossing diagnostic even though an earlier pin-contact check already rejected
it; that fixture was corrected to isolate the intended condition. Native run 02
found one genuinely dangling stub because its label had been placed on the pin.
The compiler now labels open ends. Run 03 passed native checks but exposed an
incorrect direct rasterizer call; the test now uses the established shared
rasterizer. Actual visual inspection then caught labels crowding symbols and
the input connector reference touching a rail. Label placement/alignment and
the explicit fixture text anchors were corrected. Runs 04 and final passed;
all previous files remain retained.

## Supported scope and remaining work

The first slice uses one A3 sheet, existing single-unit native symbols, explicit
component positions, orthogonal wiring and separate functional regions. It
conservatively rejects different-net crossings even where a no-junction cross
could be legal. Power flags use compiler-verified anchors; explicit relocated
flag positions are not supported in this mode. Existing multi-unit symbol
restrictions are unchanged. Native end-to-end rotation coverage includes 0 and
90 degrees; all four right-angle pin transforms have unit coverage.

Rendered review remains necessary: this is not a general symbol-body/text
collision detector or a typography optimizer. Bounds checks reserve annotation
space, but do not prove every glyph or symbol shape is collision-free.
Explanations and calculated claims require real engineering review; presence
of text does not verify its truth. Native ERC retains the existing rule baseline
and omissions. No physical operation, part selection or manufacturing release
is claimed by this platform fixture.

Multi-sheet hierarchy, automatic graph layout, multi-unit adapters and universal
enforcement on every historical caller are outside this slice. Ordinary new
design preparation should supply the functional presentation intent; omitting
it intentionally retains compatibility behavior. Existing accepted boards are
not regenerated to change their appearance.
