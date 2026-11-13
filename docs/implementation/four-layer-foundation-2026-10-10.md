# Four-layer software foundation — 2026-10-10

The user requested starting four-layer logic on October 10. This authorizes platform work now; it does not close the existing power, copper-stock or plating measurements. This phase implements and tests the copper-layer/routing/export foundation. **Ordinary four-layer publication remains blocked pending multilayer engineering qualification. No new build-ready board is delivered by this phase.**

## Implemented through shared owners

- `pcbsmith.copper_layers` defines physical order for one-sided, two-layer and four-layer routing. Four-layer order is F.Cu, In1.Cu, In2.Cu, B.Cu. Unsupported/incomplete stacks fail. The native one-sided format retains its unused B.Cu as before.
- The board serializer emits both inner copper declarations. Native readback now retains unused inner layers, and the four-layer SES importer checks the exact source and result stack order. Layer names remain authoritative across KiCad's old/new numeric layer IDs.
- Production request construction and predesign capacity use the declared layer count. Pinned Freerouting translation accepts an unrouted rectangular four-layer source and one declared F.Cu-to-B.Cu through-via technology, with copper shapes on all four layers. It rejects source/request layer mismatches instead of discarding inner layers. Legacy native A* remains limited to its existing one/two-layer research scope.
- Both the independent candidate validator and native import enforce the entire through-via span against per-net restrictions. Permission for F.Cu and B.Cu alone cannot authorize a via through forbidden inner copper. Native geometry checks model plated-pad, via and hole obstacles on inner layers as well.
- The visual owner generates mandatory separate In1.Cu and In2.Cu SVG/PNG profiles, unmirrored in front-view orientation. Combined-copper and holes/vias views include all layers. The manifest records the stack; audit binds it to the hashed native source and rejects missing inner views or a relabeled layer count. Legacy two-layer manifest serialization omits the new default field.
- The neutral manufacturing owner binds the ordered copper layers in the explicit fabrication stackup to the native board and requests every copper Gerber. X2 file-function attributes must identify one separate file for each physical layer; missing/duplicate/combined copper files fail. Four-layer packaging independently rechecks this coverage. The older fabrication shortcut directs four-layer work to the neutral owner.
- Surface laser CAM explicitly rejects multilayer boards, including a four-layer board with no routed inner traces. It cannot silently present outer-face artwork as a complete four-layer manufacturing package.

## Verification

Final regression run: **278 passed, 2 skipped, no warnings**, 51.13 seconds. The two skips are existing opt-in KiCad golden readback tests. The live four-layer test below ran separately. Tests cover existing one/two-layer routing, per-net restrictions, native geometry/readback, mandatory review, manufacturing, laser CAM, readiness and model-selection/input closure. Lint passes; mypy passes for all 14 changed/new source modules. Workflow audit passes with 213 classified callers and no changed/unclassified calls. Static caller classification is not board acceptance.

Retained evidence is under `outputs/four-layer-logic-2026-10-10/`:

- `regressions-final.xml`: final regression results.
- `workflow-audit.json`: shared-boundary audit.
- `native-proof-01/`: synthetic live interoperability test, exact commands, stdout/stderr, DSN, SES, imported PCB, DRC JSON, four copper Gerbers, Excellon drills and inner-layer SVGs.

The opt-in test `tests/integration/test_four_layer_native.py` used **KiCad 10.0.6 and pinned Freerouting 2.3.0**. It made one automatic routing invocation, capped at five passes and 60 seconds. The complete test passed in 21.58 seconds; the retained router log reports 0.29 seconds for its own job. It connected two nets using six segments and two through vias. One net is restricted to In1.Cu with no vias; the other connects front/back SMD contacts through declared vias. Both inner copper declarations survive native import and appear in Gerber exports. In2.Cu has no separately routed signal in this fixture; this is not a complex multilayer performance proof.

Native DRC reports **zero errors and zero unconnected items**. One warning remains: the flipped `D` test-point footprint differs from its installed library copy. The warning is retained in the result, not treated as a clean production DRC or waived manufacturing finding. The fixture has no schematic parity/ERC, production release, genuine visual acceptance or physical qualification claim. It is explicitly a software test, not an ordinary board job; no delivered board, board-job clock, approval or routing history was modified.

Imported PCB SHA-256: `63a3dc4008116ba0deb3dc7f3a9c710aabe3c5226e572fcecb87b763ff633d94`.

## Remaining work in this same agenda

The next implementation phase is the electrical-analysis path: extend the existing routed-copper graph and return-adjacency/reference-continuity contracts to include inner layers and source-backed stackup roles. Their existing outer-layer-only restrictions remain intact; this phase does not reinterpret them as multilayer approval. Inner-layer current analysis must not reuse the external-trace thermal model as qualification.

After those checks and inner-plane behavior are verified, run a real four-layer example through preparation, approved vector, automatic routing, native ERC/DRC/parity, actual visual inspection, release and mandatory handover. Use an explicit fabrication stackup and retain physical construction/lamination/plating and current/signal measurements as separate holds. Blind/buried/microvias, controlled-impedance claims, four-layer laser construction and manufacturing approval are outside this completed foundation phase.
