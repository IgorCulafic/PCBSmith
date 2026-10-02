# TraceLimits coupon completion — October 2, 2026

The user requested thin and thick traces and five or six close neighboring traces around a corner. The new single-sided 70 × 100 mm coupon is delivered in `deliverables/TraceLimits-Laser-Coupon-70x100.zip`. Root: `outputs/laser-trace-limits-2026-10-01`. No shared platform source was changed for this board.

## Delivered geometry and evidence

- PCB SHA256: `effaf7f76cc40f310267b2dd8447720c1cc12c712776f76845aabae1184c0650`.
- ZIP SHA256: `6bd7f214751846e636d7774cb0108371c4c7b3fe67d41aea07b31caff52fd7e9`; 81 entries, all 80 payload hashes plus the checksum inventory verified.
- Eight 50 mm center-span straight tracks: 0.15, 0.20, 0.25, 0.30, 0.40, 0.60, 0.80 and 1.00 mm. Six corner nets: 0.15, 0.20, 0.25, 0.30, 0.40 and 0.60 mm. Measured adjacent-track minimum gaps: 0.20 mm. All six share the close horizontal run; five follow the full parallel bend. The 0.60 mm inner path includes an extra branch/turn connecting its integral anchors. This is a width/corner test, not a gap ladder.
- One initial pinned Freerouting 2.3.0 run, 4.532 seconds, all 16 nets connected, 46 front segments, no vias, holes or manual copper. Native ERC/DRC/opens/parity zero. Optional 1206 2.2 kΩ reference resistor; bare trace tests require no parts. J references are etched features.
- Editable dimensioned vector and preview were inspected before placement. All 196 placement comparisons matched. Actual final visual inspection covers 37 artifacts; 11 SVG replays are pixel-identical to inspected PNGs. Reference-only F.Fab probe values overlap; actual silkscreen is readable and native silk checks are clear. No further optional polishing.
- Four laser variants: 0.5/0.8 mm surrounding isolation, each with channel-only or cleared-corner background. Conservative actual surrounding minima are 0.507195/0.807195 mm. Functional trace gaps remain 0.20 mm. Clear window is board-local x 7–54, y 52–90 mm.
- Four machine SVGs and 7000 × 10000 PNGs, 2540 DPI; 70 × 100 mm front-side, unmirrored, black removes copper. Thirty-two native-matched contact openings have separate coating SVG/PNG; eighteen integral anchors are excluded. Pad geometry, scale and actual previews were checked.
- Portable KiCad symbol/footprint closure, pinned self-contained InteractiveHtmlBom 2.11.2 with producer lineage, Gerbers, native BOM, test guide and exact measurements included. Optional resistor 3D appearance uses the installed official KiCad proxy model. Browser interaction was not tested for this revision.
- Final immutable generation: `production-final/generations/final-r001-inspected`. Release, all 15 handover roles and requested isolation replays pass. Workflow audit passes (213 classified entries). Archive verification is retained in `acceptance/archive-verification.json`.

## Preserved failures and approved completion

Initial preparation used incorrect CLI flags before work and was corrected using positional arguments. The first vector exposed an inappropriate generic body-envelope fallback for tiny bare-copper anchors; explicit copper-size courtyards with 0.025 mm margins corrected it without changing pad sizes or intended positions. Both correction cycles remain in the same ledger. One R1 reference label overlapped the meter legend; an accepted annotation-only local edit moved it below the resistor. Pre-route opens were honestly retained until routing. No automatic-routing retry was needed.

One laser-worker invocation was rejected because the final render worker still owned the job; no CAM work began. The later sequential invocation passed. Final publication then rejected the standalone model-preflight claim: it omitted the approved applicability rationale. Shared `prepare_selected_board_models` replay showed the rationale was the only difference; model identities, transforms, PCB and images matched. A bounded diagnostic retained the proof and recommendation. The user explicitly approved completion with 20 minutes evaluation plus 10 minutes execution.

The first continuation request was rejected because the predecessor allowance was still active. The already approved corrected publication ran and passed under that original allowance. This ordering mistake is retained, not hidden. The predecessor was then closed using the shared cancel boundary and the approval was successfully recorded through `continue-authorized`, with exact predecessor and diagnostic hashes. No ledger edit, reset, reroute, rerender or board edit occurred during completion.

The corrected model request, failed preflight, original publication failure, diagnostic, approval requests and all earlier source/render generations remain retained. The final 37 inspection decisions are genuine observations of current hash-matching images, not copied approvals.

## Timing and remaining boundary

Original prospective allowance: 3600 seconds evaluation plus 1800 seconds execution, including 360 seconds verification reserve. The closed predecessor consumed approximately 33m34.716s evaluation plus 10m50.392s execution, 44m25.108s wall. Completion was separately authorized; no claim that it was an untouched initial workflow run.

Approved completion finished in 391.804 seconds wall: 389.586 seconds evaluation and 2.218 seconds contained execution. Uncontained exports, inspection and packaging remain evaluation. Lifetime root wall through verified archive and job finish: 3058.013 seconds (50m58.013s). Exact clocks are in `acceptance/finished-job.json`; all prior windows and counters remain intact.

Physical laser/coating survival and repeatability remain user-owned tests on the exact revision, stock and settings. Probe-pair criteria, raw measurements and microscope observations are requested in `TEST-GUIDE.html` and the handover physical hold. Neither CAD checks nor the prior photograph establish a repeatable minimum trace width. The separate two-sided LED and timer examples remain unstarted.
