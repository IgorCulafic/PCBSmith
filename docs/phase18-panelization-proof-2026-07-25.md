# Phase 18 panelization proof — 2026-07-25

## Outcome

KiKit 1.8.0 panel generation and KiCad 10.0.3 panel DRC now have accepted live
proofs for regular and irregular boards. The proof runner retains the requested
and resolved KiKit configurations, exact panel and DRC files, tool evidence,
source/output KiCad project-rule hashes, and one atomic proof manifest.

Passing DRC is necessary but not a fabrication release. Tab strength,
depanelization stress, supplier process limits, coupon requirements, panel
utilization, and assembly-house approval remain separate authorities.

## Accepted proofs

| Proof | Construction | Panel SHA-256 | DRC SHA-256 | Proof fingerprint |
| --- | --- | --- | --- | --- |
| Retro-Pad 3x3 mouse bites | 2×1, full frame, four annotated side tabs per source board | `885935a3c55a7182cc4ae018fe81af4b06137c4f35c19df4f2dc25eb4dc6ae38` | `664a817d4f1fbacd861285d0035afe91de1803933f250cae8ca4a18a4ab41bea` | `9302cfd8aea80675e926e2e41ea7d7c574e5b15b89123432d77e6f73c4cd2b4b` |
| Lucky Clover mouse bites | 2×1, full frame, four annotated side tabs per source board | `466a3f0229e9d13d9db6870727ed921cc6de889166246222b319704646beca2a` | `78970d34c0d7a627f42fb3e91f2ed7531f210d666a1f0744de85475c6bfbdf1e` | `4e1fe964b48897a471879ba384bfed9c7d9b2c33e84fe99c6f56530886728815` |
| Retro-Pad 3x3 V-cuts | 2×1, zero board spacing, top/bottom rails | `b67c7c82a3735a0fa7ded0f8aa3aeb1ecace36e02efb02b1a52377b3f932146d` | `4e1b93838c6082c69341e291cbc7a2aa8dc6469a4391cb000b223e1d1d5bf353` | `f9abae637e88345849fa90a414c16c60e9dd22cbad4e6ea6be967b8fd501517f` |

All three reports contain zero violations, zero unconnected items, and zero
schematic-parity findings. No exclusions were introduced.

Local retained roots:

- `.pcbsmith/verification/phase18/accepted-panel-proofs-2026-07-25-r2`;
- `.pcbsmith/verification/phase18/vcut-proof-2026-07-25`.

These roots are intentionally ignored runtime evidence. The table above keeps
their identities auditable in version control.

## Visual inspection

Each accepted mouse-bite proof has top and bottom 1920×1080 orthographic
renders plus front/back SVG exports. The V-cut proof has a top render and front
SVG. Inspection confirmed:

- two complete, non-overlapping board instances;
- coherent outer panel outline and rail geometry;
- tooling holes separated from top/bottom fiducials;
- tabs located away from component courtyards and routed copper;
- mouse-bite holes confined to the intended breakaway lines;
- coherent front/back component and copper orientation; and
- a straight full-width separation line for the regular V-cut panel.

The translucent empty regions in the irregular 3D panel are routed-away panel
material, not missing board geometry.

## Retained failures and lessons

1. The first profiles inherited KiKit's zero tooling/fiducial offsets. Tooling
   holes, fiducial copper/mask, and the panel edge overlapped.
2. Generic spacing tabs were unsafe. On Retro-Pad R003 they crossed switch
   courtyards, long edge tracks, and ground pours.
3. Explicit tab anchors removed the placement failures, but R003 still has 16
   real hole-to-ground-pour clearance violations. R003 is therefore recorded as
   not panel-ready until its canonical board design includes depanel copper
   keepouts or another approved tab strategy.
4. Moving an annotated `.kicad_pcb` without its matching `.kicad_pro` caused
   KiCad to use different default track, clearance, edge, and library-mismatch
   rules. The adapter now refuses that incomplete authority and hashes the
   source and generated project files.
5. The original 2×2 full-frame V-cut attempt produced a self-intersecting
   outline. A process-appropriate 2×1 layout with top/bottom rails passes
   without weakening DRC.

## Remaining work

- generate and validate real impedance coupon geometry where a selected
  stack-up/process requires it;
- add supplier-specific tab, score, rail, tooling, and fiducial limits only
  through an approved manufacturing profile;
- complete the current-path and unsupported DFM/DFT evidence needed for the
  regular and irregular neutral-package proofs; and
- obtain fabricator/assembler approval only for an actual release package.
