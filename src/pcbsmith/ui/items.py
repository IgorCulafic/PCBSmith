from __future__ import annotations

from itertools import pairwise

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from pcbsmith.core.geom import Point
from pcbsmith.core.schematic import NetLabel, NoConnect, SymbolInstance, Wire
from pcbsmith.ui.selection import SelectionKey

SYMBOL_WIDTH = 6_000_000
SYMBOL_HEIGHT = 2_200_000
WIRE_BOUNDS_MARGIN = 250_000
CANVAS_BACKGROUND = QColor(248, 250, 252)
GRID_COLOR = QColor(221, 226, 232)
SYMBOL_TEXT_COLOR = QColor(17, 24, 39)
SYMBOL_PEN = QPen(QColor(24, 32, 42), 0)
WIRE_PEN = QPen(QColor(25, 96, 179), 0)
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
        self.setRotation(symbol.rotation_deg)
        self.setTransform(
            QTransform.fromScale(-1 if symbol.mirrored_x else 1, 1),
            combine=False,
        )
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )

        label = QGraphicsTextItem(f"{symbol.reference} {symbol.value}", self)
        label.setDefaultTextColor(SYMBOL_TEXT_COLOR)
        label.setScale(120_000)
        label.setPos(-SYMBOL_WIDTH / 2, -SYMBOL_HEIGHT)
        self._label = label

    def boundingRect(self) -> QRectF:
        return QRectF(
            -SYMBOL_WIDTH / 2,
            -SYMBOL_HEIGHT / 2,
            SYMBOL_WIDTH,
            SYMBOL_HEIGHT,
        )

    def selection_key(self) -> SelectionKey:
        return SelectionKey("symbol", self.symbol.reference)

    def is_mirrored_horizontally(self) -> bool:
        return self._mirrored_horizontally

    def set_mirrored_horizontally(self, mirrored: bool) -> None:
        self._mirrored_horizontally = mirrored
        self.setTransform(QTransform.fromScale(-1 if mirrored else 1, 1), combine=False)

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

        lead = SYMBOL_WIDTH / 4
        painter.drawLine(int(-SYMBOL_WIDTH / 2), 0, int(-lead), 0)
        painter.drawRect(
            int(-lead),
            int(-SYMBOL_HEIGHT / 2),
            int(lead * 2),
            SYMBOL_HEIGHT,
        )
        painter.drawLine(int(lead), 0, int(SYMBOL_WIDTH / 2), 0)
        handle_radius = 220_000
        painter.setPen(QPen(CONNECTION_HANDLE_COLOR, 0))
        painter.setBrush(CONNECTION_HANDLE_FILL)
        painter.drawEllipse(
            int(-SYMBOL_WIDTH / 2 - handle_radius / 2),
            int(-handle_radius / 2),
            handle_radius,
            handle_radius,
        )
        painter.drawEllipse(
            int(SYMBOL_WIDTH / 2 - handle_radius / 2),
            int(-handle_radius / 2),
            handle_radius,
            handle_radius,
        )
        painter.restore()


class WireItem(QGraphicsItem):
    def __init__(
        self,
        wire: Wire,
        index: int,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(parent)
        self.wire = wire
        self.index = index
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def segments(self) -> tuple[tuple[Point, Point], ...]:
        return tuple(pairwise(self.wire.points))

    def selection_key(self) -> SelectionKey:
        return SelectionKey("wire", str(self.index))

    def boundingRect(self) -> QRectF:
        xs = [point.x for point in self.wire.points]
        ys = [point.y for point in self.wire.points]
        left = min(xs) - WIRE_BOUNDS_MARGIN
        top = min(ys) - WIRE_BOUNDS_MARGIN
        right = max(xs) + WIRE_BOUNDS_MARGIN
        bottom = max(ys) + WIRE_BOUNDS_MARGIN
        return QRectF(left, top, right - left, bottom - top)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget

        painter.save()
        painter.setPen(WIRE_PEN)
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
        painter.setPen(QPen(QColor(152, 86, 18), 0))
        painter.drawLine(-half_size, -half_size, half_size, half_size)
        painter.drawLine(-half_size, half_size, half_size, -half_size)
        painter.restore()


__all__ = [
    "CANVAS_BACKGROUND",
    "CONNECTION_HANDLE_COLOR",
    "CONNECTION_HANDLE_FILL",
    "GRID_COLOR",
    "LABEL_TEXT_SCALE",
    "NO_CONNECT_SIZE",
    "NetLabelItem",
    "NoConnectItem",
    "SYMBOL_PEN",
    "SYMBOL_TEXT_COLOR",
    "SYMBOL_HEIGHT",
    "SYMBOL_WIDTH",
    "SymbolItem",
    "WIRE_BOUNDS_MARGIN",
    "WireItem",
]
