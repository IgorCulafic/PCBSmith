# Two-sided build examples — October 4 completion

The user-authorized DualLaser2 LED crossing and DualLaser3 NE555 timer/fanout now have accepted CAD handovers and verified build packages. Routine engineering, recovery, inspection and exports proceeded under the user's instruction not to ask for expected board-building approvals. Original roots, failed attempts, diagnostics and continuation windows remain intact. No manual routing was used.

## Delivered scope

| Board | Native PCB SHA-256 | Routed copper | Holes | Pad-only openings |
| --- | --- | --- | --- | --- |
| DualLaser2 | `575371d5d13db83993df87d898b3250d17ef5f37f726dd41af046256886c418b` | 33 segments, 6 vias, Freerouting 3.532 s | 6 ×0.8 mm vias +3 ×1.2 mm registration | 17 front /3 rear |
| DualLaser3 | `1f578ae157e5aa05869d7962e98d99f1c73050af65f53f34404681306f1d974a` | 52 segments, 1 via, Freerouting 4.031 s | 1 ×0.8 mm via +3 ×1.2 mm registration | 29 front /3 rear |

Both are 70 × 100 mm, all purchased parts front SMD, with regulated 4.75–5.25 V input. LED board: external 10 mA limit. Timer: external 30 mA limit. LED crossings use rear copper; timer signal fanout is principally front-side with a rear ground connection. These are introductory builds, not a complex two-layer or 3–5 A qualification.

Each package contains four 0.5/0.8 mm front/rear retained-background copper-removal SVG/PNG variants; separate front/rear contact-only coating SVG/PNG; native Excellon drills/map and verified board-origin CSV; exact BOM; KiCad project/local symbol and footprint dependencies; pinned proxy 3D models; editable approved vector/preview; source-bound InteractiveHtmlBom 2.11.2; build instructions and verification results. PNGs are 7000 × 10000 at 2540 DPI; rear is already X-mirrored once. Native Excellon uses absolute KiCad origin: front laser X=drill X−20, front laser Y=−drill Y−20 mm. No native CAD bytes were changed during packaging.

Combined folder/ZIP: `deliverables/Two-Sided-Build-Boards-70x100` (202 verified files). Individual archives: `DualLaser2-LED-Crossing-70x100.zip` (97 entries), `DualLaser3-Timer-Fanout-70x100.zip` (103 entries). Open `START-HERE.html`, then each `BUILD-GUIDE.html`. Pad files are explicitly present under `Contact-Pads/front` and `Contact-Pads/back` in both full archives.

## Verification and limitations

Both exact current candidates pass native ERC, DRC, unconnected/parity checks, actual automatic-route validation, published readiness, 37 final artifact decisions after actual viewing (26 PNGs plus 11 independently replayed identical SVG pairs), final routed release and 17-role `board-handover`. The workflow audit passes 213 classified callers. All combined ZIP entries are byte-identical to the delivered folders. Guide local links pass. Interactive BOM generation and source lineage pass; browser interaction was not claimed or repeated.

Every contact polygon/circle was matched to native zero-expansion pad bounds within 0.003 mm, with no routing-via openings. All 9/4 native drill hits match Excellon position/diameter. All 8 isolation variants pass conservative actual-copper checks; front minimum separation from retained background is 0.506867/0.806867 mm, rear0.511896/0.811890 mm. Edge bands are 0.512/0.812 mm. Timer SOIC functional pad gaps remain 0.67 mm; 0.8 mm artwork is not a promise of 0.8 mm between fixed IC pads.

An automatic tool review rejected an initially templated batch of visual-decision records before execution. No such records were written. After the ten current contact sheets had been displayed and inspected, explicit per-view observations plus exact SVG/PNG equality bindings were retained; supported publication/inspection then succeeded. The final checks are genuine observations, not automatically generated approvals.

Physical holds remain with the builder: actual stock/copper thickness, 0.8/1.2 mm plating shrinkage and barrel continuity, two-face registration, coating-only opening alignment, exact part fit/polarity and powered behavior. Use the existing 0.8/1.0/1.2 mm plating coupon first. Each exact board's owner/method/criterion/inputs are retained in `delivery/Verification/physical-holds.json`. Nominal timer 1.02 Hz is a calculation, with provisional 0.4–2 Hz build-test screening; it is not measured operation.

## Retained corrections and shared adapter repair

LED: local J1/J2 reference labels moved 2 mm, unchanged component placement/netlist; one automatic route passed. Timer: corrected an inapplicable advanced oscillator-zone review decision while retaining RC timing review; an unnecessary refresh failed on a wrong input path and was preserved, then exact existing prepared sources were reused. Continuation allowance carried the previous deadline forward without renewal.

The timer's first automatic result exposed a shared SES-import/native-serialization precision defect: a 0.0001 mm redundant edge rounded to zero length. Separately scoped platform work added normalization only when the collapsed edge's serialized copper is completely covered by a retained same-net/same-layer segment. Uncovered collapsed copper still blocks. No new routing or manual copper geometry is invented. Import lineage records the normalization. The second and final automatic attempt passes native checks.

Changed shared files: `src/pcbsmith/kicad/freerouting_production.py`, its unit tests, and reviewed entrypoint classification. 26 focused tests and 76 broader relevant tests passed; actual retained import replay and final 213-caller audit pass. Separate platform scope: 20 minutes allowed, 224.611 s actual. Evidence: `outputs/platform-freerouting-rounding-2026-10-04/`. No Git commit or push was performed in this board task.

## Timing, without resets

| Scope | Wall | Evaluation | Supported execution |
| --- | --- | --- | --- |
| LED authorized continuation through archive verification/finish | 34m 30.653s | 24m 58.888s | 9m 31.765s |
| Timer final repaired continuation | 25m 57.376s | 21m 6.010s | 4m 51.366s |
| Timer all current continuations, including the retained refresh/routing failures and platform interval | 38m 27.709s | 32m 52.823s | 5m 34.886s |

Lifetime root wall: LED 36931.243s, timer 35334.613s, including the earlier work and user-wait interval. Neither is presented as an original timing pass. The original checkpoint measurements and all predecessors remain recorded. Exact timing snapshots are in each root's `acceptance/completion-timing.json`. Supported worker time alone counts as execution; other export, review and packaging time remains evaluation.

The next design phase remains a more complex two-layer power/control board targeting 3–5 A, qualified against measured copper, voltage drop, temperature rise and actual plating capability. Four-copper-layer work follows successful two-layer building and that complexity/power qualification; no new board root is started merely by this delivery.
