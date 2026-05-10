from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pcbsmith.ui.theme import apply_light_palette


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv if argv is None else argv)
    app.setStyle("Fusion")
    apply_light_palette(app)

    from pcbsmith.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    if owns_app:
        return app.exec()
    return 0
