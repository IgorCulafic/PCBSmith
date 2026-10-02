# Production routing project-library scope — 2026-10-01

The repaired DualLaser1 coupon passed placement publication, 37 actual visual inspections and all 96 floorplan pose comparisons. Its routing invocation then failed before Freerouting launched: the production entry point resolved `LaserTest:PlatedGauge_D2p5_Drill0p8` outside the existing project-library scope. The exact same layout check already passed inside that scope in routing preparation. This was an integration failure, not a placement or routing-search failure.

`route_saved_placement_candidate` now keeps its full operation inside `project_footprint_scope(board.parent)`. Layout readback and downstream transactions use the retained project footprints. The existing resolver checks pinned hashes and restores its context after success or failure. No global asset installation, CAD change, rule relaxation, native-router fallback or job-policy change was made.

## Verification

- 96 targeted routing-policy, publication, asset, candidate-transaction, external-adapter and preparation tests pass, with no failures, errors or skips. Five new cases exercise real project footprint geometry and source closure around a synthetic transaction: success, transaction exception, geometric mismatch, asset tampering and source mutation.
- Ruff and mypy pass; the workflow audit passes for all 213 classified callers. The change remains within the existing production routing boundary.
- The coupon's exact failed layout check was reproduced read-only, then passed with the existing resolver. PCB SHA-256 remains `e43b76e7ef44d1d37771984d71ec7eb52acb199228391d31777e6aad93ff9c84`.
- One initial test failed because its synthetic return value lacked JSON serialization. The fixture was corrected; that result remains retained. An initial audit invocation used an unsupported command option, then the documented invocation passed.

The separate platform scope took **289.094 seconds** of its 1,200-second allowance. Evidence lives in `outputs/laser-next-tests-2026-10-01/routing-library-platform-completion.json`, `routing-library-regression.xml` and `workflow-audit-routing-library-final.json`. Tests do not claim an actual Freerouting execution or a completed coupon handover.

## Board disposition

The same coupon job retains the original failed NC candidate, the failed named-registration-net correction, the approved three-pad NC repair and all timing windows. Its completed diagnostic is `01-corner-plating-coupon/routing-diagnostic-completion.json`. The recovery was stopped through the shared owner after **32m03.687s**: **26m36.563s evaluation** and **5m27.124s execution**. Root end-to-end wall time at that stop was **1h16m52.115s**. These figures include preparation and the separately scoped platform work while the board window was still live; no time was relabeled.

The next production operation requires an explicitly authorized, hash-bound continuation on this same root. The PCB remains unrouted, with 12 expected pre-route opens and zero native ERC, geometric DRC or schematic-parity findings. No new drill/laser exports or manufacturing acceptance have been issued. The LED and timer examples have not started.

The earlier [two-sided CAM extension](two-sided-laser-cam-2026-10-01.md) and [native NC repair](native-no-connect-repair-2026-10-01.md) retain their separate results. None establishes physical electroplating, laser isolation or finished-hole qualification.

## Subsequent approved recovery — complete

The user explicitly approved the repaired routing attempt. The same-root run now connects all 12 nets in Freerouting in 4.719 seconds and completes final native, 37-view visual, eight-variant CAM, release and mandatory handover checks. The stopped disposition above describes the preserved predecessor, not current status. [Delivery, exact timings and remaining physical/new-board scope](duallaser1-coupon-completion-2026-10-01.md).
