from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from pcbsmith.core.geom import mm_to_nm
from pcbsmith.ui.items import CANVAS_BACKGROUND, GRID_COLOR

GRID_NM = 2_540_000
ZOOM_IN_FACTOR = 1.15
ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR


class SchematicView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        half_extent = mm_to_nm(500)
        extent = mm_to_nm(1000)
        default_rect = QRectF(-half_extent, -half_extent, extent, extent)
        scene.setSceneRect(default_rect)

        super().__init__(scene, parent)
        self._last_pan_pos: QPoint | None = None
        scene.setBackgroundBrush(CANVAS_BACKGROUND)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)

        left = math.floor(rect.left() / GRID_NM) * GRID_NM
        top = math.floor(rect.top() / GRID_NM) * GRID_NM

        painter.save()
        painter.setPen(QPen(GRID_COLOR, 0))

        x = left
        while x <= rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += GRID_NM

        y = top
        while y <= rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += GRID_NM

        painter.restore()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = ZOOM_IN_FACTOR if event.angleDelta().y() > 0 else ZOOM_OUT_FACTOR
            self.scale(factor, factor)
            event.accept()
            return

        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._last_pan_pos = event.position().toPoint()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_pan_pos is not None:
            current_pos = event.position().toPoint()
            delta = current_pos - self._last_pan_pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._last_pan_pos = current_pos
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._last_pan_pos is not None:
            self._last_pan_pos = None
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def fit_to_contents(self) -> None:
        scene = self.scene()
        target = scene.itemsBoundingRect()
        if not scene.items():
            target = scene.sceneRect()
        else:
            target = target.adjusted(-GRID_NM, -GRID_NM, GRID_NM, GRID_NM)

        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)


__all__ = [
    "GRID_NM",
    "SchematicView",
    "ZOOM_IN_FACTOR",
    "ZOOM_OUT_FACTOR",
]
