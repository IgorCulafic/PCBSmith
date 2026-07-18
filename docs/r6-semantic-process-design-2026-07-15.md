# R6 semantic compatibility and process-scoped dual-side design

Date: 2026-07-15  
Scope: implementation design only. This document does not claim that R6 is
implemented, that the thermometer is thermally/RF validated, or that any
component is qualified for inverted second reflow.

> **Implementation status (2026-07-16):** R6.0 common semantic authority IR and
> the bounded, opt-in R6.1a thermal source/sensitive separation evaluator are
> implemented. R6.1a retains exact rational closest-point witnesses, composes
> bounded placement error, and permits a theta estimate only as an advisory when
> its complete operating scope matches. Sensor/moat construction and checking
> remain R6.1b; no general thermal simulation or product validation is claimed.

## Executive decision

R6 should add a versioned semantic-layout contract consumed by the lossless R5
candidate representation. It should answer two different questions without
mixing their authorities:

1. does the board geometry satisfy a declared, evidence-backed semantic layout
   constraint; and
2. does the selected assembly process permit the declared side assignment?

The first question covers thermal/sensor regions, module antenna/feed geometry,
decoupling loops, oscillator regions, switching hot loops, connector zones, and
return adjacency. The second covers inverted-second-reflow retention,
assembler-specific heavy-part restrictions, and package/class-specific
neighbor-overhang allowances.

R6 must not turn mechanism evidence or one experiment into a universal hard
gate. In particular:

- a sensor moat is a design candidate whose exact slot, web, tab, copper, and
  trace geometry comes from the selected fabrication/assembly context and whose
  performance is validated in the built enclosure;
- an antenna has module-specific feed, antenna, copper/part keepout, edge or
  cutout, and enclosure-clearance declarations; `15 mm` is not synthesized as a
  PCB keepout;
- the published SAC305/QFN mass-per-wetted-perimeter result remains an advisory
  only within its narrow experimental applicability; and
- package mass alone never creates a reflow blocker. Only an explicit
  assembler/process requirement with a qualification record can do that.

R6 findings therefore carry an authority class. Exact geometry can produce a
hard result when its source rule is hard and applicable. An advisory hypothesis
can rank or request review but cannot reject. A validation requirement stays
pending until its identified test record passes. A qualified assembler rule can
be hard only for the exact process/profile it qualifies.

## Evidence basis and limitations

This design uses the distilled conclusions in
`docs/reference/books/CONSOLIDATED.md` and
`docs/reference/current-materials-knowledge-base-2026-07-14.md`; it does not
reopen source books.

The useful evidence boundaries are:

- routed decoupling-loop geometry is first-order; raw XY capacitor proximity is
  a weak proxy;
- oscillator, hot-loop, connector-zone, and return-continuity mechanisms are
  well supported, but numerical thresholds remain device/interface/profile
  scoped;
- Espressif supports module antenna placement at/beyond the baseboard edge or a
  module-specific cutout. The final-housing/object clearance is separate from
  PCB copper geometry and final range/throughput testing remains required;
- Sensirion's official March 2024 humidity/temperature design guide supports
  distance from heat, low-metal connections, metal removal, slits, airflow
  shielding, and ambient-air coupling. Its cited humidity sensitivity example
  does not prescribe a moat width, bridge count, or slot pattern; and
- the SMTA SAC305 QFN experiment is primary but narrow: two QFN types, OSP,
  100 um stencil, no-clean SAC305, particular pads/void accounting, and a
  244 C peak. Its reported ratio and buffer are observations for that process,
  not a package-family rule.

Source limitations are machine-visible. A locally absent but official,
text-verified source can support an advisory or conditional declaration; it
cannot support a qualified hard gate that claims checksum-pinned figure
geometry. Figure-derived antenna or mechanical geometry needs a figure-bound
record with source revision, locator, units, transform/origin, and checksum.

## Relationship to existing profiles and R5

`PcbRuleProfile` remains the authority for fabrication geometry, ordinary
electrical spacing, and insulation. Do not add assembly, enclosure, thermal-
validation, or RF-performance meaning to that class.

Introduce separate immutable profiles:

```python
class SemanticLayoutProfile(SemanticIrModel): ...
class AssemblyProcessProfile(SemanticIrModel): ...
class EnclosureEnvironmentProfile(SemanticIrModel): ...
class ValidationCampaignProfile(SemanticIrModel): ...

class SemanticEvaluationContext(SemanticIrModel):
    pcb_profile_fingerprint: str
    semantic_profile: SemanticLayoutProfile
    assembly_profile: AssemblyProcessProfile | None
    enclosure_profile: EnclosureEnvironmentProfile | None
    validation_profile: ValidationCampaignProfile | None
```

R5 supplies a lossless probe, exact component transforms, routed candidate,
R2/R3/R4 telemetry, and final exact-check state. R6 evaluates the same candidate
object; it must not reconstruct a second `BoardLayout`, reroute nets, or use a
different pose transform. Placement-only semantic metrics may participate in
R5 Pareto screening. Routed semantic metrics are evaluated only after detailed
routing and can reject an otherwise algorithmically routed candidate when their
hard, applicable declarations fail.

Existing placement defaults and board generators remain unchanged. The first
R6 API is separate and opt-in:

```python
def evaluate_semantic_layout(
    layout: BoardLayout,
    netlist: BoardNetlist,
    declarations: SemanticLayoutDeclarations,
    context: SemanticEvaluationContext,
    *,
    placement_candidate_fingerprint: str | None = None,
) -> SemanticLayoutResult: ...
```

## Common typed authority and provenance

### Rule authority

```python
class SemanticAuthorityClass(StrEnum):
    HARD_GEOMETRY = "hard_geometry"
    QUALIFIED_PROCESS_REQUIREMENT = "qualified_process_requirement"
    ADVISORY_HYPOTHESIS = "advisory_hypothesis"
    VALIDATION_REQUIRED = "validation_required"

class SemanticVerification(StrEnum):
    EXACT = "exact"
    BOUNDED_APPROXIMATION = "bounded_approximation"
    UNSUPPORTED = "unsupported"

class SemanticDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ADVISORY = "advisory"
    UNVERIFIED = "unverified"
    VALIDATION_PENDING = "validation_pending"
    NOT_APPLICABLE = "not_applicable"
```

`HARD_GEOMETRY` means an exact/bounded geometric predicate backed by an
applicable component/fabrication/interface requirement. It does not mean every
geometric metric is hard. Hot-loop area, for example, is geometric but remains
an advisory minimization objective unless a scoped maximum is declared.

`QUALIFIED_PROCESS_REQUIREMENT` requires an identified assembler, process
revision, qualification record, covered package/board conditions, effective
date, and review identity. A generic web article, an internal preference, or a
paper alone cannot create this class.

`ADVISORY_HYPOTHESIS` records useful direction or a calibration model. Its
failure disposition is always `ADVISORY` or `UNVERIFIED`, never `FAIL`.

`VALIDATION_REQUIRED` identifies a test/simulation/inspection campaign. Before
the matching record passes it is `VALIDATION_PENDING`; geometry cannot
automatically promote it to pass.

### Provenance

Reuse `EvidenceRef` but add an applicability binding rather than overloading
human-readable locator text:

```python
class EvidenceApplicabilityBinding(SemanticIrModel):
    binding_id: str
    evidence: tuple[EvidenceRef, ...]
    claim_id: str
    required_conditions: tuple[str, ...]
    excluded_conditions: tuple[str, ...]
    matched_conditions: tuple[str, ...]
    unmatched_conditions: tuple[str, ...]
    geometry_source_fingerprint: str | None
    reviewer_record_id: str | None
```

Every threshold, polygon, role mapping, process limit, and validation target
references one or more binding IDs. A numeric value without a unit, source, and
applicability binding is invalid. A module-local polygon derived from a figure
also records local origin, axis convention, units, and source checksum.

### Geometry declarations

Use the exact planar compound and shared placed transform required by R5.
Geometry identities are local and versioned:

```python
class SemanticRegion(SemanticIrModel):
    region_id: str
    coordinate_space: Literal["board", "component_local"]
    owner_reference: str | None
    compound: ExactPlanarCompound | None
    layers: tuple[str, ...]
    verification: SemanticVerification
    maximum_error_mm: float | None
    source_binding_ids: tuple[str, ...]
```

Component-local regions transform with the exact front/back pose. Board regions
do not. `UNSUPPORTED` has no compound and cannot numerically pass.

## Semantic layout declarations

```python
class SemanticLayoutDeclarations(SemanticIrModel):
    schema_id: Literal["pcbsmith-semantic-layout"]
    schema_version: Literal[1]
    thermal_sources: tuple[ThermalSourceDeclaration, ...] = ()
    thermal_sensitive_regions: tuple[ThermalSensitiveDeclaration, ...] = ()
    sensor_isolation_candidates: tuple[SensorIsolationCandidate, ...] = ()
    antenna_modules: tuple[AntennaModuleDeclaration, ...] = ()
    decoupling_loops: tuple[DecouplingLoopDeclaration, ...] = ()
    oscillator_zones: tuple[OscillatorZoneDeclaration, ...] = ()
    switching_hot_loops: tuple[SwitchingHotLoopDeclaration, ...] = ()
    connector_zones: tuple[ConnectorZoneDeclaration, ...] = ()
    return_paths: tuple[ReturnPathDeclaration, ...] = ()
    side_assignments: tuple[SideAssignmentDeclaration, ...] = ()
    neighbor_overhang_rules: tuple[NeighborOverhangRequirement, ...] = ()
    evidence_bindings: tuple[EvidenceApplicabilityBinding, ...] = ()
```

All IDs are unique. Every component, pad, pin, net, and region identity is
validated against the netlist, component cards, and layout. Declarations are
topology/card facts; no checker guesses them from reference prefixes, footprint
families, or net names.

## Thermal sources and sensitive zones

### Declarations

```python
class ThermalOperatingPoint(SemanticIrModel):
    operating_point_id: str
    ambient_temperature_c: float | None
    component_dissipation_w: float | None
    duty_cycle: float | None
    airflow_description: str | None
    enclosure_state_id: str | None
    source_binding_ids: tuple[str, ...]

class ThermalSourceDeclaration(SemanticIrModel):
    source_id: str
    component_reference: str
    heat_region_id: str
    operating_points: tuple[ThermalOperatingPoint, ...]
    junction_limit_c: float | None
    thermal_model_id: str | None

class ThermalSensitiveDeclaration(SemanticIrModel):
    sensitive_id: str
    component_reference: str
    sensitive_region_id: str
    sensitivity_kind: Literal[
        "temperature_sensor", "humidity_sensor", "electrolytic",
        "crystal", "precision_analog", "other"
    ]
    maximum_local_temperature_error_c: float | None
    maximum_environment_temperature_c: float | None
    separation_requirements: tuple[ThermalSeparationRequirement, ...]
    validation_requirement_ids: tuple[str, ...]
```

A `ThermalSeparationRequirement` names source IDs, an exact region-to-region
distance threshold if one is actually declared, authority class, operating
point, and evidence binding. Without a declared threshold, R6 reports distance
and overlap as metrics and advisories only.

### Checks and metrics

Compute exact/bounded placed-region overlap and minimum separation for every
declared source/sensitive pair. Report the responsible closest points and
regions. If a qualified component or project requirement declares a distance,
the geometric check can pass/fail. Generic advice to separate heat sources
does not become a hidden distance.

Junction-temperature checks require a scoped thermal model, power/duty,
ambient, board construction, copper geometry, and enclosure/airflow context.
JESD51 theta values retain their test-board/environment identity and cannot be
copied as component constants. Missing context produces `UNVERIFIED` or
`VALIDATION_PENDING`, not a temperature number.

Placement metrics include source/sensitive distance matrix, overlapping thermal
regions, predicted temperature/error only when a qualified model exists, and
validation coverage. They may rank R5 candidates, but an unmodeled greater
distance is not automatically a validated thermal improvement.

## Sensor isolation and moat candidacy

### Candidate declaration

```python
class SensorIsolationCandidate(SemanticIrModel):
    candidate_id: str
    sensor_reference: str
    sensor_sensitive_region_id: str
    ambient_access_region_ids: tuple[str, ...]
    heat_source_ids: tuple[str, ...]
    slot_region_ids: tuple[str, ...]
    retained_web_region_ids: tuple[str, ...]
    support_tab_region_ids: tuple[str, ...]
    copper_removal_region_ids: tuple[str, ...]
    allowed_bridge_net_names: tuple[str, ...]
    bridge_trace_ids: tuple[str, ...]
    assembly_support_requirement_ids: tuple[str, ...]
    enclosure_air_path_id: str | None
    thermal_validation_requirement_id: str
    humidity_validation_requirement_id: str | None
    source_binding_ids: tuple[str, ...]
```

The candidate does not contain a default slot width or bridge geometry. Exact
slot/cutout polygons live in typed board-cutout geometry. Webs and tabs are
positive laminate regions, not inferred as whatever remains after subtracting
raw Edge.Cuts strings.

### Fabrication and assembly inputs

The selected fabrication/assembly profiles must declare, when applicable:

- supported routed/milled/etched slot type and minimum finished tool/slot
  dimensions;
- minimum residual web, minimum internal radius, positional tolerance, and
  allowed tab/web construction;
- copper-to-routed-edge and hole/slot constraints on every affected layer;
- solder-mask behavior at cut edges;
- panelization, depanelization, handling, fixture, and assembly support limits;
- whether the isolated tongue can survive paste printing, placement, reflow,
  cleaning, handling, and connector/enclosure loads; and
- any assembler-required support tabs, carriers, or forbidden geometries.

These are profile data with manufacturer/process IDs and evidence. A convenient
router diameter is neither a Sensirion requirement nor a validated design.

### Geometry checks

Hard fabrication checks may verify:

- each slot/cutout is exact, simple, manufacturable, and satisfies the selected
  profile's scoped minimums;
- retained webs/tabs meet declared structural geometry;
- copper removal covers the declared layers and preserves required edge
  clearances;
- only declared bridge nets cross the isolation boundary;
- bridge traces/vias stay within selected width/count/copper budgets when such
  budgets are declared; and
- no accidental zone/pad/via/track creates an undeclared thermal bridge.

Use exact copper, filled-zone, hole, and cutout geometry. Unknown zone fill or
opaque Edge.Cuts makes the affected result unverified.

### Performance and validation

Geometry may establish that a candidate implements its declared moat. It cannot
establish sensor accuracy. Thermal/humidity validation records include board
revision, enclosure revision, firmware/radio/load states, ambient chamber or
reference instrumentation, airflow/orientation, stabilization time, sample
count, sensor error target, pass/fail, raw-data hash, test date, and reviewer.

The enclosure profile declares sensor vent/opening geometry, airflow shields,
heat-source airflow paths, membrane/filter if present, and expected mounting
orientation. Missing enclosure or test data yields `VALIDATION_PENDING` even if
all fabrication checks pass.

## Antenna, feed, copper keepout, edge overhang, and enclosure

### Module declaration

```python
class AntennaModuleDeclaration(SemanticIrModel):
    antenna_id: str
    module_reference: str
    antenna_region_id: str
    feed_region_id: str
    pcb_keepout_region_ids: tuple[str, ...]
    prohibited_object_kinds: tuple[
        Literal["track", "via", "pad", "zone", "footprint", "board_material"]
    ]
    placement_strategy: Literal["edge_overhang", "baseboard_cutout"]
    required_cutout_region_ids: tuple[str, ...] = ()
    permitted_board_overlap_region_ids: tuple[str, ...] = ()
    nearby_ground_region_ids: tuple[str, ...] = ()
    ground_stitch_requirement_id: str | None = None
    enclosure_exclusion_id: str | None = None
    rf_validation_requirement_id: str
    source_binding_ids: tuple[str, ...]
```

The local regions must come from the exact selected module revision/drawing or
a figure-bound approved derivative. The generic footprint name alone is not an
antenna contract. When the KiCad footprint supplies a keepout zone, retain its
exact polygon, layers, prohibited object kinds, and source-file hash; then bind
it to the approved module guidance rather than assuming any library version is
authoritative forever.

### Hard PCB geometry

For the placed module, transform antenna/feed/keepout geometry through R5's
shared front/back transform. Check exact intersections against:

- board material and cutouts for the selected overhang/cutout strategy;
- tracks, vias, pads, zones/fills, and other footprints on every declared
  layer;
- module-owned features explicitly allowed by the source drawing; and
- nearby ground/stitch regions only where the source requires or permits them.

`edge_overhang` proves the required antenna portion lies outside the baseboard
material while the module body/pads remain supported as declared.
`baseboard_cutout` proves the exact cutout exists on both sides/below as
declared. Neither strategy is simulated by exempting the whole module from
body-to-edge checks; use a region-scoped overhang exception.

### Enclosure and RF validation

Enclosure/object exclusion is a separate 3-D declaration:

```python
class EnclosureExclusionDeclaration(SemanticIrModel):
    exclusion_id: str
    antenna_id: str
    volume_geometry_id: str
    prohibited_material_classes: tuple[str, ...]
    clearance_mm: float | None
    source_binding_ids: tuple[str, ...]
```

A source-specific `15 mm` may appear here when its applicability is bound. It
must not expand a 2-D PCB copper keepout or become a generic antenna rule.
Missing enclosure geometry yields a review/validation finding, not a fabricated
PCB failure.

RF validation records exact module/antenna, firmware/radio mode, channel/band,
enclosure, orientation, counterpart, range/setup, throughput/RSSI or applicable
metric, acceptance target, environment, raw-data hash, and board revision.
Geometry pass plus no RF test remains `VALIDATION_PENDING`.

## Routed decoupling-loop quality

### Declaration

```python
class DecouplingLoopDeclaration(SemanticIrModel):
    loop_id: str
    load_reference: str
    supply_pin_refs: tuple[str, ...]
    capacitor_references: tuple[str, ...]
    capacitor_supply_pin_refs: tuple[str, ...]
    capacitor_return_pin_refs: tuple[str, ...]
    load_return_pin_refs: tuple[str, ...]
    supply_net_name: str
    return_net_name: str
    maximum_loop_length_mm: float | None
    maximum_via_count: int | None
    minimum_connection_width_mm: float | None
    dedicated_via_required: bool | None
    daisy_chain_forbidden: bool | None
    authority: SemanticAuthorityClass
    source_binding_ids: tuple[str, ...]
```

The declaration identifies the intended capacitor-to-load relationship. Do not
assign the nearest capacitor automatically when several rails or packages are
present.

### Routed graph and metrics

Build an exact net-owned copper graph from pads, tracks, vias, and proven filled
zones. Walk the ordered loop `load supply pin -> capacitor supply terminal ->
capacitor return terminal -> load return pin`. Record:

- electrically connected/unresolved state for each leg;
- path and total loop length;
- via count and via source IDs;
- minimum width and necks;
- shared segments with other load/decap paths;
- daisy-chain order;
- loop enclosed area when a unique planar closed projection exists; and
- geometry verification/unknown zone-fill scope.

Capacitor body distance is a separate advisory metric. A generic loop-length
number may be a project policy, but it becomes a blocker only when declared with
applicability and authority. No checker silently inserts `12.7 mm`, one via, or
one package size for every design.

## Oscillator keepout zones

```python
class OscillatorZoneDeclaration(SemanticIrModel):
    zone_id: str
    oscillator_reference: str
    crystal_reference: str | None
    load_capacitor_references: tuple[str, ...]
    oscillator_net_names: tuple[str, ...]
    zone_region_id: str
    allowed_object_ids: tuple[str, ...]
    forbidden_net_classes: tuple[str, ...]
    reference_ground_requirement_id: str | None
    stitch_via_requirement_id: str | None
    io_zone_separation_mm: float | None
    maximum_stray_capacitance_pf: float | None
    authority: SemanticAuthorityClass
    source_binding_ids: tuple[str, ...]
```

Hard geometric checks can exclude foreign tracks/vias/pads/zones and verify
declared ground/stitch geometry. An I/O-zone distance is checked only when the
declaration includes an applicable source value. Stray capacitance cannot be
derived from XY layout alone without a stackup/field/capacitance model; absent a
qualified model it is unverified rather than numerically passed.

An ESP32 module with its oscillator inside the module does not trigger a
discrete-crystal zone unless the component card declares an external zone.

## Switching hot-loop area and switch-node copper

```python
class SwitchingHotLoopDeclaration(SemanticIrModel):
    loop_id: str
    topology_kind: Literal["buck", "boost", "flyback", "other"]
    ordered_terminal_refs: tuple[str, ...]
    ordered_net_names: tuple[str, ...]
    switching_node_net_names: tuple[str, ...]
    return_net_name: str
    maximum_area_mm2: float | None
    maximum_switch_node_area_mm2: float | None
    authority: SemanticAuthorityClass
    source_binding_ids: tuple[str, ...]
```

Resolve each declared leg on the exact copper graph. A unique ordered closed
path yields signed polygon area and absolute enclosed area. Branched copper
requires declared terminal/path selection; never choose the visually smallest
loop after the fact. Report path length, area, layer transitions, vias, unresolved
legs, and geometry verification.

Switch-node copper area is the exact union area of pad/track/via/filled-zone
copper on declared layers, excluding source-scoped features only when declared.
Zone rectangles are not exact fill and cannot support an exact area result.

Without a scoped maximum, both metrics are Pareto/advisory minimization terms.
The current 1-D component-cluster span is not a substitute. A device vendor or
qualified project rule may declare a maximum and make it hard for that topology.

## Connector zoning

```python
class ConnectorZoneDeclaration(SemanticIrModel):
    zone_id: str
    region_id: str
    connector_references: tuple[str, ...]
    connector_role: Literal[
        "off_board_io", "power_entry", "on_board_module",
        "test_fixture", "internal_harness"
    ]
    allowed_edge_ids: tuple[str, ...]
    required_filter_chain_ids: tuple[str, ...] = ()
    ground_pin_policy_id: str | None = None
    separation_requirements: tuple[ZoneSeparationRequirement, ...] = ()
    enclosure_access_requirement_id: str | None = None
    source_binding_ids: tuple[str, ...] = ()
```

Check exact connector body/pad containment against declared board-edge segments
and I/O-zone polygons. Shaped outlines use actual boundary distance; rectangle
width/height proximity is not sufficient. Back-side transforms are honored.
On-board display/module headers are explicitly classified and need not enter an
off-board I/O zone.

Clock/oscillator-to-I/O separation, connector ground-pin distribution, filter
placement/order, and enclosure access are independent findings. Each requires
its own declared threshold/topology. A generic `6 mm from any edge` check does
not prove functional zoning, cable access, or EMC.

## Return adjacency and continuity

```python
class ReturnPathDeclaration(SemanticIrModel):
    return_path_id: str
    signal_net_names: tuple[str, ...]
    signal_class: Literal["clock", "differential", "bus", "switching", "other"]
    reference_net_name: str
    reference_layers: tuple[str, ...]
    adjacency_model_id: str
    maximum_adjacency_distance_mm: float | None
    maximum_discontinuity_length_mm: float | None
    transition_requirement_id: str | None
    common_impedance_pair_ids: tuple[str, ...] = ()
    authority: SemanticAuthorityClass
    source_binding_ids: tuple[str, ...]
```

An adjacency model declares stackup/reference topology and measurement rule.
For a routed signal, sample every exact segment continuously or at a proven
error bound against exact filled reference copper. Report uncovered length,
maximum lateral distance, slots/gaps crossed, necked reference spans, connector
pin-field discontinuities, and layer transitions lacking the declared stitch
via/capacitor.

Rectangle zone declarations are not proof of final filled copper. Until exact
fill polygons are available, affected return metrics are unverified. A rough
`3W`, `3h`, or one-trace-width value is not inserted globally; it may appear in
a declared advisory model whose applicability is retained.

Common-impedance checks walk the exact return graph and report shared segment
length/current/IR estimate only when conductor geometry and current are known.
High-current and sensitive return roles are declarations, not inferred from net
names.

## Process-scoped dual-side retention

### Assembly process profile

```python
class AssemblyProcessProfile(SemanticIrModel):
    profile_id: str
    assembler_id: str | None
    process_revision: str
    sequence: Literal[
        "single_reflow", "double_reflow", "reflow_then_wave",
        "selective", "hand_assembly", "other"
    ]
    first_reflow_side: Literal["front", "back", "not_applicable"]
    second_reflow_side: Literal["front", "back", "not_applicable"]
    inverted_during_second_reflow_side: Literal["front", "back", "none"]
    alloy_id: str | None
    paste_id: str | None
    surface_finish_id: str | None
    stencil_thickness_um: float | None
    aperture_process_id: str | None
    oven_id: str | None
    peak_temperature_c: float | None
    time_above_liquidus_s: float | None
    conveyor_orientation: str | None
    turbulence_class: str | None
    board_carrier_id: str | None
    adhesive_policy_id: str | None
    handling_policy_id: str | None
    qualification: QualifiedAssemblerReview | None
    evidence_binding_ids: tuple[str, ...]
```

Unknown fields remain unknown; do not fill them from the SAC305 paper. A
double-sided layout does not imply double reflow, and the back side is not
automatically the inverted second-pass side.

`QualifiedAssemblerReview` contains assembler/reviewer identity, qualification
record/hash, effective dates, covered board construction, component/package
envelope, process settings, required restrictions, deviations, and status.
Only an active, applicable record can create a hard side-assignment rule.

### Package/joint evidence

```python
class PackageRetentionEvidence(SemanticIrModel):
    evidence_id: str
    component_reference: str
    component_mass_g: float | None
    mass_source: Literal["manufacturer", "measured", "estimated", "unknown"]
    package_family: str
    joint_ids: tuple[str, ...]
    total_wetted_perimeter_mm: float | None
    wetted_perimeter_method_id: str | None
    void_fraction: float | None
    pad_pattern_fingerprint: str
    paste_aperture_fingerprint: str | None
    orientation_to_conveyor_deg: float | None
    source_binding_ids: tuple[str, ...]
```

Wetted perimeter is not package body perimeter. The method states which joint
interfaces count, pad/terminal geometry, void treatment, and units. Missing mass
or wetted geometry prevents a ratio calculation; it does not classify the part
as light/safe.

### Retention models and findings

```python
class RetentionModelDeclaration(SemanticIrModel):
    model_id: str
    authority: SemanticAuthorityClass
    applicable_package_families: tuple[str, ...]
    required_process_conditions: tuple[str, ...]
    excluded_process_conditions: tuple[str, ...]
    calculation_kind: Literal["mass_per_wetted_perimeter", "assembler_rule", "other"]
    advisory_limit_g_per_mm: float | None
    assembler_requirement_id: str | None
    source_binding_ids: tuple[str, ...]
```

For an inverted component, compute mass/wetted-perimeter only when both inputs
are known. Then evaluate applicability condition by condition. The SMTA SAC305
model is `ADVISORY_HYPOTHESIS`; matching its narrow conditions permits an
advisory comparison, while a mismatch produces `UNVERIFIED`, not interpolation
or a blocker. QFN/DFN membership alone does not establish applicability.

An assembler may impose maximum mass, package list, adhesive, carrier, or side
restrictions. Such a rule is hard only when the qualification record is active
and covers the exact board/process/package. Otherwise R6 emits a
`process_review_required` finding.

Mass, wetted perimeter, model ratio, model applicability, process match,
assembler verdict, and final disposition are all reported separately.

## Package/class-specific neighbor overhang

```python
class NeighborOverhangRequirement(SemanticIrModel):
    requirement_id: str
    acceptance_class: str
    package_geometry_kind: Literal["chip", "melf", "gull_wing", "other"]
    component_references: tuple[str, ...]
    maximum_terminal_overhang_mm: float | None
    maximum_terminal_overhang_fraction: float | None
    minimum_post_tolerance_copper_gap_mm: float
    tolerance_model_id: str
    authority: SemanticAuthorityClass
    source_binding_ids: tuple[str, ...]
```

Use exact pad/terminal geometry, placement tolerance, package-specific allowed
overhang direction/fraction, and active electrical clearance to compute the
worst-case adjacent copper gap. Do not use a single `0.5 * W` allowance for all
packages/classes. A hard finding requires a selected acceptance class and
applicable requirement. Without those declarations, report the measured gap and
request process review.

## Hard geometry, advisory hypotheses, and validation matrix

| Topic | May be hard when declared/applicable | Advisory or pending by default |
|---|---|---|
| Thermal zones | exact prohibited overlap or sourced separation | temperature prediction without scoped model; built-enclosure performance |
| Sensor moat | fab slot/web/copper/trace geometry; assembler structural restriction | isolation benefit and accuracy until thermal/humidity validation |
| Antenna | exact module keepout, edge-overhang/cutout geometry | enclosure clearance without model; RF performance until test |
| Decoupling | connectivity and explicitly sourced loop limits | proximity, generic loop target, inferred inductance |
| Oscillator | declared foreign-object keepout and sourced separation | stray capacitance without a field/model calculation |
| Hot loop | connectivity and explicitly sourced maximum | minimize area/switch-node copper when no maximum exists |
| Connector zoning | exact declared zone/edge/filter topology | generic edge proximity as EMC/cable-quality proof |
| Return path | exact declared no-slot/transition requirement with proven reference copper | distance rules without stackup/reference applicability |
| Retention | applicable qualified assembler restriction | SAC305/QFN experimental ratio |
| Neighbor overhang | selected package/class/tolerance requirement | generic package-family assumption |

Unsupported geometry never becomes advisory success. It is `UNVERIFIED` and
identifies the source/scope that prevented a result.

## Deterministic metrics, findings, and fingerprints

### Metrics

Store physical metrics in declared units and canonical integer quanta where
ranking needs exact repeatability:

- distance/length in micrometres;
- area in square micrometres;
- temperature in milli-degrees C only when a model produced it;
- power in microwatts;
- mass in micrograms;
- wetted perimeter in micrometres;
- ratios as exact numerator/denominator plus a rendered decimal;
- counts as integers; and
- validation outcomes as typed state, never numeric sentinel values.

Retain source float values separately if required for provenance. Reject
NaN/Infinity. Polygon unions, path selection, nearest-point ties, and graph
walks use stable source IDs for tie-breaking.

### Findings

Add semantic fields or a companion model rather than hiding authority in
`ReviewFinding.evidence` prose:

```python
class SemanticFinding(SemanticIrModel):
    finding_id: str
    rule_id: str
    authority: SemanticAuthorityClass
    disposition: SemanticDisposition
    verification: SemanticVerification
    object_ids: tuple[str, ...]
    component_refs: tuple[str, ...]
    net_refs: tuple[str, ...]
    region_ids: tuple[str, ...]
    metric_ids: tuple[str, ...]
    evidence_binding_ids: tuple[str, ...]
    process_profile_id: str | None
    validation_requirement_ids: tuple[str, ...]
    message: str
    suggested_action: str
```

`finding_id` hashes semantic identity, not message wording. The adapter may
produce a conventional `ReviewFinding`, but must preserve authority,
disposition, verification, process, and validation IDs in structured fields or
an attached resultâ€”not flatten them into one warning string.

### Fingerprints

Canonical JSON uses sorted keys, compact separators, UTF-8, no non-finite
numbers, and SHA-256. Pin at least:

- declarations and evidence-binding fingerprints;
- placed semantic-region fingerprint;
- exact copper/hole/cutout/fill geometry fingerprint;
- PcbRuleProfile, semantic, assembly, enclosure, and validation profile
  fingerprints;
- per-check input, metric, and result fingerprints;
- candidate semantic-result fingerprint; and
- source/toolchain fingerprints for footprint/component-card/field-model/test
  artifacts.

Input-order reversal of set-like declarations must not change fingerprints.
Semantic order, such as an ordered hot loop or process sequence, is preserved.

## Integration with R5 candidate ranking and acceptance

R6 adds structured axes, not one arbitrary weighted penalty.

Placement-stage axes include:

- hard semantic geometry failure count;
- unverified hard-scope count;
- sensor/thermal overlap and sourced separation failures;
- antenna keepout and overhang/cutout failures;
- oscillator/connector region conflicts;
- assembly hard restriction failures; and
- advisory distance/area/retention metrics after hard axes.

Routed-stage axes include unresolved decoupling/hot-loop/return paths, hard
loop/area failures, exact antenna/oscillator/connector copper intrusion, return
discontinuities, and pending validation count. Hot-loop area and decoupling
length are secondary Pareto metrics unless their declaration makes them hard.

An R5 candidate is not accepted when an applicable hard R6 finding fails or a
hard scope is unverified. Validation-pending results do not become hard geometry
failures, but the board-level status remains `needs_human_review` or a more
specific `validation_pending` until required campaigns pass. A product workflow
may require all validation records for release; that policy is separate from PCB
route acceptance and must be explicit.

## Staged implementation and firing fixtures

Every slice ends with strict mypy, Ruff, focused tests, full suite, deterministic
fingerprints, and the applicable serialized KiCad/DRC authority gate.

### R6.0 - semantic IR, authority, and provenance

Implement only common models, validation, canonicalization, and finding/result
fingerprints.

Firing fixtures:

1. hard, qualified-process, advisory, and validation-required declarations
   cannot be substituted;
2. advisory failure cannot serialize as `FAIL`;
3. qualified-process authority without assembler/review/applicability identity
   is rejected;
4. exact/bounded/unsupported geometry metadata is coherent;
5. a number without units/evidence binding is rejected;
6. reversed set-like construction pins JSON/fingerprints; ordered loop/process
   fields remain order sensitive; and
7. changed source hash, process revision, enclosure, validation target, or
   geometry changes only the expected fingerprints.

### R6.1 - thermal and sensor/moat candidacy

**R6.1a status (2026-07-16):** fixtures 1-4 are implemented for declared
polygonal regions. Geometry-only separation does not require a fabricated
enclosure identity. Theta-model estimates require matching ambient,
dissipation/duty, PCB, board/air, and enclosure scope; missing or mismatched
scope is unverified and emits no temperature. Unsupported separation retains
typed, role-specific geometry or live component/net binding causes and cannot
carry geometry, PASS, or FAIL.

**R6.1b slice 1 status (2026-07-17):** fixture 5 is implemented for exact
declared slot, retained-web, and support-tab compounds. Hard PASS requires the
selected fabrication profile, active assembly qualification, complete per-feature
evidence/applicability, exact live slot equality, and positive web/tab containment
in the retained live board outline without interior cutout overlap. No leftover
laminate or process width is inferred. Fixtures 6-9 remain unimplemented.

Firing fixtures:

1. exact heat/sensor regions overlap and separate deterministically on front and
   back arbitrary-angle placements;
2. an advisory separation reports distance but cannot hard-fail;
3. a sourced hard project separation fires at one micrometre below and passes at
   equality;
4. JESD51 theta without matching board/air context returns unverified;
5. a manufacturable rounded slot/web/tab candidate passes its selected fab and
   assembly profile, while one-less unit fires the correct constraint ID;
6. copper crossing a declared removal region fires for track, via, pad, and
   exact filled zone; unknown fill is unverified;
7. undeclared bridge net and excess declared bridge width/count fire
   independently;
8. no enclosure/test record remains validation-pending; a matching thermal and
   humidity campaign passes without changing geometry metrics; and
9. changing the Sensirion example into a moat width is rejected by schema/test.

### R6.2 - antenna/feed/edge/cutout/enclosure

Use a synthetic asymmetric module first, then the exact ESP32-C3 footprint/card.

Firing fixtures:

1. component-local antenna/feed/keepout polygons transform correctly through
   arbitrary front/back rotations;
2. a track, via, foreign pad, zone fill, footprint body, and board material each
   fire only their declared prohibited-object rule/layer;
3. the installed footprint's multilayer keepout polygon is retained and pinned,
   not discarded as a comment;
4. edge-overhang passes only when the required antenna region is outside while
   support/pads remain valid;
5. cutout strategy requires the exact declared cutout and both-layer keepout;
6. a whole-reference body-edge exemption cannot hide antenna geometry failure;
7. enclosure `15 mm` affects only the matching 3-D exclusion declaration and
   never changes PCB copper geometry;
8. geometry pass without RF campaign is validation-pending; matching RF test
   passes; and
9. module/footprint/source revision mismatch invalidates the geometry binding.

### R6.3 - decoupling and switching hot loops

Firing fixtures:

1. exact declared pin-cap-return graph resolves a complete loop and pins path,
   length, vias, minimum width, sharing, and area;
2. nearest-in-XY wrong capacitor is not substituted for the declared capacitor;
3. daisy-chained and dedicated-via policies fire independently;
4. a target loop through an unknown zone fill is unverified, not zero length;
5. 1-D cluster span can stay identical while exact hot-loop area changes, proving
   the old surrogate is insufficient;
6. branched hot-loop copper requires declared path identity;
7. switch-node union includes pad/track/via/filled-zone copper without double
   counting overlap;
8. generic area/length metrics remain advisory while a sourced scoped maximum
   hard-fails at one unit above; and
9. input construction order does not change chosen graph paths/fingerprints.

### R6.4 - oscillator, connector zoning, and return adjacency

Firing fixtures:

1. foreign switching copper inside an oscillator zone fires; allowed local
   ground and declared oscillator nets pass;
2. stitch-via and local-reference requirements fire separately;
3. stray capacitance without a qualified model remains unverified;
4. shaped-edge connector zone uses actual outline distance and exact back-side
   transforms;
5. on-board module header is not misclassified as off-board I/O;
6. connector zone, filter chain, ground-pin spread, enclosure access, and
   oscillator separation are separate findings;
7. exact reference fill gives continuous adjacency; a slot, neck, pin-field
   void, and unstiched layer transition each fire with location/source IDs;
8. rectangle-only/unknown zone fill prevents an exact return pass; and
9. `3W`, `3h`, and one-trace-width models remain distinct scoped advisories.

### R6.5 - dual-side process and neighbor overhang

Firing fixtures:

1. front/back placement alone does not imply inverted second reflow;
2. missing mass or wetted geometry produces unverified, never safe;
3. body perimeter cannot be substituted for wetted perimeter;
4. the narrow SMTA SAC305 fixture computes its published ratio deterministically
   but remains advisory;
5. changing finish, stencil, paste, alloy, peak, package, pad, void, oven, or
   orientation breaks applicability rather than reusing the ratio;
6. QFN/DFN labels alone never hard-pass or hard-fail;
7. an active assembler qualification restriction hard-fails only its covered
   process/package/board conditions;
8. expired/mismatched qualification becomes process-review-required;
9. chip, MELF, gull-wing, and unknown package overhang requirements do not
   alias, and selected acceptance class changes the expected result; and
10. one-less post-tolerance copper gap fires the exact package/class constraint.

### R6.6 - R5 integration and result honesty

Firing fixtures:

1. lossless R5 probe fields and semantic declaration fingerprints survive every
   candidate;
2. hard semantic geometry outranks advisory distance/area/retention metrics;
3. favorable HPWL cannot defeat an antenna keepout or hard process failure;
4. placement-stage advisory metrics do not claim routed loop/return success;
5. exact routing may turn a placement candidate into a decoupling/hot-loop/
   return failure without corrupting R2 success telemetry;
6. validation pending is distinct from exact-check rejection and route failure;
7. no declarations produces a deterministic empty/not-applicable semantic
   result without changing existing R5 ranking; and
8. repeated/reversed evaluation pins semantic axes, findings, and fingerprints.

### R6.7 - thermometer semantic pilot

Run only after the prerequisites below. First evaluate the fixed current
placement to produce deliberate failures/pending results; then allow R5 to move
the declared subset.

Firing fixtures:

1. current U1 antenna orientation deliberately fires against exact interior
   board/copper geometry;
2. corrected U1 rotation/edge strategy passes the exact module keepout and
   region-scoped overhang/cutout checks;
3. enclosure clearance remains pending until an enclosure model exists and RF
   validation remains pending until the test is run;
4. U4 sensor has declared heat sources, ambient-access region, bridge nets, and
   a profile-selected isolation candidate without a universal slot value;
5. candidate slot/web/tab/copper geometry passes fab/assembly checks while
   thermal/humidity performance remains pending before test;
6. U1, U2, U3, U4, and U5 decoupling relationships resolve routed loop metrics;
7. USB connector zoning and filter/protection omissions are reported separately;
8. SEG/control return declarations measure actual reference continuity and
   transitions without inventing a global spacing rule;
9. every back-side component receives process retention review for the selected
   assembly sequence, with no QFN/DFN shortcut; and
10. final semantic, route, KiCad, validation, and artifact fingerprints are
   pinned independently.

## Thermometer R7 prerequisites

Before the thermometer can claim R6/R7 authority:

1. R5 lossless probes and exact front/back body/region transforms are
   implemented and proven on arbitrary-angle asymmetric fixtures.
2. Typed board cutouts and exact filled-zone/keepout geometry exist. Raw
   graphics and zone rectangles cannot prove antenna, moat, hot-loop, or return
   results.
3. The ESP32-C3-WROOM-02 exact module revision is selected. Its antenna, feed,
   multilayer keepout, edge/cutout geometry, origin, and source checksum are
   figure-bound and cross-checked against the selected footprint revision.
4. U1 is rotated/repositioned so the antenna faces the bulb edge or uses the
   exact approved cutout strategy. A prose finding is not evidence that the
   board implements it.
5. An enclosure profile defines nearby materials/objects and antenna volume;
   final RF range/throughput validation has an explicit campaign and target.
6. The locally available SHT31 component card is extended or paired with a
   semantic card binding for the official design guide. No universal moat
   geometry is added to the electrical pin card.
7. A real fabricator/assembly profile declares slot/cutout/web/tab capability,
   copper-to-edge behavior, panel/handling constraints, and selected process.
8. U4 isolation candidate geometry includes ambient access, exact slots/webs/
   tabs, copper removal on declared layers, and only declared thin bridge nets.
9. The built enclosure thermal/humidity validation campaign covers radio/load/
   display states, ambient conditions, orientation, stabilization, and reference
   instrumentation.
10. Decoupling, connector, return, and any oscillator/hot-loop declarations are
    explicit and evidence-bound; R6 does not infer them from component roles.
11. The assembler declares the actual side/process sequence, paste, finish,
    stencil, oven/profile, carrier/adhesive/handling policy, and qualification
    status. Until then every inverted-second-reflow conclusion remains review.
12. R2-R4 detailed routing and R5 placement are complete with zero overuse;
    R6 routed checks consume that exact final geometry.
13. ERC, reader equality, simulation where applicable, virtual/design/semantic
    checks, KiCad DRC, deterministic repeats, visual review, and the required
    enclosure/process validations all retain separate outcomes.

## Unresolved decisions before production code

1. **Semantic data ownership.** Recommended: component-local geometry and
   device requirements live in a versioned semantic extension referenced by the
   component card, while project operating points/zones live in the board
   declaration. Do not overload the current pin-contract schema.
2. **Exact KiCad keepout import.** Decide whether footprint zones/keepouts enter
   `FootprintSpec` or a parallel lossless geometry object. They must retain
   layers and prohibited object kinds.
3. **Figure binding workflow.** Define reviewer/tooling for converting a vendor
   drawing into local coordinates with checksum, locator, units, origin, and
   verification state.
4. **Typed board cutouts and filled zones.** R3/R5/R6 all need them. Recommended:
   one shared exact representation, not separate semantic approximations.
5. **Thermal-model boundary.** Decide which models can become qualified numeric
   predictors and what validation is required. Do not treat theta-JA as a
   component constant.
6. **Sensor structural authority.** Determine whether fabricator, assembler,
   enclosure/mechanical reviewer, or all three approve the isolated tongue and
   how conflicting limits resolve.
7. **Ambient-air access model.** A 2-D board polygon cannot prove airflow.
   Recommended: enclosure volume/path declaration plus validation campaign.
8. **Copper graph with filled zones.** Decoupling, hot-loop, and return checks
   require exact connectivity/geometry. Define fill import and source identity
   before numeric authority.
9. **Loop path selection.** For branched nets, require declared terminal/path
   roles or a canonical constrained graph algorithm; never choose the most
   favorable loop silently.
10. **Return-adjacency model.** Select stackup-aware distance/continuity metrics
    and bounded sampling error. Keep rough width rules advisory.
11. **Process qualification schema.** Confirm required assembler signature,
    expiry, covered process envelope, deviations, and revocation behavior.
12. **Wetted-perimeter method.** Package/land geometry, paste aperture, and void
    accounting need a reviewed definition before any ratio comparison.
13. **Release policy.** Decide which validation-pending findings block product
    release versus merely prevent a claim. Keep this separate from PCB geometry
    and route acceptance.
14. **R5 Pareto interaction.** Calibrate semantic advisory axes and diversity on
    synthetic fixtures/corpus before assigning defaults. No arbitrary weight
    should silently dominate routability.

## Recommended implementation order

Implement R6.0 through R6.6 in order. Shared authority/provenance and exact
geometry precede every domain check. Thermal/sensor and antenna geometry should
land before loop/return graph metrics because the thermometer's known defects
depend on them. Process retention remains advisory until an assembler profile is
available. R6.7 is a consumer pilot, not a shortcut around synthetic fixtures.

Do not update the thermometer layout, promote a universal moat/antenna/reflow
number, or change existing placement defaults while this document is the only
R6 artifact.
