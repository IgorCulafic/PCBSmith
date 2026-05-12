from __future__ import annotations

import sys
from typing import cast

from PySide6.QtWidgets import QApplication

from pcbsmith.ui.theme import apply_light_palette


def main(argv: list[str] | None = None) -> int:
    instance = QApplication.instance()
    owns_app = instance is None
    if instance is None:
        app = QApplication(sys.argv if argv is None else argv)
    else:
        app = cast(QApplication, instance)
    app.setStyle("Fusion")
    apply_light_palette(app)

    from pcbsmith.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    if owns_app:
        return app.exec()
    return 0
