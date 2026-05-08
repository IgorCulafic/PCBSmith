from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene

from pcbsmith.core.geom import mm_to_nm
from pcbsmith.ui.schematic_view import (
    GRID_NM,
    SchematicView,
    ZOOM_IN_FACTOR,
    ZOOM_OUT_FACTOR,
)


def test_view_has_expected_navigation_defaults(qtbot) -> None:  # type: ignore[no-untyped-def]
    scene = QGraphicsScene()
    view = SchematicView(scene)
    qtbot.addWidget(view)

    assert view.dragMode() == SchematicView.DragMode.NoDrag
    assert view.transformationAnchor() == SchematicView.ViewportAnchor.AnchorUnderMouse
    assert view.resizeAnchor() == SchematicView.ViewportAnchor.AnchorUnderMouse
    assert view.renderHints() & QPainter.RenderHint.Antialiasing
    assert view.renderHints() & QPainter.RenderHint.TextAntialiasing
    assert GRID_NM == 2_540_000
    assert ZOOM_IN_FACTOR == 1.15
    assert ZOOM_OUT_FACTOR == 1 / ZOOM_IN_FACTOR
    assert view.sceneRect() == QRectF(
        -mm_to_nm(500),
        -mm_to_nm(500),
        mm_to_nm(1000),
        mm_to_nm(1000),
    )
    assert scene.sceneRect() == view.sceneRect()


def test_fit_to_contents_changes_transform(qtbot) -> None:  # type: ignore[no-untyped-def]
    scene = QGraphicsScene()
    scene.addItem(QGraphicsRectItem(QRectF(-1_000_000, -1_000_000, 2_000_000, 2_000_000)))
    view = SchematicView(scene)
    view.resize(400, 300)
    qtbot.addWidget(view)

    before = view.transform()
    view.fit_to_contents()

    assert view.transform() != before


def test_fit_to_contents_uses_unpadded_scene_rect_when_empty(
    qtbot,
) -> None:  # type: ignore[no-untyped-def]
    class RecordingSchematicView(SchematicView):
        fitted_rect: QRectF | None = None

        def fitInView(self, rect, aspect_ratio_mode) -> None:  # type: ignore[no-untyped-def]
            self.fitted_rect = QRectF(rect)
            super().fitInView(rect, aspect_ratio_mode)

    scene = QGraphicsScene()
    view = RecordingSchematicView(scene)
    view.resize(400, 300)
    qtbot.addWidget(view)

    view.fit_to_contents()

    assert view.fitted_rect == view.sceneRect()
