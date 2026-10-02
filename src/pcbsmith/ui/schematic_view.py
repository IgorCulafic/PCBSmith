from __future__ import annotations

import math
from typing import Literal

from PySide6.QtCore import QLineF, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QShowEvent, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from pcbsmith.core.geom import mm_to_nm
from pcbsmith.ui.items import CANVAS_BACKGROUND, GRID_COLOR

GRID_NM = 2_540_000
DEFAULT_VIEW_WIDTH_MM = 160
DEFAULT_VIEW_HEIGHT_MM = 100
MIN_VIEW_SCALE = 1e-7
MAX_VIEW_SCALE = 2e-4
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
        self._pan_mode = False
        self.setAccessibleName("Schematic canvas")
        scene.setBackgroundBrush(CANVAS_BACKGROUND)

        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        super().drawBackground(painter, rect)
        rect_f = QRectF(rect)

        step = self.display_grid_spacing(rect_f)
        left = math.floor(rect_f.left() / step) * step
        top = math.floor(rect_f.top() / step) * step
        painter.save()
        painter.setPen(QPen(GRID_COLOR, 0))
        x = left
        while x <= rect_f.right():
            painter.drawLine(QLineF(x, rect_f.top(), x, rect_f.bottom()))
            x += step
        y = top
        while y <= rect_f.bottom():
            painter.drawLine(QLineF(rect_f.left(), y, rect_f.right(), y))
            y += step
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF | QRect) -> None:
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
            self.zoom_by(factor)
            event.accept()
            return

        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton or (
            self._pan_mode and event.button() == Qt.MouseButton.LeftButton
        ):
            self._last_pan_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
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
        if (
            event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton)
            and self._last_pan_pos is not None
        ):
            self._last_pan_pos = None
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if self._pan_mode else Qt.CursorShape.ArrowCursor
            )
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def set_pan_mode(self, enabled: bool) -> None:
        self._pan_mode = enabled
        self._last_pan_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    def display_grid_spacing(self, rect: QRectF) -> int:
        scale = max(abs(self.transform().m11()), MIN_VIEW_SCALE)
        multiple = max(
            1,
            math.ceil(8 / (GRID_NM * scale)),
            math.ceil((abs(rect.width()) + abs(rect.height())) / (GRID_NM * 400)),
        )
        return GRID_NM * multiple

    def zoom_by(self, factor: float) -> None:
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be finite and positive")
        current = abs(self.transform().m11())
        target = min(MAX_VIEW_SCALE, max(MIN_VIEW_SCALE, current * factor))
        self.scale(target / current, target / current)
        self._sync_pick_scale()

    def _sync_pick_scale(self) -> None:
        update = getattr(self.scene(), "set_wire_pick_scale", None)
        if callable(update):
            update(abs(self.transform().m11()))
        self.viewport().update()

    def default_view_rect(self) -> QRectF:
        width = mm_to_nm(DEFAULT_VIEW_WIDTH_MM)
        height = mm_to_nm(DEFAULT_VIEW_HEIGHT_MM)
        return QRectF(-width / 2, -height / 2, width, height)

    def reset_to_default_view(self) -> None:
        target = self.default_view_rect()
        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_by(1)
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
        self.zoom_by(1)
        self.centerOn(target.center())


__all__ = [
    "DEFAULT_VIEW_HEIGHT_MM",
    "DEFAULT_VIEW_WIDTH_MM",
    "GRID_NM",
    "SchematicView",
    "ZOOM_IN_FACTOR",
    "ZOOM_OUT_FACTOR",
]
