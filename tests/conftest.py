from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item):
    """Do not let pytest-qt teardown ask a human about intentionally dirty fixtures.

    This runs only after the test; actual close/open prompts remain testable.
    The wrapper runs before pytest-qt's teardown hook closes its widgets.
    """
    if "qtbot" in getattr(item, "fixturenames", ()):
        from PySide6.QtWidgets import QApplication

        from pcbsmith.ui.main_window import MainWindow

        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget._confirm_discard_changes = lambda: True
    return (yield)
