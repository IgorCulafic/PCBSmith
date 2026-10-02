"""Fail-closed schematic/parity analysis and isolated repair transactions.

The analyzer converts KiCad's detailed schematic-parity objects into stable,
component-local authority records.  It deliberately distinguishes namespace
differences from actual pin/net conflicts and never treats warning severity as
permission to mutate a project.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(value: object) -> str:
    def default(item: object) -> object:
        if isinstance(item, SemanticIrModel):
            return item.model_dump(mode="json")
        if isinstance(item, StrEnum):
            return item.value
        raise TypeError(f"unsupported fingerprint value: {type(item).__name__}")

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=default).encode("utf-8")
    ).hexdigest()


class ParityAuthority(StrEnum):
    METADATA_LOCAL = "metadata_local"
    NAMESPACE_LOCAL = "namespace_local"
    COMPONENT_MAP_REQUIRED = "component_map_required"
    PROJECT_TOPOLOGY_REQUIRED = "project_topology_required"
    UNKNOWN = "unknown"


class ParityItem(SemanticIrModel):
    schema_id: Literal["pcbsmith-parity-item"] = "pcbsmith-parity-item"
    schema_version: Literal[1] = 1
    item_id: str
    finding_type: str
    description: str
    severity: str
    references: tuple[str, ...] = ()
    pad_numbers: tuple[str, ...] = ()
    pcb_nets: tuple[str, ...] = ()
    schematic_nets: tuple[str, ...] = ()
    authority: ParityAuthority
    blocker_id: str | None = None


class ParityEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-parity-evidence"] = "pcbsmith-parity-evidence"
    schema_version: Literal[1] = 1
    report_sha256: str
    items: tuple[ParityItem, ...]
    type_counts: tuple[tuple[str, int], ...]
    component_blockers: tuple[str, ...]
    evidence_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        expected_counts = tuple(sorted(Counter(item.finding_type for item in self.items).items()))
        if self.type_counts != expected_counts:
            raise ValueError("parity type counts are stale")
        expected_blockers = tuple(
            sorted({item.blocker_id for item in self.items if item.blocker_id is not None})
        )
        if self.component_blockers != expected_blockers:
            raise ValueError("parity component blockers are stale")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != _fingerprint(payload):
            raise ValueError("parity evidence fingerprint is stale")
        return self

    @classmethod
    def build(cls, *, report_sha256: str, items: tuple[ParityItem, ...]) -> ParityEvidence:
        ordered = tuple(sorted(items, key=lambda item: item.item_id))
        fields: dict[str, Any] = {
            "report_sha256": report_sha256,
            "items": ordered,
            "type_counts": tuple(sorted(Counter(item.finding_type for item in ordered).items())),
            "component_blockers": tuple(
                sorted({item.blocker_id for item in ordered if item.blocker_id is not None})
            ),
        }
        provisional = cls.model_construct(**fields, evidence_fingerprint="0" * 64)
        payload = provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        return cls(**fields, evidence_fingerprint=_fingerprint(payload))


_REF_RE = re.compile(r"(?:Footprint |Missing footprint | of )([A-Za-z]+[A-Za-z0-9_.-]*)")
_PAD_RE = re.compile(r"Pad ([^ ]+)")
_NET_RE = re.compile(r"Pad net \((.*?)\) doesn't match net given by schematic \((.*?)\)")


def _canonical_net(name: str) -> str:
    return name.lstrip("/")


def parse_kicad_parity_report(path: Path) -> ParityEvidence:
    """Read detailed KiCad JSON; count-only evidence is intentionally rejected."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload.get("schematic_parity")
    if not isinstance(raw_items, list):
        raise ValueError("detailed schematic_parity array is required")
    items: list[ParityItem] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            raise ValueError(f"schematic_parity[{index}] must be an object")
        finding_type = str(raw.get("type", "unknown"))
        description = str(raw.get("description", ""))
        nested = raw.get("items", [])
        nested_descriptions = [
            str(item.get("description", "")) for item in nested if isinstance(item, Mapping)
        ]
        refs = tuple(sorted(set(_REF_RE.findall(" ".join([description, *nested_descriptions])))))
        pads = tuple(sorted(set(_PAD_RE.findall(" ".join(nested_descriptions)))))
        pcb_nets: tuple[str, ...] = ()
        schematic_nets: tuple[str, ...] = ()
        net_match = _NET_RE.search(description)
        if net_match:
            pcb_nets = (net_match.group(1),)
            schematic_nets = (net_match.group(2),)
        authority = ParityAuthority.UNKNOWN
        blocker: str | None = None
        if finding_type == "footprint_symbol_field_mismatch":
            authority = ParityAuthority.METADATA_LOCAL
        elif finding_type == "net_conflict" and pcb_nets and schematic_nets:
            if _canonical_net(pcb_nets[0]) == _canonical_net(schematic_nets[0]):
                authority = ParityAuthority.NAMESPACE_LOCAL
            else:
                authority = ParityAuthority.COMPONENT_MAP_REQUIRED
                ref = refs[0] if refs else "unknown"
                pad = pads[0] if pads else "unknown"
                blocker = (
                    f"component_map:{ref}:pad:{pad}:pcb:{pcb_nets[0]}:schematic:{schematic_nets[0]}"
                )
        elif finding_type in {"footprint_symbol_mismatch", "missing_footprint"}:
            authority = ParityAuthority.COMPONENT_MAP_REQUIRED
            ref = refs[0] if refs else "unknown"
            blocker = f"component_map:{ref}:{finding_type}"
        elif finding_type == "extra_footprint":
            authority = ParityAuthority.PROJECT_TOPOLOGY_REQUIRED
            ref = refs[0] if refs else "unknown"
            blocker = f"project_topology:{ref}:extra_footprint"
        else:
            blocker = f"parity_unknown:{finding_type}:{index}"
        stable = {
            "finding_type": finding_type,
            "description": description,
            "references": refs,
            "pad_numbers": pads,
        }
        items.append(
            ParityItem(
                item_id=f"parity-{_fingerprint(stable)[:16]}",
                finding_type=finding_type,
                description=description,
                severity=str(raw.get("severity", "unknown")),
                references=refs,
                pad_numbers=pads,
                pcb_nets=pcb_nets,
                schematic_nets=schematic_nets,
                authority=authority,
                blocker_id=blocker,
            )
        )
    return ParityEvidence.build(report_sha256=_sha(path), items=tuple(items))


class ParityDelta(SemanticIrModel):
    schema_id: Literal["pcbsmith-parity-delta"] = "pcbsmith-parity-delta"
    schema_version: Literal[1] = 1
    before_count: int = Field(ge=0)
    after_count: int = Field(ge=0)
    removed_item_ids: tuple[str, ...]
    added_item_ids: tuple[str, ...]
    retained_item_ids: tuple[str, ...]


def compare_parity(before: ParityEvidence, after: ParityEvidence) -> ParityDelta:
    before_ids = {item.item_id for item in before.items}
    after_ids = {item.item_id for item in after.items}
    return ParityDelta(
        before_count=len(before_ids),
        after_count=len(after_ids),
        removed_item_ids=tuple(sorted(before_ids - after_ids)),
        added_item_ids=tuple(sorted(after_ids - before_ids)),
        retained_item_ids=tuple(sorted(before_ids & after_ids)),
    )


class ParityTransactionResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-parity-transaction-result"] = "pcbsmith-parity-transaction-result"
    schema_version: Literal[1] = 1
    source_hashes: tuple[tuple[str, str], ...]
    candidate_hashes: tuple[tuple[str, str], ...]
    changed_paths: tuple[str, ...]
    copper_changed: bool
    delta: ParityDelta
    accepted: bool
    blockers: tuple[str, ...]
    retained_directory: str


def run_parity_candidate_transaction(
    *,
    project_files: tuple[Path, ...],
    before_report: Path,
    retained_root: Path,
    mutator: Callable[[Path], None],
    validator: Callable[[Path], Path],
    copper_change_authorized: bool = False,
) -> ParityTransactionResult:
    """Mutate an isolated project copy and retain it whether accepted or rejected."""

    common = (
        Path(os.path.commonpath(project_files))
        if len(project_files) > 1
        else project_files[0].parent
    )
    source_hashes = tuple(
        sorted((str(path.relative_to(common)), _sha(path)) for path in project_files)
    )
    retained_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pcbsmith-parity-") as temporary:
        candidate_root = Path(temporary) / "candidate"
        candidate_root.mkdir()
        for source in project_files:
            relative = source.relative_to(common)
            destination = candidate_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        mutator(candidate_root)
        after_report = validator(candidate_root)
        before = parse_kicad_parity_report(before_report)
        after = parse_kicad_parity_report(after_report)
        candidate_hashes = tuple(
            sorted(
                (str(path.relative_to(candidate_root)), _sha(path))
                for path in candidate_root.rglob("*")
                if path.is_file() and path.suffix in {".kicad_pcb", ".kicad_sch", ".kicad_pro"}
            )
        )
        source_map = dict(source_hashes)
        candidate_map = dict(candidate_hashes)
        changed = tuple(
            sorted(path for path, digest in candidate_map.items() if source_map.get(path) != digest)
        )
        copper_changed = any(path.endswith(".kicad_pcb") for path in changed)
        blockers: list[str] = []
        if copper_changed and not copper_change_authorized:
            blockers.append("unauthorized_physical_copper_change")
        if after.component_blockers:
            blockers.extend(after.component_blockers)
        delta = compare_parity(before, after)
        if delta.added_item_ids:
            blockers.append("parity_regression")
        accepted = not blockers and after.items == ()
        destination = retained_root / f"candidate-{_fingerprint(candidate_hashes)[:12]}"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(candidate_root, destination)
    if any(
        _sha(path) != digest for path, digest in ((common / rel, sha) for rel, sha in source_hashes)
    ):
        raise RuntimeError("parity transaction mutated its source project")
    return ParityTransactionResult(
        source_hashes=source_hashes,
        candidate_hashes=candidate_hashes,
        changed_paths=changed,
        copper_changed=copper_changed,
        delta=delta,
        accepted=accepted,
        blockers=tuple(sorted(set(blockers))),
        retained_directory=str(destination),
    )
