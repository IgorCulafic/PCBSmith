from __future__ import annotations


def test_gui_entrypoint_imports() -> None:
    from pcbsmith.ui.app import main

    assert callable(main)
