# DualLaser1 coupon completion — 2026-10-01

The user's approved repaired-routing attempt completed on the original job root. Deliverable: `deliverables/DualLaser1-Corner-Plating-70x100.zip` (108 verified files), SHA256 `b909f5ba5ead7c12e81b0c1a03ec90654c06cebc84b7d7498514bb87c9936269`. PCB SHA256 is `20848f091f713e27a1033ca107a9c371de40f2e4d360da7da3a7a7934833e515`. The two-sided LED and timer examples have not started; this closes only the corner/plating coupon recovery.

## Result

- Pinned Freerouting 2.3.0 connected 12/12 nets in 4.719 seconds: 41 segments, 12 through vias, no zones or manual copper. The six-path corner bundle occupies the rear face with front probe escapes. Placement remains the approved NC-repaired source.
- Native ERC, geometric DRC, unconnected items and schematic parity are zero. All 37 final views were actually inspected; eleven SVGs replay pixel-identically to their viewed PNG counterparts. Accepted immutable generation: `production-final/generations/final-r001-inspected`. Dense probe F.Fab text overlap remains an explicitly recorded reference-drawing limitation.
- Eight source-bound laser variants pass native geometry/replay and genuine visual inspection: front/rear × 0.5/0.8 mm × isolated/locally cleared background. Conservative background separation is at least 0.507/0.807 mm. Functional conductor spacing remains the native 0.5 mm minimum; the wider background variant does not imply 0.8 mm between all nets.
- Excellon has 21 holes: fourteen 0.8 mm, two 1.0 mm, five 1.2 mm. Every tool/coordinate independently matches the native pad/via inventory. Native map plus local-coordinate CSV and 70 × 100 mm diameter reference accompany it. All sizes are pre-plating nominal drill sizes.
- Contact masks contain 27 front and nine rear native zero-expansion pad openings, excluding traces and via-only openings. SVG and 7000 × 10000, 2540 DPI PNG versions share the laser canvas. Rear laser and contact masks are already mirrored horizontally.
- Portable project dependencies, reviewed editable vector/preview, pinned InteractiveHtmlBom 2.11.2, manufacturing files, instructions and physical holds are included. iBOM exact lineage passes; browser interaction was not tested for this coupon.
- Shared release replay, required workflow audit (213 classified callers), mandatory `board-handover`, archive CRC and all file hashes pass. No new image or CAD operation is needed to close a physical hold.

## Retained failures and final evidence

Evidence root: `outputs/laser-next-tests-2026-10-01/01-corner-plating-coupon`. Final records are `acceptance/release-report-replayable.json`, `handover-request-replayable.json`, `handover-result-replayable.json`, `archive-verification.json`, and `job-finished.json`. Original job windows, NC failures, preflight failure and completed diagnostics remain unchanged.

The first post-route ERC/export source selection used the board-only routing generation; it lacked the complete schematic/project closure. The unchanged routed PCB was retained together with the exact preserved full project through the shared native-project owner, then verified and exported. Early standalone-project CAM is retained but superseded by `laser-variants-complete`. No copper or placement changed.

A separately scoped CAM identity correction makes `board_job.input_identity` consume the native-project closure already consumed by `laser_artwork`. Previously it hashed only the PCB, so exporting from the preserved full project was incorrectly rejected as identical input. Closure additions/changes now affect identity; byte-identical relocation, output-only changes and `.kicad_prl` do not. No ledger, timer, operation allowance or correction policy changed. The bounded platform scope took 139.269 of 600 seconds; 116 tests, Ruff, mypy and the 213-caller workflow audit pass. Exact scope/results: `cam-identity-platform-scope.json`, `cam-identity-platform-completion.json`, and the retained XML under the set root.

Final release input assembly also retained two failed bindings: the original route DRC was not the committed final DRC, and an otherwise passing report referenced the working-board path instead of the immutable generation-board path used by replay. Correct exact paths now pass the unchanged shared owners. No native checks or renders were repeated for those metadata corrections, and no positive evidence was fabricated.

## Timing and remaining scope

Approved recovery allowance: 45 minutes evaluation plus 20 minutes supervised execution, with six execution minutes reserved for verification. Finished recovery: **32m54.805s wall**, comprising **27m38.304s evaluation** and **5m16.500s execution**. Lifetime original-root wall time is **1h53m34.276s**, retaining previous failed scopes and waits. This is a successful authorized recovery, not a fresh-board original timing pass. Separate platform work performed during the live board window was not subtracted or relabeled.

Physical qualification remains with the user/operator: exact stock and laser settings; channel survival and isolation; front/rear registration; coating-mask alignment; pre/post-plating diameters, shrinkage and barrel continuity; purchased resistor fit and measured row resistance. The package records owners, methods, criteria, required inputs and exact revision. Test only with a meter at at most 1 V and 1 mA, one pair at a time. Finished plated-hole capability is deliberately unqualified pending measurements.

Next board work remains the two-sided LED crossing and timer/fanout examples. No job or vector preparation has started for either. CircleBlink remains separately available as unchanged `deliverables/CircleBlink.zip`: a circular six-LED arrangement on a 70 × 85 mm rectangular substrate, not a circular outline.
