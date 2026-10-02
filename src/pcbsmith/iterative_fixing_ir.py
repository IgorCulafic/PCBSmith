"""IF1 immutable dependency graph and non-mutating repair impact reports.

This module predicts the authority and smallest declared change envelope for a
finding.  It deliberately does not edit a KiCad project and does not qualify a
candidate.  Exact saved-board checks remain the acceptance authority.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.library import QuotedString, SExpr, parse_sexpr, serialize_sexpr
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class DependencyObjectKind(StrEnum):
    BOARD_REVISION = "board_revision"
    SCHEMATIC_REVISION = "schematic_revision"
    COMPONENT = "component"
    FOOTPRINT = "footprint"
    SYMBOL_PIN = "symbol_pin"
    PAD = "pad"
    NET = "net"
    NET_CLASS = "net_class"
    SEGMENT = "segment"
    ARC = "arc"
    VIA = "via"
    ZONE = "zone"
    FILLED_REGION = "filled_region"
    BOARD_EDGE = "board_edge"
    HOLE = "hole"
    KEEPOUT = "keepout"
    COURTYARD = "courtyard"
    MATING_ENVELOPE = "mating_envelope"
    MARKING = "marking"
    MODEL = "model"
    TOPOLOGY_RELATION = "topology_relation"
    THERMAL_OBLIGATION = "thermal_obligation"
    CHECK = "check"
    EVIDENCE = "evidence"


class DependencyRelation(StrEnum):
    CONTAINS = "contains"
    HAS_PAD = "has_pad"
    CONNECTS_TO_NET = "connects_to_net"
    REALIZES_NET = "realizes_net"
    MARKS_COMPONENT = "marks_component"
    USES_MODEL = "uses_model"
    CONSTRAINS = "constrains"
    VERIFIES = "verifies"
    DERIVED_FROM = "derived_from"


class RepairOwnerStage(StrEnum):
    INTAKE = "intake"
    SEMANTIC_DESIGN = "semantic_design"
    SCHEMATIC_EXPORT = "schematic_export"
    FOOTPRINT_MAPPING = "footprint_mapping"
    PLACEMENT = "placement"
    ESCAPE = "escape"
    ROUTING = "routing"
    FILL = "fill"
    MARKING = "marking"
    MODEL = "model"
    REVIEW = "review"
    QUALIFICATION = "qualification"
    ARCHITECTURE = "architecture"


class FindingFamily(StrEnum):
    SCHEMATIC_PARITY = "schematic_parity"
    PIN_MAPPING = "pin_mapping"
    PLACEMENT = "placement"
    OPEN = "open"
    CLEARANCE = "clearance"
    ISOLATED_ZONE = "isolated_zone"
    STARVED_THERMAL = "starved_thermal"
    MARKING = "marking"
    MODEL = "model"
    GLOBAL_CAPACITY = "global_capacity"


class RepairScope(StrEnum):
    OBJECT = "object"
    COMPONENT_NEIGHBORHOOD = "component_neighborhood"
    SELECTED_NET = "selected_net"
    SELECTED_REGION = "selected_region"
    FUNCTIONAL_CLUSTER = "functional_cluster"
    GLOBAL = "global"


class ProposedRepairClass(StrEnum):
    SCHEMATIC_IDENTITY = "schematic_identity"
    FOOTPRINT_PIN_MAP = "footprint_pin_map"
    COMPONENT_MOVE_ROTATE = "component_move_rotate"
    SELECTED_NET_COPPER = "selected_net_copper"
    LOCAL_CLEARANCE_COPPER = "local_clearance_copper"
    ZONE_INTENT_REFILL = "zone_intent_refill"
    MARKING_MOVE = "marking_move"
    MODEL_ASSIGN_TRANSFORM = "model_assign_transform"
    ARCHITECTURE_ESCALATION = "architecture_escalation"


class DryRunDisposition(StrEnum):
    READY_FOR_CANDIDATE_TRANSACTION = "ready_for_candidate_transaction"
    BLOCKED_UNRESOLVED_AUTHORITY = "blocked_unresolved_authority"
    BLOCKED_BUDGET = "blocked_budget"


class DependencyObject(SemanticIrModel):
    object_id: str
    object_kind: DependencyObjectKind
    authority_stage: RepairOwnerStage
    source_board_sha256: str
    source_object_fingerprint: str
    component_refs: tuple[str, ...] = ()
    net_names: tuple[str, ...] = ()
    region_mm: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def object_is_canonical(self) -> Self:
        require_identity(self.object_id, "object_id")
        require_sha256(self.source_board_sha256, "source_board_sha256")
        require_sha256(self.source_object_fingerprint, "source_object_fingerprint")
        for name in ("component_refs", "net_names"):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError(f"{name} must contain unique nonblank identities")
            object.__setattr__(self, name, values)
        if self.region_mm is not None:
            x1, y1, x2, y2 = self.region_mm
            if not (x1 <= x2 and y1 <= y2):
                raise ValueError("object region must be ordered")
        return self


class DependencyEdge(SemanticIrModel):
    source_object_id: str
    target_object_id: str
    relation: DependencyRelation

    @model_validator(mode="after")
    def edge_is_canonical(self) -> Self:
        require_identity(self.source_object_id, "source_object_id")
        require_identity(self.target_object_id, "target_object_id")
        if self.source_object_id == self.target_object_id:
            raise ValueError("dependency edge cannot be a self-edge")
        return self


class BoardDependencyGraph(SemanticIrModel):
    schema_id: Literal["pcbsmith-board-dependency-graph-v1"] = "pcbsmith-board-dependency-graph-v1"
    source_board_file: str
    source_board_sha256: str
    objects: tuple[DependencyObject, ...]
    edges: tuple[DependencyEdge, ...]
    observed_authority_complete: bool
    unresolved_authority_ids: tuple[str, ...] = ()
    graph_fingerprint: str

    @model_validator(mode="after")
    def graph_is_closed_and_canonical(self) -> Self:
        require_sha256(self.source_board_sha256, "source_board_sha256")
        require_sha256(self.graph_fingerprint, "graph_fingerprint")
        objects = tuple(sorted(self.objects, key=lambda item: item.object_id))
        ids = tuple(item.object_id for item in objects)
        if len(ids) != len(set(ids)):
            raise ValueError("dependency object identities must be unique")
        if any(item.source_board_sha256 != self.source_board_sha256 for item in objects):
            raise ValueError("dependency object belongs to another board revision")
        edges = tuple(
            sorted(
                self.edges,
                key=lambda item: (item.source_object_id, item.target_object_id, item.relation),
            )
        )
        edge_keys = tuple(
            (item.source_object_id, item.target_object_id, item.relation) for item in edges
        )
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("dependency edges must be unique")
        unknown = {
            endpoint
            for edge in edges
            for endpoint in (edge.source_object_id, edge.target_object_id)
            if endpoint not in set(ids)
        }
        if unknown:
            raise ValueError("dependency edge references an unknown object")
        unresolved = tuple(sorted(self.unresolved_authority_ids))
        if len(unresolved) != len(set(unresolved)):
            raise ValueError("unresolved authority identities must be unique")
        if self.observed_authority_complete == bool(unresolved):
            raise ValueError("graph authority completeness disposition is stale")
        object.__setattr__(self, "objects", objects)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "unresolved_authority_ids", unresolved)
        payload = self.model_dump(mode="json", exclude={"graph_fingerprint", "source_board_file"})
        if self.graph_fingerprint != fingerprint(payload):
            raise ValueError("dependency graph fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> BoardDependencyGraph:
        fields = dict(values)
        fields["objects"] = tuple(
            sorted(fields.get("objects", ()), key=lambda item: item.object_id)
        )
        fields["edges"] = tuple(
            sorted(
                fields.get("edges", ()),
                key=lambda item: (item.source_object_id, item.target_object_id, item.relation),
            )
        )
        fields["unresolved_authority_ids"] = tuple(
            sorted(fields.get("unresolved_authority_ids", ()))
        )
        provisional = cls.model_construct(**fields, graph_fingerprint="0" * 64)
        return cls(
            **fields,
            graph_fingerprint=fingerprint(
                provisional.model_dump(
                    mode="json", exclude={"graph_fingerprint", "source_board_file"}
                )
            ),
        )


class FindingObservation(SemanticIrModel):
    schema_id: Literal["pcbsmith-iterative-finding-observation-v1"] = (
        "pcbsmith-iterative-finding-observation-v1"
    )
    finding_id: str
    evidence_fingerprint: str
    source_board_sha256: str
    family: FindingFamily
    subject_object_ids: tuple[str, ...] = ()
    mutable_object_ids: tuple[str, ...] = ()
    affected_net_names: tuple[str, ...] = ()
    component_refs: tuple[str, ...] = ()
    target_region_mm: tuple[float, float, float, float] | None = None
    detail_authority_complete: bool = True

    @model_validator(mode="after")
    def observation_is_exact(self) -> Self:
        require_identity(self.finding_id, "finding_id")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        require_sha256(self.source_board_sha256, "source_board_sha256")
        for name in (
            "subject_object_ids",
            "mutable_object_ids",
            "affected_net_names",
            "component_refs",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique identities")
            object.__setattr__(self, name, values)
        if not set(self.mutable_object_ids) <= set(self.subject_object_ids):
            raise ValueError("mutable finding objects must be a subset of subject objects")
        if self.target_region_mm is not None:
            x1, y1, x2, y2 = self.target_region_mm
            if not (x1 < x2 and y1 < y2):
                raise ValueError("finding target region must have positive area")
        return self


class BoardFindingDiagnosis(SemanticIrModel):
    schema_id: Literal["pcbsmith-board-finding-diagnosis-v1"] = (
        "pcbsmith-board-finding-diagnosis-v1"
    )
    observation: FindingObservation
    graph_fingerprint: str
    owner_stage: RepairOwnerStage
    scope: RepairScope
    affected_object_ids: tuple[str, ...]
    protected_neighbor_ids: tuple[str, ...]
    proposed_repair_classes: tuple[ProposedRepairClass, ...]
    required_post_change_gates: tuple[str, ...]
    unresolved_authority_ids: tuple[str, ...]
    diagnosis_fingerprint: str

    @model_validator(mode="after")
    def diagnosis_is_canonical(self) -> Self:
        require_sha256(self.graph_fingerprint, "graph_fingerprint")
        require_sha256(self.diagnosis_fingerprint, "diagnosis_fingerprint")
        for name in (
            "affected_object_ids",
            "protected_neighbor_ids",
            "proposed_repair_classes",
            "required_post_change_gates",
            "unresolved_authority_ids",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
            object.__setattr__(self, name, values)
        if set(self.affected_object_ids) & set(self.protected_neighbor_ids):
            raise ValueError("affected and protected-neighbor objects must be disjoint")
        payload = self.model_dump(mode="json", exclude={"diagnosis_fingerprint"})
        if self.diagnosis_fingerprint != fingerprint(payload):
            raise ValueError("finding diagnosis fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> BoardFindingDiagnosis:
        fields = dict(values)
        for name in (
            "affected_object_ids",
            "protected_neighbor_ids",
            "proposed_repair_classes",
            "required_post_change_gates",
            "unresolved_authority_ids",
        ):
            fields[name] = tuple(sorted(fields.get(name, ())))
        provisional = cls.model_construct(**fields, diagnosis_fingerprint="0" * 64)
        return cls(
            **fields,
            diagnosis_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"diagnosis_fingerprint"})
            ),
        )


class ChangeImpactBudget(SemanticIrModel):
    schema_id: Literal["pcbsmith-change-impact-budget-v1"] = "pcbsmith-change-impact-budget-v1"
    maximum_mutable_object_count: int = Field(ge=0)
    maximum_affected_net_count: int = Field(ge=0)
    maximum_region_count: int = Field(ge=0)
    maximum_existing_copper_object_count: int = Field(ge=0)
    maximum_component_count: int = Field(ge=0)
    maximum_graph_hops: int = Field(default=2, ge=0)
    maximum_component_displacement_mm: float = Field(default=0.0, ge=0)
    maximum_component_rotation_degrees: float = Field(default=0.0, ge=0, le=360)
    maximum_ripped_segment_count: int = Field(default=0, ge=0)
    maximum_ripped_via_count: int = Field(default=0, ge=0)
    maximum_added_segment_count: int = Field(default=0, ge=0)
    maximum_added_via_count: int = Field(default=0, ge=0)
    maximum_candidate_count: int = Field(default=1, ge=1)
    maximum_elapsed_seconds: float = Field(default=60.0, gt=0)


class ProtectedObjectFingerprint(SemanticIrModel):
    object_id: str
    object_kind: DependencyObjectKind
    source_object_fingerprint: str

    @model_validator(mode="after")
    def protected_object_is_exact(self) -> Self:
        require_identity(self.object_id, "object_id")
        require_sha256(self.source_object_fingerprint, "source_object_fingerprint")
        return self


class ProtectedObjectInventory(SemanticIrModel):
    schema_id: Literal["pcbsmith-protected-object-inventory-v1"] = (
        "pcbsmith-protected-object-inventory-v1"
    )
    source_board_sha256: str
    graph_fingerprint: str
    objects: tuple[ProtectedObjectFingerprint, ...]
    inventory_fingerprint: str

    @model_validator(mode="after")
    def inventory_is_canonical(self) -> Self:
        require_sha256(self.source_board_sha256, "source_board_sha256")
        require_sha256(self.graph_fingerprint, "graph_fingerprint")
        require_sha256(self.inventory_fingerprint, "inventory_fingerprint")
        objects = tuple(sorted(self.objects, key=lambda item: item.object_id))
        if len(objects) != len({item.object_id for item in objects}):
            raise ValueError("protected object identities must be unique")
        object.__setattr__(self, "objects", objects)
        payload = self.model_dump(mode="json", exclude={"inventory_fingerprint"})
        if self.inventory_fingerprint != fingerprint(payload):
            raise ValueError("protected object inventory fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> ProtectedObjectInventory:
        fields = dict(values)
        fields["objects"] = tuple(
            sorted(fields.get("objects", ()), key=lambda item: item.object_id)
        )
        provisional = cls.model_construct(**fields, inventory_fingerprint="0" * 64)
        return cls(
            **fields,
            inventory_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"inventory_fingerprint"})
            ),
        )


class ChangeImpactEnvelope(SemanticIrModel):
    schema_id: Literal["pcbsmith-change-impact-envelope-v1"] = "pcbsmith-change-impact-envelope-v1"
    source_board_sha256: str
    graph_fingerprint: str
    diagnosis_fingerprint: str
    mutable_object_ids: tuple[str, ...]
    mutable_net_names: tuple[str, ...]
    mutable_regions_mm: tuple[tuple[float, float, float, float], ...]
    protected_inventory: ProtectedObjectInventory
    budget: ChangeImpactBudget
    required_post_change_gates: tuple[str, ...]
    predicted_consequences: tuple[str, ...]
    unknowns: tuple[str, ...]
    blocker_ids: tuple[str, ...]
    disposition: DryRunDisposition
    envelope_fingerprint: str

    @model_validator(mode="after")
    def envelope_is_closed(self) -> Self:
        for name in ("source_board_sha256", "graph_fingerprint", "diagnosis_fingerprint"):
            require_sha256(getattr(self, name), name)
        require_sha256(self.envelope_fingerprint, "envelope_fingerprint")
        for name in (
            "mutable_object_ids",
            "mutable_net_names",
            "required_post_change_gates",
            "predicted_consequences",
            "unknowns",
            "blocker_ids",
        ):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
            object.__setattr__(self, name, values)
        regions = tuple(sorted(self.mutable_regions_mm))
        object.__setattr__(self, "mutable_regions_mm", regions)
        expected = (
            DryRunDisposition.BLOCKED_BUDGET
            if any(item.startswith("budget:") for item in self.blocker_ids)
            else DryRunDisposition.BLOCKED_UNRESOLVED_AUTHORITY
            if self.blocker_ids
            else DryRunDisposition.READY_FOR_CANDIDATE_TRANSACTION
        )
        if self.disposition is not expected:
            raise ValueError("impact-envelope disposition is stale")
        payload = self.model_dump(mode="json", exclude={"envelope_fingerprint"})
        if self.envelope_fingerprint != fingerprint(payload):
            raise ValueError("impact envelope fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> ChangeImpactEnvelope:
        fields = dict(values)
        for name in (
            "mutable_object_ids",
            "mutable_net_names",
            "required_post_change_gates",
            "predicted_consequences",
            "unknowns",
            "blocker_ids",
        ):
            fields[name] = tuple(sorted(fields.get(name, ())))
        fields["mutable_regions_mm"] = tuple(sorted(fields.get("mutable_regions_mm", ())))
        blockers = fields["blocker_ids"]
        fields["disposition"] = (
            DryRunDisposition.BLOCKED_BUDGET
            if any(item.startswith("budget:") for item in blockers)
            else DryRunDisposition.BLOCKED_UNRESOLVED_AUTHORITY
            if blockers
            else DryRunDisposition.READY_FOR_CANDIDATE_TRANSACTION
        )
        provisional = cls.model_construct(**fields, envelope_fingerprint="0" * 64)
        return cls(
            **fields,
            envelope_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"envelope_fingerprint"})
            ),
        )


class DryRunImpactReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-iterative-fix-dry-run-v1"] = "pcbsmith-iterative-fix-dry-run-v1"
    source_board_file: str
    source_board_sha256_before: str
    source_board_sha256_after: str
    graph: BoardDependencyGraph
    diagnosis: BoardFindingDiagnosis
    envelope: ChangeImpactEnvelope
    source_mutated: bool
    candidate_created: bool
    acceptance_claimed: bool
    report_fingerprint: str

    @model_validator(mode="after")
    def report_is_nonmutating(self) -> Self:
        for name in (
            "source_board_sha256_before",
            "source_board_sha256_after",
            "report_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        expected_mutated = self.source_board_sha256_before != self.source_board_sha256_after
        if self.source_mutated != expected_mutated:
            raise ValueError("dry-run source mutation disposition is stale")
        if self.source_mutated or self.candidate_created or self.acceptance_claimed:
            raise ValueError("IF1 dry run cannot mutate, create a candidate, or claim acceptance")
        if self.graph.source_board_sha256 != self.source_board_sha256_before:
            raise ValueError("dry-run graph targets another board")
        if self.diagnosis.graph_fingerprint != self.graph.graph_fingerprint:
            raise ValueError("dry-run diagnosis targets another graph")
        if self.envelope.diagnosis_fingerprint != self.diagnosis.diagnosis_fingerprint:
            raise ValueError("dry-run envelope targets another diagnosis")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint", "source_board_file"})
        payload["graph"].pop("source_board_file", None)
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("dry-run report fingerprint is stale")
        return self


_DIAGNOSIS_POLICY: dict[
    FindingFamily,
    tuple[RepairOwnerStage, RepairScope, tuple[ProposedRepairClass, ...], tuple[str, ...]],
] = {
    FindingFamily.SCHEMATIC_PARITY: (
        RepairOwnerStage.SCHEMATIC_EXPORT,
        RepairScope.GLOBAL,
        (ProposedRepairClass.SCHEMATIC_IDENTITY,),
        ("erc", "schematic_parity", "package_pin_evidence"),
    ),
    FindingFamily.PIN_MAPPING: (
        RepairOwnerStage.FOOTPRINT_MAPPING,
        RepairScope.COMPONENT_NEIGHBORHOOD,
        (ProposedRepairClass.FOOTPRINT_PIN_MAP,),
        ("erc", "schematic_parity", "package_pin_evidence"),
    ),
    FindingFamily.PLACEMENT: (
        RepairOwnerStage.PLACEMENT,
        RepairScope.FUNCTIONAL_CLUSTER,
        (ProposedRepairClass.COMPONENT_MOVE_ROTATE,),
        ("placement_legality", "routing_capacity", "topology", "visual_review"),
    ),
    FindingFamily.OPEN: (
        RepairOwnerStage.ROUTING,
        RepairScope.SELECTED_NET,
        (ProposedRepairClass.SELECTED_NET_COPPER,),
        ("drc", "connectivity", "width", "return_continuity", "routing_craft"),
    ),
    FindingFamily.CLEARANCE: (
        RepairOwnerStage.ROUTING,
        RepairScope.SELECTED_REGION,
        (ProposedRepairClass.LOCAL_CLEARANCE_COPPER,),
        ("drc", "connectivity", "width", "routing_craft"),
    ),
    FindingFamily.ISOLATED_ZONE: (
        RepairOwnerStage.FILL,
        RepairScope.SELECTED_REGION,
        (ProposedRepairClass.ZONE_INTENT_REFILL,),
        ("drc", "connectivity", "final_fill", "return_continuity", "visual_review"),
    ),
    FindingFamily.STARVED_THERMAL: (
        RepairOwnerStage.FILL,
        RepairScope.SELECTED_REGION,
        (ProposedRepairClass.ZONE_INTENT_REFILL,),
        ("drc", "connectivity", "final_fill", "thermal_spokes", "visual_review"),
    ),
    FindingFamily.MARKING: (
        RepairOwnerStage.MARKING,
        RepairScope.OBJECT,
        (ProposedRepairClass.MARKING_MOVE,),
        ("drc", "production_marking", "visual_review"),
    ),
    FindingFamily.MODEL: (
        RepairOwnerStage.MODEL,
        RepairScope.OBJECT,
        (ProposedRepairClass.MODEL_ASSIGN_TRANSFORM,),
        ("model_preflight", "populated_3d_review"),
    ),
    FindingFamily.GLOBAL_CAPACITY: (
        RepairOwnerStage.ARCHITECTURE,
        RepairScope.GLOBAL,
        (ProposedRepairClass.ARCHITECTURE_ESCALATION,),
        ("restart_authority",),
    ),
}


def build_saved_board_dependency_graph(
    board_file: Path,
    *,
    require_schematic_authority: bool = False,
    supplemental_objects: tuple[DependencyObject, ...] = (),
    supplemental_edges: tuple[DependencyEdge, ...] = (),
) -> BoardDependencyGraph:
    """Extract exact observable object identities from one saved KiCad board."""

    board = board_file.resolve()
    raw = board.read_bytes()
    board_sha = hashlib.sha256(raw).hexdigest()
    root = parse_sexpr(raw.decode("utf-8"))
    if _head(root) != "kicad_pcb":
        raise ValueError("dependency graph source is not a KiCad board")
    objects: dict[str, DependencyObject] = {}
    edges: set[tuple[str, str, DependencyRelation]] = set()

    def add(
        object_id: str,
        kind: DependencyObjectKind,
        stage: RepairOwnerStage,
        node: SExpr | str,
        *,
        component_refs: tuple[str, ...] = (),
        net_names: tuple[str, ...] = (),
    ) -> None:
        node_payload = serialize_sexpr(node) if not isinstance(node, str) else node
        item = DependencyObject(
            object_id=object_id,
            object_kind=kind,
            authority_stage=stage,
            source_board_sha256=board_sha,
            source_object_fingerprint=fingerprint(node_payload),
            component_refs=component_refs,
            net_names=net_names,
        )
        previous = objects.get(object_id)
        if previous is not None and previous != item:
            raise ValueError(f"stable board object identity collision: {object_id}")
        objects[object_id] = item

    board_id = "artifact:board"
    add(board_id, DependencyObjectKind.BOARD_REVISION, RepairOwnerStage.QUALIFICATION, root)
    net_by_number: dict[str, str] = {}
    for node in _children(root, "net"):
        if len(node) >= 3:
            number, name = _atom(node[1]), _atom(node[2])
            net_by_number[number] = name
            if not name:
                continue
            net_id = f"net:{name}"
            add(
                net_id,
                DependencyObjectKind.NET,
                RepairOwnerStage.SEMANTIC_DESIGN,
                node,
                net_names=(name,),
            )
            edges.add((board_id, net_id, DependencyRelation.CONTAINS))

    for footprint in (*_children(root, "footprint"), *_children(root, "module")):
        reference = _footprint_reference(footprint)
        if reference is None:
            continue
        component_id = f"component:{reference}"
        footprint_id = f"footprint:{reference}"
        add(
            component_id,
            DependencyObjectKind.COMPONENT,
            RepairOwnerStage.SEMANTIC_DESIGN,
            reference,
            component_refs=(reference,),
        )
        add(
            footprint_id,
            DependencyObjectKind.FOOTPRINT,
            RepairOwnerStage.PLACEMENT,
            footprint,
            component_refs=(reference,),
        )
        edges.update(
            {
                (board_id, component_id, DependencyRelation.CONTAINS),
                (component_id, footprint_id, DependencyRelation.DERIVED_FROM),
            }
        )
        for ordinal, pad in enumerate(_children(footprint, "pad")):
            pad_number = _atom(pad[1]) if len(pad) > 1 else str(ordinal)
            unique = _node_uuid(pad) or f"{pad_number}:{fingerprint(serialize_sexpr(pad))[:12]}"
            pad_id = f"pad:{reference}:{unique}"
            net_name = _node_net_name(pad, net_by_number)
            add(
                pad_id,
                DependencyObjectKind.PAD,
                RepairOwnerStage.FOOTPRINT_MAPPING,
                pad,
                component_refs=(reference,),
                net_names=((net_name,) if net_name else ()),
            )
            edges.add((footprint_id, pad_id, DependencyRelation.HAS_PAD))
            if net_name and f"net:{net_name}" in objects:
                edges.add((pad_id, f"net:{net_name}", DependencyRelation.CONNECTS_TO_NET))
        reference_node = _reference_node(footprint)
        if reference_node is not None:
            mark_id = f"marking:reference:{reference}"
            add(
                mark_id,
                DependencyObjectKind.MARKING,
                RepairOwnerStage.MARKING,
                reference_node,
                component_refs=(reference,),
            )
            edges.update(
                {
                    (footprint_id, mark_id, DependencyRelation.CONTAINS),
                    (mark_id, component_id, DependencyRelation.MARKS_COMPONENT),
                }
            )
        for ordinal, model in enumerate(_children(footprint, "model")):
            model_id = f"model:{reference}:{ordinal}:{fingerprint(serialize_sexpr(model))[:12]}"
            add(
                model_id,
                DependencyObjectKind.MODEL,
                RepairOwnerStage.MODEL,
                model,
                component_refs=(reference,),
            )
            edges.add((footprint_id, model_id, DependencyRelation.USES_MODEL))

    route_kinds = {
        "segment": (DependencyObjectKind.SEGMENT, RepairOwnerStage.ROUTING),
        "arc": (DependencyObjectKind.ARC, RepairOwnerStage.ROUTING),
        "via": (DependencyObjectKind.VIA, RepairOwnerStage.ROUTING),
        "zone": (DependencyObjectKind.ZONE, RepairOwnerStage.FILL),
    }
    counters: dict[str, int] = {}
    for route_node in root:
        head = _head(route_node)
        if head not in route_kinds or not isinstance(route_node, list):
            continue
        counters[head] = counters.get(head, 0) + 1
        uuid = _node_uuid(route_node)
        identity = uuid or f"{counters[head]:04d}:{fingerprint(serialize_sexpr(route_node))[:16]}"
        object_id = f"{head}:{identity}"
        net_name = _node_net_name(route_node, net_by_number)
        kind, stage = route_kinds[head]
        add(object_id, kind, stage, route_node, net_names=((net_name,) if net_name else ()))
        edges.add((board_id, object_id, DependencyRelation.CONTAINS))
        if net_name and f"net:{net_name}" in objects:
            edges.add((object_id, f"net:{net_name}", DependencyRelation.REALIZES_NET))

    for ordinal, text_node in enumerate(_children(root, "gr_text")):
        identity = (
            _node_uuid(text_node) or f"{ordinal}:{fingerprint(serialize_sexpr(text_node))[:12]}"
        )
        marking_id = f"marking:{identity}"
        add(marking_id, DependencyObjectKind.MARKING, RepairOwnerStage.MARKING, text_node)
        edges.add((board_id, marking_id, DependencyRelation.CONTAINS))

    edge_heads = {"gr_line", "gr_arc", "gr_rect", "gr_poly", "gr_curve"}
    for ordinal, edge_node in enumerate(
        item for item in root if isinstance(item, list) and _head(item) in edge_heads
    ):
        if _node_layer(edge_node) != "Edge.Cuts":
            continue
        uuid = _node_uuid(edge_node) or (
            f"{ordinal:04d}:{fingerprint(serialize_sexpr(edge_node))[:16]}"
        )
        edge_id = f"board_edge:{uuid}"
        add(edge_id, DependencyObjectKind.BOARD_EDGE, RepairOwnerStage.PLACEMENT, edge_node)
        edges.add((board_id, edge_id, DependencyRelation.CONTAINS))

    for item in supplemental_objects:
        if item.source_board_sha256 != board_sha:
            raise ValueError("supplemental dependency object belongs to another board")
        if item.object_id in objects and item != objects[item.object_id]:
            raise ValueError("supplemental dependency object identity collision")
        objects[item.object_id] = item
    edges.update(
        (item.source_object_id, item.target_object_id, item.relation) for item in supplemental_edges
    )
    unresolved = ("schematic_dependency_authority_missing",) if require_schematic_authority else ()
    return BoardDependencyGraph.build(
        source_board_file=str(board),
        source_board_sha256=board_sha,
        objects=tuple(objects.values()),
        edges=tuple(
            DependencyEdge(source_object_id=a, target_object_id=b, relation=r) for a, b, r in edges
        ),
        observed_authority_complete=not unresolved,
        unresolved_authority_ids=unresolved,
    )


def diagnose_finding(
    graph: BoardDependencyGraph,
    observation: FindingObservation,
) -> BoardFindingDiagnosis:
    if observation.source_board_sha256 != graph.source_board_sha256:
        raise ValueError("finding observation targets another board revision")
    by_id = {item.object_id: item for item in graph.objects}
    unknown = set(observation.subject_object_ids) - set(by_id)
    unresolved: set[str] = set(graph.unresolved_authority_ids)
    unresolved.update(f"unknown_subject:{item}" for item in unknown)
    if not observation.detail_authority_complete:
        unresolved.add("finding_detail_authority_incomplete")
    owner, scope, repair_classes, gates = _DIAGNOSIS_POLICY[observation.family]
    affected = tuple(item for item in observation.subject_object_ids if item in by_id)
    adjacency: dict[str, set[str]] = {item: set() for item in by_id}
    for edge in graph.edges:
        adjacency[edge.source_object_id].add(edge.target_object_id)
        adjacency[edge.target_object_id].add(edge.source_object_id)
    protected_neighbors = tuple(
        sorted(
            {
                neighbor
                for item in affected
                for neighbor in adjacency[item]
                if neighbor not in set(affected)
            }
        )
    )
    if observation.family is FindingFamily.CLEARANCE and not observation.mutable_object_ids:
        unresolved.add("clearance_mutation_side_unresolved")
    if observation.family is FindingFamily.SCHEMATIC_PARITY:
        unresolved.add("schematic_parity_detail_required")
    return BoardFindingDiagnosis.build(
        observation=observation,
        graph_fingerprint=graph.graph_fingerprint,
        owner_stage=owner,
        scope=scope,
        affected_object_ids=affected,
        protected_neighbor_ids=protected_neighbors,
        proposed_repair_classes=repair_classes,
        required_post_change_gates=gates,
        unresolved_authority_ids=tuple(unresolved),
    )


def build_change_impact_envelope(
    graph: BoardDependencyGraph,
    diagnosis: BoardFindingDiagnosis,
    budget: ChangeImpactBudget,
) -> ChangeImpactEnvelope:
    if diagnosis.graph_fingerprint != graph.graph_fingerprint:
        raise ValueError("diagnosis targets another dependency graph")
    observation = diagnosis.observation
    by_id = {item.object_id: item for item in graph.objects}
    mutable: set[str] = set(observation.mutable_object_ids)
    if observation.family is FindingFamily.MARKING:
        mutable.update(
            item.object_id
            for item in graph.objects
            if item.object_kind is DependencyObjectKind.MARKING
            and set(item.component_refs) & set(observation.component_refs)
        )
    elif observation.family in {FindingFamily.OPEN, FindingFamily.CLEARANCE}:
        route_kinds = {
            DependencyObjectKind.SEGMENT,
            DependencyObjectKind.ARC,
            DependencyObjectKind.VIA,
        }
        if observation.family is FindingFamily.OPEN:
            mutable.update(
                item.object_id
                for item in graph.objects
                if item.object_kind in route_kinds
                and set(item.net_names) & set(observation.affected_net_names)
            )
    elif observation.family in {FindingFamily.ISOLATED_ZONE, FindingFamily.STARVED_THERMAL}:
        mutable.update(
            item.object_id
            for item in graph.objects
            if item.object_kind is DependencyObjectKind.ZONE
            and (
                item.object_id in set(observation.subject_object_ids)
                or set(item.net_names) & set(observation.affected_net_names)
            )
        )
    elif observation.family is FindingFamily.PLACEMENT:
        mutable.update(
            item.object_id
            for item in graph.objects
            if item.object_kind is DependencyObjectKind.FOOTPRINT
            and set(item.component_refs) & set(observation.component_refs)
        )
    elif observation.family is FindingFamily.MODEL:
        mutable.update(
            item.object_id
            for item in graph.objects
            if item.object_kind is DependencyObjectKind.MODEL
            and set(item.component_refs) & set(observation.component_refs)
        )
    mutable &= set(by_id)
    mutable_nets = tuple(sorted(observation.affected_net_names))
    regions = (observation.target_region_mm,) if observation.target_region_mm else ()
    copper_kinds = {
        DependencyObjectKind.SEGMENT,
        DependencyObjectKind.ARC,
        DependencyObjectKind.VIA,
        DependencyObjectKind.ZONE,
    }
    mutable_components = {ref for item_id in mutable for ref in by_id[item_id].component_refs}
    blockers = list(diagnosis.unresolved_authority_ids)
    impact_roots = {
        *diagnosis.affected_object_ids,
        *(f"net:{name}" for name in observation.affected_net_names if f"net:{name}" in by_id),
    }
    maximum_hops = _maximum_graph_hops(graph, impact_roots, mutable)
    if mutable and maximum_hops is None:
        blockers.append("impact_path_unresolved")
    budget_counts = {
        "mutable_objects": (len(mutable), budget.maximum_mutable_object_count),
        "affected_nets": (len(mutable_nets), budget.maximum_affected_net_count),
        "regions": (len(regions), budget.maximum_region_count),
        "existing_copper_objects": (
            sum(by_id[item].object_kind in copper_kinds for item in mutable),
            budget.maximum_existing_copper_object_count,
        ),
        "components": (len(mutable_components), budget.maximum_component_count),
        "graph_hops": (
            maximum_hops if maximum_hops is not None else 0,
            budget.maximum_graph_hops,
        ),
    }
    blockers.extend(
        f"budget:{name}:{observed}>{limit}"
        for name, (observed, limit) in budget_counts.items()
        if observed > limit
    )
    if not mutable and observation.family not in {
        FindingFamily.SCHEMATIC_PARITY,
        FindingFamily.PIN_MAPPING,
        FindingFamily.GLOBAL_CAPACITY,
        FindingFamily.OPEN,
    }:
        blockers.append("no_mutable_object_resolved")
    protected = ProtectedObjectInventory.build(
        source_board_sha256=graph.source_board_sha256,
        graph_fingerprint=graph.graph_fingerprint,
        objects=tuple(
            ProtectedObjectFingerprint(
                object_id=item.object_id,
                object_kind=item.object_kind,
                source_object_fingerprint=item.source_object_fingerprint,
            )
            for item in graph.objects
            if item.object_id not in mutable
        ),
    )
    consequences = tuple(
        sorted(
            {
                *(f"recheck:{gate}" for gate in diagnosis.required_post_change_gates),
                *(f"mutable_net:{name}" for name in mutable_nets),
                f"protected_object_count:{len(protected.objects)}",
            }
        )
    )
    return ChangeImpactEnvelope.build(
        source_board_sha256=graph.source_board_sha256,
        graph_fingerprint=graph.graph_fingerprint,
        diagnosis_fingerprint=diagnosis.diagnosis_fingerprint,
        mutable_object_ids=tuple(mutable),
        mutable_net_names=mutable_nets,
        mutable_regions_mm=regions,
        protected_inventory=protected,
        budget=budget,
        required_post_change_gates=diagnosis.required_post_change_gates,
        predicted_consequences=consequences,
        unknowns=diagnosis.unresolved_authority_ids,
        blocker_ids=tuple(blockers),
    )


def _maximum_graph_hops(
    graph: BoardDependencyGraph,
    roots: set[str],
    targets: set[str],
) -> int | None:
    if not targets:
        return 0
    known = {item.object_id for item in graph.objects}
    frontier = sorted(roots & known)
    if not frontier:
        return None
    distances = {item: 0 for item in frontier}
    adjacency: dict[str, set[str]] = {item: set() for item in known}
    for edge in graph.edges:
        adjacency[edge.source_object_id].add(edge.target_object_id)
        adjacency[edge.target_object_id].add(edge.source_object_id)
    cursor = 0
    while cursor < len(frontier):
        current = frontier[cursor]
        cursor += 1
        for neighbor in sorted(adjacency[current]):
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            frontier.append(neighbor)
    if not targets <= set(distances):
        return None
    return max(distances[item] for item in targets)


def generate_dry_run_impact_report(
    *,
    board_file: Path,
    observation: FindingObservation,
    budget: ChangeImpactBudget,
    require_schematic_authority: bool = False,
) -> DryRunImpactReport:
    board = board_file.resolve()
    before = hashlib.sha256(board.read_bytes()).hexdigest()
    graph = build_saved_board_dependency_graph(
        board, require_schematic_authority=require_schematic_authority
    )
    diagnosis = diagnose_finding(graph, observation)
    envelope = build_change_impact_envelope(graph, diagnosis, budget)
    after = hashlib.sha256(board.read_bytes()).hexdigest()
    fields: dict[str, Any] = {
        "source_board_file": str(board),
        "source_board_sha256_before": before,
        "source_board_sha256_after": after,
        "graph": graph,
        "diagnosis": diagnosis,
        "envelope": envelope,
        "source_mutated": before != after,
        "candidate_created": False,
        "acceptance_claimed": False,
    }
    provisional = DryRunImpactReport.model_construct(**fields, report_fingerprint="0" * 64)
    payload = provisional.model_dump(
        mode="json", exclude={"report_fingerprint", "source_board_file"}
    )
    payload["graph"].pop("source_board_file", None)
    return DryRunImpactReport(
        **fields,
        report_fingerprint=fingerprint(payload),
    )


def protected_inventory_matches(
    inventory: ProtectedObjectInventory,
    graph: BoardDependencyGraph,
) -> bool:
    if inventory.source_board_sha256 != graph.source_board_sha256:
        return False
    by_id = {item.object_id: item for item in graph.objects}
    return all(
        item.object_id in by_id
        and by_id[item.object_id].object_kind is item.object_kind
        and by_id[item.object_id].source_object_fingerprint == item.source_object_fingerprint
        for item in inventory.objects
    )


def _children(node: list[SExpr], head: str) -> tuple[list[SExpr], ...]:
    return tuple(item for item in node if isinstance(item, list) and _head(item) == head)


def _head(node: object) -> str:
    return _atom(node[0]) if isinstance(node, list) and node else ""


def _atom(value: object) -> str:
    if isinstance(value, QuotedString):
        return value.value
    return str(value)


def _first_child(node: list[SExpr], *heads: str) -> list[SExpr] | None:
    return next(
        (item for item in node if isinstance(item, list) and _head(item) in heads),
        None,
    )


def _node_uuid(node: list[SExpr]) -> str | None:
    child = _first_child(node, "uuid", "tstamp")
    return _atom(child[1]) if child is not None and len(child) > 1 else None


def _node_layer(node: list[SExpr]) -> str | None:
    child = _first_child(node, "layer")
    return _atom(child[1]) if child is not None and len(child) > 1 else None


def _node_net_name(node: list[SExpr], net_by_number: dict[str, str]) -> str | None:
    child = _first_child(node, "net", "net_name")
    if child is None or len(child) < 2:
        return None
    if len(child) >= 3:
        return _atom(child[2])
    value = _atom(child[1])
    return net_by_number.get(value, value if value not in {"0", ""} else None)


def _reference_node(footprint: list[SExpr]) -> list[SExpr] | None:
    for item in footprint:
        if not isinstance(item, list):
            continue
        if _head(item) == "property" and len(item) >= 3 and _atom(item[1]) == "Reference":
            return item
        if _head(item) == "fp_text" and len(item) >= 3 and _atom(item[1]) == "reference":
            return item
    return None


def _footprint_reference(footprint: list[SExpr]) -> str | None:
    node = _reference_node(footprint)
    return _atom(node[2]) if node is not None and len(node) >= 3 else None


__all__ = [
    "BoardDependencyGraph",
    "BoardFindingDiagnosis",
    "ChangeImpactBudget",
    "ChangeImpactEnvelope",
    "DependencyEdge",
    "DependencyObject",
    "DependencyObjectKind",
    "DependencyRelation",
    "DryRunDisposition",
    "DryRunImpactReport",
    "FindingFamily",
    "FindingObservation",
    "ProposedRepairClass",
    "ProtectedObjectFingerprint",
    "ProtectedObjectInventory",
    "RepairOwnerStage",
    "RepairScope",
    "build_change_impact_envelope",
    "build_saved_board_dependency_graph",
    "diagnose_finding",
    "generate_dry_run_impact_report",
    "protected_inventory_matches",
]
