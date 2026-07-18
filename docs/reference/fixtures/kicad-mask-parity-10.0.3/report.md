# KiCad 10 solder-mask parity probe

Date: 2026-07-15 (Europe/Budapest)  
Scope: local KiCad CLI/API behavior for solder-mask serialization and Gerber output.  
Safety insulation, creepage, clearance, material qualification, and regulatory claims are explicitly out of scope.

## Pinned environment

- CLI: `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe`
- `kicad-cli version`: `10.0.3`
- Windows file version: `10.0.3.49839`
- Product version: `10.0.3`
- File size: `2,696,544` bytes
- CLI SHA-256: `4E1910666330FA8F2321D4E616957DACAB218A0D835C343C869A87757481C2F4`
- Gerbers were exported with `pcb export gerbers --layers F.Mask,B.Mask --no-protel-ext --no-x2 --no-netlist`.
- Generated Gerbers declare metric units (`MOMM`), 4.6 coordinates (`FSLAX46Y46`), and negative solder-mask polarity.

The reproducible fixtures, commands, Gerbers, DRC reports, parsed measurements, and hashes are under `.tmp/kicad-mask-parity-probe/`. `commands.ps1` records the successful export/API commands. `measurements.json` contains parsed aperture definitions and flash coordinates. `hashes.sha256` covers every retained artifact except itself.

## Supported findings

### 1. Global expansion belongs to the board

The accepted board syntax is:

```scheme
(setup
  (pad_to_mask_clearance 0.2)
)
```

In the fixture, a 2.0 mm circular pad without a local override exported as a 2.4 mm circular opening. Removing `pad_to_mask_clearance` reduced that opening to 2.0 mm even when the associated project declared `solder_mask_clearance: 0.7`.

This is the project syntax found in installed KiCad 10 projects and tested with both the minimal fixture project and a complete installed-demo project skeleton:

```json
{
  "board": {
    "design_settings": {
      "rules": {
        "solder_mask_clearance": 0.7,
        "solder_mask_min_width": 0.3
      }
    }
  }
}
```

The keys are below `board.design_settings.rules`; putting them directly below `design_settings` is not the KiCad 10 project structure.

For the tested CLI Gerber path, the board's `pad_to_mask_clearance` was authoritative for aperture expansion. The two project rule values did not change plotted aperture geometry.

### 2. Standard pad aperture geometry is an exact planar offset

The following apertures were read directly from `probe-base-F_Mask.gbr` outputs. Dimensions are millimetres.

| Copper pad | No pad override; global +0.2 | Pad-local +0.4 | Pad-local +0.1 |
|---|---:|---:|---:|
| Circle 2.0 | circle 2.4 | circle 2.8 | circle 2.2 |
| Oval 4.0 x 2.0 | oval 4.4 x 2.4 | oval 4.8 x 2.8 | oval 4.2 x 2.2 |
| Rect 4.0 x 2.0 | roundrect 4.4 x 2.4, r=0.2 | roundrect 4.8 x 2.8, r=0.4 | roundrect 4.2 x 2.2, r=0.1 |
| Roundrect 4.0 x 2.0, native r=0.5 | roundrect 4.4 x 2.4, r=0.6 | roundrect 4.8 x 2.8, r=0.7 | roundrect 4.2 x 2.2, r=0.55 |

Consequences:

- Expansion is applied to every edge.
- A sharp rectangle becomes a rounded offset shape; its new corner radius equals the positive expansion.
- A roundrect's effective radius increases by the same offset.
- A non-zero pad-local `(solder_mask_margin X)` replaces the board global value; it is not added to it.
- Explicit `(solder_mask_margin 0)` behaved like inheritance and used the global +0.2 value.
- `(solder_mask_margin -0.2)` overrode the global value and shrank a 2.0 mm circle to 1.6 mm.

### 3. `solder_mask_margin_ratio` is unsupported in this version

Adding the following pad field caused KiCad CLI 10.0.3 to exit with code 3 and `Failed to load board`:

```scheme
(solder_mask_margin_ratio 25)
```

The retained failing fixture is `probe-invalid-ratio.kicad_pcb`; the captured CLI output is `invalid-ratio-cli.txt`. The installed KiCad libraries contained `solder_mask_margin` examples but no `solder_mask_margin_ratio` examples. A serializer targeting KiCad 10.0.3 must not emit this field.

This finding is specific to the solder-mask ratio name. KiCad has separate solder-paste ratio behavior, which this probe did not test.

### 4. Mask layer membership controls each side

For SMD pads, omitting `F.Mask` or `B.Mask` suppressed the corresponding opening. For through-hole pads at y=55:

| Pad coordinate | Layers | F.Mask flash | B.Mask flash |
|---:|---|---:|---:|
| x=60 | `"*.Cu" "*.Mask"` | yes | yes |
| x=70 | `"*.Cu" "F.Mask"` | yes | no |
| x=80 | `"*.Cu" "B.Mask"` | no | yes |
| x=90 | `"*.Cu"` | no | no |

All enabled openings used the board/pad expansion rules. No implicit opposite-side opening was added.

### 5. Via tenting is side-specific and tri-state per via

Accepted board-global syntax includes both forms:

```scheme
(setup
  (tenting front back)
)
```

```scheme
(setup
  (tenting
    (front no)
    (back no)
  )
)
```

Accepted per-via syntax is:

```scheme
(via
  ...
  (tenting
    (front yes|no|none)
    (back yes|no|none)
  )
)
```

Meaning proven by Gerber output:

- `yes`: tented; no opening on that side.
- `no`: open; an opening is emitted on that side.
- `none`: inherit the board setting.

With board default/fully tented, the exact matrix for the five 2.0 mm vias was:

| x | Per-via front/back | F.Mask | B.Mask |
|---:|---|---:|---:|
| 10 | `none / none` | no | no |
| 20 | `yes / yes` | no | no |
| 30 | `no / no` | yes | yes |
| 40 | `yes / no` | no | yes |
| 50 | `no / yes` | yes | no |

With board-global `no / no`, x=10 (`none / none`) opened both sides, proving inheritance. The explicit states retained the same side-specific behavior.

A via with no `tenting` field and no board-global tenting block was tented on both sides in `probe-via-default.kicad_pcb`. Open 2.0 mm vias exported as 2.4 mm circles under global +0.2, so the mask opening followed via copper size, not drill diameter.

### 6. A real footprint flip changes more than the footprint layer

The hand-authored front counterpart and bottom footprint showed that mask apertures remain in common board coordinates and are plotted only on the side named by pad layers.

For a stronger check, the installed KiCad 10.0.3 Python API loaded `probe-base.kicad_pcb`, selected `F-Rot-Probe`, and executed:

```python
fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
```

KiCad serialized these changes in `probe-api-flipped.kicad_pcb`:

- footprint layer `F.Cu` -> `B.Cu`;
- pad layers `F.Cu/F.Mask` -> `B.Cu/B.Mask`;
- pad angle 0 degrees -> 180 degrees;
- pad angle 30 degrees -> 150 degrees;
- reference/value display layers and mirroring were also changed by KiCad.

The bottom Gerber's oval macro reflected the mirrored 150-degree axis. Therefore a serializer must perform the full side flip—side-sensitive layer swaps plus mirrored pad/graphic geometry and orientation. Merely changing the footprint layer is not equivalent to a KiCad flip.

### 7. Project minimum mask web did not alter the CLI plot

Two 1.0 mm circular pads used global +0.2 openings, yielding two 1.4 mm openings whose edge-to-edge mask web was 0.1 mm. The output remained two separate flashes for project `solder_mask_min_width` values 0.0 and 0.3. After removing creation date and project-ID metadata, the relevant Gerber geometry was identical. CLI DRC also emitted no solder-mask violation for this pair.

The practical conclusion is narrow but important: do not assume `.kicad_pro` minimum-web metadata will merge apertures or enforce a manufacturable web in `kicad-cli pcb export gerbers`. PCBSmith needs an explicit geometry check and Gerber-parity test if it promises a minimum web.

## Ambiguous or unverified items

- The GUI's use of `.kicad_pro` mask rules outside this CLI export/DRC path was not tested. The project keys should not be called ineffective in every KiCad workflow; only their lack of effect on these CLI outputs is proven.
- `allow_soldermask_bridges_in_footprints` interaction with project minimum web was not isolated.
- Custom pads, mask-only graphics, polygons, and text were not probed.
- Blind/buried vias, microvias, covering, plugging, filling, and capping were not probed.
- The collapse/removal threshold for very large negative margins was not probed.
- No claim is made for KiCad versions other than the pinned 10.0.3 binary.

## Recommended profile and serializer fields

Use explicit semantic fields rather than one overloaded mask number:

```text
SolderMaskProfile
  global_expansion_mm: nonnegative float
  minimum_web_mm: optional nonnegative float
  allow_bridges_in_footprints: bool
  default_via_front: TENTED | OPEN
  default_via_back: TENTED | OPEN

PadMaskSpec
  front_enabled: bool
  back_enabled: bool
  margin_mm: optional float

ViaMaskSpec
  front: INHERIT | TENTED | OPEN
  back: INHERIT | TENTED | OPEN
```

Serialization mapping:

- `global_expansion_mm` -> board `(setup (pad_to_mask_clearance ...))`.
- `minimum_web_mm` -> project `board.design_settings.rules.solder_mask_min_width`, but also enforce it in PCBSmith geometry; do not claim CLI plot enforcement.
- pad side enablement -> exact inclusion/omission of `F.Mask` and `B.Mask` in `(layers ...)`.
- pad non-zero `margin_mm` -> `(solder_mask_margin ...)`; absence/zero inherits board global in the tested KiCad version.
- via `INHERIT/TENTED/OPEN` -> `none/yes/no` respectively.
- do not emit `solder_mask_margin_ratio` for KiCad 10.0.3.
- implement footprint flip as a geometry/layer transform, with KiCad API-generated fixtures retained as goldens.

For exact mask-web checking, construct the final per-side aperture geometry after inheritance and local overrides, union openings, and measure residual mask regions. Golden tests should compare normalized F.Mask/B.Mask Gerber geometry, not only source S-expressions.
