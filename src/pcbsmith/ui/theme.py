from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

LIGHT_STYLESHEET = """
QMainWindow, QDialog {
    background: #f3f5f7;
    color: #17202a;
}
QMenuBar, QMenu, QToolBar, QDockWidget, QStatusBar {
    background: #eef1f5;
    color: #17202a;
}
QMenuBar::item:selected, QMenu::item:selected {
    background: #dce8f7;
}
QDockWidget::title {
    background: #eef1f5;
    color: #17202a;
    padding: 4px;
}
QLineEdit, QTextEdit, QListWidget, QToolBox, QToolBox::tab, QWidget {
    background: #ffffff;
    color: #17202a;
    selection-background-color: #cfe3fb;
    selection-color: #17202a;
}
QLineEdit, QTextEdit, QListWidget {
    border: 1px solid #cbd2d9;
    border-radius: 4px;
}
QToolButton, QPushButton {
    background: #ffffff;
    color: #17202a;
    border: 1px solid #cbd2d9;
    border-radius: 4px;
    padding: 4px 8px;
}
QToolButton:hover, QPushButton:hover {
    background: #e8f1fb;
    border-color: #8fb7e6;
}
QToolButton:pressed, QPushButton:pressed {
    background: #d2e6fb;
}
QCheckBox {
    color: #17202a;
    background: transparent;
}
"""

DARK_STYLESHEET = """
QMainWindow, QDialog, QDockWidget, QTextEdit, QListWidget, QToolBox {
    background: #1f1f1f;
    color: #f2f4f7;
}
QMenuBar, QMenu, QToolBar, QDockWidget::title {
    background: #191919;
    color: #f2f4f7;
}
QLineEdit, QTextEdit, QListWidget, QToolBox::tab {
    background: #2b2b2b;
    color: #f2f4f7;
    border: 1px solid #555555;
}
QToolButton, QPushButton {
    background: #333333;
    color: #f2f4f7;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 4px 8px;
}
QCheckBox {
    color: #f2f4f7;
    background: transparent;
}
"""


def apply_light_palette(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(243, 245, 247))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(23, 32, 42))
    palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(239, 242, 246))
    palette.setColor(QPalette.ColorRole.Text, QColor(23, 32, 42))
    palette.setColor(QPalette.ColorRole.Button, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(23, 32, 42))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(207, 227, 251))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(23, 32, 42))
    app.setPalette(palette)


def apply_window_theme(widget: QWidget, theme: str) -> None:
    if theme == "dark":
        widget.setProperty("pcbsTheme", "dark")
        widget.setStyleSheet(DARK_STYLESHEET)
        return

    widget.setProperty("pcbsTheme", "light")
    widget.setStyleSheet(LIGHT_STYLESHEET)
