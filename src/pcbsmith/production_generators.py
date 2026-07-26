"""Registered, fail-closed publication boundary for KiCad board generators.

Board builders intentionally remain pure file generators.  This module is the
single boundary that decides whether one of those builders may publish a
placement or routed production candidate.  Registration is explicit so a new
generator cannot silently bypass the Phase 17 transaction workflow.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pcbsmith.component_review_execution import ProjectComponentReviewExecution
from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.production_workflow import (
    PlacementReviewTransactionResult,
    RoutedReviewTransactionResult,
    persist_placement_and_generate_review,
    persist_routed_board_and_generate_review,
)
from pcbsmith.review.visual_package import VisualReviewManifest


class GeneratorPublicationCapability(StrEnum):
    """Highest candidate stage a registered builder may publish."""

    PLACEMENT = "placement"
    ROUTED = "routed"


@dataclass(frozen=True)
class GeneratorRegistration:
    generator_id: str
    module: str
    entrypoint: str
    capability: GeneratorPublicationCapability
    notes: str

    @property
    def source_relative_path(self) -> str:
        return self.module.replace(".", "/") + ".py"


@dataclass(frozen=True)
class GeneratorRegistryAudit:
    discovered_ids: tuple[str, ...]
    registered_ids: tuple[str, ...]
    unregistered_ids: tuple[str, ...]
    stale_registration_ids: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.unregistered_ids and not self.stale_registration_ids


def _registration(
    module_name: str,
    entrypoint: str,
    capability: GeneratorPublicationCapability,
    notes: str,
) -> GeneratorRegistration:
    module = f"pcbsmith.kicad.{module_name}"
    return GeneratorRegistration(
        generator_id=f"{module}:{entrypoint}",
        module=module,
        entrypoint=entrypoint,
        capability=capability,
        notes=notes,
    )


_PLACEMENT = GeneratorPublicationCapability.PLACEMENT
_ROUTED = GeneratorPublicationCapability.ROUTED

# Every public board-builder entrypoint under pcbsmith.kicad is listed here.
# An AST inventory test makes this list fail when a builder is added, renamed,
# or removed without an explicit migration decision.
GENERATOR_REGISTRY: tuple[GeneratorRegistration, ...] = (
    _registration(
        "bldc_esc_board",
        "generate_bldc_esc_placement_board",
        _PLACEMENT,
        "BLDC ESC visual-placement study; routing was never established.",
    ),
    _registration(
        "bldc_esc_r002_board",
        "generate_bldc_esc_r002_board",
        _PLACEMENT,
        "Cooling-review placement study; not a routed production candidate.",
    ),
    _registration(
        "board",
        "generate_board",
        _PLACEMENT,
        "Generic board serializer; routed status requires a dedicated routed builder.",
    ),
    _registration(
        "clover_board",
        "generate_clover_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "flyback_board",
        "generate_flyback_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "led_art_board",
        "generate_led_art_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "metal_detector_board",
        "generate_detector_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "pear_board",
        "generate_pear_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "protocol_analyzer_8ch_board",
        "generate_protocol_analyzer_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "protocol_analyzer_8ch_board",
        "generate_protocol_analyzer_routed_board",
        _ROUTED,
        "Explicit routed builder; saved-board inspection remains authoritative.",
    ),
    _registration(
        "protocol_analyzer_8ch_r002_board",
        "generate_protocol_analyzer_r002_placement_board",
        _PLACEMENT,
        "R002 compaction remains an unrouted placement candidate.",
    ),
    _registration(
        "retro_pad_3x3_board",
        "generate_retro_pad_3x3_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "retro_pad_3x3_board",
        "generate_retro_pad_3x3_routed_board",
        _ROUTED,
        "Explicit routed builder; saved-board inspection remains authoritative.",
    ),
    _registration(
        "retro_pad_board",
        "generate_retro_pad_board",
        _ROUTED,
        "Original routed Retro-Pad builder retained behind objective route inspection.",
    ),
    _registration(
        "retro_pad_board",
        "generate_retro_pad_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "retro_pad_r003_board",
        "generate_retro_pad_r003_placement_board",
        _PLACEMENT,
        "Explicit placement candidate.",
    ),
    _registration(
        "retro_pad_r003_board",
        "generate_retro_pad_r003_routed_board",
        _ROUTED,
        "Explicit routed builder; saved-board inspection remains authoritative.",
    ),
    _registration(
        "servo555_board",
        "generate_servo555_board",
        _PLACEMENT,
        "Legacy topology builder migrated to placement publication only.",
    ),
    _registration(
        "thermometer_board",
        "generate_thermometer_board",
        _PLACEMENT,
        "Completed historical board retained as placement-only legacy evidence.",
    ),
)

_REGISTRY_BY_ID = {item.generator_id: item for item in GENERATOR_REGISTRY}
if len(_REGISTRY_BY_ID) != len(GENERATOR_REGISTRY):
    raise RuntimeError("production generator registry contains duplicate IDs")


def registered_generator(generator_id: str) -> GeneratorRegistration:
    try:
        return _REGISTRY_BY_ID[generator_id]
    except KeyError as exc:
        raise ValueError(
            f"unregistered board generator {generator_id!r}; publication is blocked"
        ) from exc


def discover_board_generator_ids(kicad_source_dir: Path) -> tuple[str, ...]:
    """Discover public board entrypoints without importing generator modules."""

    discovered: list[str] = []
    for source in sorted(kicad_source_dir.glob("*board.py")):
        module = f"pcbsmith.kicad.{source.stem}"
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith(("generate_", "build_")) and node.name.endswith("board"):
                discovered.append(f"{module}:{node.name}")
    return tuple(sorted(discovered))


def audit_generator_registry(kicad_source_dir: Path) -> GeneratorRegistryAudit:
    discovered = discover_board_generator_ids(kicad_source_dir)
    registered = tuple(sorted(_REGISTRY_BY_ID))
    return GeneratorRegistryAudit(
        discovered_ids=discovered,
        registered_ids=registered,
        unregistered_ids=tuple(sorted(set(discovered) - set(registered))),
        stale_registration_ids=tuple(sorted(set(registered) - set(discovered))),
    )


def persist_registered_placement_candidate(
    *,
    generator_id: str,
    transaction_root: Path,
    project_id: str,
    generation_id: str,
    generation_sha256: str,
    board_relative_path: str,
    board_payload: bytes,
    review_generator: Callable[[Path, Path], VisualReviewManifest],
    component_review_generator: Callable[[Path], ProjectComponentReviewExecution],
    support_payloads: Mapping[str, bytes] | None = None,
) -> PlacementReviewTransactionResult:
    """Publish one registered builder's placement candidate atomically."""

    registered_generator(generator_id)
    return persist_placement_and_generate_review(
        transaction_root=transaction_root,
        project_id=project_id,
        generation_id=generation_id,
        generation_sha256=generation_sha256,
        board_relative_path=board_relative_path,
        board_payload=board_payload,
        review_generator=review_generator,
        component_review_generator=component_review_generator,
        support_payloads=support_payloads,
    )


def persist_registered_routed_candidate(
    *,
    generator_id: str,
    transaction_root: Path,
    project_id: str,
    generation_id: str,
    generation_sha256: str,
    board_relative_path: str,
    board_payload: bytes,
    review_generator: Callable[[Path, Path], VisualReviewManifest],
    drc_generator: Callable[[Path, Path], None],
    support_payloads: Mapping[str, bytes] | None = None,
) -> RoutedReviewTransactionResult:
    """Publish a routed candidate only from an explicitly routed-capable builder."""

    registration = registered_generator(generator_id)
    if registration.capability is not GeneratorPublicationCapability.ROUTED:
        raise ValueError(
            f"generator {generator_id!r} is registered for placement publication only"
        )
    return persist_routed_board_and_generate_review(
        transaction_root=transaction_root,
        project_id=project_id,
        generation_id=generation_id,
        generation_sha256=generation_sha256,
        board_relative_path=board_relative_path,
        board_payload=board_payload,
        review_generator=review_generator,
        drc_generator=drc_generator,
        support_payloads=support_payloads,
    )


def generate_nonmutating_kicad_drc(
    board_file: Path,
    report_file: Path,
    *,
    schematic_parity: bool = True,
) -> None:
    """Retain exact KiCad JSON DRC without rewriting the inspected board.

    Production transactions bind model preflight, routing evidence, review,
    and DRC to one byte-exact board.  KiCad's ``--save-board`` option is
    therefore deliberately excluded here.
    """

    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI is required for production DRC")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.unlink(missing_ok=True)
    parity = ("--schematic-parity",) if schematic_parity else ()
    command = (
        str(install.path),
        "pcb",
        "drc",
        "--format",
        "json",
        "--output",
        str(report_file),
        *parity,
        "--refill-zones",
        str(board_file),
    )
    result = run_kicad_process(command)
    if not report_file.is_file():
        detail = result.stderr.strip() or result.stdout.strip() or "KiCad DRC failed"
        raise RuntimeError(f"KiCad DRC did not retain JSON: {detail}")


__all__ = [
    "GENERATOR_REGISTRY",
    "GeneratorPublicationCapability",
    "GeneratorRegistration",
    "GeneratorRegistryAudit",
    "audit_generator_registry",
    "discover_board_generator_ids",
    "generate_nonmutating_kicad_drc",
    "persist_registered_placement_candidate",
    "persist_registered_routed_candidate",
    "registered_generator",
]
