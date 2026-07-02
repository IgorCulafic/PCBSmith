from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pcbsmith.circuit.models import RevisionRecord

_FAILURE_ROUTES = {
    "evidence_missing": (
        ("Evidence cache or part selection",),
        ("evidence_lookup",),
        "Fetch or request the missing evidence before changing the schematic.",
    ),
    "math_mismatch": (
        ("Circuit object values or deterministic calculators",),
        ("math_gate",),
        "Recalculate values and update the existing circuit object.",
    ),
    "kicad_failed": (
        ("KiCad schematic or symbol mapping",),
        ("kicad_erc", "kicad_spice_export"),
        "Patch the existing KiCad schematic or symbol mapping.",
    ),
    "simulation_failed": (
        ("SPICE model, simulation setup, or circuit values",),
        ("ngspice",),
        "Patch the simulation setup or circuit values and rerun ngspice.",
    ),
    "reconciliation_failed": (
        ("Translation boundary between PCBSmith, KiCad, and ngspice",),
        ("reconciliation",),
        "Patch the mismatched translation layer.",
    ),
    "board_failed": (
        ("Board generator placement, routing, or footprint geometry",),
        ("kicad_drc",),
        "Patch the generated board layout and rerun KiCad DRC.",
    ),
}


def revision_for_authority_failure(
    *,
    revision_id: str,
    parent_revision_id: str | None,
    failure_code: str,
    findings: tuple[str, ...],
) -> RevisionRecord:
    try:
        changed_artifacts, checks, next_action = _FAILURE_ROUTES[failure_code]
    except KeyError as exc:
        raise ValueError(f"Unknown authority failure code: {failure_code}") from exc

    return RevisionRecord(
        revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        changed_artifacts=changed_artifacts,
        authority_checks=checks,
        findings=findings,
        next_action=next_action,
    )


def should_stop_revision_loop(failure_codes: Iterable[str], *, limit: int = 3) -> bool:
    if limit <= 0:
        raise ValueError("Revision loop limit must be positive.")

    counts = Counter(failure_codes)
    return any(count >= limit for count in counts.values())
