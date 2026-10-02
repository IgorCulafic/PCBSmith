# Two-sided laser CAM and controlled clearing comparisons

The user supplied a photograph and reported successful laser results on October 1, then requested wider isolation, a cluster of traces turning a corner with both retained and cleared background, and three progressively harder two-sided examples. Confirmed dimensions are 70 x 100 mm; isolation comparisons are 0.5 and 0.8 mm. Interconnect is electroplated through holes. The first coupon must compare 0.8/1.0/1.2 mm drilled holes; finished-hole shrinkage is not yet measured.

## Separate shared capability scope

Before beginning a new board job, `outputs/laser-next-tests-2026-10-01/platform-scope.json` records a finite 1800-second shared CAM scope. Existing boards, job histories and archives remain unchanged. The native router already handles two layers; the existing laser exporter and independent native-copper verifier were front-only.

The existing `pcbsmith.laser_artwork` owner now supports explicit two-sided exports for rectangular boards with straight tracks, front SMD components, ordinary plated through-hole lands and through vias. Native solid circles are handled as well as polygon/line geometry. Slots, offset drills, custom/removed-layer pad stacks, blind/micro vias, inner copper, arcs, zones and rear-mounted components remain rejected by the two-sided native check. Drilled-hole sizes are not a measured finished-hole guarantee.

Rear artwork is explicitly mirrored in X around the board centre for a **left-right flip**. Front and rear retain the identical full canvas. Full-clear rectangles are specified in unmirrored board-local coordinates; only floating background is removed, and native functional copper is preserved. The existing source-backed analytic copper enclosure independently checks the selected face and reverses the declared mirror before comparison. It does not infer physical qualification or electrical connection from an image.

`--variants FILE.json` exports 1–8 explicitly planned comparisons in one supervised CAM operation. Each has its own native process, exact source identity, SVG, geometry result and inspection obligation. This is an export set, not additional placement or routing attempts. The existing worker requirement applies to both the set and each child export. No new board-producing caller is introduced; the 213-entry audit remains unchanged and passes.

Mandatory handover replays every `isolation_cam*` role. The primary role remains unmirrored F.Cu. Additional roles require `isolation_variants` entries containing `manifest`, `inspection`, `copper_layer` and `mirror_x`. A two-sided set must include both front and mirrored rear artwork. Each native process layer/scale/drill-display setting, geometry receipt, source identity and actual visual decision must match. Every additional role is part of the reviewed mandatory deliverable inventory.

## Verification and retained boundaries

The focused laser, recurring-handover, mandatory-review and manufacturing-lineage suite passes **111 tests**. New controls include asymmetric face/flip rejection, changed layer/source/region/inspection rejection, drill/annulus/layer-stack failure cases, exact region-only background clearing, bounded comparison-set validation, and real KiCad F.Cu/B.Cu export and replay from unchanged DuoFilter. The initial tests exposed a synthetic multipolygon fixture omission, a nested-drill diagnostic exception and missing native circle support; failures remain in the first test directory. The corrected suite, lint, type checks and producer audit pass. Original coupon, LED and blinker CAD handover requests all replay successfully.

This qualifies the scoped software extension and native export/replay path, not the requested new boards. New board jobs still require actual vector review, source-backed engineering/component reviews, automatic routing, native checks, visual decisions, native drill export, interactive BOM and final handover. Physical plating, registration and laser measurements remain with the user.

## Existing CircleBlink and first physical feedback

CircleBlink was omitted from the later three-board test archive but remains intact at `deliverables/CircleBlink.zip`, SHA-256 `b1444041e5401f1e9a3ef3253ee7e00231a393527a31e1b8f91f23fa274ec267`. All 39 manifest entries and their archived bytes verify. It is a 70 x 85 mm rectangular board with six LEDs on a circle and 0.8 mm isolation, not a circular substrate. This is a link to its unchanged previously accepted package; no new CAD approval is asserted.

The user photograph and qualitative report are retained in `outputs/laser-next-tests-2026-10-01/intake.json` with the photograph hash. The photograph appears consistent with the three-branch LED topology but does not establish the exact fabricated SVG revision, calibrated channel width, resistance, plating or powered operation. The report is recorded as qualitative success, without replacing outstanding quantitative acceptance criteria.
