"""Deterministic geometric design checks over a computed board layout.

Each check encodes a rule from docs/pcb-design-rules.md that was originally
discovered by visual review. Once a visual finding is expressible as geometry
it is promoted here so it never needs eyes again; the model reviewer only
handles what cannot be computed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pcbsmith.circuit.models import DesignReviewReport, ReviewFinding
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    PART_GAP_MM,
    BoardLayout,
    BoardNetlist,
)

CONNECTOR_EDGE_ZONE_MM = 6.0
SWITCHING_CLUSTER_SLACK_MM = 6.0


@dataclass(frozen=True)
class DesignChecksSpec:
    """Topology-provided parameters for the geometric checks."""

    switching_cluster_refs: tuple[str, ...] = ()
    sensitive_net_names: tuple[str, ...] = ()
    inductor_references: tuple[str, ...] = ()
    extra_model_findings: tuple[ReviewFinding, ...] = field(default=())


def run_design_checks(
    layout: BoardLayout,
    netlist: BoardNetlist,
    spec: DesignChecksSpec,
) -> DesignReviewReport:
    checks_run: list[str] = []
    findings: list[ReviewFinding] = []

    checks_run.append("connector_edge")
    findings.extend(_check_connector_edges(layout))

    if spec.switching_cluster_refs:
        checks_run.append("switching_cluster")
        findings.extend(_check_switching_cluster(layout, spec.switching_cluster_refs))

    if spec.sensitive_net_names and spec.inductor_references:
        checks_run.append("sensitive_net_under_inductor")
        findings.extend(
            _check_sensitive_net_under_inductor(
                layout,
                spec.sensitive_net_names,
                spec.inductor_references,
            )
        )

    findings.extend(spec.extra_model_findings)

    if any(finding.severity == "blocker" for finding in findings):
        status = "failed"
    elif findings:
        status = "needs_human_review"
    else:
        status = "passed"
    return DesignReviewReport(
        status=status,
        checks_run=tuple(checks_run),
        findings=tuple(findings),
    )


def _check_connector_edges(layout: BoardLayout) -> tuple[ReviewFinding, ...]:
    findings: list[ReviewFinding] = []
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if not spec.is_connector:
            continue
        pad_xs = [anchor_x + pad.x_mm for pad in spec.pads]
        near_left = min(pad_xs) <= CONNECTOR_EDGE_ZONE_MM
        near_right = max(pad_xs) >= layout.width_mm - CONNECTOR_EDGE_ZONE_MM
        if not (near_left or near_right):
            findings.append(
                ReviewFinding(
                    rule="1.1",
                    severity="blocker",
                    scope="component",
                    where=component.reference,
                    evidence=(
                        f"{component.reference} pads sit at x="
                        f"{min(pad_xs):.1f}-{max(pad_xs):.1f}mm on a "
                        f"{layout.width_mm:.1f}mm wide board, more than "
                        f"{CONNECTOR_EDGE_ZONE_MM:g}mm from both edges."
                    ),
                    suggested_action=(
                        "Assign the connector to the leading (left) or trailing "
                        "(right) edge group in the placer."
                    ),
                    source="check",
                )
            )
    return tuple(findings)


def _check_switching_cluster(
    layout: BoardLayout,
    cluster_refs: tuple[str, ...],
) -> tuple[ReviewFinding, ...]:
    members = [
        (component, anchor_x)
        for component, anchor_x in layout.placements
        if component.reference in cluster_refs
    ]
    if len(members) < 2:
        return ()
    extents = [
        (
            anchor_x + FOOTPRINT_LIBRARY[component.footprint].x_min,
            anchor_x + FOOTPRINT_LIBRARY[component.footprint].x_max,
        )
        for component, anchor_x in members
    ]
    span = max(right for _, right in extents) - min(left for left, _ in extents)
    budget = (
        sum(right - left for left, right in extents)
        + (len(members) - 1) * PART_GAP_MM
        + SWITCHING_CLUSTER_SLACK_MM
    )
    if span <= budget:
        return ()
    return (
        ReviewFinding(
            rule="3.1",
            severity="blocker",
            scope="region",
            where=", ".join(sorted(cluster_refs)),
            evidence=(
                f"Switching-loop cluster spans {span:.1f}mm but adjacent "
                f"placement needs only {budget:.1f}mm; parts outside the loop "
                "are interleaved into the high di/dt path."
            ),
            suggested_action=(
                "Increase the power-net span weight or pin the cluster "
                "adjacent in the row order."
            ),
            source="check",
        ),
    )


def _check_sensitive_net_under_inductor(
    layout: BoardLayout,
    sensitive_net_names: tuple[str, ...],
    inductor_references: tuple[str, ...],
) -> tuple[ReviewFinding, ...]:
    sensitive = {name.lstrip("/").upper() for name in sensitive_net_names}
    inductor_extents = [
        (
            component.reference,
            anchor_x + FOOTPRINT_LIBRARY[component.footprint].x_min,
            anchor_x + FOOTPRINT_LIBRARY[component.footprint].x_max,
        )
        for component, anchor_x in layout.placements
        if component.reference in inductor_references
    ]
    findings: list[ReviewFinding] = []
    for segment in layout.segments:
        if segment.layer != "B.Cu":
            continue
        if segment.net_name.lstrip("/").upper() not in sensitive:
            continue
        seg_left, seg_right = sorted((segment.x1, segment.x2))
        for reference, left, right in inductor_extents:
            if seg_left < right and seg_right > left:
                findings.append(
                    ReviewFinding(
                        rule="3.3",
                        severity="warning",
                        scope="net",
                        where=f"{segment.net_name} under {reference}",
                        evidence=(
                            f"The {segment.net_name} lane on B.Cu spans "
                            f"{seg_left:.1f}-{seg_right:.1f}mm and passes under "
                            f"{reference} ({left:.1f}-{right:.1f}mm); inductor "
                            "flux can couple into the high-impedance node."
                        ),
                        suggested_action=(
                            "Route the sensitive net clear of the inductor "
                            "body, or specify a shielded inductor and record "
                            "that evidence."
                        ),
                        source="check",
                    )
                )
    return tuple(findings)
