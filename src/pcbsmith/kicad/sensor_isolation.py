"""Opt-in KiCad adapter for exact R6.1b sensor-isolation fabrication checks."""

from __future__ import annotations

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.rule_profiles import PcbRuleProfile
from pcbsmith.semantic_ir import SemanticEvaluationContext
from pcbsmith.sensor_isolation_ir import (
    SensorIsolationCatalog,
    SensorIsolationEvaluationResult,
)


def evaluate_sensor_isolation_fabrication(
    layout: BoardLayout,
    catalog: SensorIsolationCatalog,
    context: SemanticEvaluationContext,
    *,
    rule_profile: PcbRuleProfile,
) -> SensorIsolationEvaluationResult:
    """Evaluate only explicit slot/web/tab geometry against selected process limits."""

    outline_points = layout.outline or (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    board_outline = ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=outline_points),))
    cutouts = tuple(
        ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=item.points),))
        for item in layout.cutouts
    )
    return SensorIsolationEvaluationResult.build(
        context=context,
        catalog=catalog,
        fabrication_profile=rule_profile.geometry,
        board_layout_fingerprint=board_layout_fingerprint(layout),
        board_outline=board_outline,
        live_cutouts=cutouts,
    )
