from __future__ import annotations

import importlib


def test_architecture_packages_are_available() -> None:
    for package in (
        "pcbsmith.ai",
        "pcbsmith.generators",
        "pcbsmith.kicad",
        "pcbsmith.knowledge",
        "pcbsmith.operations",
        "pcbsmith.reporting",
        "pcbsmith.rules",
    ):
        assert importlib.import_module(package)


def test_representative_modules_live_in_their_architecture_packages() -> None:
    module_names = (
        "pcbsmith.ai.ai_planner_package",
        "pcbsmith.generators.led_art_board",
        "pcbsmith.kicad.kicad_export",
        "pcbsmith.knowledge.component_selection",
        "pcbsmith.operations.design_operations",
        "pcbsmith.reporting.validation_report",
        "pcbsmith.rules.board_manufacturability",
    )

    for module_name in module_names:
        assert importlib.import_module(module_name)
