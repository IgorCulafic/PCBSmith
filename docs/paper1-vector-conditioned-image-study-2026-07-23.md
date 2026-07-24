# Paper 1 study note: vector-conditioned PCB concept images

Date: 2026-07-23

Status: exploratory case evidence retained during ordinary development; not a
controlled experiment and not publication-ready comparative evidence

## Research opportunity

The reduced 8-channel USB-C protocol-analyzer pre-design exposed a useful
four-condition comparison for Paper 1, *Render Before Route*:

| Condition | Design aid available before implementation | Retained artifact |
|---|---|---|
| A | Text and constraints only; no planning image | `outputs/protocol-analyzer-8ch-predesign-r001/expanded-project-prompt.md` |
| B | Raster image generated directly from the image prompt | `outputs/protocol-analyzer-8ch-predesign-r001/concept/pure-generated-r001.png` |
| C | Deterministic SVG made from simple board, hole, component, pin, zone, and route-corridor primitives | `outputs/protocol-analyzer-8ch-predesign-r001/concept/vector-floorplan-r001.svg` and `.png` |
| D | Raster image generated with the deterministic vector render as an authoritative geometry reference | `outputs/protocol-analyzer-8ch-predesign-r001/concept/vector-assisted-render-r001.png` |

An additional corrected but still unconditioned raster is retained at
`outputs/protocol-analyzer-8ch-predesign-r001/concept/pure-generated-corrected-r002.png`.
It records the effect and limits of a text-only corrective iteration and should
not silently replace the first attempt in the study.

## Observed case evidence

### A. No image

The expanded text can state exact functional order, pin population, board
dimensions, and constraints. It cannot make the proposed placement immediately
scannable, and it provides no visual object against which a user can judge
composition, connector access, crowding, or recognizable product intent.

### B. Pure generated image

The direct raster communicated a plausible overall board quickly and made the
USB, MCU, input, and connector zones easy to discuss. It also produced defects
that cannot be trusted as engineering geometry:

- the first pass showed a USB pair that visually terminated before the MCU;
- input protection and buffers were ambiguous or represented by
  connector-like objects;
- bottom-side routes included disconnected-looking stubs;
- a corrective prompt improved several details but still depended on the image
  model to preserve ordering, pin count, mirroring, and connectivity.

These are useful findings because they are visible before CAD work, but the
raster remains presentation evidence only.

### C. Pure deterministic vector

The vector explicitly locks:

- the 88 x 50 mm preferred board envelope;
- four mounting-hole centers;
- USB-C, target-header, SWD, MCU, flash, oscillator, and front-end zones;
- exactly 20 target-header contacts;
- eight repeated channel corridors;
- the intended connector -> ESD -> series resistor -> input buffer -> MCU
  sequence;
- a same-orientation ground-reference X-ray convention.

The vector is reproducible, editable, hashable, and suitable for deterministic
anchor comparison. Its limitations are equally important: it is visually
abstract, its component geometry is provisional until exact footprints are
loaded, and it cannot prove pinout, copper legality, signal integrity,
protection performance, or manufacturability.

### D. Vector-conditioned generated image

The combined result preserved substantially more of the intended board
structure while adding a realistic PCB presentation:

- the two boards remained aligned and consistently oriented;
- the target connector retained 20 visible contacts;
- the eight-channel front-end visibly followed the intended stage order;
- the two quad buffers, SWD header, mounting holes, and functional zones
  remained recognizable.

The generated layer still drifted. It labeled the provisional oscillator
`24 MHz` instead of the intended RP2040-class `12 MHz`, and its displayed
copper remains illustrative rather than authoritative. This supports a
separation of roles:

> The vector is the geometry contract; the generated image is a review and
> communication layer; KiCad and independent checks remain implementation
> authority.

## Proposed controlled experiment

The retained examples are not enough to claim superiority. A defensible paper
experiment should:

1. freeze a set of unseen PCB briefs with comparable complexity;
2. run every condition from fresh contexts without cross-condition artifact
   leakage;
3. hold the language prompt, model, tool budget, time budget, and revision
   budget constant where applicable;
4. publish the exact inputs, prompts, model/tool versions, outputs, and hashes;
5. use independent reviewers or a blinded scoring process;
6. distinguish early concept defects from later schematic, PCB, ERC, DRC, and
   visual-review outcomes;
7. retain rejected and failed outputs rather than selecting only attractive
   examples.

Candidate measurements:

- board-outline and mounting-anchor displacement;
- connector location, orientation, pin-count, and boundary errors;
- component presence/absence and functional-order errors;
- channel-count and repeated-lane consistency;
- mirrored-side and camera-alignment errors;
- visually implied open, crossed, or impossible connections;
- user-rated concept comprehension and preservation of intent;
- time to accepted concept;
- clarification requests and human interventions;
- implementation rework after concept acceptance;
- downstream compute and tool calls spent on concept defects;
- unsupported electrical or manufacturability implications.

The main comparison should report both communication quality and engineering
drift. A visually attractive result that changes connector population or
topology is not a better engineering concept.

## Relationship to other papers

- Paper 1 owns staged visual planning and the vector/raster review method.
- Paper 3 may reuse the vector as an early constraint condition when studying
  convergence, but should not duplicate the visual-quality experiment.
- Paper 4 may study whether the vector helps preserve intent during prompt
  refinement and feasibility negotiation.
- Paper 5 may treat image generation and vector generation as tool-access
  conditions, while keeping the scoring oracle independent.

## Claim boundary

This study does not establish electrical correctness, routability,
manufacturability, or model-independent performance. The generated images do
not verify traces or pinouts. The vector becomes dimensionally meaningful only
after its primitives are derived from exact board and footprint geometry.
