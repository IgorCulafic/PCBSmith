from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

INK = QColor(24, 32, 42)
BLUE = QColor(25, 96, 179)


def _base_icon(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(INK, max(2, size // 18))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return pixmap, painter


def _draw_line(painter: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def symbol_icon(symbol_id: str, size: int = 40) -> QIcon:
    pixmap, painter = _base_icon(size)
    rect = QRectF(size * 0.16, size * 0.16, size * 0.68, size * 0.68)
    _draw_symbol_preview(painter, symbol_id, rect)
    painter.end()
    return QIcon(pixmap)


def tool_icon(name: str, size: int = 22) -> QIcon:
    pixmap, painter = _base_icon(size)
    center = size / 2
    if name == "select":
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(size * 0.25, size * 0.18),
                    QPointF(size * 0.72, size * 0.52),
                    QPointF(size * 0.49, size * 0.58),
                    QPointF(size * 0.59, size * 0.82),
                    QPointF(size * 0.46, size * 0.87),
                    QPointF(size * 0.36, size * 0.63),
                    QPointF(size * 0.18, size * 0.78),
                ]
            )
        )
    elif name == "pan":
        painter.drawEllipse(QPointF(center, center), size * 0.26, size * 0.26)
        _draw_line(painter, center, size * 0.1, center, size * 0.9)
        _draw_line(painter, size * 0.1, center, size * 0.9, center)
    elif name == "wire":
        pen = painter.pen()
        pen.setColor(BLUE)
        pen.setWidth(max(3, size // 7))
        painter.setPen(pen)
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(size * 0.12, size * 0.75),
                    QPointF(size * 0.4, size * 0.48),
                    QPointF(size * 0.7, size * 0.48),
                    QPointF(size * 0.88, size * 0.25),
                ]
            )
        )
    elif name == "label":
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "T")
    elif name == "no_connect":
        _draw_line(painter, size * 0.25, size * 0.25, size * 0.75, size * 0.75)
        _draw_line(painter, size * 0.75, size * 0.25, size * 0.25, size * 0.75)
    elif name == "undo":
        painter.drawArc(
            QRectF(size * 0.22, size * 0.24, size * 0.56, size * 0.5), 30 * 16, 250 * 16
        )
        _draw_line(painter, size * 0.27, size * 0.38, size * 0.12, size * 0.38)
        _draw_line(painter, size * 0.27, size * 0.38, size * 0.23, size * 0.22)
    elif name == "redo":
        painter.drawArc(
            QRectF(size * 0.22, size * 0.24, size * 0.56, size * 0.5), -100 * 16, 250 * 16
        )
        _draw_line(painter, size * 0.73, size * 0.38, size * 0.88, size * 0.38)
        _draw_line(painter, size * 0.73, size * 0.38, size * 0.77, size * 0.22)
    elif name == "delete":
        painter.drawRect(QRectF(size * 0.3, size * 0.35, size * 0.4, size * 0.45))
        _draw_line(painter, size * 0.24, size * 0.3, size * 0.76, size * 0.3)
    elif name == "rotate":
        painter.drawArc(
            QRectF(size * 0.22, size * 0.22, size * 0.56, size * 0.56), 35 * 16, 285 * 16
        )
        _draw_line(painter, size * 0.72, size * 0.22, size * 0.88, size * 0.28)
        _draw_line(painter, size * 0.72, size * 0.22, size * 0.78, size * 0.38)
    elif name == "mirror":
        _draw_line(painter, center, size * 0.14, center, size * 0.86)
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(size * 0.42, size * 0.28),
                    QPointF(size * 0.2, center),
                    QPointF(size * 0.42, size * 0.72),
                ]
            )
        )
        painter.drawPolyline(
            QPolygonF(
                [
                    QPointF(size * 0.58, size * 0.28),
                    QPointF(size * 0.8, center),
                    QPointF(size * 0.58, size * 0.72),
                ]
            )
        )
    elif name == "fit":
        painter.drawRect(QRectF(size * 0.22, size * 0.22, size * 0.56, size * 0.56))
        _draw_line(painter, size * 0.22, size * 0.38, size * 0.38, size * 0.22)
        _draw_line(painter, size * 0.78, size * 0.62, size * 0.62, size * 0.78)
    elif name == "erc":
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "!")
    painter.end()
    return QIcon(pixmap)


def _draw_symbol_preview(painter: QPainter, symbol_id: str, rect: QRectF) -> None:
    y = rect.center().y()
    left = rect.left()
    right = rect.right()
    center = rect.center().x()
    painter.drawLine(QPointF(left, y), QPointF(left + rect.width() * 0.18, y))
    painter.drawLine(QPointF(right - rect.width() * 0.18, y), QPointF(right, y))

    if symbol_id == "stdlib:R":
        x0 = left + rect.width() * 0.18
        step = rect.width() * 0.64 / 6
        points = [QPointF(x0, y)]
        for index in range(1, 6):
            points.append(
                QPointF(
                    x0 + step * index,
                    y + (-1 if index % 2 else 1) * rect.height() * 0.22,
                )
            )
        points.append(QPointF(right - rect.width() * 0.18, y))
        painter.drawPolyline(QPolygonF(points))
    elif symbol_id == "stdlib:C":
        x1 = center - rect.width() * 0.08
        x2 = center + rect.width() * 0.08
        painter.drawLine(QPointF(x1, rect.top()), QPointF(x1, rect.bottom()))
        painter.drawLine(QPointF(x2, rect.top()), QPointF(x2, rect.bottom()))
    elif symbol_id in {"stdlib:D", "stdlib:LED"}:
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(center - rect.width() * 0.2, rect.top()),
                    QPointF(center - rect.width() * 0.2, rect.bottom()),
                    QPointF(center + rect.width() * 0.16, y),
                ]
            )
        )
        painter.drawLine(
            QPointF(center + rect.width() * 0.22, rect.top()),
            QPointF(center + rect.width() * 0.22, rect.bottom()),
        )
        if symbol_id == "stdlib:LED":
            painter.drawLine(
                QPointF(center + rect.width() * 0.22, rect.top()),
                QPointF(right, rect.top() - rect.height() * 0.2),
            )
            painter.drawLine(
                QPointF(center + rect.width() * 0.34, rect.top() + rect.height() * 0.18),
                QPointF(right, rect.top()),
            )
    elif symbol_id in {"stdlib:SW_PUSH", "stdlib:SW_SPST"}:
        painter.drawEllipse(
            QPointF(left + rect.width() * 0.2, y), rect.width() * 0.07, rect.width() * 0.07
        )
        painter.drawEllipse(
            QPointF(right - rect.width() * 0.2, y), rect.width() * 0.07, rect.width() * 0.07
        )
        painter.drawLine(
            QPointF(left + rect.width() * 0.28, y - rect.height() * 0.08),
            QPointF(right - rect.width() * 0.28, y - rect.height() * 0.25),
        )
    elif symbol_id == "stdlib:CONN_01X02":
        painter.drawEllipse(
            QPointF(center, y - rect.height() * 0.18), rect.width() * 0.11, rect.width() * 0.11
        )
        painter.drawEllipse(
            QPointF(center, y + rect.height() * 0.18), rect.width() * 0.11, rect.width() * 0.11
        )
    elif symbol_id == "stdlib:VCC":
        painter.drawLine(QPointF(center, rect.bottom()), QPointF(center, rect.top()))
        painter.drawLine(
            QPointF(center, rect.top()),
            QPointF(center - rect.width() * 0.16, rect.top() + rect.height() * 0.2),
        )
        painter.drawLine(
            QPointF(center, rect.top()),
            QPointF(center + rect.width() * 0.16, rect.top() + rect.height() * 0.2),
        )
    elif symbol_id == "stdlib:GND":
        painter.drawLine(
            QPointF(center, rect.top()), QPointF(center, rect.bottom() - rect.height() * 0.28)
        )
        painter.drawLine(
            QPointF(center - rect.width() * 0.24, rect.bottom() - rect.height() * 0.28),
            QPointF(center + rect.width() * 0.24, rect.bottom() - rect.height() * 0.28),
        )
        painter.drawLine(
            QPointF(center - rect.width() * 0.16, rect.bottom() - rect.height() * 0.14),
            QPointF(center + rect.width() * 0.16, rect.bottom() - rect.height() * 0.14),
        )
        painter.drawLine(
            QPointF(center - rect.width() * 0.08, rect.bottom()),
            QPointF(center + rect.width() * 0.08, rect.bottom()),
        )
    else:
        painter.drawRect(
            QRectF(center - rect.width() * 0.18, rect.top(), rect.width() * 0.36, rect.height())
        )
