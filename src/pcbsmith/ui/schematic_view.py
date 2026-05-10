from __future__ import annotations

import math
from typing import Literal

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QShowEvent, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from pcbsmith.core.geom import mm_to_nm
from pcbsmith.ui.items import CANVAS_BACKGROUND, GRID_COLOR

GRID_NM = 2_540_000
DEFAULT_VIEW_WIDTH_MM = 160
DEFAULT_VIEW_HEIGHT_MM = 100
ZOOM_IN_FACTOR = 1.15
ZOOM_OUT_FACTOR = 1 / ZOOM_IN_FACTOR
GridUnit = Literal["mm", "cm"]


class SchematicView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        half_extent = mm_to_nm(500)
        extent = mm_to_nm(1000)
        default_rect = QRectF(-half_extent, -half_extent, extent, extent)
        scene.setSceneRect(default_rect)

        super().__init__(scene, parent)
        self._last_pan_pos: QPoint | None = None
        self._grid_unit: GridUnit = "mm"
        self._did_initial_fit = False
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

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)

        painter.save()
        painter.resetTransform()
        painter.setPen(QPen(QColor(76, 86, 96), 1))
        painter.drawText(12, 20, f"Grid: {self.grid_spacing_label()}")
        painter.restore()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._did_initial_fit:
            return

        self._did_initial_fit = True
        self.reset_to_default_view()

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

    def default_view_rect(self) -> QRectF:
        width = mm_to_nm(DEFAULT_VIEW_WIDTH_MM)
        height = mm_to_nm(DEFAULT_VIEW_HEIGHT_MM)
        return QRectF(-width / 2, -height / 2, width, height)

    def reset_to_default_view(self) -> None:
        target = self.default_view_rect()
        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(target.center())

    def grid_unit(self) -> GridUnit:
        return self._grid_unit

    def set_grid_unit(self, unit: GridUnit) -> None:
        self._grid_unit = unit
        self.viewport().update()

    def grid_spacing_label(self) -> str:
        if self._grid_unit == "cm":
            return "0.254 cm"
        return "2.54 mm"

    def fit_to_contents(self) -> None:
        scene = self.scene()
        target = scene.itemsBoundingRect()
        if not scene.items():
            target = self.default_view_rect()
        else:
            target = target.adjusted(-GRID_NM, -GRID_NM, GRID_NM, GRID_NM)

        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(target.center())


__all__ = [
    "DEFAULT_VIEW_HEIGHT_MM",
    "DEFAULT_VIEW_WIDTH_MM",
    "GRID_NM",
    "SchematicView",
    "ZOOM_IN_FACTOR",
    "ZOOM_OUT_FACTOR",
]
