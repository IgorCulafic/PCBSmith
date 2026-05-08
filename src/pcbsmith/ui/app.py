from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv if argv is None else argv)

    from pcbsmith.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    if owns_app:
        return app.exec()
    return 0
