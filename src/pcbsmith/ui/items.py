from __future__ import annotations

from itertools import pairwise

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from pcbsmith.core.geom import Point, transform_schematic_offset
from pcbsmith.core.schematic import Junction, NetLabel, NoConnect, SymbolInstance, Wire
from pcbsmith.knowledge.builtin_library import SYMBOLS
from pcbsmith.ui.icons import _draw_symbol_preview
from pcbsmith.ui.selection import SelectionKey

SYMBOL_WIDTH = 6_000_000
SYMBOL_HEIGHT = 2_200_000
WIRE_BOUNDS_MARGIN = 250_000
CONNECTION_HANDLE_RADIUS = 220_000
CANVAS_BACKGROUND = QColor(248, 250, 252)
GRID_COLOR = QColor(221, 226, 232)
SYMBOL_TEXT_COLOR = QColor(17, 24, 39)
SYMBOL_PEN = QPen(QColor(24, 32, 42), 0)
WIRE_COLOR = QColor(25, 96, 179)
WIRE_PEN = QPen(WIRE_COLOR, 4)
WIRE_PEN.setCosmetic(True)
CONNECTION_HANDLE_COLOR = QColor(27, 115, 209)
CONNECTION_HANDLE_FILL = QColor(255, 255, 255)
LABEL_TEXT_SCALE = 120_000
NO_CONNECT_SIZE = 1_200_000


class SymbolItem(QGraphicsItem):
    def __init__(self, symbol: SymbolInstance, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.symbol = symbol
        self._mirrored_horizontally = symbol.mirrored_x

        self.setPos(symbol.position.x, symbol.position.y)
        self._set_symbol_transform()
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )

        label = QGraphicsTextItem(f"{symbol.reference} {symbol.value}", self)
        label.setDefaultTextColor(SYMBOL_TEXT_COLOR)
        label.setScale(120_000)
        label.setPos(
            -SYMBOL_WIDTH / 2,
            self.boundingRect().top() - label.boundingRect().height() * label.scale() - 300_000,
        )
        self._label = label

    def boundingRect(self) -> QRectF:
        pin_positions = self.local_pin_positions()
        xs: list[float] = [point.x for point in pin_positions]
        ys: list[float] = [point.y for point in pin_positions]
        xs.extend((-SYMBOL_WIDTH / 2, SYMBOL_WIDTH / 2))
        ys.extend((-SYMBOL_HEIGHT / 2, SYMBOL_HEIGHT / 2))
        margin = CONNECTION_HANDLE_RADIUS
        left = min(xs) - margin
        top = min(ys) - margin
        right = max(xs) + margin
        bottom = max(ys) + margin
        return QRectF(
            left,
            top,
            right - left,
            bottom - top,
        )

    def selection_key(self) -> SelectionKey:
        return SelectionKey("symbol", self.symbol.reference)

    def local_pin_positions(self) -> tuple[Point, ...]:
        symbol = SYMBOLS.get(self.symbol.symbol_id)
        if symbol is None:
            return (
                Point(x=int(-SYMBOL_WIDTH / 2), y=0),
                Point(x=int(SYMBOL_WIDTH / 2), y=0),
            )
        return tuple(pin.position for pin in symbol.pins)

    def is_mirrored_horizontally(self) -> bool:
        return self._mirrored_horizontally

    def set_mirrored_horizontally(self, mirrored: bool) -> None:
        self._mirrored_horizontally = mirrored
        self._set_symbol_transform()

    def _set_symbol_transform(self) -> None:
        x = transform_schematic_offset(
            Point(x=1, y=0),
            self.symbol.rotation_deg,
            mirrored_x=self._mirrored_horizontally,
        )
        y = transform_schematic_offset(
            Point(x=0, y=1),
            self.symbol.rotation_deg,
            mirrored_x=self._mirrored_horizontally,
        )
        self.setTransform(QTransform(x.x, x.y, y.x, y.y, 0, 0), combine=False)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(SYMBOL_PEN)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        _draw_symbol_preview(painter, self.symbol.symbol_id, self.boundingRect())
        painter.setPen(QPen(CONNECTION_HANDLE_COLOR, 0))
        painter.setBrush(CONNECTION_HANDLE_FILL)
        for pin_position in self.local_pin_positions():
            painter.drawEllipse(
                int(pin_position.x - CONNECTION_HANDLE_RADIUS / 2),
                int(pin_position.y - CONNECTION_HANDLE_RADIUS / 2),
                CONNECTION_HANDLE_RADIUS,
                CONNECTION_HANDLE_RADIUS,
            )
        if self.isSelected():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(180, 55, 0), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(self.boundingRect())
        painter.restore()


class JunctionItem(QGraphicsEllipseItem):
    """A connectivity dot; loaded junctions remain visible without a new tool."""

    def __init__(self, junction: Junction) -> None:
        radius = 350_000
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.junction = junction
        self.setPos(junction.position.x, junction.position.y)
        self.setPen(QPen(WIRE_COLOR, 0))
        self.setBrush(WIRE_COLOR)
        self.setZValue(1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setToolTip("Electrical junction")


class WireItem(QGraphicsItem):
    def __init__(
        self,
        wire: Wire,
        index: int,
        stroke_width: int = 4,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self.wire = wire
        self.index = index
        self._stroke_width = stroke_width
        self._pick_scale = 4e-6
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def segments(self) -> tuple[tuple[Point, Point], ...]:
        return tuple(pairwise(self.wire.points))

    def selection_key(self) -> SelectionKey:
        return SelectionKey("wire", str(self.index))

    def stroke_width(self) -> int:
        return self._stroke_width

    def set_pick_scale(self, scale: float) -> None:
        if scale <= 0:
            raise ValueError("Wire pick scale must be positive")
        if self._pick_scale != scale:
            self.prepareGeometryChange()
            self._pick_scale = scale

    def set_stroke_width(self, width: int) -> None:
        self.prepareGeometryChange()
        self._stroke_width = width
        self.update()

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        first = self.wire.points[0]
        path.moveTo(first.x / 1e6, first.y / 1e6)
        for point in self.wire.points[1:]:
            path.lineTo(point.x / 1e6, point.y / 1e6)
        stroker = QPainterPathStroker()
        stroker.setWidth(max(8, self._stroke_width + 4) / (self._pick_scale * 1e6))
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return QTransform.fromScale(1e6, 1e6).map(stroker.createStroke(path))

    def contains(self, point: QPointF | QPoint | QPainterPath.Element) -> bool:
        # Compute in mm to avoid Qt path winding precision at nm magnitudes.
        if isinstance(point, QPainterPath.Element):
            px, py = point.x / 1e6, point.y / 1e6
        else:
            px, py = point.x() / 1e6, point.y() / 1e6
        radius = max(8, self._stroke_width + 4) / (2 * self._pick_scale * 1e6)
        for start, end in self.segments():
            ax, ay = start.x / 1e6, start.y / 1e6
            dx, dy = (end.x - start.x) / 1e6, (end.y - start.y) / 1e6
            length2 = dx * dx + dy * dy
            t = (
                0.0
                if length2 == 0
                else min(1.0, max(0.0, ((px - ax) * dx + (py - ay) * dy) / length2))
            )
            if (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2 <= radius**2:
                return True
        return False

    def boundingRect(self) -> QRectF:
        return self.shape().boundingRect()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget

        painter.save()
        pen = QPen(QColor(180, 55, 0) if self.isSelected() else WIRE_COLOR, self._stroke_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for start, end in self.segments():
            painter.drawLine(start.x, start.y, end.x, end.y)
        painter.restore()


class NetLabelItem(QGraphicsTextItem):
    def __init__(
        self,
        label: NetLabel,
        index: int,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(label.name, parent)
        self.label = label
        self.index = index

        self.setPos(label.position.x, label.position.y)
        self.setDefaultTextColor(QColor(152, 86, 18))
        self.setScale(LABEL_TEXT_SCALE)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )

    def selection_key(self) -> SelectionKey:
        return SelectionKey("label", str(self.index))


class NoConnectItem(QGraphicsItem):
    def __init__(
        self,
        no_connect: NoConnect,
        index: int,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self.no_connect = no_connect
        self.index = index

        self.setPos(no_connect.position.x, no_connect.position.y)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )

    def selection_key(self) -> SelectionKey:
        return SelectionKey("no_connect", str(self.index))

    def boundingRect(self) -> QRectF:
        half_size = NO_CONNECT_SIZE / 2
        return QRectF(-half_size, -half_size, NO_CONNECT_SIZE, NO_CONNECT_SIZE)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget

        half_size = int(NO_CONNECT_SIZE / 2)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(180, 55, 0) if self.isSelected() else QColor(152, 86, 18), 0))
        if self.isSelected():
            painter.drawRect(self.boundingRect())
        painter.drawLine(-half_size, -half_size, half_size, half_size)
        painter.drawLine(-half_size, half_size, half_size, -half_size)
        painter.restore()


__all__ = [
    "CANVAS_BACKGROUND",
    "CONNECTION_HANDLE_RADIUS",
    "CONNECTION_HANDLE_COLOR",
    "CONNECTION_HANDLE_FILL",
    "GRID_COLOR",
    "LABEL_TEXT_SCALE",
    "NO_CONNECT_SIZE",
    "NetLabelItem",
    "JunctionItem",
    "NoConnectItem",
    "SYMBOL_PEN",
    "SYMBOL_TEXT_COLOR",
    "SYMBOL_HEIGHT",
    "SYMBOL_WIDTH",
    "SymbolItem",
    "WIRE_BOUNDS_MARGIN",
    "WireItem",
]
