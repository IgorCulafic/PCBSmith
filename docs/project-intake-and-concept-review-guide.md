# Project intake and concept-review guide

Use this sequence for every new board before schematic or PCB generation. The
purpose is to expose infeasible or ambiguous requirements without erasing the
recognizable spirit of the idea.

## 1. Preserve and structure the request

1. Save the original prompt and every supplied asset unchanged.
2. Transcribe it into the versioned project-brief schema.
3. Tag every value as `explicit`, `derived`, `assumed`, `decision_required`, or
   `conflict`, with source text and rationale where applicable.
4. Separate spirit anchors, engineering freedoms, and hard conflicts.
5. Do not call the brief accepted while any hard conflict remains.

The deterministic normalizer validates structured input. Human or AI extraction
from prose is allowed, but it is not deterministic authority and must retain
source spans and uncertainty.

## 2. Examine mechanics before electronics

Trace the supplied outline at its declared physical scale, then check:

- maximum dimensions and actual traced bounds;
- mounting-hole drill envelopes and edge distances;
- fixed connector bodies, pads, shell holes, and mating access;
- real footprint pad/hole, body, and courtyard envelopes;
- switch/keycap or control envelopes and intentional overhang allowances;
- board apertures, slots, keepouts, and artwork bounds;
- usable necks and plausible routing/component regions.

Red means an explicit required envelope is not feasible. Blue is an engineering
proposal, not an accepted rewrite. Yellow requires an assumption or has little
margin. Green indicates comfortable geometry within the checked scope.

## 3. Produce two complementary concept records

1. A spirit-preserving front/back visual for composition and product intent.
2. A dimensionally accurate front/back engineering overlay from the traced
   outline and actual geometry.

Use 4K overviews where practical and deterministic crops for dense or
mechanically critical regions. Back views must state whether they are mirrored
as an underside view. Store source hashes, physical transforms, status legend,
and findings beside the images.

The aesthetic concept is not dimensional authority. The engineering overlay is
not routing or fabrication approval.

## 4. Obtain explicit approval

Record the selected proposal and every resolved ambiguity. Bind approval to the
exact normalized-brief and concept-review hashes. Any change invalidates the
approval. Do not generate a schematic or PCB before this gate passes.

## 5. Continue through staged evidence

After approval, the intended stage order is:

1. circuit and evidence selection;
2. unrouted placement PCB;
3. automatic placement checks and 2D/3D review package;
4. pre-route capacity/failing-net diagnostic;
5. bounded routing with progress telemetry;
6. final ERC, DRC, design/semantic checks, model preflight, and visual package;
7. recorded inspection and user acceptance.

Each stage needs one generation identity. A failed later stage must not present
older artifacts as though they belong to the current generation. The common
transactional stage mechanism is still roadmap work; until it exists, mark the
project incomplete and stop on any mismatch.

## Retro-Pad pilot

Run the current pre-design slice with:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe tools\generate_retro_pad_predesign.py
```

It produces `outputs/retro-pad-r001/predesign/`. The existing PCB generator is
guarded by the pending hash-bound approval and must not be run until the user
resolves the documented mechanical and placement decisions.
